"""The menus of /reminder_list and /remindme, clicked through like on Discord

See fakediscord.py. The database is an in-memory MongoDB (mongomock).
"""
import asyncio
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

try:
    import mongomock
except ImportError:  # pragma: no cover
    mongomock = None

import lib.timeutil as timeutil
import lib.ReminderRepeater
from lib.Connector import Connector
from lib.Reminder import Reminder, IntervalReminder
import util.interaction
import util.reminderInteraction as ri
from cogs.ReminderListing import ReminderListView
from cogs.ReminderCreation import NewReminderView
import unit_tests.fakediscord as fakediscord
from unit_tests.fakediscord import FakeDiscord, ChatMessage, OWNER, STRANGER

GUILD = 1
PICK_REMINDER = 'Select a reminder to edit'
PICK_RULE = 'Select a rule/date for more info'
QUICK_REPEAT = 'Quick repeat...'


@unittest.skipUnless(mongomock, 'needs mongomock')
class MenuFlowTest(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        Connector.db = mongomock.MongoClient().reminderBot
        Connector.set_timezone(GUILD, 'Europe/Paris')
        self.discord = FakeDiscord()
        ctx = SimpleNamespace(author=SimpleNamespace(id=OWNER),
                              guild=SimpleNamespace(id=GUILD, name='Test'),
                              bot=None)
        self.stm = ri.STM(ctx, Connector.Scope(is_private=False, guild_id=GUILD, user_id=OWNER))
        self.stm.tz_str = 'Europe/Paris'

    # ---------- helpers ----------

    def add_reminder(self, msg='take out the trash', days=2) -> Reminder:
        rem = Reminder({'msg': msg, 'g_id': str(GUILD), 'ch_id': '2', 'ch_name': 'general',
                        'author': str(OWNER), 'target': str(OWNER), 'target_mention': f'<@{OWNER}>'})
        rem.created_at = timeutil.utcnow()
        rem.at = timeutil.utcnow().replace(second=0, microsecond=0) + timedelta(days=days)
        rem._id = Connector.add_reminder(rem)
        return rem

    def add_weekly_interval(self) -> IntervalReminder:
        return lib.ReminderRepeater.add_rules(self.add_reminder(), rrule='DTSTART:20260101T070000\nRRULE:FREQ=WEEKLY')

    async def open_list(self) -> ChatMessage:
        # /reminder_list defers, then answers with a followup
        self.stm.reminders = Connector.get_scoped_reminders(self.stm.scope)
        view = ReminderListView(self.stm)
        return await self.discord.respond(view, embed=view.get_embed(), deferred=True)

    async def open_interval_menu(self) -> ChatMessage:
        """list -> first reminder -> Set Interval (Edit Interval)"""
        msg = await self.open_list()
        await self.discord.choose(msg, PICK_REMINDER, '0')
        await self.discord.click(msg, msg.view.set_interval.label)
        return msg

    def stored_intervals(self):
        return list(Connector.db.intervals.find({}))

    def stored_reminders(self):
        return list(Connector.db.reminders.find({}))

    # ---------- /reminder_list ----------

    async def test_menus_stay_on_one_message(self):
        self.add_reminder()
        msg = await self.open_list()
        await self.discord.choose(msg, PICK_REMINDER, '0')
        self.assertIsInstance(msg.view, ri.ReminderEditView)
        await self.discord.click(msg, 'Return')
        self.assertIsInstance(msg.view, ReminderListView)
        self.assertEqual(len(self.discord.messages), 1)

    async def test_add_single_date_is_saved(self):
        self.add_reminder()
        msg = await self.open_interval_menu()
        self.assertEqual(msg.title, 'Add new rules')

        await self.discord.click(msg, 'Add Single Date')
        await self.discord.submit('in 5 days')
        self.assertEqual(msg.title, 'New single date')
        await self.discord.click(msg, 'Confirm')

        # back on the rule menu, the reminder became an interval with that date
        self.assertEqual(msg.title, 'Add new rules')
        self.assertEqual(self.stored_reminders(), [])
        [interval] = self.stored_intervals()
        self.assertEqual(len(interval['rdates']), 1)

        # Return twice: the edit menu (now an interval), then the list
        await self.discord.click(msg, 'Return')
        self.assertIsInstance(msg.view, ri.ReminderEditView)
        self.assertEqual(msg.view.set_interval.label, 'Edit Interval')
        await self.discord.click(msg, 'Return')
        self.assertIsInstance(msg.view, ReminderListView)
        self.assertEqual(len(self.discord.messages), 1)

    async def test_add_exception_date_is_saved(self):
        self.add_weekly_interval()
        msg = await self.open_interval_menu()
        self.assertIsInstance(msg.view, ri.ReminderIntervalModifyView)

        await self.discord.click(msg, 'Add New Rule')
        await self.discord.click(msg, 'Add Exception Date')
        await self.discord.submit('in 7 days')
        await self.discord.click(msg, 'Confirm')

        self.assertEqual(msg.title, 'Add new rules')
        [interval] = self.stored_intervals()
        self.assertEqual(len(interval['exdates']), 1)

        await self.discord.click(msg, 'Return')
        self.assertIsInstance(msg.view, ri.ReminderIntervalModifyView)
        await self.discord.click(msg, 'Return')
        self.assertIsInstance(msg.view, ri.ReminderEditView)

    async def test_bad_single_date_shows_an_error(self):
        self.add_reminder()
        msg = await self.open_interval_menu()
        for text in ('blah', 'every friday', 'yesterday'):
            await self.discord.click(msg, 'Add Single Date')
            await self.discord.submit(text)
            self.assertEqual(msg.title, 'Invalid input date', text)
            await self.discord.click(msg, 'Confirm')
            self.assertEqual(msg.title, 'Add new rules')
        self.assertEqual(self.stored_intervals(), [])

    async def test_repeating_rule_in_plain_words(self):
        self.add_reminder()
        msg = await self.open_interval_menu()
        await self.discord.click(msg, 'Add Repeating Rule')
        await self.discord.submit('every saturday')
        self.assertEqual(msg.title, 'New Rrule')
        await self.discord.click(msg, 'Confirm')

        self.assertEqual(msg.title, 'Add new rules')
        [interval] = self.stored_intervals()
        self.assertIn('BYDAY=SA', interval['rrules'][0])

    async def test_bad_rule_shows_an_error(self):
        self.add_reminder()
        msg = await self.open_interval_menu()
        await self.discord.click(msg, 'Add Repeating Rule')
        await self.discord.submit('blah blah')
        self.assertEqual(msg.title, 'Invalid rrule')
        await self.discord.click(msg, 'Confirm')
        self.assertEqual(msg.title, 'Add new rules')
        self.assertEqual(self.stored_intervals(), [])

    async def test_rule_without_future_date(self):
        self.add_reminder()
        msg = await self.open_interval_menu()
        await self.discord.click(msg, 'Add Repeating Rule')
        await self.discord.submit('FREQ=DAILY;UNTIL=20200101')
        self.assertEqual(msg.title, 'Invalid rrule')
        self.assertIn('no date in the future', msg.embed.description)

    async def test_pasted_rule_keeps_its_timezone(self):
        self.add_reminder()
        msg = await self.open_interval_menu()
        await self.discord.click(msg, 'Add Repeating Rule')
        await self.discord.submit('DTSTART;TZID=America/New_York:20261110T090000\nRRULE:FREQ=WEEKLY')
        self.assertEqual(msg.title, 'New Rrule')
        await self.discord.click(msg, 'Confirm')
        [interval] = self.stored_intervals()
        # 09:00 in New York is 15:00 in Paris, the rule frame
        self.assertIn('T150000', interval['rrules'][0])

    async def test_rule_pasted_on_one_line(self):
        # the popup field is a single line: the generator's line break becomes a space
        self.add_reminder()
        msg = await self.open_interval_menu()
        await self.discord.click(msg, 'Add Repeating Rule')
        await self.discord.submit('DTSTART:20261110T090000Z\nRRULE:FREQ=WEEKLY;BYDAY=TU')
        self.assertEqual(msg.title, 'New Rrule')
        await self.discord.click(msg, 'Confirm')
        [interval] = self.stored_intervals()
        # 09:00 UTC is 10:00 in Paris, the rule frame
        self.assertIn('T100000', interval['rrules'][0])

    async def test_two_menus_on_the_same_reminder(self):
        self.add_reminder()
        first = await self.open_interval_menu()
        second = await self.open_interval_menu()

        await self.discord.choose(first, QUICK_REPEAT, 'weekly')
        await self.discord.click(first, 'Confirm')
        # the second menu still shows the single reminder, which is now an interval
        await self.discord.choose(second, QUICK_REPEAT, 'daily')
        await self.discord.click(second, 'Confirm')

        self.assertEqual(second.title, 'Menu closed')
        self.assertIsNone(second.view)
        [interval] = self.stored_intervals()
        self.assertIn('FREQ=WEEKLY', interval['rrules'][0])

    async def test_rule_deleted_in_another_menu(self):
        self.add_weekly_interval()
        first = await self.open_interval_menu()
        second = await self.open_interval_menu()
        for msg in (first, second):
            await self.discord.choose(msg, PICK_RULE, '0')
            await self.discord.click(msg, 'Delete Selected')
            await self.discord.click(msg, 'Confirm')
        # the first one made it a single reminder again, the second can't remove more
        self.assertEqual(second.title, 'Menu closed')
        self.assertEqual(len(self.stored_reminders()), 1)
        self.assertEqual(self.stored_intervals(), [])

    async def test_closed_popup_leaves_the_store(self):
        self.add_reminder()
        with patch.object(util.interaction, 'POPUP_TIMEOUT', 0.2):
            msg = await self.open_interval_menu()
            await self.discord.click(msg, 'Add Repeating Rule')
            self.assertEqual(len(self.discord.modal_store._modals), 1)
            await asyncio.sleep(0.4)
            await self.discord.settle()
        self.assertEqual(len(self.discord.modal_store._modals), 0)

    async def test_menu_closed_before_its_token_dies(self):
        # last edit, then a popup that is closed without submitting:
        # py-cord's timeout restarts, but the token to edit the menu doesn't
        self.add_reminder()
        with patch.object(util.interaction, 'TOKEN_LIFETIME', 0.3), \
             patch.object(fakediscord, 'TOKEN_LIFETIME', 0.5):
            msg = await self.open_list()
            list_view = msg.view
            await self.discord.choose(msg, PICK_REMINDER, '0')
            await asyncio.sleep(0.2)
            await self.discord.click(msg, 'Edit')
            await asyncio.sleep(0.2)
            await self.discord.settle()
        self.assertTrue(all(item.disabled for item in msg.view.children))
        self.assertTrue(list_view.is_finished())

    async def test_late_edit_popup_tells_what_was_not_saved(self):
        self.add_reminder('old text')
        with patch.object(util.interaction, 'MENU_TIMEOUT', 0.2):
            msg = await self.open_list()
            await self.discord.choose(msg, PICK_REMINDER, '0')
            await self.discord.click(msg, 'Edit')
            await asyncio.sleep(0.4)
            await self.discord.submit('', 'new text', 'not a url', '')
        reply = self.discord.last_message().content
        self.assertIn('Saved', reply)
        self.assertIn('not a valid URL', reply)
        self.assertEqual(self.stored_reminders()[0]['msg'], 'new text')

    async def test_abort_saves_nothing(self):
        self.add_reminder()
        msg = await self.open_interval_menu()
        await self.discord.choose(msg, QUICK_REPEAT, 'weekly')
        await self.discord.click(msg, 'Abort')
        self.assertEqual(msg.title, 'Add new rules')
        self.assertEqual(self.stored_intervals(), [])

    async def test_delete_selected_rule(self):
        self.add_weekly_interval()
        msg = await self.open_interval_menu()
        await self.discord.choose(msg, PICK_RULE, '0')
        await self.discord.click(msg, 'Delete Selected')
        self.assertEqual(msg.title, 'Danger')
        await self.discord.click(msg, 'Confirm')

        # no rule left: a single reminder again, back on the edit menu
        self.assertIsInstance(msg.view, ri.ReminderEditView)
        self.assertEqual(msg.view.set_interval.label, 'Set Interval')
        self.assertEqual(self.stored_intervals(), [])
        self.assertEqual(len(self.stored_reminders()), 1)

    async def test_delete_from_the_list(self):
        self.add_reminder('first')
        self.add_reminder('second', days=3)
        msg = await self.open_list()
        await self.discord.choose(msg, PICK_REMINDER, '0')
        await self.discord.click(msg, 'Delete')
        await self.discord.click(msg, 'Confirm')

        self.assertIsInstance(msg.view, ReminderListView)
        self.assertEqual([r['msg'] for r in self.stored_reminders()], ['second'])
        self.assertNotIn('first', msg.embed.description)

    async def test_skip_next_date(self):
        rem = self.add_weekly_interval()
        before = Connector.get_interval_by_id(rem._id).at
        msg = await self.open_list()
        await self.discord.choose(msg, PICK_REMINDER, '0')
        await self.discord.click(msg, 'Skip next')
        self.assertEqual(msg.title, 'Skip the next date?')
        await self.discord.click(msg, 'Confirm')

        self.assertIsInstance(msg.view, ri.ReminderEditView)
        stored = Connector.get_interval_by_id(rem._id)
        # the skipped date is an exclusion date now, the next one comes after it
        self.assertEqual(stored.exdates, [lib.ReminderRepeater.utc_to_rule_frame(before, GUILD)])
        self.assertGreater(stored.at, before)

    async def test_pause_and_resume(self):
        self.add_weekly_interval()
        msg = await self.open_list()
        await self.discord.choose(msg, PICK_REMINDER, '0')
        await self.discord.click(msg, 'Pause')
        self.assertTrue(self.stored_intervals()[0]['paused'])
        await self.discord.click(msg, 'Resume')
        self.assertFalse(self.stored_intervals()[0]['paused'])

    async def test_edit_popup(self):
        self.add_reminder('old text')
        msg = await self.open_list()
        await self.discord.choose(msg, PICK_REMINDER, '0')
        await self.discord.click(msg, 'Edit')
        await self.discord.submit('A title', 'new text', '', '')

        self.assertIsInstance(msg.view, ri.ReminderEditView)
        [stored] = self.stored_reminders()
        self.assertEqual((stored['title'], stored['msg']), ('A title', 'new text'))
        self.assertEqual(msg.view.reminder.msg, 'new text')

    async def test_edit_popup_after_delivery(self):
        rem = self.add_reminder('old text')
        msg = await self.open_list()
        await self.discord.choose(msg, PICK_REMINDER, '0')
        await self.discord.click(msg, 'Edit')
        Connector.delete_reminder(rem._id)  # delivered while the popup is open
        await self.discord.submit('', 'new text', '', '')

        self.assertIn('delivered or deleted', self.discord.last_message().content)
        self.assertIsInstance(msg.view, ReminderListView)

    async def test_only_the_author_can_click(self):
        self.add_reminder()
        msg = await self.open_list()
        await self.discord.choose(msg, PICK_REMINDER, '0', user_id=STRANGER)
        self.assertIsInstance(msg.view, ReminderListView)
        self.assertIn('Only the person who opened this menu', self.discord.last_message().content)

    async def test_timeout_disables_the_menu(self):
        self.add_reminder()
        with patch.object(util.interaction, 'MENU_TIMEOUT', 0.2):
            msg = await self.open_list()
            list_view = msg.view
            await self.discord.choose(msg, PICK_REMINDER, '0')
            await asyncio.sleep(0.5)
            await self.discord.settle()

        # the edit menu disabled itself, the list stays closed
        self.assertIsInstance(msg.view, ri.ReminderEditView)
        self.assertTrue(all(item.disabled for item in msg.view.children))
        self.assertTrue(list_view.is_finished())

    async def test_list_waits_for_its_sub_menu(self):
        self.add_weekly_interval()
        with patch.object(util.interaction, 'MENU_TIMEOUT', 0.3):
            msg = await self.open_list()
            list_view = msg.view
            await self.discord.choose(msg, PICK_REMINDER, '0')
            # keep using the sub menu longer than the list's own timeout
            for label in ('Pause', 'Resume', 'Pause'):
                await asyncio.sleep(0.15)
                await self.discord.click(msg, label)
            await self.discord.click(msg, 'Return')
        self.assertIs(msg.view, list_view)
        self.assertFalse(list_view.is_finished())

    async def test_errors_are_logged_and_reported(self):
        self.add_reminder()
        msg = await self.open_interval_menu()
        await self.discord.choose(msg, QUICK_REPEAT, 'weekly')
        with patch.object(lib.ReminderRepeater, 'add_rules', side_effect=RuntimeError('boom')), \
             self.assertLogs('Remindme', 'ERROR') as logs:
            await self.discord.click(msg, 'Confirm')
        self.assertIn('boom', '\n'.join(logs.output))
        self.assertIn('Something went wrong', self.discord.last_message().content)

    # ---------- /remindme ----------

    async def new_reminder_menu(self) -> ChatMessage:
        rem = self.add_reminder()
        view = NewReminderView(rem, stm=self.stm, info_str='', rrule_override=None, timeout=None)
        return await self.discord.respond(view, embed=view.get_embed(), ephemeral=False)

    async def test_new_reminder_set_interval(self):
        msg = await self.new_reminder_menu()
        await self.discord.click(msg, 'Set Interval')
        await self.discord.choose(msg, QUICK_REPEAT, 'weekly')
        await self.discord.click(msg, 'Confirm')
        await self.discord.click(msg, 'Return')

        self.assertIsInstance(msg.view, NewReminderView)
        self.assertEqual(msg.view.edit_interval.label, 'Edit Interval')
        self.assertEqual(len(self.stored_intervals()), 1)

    async def test_new_reminder_edit(self):
        msg = await self.new_reminder_menu()
        await self.discord.click(msg, 'Edit')
        await self.discord.submit('', 'changed', '', '')
        self.assertIsInstance(msg.view, NewReminderView)
        self.assertEqual(self.stored_reminders()[0]['msg'], 'changed')

    async def test_new_reminder_strangers_cant_click(self):
        msg = await self.new_reminder_menu()
        await self.discord.click(msg, emoji='🗑️', user_id=STRANGER)
        self.assertEqual(len(self.stored_reminders()), 1)
        await self.discord.click(msg, emoji='🗑️')
        self.assertEqual(self.stored_reminders(), [])


if __name__ == '__main__':
    unittest.main()
