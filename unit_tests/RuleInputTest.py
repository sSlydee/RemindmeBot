import unittest
from datetime import datetime

import lib.Connector  # noqa: F401 (import order: lib.Reminder needs it first)
from util.reminderInteraction import ReminderIntervalAddView


class RuleInputTest(unittest.TestCase):
    """rules of 'Add Repeating Rule' can be written in natural language"""

    def setUp(self):
        self.dtstart = datetime(2026, 11, 13, 7, 0)  # Friday 07:00 local

    def _rule(self, text):
        rule, err = ReminderIntervalAddView._parse_rule(text, self.dtstart, 'Europe/Paris')
        self.assertIsNone(err, text)
        return rule

    def test_natural_language(self):
        rule = self._rule('every friday at 7')
        self.assertEqual(list(rule[:2]), [datetime(2026, 11, 13, 7, 0), datetime(2026, 11, 20, 7, 0)])

    def test_natural_language_keeps_the_reminder_time(self):
        # no time in the text: the reminder's own time and weekday are used
        rule = self._rule('every 2 weeks')
        self.assertEqual(list(rule[:2]), [datetime(2026, 11, 13, 7, 0), datetime(2026, 11, 27, 7, 0)])

    def test_rrule_still_works(self):
        rule = self._rule('FREQ=MONTHLY;BYDAY=1MO')
        self.assertEqual(rule[0], datetime(2026, 12, 7, 7, 0))

    def test_quick_rules_are_valid(self):
        for key, (_, text) in ReminderIntervalAddView.QUICK_RULES.items():
            with self.subTest(key=key):
                self._rule(text)

    def test_single_date_is_refused(self):
        rule, err = ReminderIntervalAddView._parse_rule('tomorrow at 9', self.dtstart, 'Europe/Paris')
        self.assertIsNone(rule)
        self.assertIn('Add Single Date', err)

    def test_garbage_is_refused(self):
        rule, err = ReminderIntervalAddView._parse_rule('blabla', self.dtstart, 'Europe/Paris')
        self.assertIsNone(rule)
        self.assertIn('every friday at 7', err)


if __name__ == '__main__':
    unittest.main()
