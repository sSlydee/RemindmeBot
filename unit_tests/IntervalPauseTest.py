import asyncio
import unittest
from unittest.mock import patch
from datetime import datetime

import discord

import lib.Connector
from lib.Reminder import IntervalReminder
from lib.timeutil import utc_timestamp


def _weekly_friday_7():
    rem = IntervalReminder({'msg': 'x', 'g_id': '1', 'ch_id': '2', 'author': '3', 'target': '3'})
    rem._id = 'id'
    rem.first_at = datetime(2026, 11, 13, 7, 0)  # rule frame: local time
    rem.rrules = ['DTSTART:20261113T070000\nRRULE:FREQ=WEEKLY;BYDAY=FR']
    rem.at = datetime(2026, 11, 13, 6, 0)  # UTC
    return rem


class IntervalUpcomingTest(unittest.TestCase):

    def test_next_three_occurrences(self):
        rem = _weekly_friday_7()
        self.assertEqual(rem.upcoming(3, tz_str='Europe/Paris'),
                         [datetime(2026, 11, 13, 6, 0), datetime(2026, 11, 20, 6, 0), datetime(2026, 11, 27, 6, 0)])

    def test_menus_show_the_next_five(self):
        eb = discord.Embed()
        _weekly_friday_7().add_upcoming_field(eb, tz_str='Europe/Paris')
        [field] = eb.fields
        self.assertEqual(field.name, 'Next occurrences')
        lines = field.value.splitlines()
        self.assertEqual(len(lines), 5)
        # Fridays 07:00 in Paris, from 13 Nov to 11 Dec
        self.assertEqual(lines[0], f'<t:{int(utc_timestamp(datetime(2026, 11, 13, 6)))}:F>')
        self.assertEqual(lines[-1], f'<t:{int(utc_timestamp(datetime(2026, 12, 11, 6)))}:F>')

    def test_upcoming_is_one_pass(self):
        # each search replays the rules from their start: once for all the dates
        rem = _weekly_friday_7()
        with patch.object(IntervalReminder, '_local_occurrences', autospec=True,
                          side_effect=IntervalReminder._local_occurrences) as search:
            self.assertEqual(len(rem.upcoming(5, tz_str='Europe/Paris')), 5)
        self.assertEqual(search.call_count, 1)

    def test_info_embed_uses_the_rule_timezone(self):
        # the failed-delivery DM builds it without a display timezone (UTC)
        rem = _weekly_friday_7()
        with patch.object(lib.Connector.Connector, 'get_timezone', return_value='Europe/Paris'):
            in_utc = rem.get_info_embed()
            in_paris = rem.get_info_embed('Europe/Paris')
        upcoming = lambda eb: next(f.value for f in eb.fields if f.name == 'Next occurrences')
        self.assertEqual(upcoming(in_utc), upcoming(in_paris))
        self.assertTrue(upcoming(in_utc).startswith(f'<t:{int(utc_timestamp(datetime(2026, 11, 13, 6)))}:F>\n'
                                                    f'<t:{int(utc_timestamp(datetime(2026, 11, 20, 6)))}:F>'))

    def test_exception_removing_every_date(self):
        # every weekend, except every day: the search used to run into year 10000 (ValueError)
        rem = _weekly_friday_7()
        rem.rrules = ['DTSTART:20261113T070000\nRRULE:FREQ=WEEKLY;BYDAY=SA,SU']
        rem.exrules = ['DTSTART:20261113T070000\nRRULE:FREQ=DAILY']
        self.assertIsNone(rem.next_trigger(datetime(2026, 11, 10), tz_str='Europe/Paris'))

    def test_endless_yearly_rule_fully_excluded(self):
        # fewer than SEARCH_LIMIT years are left: the search ends at year 9999, no error
        rem = _weekly_friday_7()
        rem.rrules = ['DTSTART:20261113T070000\nRRULE:FREQ=YEARLY']
        rem.exrules = ['DTSTART:20261113T070000\nRRULE:FREQ=YEARLY']
        self.assertIsNone(rem.next_trigger(datetime(2026, 11, 14), tz_str='Europe/Paris'))

    def test_upcoming_stops_at_the_last_occurrence(self):
        rem = _weekly_friday_7()
        rem.rrules = ['DTSTART:20261113T070000\nRRULE:FREQ=WEEKLY;BYDAY=FR;COUNT=2']
        self.assertEqual(len(rem.upcoming(3, tz_str='Europe/Paris')), 2)

    def test_no_occurrence(self):
        rem = _weekly_friday_7()
        rem.at = None
        self.assertEqual(rem.upcoming(3, tz_str='Europe/Paris'), [])


class IntervalPauseTest(unittest.TestCase):

    def test_paused_is_stored(self):
        rem = _weekly_friday_7()
        self.assertFalse(IntervalReminder(rem._to_json()).paused)
        rem.paused = True
        self.assertTrue(IntervalReminder(rem._to_json()).paused)

    def test_paused_interval_moves_on_without_delivery(self):
        import cogs.ReminderModule as RM

        connector = lib.Connector.Connector
        paused, active = _weekly_friday_7(), _weekly_friday_7()
        paused.paused = True
        active._id = 'active'
        stored = {}
        sent = []

        class FakeCog:
            deliver = RM.ReminderModule.deliver
            loop_done = {}

            async def print_reminder(self, rem):
                sent.append(rem._id)

        with patch.object(connector, 'get_pending_intervals', return_value=[paused, active]), \
             patch.object(connector, 'update_interval_at', side_effect=lambda r: stored.update({r._id: r.at})), \
             patch.object(connector, 'get_timezone', return_value='Europe/Paris'), \
             patch('lib.timeutil.utcnow', return_value=datetime(2026, 11, 13, 6, 0, 30)):
            asyncio.run(RM.ReminderModule.check_pending_intervals.coro(FakeCog()))

        self.assertEqual(sent, ['active'])
        # both moved to the next Friday, 07:00 local
        self.assertEqual(stored, {'id': datetime(2026, 11, 20, 6, 0), 'active': datetime(2026, 11, 20, 6, 0)})


if __name__ == '__main__':
    unittest.main()
