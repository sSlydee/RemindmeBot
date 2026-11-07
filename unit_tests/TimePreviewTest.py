"""The date shown while typing the 'time' of /remindme and /remind (autocomplete)"""
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

try:
    import mongomock
except ImportError:  # pragma: no cover
    mongomock = None

import lib.Connector
from lib.Connector import Connector
from cogs.ReminderCreation import describe_time, time_autocomplete, TIME_EXAMPLES

NOW = datetime(2026, 11, 7, 13, 5, 20)  # Saturday, 14:05 in Paris
TZ = 'Europe/Paris'


class DescribeTimeTest(unittest.TestCase):

    def check(self, text, expected):
        self.assertEqual(describe_time(text, NOW, TZ), expected, text)

    def test_dates(self):
        self.check('in 2h', 'Sat 07 Nov 16:05 (in 2 h)')
        self.check('in 30 minutes', 'Sat 07 Nov 14:35 (in 30 min)')
        self.check('tomorrow 9:00', 'Sun 08 Nov 09:00 (in 18 h 54)')
        self.check('friday 18:30', 'Fri 13 Nov 18:30 (in 6 days)')
        self.check('1 jan 2028 10:00', 'Sat 01 Jan 2028 10:00 (in 419 days)')

    def test_repetitions(self):
        self.check('every friday at 20:15', 'repeats, first Fri 13 Nov 20:15 (in 6 days)')
        self.assertIn('no date in the future', describe_time('every day until 1 jan 2020', NOW, TZ))
        self.assertIn('none of its months', describe_time('every 30th of february', NOW, TZ))

    def test_errors(self):
        self.check('blah', '⚠ can\'t read this date')
        self.check('yesterday', '⚠ this date is in the past')
        self.check('999999999d', '⚠ can\'t read this date')

    def test_server_timezone(self):
        self.assertEqual(describe_time('in 2h', NOW, 'America/New_York'), 'Sat 07 Nov 10:05 (in 2 h)')


def _context(value, personal=False):
    owners = SimpleNamespace(guild_id=None if personal else 1, user_id=3 if personal else None)
    interaction = SimpleNamespace(guild_id=1, user=SimpleNamespace(id=3), authorizing_integration_owners=owners)
    return SimpleNamespace(value=value, interaction=interaction)


@unittest.skipUnless(mongomock, 'needs mongomock')
class TimeAutocompleteTest(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        Connector.db = mongomock.MongoClient().reminderBot
        Connector.set_timezone(1, 'Europe/Paris')
        Connector.set_timezone(3, 'America/New_York')
        self.now = patch('lib.timeutil.utcnow', return_value=NOW)
        self.now.start()
        self.addCleanup(self.now.stop)

    async def test_examples_when_empty(self):
        choices = await time_autocomplete(_context(''))
        self.assertEqual([c.value for c in choices], TIME_EXAMPLES)
        self.assertEqual(choices[0].name, 'in 2h → Sat 07 Nov 16:05 (in 2 h)')

    async def test_typed_text_is_kept(self):
        [choice] = await time_autocomplete(_context('friday 18:30'))
        self.assertEqual(choice.value, 'friday 18:30')
        self.assertEqual(choice.name, 'friday 18:30 → Fri 13 Nov 18:30 (in 6 days)')

    async def test_user_timezone_where_only_the_user_installed_the_app(self):
        [choice] = await time_autocomplete(_context('in 2h', personal=True))
        self.assertIn('10:05', choice.name)

    async def test_long_text(self):
        [choice] = await time_autocomplete(_context('every friday at 20:15 ' + 'x' * 200))
        self.assertLessEqual(len(choice.name), 100)
        self.assertLessEqual(len(choice.value), 100)

    async def test_errors_give_no_suggestion(self):
        with patch.object(lib.Connector.Connector, 'get_timezone', side_effect=RuntimeError('db down')), \
             self.assertLogs('Remindme.Creation', 'ERROR'):
            self.assertEqual(await time_autocomplete(_context('in 2h')), [])


if __name__ == '__main__':
    unittest.main()
