"""A server shared with other members

The list and button tests use an in-memory database (mongomock) and
fakediscord.py.
"""
import asyncio
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

try:
    import mongomock
except ImportError:  # pragma: no cover
    mongomock = None

import discord

import cogs.ReminderModule as rm
from cogs.ReminderCreation import ReminderCreation
import cogs.ReminderListing
from cogs.ReminderListing import ReminderListView
import lib.permissions
import lib.timeutil as timeutil
from lib.Connector import Connector
from lib.Reminder import Reminder, IntervalReminder
import util.reminderButtons as buttons
import util.reminderInteraction as ri
from unit_tests.fakediscord import FakeDiscord, OWNER, STRANGER

USER = 3
GUILD = 1
MODERATOR = 333
ROLE = 444
PICK_REMINDER = 'Select a reminder to edit'


def _member(user_id, guild_id=GUILD, moderator=False):
    """a member of a server, as Discord gives it with a command or a click"""
    member = MagicMock(spec=discord.Member)
    member.id = user_id
    member.mention = f'<@{user_id}>'
    member.display_name = f'Member {user_id}'
    member.guild = SimpleNamespace(id=guild_id, name='Test')
    member.guild_permissions = discord.Permissions(manage_messages=moderator)
    return member


def _not_found(code, message):
    return discord.NotFound(SimpleNamespace(status=404, reason='Not Found'), {'code': code, 'message': message})


class FindAuthorTest(unittest.IsolatedAsyncioTestCase):
    """the author of a server reminder, looked up when it is sent"""

    def guild(self, cached=None, fetched=None, error=None):
        return SimpleNamespace(get_member=lambda uid: cached if uid == USER else None,
                               fetch_member=AsyncMock(return_value=fetched, side_effect=error))

    async def test_member_in_the_cache(self):
        member = object()
        guild = self.guild(cached=member)
        self.assertIs(await rm.ReminderModule.find_author(guild, USER), member)
        guild.fetch_member.assert_not_awaited()

    async def test_member_asked_to_discord(self):
        member = object()
        self.assertIs(await rm.ReminderModule.find_author(self.guild(fetched=member), USER), member)

    async def test_author_left(self):
        guild = self.guild(error=_not_found(10007, 'Unknown Member'))
        with self.assertRaises(rm.AuthorLeft):
            await rm.ReminderModule.find_author(guild, USER)

    async def test_other_answers_are_unknown(self):
        # sent, without @everyone and role pings
        for error in (_not_found(10004, 'Unknown Guild'),
                      discord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'), 'Missing Access')):
            self.assertIsNone(await rm.ReminderModule.find_author(self.guild(error=error), USER), error)

    async def test_discord_down(self):
        # the reminder is kept and tried again
        error = discord.DiscordServerError(SimpleNamespace(status=503, reason='Service Unavailable'), 'down')
        with self.assertRaises(discord.DiscordServerError):
            await rm.ReminderModule.find_author(self.guild(error=error), USER)


class RemindPermissionTest(unittest.TestCase):
    """/remind pings others: moderators only, unless the server opens it
       (Server Settings > Integrations)
    """

    def test_remind_needs_manage_messages(self):
        self.assertEqual(ReminderCreation.remind_user.default_member_permissions,
                         discord.Permissions(manage_messages=True))

    def test_remindme_is_open_to_all(self):
        self.assertIsNone(ReminderCreation.remindme.default_member_permissions)


class DeleteRightsTest(unittest.TestCase):
    """who may delete a reminder (its author can also edit it)"""

    def can(self, user, target=STRANGER, g_id=GUILD, msg='x', title=None):
        rem = Reminder({'msg': msg, 'title': title, 'g_id': str(g_id) if g_id else None,
                        'author': str(OWNER), 'target': str(target)})
        return lib.permissions.can_delete_reminder(rem, user)

    def test_members_it_mentions(self):
        self.assertTrue(self.can(_member(USER), msg=f'standup with <@{USER}>'))
        self.assertTrue(self.can(_member(USER), msg=f'standup with <@!{USER}>'))
        self.assertTrue(self.can(_member(USER), title=f'<@{USER}> call'))
        # a role is not a member, another id is not this one
        self.assertFalse(self.can(_member(USER), msg=f'standup <@&{USER}>'))
        self.assertFalse(self.can(_member(USER), msg=f'standup <@{USER}0>'))

    def test_mentioned_in_a_role_reminder(self):
        # a moderator's reminder for a role or @everyone isn't stopped by a member it names
        rem = Reminder({'msg': f'meeting, <@{USER}> presents', 'g_id': str(GUILD), 'author': str(OWNER),
                        'target': str(ROLE), 'target_mention': f'<@&{ROLE}>'})
        self.assertFalse(lib.permissions.can_delete_reminder(rem, _member(USER)))
        rem.target_mention = '@everyone'
        self.assertFalse(lib.permissions.can_delete_reminder(rem, _member(USER)))

    def test_author_and_the_member_it_is_for(self):
        self.assertTrue(self.can(_member(OWNER)))
        self.assertTrue(self.can(_member(STRANGER)))

    def test_other_members(self):
        self.assertFalse(self.can(_member(USER)))
        # a member of the role it pings is not "the member it is for"
        self.assertFalse(self.can(_member(USER), target=ROLE))

    def test_moderators_of_its_server(self):
        self.assertTrue(self.can(_member(MODERATOR, moderator=True)))
        self.assertFalse(self.can(_member(MODERATOR, guild_id=99, moderator=True)))

    def test_private_reminder(self):
        self.assertFalse(self.can(_member(MODERATOR, moderator=True), target=OWNER, g_id=None))


@unittest.skipUnless(mongomock, 'needs mongomock')
class SharedListTest(unittest.IsolatedAsyncioTestCase):
    """/reminder_list on a server: 'For me', and 'Whole server' for moderators"""

    def setUp(self):
        Connector.db = mongomock.MongoClient().reminderBot
        Connector.set_timezone(GUILD, 'Europe/Paris')
        self.discord = FakeDiscord()
        # the owner is in the bot's cache, the stranger is asked to Discord, others left;
        # channel 2 is public, 3 private (the moderators')
        channels = {2: SimpleNamespace(permissions_for=lambda m: SimpleNamespace(view_channel=True)),
                    3: SimpleNamespace(permissions_for=lambda m: SimpleNamespace(view_channel=False))}
        self.guild = SimpleNamespace(
            id=GUILD, name='Test',
            get_member=lambda uid: SimpleNamespace(display_name='Owner Name') if uid == OWNER else None,
            fetch_member=AsyncMock(side_effect=self.fetch_member),
            get_channel_or_thread=channels.get)

    async def fetch_member(self, user_id):
        if user_id == STRANGER:
            return SimpleNamespace(display_name='Stranger*')
        raise _not_found(10007, 'Unknown Member')

    def add(self, msg, author, target, days=2, channel=2):
        mention = f'<@&{target}>' if target == ROLE else f'<@{target}>'
        rem = Reminder({'msg': msg, 'g_id': str(GUILD), 'ch_id': str(channel), 'ch_name': 'general',
                        'author': str(author), 'target': str(target), 'target_mention': mention})
        rem.created_at = timeutil.utcnow()
        rem.at = timeutil.utcnow().replace(second=0, microsecond=0) + timedelta(days=days)
        rem._id = Connector.add_reminder(rem)
        return rem

    async def open_list(self, user):
        ctx = SimpleNamespace(author=user, guild=self.guild, bot=None)
        stm = ri.STM(ctx, Connector.Scope(is_private=False, guild_id=GUILD, user_id=user.id))
        stm.tz_str = 'Europe/Paris'
        view = ReminderListView(stm)
        return await self.discord.respond(view, embed=view.get_embed(), user_id=user.id, deferred=True)

    @staticmethod
    def dropdown(msg):
        selects = [item for item in msg.view.children if isinstance(item, discord.ui.Select)]
        return selects[0].options if selects else []

    def listed(self, msg):
        return [option.label for option in self.dropdown(msg)]

    def authors(self, msg):
        # each dropdown entry starts with its author
        return [option.description.split(' · ')[0] for option in self.dropdown(msg)]

    async def test_for_me_lists_the_reminders_that_mention_me(self):
        self.add(f'call <@{STRANGER}> about it', author=OWNER, target=OWNER)
        self.add(f'call <@!{STRANGER}> again', author=OWNER, target=OWNER, days=3)
        self.add(f'not me <@{USER}>', author=OWNER, target=OWNER, days=4)
        self.add(f'my own note <@{STRANGER}>', author=STRANGER, target=STRANGER, days=5)
        # not: a reminder for a role that names them, one in a channel they can't read
        self.add(f'team meeting, <@{STRANGER}> presents', author=OWNER, target=ROLE, days=6)
        self.add(f'check <@{STRANGER}>\'s warnings', author=OWNER, target=OWNER, days=7, channel=3)
        msg = await self.open_list(_member(STRANGER))
        await self.discord.click(msg, 'For me', user_id=STRANGER)
        self.assertEqual(self.listed(msg), [f'call <@{STRANGER}> about it', f'call <@!{STRANGER}> again'])

    async def test_for_me_keeps_the_reminders_for_me_in_any_channel(self):
        # reminders for them (/remind @them) are theirs, wherever they were written
        self.add('for you, from the mods channel', author=OWNER, target=STRANGER, channel=3)
        msg = await self.open_list(_member(STRANGER))
        await self.discord.click(msg, 'For me', user_id=STRANGER)
        self.assertEqual(self.listed(msg), ['for you, from the mods channel'])

    async def test_author_told_when_someone_else_deletes(self):
        self.add(f'call <@{STRANGER}>', author=OWNER, target=OWNER)
        msg = await self.open_list(_member(STRANGER))
        await self.discord.click(msg, 'For me', user_id=STRANGER)
        await self.discord.choose(msg, PICK_REMINDER, '0', user_id=STRANGER)
        with self.assertLogs('Remindme.Listing', 'INFO'):
            await self.discord.click(msg, 'Delete', user_id=STRANGER)
            await self.discord.click(msg, 'Confirm', user_id=STRANGER)
        self.assertEqual(Connector.db.reminders.count_documents({}), 0)
        [dm] = self.discord.dms
        self.assertEqual(dm.user_id, OWNER)
        self.assertEqual(dm.embed.title, 'Your reminder was deleted')
        self.assertIn(f'Deleted by <@{STRANGER}>', dm.embed.description)
        self.assertIn('(#general on Test)', dm.embed.description)

    async def test_author_told_once_with_two_menus(self):
        # the second menu deletes nothing: no second DM
        self.add(f'call <@{STRANGER}>', author=OWNER, target=OWNER)
        menus = []
        for _ in range(2):
            msg = await self.open_list(_member(STRANGER))
            await self.discord.click(msg, 'For me', user_id=STRANGER)
            await self.discord.choose(msg, PICK_REMINDER, '0', user_id=STRANGER)
            menus.append(msg)
        with self.assertLogs('Remindme.Listing', 'INFO'):
            for msg in menus:
                await self.discord.click(msg, 'Delete', user_id=STRANGER)
                await self.discord.click(msg, 'Confirm', user_id=STRANGER)
        self.assertEqual(len(self.discord.dms), 1)

    async def test_author_not_told_of_their_own_delete(self):
        self.add('mine', author=OWNER, target=OWNER)
        msg = await self.open_list(_member(OWNER))
        await self.discord.choose(msg, PICK_REMINDER, '0')
        await self.discord.click(msg, 'Delete')
        await self.discord.click(msg, 'Confirm')
        self.assertEqual(Connector.db.reminders.count_documents({}), 0)
        self.assertEqual(self.discord.dms, [])

    async def test_the_member_it_is_for_can_delete_it(self):
        self.add('from the owner', author=OWNER, target=STRANGER)
        self.add('for a role', author=OWNER, target=ROLE)
        self.add('their own', author=STRANGER, target=STRANGER, days=3)
        msg = await self.open_list(_member(STRANGER))
        self.assertEqual(self.listed(msg), ['their own'])

        await self.discord.click(msg, 'For me', user_id=STRANGER)
        self.assertEqual(msg.title, 'Reminders for you · Test')
        self.assertEqual(self.listed(msg), ['from the owner'])
        # by name: a mention only shows one when the viewer's Discord knows the member
        self.assertIn('· from Owner Name', msg.embed.description)
        self.assertEqual(self.authors(msg), ['from Owner Name'])

        # delete only: it isn't theirs to edit
        await self.discord.choose(msg, PICK_REMINDER, '0', user_id=STRANGER)
        view = msg.view
        self.assertIsInstance(view, ri.ReminderEditView)
        for button in (view.edit_channel, view.set_interval, view.edit_reminder_btn, view.pause_btn, view.skip_btn):
            self.assertTrue(button.disabled, button.label)
        with self.assertLogs('Remindme.Listing', 'INFO'):
            await self.discord.click(msg, 'Delete', user_id=STRANGER)
            await self.discord.click(msg, 'Confirm', user_id=STRANGER)

        # back on 'For me', now empty
        self.assertIsInstance(msg.view, ReminderListView)
        self.assertEqual(self.listed(msg), [])
        self.assertIn('No reminders from other members', msg.embed.description)
        self.assertEqual(sorted(r['msg'] for r in Connector.db.reminders.find({})), ['for a role', 'their own'])

    async def test_moderators_see_the_whole_server(self):
        self.add('mine', author=MODERATOR, target=MODERATOR)
        self.add('from the owner', author=OWNER, target=OWNER, days=3)
        self.add('from someone', author=STRANGER, target=ROLE, days=4)
        msg = await self.open_list(_member(MODERATOR, moderator=True))

        await self.discord.click(msg, 'Whole server', user_id=MODERATOR)
        self.assertEqual(msg.title, 'All reminders · Test')
        self.assertEqual(self.listed(msg), ['mine', 'from the owner', 'from someone'])
        self.assertEqual(msg.button('Whole server').style, discord.ButtonStyle.primary)
        self.assertEqual(self.authors(msg), ['from you', 'from Owner Name', 'from Stranger*'])
        for author in ('from you', 'from Owner Name', 'from Stranger\\*'):
            self.assertIn(author, msg.embed.description)

        # their own reminder stays editable, the others can only be deleted
        await self.discord.choose(msg, PICK_REMINDER, '0', user_id=MODERATOR)
        self.assertFalse(msg.view.edit_reminder_btn.disabled)
        await self.discord.click(msg, 'Return', user_id=MODERATOR)
        await self.discord.choose(msg, PICK_REMINDER, '2', user_id=MODERATOR)
        self.assertTrue(msg.view.edit_reminder_btn.disabled)
        with self.assertLogs('Remindme.Listing', 'INFO'):
            await self.discord.click(msg, 'Delete', user_id=MODERATOR)
            await self.discord.click(msg, 'Confirm', user_id=MODERATOR)
        self.assertEqual(self.listed(msg), ['mine', 'from the owner'])

        await self.discord.click(msg, 'My reminders', user_id=MODERATOR)
        self.assertEqual(self.listed(msg), ['mine'])

    async def test_former_member(self):
        self.add('left behind', author=USER, target=USER)
        msg = await self.open_list(_member(MODERATOR, moderator=True))
        await self.discord.click(msg, 'Whole server', user_id=MODERATOR)
        self.assertEqual(self.authors(msg), ['from a former member'])
        self.assertIn('from a former member', msg.embed.description)

    async def test_member_it_is_for_by_name(self):
        rem = self.add('for the stranger', author=OWNER, target=STRANGER)
        Connector.db.reminders.update_one({'_id': rem._id}, {'$set': {'target_name': f'<@{STRANGER}>'}})
        msg = await self.open_list(_member(MODERATOR, moderator=True))
        await self.discord.click(msg, 'Whole server', user_id=MODERATOR)
        self.assertIn('· for Stranger\\* · from Owner Name', msg.embed.description)

    async def test_slow_name_lookup(self):
        # the click is still answered in time, with mentions instead of names
        async def slow(user_id):
            await asyncio.sleep(5)
        self.guild.fetch_member = AsyncMock(side_effect=slow)
        self.add('from someone', author=STRANGER, target=STRANGER)
        msg = await self.open_list(_member(MODERATOR, moderator=True))
        with patch.object(cogs.ReminderListing, 'NAME_LOOKUP_TIMEOUT', 0.05):
            inter = await self.discord.click(msg, 'Whole server', user_id=MODERATOR, must_answer=False)
            await asyncio.sleep(0.2)
            await self.discord.settle()
        self.assertTrue(inter.response.is_done())
        self.assertIn(f'from <@{STRANGER}>', msg.embed.description)
        self.assertEqual(self.authors(msg), ['from another member'])

    async def test_other_members_have_no_server_view(self):
        msg = await self.open_list(_member(STRANGER))
        self.assertEqual(msg.button('My reminders').style, discord.ButtonStyle.primary)
        with self.assertRaises(AssertionError):
            msg.button('Whole server')

    async def test_private_list_has_no_views(self):
        ctx = SimpleNamespace(author=SimpleNamespace(id=OWNER), guild=None, bot=None)
        stm = ri.STM(ctx, Connector.Scope(is_private=True, user_id=OWNER))
        stm.tz_str = 'UTC'
        view = ReminderListView(stm)
        self.assertEqual([item.label for item in view.children if getattr(item, 'label', None)], [])


@unittest.skipUnless(mongomock, 'needs mongomock')
class DeliveredDeleteTest(unittest.IsolatedAsyncioTestCase):
    """the 🗑️ under a delivered repeating reminder"""

    def setUp(self):
        Connector.db = mongomock.MongoClient().reminderBot
        Connector.set_timezone(GUILD, 'Europe/Paris')
        self.discord = FakeDiscord()

    def delivered(self, target, text='weekly'):
        mention = f'<@&{target}>' if target == ROLE else f'<@{target}>'
        rem = IntervalReminder({'msg': text, 'g_id': str(GUILD), 'ch_id': '2', 'ch_name': 'general',
                                'author': str(OWNER), 'target': str(target), 'target_mention': mention})
        rem.first_at = datetime(2026, 1, 2, 7, 0)
        rem.rrules = ['DTSTART:20260102T070000\nRRULE:FREQ=WEEKLY;BYDAY=FR']
        rem.at = rem.next_trigger(timeutil.utcnow(), tz_str='Europe/Paris')
        rem._id = Connector.add_interval(rem)
        msg = self.discord.new_message(ephemeral=False)
        msg.apply(view=buttons.delivered_view(rem))
        return rem, msg

    async def test_the_member_it_is_for(self):
        rem, msg = self.delivered(target=STRANGER)
        with self.assertLogs('Remindme.Buttons', 'INFO'):
            await self.discord.press(msg, emoji='🗑️', member=_member(STRANGER))
        self.assertIsNone(Connector.get_interval_by_id(rem._id))
        self.assertEqual(msg.embed.description, f'The reminder was deleted by <@{STRANGER}>')

    async def test_a_member_it_mentions(self):
        rem, msg = self.delivered(target=STRANGER, text=f'weekly with <@{USER}>')
        with self.assertLogs('Remindme.Buttons', 'INFO'):
            await self.discord.press(msg, emoji='🗑️', member=_member(USER))
        self.assertIsNone(Connector.get_interval_by_id(rem._id))
        [dm] = self.discord.dms
        self.assertEqual(dm.user_id, OWNER)
        self.assertIn(f'<@{USER}> (Member {USER})', dm.embed.description)
        self.assertIn('**weekly with', dm.embed.description)

    async def test_a_member_named_in_a_role_reminder(self):
        rem, msg = self.delivered(target=ROLE, text=f'weekly with <@{USER}>')
        await self.discord.press(msg, emoji='🗑️', member=_member(USER))
        self.assertIsNotNone(Connector.get_interval_by_id(rem._id))
        self.assertIn('moderator', self.discord.last_message().content)

    async def test_author_deleting_is_not_told(self):
        rem, msg = self.delivered(target=STRANGER)
        await self.discord.press(msg, emoji='🗑️', member=_member(OWNER))
        self.assertIsNone(Connector.get_interval_by_id(rem._id))
        self.assertEqual(self.discord.dms, [])

    async def test_author_with_closed_dms(self):
        rem, msg = self.delivered(target=STRANGER)
        self.discord.closed_dms.add(OWNER)
        with self.assertLogs('Remindme.Notices', 'INFO') as logs:
            await self.discord.press(msg, emoji='🗑️', member=_member(STRANGER))
        self.assertIsNone(Connector.get_interval_by_id(rem._id))
        self.assertIn('could not tell', '\n'.join(logs.output))
        self.assertEqual(msg.embed.title, 'Deleted Reminder')
        self.assertEqual(self.discord.dms, [])

    async def test_the_member_it_is_for_cannot_skip(self):
        rem, msg = self.delivered(target=STRANGER)
        await self.discord.press(msg, 'Skip next', member=_member(STRANGER))
        self.assertEqual(Connector.get_interval_by_id(rem._id).exdates, [])

    async def test_a_moderator(self):
        rem, msg = self.delivered(target=ROLE)
        with self.assertLogs('Remindme.Buttons', 'INFO'):
            await self.discord.press(msg, emoji='🗑️', member=_member(MODERATOR, moderator=True))
        self.assertIsNone(Connector.get_interval_by_id(rem._id))

    async def test_another_member(self):
        rem, msg = self.delivered(target=ROLE)
        await self.discord.press(msg, emoji='🗑️', member=_member(USER))
        self.assertIsNotNone(Connector.get_interval_by_id(rem._id))
        self.assertIn('moderator', self.discord.last_message().content)


if __name__ == '__main__':
    unittest.main()
