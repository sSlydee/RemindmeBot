import discord
import lib.timeutil as timeutil
from enum import Enum
from datetime import datetime, timedelta
from dateutil import tz
import validators
import logging

import util.interaction
from util.consts import Consts
import util.verboseErrors
import lib.input_parser
import lib.ReminderRepeater
from lib.Reminder import Reminder, IntervalReminder
from lib.Connector import Connector

log = logging.getLogger('Remindme.Listing')


class STMState(Enum):
        INIT=0

class STM():
    def __init__(self, ctx, scope):
        self.ctx: discord.ApplicationContext=ctx
        self.scope:Connector.Scope=scope
        self.state:STMState = STMState.INIT
        self.page:int=0
        self.reminders:list[Reminder] = []
        self.tz_str:str = None


class ReminderChannelEdit(util.interaction.CustomView):
    # channels a reminder can be posted in (forums and media channels only accept threads)
    CHANNEL_TYPES = [
        discord.ChannelType.text,
        discord.ChannelType.voice,
        discord.ChannelType.news,
        discord.ChannelType.stage_voice,
        discord.ChannelType.public_thread,
        discord.ChannelType.private_thread,
        discord.ChannelType.news_thread,
    ]

    def __init__(self, reminder: Reminder, stm: STM, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner_id = stm.ctx.author.id
        self.reminder = reminder
        self.stm = stm

        # Discord's own channel picker: searchable, lists every channel and thread,
        # starts on the current channel of the reminder
        defaults = None
        if reminder.ch_id:
            defaults = [discord.SelectDefaultValue(id=reminder.ch_id, type=discord.SelectDefaultValueType.channel)]
        self.drop_down = discord.ui.Select(
            select_type=discord.ComponentType.channel_select,
            channel_types=ReminderChannelEdit.CHANNEL_TYPES,
            placeholder='Select the channel for this reminder',
            min_values=1,
            max_values=1,
            default_values=defaults,
            row=0
        )
        self.drop_down.callback = self.channel_selected_callback
        self.add_item(self.drop_down)


    def get_embed(self) -> discord.Embed:
        eb = self.reminder.get_info_embed(self.stm.tz_str)
        eb.title = 'Select a new channel'
        return eb


    async def _check_channel(self, new_ch) -> discord.Embed:
        """error embed if the reminder can't be delivered into new_ch, None if it can"""
        if not new_ch:
            return discord.Embed(title='Failed to edit Reminder',
                                 description='Couldn\'t resolve the selected channel. Ensure that I have sufficient permissions.',
                                 color=Consts.col_err)

        r_type = Connector.get_reminder_type(self.stm.scope.instance_id)
        if r_type == Connector.ReminderType.TEXT_ONLY:
            req_perms = discord.Permissions(send_messages=True)
            has_perms = util.verboseErrors.VerboseErrors.has_permission(req_perms, new_ch)
        else:
            has_perms = util.verboseErrors.VerboseErrors.can_send_messages(new_ch)

        if not has_perms:
            return discord.Embed(title='Failed to set new Channel',
                                 description=f'I am missing permissions to send messages in `{new_ch.name}`',
                                 color=Consts.col_err)
        return None


    async def channel_selected_callback(self, interaction: discord.Interaction):
        selected = self.drop_down.values or []
        if not selected:
            await interaction.response.defer()
            return

        new_ch_id = selected[0].id
        try:
            # fetch the full channel: the selection only carries partial data
            new_ch = await self.stm.ctx.bot.fetch_channel(new_ch_id)
        except (discord.errors.Forbidden, discord.errors.NotFound):
            new_ch = None

        err_eb = await self._check_channel(new_ch)
        if err_eb:
            if await self.open_child(interaction, util.interaction.AckView(dangerous_action=True), embed=err_eb):
                return
            # back to the channel picker
            await self.show(embed=self.get_embed(), view=self)
            return

        view = util.interaction.ConfirmDenyView()
        eb = discord.Embed(title='New Notification Channel',
                           description=f'Do you want to deliver this reminder to `{new_ch.name}`?')
        if await self.open_child(interaction, view, embed=eb):
            return

        if view.value:
            # store the channel change (same 25 char limit as on creation)
            Connector.set_reminder_channel(self.reminder._id, new_ch_id, new_ch.name[0:25])
            self.reminder.ch_id = new_ch_id
            self.reminder.ch_name = new_ch.name[0:25]
            # done: the caller shows the reminder again
            self.stop()
        else:
            # back to the channel picker
            await self.show(embed=self.get_embed(), view=self)


    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.danger, row=1)
    async def cancel_btn(self, button:  discord.ui.Button, interaction: discord.Interaction):
        self.stop() # back to the edit menu, which answers this click



class RuleMode(Enum):
    RRULE_ADD=0
    RRULE_EX_ADD=1
    DATE_ADD=2
    DATE_EX_ADD=3


class ReportErrors:
    """popups: log errors to the bot log and tell the user"""
    async def on_error(self, error: Exception, interaction: discord.Interaction):
        await util.interaction.report_error(error, interaction, type(self).__name__)


class RuleModal(ReportErrors, discord.ui.DesignerModal):
    """popup asking for one rule or date

    help_text (optional) is shown above the field and may contain links
    (a 'designer' modal: a plain Modal only holds text fields)
    """
    def __init__(self, field, custom_callback, mode: RuleMode, help_text: str = None, *args, **kwargs):
        # forgotten popups are dropped with their menu
        kwargs.setdefault('timeout', util.interaction.MENU_TIMEOUT)
        super().__init__(*args, **kwargs)
        self.value = None
        self.custom_callback = custom_callback
        self.mode = mode

        if help_text:
            self.add_item(discord.ui.TextDisplay(help_text))

        self.input = discord.ui.InputText(style=discord.InputTextStyle.singleline)
        self.add_item(discord.ui.Label(field, self.input))


    def _submitted_value(self, interaction: discord.Interaction):
        """the text typed in the field, found by its custom_id in the submitted data

        (py-cord matches submitted components to the modal items by position,
        which would break if Discord left the text display out of the payload)
        """
        def walk(components):
            for comp in components or []:
                if comp.get('custom_id') == self.input.custom_id:
                    return comp.get('value')
                nested = comp.get('components') or ([comp['component']] if 'component' in comp else [])
                found = walk(nested)
                if found is not None:
                    return found
            return None

        value = walk((interaction.data or {}).get('components'))
        return value if value is not None else self.input.value


    async def callback(self, interaction: discord.Interaction):
        user_input = self._submitted_value(interaction)
        self.value = user_input

        
        if self.custom_callback:
            await self.custom_callback(interaction, self.value, self.mode)
        else:
            await interaction.response.send_message('OK', ephemeral=True)



def optional_input(**kwargs) -> discord.ui.InputText:
    """an InputText the user may leave empty

    py-cord 2.7 turns required=False into None in the payload, which
    Discord reads as required (fixed in py-cord 2.8). Set it afterwards.
    """
    item = discord.ui.InputText(**kwargs)
    item.required = False
    return item


class EditModal(ReportErrors, discord.ui.Modal):
    def __init__(self, reminder: Reminder, tz_str:str, custom_callback, *args, **kwargs):
        kwargs.setdefault('timeout', util.interaction.MENU_TIMEOUT)
        super().__init__(*args, **kwargs)
        self.value = None
        self.custom_callback = custom_callback
        self.reminder = reminder
        self.tz = tz_str


        self.add_item(
            optional_input(
                label='Title',
                placeholder='(optional)',
                value=self.reminder.title,
                style=discord.InputTextStyle.singleline
            )
        )
        self.add_item(discord.ui.InputText(
                label='Content',
                value=self.reminder.msg,
                required=True,
                style=discord.InputTextStyle.paragraph
            )
        )
        self.add_item(optional_input(
            label='Image Url (optional)',
            value=self.reminder.img_url,
            style=discord.InputTextStyle.singleline
        ))

        self.prefilled_at = None
        if not isinstance(self.reminder, IntervalReminder):
            # local time with its offset (e.g. +01:00), without microseconds
            local_at = self.reminder.at.replace(tzinfo=tz.UTC).astimezone(tz=tz.gettz(tz_str))
            self.prefilled_at = local_at.replace(microsecond=0).isoformat()
            self.add_item(discord.ui.InputText(
                label='Remind at (date or ISO timestamp)',
                value=self.prefilled_at,
                required=True,
                style=discord.InputTextStyle.singleline
                )
            )
        else:
            self.add_item(optional_input(
                label='Remind at',
                placeholder='Edit Intervals with `/reminder_list`',
                style=discord.InputTextStyle.singleline
                )
            )


    async def callback(self, interaction: discord.Interaction):

        info = ''

        # title
        new_title = self.children[0].value
        new_msg = self.children[1].value
        new_imgurl = self.children[2].value
        new_at = self.children[3].value
        
        new_title = new_title or None
        if new_title != (self.reminder.title or None):
            self.reminder.title = new_title
            Connector.set_reminder_title(self.reminder._id, self.reminder.title)

        if new_msg != self.reminder.msg:
            self.reminder.msg = new_msg
            Connector.set_reminder_message(self.reminder._id, self.reminder.msg)

        new_imgurl = (new_imgurl or '').strip()
        if new_imgurl != (self.reminder.img_url or ''):
            if not new_imgurl:
                # an empty field removes the image
                self.reminder.img_url = None
                Connector.set_reminder_img_url(self.reminder._id, None)
            else:
                # check if the given url is actually valid
                try:
                    success = validators.url(new_imgurl)
                except Exception:
                    success = False
                if success:
                    self.reminder.img_url = new_imgurl
                    Connector.set_reminder_img_url(self.reminder._id, self.reminder.img_url)
                else:
                    info += f'Didn\'t change the image: `{new_imgurl[:100]}` is not a valid URL.\n'


        if not isinstance(self.reminder, IntervalReminder):
            new_at = (new_at or '').strip()
            # only parse the date when the user changed it,
            # the pre-filled value is the current due date
            if new_at and new_at != self.prefilled_at:
                utcnow = timeutil.utcnow()
                # same parser as /remindme: ISO timestamps (without offset: server timezone),
                # relative times and natural dates
                parsed_at, parse_info = lib.input_parser.parse(new_at, utcnow, self.tz)

                if not isinstance(parsed_at, datetime) or parsed_at == utcnow:
                    info += f'Didn\'t change the reminder date: couldn\'t read `{new_at[:100]}`.\n'
                    if isinstance(parsed_at, str):
                        info += 'Repeating dates must be added with `Set Interval`.\n'
                    elif parse_info:
                        info += f'```{parse_info}```\n'
                elif parsed_at <= utcnow:
                    info += 'Didn\'t change the reminder date: it must be in the future.\n'
                else:
                    self.reminder.at = parsed_at
                    Connector.update_reminder_at(self.reminder)
        else:
            if new_at:
                info += 'The `Interval` attribute must be edited with `Edit Interval`.\n'


        if self.custom_callback:
            # the menu shows the result, info is what wasn't changed
            await self.custom_callback(interaction, info)
        else:
            await interaction.response.send_message(info or 'Reminder updated', ephemeral=True)

        self.stop()


RRULE_GENERATOR_URL = 'https://www.textmagic.com/free-tools/rrule-generator'


def reload_reminder(reminder):
    """the stored version of a reminder or interval, None if it is gone
       (delivered or deleted meanwhile)
    """
    if isinstance(reminder, IntervalReminder):
        return Connector.get_interval_by_id(reminder._id)
    return Connector.get_reminder_by_id(reminder._id)


class ReminderIntervalAddView(util.interaction.CustomView):
    def __init__(self, reminder: Reminder, stm: STM, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner_id = stm.ctx.author.id

        self.reminder = reminder
        self.stm = stm
        self.update_btn_activation()

    # one-click repetitions, based on the date and time of the reminder
    QUICK_RULES = {
        'daily': ('Every day', 'FREQ=DAILY'),
        'weekdays': ('Every weekday (Mon-Fri)', 'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR'),
        'weekly': ('Every week', 'FREQ=WEEKLY'),
        'biweekly': ('Every 2 weeks', 'FREQ=WEEKLY;INTERVAL=2'),
        'monthly': ('Every month', 'FREQ=MONTHLY'),
        'yearly': ('Every year', 'FREQ=YEARLY'),
    }

    def get_embed(self) -> discord.Embed:
        return discord.Embed(
            title='Add new rules',
            description='Pick a quick repetition below, or add a rule written like '\
                        '`every friday at 7`, `every 2 weeks` or `every weekday`.\n'\
                        'RRULEs work too (e.g. `FREQ=MONTHLY;BYDAY=1MO`): '\
                        f'you can use an [RRULE Generator]({RRULE_GENERATOR_URL}).'
        )

    def update_btn_activation(self):
        """disable rule buttons if too many rules are present
        """
        if isinstance(self.reminder, IntervalReminder):
            if len(self.reminder.get_rule_dicts()) >= 25:
                disabled=True
            else:
                disabled=False
        else:
            disabled=False

        for btn in self.children:
            btn.disabled=disabled

        self.return_btn.disabled=False # always allow return


    async def rrule_callback(self, interaction: discord.Interaction, user_input: str, mode: RuleMode):
        """a rule from the popup or the quick repeat dropdown (interaction)"""
        if await self.answer_expired(interaction):
            return

        action_str = 'Rrule' if mode==RuleMode.RRULE_ADD else 'Rrule exception'
        action_modifier = '*not*' if mode==RuleMode.RRULE_EX_ADD else ''

        # the rule frame is the local time of the server (of the user, in DMs)
        if isinstance(self.reminder, IntervalReminder):
            dtstart = self.reminder.first_at
        else:
            dtstart = lib.ReminderRepeater.utc_to_rule_frame(self.reminder.at, lib.ReminderRepeater.instance_id_of(self.reminder))

        rule_tz = Connector.get_timezone(lib.ReminderRepeater.instance_id_of(self.reminder))
        rrule, error = self._parse_rule(user_input, dtstart, rule_tz)

        if not rrule:
            error_str = error or 'Unknown error occurred while parsing the rrule.'
            embed = discord.Embed(title='Invalid rrule',
                                  color=0xff0000,
                                  description=error_str+'\nPlease try again. '\
                                              f'You can build an RRULE with an [RRULE Generator]({RRULE_GENERATOR_URL}).')
            if await self.open_child(interaction, util.interaction.AckView(), embed=embed):
                return

        else:
            # success
            eb = discord.Embed(title=f'New {action_str}',
                           description='Add the rule `{:s}`?. The reminder is {:s} triggered according to this rule.'\
                                        .format(str(rrule), action_modifier))
            preview = self._preview(rrule, rule_tz)
            if preview:
                name = 'Skipped dates' if mode == RuleMode.RRULE_EX_ADD else 'Next dates of this rule'
                eb.add_field(name=name, value=preview, inline=False)
            view = util.interaction.ConfirmDenyView(dangerous_action=False)
            if await self.open_child(interaction, view, embed=eb):
                return

            if view.value:
                # store to db
                if mode == RuleMode.RRULE_ADD:
                    self.reminder = lib.ReminderRepeater.add_rules(self.reminder, rrule=str(rrule))
                else:
                    self.reminder = lib.ReminderRepeater.add_rules(self.reminder, exrule=str(rrule))

        # back to this menu in any case
        self.update_btn_activation() # update in case too many rules are present
        await self.show(embed=self.get_embed(), view=self)


    @staticmethod
    def _parse_rule(user_input: str, dtstart, rule_tz: str):
        """rule from an RRULE or from natural language ('every friday at 7')

        Returns:
            (rrule, str): the rule (None on failure) and an error message
        """
        text = (user_input or '').strip()
        if 'freq=' not in text.lower():
            # natural language, same parser as /remindme
            parsed, _ = lib.input_parser.parse(text, timeutil.utcnow(), rule_tz)
            if isinstance(parsed, datetime):
                return None, 'This is a single date, not a repetition: use `Add Single Date` for it.'
            if not isinstance(parsed, str):
                return None, f'Couldn\'t read a repetition from `{text[:100]}`.\n'\
                             'Try e.g. `every friday at 7`, `every 2 weeks`, or an RRULE like `FREQ=WEEKLY;BYDAY=FR`.'
            text = parsed
        return lib.input_parser.rrule_normalize(text.lower(), dtstart, rule_tz)


    @staticmethod
    def _preview(rrule, rule_tz: str, count: int = 3) -> str:
        """the next dates of a rule (rule frame: local time) as Discord timestamps"""
        local_tz = tz.gettz(rule_tz)
        local_now = timeutil.utcnow().replace(tzinfo=tz.UTC).astimezone(local_tz).replace(tzinfo=None)
        try:
            dates = list(rrule.xafter(local_now, count=count))
        except Exception:
            return ''
        return '\n'.join(f'<t:{int(d.replace(tzinfo=local_tz).timestamp())}:F>' for d in dates)


    @discord.ui.select(
        placeholder='Quick repeat...',
        min_values=1,
        max_values=1,
        options=[discord.SelectOption(label=label, value=key) for key, (label, _) in QUICK_RULES.items()],
        row=0
    )
    async def quick_repeat(self, select: discord.ui.Select, interaction: discord.Interaction):
        _, rule = ReminderIntervalAddView.QUICK_RULES[select.values[0]]
        await self.rrule_callback(interaction, rule, RuleMode.RRULE_ADD)


    @staticmethod
    def _date_error(date, info: str, user_input: str, utcnow: datetime) -> str:
        """why a parsed single date can't be used, None if it can"""
        if isinstance(date, str):
            return 'This is a repetition, not a single date: use `Add Repeating Rule` for it.'
        if not isinstance(date, datetime) or date == utcnow:
            # the parser returns 'now' when it can't read the input
            return info or f'Couldn\'t read a date from `{(user_input or "")[:100]}`.'
        if date <= utcnow:
            return 'Only dates in the future are allowed.'
        return None


    async def date_callback(self, interaction: discord.Interaction, user_input: str, mode: RuleMode):
        """a single date from the popup (interaction)"""
        if await self.answer_expired(interaction):
            return

        action_str = 'single date' if mode==RuleMode.DATE_ADD else 'date exception'

        utcnow = timeutil.utcnow()
        date, info = lib.input_parser.parse(user_input, utcnow, self.stm.tz_str)
        error_str = self._date_error(date, info, user_input, utcnow)

        if error_str:
            embed = discord.Embed(title='Invalid input date',
                                  color=0xff0000,
                                  description=error_str+'\nPlease try again.')
            if await self.open_child(interaction, util.interaction.AckView(), embed=embed):
                return

        else:
            # success
            localized_date = date.replace(tzinfo=tz.UTC).astimezone(tz.gettz(self.stm.tz_str))

            eb = discord.Embed(title=f'New {action_str}',
                           description='Do you want to add the date `{:s}`? as a new {:s}.'\
                                        .format(localized_date.strftime('%Y-%m-%d %H:%M %Z'), action_str))
            view = util.interaction.ConfirmDenyView(dangerous_action=False)
            if await self.open_child(interaction, view, embed=eb):
                return

            if view.value:
                # rule dates live in the rule frame (local time of the server or user)
                rule_date = lib.ReminderRepeater.utc_to_rule_frame(date, lib.ReminderRepeater.instance_id_of(self.reminder))
                if mode == RuleMode.DATE_ADD:
                    self.reminder = lib.ReminderRepeater.add_rules(self.reminder, rdate=rule_date)
                else:
                    self.reminder = lib.ReminderRepeater.add_rules(self.reminder, exdate=rule_date)

        # back to this menu in any case
        self.update_btn_activation() # update in case too many rules are present
        await self.show(embed=self.get_embed(), view=self)


    @discord.ui.button(label='Add Repeating Rule', style=discord.ButtonStyle.secondary, row=1)
    async def add_rrule(self, button:  discord.ui.Button, interaction: discord.Interaction):

        modal = RuleModal(field='Repeat, e.g. "every friday at 7" or an RRULE',
                            title='Add Repeating Rule',
                            custom_callback=self.rrule_callback,
                            mode=RuleMode.RRULE_ADD,
                            help_text='Write the repetition in plain words (`every friday at 7`, `every 2 weeks`, '\
                                      '`every weekday`) or paste an RRULE.\n'\
                                      f'Build an RRULE with the [RRULE Generator]({RRULE_GENERATOR_URL}).')
        await interaction.response.send_modal(modal)



    @discord.ui.button(label='Add Exception Rule', style=discord.ButtonStyle.secondary, row=1)
    async def add_rrule_ex(self, button:  discord.ui.Button, interaction: discord.Interaction):

        modal = RuleModal(field='Skip, e.g. "every saturday" or an RRULE',
                            title='Add Exception Rule',
                            custom_callback=self.rrule_callback,
                            mode=RuleMode.RRULE_EX_ADD,
                            help_text='The reminder will **not** be sent on the dates of this rule. '\
                                      'Write it in plain words (`every saturday`) or paste an RRULE.\n'\
                                      f'Build an RRULE with the [RRULE Generator]({RRULE_GENERATOR_URL}).')
        await interaction.response.send_modal(modal)



    @discord.ui.button(label='Add Single Date', style=discord.ButtonStyle.secondary, row=2)
    async def add_single(self, button:  discord.ui.Button, interaction: discord.Interaction):

        modal = RuleModal(field='Enter a new date (fuzzy or iso)',
                            title='Add a single occurrence date',
                            custom_callback=self.date_callback,
                            mode=RuleMode.DATE_ADD)
        await interaction.response.send_modal(modal)


    @discord.ui.button(label='Add Exception Date', style=discord.ButtonStyle.secondary, row=2)
    async def add_single_ex(self, button:  discord.ui.Button, interaction: discord.Interaction):

        modal = RuleModal(field='Enter an exclusion date (fuzzy or iso)',
                            title='Add a single exclusion date',
                            custom_callback=self.date_callback,
                            mode=RuleMode.DATE_EX_ADD)
        await interaction.response.send_modal(modal)



    @discord.ui.button(label='Return', style=discord.ButtonStyle.secondary, row=3)
    async def return_btn(self, button:  discord.ui.Button, interaction: discord.Interaction):
        self.stop() # back to the previous menu, which answers this click


class ReminderIntervalModifyView(util.interaction.CustomView):
    def __init__(self, reminder: IntervalReminder, stm, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner_id = stm.ctx.author.id

        self.reminder: IntervalReminder = reminder
        self.stm = stm
        self.rule_index:int = None

        # this button possibly can't be active w/o selection
        self.del_rule.disabled=True

        # populate the dropdown selection
        self.update_dropdown()



    def get_embed(self, rule_id:int=None) -> discord.Embed:

        rules = self.reminder.get_rule_dicts()

        if self.rule_index is None:
            descr = 'You can show more detailed information for existing rules.'\
                            'You can aswell delete selected rules/dates'
        else:
            descr = rules[self.rule_index]['descr']

        return discord.Embed(
            title='Show/Delete existing rules',
            description=descr
        )


    def update_dropdown(self):
        rules = self.reminder.get_rule_dicts()

        dd_search = [x for x in self.children if isinstance(x, discord.ui.Select)]

        rule_options = [discord.SelectOption(
                        label=r['label'],
                        description=r['descr'],
                        value=str(i),
                        default=(i==self.rule_index)) for i, r in enumerate(rules)]

        if dd_search and rule_options:
            dd = dd_search[0]
            dd.options = []
            for opt in rule_options:
                dd.append_option(opt)
        elif dd_search and not rule_options:
            # delete action row
            self.remove_item(dd_search[0])
        elif rule_options:
            self.drop_down = discord.ui.Select(
                placeholder='Select a rule/date for more info',
                min_values=1,
                max_values=1,
                options=rule_options,
                row=1
            )
            self.drop_down.callback = self.drop_callback
            self.add_item(self.drop_down)

        # else pass


    def _reset_selection(self):
        self.rule_index=None
        self.del_rule.disabled=True
        self.update_dropdown()


    @discord.ui.button(label='Add New Rule', style=discord.ButtonStyle.primary, row=2)
    async def add_rule(self, button:  discord.ui.Button, interaction: discord.Interaction):
        view = ReminderIntervalAddView(self.reminder, self.stm)
        if await self.open_child(interaction, view, embed=view.get_embed()):
            return
        self.reminder = view.reminder

        # back to this menu
        self._reset_selection()
        await self.show(embed=self.get_embed(), view=self)



    @discord.ui.button(label='Delete Selected', style=discord.ButtonStyle.danger, row=2)
    async def del_rule(self, button:  discord.ui.Button, interaction: discord.Interaction):

        rules = self.reminder.get_rule_dicts()
        rule_descr = rules[self.rule_index]['descr']

        view = util.interaction.ConfirmDenyView(dangerous_action=True)
        embed = discord.Embed(
            title='Danger',
            description=f'Are you sure to delete the rule `{rule_descr}`?',
            color=0xff0000
        )
        if await self.open_child(interaction, view, embed=embed):
            return

        if view.value:
            # go aheaad with deletion
            self.reminder = lib.ReminderRepeater.rm_rules(self.reminder, rule_idx=self.rule_index)

            if not self.reminder.at:
                eb = discord.Embed(title='Orphan warning',
                    color=0xaa3333,
                    description='The reminder has no further events pending. It will be deleted soon, if no new rule is added')
                if await self.open_child(None, util.interaction.AckView(dangerous_action=True), embed=eb):
                    return

        if isinstance(self.reminder, IntervalReminder):
            # back to this menu
            self._reset_selection()
            await self.show(embed=self.get_embed(), view=self)
        else:
            # no rule left: a single reminder again, back to the edit menu
            self.stop()



    @discord.ui.button(label='Return', style=discord.ButtonStyle.secondary, row=3)
    async def return_btn(self, button:  discord.ui.Button, interaction: discord.Interaction):
        self.stop() # back to the edit menu, which answers this click



    async def drop_callback(self, interaction: discord.Interaction):
        sel = interaction.data['values'][0] # min_select 1
        self.rule_index = int(sel)

        # update the embed with the rule details
        self.del_rule.disabled=False
        eb = self.get_embed()
        self.update_dropdown()
        await self.show(interaction, embed=eb, view=self)




class ReminderEditView(util.interaction.CustomView):
    def __init__(self, reminder: Reminder, stm, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner_id = stm.ctx.author.id

        self.reminder = reminder
        self.stm = stm
        self.is_foreign = reminder.author != stm.ctx.author.id

        self._override_edit_label()

        if self.stm.scope.is_private:
            # private reminders cannot change the channel
            self.edit_channel.disabled=True

        if self.is_foreign:
            self.edit_channel.disabled = True
            self.set_interval.disabled = True
            self.edit_reminder_btn.disabled = True
            self.pause_btn.disabled = True


    def _override_edit_label(self):
        if isinstance(self.reminder, IntervalReminder):
            self.set_interval.label = 'Edit Interval' # override decorator
            self.pause_btn.disabled = self.is_foreign
            if self.reminder.paused:
                self.pause_btn.label = 'Resume'
                self.pause_btn.emoji = '▶️'
            else:
                self.pause_btn.label = 'Pause'
                self.pause_btn.emoji = '⏸️'
        else:
            self.set_interval.label = 'Set Interval'
            # only repeating reminders can be paused
            self.pause_btn.label = 'Pause'
            self.pause_btn.emoji = '⏸️'
            self.pause_btn.disabled = True


    def get_embed(self) -> discord.Embed:
        return self.reminder.get_info_embed(self.stm.tz_str)


    @discord.ui.button(label='Edit Channel', style=discord.ButtonStyle.primary)
    async def edit_channel(self, button:  discord.ui.Button, interaction: discord.Interaction):

        view = ReminderChannelEdit(self.reminder, self.stm)
        if await self.open_child(interaction, view, embed=view.get_embed()):
            return

        # back to this menu
        await self.show(embed=self.get_embed(), view=self)



    @discord.ui.button(label='Set Interval', style=discord.ButtonStyle.primary)
    async def set_interval(self, button:  discord.ui.Button, interaction: discord.Interaction):

        if isinstance(self.reminder, IntervalReminder):
            view = ReminderIntervalModifyView(self.reminder, self.stm)
        else:
            view = ReminderIntervalAddView(self.reminder, self.stm)

        if await self.open_child(interaction, view, embed=view.get_embed()):
            return
        # a reminder with rules becomes an interval (and back), with a new id
        self.reminder = view.reminder

        # back to this menu
        self._override_edit_label()
        await self.show(embed=self.get_embed(), view=self)


    @discord.ui.button(label='Edit', emoji='🛠️', style=discord.ButtonStyle.secondary)
    async def edit_reminder_btn(self, button: discord.ui.Button, interaction: discord.Interaction):
        modal = EditModal(reminder=self.reminder,
                          custom_callback=self.edit_done,
                          tz_str=self.stm.tz_str,
                          title='Edit the Reminder')
        await interaction.response.send_modal(modal)


    async def edit_done(self, interaction: discord.Interaction, info: str):
        """the edit popup was submitted (interaction), info: what wasn't changed"""
        if await self.answer_expired(interaction, saved=True):
            return

        reloaded = reload_reminder(self.reminder)
        if reloaded is None:
            await interaction.response.send_message('This reminder was delivered or deleted while you edited it.', ephemeral=True)
            self.stop() # back to the list
            return

        self.reminder = reloaded
        await self.show(interaction, embed=self.get_embed(), view=self)
        if info:
            await interaction.followup.send(info, ephemeral=True)


    @discord.ui.button(label='Pause', emoji='⏸️', style=discord.ButtonStyle.secondary, row=1)
    async def pause_btn(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not isinstance(self.reminder, IntervalReminder):
            await interaction.response.defer()
            return

        # paused intervals keep moving to their next date, but are not sent
        self.reminder.paused = not self.reminder.paused
        Connector.set_interval_paused(self.reminder._id, self.reminder.paused)

        self._override_edit_label()
        await self.show(interaction, embed=self.get_embed(), view=self)


    @discord.ui.button(label='Return', style=discord.ButtonStyle.secondary, row=2)
    async def ret_menu(self, button:  discord.ui.Button, interaction: discord.Interaction):
        self.stop() # back to the list, which answers this click


    @discord.ui.button(label='Delete', style=discord.ButtonStyle.danger, row=2)
    async def delete_reminder(self, button:  discord.ui.Button, interaction: discord.Interaction):

        view = util.interaction.ConfirmDenyView(dangerous_action=True)
        eb = self.get_embed()
        eb.title = 'Delete Reminder?'
        if await self.open_child(interaction, view, embed=eb):
            return

        if view.value:
            if isinstance(self.reminder, IntervalReminder):
                Connector.delete_interval(self.reminder._id)
            else:
                Connector.delete_reminder(self.reminder._id)
            self.stop() # back to the list, without this reminder
            return

        await self.show(embed=self.get_embed(), view=self)
