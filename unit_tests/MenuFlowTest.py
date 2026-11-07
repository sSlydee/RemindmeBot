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
        self.stm.reminders = Connector.get_scoped_reminders(self.stm.scope)
        view = ReminderListView(self.stm)
        return await self.discord.respond(view, embed=view.get_embed())

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
        self.assertIn('Only the author', self.discord.last_message().content)

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

    # ---------- delivered reminders ----------

    async def test_snooze_on_a_delivered_reminder(self):
        rem = self.add_reminder()
        view = util.interaction.SnoozeView(rem, timeout=500)
        msg = self.discord.new_message(ephemeral=False)
        msg.apply(embed=None, view=view)
        view.origin = msg
        await self.discord.click(msg, '+15m')
        self.assertEqual(len(self.stored_reminders()), 2)
        self.assertTrue(all(item.disabled for item in msg.view.children))


if __name__ == '__main__':
    unittest.main()
