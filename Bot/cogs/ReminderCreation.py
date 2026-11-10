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
from lib.i18n import lang_of, tr, hints, date_str
import util.interaction
import util.reminderInteraction



log = logging.getLogger('Remindme.Creation')

# the message goes into the embed description (4096 characters at most);
# text-only reminders are split into several messages
MAX_MESSAGE_LEN = 4000
# pending reminders and repeating reminders a user can have
MAX_REMINDERS_PER_USER = 100

# suggested while the 'time' field is empty
TIME_EXAMPLES = ['in 2h', 'tomorrow 9:00', 'friday 18:30', 'every monday at 9:00']
TIME_EXAMPLES_FR = ['dans 2h', 'demain 9h', 'vendredi 18h30', 'tous les lundis à 9h']


def _in_words(delta: timedelta, lang='en') -> str:
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return tr(lang, 'in {n} min', n=max(minutes, 1))
    hours = minutes // 60
    if hours < 48:
        if minutes % 60:
            return tr(lang, 'in {h} h {m}', h=hours, m=f'{minutes % 60:02d}')
        return tr(lang, 'in {h} h', h=hours)
    return tr(lang, 'in {d} days', d=hours // 24)


def describe_time(text: str, utcnow: datetime, tz_str: str, lang='en') -> str:
    """how /remindme reads its 'time' (shown while it is typed),
       in the local time of the server or user, in the user's language
    """
    local_tz = tz.gettz(tz_str)
    local_now = utcnow.replace(tzinfo=tz.UTC).astimezone(local_tz)

    def local_str(local_dt):
        return date_str(local_dt, lang, with_year=local_dt.year != local_now.year)

    at, _ = lib.input_parser.parse(text.strip(), utcnow, tz_str)

    if isinstance(at, str):
        dtstart = timeutil.to_minute(local_now.replace(tzinfo=None))
        rule, error = lib.input_parser.rrule_normalize(at, dtstart=dtstart, tz_str=tz_str)
        if not rule:
            return '⚠ ' + (hints(lang, error.splitlines()[0]) if error else tr(lang, 'invalid repetition'))
        first = rule.after(dtstart)
        if not first:
            return tr(lang, '⚠ this repetition has no date in the future')
        first_utc = first.replace(tzinfo=local_tz).astimezone(tz.UTC).replace(tzinfo=None)
        return tr(lang, 'repeats, first {date} ({when})', date=local_str(first), when=_in_words(first_utc - utcnow, lang))

    if not isinstance(at, datetime) or at == utcnow:
        return tr(lang, '⚠ can\'t read this date')
    if at < utcnow:
        return tr(lang, '⚠ this date is in the past')
    return f'{local_str(at.replace(tzinfo=tz.UTC).astimezone(local_tz))} ({_in_words(at - utcnow, lang)})'


async def time_autocomplete(ctx: discord.AutocompleteContext):
    """the date of the 'time' being typed, as a suggestion (picking it keeps the text)"""
    try:
        text = (ctx.value or '').strip()
        interaction = ctx.interaction
        personal = lib.permissions.is_personal_context(ctx)
        tz_str = Connector.get_timezone(interaction.user.id if personal else interaction.guild_id)
        utcnow = timeutil.utcnow()
        lang = lang_of(interaction)
        if not text:
            examples = TIME_EXAMPLES_FR if lang == 'fr' else TIME_EXAMPLES
            return [discord.OptionChoice(name=f'{ex} → {describe_time(ex, utcnow, tz_str, lang)}'[:100], value=ex)
                    for ex in examples]
        return [discord.OptionChoice(name=f'{text[:40]} → {describe_time(text, utcnow, tz_str, lang)}'[:100],
                                     value=text[:100])]
    except Exception:
        log.exception('time preview failed')
        return []


class NewReminderView(util.interaction.CustomView):
    def __init__(self, reminder: Reminder, stm: util.reminderInteraction.STM, info_str: str, rrule_override, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reminder = reminder
        self.stm = stm
        self.info_str = info_str
        self.rrule_override = rrule_override
        self.owner_id = reminder.author

        lang = stm.lang
        self.edit_interval.label = tr(lang, 'Edit Interval' if isinstance(reminder, IntervalReminder) else 'Set Interval')
        self.edit_reminder.label = tr(lang, 'Edit')

    def get_embed(self) -> discord.Embed:
        return self.reminder.get_tiny_embed(info=self.info_str, rrule_override=self.rrule_override, lang=self.stm.lang)


    @discord.ui.button(label='Set Interval', emoji='🔁', style=discord.ButtonStyle.primary)
    async def edit_interval(self, button: discord.ui.Button, interaction: discord.Interaction):

        view = util.reminderInteraction.ReminderIntervalAddView(self.reminder, self.stm)
        if await self.open_child(interaction, view, embed=view.get_embed()):
            return
        self.reminder = view.reminder # could be an interval with different id now
        if isinstance(self.reminder, IntervalReminder):
            self.edit_interval.label = tr(self.stm.lang, 'Edit Interval')

        # back to this menu
        await self.show(embed=self.get_embed(), view=self)


    @discord.ui.button(label='Edit', emoji='🛠️', style=discord.ButtonStyle.secondary)
    async def edit_reminder(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.reminder.author != interaction.user.id:
            eb = discord.Embed(title=tr(lang_of(interaction), 'Cannot edit reminders of other users'), color=Consts.col_crit)
            self.disable_all()
            self.del_reminder.style = discord.ButtonStyle.danger # keep this btn red
            await self.show(interaction, embed=eb, view=self)
            return

        modal = util.reminderInteraction.EditModal(reminder=self.reminder,
                                                    custom_callback=self.edit_done,
                                                    tz_str=self.stm.tz_str,
                                                    title=tr(lang_of(interaction), 'Edit the Reminder'))
        await util.interaction.open_popup(interaction, modal)


    async def edit_done(self, interaction: discord.Interaction, info: str):
        """the edit popup was submitted (interaction), info: what wasn't changed"""
        reloaded = util.reminderInteraction.reload_reminder(self.reminder)
        if reloaded is None or self.is_finished():
            lang = lang_of(interaction)
            text = tr(lang, 'Saved.') if reloaded else tr(lang, 'This reminder was delivered or deleted while you edited it.')
            await interaction.response.send_message(f'{text} {info}'.strip(), ephemeral=True)
            return

        self.reminder = reloaded
        await self.show(interaction, embed=self.get_embed(), view=self)
        if info:
            await interaction.followup.send(info, ephemeral=True)



    @discord.ui.button(emoji='🗑️', style=discord.ButtonStyle.danger)
    async def del_reminder(self, button: discord.ui.Button, interaction: discord.Interaction):
        eb_title = None
        lang = lang_of(interaction)
        if self.reminder.author != interaction.user.id:
            eb_title = tr(lang, 'Cannot delete reminders of other users')
            color = Consts.col_crit
        elif Connector.delete_reminder(self.reminder._id):
            eb_title = tr(lang, 'Deleted the reminder')
            color = Consts.col_warn
        elif Connector.delete_interval(self.reminder._id):
            eb_title = tr(lang, 'Deleted the reminder')
            color = Consts.col_warn
        else:
            eb_title = tr(lang, 'Failed to delete reminder due to an unknown issue')
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
                
    REMIND_FORMAT_HELP_FR = \
                'exemple simple :\n'\
                '> /remindme `time: dans 2 jours` `message: Bonjour`\n'\
                '\n'\
                'rappeler d’autres membres ou un rôle\n'\
                '> /remind `target: @Rôle` `time: 24 décembre` `message: Joyeux Noël`\n'\
                '\n'\
                'créer des rappels qui se répètent\n'\
                '> /remindme `time: tous les vendredis à 20h15` `message: faire un truc`\n'\
                '\n'\
                'd’autres formats\n'\
                '```'\
                '• demain 9h, vendredi à 18h30, dans 3 jours\n'\
                '• 5 juillet, 23 août à 15h\n'\
                '• toutes les 2 semaines, tous les mois le 15\n'\
                '\n'\
                '```'\
                '\n'\
                '`/help page: syntax` pour tous les détails.\n'

    HELP_FOOTER = 'The time formats are on the syntax page of /help.'


    # =====================
    # internal functions
    # =====================


    def __init__(self, client):
        self.client = client


    async def process_reminder(self, ctx: discord.ApplicationContext, author: Union[discord.User, discord.Member], target, period, message, channel):

        # DMs, or a server where only the user installed the app: private reminder, by DM
        personal = lib.permissions.is_personal_context(ctx)
        lang = lang_of(ctx)
        format_help = ReminderCreation.REMIND_FORMAT_HELP_FR if lang == 'fr' else ReminderCreation.REMIND_FORMAT_HELP
        failed = tr(lang, 'Failed to create the reminder')
        footer = tr(lang, ReminderCreation.HELP_FOOTER)

        # Discord waits 3 seconds for an answer: only quick database reads before it
        instance_id = author.id if personal else ctx.guild.id
        tz_str = Connector.get_timezone(instance_id)
        auto_del_action = Connector.get_auto_delete(instance_id)

        if Connector.count_user_reminders(author.id) >= MAX_REMINDERS_PER_USER:
            embed = discord.Embed(title=failed, color=0xff0000,
                                  description=tr(lang, 'You already have {n} pending reminders. Delete some with '
                                                       '`/reminder_list` first.', n=MAX_REMINDERS_PER_USER))
            await ctx.respond(embed=embed, ephemeral=True)
            return

        utcnow = timeutil.utcnow()
        remind_at, info = lib.input_parser.parse(period, utcnow, tz_str)
        rrule = None

        if isinstance(remind_at, datetime):
            interval = (remind_at - utcnow)
            if remind_at is None or interval <= timedelta(hours=0):
                if info != '':
                    out_str = f'```{tr(lang, "Parsing hints")}:\n{hints(lang, info)}```\n'
                else:
                    out_str = ''

                if interval == timedelta(hours=0):
                    # only append full help on invalid strings
                    # not on negative intervals
                    out_str += format_help
                elif interval < timedelta(hours=0):
                    out_str += tr(lang, 'Make sure your server is using the correct timezone `/timezone`')

                embed = discord.Embed(title=failed, color=0xff0000, description=out_str)
                embed.set_footer(text=footer)
                await ctx.respond(embed=embed, ephemeral=True)
                return  # error exit

        elif remind_at is None:
            if info != '':
                out_str = f'```{tr(lang, "Parsing hints")}:\n{hints(lang, info)}```\n'
            else:
                out_str = ''
            out_str += format_help

            embed = discord.Embed(title=failed, color=0xff0000, description=out_str)
            embed.set_footer(text=footer)
            await ctx.respond(embed=embed, ephemeral=True)
            return  

        elif isinstance(remind_at, str):

            # interval rules live in the local time of the server/user, to the minute
            dtstart = utcnow.replace(tzinfo=tz.UTC).astimezone(tz.gettz(tz_str)).replace(tzinfo=None)
            dtstart = timeutil.to_minute(dtstart)

            rrule, info = lib.input_parser.rrule_normalize(remind_at, dtstart=dtstart, tz_str=tz_str)
            if rrule and not rrule.after(dtstart):
                # e.g. 'every day until 1 jan 2020'
                rrule, info = None, '• this repetition has no date in the future'
            if not rrule:
                if info != '':
                    out_str = f'```{tr(lang, "Parsing hints")}:\n{hints(lang, info)}```\n'
                else:
                    # only show general help, if normalizing doesn't give
                    # specific error
                    out_str = format_help

                embed = discord.Embed(title=failed, color=0xff0000, description=out_str)
                embed.set_footer(text=footer)
                await ctx.respond(embed=embed, ephemeral=True)
                return

        if auto_del_action == Connector.AutoDelete.HIDE or personal:
            defer_hidden=True
        else:
            defer_hidden=False
        await ctx.defer(ephemeral=defer_hidden) # allow more headroom for response latency, before command fails
        rem = Reminder()

        last_msg = None
        if not personal:
            # the last message, for a jump link
            try:
                history = await ctx.channel.history(limit=1).flatten()
                last_msg = history[0] if history else None
            except discord.HTTPException:
                pass


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
                    info += tr(lang, '\n• Failed to resolve the target channel. The reminder *might* not be delivered due to missing permissions.')
            else:
                # channel name by attribute
                rem.ch_name = channel.name[0:25] # only keep first 25 letters
           
            # independant of channel itself
            rem.g_id = ctx.guild.id
            rem.ch_id = channel.id

            if rem.ch_id != ctx.channel_id:
                info += tr(lang, '\n• This reminder will be delivered to `{channel}`.\nMake sure this bot has permission to send '
                               'messages into that channel', channel=rem.ch_name)


        rem.msg = message
        rem.at = remind_at
        rem.author = author.id
        # what the bot sends later is in the author's language
        rem.lang = lang

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

        if not personal and rem.is_for_a_member() and Connector.get_dm_delivery(ctx.guild.id):
            # the server sends the reminders of its members by DM
            rem.by_dm = True

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
    # pinging others: moderators only by default. Admins can open it to other
    # roles in Server Settings > Integrations (/remindme stays open to all)
    @commands.slash_command(name='remind', description='Remind another member or a role (moderators by default)',
                            description_localizations={'fr': 'Rappeler un autre membre ou un rôle (modérateurs par défaut)'},
                            default_member_permissions=discord.Permissions(manage_messages=True))
    async def remind_user(self, ctx:discord.ApplicationContext,
                        target:discord.Option((discord.Member, discord.Role), 'the member or role to remind', required=True,
                                              description_localizations={'fr': 'le membre ou le rôle à qui rappeler'}),
                        time:discord.Option(str, 'when: in 2h, tomorrow 9:00, every friday at 7 (see /help)', required=True,
                                            autocomplete=time_autocomplete, description_localizations={'fr': 'quand : dans 2h, demain 9h, tous les vendredis à 7h (voir /help)'}),
                        message:discord.Option(str, 'what to remind them of', required=True,
                                               description_localizations={'fr': 'de quoi lui rappeler'},
                                               max_length=MAX_MESSAGE_LEN)):
                        #channel:discord.Option((discord.TextChannel,discord.VoiceChannel), 'Show the reminder in a channel other than the current one', required=False)=None):

        channel=None
        if ctx.guild:
            # update channel, when not specified (optional parameter)
            channel = channel or ctx.channel

        await self.process_reminder(ctx, ctx.author, target, time, message, channel=channel)
    

    @commands.slash_command(name='remindme', description='Set a reminder for yourself',
                            description_localizations={'fr': 'Créer un rappel pour toi'},
                            **lib.permissions.EVERYWHERE)
    async def remindme(self, ctx:discord.ApplicationContext,
                        time:discord.Option(str, 'when: in 2h, tomorrow 9:00, every friday at 7 (see /help)', required=True,
                                            autocomplete=time_autocomplete, description_localizations={'fr': 'quand : dans 2h, demain 9h, tous les vendredis à 7h (voir /help)'}),
                        message:discord.Option(str, 'what to remind you of', required=True,
                                               description_localizations={'fr': 'de quoi te rappeler'},
                                               max_length=MAX_MESSAGE_LEN)):
                        #channel:discord.Option((discord.TextChannel,discord.VoiceChannel), 'Show the reminder in a channel other than the current one', required=False)=None):
        channel = None
        if not lib.permissions.is_personal_context(ctx):
            channel = channel or ctx.channel # overwrite if not specified

        await self.process_reminder(ctx, ctx.author, ctx.author, time, message, channel=channel)
        


def setup(client):
    client.add_cog(ReminderCreation(client))
