"""/remindme, /timezone and other checks, with an in-memory database (mongomock)

See fakediscord.py.
"""
import asyncio
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

try:
    import mongomock
except ImportError:  # pragma: no cover
    mongomock = None

import lib.timeutil as timeutil
import lib.ReminderRepeater
from lib.Connector import Connector
from lib.Reminder import Reminder, IntervalReminder
import util.interaction
from cogs.ReminderCreation import ReminderCreation, MAX_REMINDERS_PER_USER
from cogs.TimezoneModule import TimezoneModule
from unit_tests.fakediscord import FakeDiscord, OWNER, STRANGER

GUILD = 1


class FakeContext:
    """the ApplicationContext of a slash command in a server"""
    def __init__(self, world: FakeDiscord):
        self.world = world
        self.calls = []
        self.answers = []
        self.author = SimpleNamespace(id=OWNER, name='owner', display_name='owner', mention=f'<@{OWNER}>')
        self.guild = SimpleNamespace(id=GUILD, name='Test', default_role=object())
        self.channel_id = 2

        async def flatten():
            self.calls.append('history')
            return []
        self.channel = SimpleNamespace(id=2, name='general', history=lambda limit: SimpleNamespace(flatten=flatten))
        self.interaction = SimpleNamespace(
            guild_id=GUILD, authorizing_integration_owners=SimpleNamespace(guild_id=GUILD, user_id=None))

    async def defer(self, ephemeral=False):
        self.calls.append('defer')

    async def respond(self, content=None, embed=None, view=None, ephemeral=False, **_):
        self.calls.append('respond')
        self.answers.append(embed)
        if view is None:
            return None
        await self.world.respond(view, embed=embed, ephemeral=ephemeral)
        return view.origin


@unittest.skipUnless(mongomock, 'needs mongomock')
class CreationTest(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        Connector.db = mongomock.MongoClient().reminderBot
        Connector.set_timezone(GUILD, 'Europe/Paris')
        self.discord = FakeDiscord()
        self.ctx = FakeContext(self.discord)
        self.cog = ReminderCreation(client=None)

    async def remindme(self, time, message='hello'):
        await self.cog.process_reminder(self.ctx, self.ctx.author, self.ctx.author, time, message, channel=self.ctx.channel)

    async def test_one_shot_reminder(self):
        await self.remindme('in 2 days')
        self.assertEqual(Connector.db.reminders.count_documents({}), 1)
        self.assertEqual(self.ctx.answers[-1].title, 'New Reminder Created')

    async def test_hidden_reply_times_out(self):
        # hidden by default: its menu must still time out, or it stays in memory
        await self.remindme('in 2 days')
        view = self.discord.messages[-1].view
        self.assertIsNotNone(view.timeout)
        self.assertEqual(view.timeout, util.interaction.MENU_TIMEOUT)

    def test_time_is_limited(self):
        for command in (ReminderCreation.remindme, ReminderCreation.remind_user):
            [time] = [o for o in command.options if o.name == 'time']
            self.assertEqual(time.max_length, 100)

    async def test_discord_is_answered_before_the_history_is_read(self):
        await self.remindme('in 2 days')
        self.assertLess(self.ctx.calls.index('defer'), self.ctx.calls.index('history'))

    async def test_repeating_reminder_starts_on_the_minute(self):
        await self.remindme('every friday at 20:15')
        [stored] = Connector.db.intervals.find({})
        dtstart = stored['rrules'][0].splitlines()[0]
        self.assertTrue(dtstart.endswith('00'), dtstart)
        self.assertEqual(timeutil.utc_from_timestamp(stored['first_at']).second, 0)

    async def test_repetition_without_future_date(self):
        await self.remindme('every day until 1 jan 2020')
        self.assertEqual(self.ctx.answers[-1].title, 'Failed to create the reminder')
        self.assertIn('no date in the future', self.ctx.answers[-1].description)
        self.assertEqual(Connector.db.intervals.count_documents({}), 0)

    async def test_reminder_limit(self):
        for _ in range(MAX_REMINDERS_PER_USER):
            Connector.db.reminders.insert_one({'msg': 'x', 'author': str(OWNER), 'at': 0})
        await self.remindme('in 2 days')
        self.assertIn(str(MAX_REMINDERS_PER_USER), self.ctx.answers[-1].description)
        self.assertEqual(Connector.db.reminders.count_documents({}), MAX_REMINDERS_PER_USER)

    async def test_huge_duration(self):
        await self.remindme('999999999d')
        self.assertEqual(self.ctx.answers[-1].title, 'Failed to create the reminder')

    # ---------- /timezone ----------

    async def test_only_the_author_confirms_the_timezone(self):
        Connector.set_timezone(GUILD, 'UTC')
        task = asyncio.get_running_loop().create_task(
            TimezoneModule(client=None).set_timezone(self.ctx, GUILD, 'Europe/Paris'))
        await self.discord.settle()
        msg = self.discord.messages[0]

        await self.discord.click(msg, 'Confirm', user_id=STRANGER)
        self.assertEqual(Connector.get_timezone(GUILD), 'UTC')
        await self.discord.click(msg, 'Confirm')
        await task
        self.assertEqual(Connector.get_timezone(GUILD), 'Europe/Paris')

    # ---------- helpers ----------

    def add_interval(self, author=OWNER):
        rem = IntervalReminder({'msg': 'x', 'g_id': str(GUILD), 'ch_id': '2', 'author': str(author), 'target': str(STRANGER)})
        rem.first_at = datetime(2026, 1, 2, 7, 0)
        rem.rrules = ['DTSTART:20260102T070000\nRRULE:FREQ=WEEKLY;BYDAY=FR']
        rem.at = rem.next_trigger(timeutil.utcnow(), tz_str='Europe/Paris')
        rem._id = Connector.add_interval(rem)
        return rem

    # ---------- two menus on the same reminder ----------

    def test_rules_added_in_two_menus_are_kept(self):
        rem = self.add_interval()
        menu_a = Connector.get_interval_by_id(rem._id)
        menu_b = Connector.get_interval_by_id(rem._id)
        lib.ReminderRepeater.add_rules(menu_a, exdate=datetime(2026, 12, 4, 7, 0))
        lib.ReminderRepeater.add_rules(menu_b, exdate=datetime(2026, 12, 11, 7, 0))
        stored = Connector.get_interval_by_id(rem._id)
        self.assertEqual(stored.exdates, [datetime(2026, 12, 4, 7, 0), datetime(2026, 12, 11, 7, 0)])

    def test_plain_reminder_changed_in_another_menu(self):
        rem = Reminder({'msg': 'x', 'g_id': str(GUILD), 'ch_id': '2', 'author': str(OWNER), 'target': str(OWNER)})
        rem.created_at = timeutil.utcnow()
        rem.at = timeutil.utcnow() + timedelta(days=2)
        rem._id = Connector.add_reminder(rem)
        menu_a = Connector.get_reminder_by_id(rem._id)
        menu_b = Connector.get_reminder_by_id(rem._id)

        lib.ReminderRepeater.add_rules(menu_a, rrule='DTSTART:20260101T070000\nRRULE:FREQ=WEEKLY')
        with self.assertRaises(lib.ReminderRepeater.ReminderChanged):
            lib.ReminderRepeater.add_rules(menu_b, rrule='DTSTART:20260101T080000\nRRULE:FREQ=DAILY')
        self.assertEqual(Connector.db.intervals.count_documents({}), 1)

    def test_deleted_interval_is_not_brought_back(self):
        rem = self.add_interval()
        menu = Connector.get_interval_by_id(rem._id)
        Connector.delete_interval(rem._id)
        with self.assertRaises(lib.ReminderRepeater.ReminderChanged):
            lib.ReminderRepeater.rm_rules(menu, rule_idx=0)
        with self.assertRaises(lib.ReminderRepeater.ReminderChanged):
            lib.ReminderRepeater.add_rules(menu, exdate=datetime(2026, 12, 4, 7, 0))
        self.assertEqual(Connector.db.reminders.count_documents({}), 0)
        self.assertEqual(Connector.db.intervals.count_documents({}), 0)

    def test_rule_deleted_in_an_old_menu_is_the_right_one(self):
        rem = self.add_interval()
        lib.ReminderRepeater.add_rules(rem, exdate=datetime(2026, 12, 4, 7, 0))
        lib.ReminderRepeater.add_rules(rem, exdate=datetime(2026, 12, 11, 7, 0))
        menu_a = Connector.get_interval_by_id(rem._id)
        menu_b = Connector.get_interval_by_id(rem._id)

        # rules: 0 = the weekly rule, 1 = 4 Dec, 2 = 11 Dec
        lib.ReminderRepeater.rm_rules(menu_a, rule_idx=1)
        lib.ReminderRepeater.rm_rules(menu_b, rule_idx=2)  # still numbered as before
        stored = Connector.get_interval_by_id(rem._id)
        self.assertEqual(stored.exdates, [])
        self.assertEqual(len(stored.rrules), 1)


if __name__ == '__main__':
    unittest.main()
