import os
import time
import unittest
from datetime import datetime

import lib.Connector
from lib.Reminder import Reminder, IntervalReminder, utc_timestamp, utc_from_timestamp


class ReminderStorageTest(unittest.TestCase):
    """stored timestamps must not depend on the machine timezone

    Reminder.at is naive UTC. Converting it with datetime.timestamp() used
    the host timezone, so the bot only worked on a UTC machine (TZ=UTC).
    """

    ZONES = ['UTC', 'Europe/Amsterdam', 'America/New_York', 'Asia/Kolkata']

    def setUp(self):
        self._old_tz = os.environ.get('TZ')

    def tearDown(self):
        if self._old_tz is None:
            os.environ.pop('TZ', None)
        else:
            os.environ['TZ'] = self._old_tz
        time.tzset()

    def _set_machine_tz(self, zone):
        os.environ['TZ'] = zone
        time.tzset()

    def test_timestamp_is_real_epoch(self):
        at = datetime(2026, 11, 13, 6, 0)
        for zone in self.ZONES:
            with self.subTest(zone=zone):
                self._set_machine_tz(zone)
                self.assertEqual(utc_timestamp(at), 1794549600.0)
                self.assertEqual(utc_from_timestamp(1794549600.0), at)

    def test_round_trip_in_any_machine_timezone(self):
        # 2027-03-28 02:30 does not exist in Europe/Amsterdam (spring forward)
        for at in (datetime(2026, 11, 13, 6, 0), datetime(2027, 3, 28, 2, 30)):
            for zone in self.ZONES:
                with self.subTest(at=at, zone=zone):
                    self._set_machine_tz(zone)
                    rem = IntervalReminder({'msg': 'x'})
                    rem.at = at
                    rem.first_at = at
                    rem.created_at = at
                    stored = rem._to_json()
                    self.assertEqual(stored['at'], utc_timestamp(at))

                    # read back on another machine timezone
                    self._set_machine_tz('Pacific/Auckland')
                    loaded = IntervalReminder(stored)
                    self.assertEqual(loaded.at, at)
                    self.assertEqual(loaded.first_at, at)
                    self.assertEqual(loaded.created_at, at)


if __name__ == '__main__':
    unittest.main()
