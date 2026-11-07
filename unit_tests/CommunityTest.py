"""A server shared with other members (no database)"""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

import cogs.ReminderModule as rm
from cogs.ReminderCreation import ReminderCreation

USER = 3


def _not_found(code, message):
    return discord.NotFound(SimpleNamespace(status=404, reason='Not Found'), {'code': code, 'message': message})


class FindAuthorTest(unittest.IsolatedAsyncioTestCase):
    """the author of a server reminder, looked up when it is sent"""

    def guild(self, cached=None, fetched=None, error=None):
        return SimpleNamespace(get_member=lambda uid: cached if uid == USER else None,
                               fetch_member=AsyncMock(return_value=fetched, side_effect=error))

    async def test_member_in_the_cache(self):
        member = object()
        guild = self.guild(cached=member)
        self.assertIs(await rm.ReminderModule.find_author(guild, USER), member)
        guild.fetch_member.assert_not_awaited()

    async def test_member_asked_to_discord(self):
        member = object()
        self.assertIs(await rm.ReminderModule.find_author(self.guild(fetched=member), USER), member)

    async def test_author_left(self):
        guild = self.guild(error=_not_found(10007, 'Unknown Member'))
        with self.assertRaises(rm.AuthorLeft):
            await rm.ReminderModule.find_author(guild, USER)

    async def test_other_answers_are_unknown(self):
        # sent, without @everyone and role pings
        for error in (_not_found(10004, 'Unknown Guild'),
                      discord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'), 'Missing Access')):
            self.assertIsNone(await rm.ReminderModule.find_author(self.guild(error=error), USER), error)

    async def test_discord_down(self):
        # the reminder is kept and tried again
        error = discord.DiscordServerError(SimpleNamespace(status=503, reason='Service Unavailable'), 'down')
        with self.assertRaises(discord.DiscordServerError):
            await rm.ReminderModule.find_author(self.guild(error=error), USER)


class RemindPermissionTest(unittest.TestCase):
    """/remind pings others: moderators only, unless the server opens it
       (Server Settings > Integrations)
    """

    def test_remind_needs_manage_messages(self):
        self.assertEqual(ReminderCreation.remind_user.default_member_permissions,
                         discord.Permissions(manage_messages=True))

    def test_remindme_is_open_to_all(self):
        self.assertIsNone(ReminderCreation.remindme.default_member_permissions)


if __name__ == '__main__':
    unittest.main()
