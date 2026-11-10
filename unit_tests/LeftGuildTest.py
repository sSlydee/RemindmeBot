"""A server that removes the bot: its data is kept 7 days, its reminders wait

The tests use an in-memory database (mongomock).
"""
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

try:
    import mongomock
except ImportError:  # pragma: no cover
    mongomock = None

import cogs.ReminderModule as rm
import lib.timeutil as timeutil
from lib.Connector import Connector
from lib.Reminder import Reminder, IntervalReminder
from util.consts import Consts

LEFT = 1      # the server that removed the bot
OTHER = 2     # another server
USER = 3


@unittest.skipUnless(mongomock, 'needs mongomock')
class LeftGuildTest(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        Connector.db = mongomock.MongoClient().reminderBot
        for guild in (LEFT, OTHER):
            Connector.set_timezone(guild, 'Europe/Paris')
        self.now = timeutil.utcnow()

    def add(self, msg, guild, interval=False):
        data = {'msg': msg, 'g_id': str(guild) if guild else None, 'ch_id': '9' if guild else None,
                'author': str(USER), 'target': str(USER)}
        if interval:
            rem = IntervalReminder(data)
            rem.first_at = self.now - timedelta(days=30)
            rem.rrules = ['DTSTART:20260101T070000\nRRULE:FREQ=DAILY']
        else:
            rem = Reminder(data)
        rem.created_at = self.now - timedelta(days=3)
        rem.at = self.now - timedelta(minutes=1)
        if interval:
            rem._id = Connector.add_interval(rem)
        else:
            rem._id = Connector.add_reminder(rem)
        return rem

    def due(self):
        ts = timeutil.utc_timestamp(self.now)
        return sorted(r.msg for r in Connector.get_elapsed_reminders(ts) + Connector.get_pending_intervals(ts))

    def test_reminders_wait_while_the_bot_is_out(self):
        self.add('left server', LEFT)
        self.add('left server, repeating', LEFT, interval=True)
        self.add('other server', OTHER)
        self.add('private', None)
        self.assertEqual(Connector.guild_left(LEFT, self.now), 2)
        self.assertEqual(self.due(), ['other server', 'private'])
        # nothing is deleted
        self.assertEqual(Connector.db.reminders.count_documents({'g_id': str(LEFT)}), 1)
        self.assertEqual(Connector.db.intervals.count_documents({'g_id': str(LEFT)}), 1)
        self.assertEqual(Connector.get_timezone(LEFT), 'Europe/Paris')

    def test_back_within_the_week(self):
        self.add('left server', LEFT)
        Connector.guild_left(LEFT, self.now)
        self.assertTrue(Connector.guild_back(LEFT))
        self.assertEqual(self.due(), ['left server'])
        # only once, and not for a server that never left
        self.assertFalse(Connector.guild_back(LEFT))
        self.assertFalse(Connector.guild_back(OTHER))
        self.assertIsNone(Connector.db.settings.find_one({'g_id': '99'}))
        self.assertFalse(Connector.guild_back(99))
        self.assertIsNone(Connector.db.settings.find_one({'g_id': '99'}))

    def test_purged_after_the_week(self):
        self.add('left long ago', LEFT)
        self.add('left recently', OTHER, interval=True)
        Connector.db.delivered.insert_one({'g_id': str(LEFT), 'msg': 'sent'})
        Connector.guild_left(LEFT, self.now - timedelta(days=8))
        Connector.guild_left(OTHER, self.now - timedelta(days=2))

        purged = Connector.purge_left_guilds(self.now - Consts.left_guild_keep)
        self.assertEqual(purged, [(str(LEFT), 1, 0)])
        self.assertEqual(Connector.db.reminders.count_documents({'g_id': str(LEFT)}), 0)
        self.assertEqual(Connector.db.delivered.count_documents({'g_id': str(LEFT)}), 0)
        self.assertIsNone(Connector.db.settings.find_one({'g_id': str(LEFT)}))
        # the other one is still kept
        self.assertEqual(Connector.db.intervals.count_documents({'g_id': str(OTHER)}), 1)

    async def test_delivery_loop_skips_them(self):
        self.add('left server', LEFT)
        self.add('other server', OTHER)
        Connector.guild_left(LEFT, self.now)
        cog = rm.ReminderModule.__new__(rm.ReminderModule)
        cog.client = SimpleNamespace(latency=0.05, is_ready=lambda: True, is_closed=lambda: False)
        cog.heartbeat = SimpleNamespace(push=AsyncMock())
        cog.loop_done = {'reminders': self.now, 'intervals': self.now}
        sent = []
        cog.print_reminder = AsyncMock(side_effect=lambda rem: sent.append(rem.msg))
        await rm.ReminderModule.check_pending_reminders.coro(cog)
        self.assertEqual(sent, ['other server'])
        self.assertEqual(Connector.db.reminders.count_documents({'g_id': str(LEFT)}), 1)

    async def test_daily_clean_up_purges(self):
        self.add('left long ago', LEFT)
        Connector.guild_left(LEFT, self.now - timedelta(days=8))
        cog = rm.ReminderModule.__new__(rm.ReminderModule)
        with self.assertLogs('Remindme.Core', 'INFO') as logs:
            await rm.ReminderModule.clean_interval_orphans.coro(cog)
        self.assertIn(f'guild {LEFT} left 7 days ago: deleted 1 reminder(s)', '\n'.join(logs.output))
        self.assertEqual(Connector.db.reminders.count_documents({}), 0)


if __name__ == '__main__':
    unittest.main()
