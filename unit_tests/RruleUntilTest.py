import unittest
from datetime import datetime

import lib.input_parser as p


class RruleUntilTest(unittest.TestCase):
    """UNTIL of repeating rules, in the rule frame (local time of the server)

    RRULE generators write UNTIL in UTC ('...Z'); dateutil refused it with the
    naive local DTSTART the bot uses, so such rules could not be added.
    """

    def setUp(self):
        self.dtstart = datetime(2026, 11, 7, 7, 0)  # 07:00 local

    def _until(self, rule_str, tz_str='Europe/Paris'):
        rule, err = p.rrule_normalize(rule_str, self.dtstart, tz_str)
        self.assertIsNone(err)
        return rule._until

    def test_utc_until_is_converted_to_local_time(self):
        # winter: UTC+1
        self.assertEqual(self._until('FREQ=DAILY;UNTIL=20261231T120000Z'), datetime(2026, 12, 31, 13, 0))
        # summer: UTC+2
        self.assertEqual(self._until('FREQ=WEEKLY;BYDAY=FR;UNTIL=20270615T220000Z'), datetime(2027, 6, 16, 0, 0))

    def test_lowercase_and_rrule_prefix(self):
        # the Add Repeating Rule modal lowercases the input
        self.assertEqual(self._until('rrule:freq=daily;until=20261231t230000z'), datetime(2027, 1, 1, 0, 0))

    def test_local_until_is_kept(self):
        self.assertEqual(self._until('FREQ=DAILY;UNTIL=20261231T120000'), datetime(2026, 12, 31, 12, 0))

    def test_date_only_until_includes_that_day(self):
        rule, err = p.rrule_normalize('FREQ=DAILY;UNTIL=20261110', self.dtstart, 'Europe/Paris')
        self.assertIsNone(err)
        occurrences = list(rule)
        self.assertEqual(occurrences[-1], datetime(2026, 11, 10, 7, 0))

    def test_rule_without_until(self):
        rule, err = p.rrule_normalize('FREQ=WEEKLY;BYDAY=FR;COUNT=3', self.dtstart, 'Europe/Paris')
        self.assertIsNone(err)
        self.assertEqual(len(list(rule)), 3)

    def test_invalid_until_is_reported(self):
        rule, err = p.rrule_normalize('FREQ=DAILY;UNTIL=garbage', self.dtstart, 'Europe/Paris')
        self.assertIsNone(rule)
        self.assertIn('UNTIL', err.upper())

    def test_natural_language_until(self):
        now = datetime(2026, 11, 7, 12, 0)
        rule_str, _ = p.parse('every day until 31 dec', now, 'Europe/Paris')
        rule, err = p.rrule_normalize(rule_str, datetime(2026, 11, 7, 13, 0), 'Europe/Paris')
        self.assertIsNone(err)
        self.assertEqual(list(rule)[-1].date(), datetime(2026, 12, 31).date())


if __name__ == '__main__':
    unittest.main()
