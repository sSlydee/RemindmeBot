"""The delivery loops, with an in-memory database (mongomock)"""
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

try:
    import mongomock
except ImportError:  # pragma: no cover
    mongomock = None

import discord

import lib.timeutil as timeutil
import lib.ReminderRepeater
from lib.Connector import Connector
from lib.Reminder import Reminder, IntervalReminder
import cogs.ReminderModule as rm

GUILD = 1
USER = 3


def _server_error():
    return discord.DiscordServerError(SimpleNamespace(status=503, reason='Service Unavailable'), 'down')


class FakeHeartbeat:
    def __init__(self):
        self.pushes = 0

    async def push(self, msg='OK', ping_ms=None):
        self.pushes += 1


@unittest.skipUnless(mongomock, 'needs mongomock')
class DeliveryTest(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        Connector.db = mongomock.MongoClient().reminderBot
        Connector.set_timezone(GUILD, 'Europe/Paris')
        self.sent = []

        # the cog without its loops running
        self.cog = rm.ReminderModule.__new__(rm.ReminderModule)
        self.cog.client = SimpleNamespace(latency=0.05, is_ready=lambda: True, is_closed=lambda: False)
        self.cog.heartbeat = FakeHeartbeat()
        now = timeutil.utcnow()
        self.cog.loop_done = {'reminders': now, 'intervals': now}
        self.cog.print_reminder = AsyncMock(side_effect=self._record)

    async def _record(self, rem):
        self.sent.append(rem.msg)

    def fail_with(self, error):
        self.cog.print_reminder = AsyncMock(side_effect=error)

    async def run_reminders(self):
        await rm.ReminderModule.check_pending_reminders.coro(self.cog)

    async def run_intervals(self):
        await rm.ReminderModule.check_pending_intervals.coro(self.cog)

    def add_reminder(self, msg, late=timedelta(minutes=1)):
        rem = Reminder({'msg': msg, 'g_id': str(GUILD), 'ch_id': '2', 'author': str(USER), 'target': str(USER)})
        rem.created_at = timeutil.utcnow() - timedelta(days=3)
        rem.at = timeutil.utcnow() - late
        rem._id = Connector.add_reminder(rem)
        return rem

    def add_interval(self, msg, rule='DTSTART:20260101T070000\nRRULE:FREQ=WEEKLY', late=timedelta(minutes=1)):
        rem = IntervalReminder({'msg': msg, 'g_id': str(GUILD), 'ch_id': '2', 'author': str(USER), 'target': str(USER)})
        rem.created_at = timeutil.utcnow() - timedelta(days=30)
        rem.first_at = datetime(2026, 1, 1, 7, 0)
        rem.rrules = [rule]
        rem.at = timeutil.utcnow() - late
        rem._id = Connector.add_interval(rem)
        return rem

    # ---------- one-shot reminders ----------

    async def test_reminder_is_sent_and_kept_for_its_buttons(self):
        rem = self.add_reminder('hello')
        await self.run_reminders()
        self.assertEqual(self.sent, ['hello'])
        self.assertEqual(Connector.db.reminders.count_documents({}), 0)
        self.assertEqual(Connector.get_delivered(rem._id).msg, 'hello')

    async def test_reminder_kept_while_discord_is_down(self):
        self.add_reminder('first')
        self.add_reminder('second')
        self.fail_with(_server_error())
        with self.assertLogs('Remindme.Core', 'WARNING'):
            await self.run_reminders()
        # both tried, both kept for the next run
        self.assertEqual(self.cog.print_reminder.await_count, 2)
        self.assertEqual(Connector.db.reminders.count_documents({}), 2)

        self.cog.print_reminder = AsyncMock(side_effect=self._record)
        await self.run_reminders()
        self.assertEqual(sorted(self.sent), ['first', 'second'])
        self.assertEqual(Connector.db.reminders.count_documents({}), 0)

    async def test_one_failing_reminder_does_not_block_the_others(self):
        self.add_reminder('bad')
        for i in range(4):
            self.add_reminder(f'good {i}')

        async def send(rem):
            if rem.msg == 'bad':
                raise _server_error()
            self.sent.append(rem.msg)
        self.cog.print_reminder = AsyncMock(side_effect=send)
        with self.assertLogs('Remindme.Core', 'WARNING'):
            await self.run_reminders()
        self.assertEqual(sorted(self.sent), ['good 0', 'good 1', 'good 2', 'good 3'])
        self.assertEqual([r['msg'] for r in Connector.db.reminders.find({})], ['bad'])

    async def test_discord_down_stops_the_run_and_the_heartbeat(self):
        for i in range(5):
            self.add_reminder(f'r{i}')
        self.cog.loop_done = {name: timeutil.utcnow() - timedelta(minutes=10) for name in self.cog.loop_done}
        self.fail_with(_server_error())
        with self.assertLogs('Remindme.Core', 'WARNING'):
            await self.run_reminders()
        # 3 failures in a row: the other 2 aren't tried, all kept, no OK for the monitor
        self.assertEqual(self.cog.print_reminder.await_count, rm.DOWN_AFTER)
        self.assertEqual(Connector.db.reminders.count_documents({}), 5)
        self.assertEqual(self.cog.heartbeat.pushes, 0)

    async def test_one_failing_interval_does_not_block_the_others(self):
        bad = self.add_interval('bad')
        good = self.add_interval('good')

        async def send(rem):
            if rem.msg == 'bad':
                raise _server_error()
            self.sent.append(rem.msg)
        self.cog.print_reminder = AsyncMock(side_effect=send)
        due = Connector.get_interval_by_id(bad._id).at
        with self.assertLogs('Remindme.Core', 'WARNING'):
            await self.run_intervals()
        self.assertEqual(self.sent, ['good'])
        self.assertEqual(Connector.get_interval_by_id(bad._id).at, due)
        self.assertGreater(Connector.get_interval_by_id(good._id).at, timeutil.utcnow())

    async def test_network_errors_are_retried(self):
        self.add_reminder('hello')
        self.fail_with(TimeoutError())
        with self.assertLogs('Remindme.Core', 'WARNING'):
            await self.run_reminders()
        self.assertEqual(Connector.db.reminders.count_documents({}), 1)

    async def test_reminder_dropped_after_a_day(self):
        self.add_reminder('old', late=timedelta(days=2))
        self.fail_with(_server_error())
        with self.assertLogs('Remindme.Core', 'ERROR'):
            await self.run_reminders()
        self.assertEqual(Connector.db.reminders.count_documents({}), 0)

    async def test_other_errors_are_not_retried(self):
        self.add_reminder('hello')
        self.fail_with(ValueError('bug'))
        with self.assertLogs('Remindme.Core', 'ERROR'):
            await self.run_reminders()
        self.assertEqual(Connector.db.reminders.count_documents({}), 0)

    # ---------- intervals ----------

    async def test_interval_is_sent_and_moved_on(self):
        rem = self.add_interval('weekly')
        await self.run_intervals()
        self.assertEqual(self.sent, ['weekly'])
        stored = Connector.get_interval_by_id(rem._id)
        self.assertGreater(stored.at, timeutil.utcnow())

    async def test_broken_rule_does_not_block_the_others(self):
        broken = self.add_interval('broken', rule='RRULE:FREQ=NOPE')
        good = self.add_interval('good')
        with self.assertLogs('Remindme.Core', 'ERROR'):
            await self.run_intervals()

        # both sent, the broken one with a warning, and it isn't scheduled anymore
        self.assertEqual(len(self.sent), 2)
        self.assertIn('good', self.sent)
        self.assertTrue(any(m.startswith('broken') and 'WARNING' in m for m in self.sent))
        self.assertIsNone(Connector.get_interval_by_id(broken._id).at)
        self.assertGreater(Connector.get_interval_by_id(good._id).at, timeutil.utcnow())

        # the next run doesn't fail on it again
        self.sent.clear()
        await self.run_intervals()
        self.assertEqual(self.sent, [])

    async def test_interval_waits_while_discord_is_down(self):
        rem = self.add_interval('weekly')
        due = Connector.get_interval_by_id(rem._id).at
        self.fail_with(_server_error())
        with self.assertLogs('Remindme.Core', 'WARNING'):
            await self.run_intervals()
        # back to the missed date
        self.assertEqual(Connector.get_interval_by_id(rem._id).at, due)

        self.cog.print_reminder = AsyncMock(side_effect=self._record)
        await self.run_intervals()
        self.assertEqual(self.sent, ['weekly'])
        self.assertGreater(Connector.get_interval_by_id(rem._id).at, timeutil.utcnow())

    async def test_paused_interval_moves_on_silently(self):
        rem = self.add_interval('weekly')
        Connector.set_interval_paused(rem._id, True)
        await self.run_intervals()
        self.assertEqual(self.sent, [])
        self.assertGreater(Connector.get_interval_by_id(rem._id).at, timeutil.utcnow())

    # ---------- monitor ----------

    async def test_heartbeat_when_both_loops_run(self):
        await self.run_intervals()
        await self.run_reminders()
        self.assertEqual(self.cog.heartbeat.pushes, 1)

    async def test_no_heartbeat_when_the_interval_loop_is_stuck(self):
        self.cog.loop_done['intervals'] = timeutil.utcnow() - timedelta(minutes=10)
        with self.assertLogs('Remindme.Core', 'WARNING'):
            await self.run_reminders()
        self.assertEqual(self.cog.heartbeat.pushes, 0)

    # ---------- timezone change ----------

    def test_timezone_change_moves_the_next_date(self):
        # every Friday 07:00 local
        rem = IntervalReminder({'msg': 'x', 'g_id': str(GUILD), 'ch_id': '2', 'author': str(USER), 'target': str(USER)})
        rem.created_at = timeutil.utcnow()
        rem.first_at = datetime(2026, 1, 2, 7, 0)
        rem.rrules = ['DTSTART:20260102T070000\nRRULE:FREQ=WEEKLY;BYDAY=FR']
        rem.at = rem.next_trigger(timeutil.utcnow(), tz_str='Europe/Paris')
        rem._id = Connector.add_interval(rem)
        private = IntervalReminder({'msg': 'mine', 'author': str(USER), 'target': str(USER)})
        private.first_at = datetime(2026, 1, 2, 7, 0)
        private.rrules = list(rem.rrules)
        private.at = rem.at
        private._id = Connector.add_interval(private)

        broken = IntervalReminder({'msg': 'broken', 'g_id': str(GUILD), 'author': str(USER), 'target': str(USER)})
        broken.first_at = datetime(2026, 1, 2, 7, 0)
        broken.rrules = ['RRULE:FREQ=NOPE']
        broken.at = rem.at
        broken._id = Connector.add_interval(broken)

        Connector.set_timezone(GUILD, 'America/New_York')
        # the broken rule is logged and skipped, the others move on
        with self.assertLogs('Remindme.Repeater', 'ERROR'):
            self.assertEqual(lib.ReminderRepeater.reschedule_instance(GUILD), 1)

        moved = Connector.get_interval_by_id(rem._id).at
        # 07:00 in New York is 5 or 6 hours later than 07:00 in Paris
        self.assertIn(moved - rem.at, (timedelta(hours=5), timedelta(hours=6)))
        self.assertEqual(moved.weekday(), 4)
        # the private interval of the user keeps its timezone
        self.assertEqual(Connector.get_interval_by_id(private._id).at, private.at)


class SendLongTest(unittest.IsolatedAsyncioTestCase):

    async def test_long_text_is_split(self):
        dest = SimpleNamespace(send=AsyncMock(return_value='msg'))
        view = object()
        await rm.send_long(dest, 'x' * 4500, view=view, allowed_mentions='mentions')
        calls = dest.send.await_args_list
        self.assertEqual([len(c.args[0]) for c in calls], [2000, 2000, 500])
        self.assertIs(calls[-1].kwargs['view'], view)
        self.assertNotIn('view', calls[0].kwargs)
        self.assertEqual(calls[0].kwargs['allowed_mentions'], 'mentions')

    async def test_partly_sent_text_is_not_sent_again(self):
        dest = SimpleNamespace(send=AsyncMock(side_effect=['first', _server_error()]))
        with self.assertLogs('Remindme.Core', 'ERROR'):
            sent = await rm.send_long(dest, 'x' * 3000)
        self.assertEqual(sent, 'first')

    async def test_nothing_sent_is_retried(self):
        dest = SimpleNamespace(send=AsyncMock(side_effect=_server_error()))
        with self.assertRaises(discord.DiscordServerError):
            await rm.send_long(dest, 'x' * 3000)

    async def test_mention_is_not_alone(self):
        dest = SimpleNamespace(send=AsyncMock(return_value='msg'))
        await rm.send_long(dest, '<@3> ' + 'A' * 3000)
        first = dest.send.await_args_list[0].args[0]
        self.assertEqual(len(first), 2000)
        self.assertTrue(first.startswith('<@3> AAA'))

    async def test_embed_without_text(self):
        dest = SimpleNamespace(send=AsyncMock(return_value='msg'))
        await rm.send_long(dest, '', embed='eb')
        dest.send.assert_awaited_once_with(None, embed='eb')


if __name__ == '__main__':
    unittest.main()
