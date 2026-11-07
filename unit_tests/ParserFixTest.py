"""Inputs the time parser used to misread (found while checking the README examples)"""
import unittest
from datetime import datetime

from dateutil import tz

import lib.Connector  # noqa: F401 (import order: lib.Reminder needs it first)
import lib.input_parser as p

TZ = 'Europe/Paris'
SATURDAY = datetime(2026, 11, 7, 13, 30)  # 14:30 in Paris
WEDNESDAY = datetime(2026, 11, 4, 8, 0)
FRIDAY_EVENING = datetime(2026, 11, 6, 18, 0)  # 19:00 in Paris


def utc(*local):
    """naive UTC of a Paris local time"""
    return datetime(*local, tzinfo=tz.gettz(TZ)).astimezone(tz.UTC).replace(tzinfo=None)


class DateTest(unittest.TestCase):

    def check(self, text, expected, now=SATURDAY):
        at, info = p.parse(text, now, TZ)
        self.assertEqual(at, expected, f'{text!r}: {info}')

    def test_sept(self):
        for text in ('23 sept 15:00', '23 sept at 3pm', 'sept 23 at 15:00', '23 Sept. 15:00'):
            self.check(text, utc(2027, 9, 23, 15, 0))

    def test_thurs(self):
        for text in ('thurs 9:00', 'thur 9:00', 'thu 9:00', 'thursday 9:00'):
            self.check(text, utc(2026, 11, 12, 9, 0))

    def test_date_then_time_without_at(self):
        for text in ('2 aug 3pm', '2 aug 15:00', '2 august 3pm', '2 aug at 3pm'):
            self.check(text, utc(2027, 8, 2, 15, 0))
        self.check('23 september 2027 15:00', utc(2027, 9, 23, 15, 0))
        self.check('24 dec 18:00', utc(2026, 12, 24, 18, 0))

    def test_end_of_week(self):
        # on the weekend: next Friday
        self.check('eow', utc(2026, 11, 13, 17, 0))
        # during the week: this Friday, as before
        self.check('eow', utc(2026, 11, 6, 17, 0), now=WEDNESDAY)
        # Friday evening: a bit later that evening, as before
        self.check('eow', utc(2026, 11, 6, 21, 0), now=FRIDAY_EVENING)


class DurationTest(unittest.TestCase):

    def check(self, text, expected):
        at, info = p.parse(text, SATURDAY, TZ)
        self.assertEqual(at, expected, f'{text!r}: {info}')

    def test_written_together(self):
        self.check('1h30m', datetime(2026, 11, 7, 15, 0))
        self.check('2d12h', datetime(2026, 11, 10, 1, 30))
        self.check('1h 30m', datetime(2026, 11, 7, 15, 0))

    def test_minutes_after_hours(self):
        self.check('1h30', datetime(2026, 11, 7, 15, 0))

    def test_unchanged(self):
        self.check('1y 1mo 2 days -5h', datetime(2027, 12, 9, 8, 30))
        self.check('90 min', datetime(2026, 11, 7, 15, 0))


class TimeOfDayTest(unittest.TestCase):

    def check(self, text, expected, now=SATURDAY):
        at, info = p.parse(text, now, TZ)
        self.assertEqual(at, expected, f'{text!r}: {info}')

    def test_passed_today_means_tomorrow(self):
        self.check('noon', utc(2026, 11, 8, 12, 0))
        self.check('midnight', utc(2026, 11, 8, 0, 0))
        for text in ('9:00', '9am', 'at 9', 'at 9:00'):
            self.check(text, utc(2026, 11, 8, 9, 0))

    def test_still_today(self):
        self.check('16:00', utc(2026, 11, 7, 16, 0))
        self.check('at 9pm', utc(2026, 11, 7, 21, 0))
        self.check('at 9', utc(2026, 11, 4, 9, 0), now=WEDNESDAY)

    def test_bare_number_is_unchanged(self):
        # read as the 9th of the month, as before
        self.check('9', utc(2026, 11, 9, 0, 0))


class YearlyTest(unittest.TestCase):

    def first(self, text, now=SATURDAY):
        rule_text, info = p.parse(text, now, TZ)
        self.assertIsInstance(rule_text, str, f'{text!r}: {info}')
        start = now.replace(tzinfo=tz.UTC).astimezone(tz.gettz(TZ)).replace(tzinfo=None)
        rule, err = p.rrule_normalize(rule_text, start, TZ)
        self.assertIsNone(err, text)
        return rule.after(start)

    def test_every_year_on_a_date(self):
        for text in ('every year at 1st july at 10:00', 'every year on 1 july at 10:00',
                     'every 1 july at 10:00', 'every year on the 1st of july at 10:00',
                     'every year on july 1st at 10:00', 'every july 1st at 10:00', 'every 1st july at 10:00'):
            self.assertEqual(self.first(text), datetime(2027, 7, 1, 10, 0), text)

    def test_other_repetitions_unchanged(self):
        self.assertEqual(self.first('every friday at 20:15'), datetime(2026, 11, 13, 20, 15))
        self.assertEqual(self.first('every 2 weeks'), datetime(2026, 11, 21, 14, 30))


if __name__ == '__main__':
    unittest.main()
