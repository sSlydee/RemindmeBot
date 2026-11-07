"""The buttons under delivered reminders (snooze, skip, delete)

They have no view in memory: clicks go through util.reminderButtons.handle_click,
like the bot's on_interaction listener. See fakediscord.py.
"""
import unittest
from datetime import datetime, timedelta

try:
    import mongomock
except ImportError:  # pragma: no cover
    mongomock = None

from dateutil import tz

import lib.timeutil as timeutil
from lib.Connector import Connector
from lib.Reminder import Reminder, IntervalReminder
import util.reminderButtons as buttons
from unit_tests.fakediscord import FakeDiscord, ChatMessage, OWNER, STRANGER

GUILD = 1


@unittest.skipUnless(mongomock, 'needs mongomock')
class ReminderButtonsTest(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        Connector.db = mongomock.MongoClient().reminderBot
        Connector.set_timezone(GUILD, 'Europe/Paris')
        Connector.set_timezone(STRANGER, 'America/New_York')
        self.discord = FakeDiscord()

    def delivered(self, msg='take out the trash') -> Reminder:
        rem = Reminder({'msg': msg, 'g_id': str(GUILD), 'ch_id': '2', 'ch_name': 'general',
                        'author': str(OWNER), 'target': str(OWNER), 'target_mention': f'<@{OWNER}>'})
        rem.created_at = timeutil.utcnow() - timedelta(days=1)
        rem.at = timeutil.utcnow() - timedelta(minutes=1)
        rem._id = Connector.add_reminder(rem)
        Connector.archive_delivered(rem)
        return rem

    def interval(self) -> IntervalReminder:
        rem = IntervalReminder({'msg': 'weekly', 'g_id': str(GUILD), 'ch_id': '2',
                                'author': str(OWNER), 'target': str(OWNER)})
        rem.first_at = datetime(2026, 1, 2, 7, 0)
        rem.rrules = ['DTSTART:20260102T070000\nRRULE:FREQ=WEEKLY;BYDAY=FR']
        rem.at = rem.next_trigger(timeutil.utcnow(), tz_str='Europe/Paris')
        rem._id = Connector.add_interval(rem)
        return rem

    def message(self, rem) -> ChatMessage:
        msg = self.discord.new_message(ephemeral=False)
        msg.apply(view=buttons.delivered_view(rem))
        return msg

    def snoozes(self):
        return [Reminder(doc) for doc in Connector.db.reminders.find({})]

    # ---------- the buttons ----------

    async def test_buttons_survive_a_restart(self):
        rem = self.delivered()
        view = buttons.delivered_view(rem)
        # nothing to keep in memory: the custom_id says it all
        self.assertIsNone(view.timeout)
        self.assertFalse(view._store)
        for item in view.children:
            self.assertEqual(buttons.parse_custom_id(item.custom_id)[1:], ('r', rem._id))

    def test_other_components_are_ignored(self):
        self.assertIsNone(buttons.parse_custom_id('d1d0b7c4f6a1'))
        self.assertIsNone(buttons.parse_custom_id('rm:10m:r:not-an-id'))

    async def test_interval_has_skip_and_delete(self):
        labels = [item.label or str(item.emoji) for item in buttons.delivered_view(self.interval()).children]
        self.assertEqual(labels, ['+10 min', '+1 hour', 'Tomorrow 9:00', 'Other…', 'Skip next', '🗑️'])

    # ---------- snooze ----------

    async def test_snooze_ten_minutes(self):
        msg = self.message(self.delivered())
        before = timeutil.utcnow()
        await self.discord.press(msg, '+10 min')

        [snoozed] = self.snoozes()
        self.assertTrue(snoozed.msg.endswith('(snoozed)'))
        self.assertAlmostEqual((snoozed.at - before).total_seconds(), 600, delta=5)
        self.assertEqual(snoozed.ch_id, 2)
        # the snooze buttons are done, the used one is green
        self.assertTrue(all(item.disabled for item in msg.view.children))
        self.assertIn('Snoozed until', self.discord.last_message().content)

    async def test_snooze_tomorrow_9_in_the_server_timezone(self):
        msg = self.message(self.delivered())
        await self.discord.press(msg, 'Tomorrow 9:00')
        [snoozed] = self.snoozes()
        local = snoozed.at.replace(tzinfo=tz.UTC).astimezone(tz.gettz('Europe/Paris'))
        self.assertEqual((local.hour, local.minute), (9, 0))
        today = timeutil.utcnow().replace(tzinfo=tz.UTC).astimezone(tz.gettz('Europe/Paris')).date()
        self.assertEqual(local.date(), today + timedelta(days=1))

    async def test_snooze_until_a_typed_time(self):
        msg = self.message(self.delivered())
        await self.discord.press(msg, 'Other…')
        before = timeutil.utcnow()
        await self.discord.submit('in 2 hours')
        [snoozed] = self.snoozes()
        self.assertAlmostEqual((snoozed.at - before).total_seconds(), 7200, delta=5)

    async def test_snooze_with_a_wrong_time(self):
        msg = self.message(self.delivered())
        for text in ('blah', 'every friday', 'yesterday'):
            await self.discord.press(msg, 'Other…')
            await self.discord.submit(text)
            self.assertEqual(self.snoozes(), [], text)
        self.assertFalse(any(item.disabled for item in msg.view.children))

    async def test_someone_else_snoozes_for_themselves(self):
        msg = self.message(self.delivered())
        await self.discord.press(msg, 'Tomorrow 9:00', user_id=STRANGER)

        [snoozed] = self.snoozes()
        self.assertEqual((snoozed.author, snoozed.target, snoozed.g_id), (STRANGER, STRANGER, None))
        # 9:00 in their own timezone
        local = snoozed.at.replace(tzinfo=tz.UTC).astimezone(tz.gettz('America/New_York'))
        self.assertEqual(local.hour, 9)
        # the buttons stay for the others
        self.assertFalse(any(item.disabled for item in msg.view.children))
        self.assertIn('your DMs', self.discord.last_message().content)

    async def test_snooze_a_repeating_reminder(self):
        msg = self.message(self.interval())
        await self.discord.press(msg, '+1 hour')
        [snoozed] = self.snoozes()
        self.assertIs(type(snoozed), Reminder)
        # skip and delete stay usable
        self.assertFalse(msg.button('Skip next').disabled)

    async def test_reminder_gone(self):
        rem = self.delivered()
        msg = self.message(rem)
        Connector.db.delivered.delete_many({})
        await self.discord.press(msg, '+10 min')
        self.assertIn('gone', self.discord.last_message().content)

    # ---------- skip / delete ----------

    async def test_skip_next(self):
        rem = self.interval()
        msg = self.message(rem)
        await self.discord.press(msg, 'Skip next')
        stored = Connector.get_interval_by_id(rem._id)
        self.assertEqual(len(stored.exdates), 1)
        self.assertEqual(stored.at - rem.at, timedelta(days=7))
        self.assertIn('Skipped', self.discord.last_message().content)

    async def test_only_the_author_skips_or_deletes(self):
        rem = self.interval()
        msg = self.message(rem)
        await self.discord.press(msg, 'Skip next', user_id=STRANGER)
        await self.discord.press(msg, emoji='🗑️', user_id=STRANGER)
        stored = Connector.get_interval_by_id(rem._id)
        self.assertEqual((stored.exdates, stored.at), ([], rem.at))

    async def test_delete(self):
        rem = self.interval()
        msg = self.message(rem)
        await self.discord.press(msg, emoji='🗑️')
        self.assertIsNone(Connector.get_interval_by_id(rem._id))
        self.assertEqual(msg.title, 'Deleted Reminder')
        self.assertTrue(all(item.disabled for item in msg.view.children))

    # ---------- kept a week ----------

    def test_delivered_reminders_are_kept_a_week(self):
        rem = self.delivered()
        old = self.delivered('old')
        Connector.db.delivered.update_one({'_id': old._id}, {'$set': {
            'delivered_at': timeutil.utc_timestamp(timeutil.utcnow() - timedelta(days=8))}})
        Connector.delete_delivered_before(timeutil.utc_timestamp(timeutil.utcnow() - buttons.DELIVERED_KEEP))
        self.assertIsNotNone(Connector.get_delivered(rem._id))
        self.assertIsNone(Connector.get_delivered(old._id))


if __name__ == '__main__':
    unittest.main()
