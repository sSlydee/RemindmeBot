import asyncio
import math
from datetime import timedelta
import lib.timeutil as timeutil
import os
import logging

import aiohttp
import discord
from discord.ext import commands, tasks

from lib.Connector import Connector
from lib.Reminder import Reminder, IntervalReminder, utc_timestamp
import lib.text

import util.reminderButtons
from util.verboseErrors import VerboseErrors
from util.loops import log_errors
from util.heartbeat import Heartbeat
from util.consts import Consts


log = logging.getLogger('Remindme.Core')

# Discord unreachable (outage, network): the reminder is kept and sent on a later run
TRANSIENT_ERRORS = (discord.DiscordServerError, aiohttp.ClientError, asyncio.TimeoutError, OSError)
# ... but not forever
RETRY_FOR = timedelta(days=1)
# sent later than this after its date: it says so (the loops run about every minute)
LATE_AFTER = timedelta(minutes=5)
# after this many failures in a row Discord seems unreachable: the run stops trying
DOWN_AFTER = 3
# the monitor is only told that all is well when both delivery loops ran this recently
# (a run that found Discord unreachable doesn't count)
LOOP_STALE_AFTER = timedelta(minutes=3)

class AuthorLeft(Exception):
    """the author of a server reminder is no longer a member of that server"""


INTERVAL_BROKEN_WARNING = '\n**WARNING: the reminder couldn\'t get queued for future invocations** '\
                          '(likely due to an invalid repetition rule). **This reminder will not be delivered anymore**'


async def send_long(dest, text, **kwargs):
    """send text, split into several messages when it is longer than Discord allows

    kwargs (embed, view...) go with the last message, allowed_mentions with all of them
    """
    parts = lib.text.split_message(text or '')
    sent = None
    for i, part in enumerate(parts):
        try:
            if i == len(parts) - 1:
                sent = await dest.send(part or None, **kwargs)
            else:
                sent = await dest.send(part, allowed_mentions=kwargs.get('allowed_mentions'))
        except TRANSIENT_ERRORS:
            if i == 0:
                raise  # nothing sent: tried again later
            # sending it again would repeat the first parts and the mention
            log.error(f'reminder only partly sent ({i} of {len(parts)} messages), Discord unreachable')
            return sent
    return sent


class ReminderModule(commands.Cog):


    # =====================
    # internal functions
    # =====================


    def __init__(self, client):
        self.client: discord.Bot = client
        # optional Uptime Kuma push monitor, fed by the reminder delivery loop
        self.heartbeat = Heartbeat(os.getenv('UPTIME_KUMA_PUSH_URL'))
        # last run of each delivery loop that went through
        started = timeutil.utcnow()
        self.loop_done = {'reminders': started, 'intervals': started}

        log.debug('starting reminder event loops')

        if not self.check_pending_reminders.is_running():
            self.check_pending_reminders.start()
        if not self.check_pending_intervals.is_running():
            self.check_pending_intervals.start()
        if not self.clean_interval_orphans.is_running():
            self.clean_interval_orphans.start()

    def cog_unload(self):
        log.debug('stopping reminder event loops')
        self.check_pending_reminders.cancel()
        self.check_pending_intervals.cancel()
        self.clean_interval_orphans.cancel()
        
        
    async def warn_author_dm(self, rem: Reminder, reason: str, channel:discord.TextChannel=None, err_msg=None):

        log.warning(f'reminder {rem._id} not delivered: {reason}')

        if rem.author == rem.target:
            # the DM to that same user already failed, nothing else to try
            return

        # try to notify the author of the reminder
        try:
            author = await self.client.fetch_user(rem.author)
        except discord.errors.NotFound:
            log.warning(f'cannot find user {rem.author} for author warning')
            return
        
        guild = self.client.get_guild(rem.g_id) if rem.g_id else None
        dm =  await author.create_dm()
        eb = rem.get_info_embed()

        guild_name = guild.name if guild else '*Unresolved Guild*'
        channel_name = channel.name if channel else '*Unresolved Channel*'
        
        help_text = 'Couldn\'t send the reminder into the requested channel\n\n'\
                   f'• Make sure I have permission to send messages into the channel `{channel_name}` on `{guild_name}`\n'\
                    '• or make sure the receiver allows to receive DMs from me\n'\
                    '• or edit the Reminder to be send into an existing channel'
        
        eb_warn = discord.Embed(title='Failed to deliver Reminder',
                                description=f'{help_text}',
                                color=Consts.col_crit)

        try:
            await dm.send(embed=eb_warn)
            await dm.send(embed=eb)
        except discord.errors.Forbidden:
            # dm has no embed permissions, embeds must always succeed
            log.warning(f'failed to send author warning')
            return


    async def print_reminder_dm(self, rem: Reminder, channel=None, err_msg=None, warn=True) -> bool:
        """send the reminder to its target by DM

        warn: tell the author when it fails (not when the channel is tried next)

        Returns:
            bool: True if it was sent
        """
        # target must be resolved, otherwise dm cannot be created

        try:
            target = await self.client.fetch_user(rem.target)
        except discord.errors.NotFound:
            log.warning(f'cannot find user {rem.target} for reminder DM')
            if warn:
                await self.warn_author_dm(rem, 'target user not found', channel=channel, err_msg=err_msg)
            return False

        if target.bot:
            if warn:
                await self.warn_author_dm(rem, 'target is a bot', channel=channel, err_msg=err_msg)
            return False

        # dm if channel not existing anymor
        dm = await target.create_dm()
        
        
        # respect user preferences
        rem_type = Connector.get_reminder_type(rem.target)
        
        if rem_type == Connector.ReminderType.TEXT_ONLY:
            # text is identical to missing permission fallback
            # but the spoiler asking for more permissions is missing
            eb = None
            text = await rem.get_string(client=self.client, is_dm=True)
        elif rem_type == Connector.ReminderType.EMBED_ONLY:
            eb = await rem.get_embed(self.client, is_dm=True)
            text = ''
        else:
            eb = await rem.get_embed(self.client, is_dm=True)
            text = rem.get_embed_text(is_dm=True)
        
        view = util.reminderButtons.delivered_view(rem)

        # first fallback is string-only message
        # second fallback is dm to user
        # DM never requires user mention (DM itself is a ping)
        try:
            await send_long(dm, text, embed=eb, view=view)
            if err_msg:
                await dm.send(f'||{err_msg}||')
        except discord.errors.Forbidden:
            # embeds can't be forbidden in DMs
            log.warning(f'failed to send reminder as DM to {rem.target}')
            if warn:
                await self.warn_author_dm(rem, 'cannot DM the target', channel=channel, err_msg=err_msg)
            return False
        return True


    @staticmethod
    async def find_author(guild: discord.Guild, user_id: int):
        """the author of a reminder as a member of its server

        Returns:
            the member, or None when Discord doesn't say (the reminder is
            then sent without @everyone and role pings)

        Raises:
            AuthorLeft: they are no longer a member of the server
            TRANSIENT_ERRORS: Discord unreachable, the reminder is kept
        """
        member = guild.get_member(user_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(user_id)
        except discord.NotFound as e:
            if e.code == Consts.unknown_member:
                raise AuthorLeft(user_id) from e
            return None
        except discord.Forbidden:
            return None


    @staticmethod
    def allowed_mentions(rem: Reminder, channel, author) -> discord.AllowedMentions:
        """the mentions of a reminder ping like a message of its author would:
           @everyone, @here and roles need the author's 'Mention @everyone' permission
           in that channel (the role targeted by /remind also pings when it is mentionable)

        author: the author as a member of the server, None when unknown
        """
        guild = channel.guild
        if author is not None and channel.permissions_for(author).mention_everyone:
            return discord.AllowedMentions(everyone=True, roles=True, users=True)

        target_role = guild.get_role(rem.target) if rem.target else None
        roles = [target_role] if target_role and target_role.mentionable else []
        return discord.AllowedMentions(everyone=False, roles=roles, users=True)


    async def print_reminder(self, rem: Reminder):
        """send a due reminder: by DM (private ones, or 'by DM' ones for a member), else in its channel

        Raises:
            AuthorLeft: the author left its server (it is dropped, not sent)
        """
        if not rem.g_id:
            await self.print_reminder_dm(rem)
            return

        guild = self.client.get_guild(rem.g_id)
        # raises AuthorLeft: the reminder is dropped, also its DM fallback
        author = await self.find_author(guild, rem.author) if guild else None

        if rem.by_dm and rem.is_for_a_member():
            if await self.print_reminder_dm(rem, warn=False):
                return
            # DMs closed: in its channel after all, not lost
            log.info(f'reminder {rem._id}: cannot DM {rem.target}, sent in its channel')

        await self._print_in_channel(rem, guild, author)


    async def _print_in_channel(self, rem: Reminder, guild, author):
        """send it into its channel, by DM when the channel can't be used"""

        async def send_message(guild, channel, text, embed, rem_type: Connector.ReminderType, reminder, mentions):
            if isinstance(channel, discord.Thread) or VerboseErrors.can_embed(channel):
                try:
                    if rem_type in (Connector.ReminderType.EMBED_ONLY, Connector.ReminderType.HYBRID):
                        view = util.reminderButtons.delivered_view(reminder)
                    else:
                        view = None

                    await send_long(channel, text, embed=embed, allowed_mentions=mentions, view=view)
                    return True
                except discord.errors.Forbidden:
                    if isinstance(channel, discord.Thread) and channel.locked:
                        return False # no error on locked threads
                    log.error('failed to send embed, even though permissions had been assured')

            elif VerboseErrors.can_send_messages(channel):
                try:
                    # get the reminder string
                    # ignoring the user preferences
                    fallback = await rem.get_string(client=self.client)
                    fallback += '\n||This reminder can be more beautiful with `Embed Links` permissions||'
                    await send_long(channel, fallback, allowed_mentions=mentions)
                    return True
                except discord.errors.Forbidden:
                    if isinstance(channel, discord.Thread) and channel.locked:
                        return False # no error on locked threads
                    log.error('failed to send text message, even though permissions had been assured')

            return False

    
        channel = guild.get_channel_or_thread(rem.ch_id) if guild else None

        if not channel:
            # this gets archived threads
            try:
                channel = await self.client.fetch_channel(rem.ch_id)
            except (discord.errors.NotFound, discord.errors.Forbidden):
                channel = None


        # no need to resolve author, target is sufficient
        guild_name = guild.name if guild else 'Unresolved Guild'
        if not channel:
            err = f'`You are receiving this dm, as the desired channel on \'{guild_name}\' is not accesible (anymore).`'
        elif isinstance(channel, discord.CategoryChannel):
            # cannot use category channels
            log.debug('tried to send reminder for category channel')
            err = f'`You are receivin this dm, as the desired channel \'{channel.name}\' on \'{guild_name}\' is not a Text- or Voice- channel`'
        else:
            err = None
        
        if err:
            log.debug('try to send reminder over dm')
            await self.print_reminder_dm(rem, channel=None, err_msg=err)
            return

        # respect guild preferences
        rem_type = Connector.get_reminder_type(guild.id)
        

        if rem_type == Connector.ReminderType.BAREBONE:
            eb = None
            text = await rem.get_string(client=self.client, barebone=True)
        elif rem_type == Connector.ReminderType.TEXT_ONLY:
            # text is identical to missing permission fallback
            # but the spoiler asking for more permissions is missing
            eb = None
            text = await rem.get_string(client=self.client, barebone=False)
        elif rem_type == Connector.ReminderType.EMBED_ONLY:
            eb = await rem.get_embed(self.client)
            text = rem.target_mention or f'<@{rem.target}>'
        else:
            eb = await rem.get_embed(self.client)
            text = rem.get_embed_text()

        mentions = self.allowed_mentions(rem, channel, author)
        success = await send_message(guild, channel, text, eb, rem_type, reminder=rem, mentions=mentions)
        

        if not success:
            if isinstance(channel, discord.Thread) and channel.locked:
                err = f'`You are receiving this dm, as I the original thread \'{channel.name}\' on \'{guild.name}\' of this reminder was locked by a moderator.`'
            elif isinstance(channel, discord.Thread):
                err = f'`You are receiving this dm, as I do not have permission to send messages into the thread \'{channel.name}\' on \'{guild.name}\'.`'
            else:
                err = f'`You are receiving this dm, as I do not have permission to send messages into the channel \'{channel.name}\' on \'{guild.name}\'.`'

            await self.print_reminder_dm(rem, channel=channel, err_msg=err)

    # =====================
    # events functions
    # =====================



    @commands.Cog.listener()
    async def on_ready(self):
        log.info('loaded')


    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        # the buttons under delivered reminders (they have no view in memory)
        if interaction.type == discord.InteractionType.component:
            await util.reminderButtons.handle_click(interaction)


    @tasks.loop(hours=24)
    @log_errors(log)
    async def clean_interval_orphans(self):
        cnt = Connector.delete_orphaned_intervals()
        log.debug(f'deleted {cnt} orphaned interval(s)')
        cnt = Connector.delete_delivered_before(utc_timestamp(timeutil.utcnow() - util.reminderButtons.DELIVERED_KEEP))
        log.debug(f'deleted {cnt} delivered reminder(s) kept for their buttons')


    async def deliver(self, rem: Reminder, due_at, now) -> bool:
        """send a due reminder

        Returns:
            bool: False when Discord couldn't be reached: try again later.
                  True when done, also after an error that a retry won't fix
        """
        rem.late_due_at = due_at if due_at and now - due_at > LATE_AFTER else None
        try:
            await self.print_reminder(rem)
        except AuthorLeft:
            # nobody wants it anymore, and it must not keep pinging the others
            log.info(f'reminder {rem._id} dropped: its author {rem.author} left the server {rem.g_id}')
            if isinstance(rem, IntervalReminder):
                Connector.delete_interval(rem._id)
            else:
                Connector.delete_reminder(rem._id)
        except TRANSIENT_ERRORS as e:
            if due_at and now - due_at < RETRY_FOR:
                log.warning(f'reminder {rem._id} not delivered, Discord is unreachable ({e!r}): retrying later')
                return False
            log.error(f'reminder {rem._id} not delivered for {RETRY_FOR}, dropped', exc_info=e)
        except Exception:
            log.exception(f'reminder {rem._id} not delivered, skipping')
        return True


    @tasks.loop(seconds=45)
    @log_errors(log)
    async def check_pending_intervals(self):
        now = timeutil.utcnow()

        pending_intvls = Connector.get_pending_intervals(utc_timestamp(now))

        # move each one to its next date before sending: a crash or restart
        # while sending must not send them twice
        due_at = {}
        for interval in pending_intvls:
            due_at[interval._id] = interval.at
            try:
                interval.at = interval.next_trigger(now)
            except Exception:
                # one broken rule must not stop the other intervals
                log.exception(f'interval {interval._id}: cannot compute its next date')
                interval.at = None

            if interval.at is None:
                # last delivery, with a warning (orphans are deleted within a day)
                interval.msg += INTERVAL_BROKEN_WARNING
            Connector.update_interval_at(interval)

        failures = 0  # in a row
        for interval in pending_intvls:
            if interval.paused:
                # the schedule moved on above, nothing to send
                log.debug(f'interval {interval._id} is paused, not delivered')
                continue

            if failures < DOWN_AFTER:
                if await self.deliver(interval, due_at[interval._id], now):
                    failures = 0
                    continue
                failures += 1

            # not sent, Discord unreachable: back to the missed date, sent on a later run
            interval.at = due_at[interval._id]
            Connector.update_interval_at(interval)

        sent_in = (timeutil.utcnow()-now).total_seconds()
        if sent_in > 1:
            log.debug(f'intervals sent in {sent_in}s')
        if failures < DOWN_AFTER:
            self.loop_done['intervals'] = timeutil.utcnow()


    @tasks.loop(seconds=50)
    @log_errors(log)
    async def check_pending_reminders(self):
        now = timeutil.utcnow()

        # delete each reminder only after it was handled:
        # a crash or restart while sending must not lose the pending ones
        pending_rems = Connector.get_elapsed_reminders(utc_timestamp(now))

        failures = 0  # in a row
        for reminder in pending_rems:
            if failures >= DOWN_AFTER:
                # Discord seems unreachable: keep the next ones for a later run
                break

            if not await self.deliver(reminder, reminder.at, now):
                # kept, tried again on a later run
                failures += 1
                continue
            failures = 0

            # also after an error: a reminder that always fails must not be retried forever
            # (not in a finally: a shutdown while sending must keep the reminder).
            # Kept a while for the buttons under it (snooze)
            Connector.archive_delivered(reminder)


        sent_in = (timeutil.utcnow()-now).total_seconds()
        if sent_in > 1:
            log.debug(f'reminders sent in {sent_in}s')
        if failures < DOWN_AFTER:
            self.loop_done['reminders'] = timeutil.utcnow()

        await self.push_heartbeat()


    async def push_heartbeat(self):
        """tell the monitor that all is well: both delivery loops ran
           recently and the gateway connection is up
        """
        now = timeutil.utcnow()
        stale = [name for name, done in self.loop_done.items() if now - done > LOOP_STALE_AFTER]
        if stale:
            log.warning(f'delivery loop(s) {", ".join(stale)} stuck, monitor not updated')
            return

        latency = self.client.latency
        if self.client.is_ready() and not self.client.is_closed() and math.isfinite(latency):
            await self.heartbeat.push(msg='OK', ping_ms=latency*1000)
        
    
   
    

    @clean_interval_orphans.before_loop
    async def clean_interval_orphans_before(self):
        await self.client.wait_until_ready()

    @check_pending_intervals.before_loop
    async def check_pending_intervals_before(self):
        await self.client.wait_until_ready()

    @check_pending_reminders.before_loop
    async def check_pending_reminders_before(self):
        await self.client.wait_until_ready()


    # =====================
    # commands functions
    # =====================

def setup(client):
    client.add_cog(ReminderModule(client))
