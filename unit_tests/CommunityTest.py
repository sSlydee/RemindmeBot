"""A server shared with other members

The list and button tests use an in-memory database (mongomock) and
fakediscord.py.
"""
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

try:
    import mongomock
except ImportError:  # pragma: no cover
    mongomock = None

import discord

import cogs.ReminderModule as rm
from cogs.ReminderCreation import ReminderCreation
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

    def can(self, user, target=STRANGER, g_id=GUILD):
        rem = Reminder({'msg': 'x', 'g_id': str(g_id) if g_id else None,
                        'author': str(OWNER), 'target': str(target)})
        return lib.permissions.can_delete_reminder(rem, user)

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

    def add(self, msg, author, target, days=2):
        rem = Reminder({'msg': msg, 'g_id': str(GUILD), 'ch_id': '2', 'ch_name': 'general',
                        'author': str(author), 'target': str(target)})
        rem.created_at = timeutil.utcnow()
        rem.at = timeutil.utcnow().replace(second=0, microsecond=0) + timedelta(days=days)
        rem._id = Connector.add_reminder(rem)
        return rem

    async def open_list(self, user):
        ctx = SimpleNamespace(author=user, guild=SimpleNamespace(id=GUILD, name='Test'), bot=None)
        stm = ri.STM(ctx, Connector.Scope(is_private=False, guild_id=GUILD, user_id=user.id))
        stm.tz_str = 'Europe/Paris'
        view = ReminderListView(stm)
        return await self.discord.respond(view, embed=view.get_embed(), user_id=user.id, deferred=True)

    @staticmethod
    def listed(msg):
        selects = [item for item in msg.view.children if isinstance(item, discord.ui.Select)]
        return [option.label for option in selects[0].options] if selects else []

    async def test_the_member_it_is_for_can_delete_it(self):
        self.add('from the owner', author=OWNER, target=STRANGER)
        self.add('for a role', author=OWNER, target=ROLE)
        self.add('their own', author=STRANGER, target=STRANGER, days=3)
        msg = await self.open_list(_member(STRANGER))
        self.assertEqual(self.listed(msg), ['their own'])

        await self.discord.click(msg, 'For me', user_id=STRANGER)
        self.assertEqual(msg.title, 'Reminders for you · Test')
        self.assertEqual(self.listed(msg), ['from the owner'])
        self.assertIn(f'from <@{OWNER}>', msg.embed.description)

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

    def delivered(self, target):
        rem = IntervalReminder({'msg': 'weekly', 'g_id': str(GUILD), 'ch_id': '2',
                                'author': str(OWNER), 'target': str(target)})
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
