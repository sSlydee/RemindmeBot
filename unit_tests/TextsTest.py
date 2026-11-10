"""The privacy note, /help, the settings in DMs and other texts members see

The tests use an in-memory database (mongomock) and fakediscord.py.
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
from dateutil import tz

from cogs.SettingsModule import SettingsView
from discord.ext.help.help import Help, HelpPage
import lib.input_parser
import lib.timeutil as timeutil
from lib.Connector import Connector
from lib.Reminder import Reminder, IntervalReminder
from util.consts import Consts
import util.privacy
import util.reminderButtons as buttons
import util.reminderInteraction as ri
from unit_tests.fakediscord import FakeDiscord, OWNER

GUILD = 1
ROLE = 444


class PrivacyTest(unittest.TestCase):

    def test_fits_in_one_message(self):
        self.assertLessEqual(len(util.privacy.PRIVACY_TEXT), 2000)

    def test_says_the_real_delays(self):
        text = util.privacy.PRIVACY_TEXT
        self.assertIn(f'then {buttons.DELIVERED_KEEP.days} days more', text)
        self.assertIn(f'deleted after {Consts.left_guild_keep.days} days', text)
        self.assertIn('backups are kept 14 days', text)


class HelpTest(unittest.IsolatedAsyncioTestCase):

    async def test_only_to_whoever_asked_without_invite(self):
        Help.is_cog_scope = True
        Help.add_page(HelpPage(name='overview', title='Help', description='commands'))
        Help.invite_permissions(None)
        Help.set_privacy_text(util.privacy.PRIVACY_TEXT)
        cog = Help.__new__(Help)
        cog.client = SimpleNamespace(user=SimpleNamespace(id=1))
        ctx = MagicMock(spec=discord.ApplicationContext)
        ctx.respond = AsyncMock()

        await cog.send_help_page(ctx, 'overview')
        kwargs = ctx.respond.call_args.kwargs
        self.assertTrue(kwargs['ephemeral'])
        labels = [item.label for item in kwargs['view'].children if hasattr(item, 'label')]
        self.assertNotIn('Invite Me', labels)
        self.assertIn('Privacy', labels)


@unittest.skipUnless(mongomock, 'needs mongomock')
class SettingsInDmTest(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        Connector.db = mongomock.MongoClient().reminderBot
        self.discord = FakeDiscord()

    async def test_own_style_only(self):
        view = SettingsView(Connector.Scope(is_private=True, guild_id=None, user_id=OWNER), SimpleNamespace(id=OWNER))
        self.assertIn('Your own settings', view.get_embed().description)
        for item in (view.del_timeout, view.del_never, view.del_hidden, view.deliver_channel, view.deliver_dm):
            self.assertTrue(item.disabled, item.label)
        self.assertFalse(view.style_text.disabled)

        msg = await self.discord.respond(view, embed=view.get_embed())
        await self.discord.click(msg, 'Text-Only Reminders')
        self.assertEqual(Connector.get_reminder_type(OWNER), Connector.ReminderType.TEXT_ONLY)
        # still only the style after the update
        self.assertTrue(view.del_never.disabled)
        self.assertTrue(view.deliver_dm.disabled)

    def test_creation_reply_shown_to_its_author_by_default(self):
        self.assertEqual(Connector.get_auto_delete(GUILD), Connector.AutoDelete.HIDE)


@unittest.skipUnless(mongomock, 'needs mongomock')
class SnoozeRoleTest(unittest.IsolatedAsyncioTestCase):
    """the author snoozes a reminder that pinged a role"""

    def setUp(self):
        Connector.db = mongomock.MongoClient().reminderBot
        Connector.set_timezone(GUILD, 'Europe/Paris')
        self.discord = FakeDiscord()

    def delivered(self, target, mention):
        rem = Reminder({'msg': 'meeting', 'g_id': str(GUILD), 'ch_id': '2', 'ch_name': 'general',
                        'author': str(OWNER), 'target': str(target), 'target_mention': mention})
        rem.created_at = timeutil.utcnow() - timedelta(days=1)
        rem.at = timeutil.utcnow() - timedelta(minutes=1)
        rem._id = Connector.add_reminder(rem)
        Connector.archive_delivered(rem)
        msg = self.discord.new_message(ephemeral=False)
        msg.apply(view=buttons.delivered_view(rem))
        return msg

    async def test_role_reminder_snoozed_for_its_author_only(self):
        msg = self.delivered(ROLE, f'<@&{ROLE}>')
        await self.discord.press(msg, '+10 min')
        [snoozed] = [Reminder(doc) for doc in Connector.db.reminders.find({})]
        self.assertEqual(snoozed.target, OWNER)
        self.assertEqual(snoozed.target_mention, f'<@{OWNER}>')
        self.assertEqual(snoozed.ch_id, 2)
        self.assertIn('only you', self.discord.last_message().content)

    async def test_member_reminder_unchanged(self):
        msg = self.delivered(OWNER, f'<@{OWNER}>')
        await self.discord.press(msg, '+10 min')
        [snoozed] = [Reminder(doc) for doc in Connector.db.reminders.find({})]
        self.assertEqual(snoozed.target_mention, f'<@{OWNER}>')
        self.assertNotIn('only you', self.discord.last_message().content)


class ReminderTextTest(unittest.IsolatedAsyncioTestCase):

    async def test_delivered_with_its_title(self):
        rem = Reminder({'msg': 'the long text', 'title': 'Dentist', 'author': '3', 'target': '3'})
        self.assertEqual((await rem.get_embed(client=None)).title, 'Dentist')
        rem.title = None
        self.assertEqual((await rem.get_embed(client=None)).title, 'Reminder')
        rem.title = 'x' * 300
        self.assertEqual(len((await rem.get_embed(client=None)).title), 256)

    def test_rule_labels(self):
        rem = IntervalReminder({'msg': 'x', 'author': '3', 'target': '3'})
        rem.rrules = ['DTSTART:20261113T070000\nRRULE:FREQ=WEEKLY']
        rem.exrules = ['DTSTART:20261113T070000\nRRULE:FREQ=MONTHLY']
        rem.rdates = [datetime(2026, 12, 1, 9)]
        rem.exdates = [datetime(2026, 12, 4, 7)]
        self.assertEqual([r['label'] for r in rem.get_rule_dicts()],
                         ['Repeating rule', 'Exception rule', 'Single date', 'Exception date'])

    async def test_edit_date_written_like_a_user(self):
        rem = Reminder({'msg': 'x', 'author': '3', 'target': '3'})
        rem.at = datetime(2026, 11, 13, 17, 30)  # 18:30 in Paris
        modal = ri.EditModal(reminder=rem, tz_str='Europe/Paris', custom_callback=None, title='Edit')
        self.assertEqual(modal.prefilled_at, '13 Nov 2026 18:30')
        # changed by hand, it reads back
        at, _ = lib.input_parser.parse('14 Nov 2026 18:30', datetime(2026, 11, 10, 12), 'Europe/Paris')
        self.assertEqual(at, datetime(2026, 11, 14, 18, 30, tzinfo=tz.gettz('Europe/Paris'))
                         .astimezone(tz.UTC).replace(tzinfo=None))


if __name__ == '__main__':
    unittest.main()
