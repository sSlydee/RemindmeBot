"""'9h' / '18h30' times, French inputs and repetitions the parser used to misread"""
import unittest
from datetime import datetime

from dateutil import tz

import lib.Connector  # noqa: F401 (import order: lib.Reminder needs it first)
import lib.input_parser as p

TZ = 'Europe/Paris'
SATURDAY = datetime(2026, 11, 7, 13, 30)  # 14:30 in Paris


def utc(*local):
    """naive UTC of a Paris local time"""
    return datetime(*local, tzinfo=tz.gettz(TZ)).astimezone(tz.UTC).replace(tzinfo=None)


class ParseCase(unittest.TestCase):

    def check(self, text, expected):
        at, info = p.parse(text, SATURDAY, TZ)
        self.assertEqual(at, expected, f'{text!r}: {info}')

    def rule(self, text, **expected):
        """the parts of the RRULE read from text"""
        rule, info = p.parse(text, SATURDAY, TZ)
        self.assertIsInstance(rule, str, f'{text!r}: {info}')
        line = next(l for l in rule.splitlines() if l.startswith('RRULE:'))
        parts = dict(part.split('=', 1) for part in line[len('RRULE:'):].split(';'))
        for key, value in expected.items():
            self.assertEqual(parts.get(key.upper()), value, f'{text!r}: {line}')


class HourTimeTest(ParseCase):

    def test_after_a_day(self):
        self.check('tomorrow 18h30', utc(2026, 11, 8, 18, 30))
        self.check('tomorrow at 9h', utc(2026, 11, 8, 9, 0))
        self.check('friday 9h', utc(2026, 11, 13, 9, 0))
        self.check('9h30 tomorrow', utc(2026, 11, 8, 9, 30))
        self.check('tomorrow 18 h 30', utc(2026, 11, 8, 18, 30))

    def test_after_at(self):
        self.check('at 18h30', utc(2026, 11, 7, 18, 30))
        # passed today: tomorrow
        self.check('at 9h', utc(2026, 11, 8, 9, 0))

    def test_durations_are_unchanged(self):
        # alone, as documented: a duration
        self.check('1h30', datetime(2026, 11, 7, 15, 0))
        self.check('18h30', datetime(2026, 11, 8, 8, 0))
        self.check('2h', datetime(2026, 11, 7, 15, 30))

    def test_in_a_duration(self):
        # was read as 01:30 today
        self.check('in 1h30', datetime(2026, 11, 7, 15, 0))
        self.check('in 2 hours', datetime(2026, 11, 7, 15, 30))
        self.check('in an hour', datetime(2026, 11, 7, 14, 30))


class FrenchTest(ParseCase):

    def test_days(self):
        self.check('demain', utc(2026, 11, 8, 9, 0))
        self.check('demain à 18h30', utc(2026, 11, 8, 18, 30))
        self.check('demain a 9h', utc(2026, 11, 8, 9, 0))
        self.check('demain midi', utc(2026, 11, 8, 12, 0))
        self.check('vendredi à 9h', utc(2026, 11, 13, 9, 0))
        self.check('Vendredi 18:30', utc(2026, 11, 13, 18, 30))
        self.check("aujourd'hui 18h", utc(2026, 11, 7, 18, 0))
        self.check('après-demain 10h', utc(2026, 11, 9, 10, 0))
        self.check('apres demain à 10h', utc(2026, 11, 9, 10, 0))

    def test_times_of_day(self):
        self.check('à 18h', utc(2026, 11, 7, 18, 0))
        self.check('midi', utc(2026, 11, 8, 12, 0))
        self.check('minuit', utc(2026, 11, 8, 0, 0))

    def test_dates(self):
        self.check('le 15 janvier à 9h', utc(2027, 1, 15, 9, 0))
        self.check('15 janvier 9h', utc(2027, 1, 15, 9, 0))
        self.check('1er décembre à 10h', utc(2026, 12, 1, 10, 0))
        self.check('20/11 à 9h', utc(2026, 11, 20, 9, 0))

    def test_durations(self):
        self.check('dans 2h', datetime(2026, 11, 7, 15, 30))
        self.check('dans 2 heures', datetime(2026, 11, 7, 15, 30))
        self.check('dans 3 jours', datetime(2026, 11, 10, 13, 30))
        self.check('dans 1 semaine', datetime(2026, 11, 14, 13, 30))
        self.check('dans 10 minutes', datetime(2026, 11, 7, 13, 40))
        self.check('dans 1 an', datetime(2027, 11, 7, 13, 30))

    def test_repetitions(self):
        self.rule('tous les lundis à 9h', freq='WEEKLY', byday='MO', byhour='9', byminute='0')
        self.rule('tous les jours à 8h30', freq='DAILY', byhour='8', byminute='30')
        self.rule('chaque vendredi à 20h', freq='WEEKLY', byday='FR', byhour='20')
        self.rule('toutes les 2 semaines', freq='WEEKLY', interval='2')
        self.rule('tous les 2 jours', freq='DAILY', interval='2')
        self.rule('toutes les heures', freq='HOURLY')
        self.rule('tous les week-ends à 10h', freq='WEEKLY', byday='SA,SU', byhour='10')
        self.rule('tous les lundis et mercredis à 9h', freq='WEEKLY', byday='MO,WE', byhour='9')
        self.rule('en semaine à 8h', freq='WEEKLY', byday='MO,TU,WE,TH,FR', byhour='8')
        self.rule('tous les jours de la semaine à 8h', freq='WEEKLY', byday='MO,TU,WE,TH,FR', byhour='8')
        self.rule('tous les mois le 15 à 9h', freq='MONTHLY', bymonthday='15', byhour='9')
        self.rule('tous les ans le 1er juillet', freq='YEARLY', bymonth='7', bymonthday='1')
        self.rule('tous les premiers lundis du mois', freq='MONTHLY', byday='1MO')
        self.rule('chaque dernier vendredi du mois à 18h', freq='MONTHLY', byday='-1FR', byhour='18')
        self.rule("tous les vendredis jusqu'au 20 décembre", freq='WEEKLY', byday='FR', until='20261220')


class RepetitionTest(ParseCase):

    def test_every_compact_duration(self):
        # 'every 2h' was read as today 02:00
        self.rule('every 2h', freq='HOURLY', interval='2')
        self.rule('every 30m', freq='MINUTELY', interval='30')
        self.rule('every 15 min', freq='MINUTELY', interval='15')

    def test_time_without_at(self):
        # the time was lost
        self.rule('every friday 18:00', freq='WEEKLY', byday='FR', byhour='18')
        self.rule('every friday 18h', freq='WEEKLY', byday='FR', byhour='18')
        self.rule('every day 8:30', freq='DAILY', byhour='8', byminute='30')

    def test_unchanged(self):
        self.rule('every monday at 9', freq='WEEKLY', byday='MO', byhour='9')
        self.rule('every weekday at 8:30', byday='MO,TU,WE,TH,FR', byhour='8', byminute='30')
        self.rule('every month on the 15th at 9:00', freq='MONTHLY', bymonthday='15', byhour='9')
        self.rule('every first monday of the month', freq='MONTHLY', byday='1MO')
        self.rule('every 2 weeks on friday at 7', freq='WEEKLY', interval='2', byday='FR', byhour='7')


class MessageTest(unittest.TestCase):

    def test_unreadable_input(self):
        at, info = p.parse('xyz', SATURDAY, TZ)
        self.assertIsNone(at)
        self.assertNotIn('%s', info)
        self.assertIn('xyz', info)

    def test_past_date_in_local_time(self):
        at, info = p.parse('1 jan 2020 10:00', SATURDAY, TZ)
        self.assertIn('must be in the future', info)
        self.assertIn('now:        2026-11-07 14:30', info)
        self.assertIn('understood: 2020-01-01 10:00', info)
        self.assertNotIn('utc', info.lower())


if __name__ == '__main__':
    unittest.main()
