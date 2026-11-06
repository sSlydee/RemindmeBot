import math
import lib.timeutil as timeutil
import os
import logging
import traceback



import discord
from discord.ext import commands, tasks

from lib.Connector import Connector
from lib.Reminder import Reminder, IntervalReminder, utc_timestamp
import util.interaction
from util.verboseErrors import VerboseErrors
from util.loops import log_errors
from util.heartbeat import Heartbeat
from util.consts import Consts


log = logging.getLogger('Remindme.Core')

class ReminderModule(commands.Cog):


    # =====================
    # internal functions
    # =====================


    def __init__(self, client):
        self.client: discord.Bot = client
        # optional Uptime Kuma push monitor, fed by the reminder delivery loop
        self.heartbeat = Heartbeat(os.getenv('UPTIME_KUMA_PUSH_URL'))

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


    async def print_reminder_dm(self, rem: Reminder, channel=None, err_msg=None):
        # fallback to dm
        # target must be resolved, otherwise dm cannot be created

        try:
            target = await self.client.fetch_user(rem.target)
        except discord.errors.NotFound:
            log.warning(f'cannot find user {rem.target} for reminder DM')
            await self.warn_author_dm(rem, 'target user not found', channel=channel, err_msg=err_msg)
            return

        if target.bot:
            await self.warn_author_dm(rem, 'target is a bot', channel=channel, err_msg=err_msg)
            return

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
        
        view = util.interaction.UndeliveredView(reminder_id=rem._id, timeout=300)

        # first fallback is string-only message
        # second fallback is dm to user
        # DM never requires user mention (DM itself is a ping)
        try:
            await dm.send(text, embed=eb, view=view)
            if err_msg:
                await dm.send(f'||{err_msg}||')
        except discord.errors.Forbidden:
            # embeds can't be forbidden in DMs
            log.warning(f'failed to send reminder as DM to {rem.target}')
            await self.warn_author_dm(rem, 'cannot DM the target', channel=channel, err_msg=err_msg)
            return


    async def print_reminder(self, rem: Reminder):

        async def send_message(guild, channel, text, embed, rem_type: Connector.ReminderType, reminder):
            if isinstance(channel, discord.Thread) or VerboseErrors.can_embed(channel):
                try:
                    if rem_type != Connector.ReminderType.EMBED_ONLY and \
                        rem_type != Connector.ReminderType.HYBRID:
                        view = None
                    elif  isinstance(reminder, IntervalReminder):                        
                        view = util.interaction.SnoozeIntervalView(reminder, timeout=500)
                    else:
                        view = util.interaction.SnoozeView(reminder, timeout=500)


                    tmp_msg = await channel.send(text, embed=embed, 
                                    allowed_mentions=discord.AllowedMentions.all(),
                                    view=view)

                    if view:
                        # for timeout functionality
                        view.message = tmp_msg
                                    
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
                    await channel.send(fallback)
                    return True
                except discord.errors.Forbidden:
                    if isinstance(channel, discord.Thread) and channel.locked:
                        return False # no error on locked threads
                    log.error('failed to send text message, even though permissions had been assured')

            return False

    
        # reminder is a DM reminder
        if not rem.g_id:
            await self.print_reminder_dm(rem)
            return

        guild = self.client.get_guild(rem.g_id)
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

        success = await send_message(guild, channel, text, eb, rem_type, reminder=rem)
        

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


    @tasks.loop(hours=24)
    @log_errors(log)
    async def clean_interval_orphans(self):
        cnt = Connector.delete_orphaned_intervals()
        log.debug(f'deleted {cnt} orphaned interval(s)')


    @tasks.loop(seconds=45)
    @log_errors(log)
    async def check_pending_intervals(self):   
        now = timeutil.utcnow()
        
        pending_intvls = Connector.get_pending_intervals(utc_timestamp(now))

        for interval in pending_intvls:
            interval.at = interval.next_trigger(now)

            if interval.at is None:
                # do not update on invalid rrule
                interval.msg += '\n**WARNING: the reminder couldn\'t get queued for future invocations** (likely due to an invalid repetition rule). **This reminder will not be delivered anymore**'
            Connector.update_interval_at(interval)                
            
        for interval in pending_intvls:
            if interval.paused:
                # the schedule moved on above, nothing to send
                log.debug(f'interval {interval._id} is paused, not delivered')
                continue
            try:
                await self.print_reminder(interval)
            except Exception as e:
                log.error(f'interval not delivered, skipping. See exception below')
                t = (type(e), e, e.__traceback__)
                log.error(''.join(traceback.format_exception(*t)))

        self.last_loop = timeutil.utcnow()
        sent_in = (self.last_loop-now).total_seconds()
        if sent_in > 1:
            log.debug(f'intervals sent in {sent_in}s')


    @tasks.loop(seconds=50)
    @log_errors(log)
    async def check_pending_reminders(self):
        now = timeutil.utcnow()

        # delete each reminder only after it was handled:
        # a crash or restart while sending must not lose the pending ones
        pending_rems = Connector.get_elapsed_reminders(utc_timestamp(now))
        
        for reminder in pending_rems:
            try:
                await self.print_reminder(reminder)
            except Exception as e:
                log.error(f'reminder not delivered, skipping. See exception below')
                t = (type(e), e, e.__traceback__)
                log.error(''.join(traceback.format_exception(*t)))

            # also after an error: a reminder that always fails must not be retried forever
            # (not in a finally: a shutdown while sending must keep the reminder)
            Connector.delete_reminder(reminder._id)


        sent_in = (timeutil.utcnow()-now).total_seconds()
        if sent_in > 1:
            log.debug(f'reminders sent in {sent_in}s')

        # this run worked: tell the monitor, unless the gateway connection is down
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
