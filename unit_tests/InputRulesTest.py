"""Input checks and mentions (no database)"""
import time
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import discord

import lib.input_parser as p
from lib.Connector import Connector
from lib.Reminder import Reminder
import util.reminderInteraction as ri
from util.verboseErrors import VerboseErrors
import cogs.ReminderModule as rm

TZ = 'Europe/Paris'
NOW = datetime(2026, 11, 6, 13, 3, 27)


class PastedRuleTest(unittest.TestCase):
    """a DTSTART with a timezone is converted into the local time of the server"""

    def test_utc_dtstart(self):
        rule, err = p.rrule_normalize('DTSTART:20261110T090000Z\nRRULE:FREQ=WEEKLY;BYDAY=TU', NOW, TZ)
        self.assertIsNone(err)
        # 09:00 UTC = 10:00 in Paris
        self.assertEqual(rule.after(datetime(2026, 11, 7)), datetime(2026, 11, 10, 10, 0))

    def test_tzid_dtstart(self):
        rule, err = p.rrule_normalize('DTSTART;TZID=America/New_York:20261110T090000\nRRULE:FREQ=WEEKLY', NOW, TZ)
        self.assertIsNone(err)
        self.assertEqual(rule.after(datetime(2026, 11, 7)), datetime(2026, 11, 10, 15, 0))

    def test_tzid_in_lower_case(self):
        rule, err = p.rrule_normalize('dtstart;tzid=america/new_york:20261110t090000\nrrule:freq=weekly', NOW, TZ)
        self.assertIsNone(err)
        self.assertEqual(rule.after(datetime(2026, 11, 7)), datetime(2026, 11, 10, 15, 0))

    def test_unknown_tzid(self):
        rule, err = p.rrule_normalize('DTSTART;TZID=Mars/Olympus:20261110T090000\nRRULE:FREQ=WEEKLY', NOW, TZ)
        self.assertIsNone(rule)
        self.assertIn('Mars/Olympus', err)

    def test_pasted_on_one_line(self):
        # the popup is a single-line field: line breaks arrive as spaces, or are dropped
        for text in ('DTSTART:20261110T090000Z RRULE:FREQ=WEEKLY;BYDAY=TU',
                     'DTSTART:20261110T090000ZRRULE:FREQ=WEEKLY;BYDAY=TU',
                     'dtstart:20261110t090000z rrule:freq=weekly;byday=tu'):
            rule, err = p.rrule_normalize(text, NOW, TZ)
            self.assertIsNone(err, text)
            self.assertEqual(rule.after(datetime(2026, 11, 7)), datetime(2026, 11, 10, 10, 0), text)

    def test_tzid_on_one_line(self):
        rule, err = p.rrule_normalize('DTSTART;TZID=America/New_York:20261110T090000 RRULE:FREQ=WEEKLY', NOW, TZ)
        self.assertIsNone(err)
        self.assertIsNone(rule._dtstart.tzinfo)
        self.assertEqual(rule.after(datetime(2026, 11, 7)), datetime(2026, 11, 10, 15, 0))

    def test_utc_until_on_one_line(self):
        rule, err = p.rrule_normalize('DTSTART:20261110T090000Z RRULE:FREQ=WEEKLY;UNTIL=20261124T090000Z', NOW, TZ)
        self.assertIsNone(err)
        self.assertEqual(list(rule), [datetime(2026, 11, 10, 10), datetime(2026, 11, 17, 10), datetime(2026, 11, 24, 10)])

    def test_dtstart_without_timezone_is_local(self):
        rule, err = p.rrule_normalize('DTSTART:20261110T090000\nRRULE:FREQ=WEEKLY', NOW, TZ)
        self.assertEqual(rule.after(datetime(2026, 11, 7)), datetime(2026, 11, 10, 9, 0))


class RepeatLimitTest(unittest.TestCase):

    def test_list_of_minutes_is_refused(self):
        rule, err = p.rrule_normalize('FREQ=HOURLY;BYMINUTE=0,5,10,15,20,25,30,35,40,45,50,55', NOW, TZ)
        self.assertIsNone(rule)
        self.assertIn('10 minutes', err)

    def test_two_times_a_day_are_fine(self):
        rule, err = p.rrule_normalize('FREQ=DAILY;BYHOUR=9;BYMINUTE=0,30', NOW, TZ)
        self.assertIsNone(err)

    def test_hourly_is_fine(self):
        rule, err = p.rrule_normalize('FREQ=HOURLY', NOW, TZ)
        self.assertIsNone(err)


class ImpossibleRuleTest(unittest.TestCase):
    """a rule without any date is refused quickly (dateutil would search until 9999)"""

    def test_30th_of_february(self):
        for text in ('FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30', 'FREQ=HOURLY;BYMONTH=2;BYMONTHDAY=30'):
            started = time.monotonic()
            rule, err = p.rrule_normalize(text, NOW, TZ)
            self.assertLess(time.monotonic() - started, 2, text)
            self.assertIsNone(rule, text)

    def test_sixth_monday(self):
        rule, err = p.rrule_normalize('FREQ=MONTHLY;BYDAY=MO;BYSETPOS=6', NOW, TZ)
        self.assertIsNone(rule)

    def test_29th_of_february_is_fine(self):
        rule, err = p.rrule_normalize('FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=29', NOW, TZ)
        self.assertEqual(rule.after(NOW), datetime(2028, 2, 29, 13, 3))

    def test_until_in_the_past(self):
        rule, err = p.rrule_normalize('FREQ=DAILY;UNTIL=20200101', NOW, TZ)
        self.assertIsNone(rule)
        self.assertIn('no date in the future', err)


class HugeDateTest(unittest.TestCase):

    def test_huge_duration_is_an_error(self):
        for text in ('999999999d', '99999999999h'):
            at, info = p.parse(text, NOW, TZ)
            self.assertEqual(at, NOW, text)
            self.assertIn('too far', info)


def _reminder(target=3):
    return Reminder({'msg': 'x', 'g_id': '1', 'ch_id': '2', 'author': '3', 'target': str(target)})


AUTHOR = object()  # the author, as a member of the server


class MentionTest(unittest.TestCase):
    """@everyone, @here and roles in a reminder ping only if its author may ping them"""

    def channel(self, mention_everyone, role=None):
        guild = SimpleNamespace(get_role=lambda rid: role if role is not None and rid == 99 else None)
        return SimpleNamespace(guild=guild,
                               permissions_for=lambda m: discord.Permissions(mention_everyone=mention_everyone))

    def test_author_may_mention_everyone(self):
        mentions = rm.ReminderModule.allowed_mentions(_reminder(), self.channel(True), AUTHOR)
        self.assertTrue(mentions.everyone)
        self.assertTrue(mentions.roles)

    def test_author_may_not(self):
        mentions = rm.ReminderModule.allowed_mentions(_reminder(), self.channel(False), AUTHOR)
        self.assertFalse(mentions.everyone)
        self.assertEqual(mentions.roles, [])
        self.assertTrue(mentions.users)

    def test_author_unknown(self):
        mentions = rm.ReminderModule.allowed_mentions(_reminder(), self.channel(True), None)
        self.assertFalse(mentions.everyone)

    def test_mentionable_target_role(self):
        role = SimpleNamespace(id=99, mentionable=True)
        mentions = rm.ReminderModule.allowed_mentions(_reminder(target=99), self.channel(False, role=role), AUTHOR)
        self.assertFalse(mentions.everyone)
        self.assertEqual(mentions.roles, [role])

    def test_not_mentionable_target_role(self):
        role = SimpleNamespace(id=99, mentionable=False)
        mentions = rm.ReminderModule.allowed_mentions(_reminder(target=99), self.channel(False, role=role), AUTHOR)
        self.assertEqual(mentions.roles, [])


class ChannelPickerTest(unittest.IsolatedAsyncioTestCase):
    """a reminder can't be moved to a channel its author can't post in"""

    async def check(self, perms):
        ctx = SimpleNamespace(author=MagicMock(spec=discord.Member), bot=None)
        ctx.author.id = 3
        stm = ri.STM(ctx, Connector.Scope(guild_id=1, user_id=3))
        view = ri.ReminderChannelEdit(_reminder(), stm)
        channel = SimpleNamespace(name='secret', permissions_for=lambda member: perms)
        with patch.object(Connector, 'get_reminder_type', return_value=Connector.ReminderType.HYBRID), \
             patch.object(VerboseErrors, 'can_send_messages', return_value=True):
            return await view._check_channel(channel)

    async def test_author_cannot_post(self):
        error = await self.check(discord.Permissions(view_channel=True, send_messages=False))
        self.assertIn('yourself', error.description)

    async def test_author_cannot_see(self):
        error = await self.check(discord.Permissions(view_channel=False, send_messages=True))
        self.assertIsNotNone(error)

    async def test_author_can_post(self):
        self.assertIsNone(await self.check(discord.Permissions(view_channel=True, send_messages=True)))


if __name__ == '__main__':
    unittest.main()
