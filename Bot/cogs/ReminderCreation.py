import logging
import lib.timeutil as timeutil
from typing import Union

from datetime import datetime, timedelta
from dateutil import tz


import discord
from discord.ext import commands

from util.consts import Consts
from lib.Connector import Connector
from lib.Reminder import Reminder, IntervalReminder
import lib.permissions
import lib.input_parser
import lib.ReminderRepeater
import util.interaction
import util.reminderInteraction



log = logging.getLogger('Remindme.Creation')


class NewReminderView(util.interaction.CustomView):
    def __init__(self, reminder: Reminder, stm: util.reminderInteraction.STM, info_str: str, rrule_override, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reminder = reminder
        self.stm = stm
        self.info_str = info_str
        self.rrule_override = rrule_override
        self.owner_id = reminder.author

        if isinstance(self.reminder, IntervalReminder):
            self.edit_interval.label='Edit Interval'

    def get_embed(self) -> discord.Embed:
        return self.reminder.get_tiny_embed(info=self.info_str, rrule_override=self.rrule_override)


    @discord.ui.button(label='Set Interval', emoji='🔁', style=discord.ButtonStyle.primary)
    async def edit_interval(self, button: discord.ui.Button, interaction: discord.Interaction):

        view = util.reminderInteraction.ReminderIntervalAddView(self.reminder, self.stm)
        if await self.open_child(interaction, view, embed=view.get_embed()):
            return
        self.reminder = view.reminder # could be an interval with different id now
        if isinstance(self.reminder, IntervalReminder):
            self.edit_interval.label = 'Edit Interval'

        # back to this menu
        await self.show(embed=self.get_embed(), view=self)


    @discord.ui.button(label='Edit', emoji='🛠️', style=discord.ButtonStyle.secondary)
    async def edit_reminder(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.reminder.author != interaction.user.id:
            eb = discord.Embed(title='Cannot edit reminders of other users', color=Consts.col_crit)
            self.disable_all()
            self.del_reminder.style = discord.ButtonStyle.danger # keep this btn red
            await self.show(interaction, embed=eb, view=self)
            return

        modal = util.reminderInteraction.EditModal(reminder=self.reminder,
                                                    custom_callback=self.edit_done,
                                                    tz_str=self.stm.tz_str,
                                                    title='Edit the Reminder')
        await interaction.response.send_modal(modal)


    async def edit_done(self, interaction: discord.Interaction, info: str):
        """the edit popup was submitted (interaction), info: what wasn't changed"""
        reloaded = util.reminderInteraction.reload_reminder(self.reminder)
        if reloaded is None or self.is_finished():
            text = 'Saved.' if reloaded else 'This reminder was delivered or deleted while you edited it.'
            await interaction.response.send_message(f'{text} {info}'.strip(), ephemeral=True)
            return

        self.reminder = reloaded
        await self.show(interaction, embed=self.get_embed(), view=self)
        if info:
            await interaction.followup.send(info, ephemeral=True)



    @discord.ui.button(emoji='🗑️', style=discord.ButtonStyle.danger)
    async def del_reminder(self, button: discord.ui.Button, interaction: discord.Interaction):
        eb_title = None
        if self.reminder.author != interaction.user.id:
            eb_title = 'Cannot delete reminders of other users'
            color = Consts.col_crit
        elif Connector.delete_reminder(self.reminder._id):
            eb_title = 'Deleted the reminder'
            color = Consts.col_warn
        elif Connector.delete_interval(self.reminder._id):
            eb_title = 'Deleted the reminder'
            color = Consts.col_warn
        else:
            eb_title = 'Failed to delete reminder due to an unknown issue'
            color = Consts.col_crit
            log.error(f'Couldn\'t direct-delete a reminder of type {type(self.reminder)}. Both delete queries didn\'t suceed.')


        eb = discord.Embed(title=eb_title, color=color)
        self.disable_all()
        self.del_reminder.style = discord.ButtonStyle.danger # keep this btn red
        await self.show(interaction, embed=eb, view=self)
        self.stop()



class ReminderCreation(commands.Cog):

    REMIND_FORMAT_HELP = \
                'basic example:\n'\
                '> /remindme `time: 2d` `message: Hello World`\n'\
                '\n'\
                'remind other users and roles\n'\
                '> /remind `target: @Role` `time: 24 dec`  `message: Merry Christmas`\n'\
                '\n'\
                'create repeating reminders\n'\
                '> /remindme `time: every friday at 20:15` `message: do stuff`\n'\
                '\n'\
                'try different formats\n'\
                '```'\
                '• 5 jul, 5th july, july 5\n'\
                '• 23 aug at 3pm, 23 aug at 15\n'\
                '• every other week\n'\
                '\n'\
                '```'\
                '\n'\
                'Call `/help page: syntax` for more detailed information.\n'
                
    HELP_FOOTER = 'If you find a bug in the parser, please report it on GitHub.'


    # =====================
    # internal functions
    # =====================


    def __init__(self, client):
        self.client = client


    async def process_reminder(self, ctx: discord.ApplicationContext, author: Union[discord.User, discord.Member], target, period, message, channel):

        # DMs, or a server where only the user installed the app: private reminder, by DM
        personal = lib.permissions.is_personal_context(ctx)

        if not personal:
            instance_id = ctx.guild.id
            # try and get the last message, for providing a jump link
            try:
                last_msg = await ctx.channel.history(limit=1).flatten()
            except:
                last_msg = None
            last_msg = last_msg[0] if last_msg else None
        else:
            instance_id = author.id
            last_msg = None

        
        

        tz_str = Connector.get_timezone(instance_id)
        auto_del_action = Connector.get_auto_delete(instance_id)

        utcnow = timeutil.utcnow()
        remind_at, info = lib.input_parser.parse(period, utcnow, tz_str)
        rrule = None

        if isinstance(remind_at, datetime):
            interval = (remind_at - utcnow)
            if remind_at is None or interval <= timedelta(hours=0):
                if info != '':
                    out_str = f'```Parsing hints:\n{info}```\n'
                else:
                    out_str = ''

                if interval == timedelta(hours=0):
                    # only append full help on invalid strings
                    # not on negative intervals
                    out_str += ReminderCreation.REMIND_FORMAT_HELP
                elif interval < timedelta(hours=0):
                    out_str += 'Make sure your server is using the correct timezone `/timezone`'

                embed = discord.Embed(title='Failed to create the reminder', color=0xff0000, description=out_str)
                embed.set_footer(text=ReminderCreation.HELP_FOOTER)
                await ctx.respond(embed=embed, ephemeral=True)
                return  # error exit

        elif remind_at is None:
            if info != '':
                out_str = f'```Parsing hints:\n{info}```\n'
            else:
                out_str = ''
            out_str += ReminderCreation.REMIND_FORMAT_HELP

            embed = discord.Embed(title='Failed to create the reminder', color=0xff0000, description=out_str)
            embed.set_footer(text=ReminderCreation.HELP_FOOTER)
            await ctx.respond(embed=embed, ephemeral=True)
            return  

        elif isinstance(remind_at, str):

            # interval rules live in the local time of the server/user
            dtstart = utcnow.replace(tzinfo=tz.UTC).astimezone(tz.gettz(tz_str)).replace(tzinfo=None)

            rrule, info = lib.input_parser.rrule_normalize(remind_at, dtstart=dtstart, tz_str=tz_str)
            if not rrule:
                if info != '':
                    out_str = f'```Parsing hints:\n{info}```\n'
                else:
                    # only show general help, if normalizing doesn't give
                    # specific error
                    out_str = ReminderCreation.REMIND_FORMAT_HELP

                embed = discord.Embed(title='Failed to create the reminder', color=0xff0000, description=out_str)
                embed.set_footer(text=ReminderCreation.HELP_FOOTER)
                await ctx.respond(embed=embed, ephemeral=True)
                return

        if auto_del_action == Connector.AutoDelete.HIDE or personal:
            defer_hidden=True
        else:
            defer_hidden=False
        await ctx.defer(ephemeral=defer_hidden) # allow more headroom for response latency, before command fails
        rem = Reminder()


        info = '' if not info else info
        if channel is None:
            # command was called in DM
            rem.g_id = None
            rem.ch_id = None
            rem.ch_name = 'DM'
        else:
            if isinstance(channel, discord.channel.PartialMessageable):
                # channel not fully loaded (due to sharding or permissions)
                try:
                    res_channel = await self.client.fetch_channel(channel.id)
                    channel = res_channel
                    rem.ch_name = channel.name[0:25] # only keep first 25 letters   
                except discord.errors.Forbidden:
                    rem.ch_name = '*Unresolved Channel*'
                    info += f'\n• Failed to resolve the target channel. The reminder *might* not be delivered due to missing permissions.' 
            else:
                # channel name by attribute
                rem.ch_name = channel.name[0:25] # only keep first 25 letters
           
            # independant of channel itself
            rem.g_id = ctx.guild.id
            rem.ch_id = channel.id

            if rem.ch_id != ctx.channel_id:
                info += f'\n• This reminder will be delivered to `{rem.ch_name}`.\nMake sure this bot has permission to send messages into that channel'


        rem.msg = message
        rem.at = remind_at
        rem.author = author.id

        rem.created_at = utcnow
        rem.last_msg_id = last_msg.id if last_msg else None


        if isinstance(target, int):
            # use user-mention (no &) as fallback
            # as it's more likely to not resolve a user
            rem.target = target
            rem.target_name = f'<@{target}>'
            rem.target_mention = f'<@{target}>'
            log.warning('failed to resolve mentionable, using a user mention')
        elif isinstance(target, discord.member.Member):
            rem.target = target.id
            rem.target_name = target.mention
            rem.target_mention = target.mention
        else:
            rem.target = target.id
            rem.target_name = target.name
            # everyone requires a special case
            # as it cannot be mentioned by using the id
            if ctx.guild and ctx.guild.default_role == target:
                rem.target_mention = target.name # @everyone
            else:
                rem.target_mention = target.mention

        if rrule:
            old_rem = rem
            old_rem.at = dtstart
            rem = IntervalReminder(old_rem._to_json())
            rem.first_at = old_rem.at
            rem.rrules.append(str(rrule))

            rem.at = rem.next_trigger(utcnow, tz_str=tz_str)
            # do NOT save, if trigger creation faild
            # this should not be possible
            if rem.at:
                rem._id = Connector.add_interval(rem)
        else:
            # the id is required in case the users wishes to abort
            rem._id = Connector.add_reminder(rem)


        if auto_del_action == Connector.AutoDelete.TIMEOUT:
            delete_after = 300
            hidden=False
        elif auto_del_action == Connector.AutoDelete.NEVER:
            delete_after = None
            hidden=False
        else:
            delete_after = None
            hidden=True

        if personal:
            # don't post into a DM with someone else or a server the bot is not part of
            delete_after = None
            hidden = True


        stm = util.reminderInteraction.STM(
            ctx,
            Connector.Scope(is_private=personal, guild_id=None if personal else ctx.guild.id, user_id=ctx.author.id)
        )
        stm.tz_str = tz_str

        view = NewReminderView(rem, stm=stm, info_str=info, rrule_override=rrule, timeout=delete_after)
        tiny_embed = view.get_embed() 

        view.origin = await ctx.respond(embed=tiny_embed, delete_after=delete_after, view=view,
                            allowed_mentions=discord.AllowedMentions.none(), ephemeral=hidden)


    # =====================
    # events functions
    # =====================

    @discord.Cog.listener()
    async def on_ready(self):
        log.info('loaded')


    # =====================
    # commands functions
    # =====================
    # TODO: fix mentionable type, wait for lib fix
    @commands.slash_command(name='remind', description='set a reminder after a certain time period')
    async def remind_user(self, ctx:discord.ApplicationContext,
                        target:discord.Option((discord.Member, discord.Role), 'the user or role you want to remind', required=True),
                        time:discord.Option(str, 'time/date when the reminder is triggered (see syntax page on /help)', required=True),
                        message:discord.Option(str, 'the bot will remind you with this message', required=True)):
                        #channel:discord.Option((discord.TextChannel,discord.VoiceChannel), 'Show the reminder in a channel other than the current one', required=False)=None):

        channel=None
        if ctx.guild:
            # update channel, when not specified (optional parameter)
            channel = channel or ctx.channel

        await self.process_reminder(ctx, ctx.author, target, time, message, channel=channel)
    

    @commands.slash_command(name='remindme', description='set a reminder after a certain time period',
                            **lib.permissions.EVERYWHERE)
    async def remindme(self, ctx:discord.ApplicationContext,
                        time:discord.Option(str, 'time/date when the reminder is triggered (see syntax page on /help)', required=True),
                        message:discord.Option(str, 'the bot will remind you with this message', required=True)):
                        #channel:discord.Option((discord.TextChannel,discord.VoiceChannel), 'Show the reminder in a channel other than the current one', required=False)=None):
        channel = None
        if not lib.permissions.is_personal_context(ctx):
            channel = channel or ctx.channel # overwrite if not specified

        await self.process_reminder(ctx, ctx.author, ctx.author, time, message, channel=channel)
        


def setup(client):
    client.add_cog(ReminderCreation(client))
