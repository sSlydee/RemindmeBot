"""Reminders sent late say so; reminders of a server sent by DM

The tests use an in-memory database (mongomock) and fakediscord.py.
"""
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

try:
    import mongomock
except ImportError:  # pragma: no cover
    mongomock = None

import discord

import cogs.ReminderModule as rm
from cogs.ReminderListing import ReminderListing, ReminderListView
from cogs.ReminderCreation import ReminderCreation
from cogs.SettingsModule import SettingsView
import lib.timeutil as timeutil
from lib.Connector import Connector
from lib.Reminder import Reminder, IntervalReminder
import util.reminderInteraction as ri
from unit_tests.fakediscord import FakeDiscord, OWNER
from unit_tests.CreationTest import FakeContext

GUILD = 1
USER = 3
ROLE = 444
PICK_REMINDER = 'Select a reminder to edit'


def _reminder(target=USER, mention=None, by_dm=False, **fields):
    data = {'msg': 'hello', 'g_id': str(GUILD), 'ch_id': '2', 'ch_name': 'general',
            'author': str(USER), 'target': str(target), 'target_mention': mention or f'<@{target}>',
            'by_dm': by_dm}
    data.update(fields)
    rem = Reminder(data)
    rem._id = 'id'
    return rem


class LateTextTest(unittest.IsolatedAsyncioTestCase):

    async def test_embed_and_text(self):
        rem = _reminder()
        rem.late_due_at = datetime(2026, 11, 10, 8, 0)
        ts = int(timeutil.utc_timestamp(datetime(2026, 11, 10, 8, 0)))
        eb = await rem.get_embed(client=None)
        [field] = [f for f in eb.fields if f.name == '⏰ Sent late']
        self.assertIn(f'Due <t:{ts}:f>', field.value)
        self.assertIn(f'⏰ Due <t:{ts}:f>', await rem.get_string())
        # bare reminders stay bare
        self.assertNotIn('⏰', await rem.get_string(barebone=True))

    async def test_on_time(self):
        rem = _reminder()
        eb = await rem.get_embed(client=None)
        self.assertEqual([f.name for f in eb.fields if f.name.startswith('⏰')], [])
        self.assertNotIn('⏰', await rem.get_string())

    def test_kinds_of_target(self):
        self.assertTrue(_reminder().is_for_a_member())
        self.assertTrue(_reminder(mention=f'<@!{USER}>').is_for_a_member())
        self.assertFalse(_reminder(target=ROLE, mention=f'<@&{ROLE}>').is_for_a_member())
        self.assertFalse(_reminder(target=GUILD, mention='@everyone').is_for_a_member())


@unittest.skipUnless(mongomock, 'needs mongomock')
class LateDeliveryTest(unittest.IsolatedAsyncioTestCase):
    """the loops mark a reminder sent more than LATE_AFTER after its date"""

    def setUp(self):
        Connector.db = mongomock.MongoClient().reminderBot
        Connector.set_timezone(GUILD, 'Europe/Paris')
        self.cog = rm.ReminderModule.__new__(rm.ReminderModule)
        self.cog.client = SimpleNamespace(latency=0.05, is_ready=lambda: True, is_closed=lambda: False)
        self.cog.heartbeat = SimpleNamespace(push=AsyncMock())
        now = timeutil.utcnow()
        self.cog.loop_done = {'reminders': now, 'intervals': now}
        self.sent = []
        self.cog.print_reminder = AsyncMock(side_effect=lambda rem: self.sent.append((rem.msg, rem.late_due_at)))

    def add(self, msg, late):
        rem = _reminder(msg=msg)
        rem._id = None
        rem.created_at = timeutil.utcnow() - timedelta(days=3)
        rem.at = timeutil.utcnow().replace(microsecond=0) - late
        rem._id = Connector.add_reminder(rem)
        return rem

    async def test_late_and_on_time(self):
        late = self.add('late', timedelta(hours=3))
        self.add('on time', timedelta(minutes=1))
        await rm.ReminderModule.check_pending_reminders.coro(self.cog)
        self.assertEqual(sorted(self.sent), [('late', late.at), ('on time', None)])

    async def test_interval_late(self):
        rem = IntervalReminder(_reminder(msg='weekly')._to_json())
        rem._id = None
        rem.created_at = timeutil.utcnow() - timedelta(days=30)
        rem.first_at = datetime(2026, 1, 1, 7, 0)
        rem.rrules = ['DTSTART:20260101T070000\nRRULE:FREQ=WEEKLY']
        due = timeutil.utcnow().replace(microsecond=0) - timedelta(hours=2)
        rem.at = due
        rem._id = Connector.add_interval(rem)
        await rm.ReminderModule.check_pending_intervals.coro(self.cog)
        self.assertEqual(self.sent, [('weekly', due)])


@unittest.skipUnless(mongomock, 'needs mongomock')
class ByDmRouteTest(unittest.IsolatedAsyncioTestCase):
    """where print_reminder sends a server reminder"""

    def setUp(self):
        Connector.db = mongomock.MongoClient().reminderBot
        self.cog = rm.ReminderModule.__new__(rm.ReminderModule)
        guild = SimpleNamespace(id=GUILD, name='Test', get_member=lambda uid: SimpleNamespace(id=uid))
        self.cog.client = SimpleNamespace(get_guild=lambda gid: guild)
        self.cog.print_reminder_dm = AsyncMock(return_value=True)
        self.cog._print_in_channel = AsyncMock()

    async def test_by_dm(self):
        await self.cog.print_reminder(_reminder(by_dm=True))
        self.cog.print_reminder_dm.assert_awaited_once()
        self.assertFalse(self.cog.print_reminder_dm.call_args.kwargs['warn'])
        self.cog._print_in_channel.assert_not_awaited()

    async def test_closed_dms_fall_back_to_the_channel(self):
        self.cog.print_reminder_dm.return_value = False
        with self.assertLogs('Remindme.Core', 'INFO') as logs:
            await self.cog.print_reminder(_reminder(by_dm=True))
        self.cog._print_in_channel.assert_awaited_once()
        self.assertIn('sent in its channel', logs.output[0])

    async def test_a_role_stays_in_the_channel(self):
        await self.cog.print_reminder(_reminder(target=ROLE, mention=f'<@&{ROLE}>', by_dm=True))
        self.cog.print_reminder_dm.assert_not_awaited()
        self.cog._print_in_channel.assert_awaited_once()

    async def test_in_the_channel(self):
        await self.cog.print_reminder(_reminder())
        self.cog.print_reminder_dm.assert_not_awaited()
        self.cog._print_in_channel.assert_awaited_once()


@unittest.skipUnless(mongomock, 'needs mongomock')
class DmTest(unittest.IsolatedAsyncioTestCase):
    """print_reminder_dm says if it was sent; warn=False leaves the author alone"""

    def setUp(self):
        Connector.db = mongomock.MongoClient().reminderBot
        self.cog = rm.ReminderModule.__new__(rm.ReminderModule)
        self.cog.warn_author_dm = AsyncMock()
        self.dm = SimpleNamespace(send=AsyncMock())
        user = SimpleNamespace(id=USER, bot=False, create_dm=AsyncMock(return_value=self.dm))
        self.cog.client = SimpleNamespace(fetch_user=AsyncMock(return_value=user))

    async def test_sent(self):
        self.assertTrue(await self.cog.print_reminder_dm(_reminder(by_dm=True), warn=False))
        self.dm.send.assert_awaited()

    async def test_closed_dms(self):
        self.dm.send.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'), 'closed')
        with self.assertLogs('Remindme.Core', 'WARNING'):
            self.assertFalse(await self.cog.print_reminder_dm(_reminder(by_dm=True), warn=False))
        self.cog.warn_author_dm.assert_not_awaited()

    async def test_closed_dms_warn_by_default(self):
        self.dm.send.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'), 'closed')
        with self.assertLogs('Remindme.Core', 'WARNING'):
            self.assertFalse(await self.cog.print_reminder_dm(_reminder()))
        self.cog.warn_author_dm.assert_awaited_once()


@unittest.skipUnless(mongomock, 'needs mongomock')
class ByDmSettingTest(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        Connector.db = mongomock.MongoClient().reminderBot
        Connector.set_timezone(GUILD, 'Europe/Paris')
        self.discord = FakeDiscord()

    async def remindme(self, target=None):
        ctx = FakeContext(self.discord)
        await ReminderCreation(client=None).process_reminder(ctx, ctx.author, target or ctx.author, 'in 2 days',
                                                             'hello', channel=ctx.channel)
        [doc] = list(Connector.db.reminders.find({}))
        return doc

    async def test_off_by_default(self):
        self.assertFalse(Connector.get_dm_delivery(GUILD))
        self.assertFalse((await self.remindme())['by_dm'])

    async def test_new_reminders_by_dm(self):
        Connector.set_dm_delivery(GUILD, True)
        self.assertTrue((await self.remindme())['by_dm'])

    async def test_not_for_a_role(self):
        Connector.set_dm_delivery(GUILD, True)
        role = SimpleNamespace(id=ROLE, name='team', mention=f'<@&{ROLE}>')
        self.assertFalse((await self.remindme(target=role))['by_dm'])

    async def test_settings_buttons(self):
        admin = SimpleNamespace(id=OWNER)  # not a server member: the settings are theirs
        view = SettingsView(Connector.Scope(is_private=False, guild_id=GUILD, user_id=OWNER), admin)
        self.assertTrue(view.deliver_channel.disabled)
        msg = await self.discord.respond(view, embed=view.get_embed())
        await self.discord.click(msg, 'By DM')
        self.assertTrue(Connector.get_dm_delivery(GUILD))
        self.assertTrue(view.deliver_dm.disabled)
        await self.discord.click(msg, 'In the channel')
        self.assertFalse(Connector.get_dm_delivery(GUILD))


@unittest.skipUnless(mongomock, 'needs mongomock')
class ByDmMenuTest(unittest.IsolatedAsyncioTestCase):
    """the 'Send by DM' button of Edit Channel, and the list"""

    def setUp(self):
        Connector.db = mongomock.MongoClient().reminderBot
        Connector.set_timezone(GUILD, 'Europe/Paris')
        self.discord = FakeDiscord()
        ctx = SimpleNamespace(author=SimpleNamespace(id=OWNER), guild=SimpleNamespace(id=GUILD, name='Test'), bot=None)
        self.stm = ri.STM(ctx, Connector.Scope(is_private=False, guild_id=GUILD, user_id=OWNER))
        self.stm.tz_str = 'Europe/Paris'

    def add(self, target=OWNER, mention=None):
        rem = _reminder(target=target, mention=mention, author=str(OWNER))
        rem._id = None
        rem.created_at = timeutil.utcnow()
        rem.at = timeutil.utcnow().replace(second=0, microsecond=0) + timedelta(days=2)
        rem._id = Connector.add_reminder(rem)

    async def open_channel_menu(self):
        self.stm.reminders = Connector.get_scoped_reminders(self.stm.scope)
        view = ReminderListView(self.stm)
        msg = await self.discord.respond(view, embed=view.get_embed(), deferred=True)
        await self.discord.choose(msg, PICK_REMINDER, '0')
        await self.discord.click(msg, 'Edit Channel')
        return msg

    async def test_send_by_dm_and_back(self):
        self.add()
        msg = await self.open_channel_menu()
        self.assertEqual(msg.title, 'Select a new channel')
        await self.discord.click(msg, 'Send by DM')
        self.assertIsInstance(msg.view, ri.ReminderEditView)
        self.assertTrue(Connector.db.reminders.find_one({})['by_dm'])

        await self.discord.click(msg, 'Edit Channel')
        self.assertIn('by DM', next(f.value for f in msg.embed.fields if f.name == 'Sent'))
        await self.discord.click(msg, 'Send in the channel')
        self.assertFalse(Connector.db.reminders.find_one({})['by_dm'])

    async def test_not_for_a_role(self):
        self.add(target=ROLE, mention=f'<@&{ROLE}>')
        msg = await self.open_channel_menu()
        self.assertTrue(msg.button('Send by DM').disabled)

    def test_list_entry(self):
        rem = _reminder(by_dm=True)
        rem.at = datetime(2026, 11, 8, 8, 0)
        self.assertIn('· by DM', ReminderListing._entry(1, rem, USER))
        self.assertNotIn('<#2>', ReminderListing._entry(1, rem, USER))


if __name__ == '__main__':
    unittest.main()
