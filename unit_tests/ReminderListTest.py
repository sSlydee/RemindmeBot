"""The look of /reminder_list"""
import unittest
from datetime import datetime
from types import SimpleNamespace

try:
    import mongomock
except ImportError:  # pragma: no cover
    mongomock = None

import lib.Connector
from lib.Connector import Connector
from lib.Reminder import Reminder, IntervalReminder
import util.reminderInteraction as ri
from cogs.ReminderListing import ReminderListing, ReminderListView

AT = datetime(2026, 11, 8, 8, 0)  # 09:00 in Paris
TS = 1794124800


def _reminder(msg='Take out the trash', **fields):
    data = {'msg': msg, 'g_id': '1', 'ch_id': '22', 'ch_name': 'general', 'author': '3', 'target': '3'}
    data.update(fields)
    rem = Reminder(data)
    rem.at = AT
    return rem


def _interval(msg='Check the feed', paused=False):
    rem = IntervalReminder({'msg': msg, 'g_id': '1', 'ch_id': '22', 'ch_name': 'general', 'author': '3', 'target': '3'})
    rem.first_at = datetime(2026, 11, 13, 7)
    rem.rrules = ['DTSTART:20261113T070000\nRRULE:FREQ=WEEKLY;BYDAY=FR']
    rem.exdates = [datetime(2026, 11, 20, 7)]
    rem.at = datetime(2026, 11, 13, 6)
    rem.paused = paused
    return rem


class ListEmbedTest(unittest.TestCase):

    def entry(self, rem, author_id=3):
        return ReminderListing._entry(1, rem, author_id)

    def test_one_shot(self):
        self.assertEqual(self.entry(_reminder()),
                         f'1️⃣ **Take out the trash**\n <t:{TS}:f> · <t:{TS}:R> · <#22>')

    def test_title_first_and_markdown_escaped(self):
        self.assertIn('**Car \\*now\\***', self.entry(_reminder(title='Car *now*')))

    def test_long_name_is_shortened(self):
        head = self.entry(_reminder('x' * 200)).splitlines()[0]
        self.assertIn('x' * 59 + '…', head)

    def test_repeating(self):
        lines = self.entry(_interval()).splitlines()
        self.assertTrue(lines[0].startswith('1️⃣ 🔁 **Check the feed**'))
        self.assertEqual(lines[2], ' ↳ every Fri, 1 exception')

    def test_paused(self):
        lines = self.entry(_interval(paused=True)).splitlines()
        self.assertIn('⏸️', lines[0])
        self.assertIn('· paused ·', lines[1])

    def test_other_target_and_dm(self):
        details = self.entry(_reminder(ch_id=None, target='4', target_name='@Bob')).splitlines()[1]
        self.assertTrue(details.endswith('· by DM · for @Bob'))

    def test_someone_else_s_reminder(self):
        self.assertIn('from <@3>', self.entry(_reminder(), author_id=9))

    def test_reminder_for_the_viewer(self):
        # in 'For me': who it is from, not again for whom
        details = self.entry(_reminder(author='4', target='3', target_name='@Me')).splitlines()[1]
        self.assertTrue(details.endswith('· <#22> · from <@4>'), details)

    def test_no_next_date(self):
        rem = _interval()
        rem.at = None
        self.assertIn('no next date', self.entry(rem))

    def test_pages(self):
        reminders = [_reminder(f'r{i}') for i in range(11)]
        eb = ReminderListing.get_reminder_list_eb(reminders, 1, 'Your reminders · Test')
        self.assertEqual(eb.footer.text, 'Page 2/2 · 11 reminders')
        # numbered like the dropdown of that page
        self.assertTrue(eb.description.startswith('1️⃣ **r9**'))
        self.assertIn('2️⃣ **r10**', eb.description)

    def test_empty(self):
        eb = ReminderListing.get_reminder_list_eb([], 0, 'Your private reminders')
        self.assertIn('No pending reminders', eb.description)
        self.assertEqual(eb.footer.text, 'Page 1/1 · 0 reminders')


@unittest.skipUnless(mongomock, 'needs mongomock')
class ListDropdownTest(unittest.IsolatedAsyncioTestCase):

    async def test_dropdown_shows_date_and_channel(self):
        Connector.db = mongomock.MongoClient().reminderBot
        ctx = SimpleNamespace(author=SimpleNamespace(id=3), guild=SimpleNamespace(id=1, name='Test'), bot=None)
        stm = ri.STM(ctx, Connector.Scope(is_private=False, guild_id=1, user_id=3))
        stm.tz_str = 'Europe/Paris'
        for rem in (_reminder(), _interval(paused=True)):
            if isinstance(rem, IntervalReminder):
                Connector.add_interval(rem)
            else:
                Connector.add_reminder(rem)
        view = ReminderListView(stm)
        [dropdown] = [item for item in view.children if hasattr(item, 'options')]
        self.assertEqual([o.description for o in dropdown.options],
                         ['Sun 08 Nov 09:00 · #general', '🔁 ⏸️ paused · Fri 13 Nov 07:00 · #general'])
        self.assertEqual(view.get_embed().title, 'Your reminders · Test')


if __name__ == '__main__':
    unittest.main()
