"""Input checks and mentions (no database)"""
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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


class HugeDateTest(unittest.TestCase):

    def test_huge_duration_is_an_error(self):
        for text in ('999999999d', '99999999999h'):
            at, info = p.parse(text, NOW, TZ)
            self.assertEqual(at, NOW, text)
            self.assertIn('too far', info)


def _reminder(target=3):
    return Reminder({'msg': 'x', 'g_id': '1', 'ch_id': '2', 'author': '3', 'target': str(target)})


def _not_found():
    return discord.NotFound(SimpleNamespace(status=404, reason='Not Found'), 'Unknown Member')


class MentionTest(unittest.IsolatedAsyncioTestCase):
    """@everyone, @here and roles in a reminder ping only if its author may ping them"""

    def channel(self, mention_everyone, member_found=True, role=None):
        member = object()
        guild = SimpleNamespace(
            get_member=lambda uid: member if member_found else None,
            fetch_member=AsyncMock(side_effect=_not_found()),
            get_role=lambda rid: role if role is not None and rid == 99 else None)
        return SimpleNamespace(guild=guild,
                               permissions_for=lambda m: discord.Permissions(mention_everyone=mention_everyone))

    async def test_author_may_mention_everyone(self):
        mentions = await rm.ReminderModule.allowed_mentions(_reminder(), self.channel(True))
        self.assertTrue(mentions.everyone)
        self.assertTrue(mentions.roles)

    async def test_author_may_not(self):
        mentions = await rm.ReminderModule.allowed_mentions(_reminder(), self.channel(False))
        self.assertFalse(mentions.everyone)
        self.assertEqual(mentions.roles, [])
        self.assertTrue(mentions.users)

    async def test_author_left_the_server(self):
        mentions = await rm.ReminderModule.allowed_mentions(_reminder(), self.channel(True, member_found=False))
        self.assertFalse(mentions.everyone)

    async def test_mentionable_target_role(self):
        role = SimpleNamespace(id=99, mentionable=True)
        mentions = await rm.ReminderModule.allowed_mentions(_reminder(target=99), self.channel(False, role=role))
        self.assertFalse(mentions.everyone)
        self.assertEqual(mentions.roles, [role])

    async def test_not_mentionable_target_role(self):
        role = SimpleNamespace(id=99, mentionable=False)
        mentions = await rm.ReminderModule.allowed_mentions(_reminder(target=99), self.channel(False, role=role))
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
