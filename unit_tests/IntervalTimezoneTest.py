import unittest
from unittest.mock import patch

from datetime import datetime, timedelta

import lib.Connector
import lib.input_parser as p
import lib.ReminderRepeater as repeater
from lib.Reminder import Reminder


class IntervalTimezoneTest(unittest.TestCase):
    """intervals built from a one-shot reminder must keep its local time

    Reminder.at is UTC, interval rules live in the server's local time.
    Mixing both made repeating reminders fire 1h (winter) or 2h (summer)
    early in Europe/Paris.
    """

    def setUp(self):
        connector = lib.Connector.Connector
        patches = [
            patch.object(connector, 'get_timezone', return_value='Europe/Paris'),
            patch.object(connector, 'add_interval', return_value='new-id'),
            patch.object(connector, 'add_reminder', return_value='new-id'),
            patch.object(connector, 'delete_reminder', return_value=True),
            patch.object(connector, 'delete_interval', return_value=True),
            patch.object(connector, 'update_interval_rules'),
            patch.object(connector, 'update_interval_at'),
            # no database: the given objects are the stored ones
            patch.object(repeater, '_stored', side_effect=lambda interval: interval),
            patch.object(connector, 'get_reminder_by_id', return_value=object()),
        ]
        for pt in patches:
            pt.start()
            self.addCleanup(pt.stop)

    def _one_shot(self, at):
        rem = Reminder({'msg': 'test', 'g_id': '1', 'ch_id': '2', 'author': '3', 'target': '3'})
        rem._id = 'old-id'
        rem.at = at
        return rem

    def _set_daily(self, rem):
        # same path as the "Set Interval" -> "Add Repeating Rule" button
        dtstart = repeater.utc_to_rule_frame(rem.at, repeater.instance_id_of(rem))
        rule, err = p.rrule_normalize('freq=daily', dtstart)
        self.assertIsNone(err)
        return repeater.add_rules(rem, rrule=str(rule))

    def test_winter_keeps_local_time(self):
        now = datetime(2026, 11, 7, 12, 0)
        at, _ = p.parse('8 nov 7:00', now, 'Europe/Paris')
        self.assertEqual(at, datetime(2026, 11, 8, 6, 0))  # 07:00 CET

        interval = self._set_daily(self._one_shot(at))
        self.assertEqual(interval.first_at, datetime(2026, 11, 8, 7, 0))  # local frame

        first = interval.next_trigger(now)
        second = interval.next_trigger(first + timedelta(seconds=1))
        self.assertEqual(first, datetime(2026, 11, 8, 6, 0))
        self.assertEqual(second, datetime(2026, 11, 9, 6, 0))

    def test_summer_keeps_local_time(self):
        now = datetime(2026, 6, 1, 12, 0)
        at, _ = p.parse('2 jun 7:00', now, 'Europe/Paris')
        self.assertEqual(at, datetime(2026, 6, 2, 5, 0))  # 07:00 CEST

        interval = self._set_daily(self._one_shot(at))
        first = interval.next_trigger(now)
        self.assertEqual(first, datetime(2026, 6, 2, 5, 0))
        self.assertEqual(interval.next_trigger(first + timedelta(seconds=1)), datetime(2026, 6, 3, 5, 0))

    def test_daylight_saving_switch(self):
        # 07:00 local every day, across the October switch (CEST -> CET)
        now = datetime(2026, 10, 24, 12, 0)
        at, _ = p.parse('25 oct 7:00', now, 'Europe/Paris')
        interval = self._set_daily(self._one_shot(at))
        first = interval.next_trigger(now)
        second = interval.next_trigger(first + timedelta(seconds=1))
        self.assertEqual(first, datetime(2026, 10, 25, 6, 0))  # 07:00 CET (switch at 03:00 that night)
        self.assertEqual(second, datetime(2026, 10, 26, 6, 0))

    def test_single_date_is_stored_in_local_frame(self):
        now = datetime(2026, 11, 7, 12, 0)
        at, _ = p.parse('8 nov 7:00', now, 'Europe/Paris')
        interval = self._set_daily(self._one_shot(at))

        extra_utc, _ = p.parse('20 nov 18:30', now, 'Europe/Paris')
        rule_date = repeater.utc_to_rule_frame(extra_utc, repeater.instance_id_of(interval))
        self.assertEqual(rule_date, datetime(2026, 11, 20, 18, 30))

    def test_back_to_one_shot_returns_utc(self):
        now = datetime(2026, 11, 7, 12, 0)
        at, _ = p.parse('8 nov 7:00', now, 'Europe/Paris')
        interval = self._set_daily(self._one_shot(at))

        with patch('lib.timeutil.utcnow', return_value=now):
            one_shot = repeater.rm_rules(interval, rule_idx=0)

        self.assertIs(type(one_shot), Reminder)
        self.assertEqual(one_shot.at, at)


if __name__ == '__main__':
    unittest.main()
