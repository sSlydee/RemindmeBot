"""The buttons under a delivered reminder: snooze, skip the next date, delete

Anyone can snooze (a copy for themselves), only the author can skip, and
lib.permissions.can_delete_reminder says who can delete.

They keep working after a restart and don't time out: their custom_id holds
the action and the reminder ('rm:<action>:<kind>:<id>'), and handle_click()
(called by ReminderModule.on_interaction) acts on it. No view waits in memory.

kind: 'r' for a one-shot reminder (kept DELIVERED_KEEP after its delivery
for this), 'i' for an interval.
"""
import logging
from datetime import timedelta

import discord
from bson import ObjectId
from bson.errors import InvalidId
from dateutil import tz

import lib.input_parser
import lib.permissions
import lib.ReminderRepeater
import lib.timeutil as timeutil
from lib.Connector import Connector
from lib.Reminder import Reminder, IntervalReminder
import util.interaction
from util.reminderInteraction import ReportErrors

log = logging.getLogger('Remindme.Buttons')

PREFIX = 'rm'
# how long the buttons of a delivered one-shot reminder keep working
DELIVERED_KEEP = timedelta(days=7)

# snooze buttons: action -> (label, delay); None: computed when clicked
SNOOZES = {
    '10m': ('+10 min', timedelta(minutes=10)),
    '1h': ('+1 hour', timedelta(hours=1)),
    'tmr': ('Tomorrow 9:00', None),
    'other': ('Other…', None),
}
GONE = 'This reminder is gone: deleted, or delivered more than 7 days ago.'


def custom_id(action: str, rem: Reminder) -> str:
    kind = 'i' if isinstance(rem, IntervalReminder) else 'r'
    return f'{PREFIX}:{action}:{kind}:{rem._id}'


def parse_custom_id(cid: str):
    """(action, kind, id) of one of these buttons, None for other components"""
    parts = (cid or '').split(':')
    if len(parts) != 4 or parts[0] != PREFIX or parts[2] not in ('r', 'i'):
        return None
    try:
        return parts[1], parts[2], ObjectId(parts[3])
    except InvalidId:
        return None


def delivered_view(rem: Reminder, snoozed: str = None, deleted=False) -> discord.ui.View:
    """the buttons for a delivered reminder

    snoozed: the snooze action the author used (the snooze buttons are done then)
    deleted: the interval was deleted (all buttons are done)
    """
    # store=False: py-cord doesn't keep it, the clicks go to handle_click()
    view = discord.ui.View(timeout=None, store=False)
    for action, (label, _) in SNOOZES.items():
        view.add_item(discord.ui.Button(
            label=label, emoji='⏱️' if action != 'other' else None, row=0,
            custom_id=custom_id(action, rem),
            style=discord.ButtonStyle.green if action == snoozed else discord.ButtonStyle.blurple,
            disabled=bool(snoozed) or deleted))
    if isinstance(rem, IntervalReminder):
        view.add_item(discord.ui.Button(label='Skip next', emoji='⏭️', row=1, disabled=deleted,
                                        style=discord.ButtonStyle.secondary, custom_id=custom_id('skip', rem)))
        view.add_item(discord.ui.Button(emoji='🗑️', row=1, disabled=deleted,
                                        style=discord.ButtonStyle.danger, custom_id=custom_id('del', rem)))
    return view


def _load(kind: str, rem_id) -> Reminder:
    if kind == 'i':
        return Connector.get_interval_by_id(rem_id)
    return Connector.get_delivered(rem_id)


def _snooze_tz(rem: Reminder, user_id: int) -> str:
    """timezone for 'tomorrow 9:00': the server's for its author, else the user's own"""
    if user_id == rem.author and rem.g_id:
        return Connector.get_timezone(rem.g_id)
    return Connector.get_timezone(user_id)


def _tomorrow_9(tz_str: str):
    local_tz = tz.gettz(tz_str)
    local_now = timeutil.utcnow().replace(tzinfo=tz.UTC).astimezone(local_tz)
    local = (local_now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0, tzinfo=None)
    return local.replace(tzinfo=local_tz).astimezone(tz.UTC).replace(tzinfo=None)


async def handle_click(interaction: discord.Interaction) -> bool:
    """act on a click on these buttons

    Returns:
        bool: False if the click wasn't for one of these buttons
    """
    parsed = parse_custom_id((interaction.data or {}).get('custom_id'))
    if parsed is None:
        return False
    action, kind, rem_id = parsed
    try:
        rem = _load(kind, rem_id)
        if rem is None:
            await interaction.response.send_message(GONE, ephemeral=True)
        elif action in SNOOZES:
            await _snooze_clicked(interaction, rem, action)
        elif action == 'skip' and isinstance(rem, IntervalReminder):
            await _skip(interaction, rem)
        elif action == 'del' and isinstance(rem, IntervalReminder):
            await _delete(interaction, rem)
        else:
            await interaction.response.send_message('Unknown button.', ephemeral=True)
    except Exception as e:
        await util.interaction.report_error(e, interaction, f'reminder button {action}')
    return True


async def _snooze_clicked(interaction: discord.Interaction, rem: Reminder, action: str):
    if action == 'other':
        await util.interaction.open_popup(interaction, SnoozeModal(rem, title='Snooze the reminder'))
        return
    if action == 'tmr':
        at = _tomorrow_9(_snooze_tz(rem, interaction.user.id))
    else:
        at = timeutil.utcnow() + SNOOZES[action][1]
    await snooze(interaction, rem, at, action)


async def snooze(interaction: discord.Interaction, rem: Reminder, at, action: str):
    """a copy of rem, delivered again at 'at' (naive UTC)"""
    # an interval's copy is a one-shot reminder
    snoozed = Reminder(rem._to_json())
    snoozed._id = None
    snoozed.created_at = timeutil.utcnow()
    if not snoozed.msg.endswith(' (snoozed)'):
        snoozed.msg += ' (snoozed)'
    snoozed.at = at
    when = f'<t:{int(timeutil.utc_timestamp(at))}:F>'

    if interaction.user.id != rem.author:
        # someone else: their own reminder, by DM
        snoozed.g_id = None
        snoozed.ch_id = None
        snoozed.ch_name = 'DM'
        snoozed.author = interaction.user.id
        snoozed.target = interaction.user.id
        snoozed.target_name = interaction.user.mention
        snoozed.target_mention = interaction.user.mention
        Connector.add_reminder(snoozed)
        await interaction.response.send_message(
            f'Snoozed until {when}. It will be delivered to your DMs, as you are not the author: '
            'make sure I\'m allowed to message you.', ephemeral=True)
        return

    Connector.add_reminder(snoozed)
    await interaction.response.edit_message(view=delivered_view(rem, snoozed=action))
    await interaction.followup.send(f'Snoozed until {when}.', ephemeral=True)


async def _skip(interaction: discord.Interaction, interval: IntervalReminder):
    if interaction.user.id != interval.author:
        await interaction.response.send_message('Only the author of this reminder can change it.', ephemeral=True)
        return
    try:
        skipped, interval = lib.ReminderRepeater.skip_next(interval)
    except lib.ReminderRepeater.ReminderChanged:
        await interaction.response.send_message(GONE, ephemeral=True)
        return
    if skipped is None:
        await interaction.response.send_message('This reminder has no next date.', ephemeral=True)
        return
    nxt = f'<t:{int(timeutil.utc_timestamp(interval.at))}:F>' if interval.at else 'none'
    await interaction.response.send_message(
        f'Skipped <t:{int(timeutil.utc_timestamp(skipped))}:F>. Next one: {nxt}.\n'
        'To undo, delete the exclusion date in `/reminder_list` > Edit Interval.', ephemeral=True)


async def _delete(interaction: discord.Interaction, interval: IntervalReminder):
    user = interaction.user
    if not lib.permissions.can_delete_reminder(interval, user):
        await interaction.response.send_message(
            'Only the author of this reminder, the member it is for, or a moderator can delete it.', ephemeral=True)
        return
    Connector.delete_interval(interval._id)
    if user.id == interval.author:
        by = 'its author'
    else:
        by = user.mention
        log.info(f'reminder {interval._id} of {interval.author} deleted by {user.id}')
    await interaction.response.edit_message(
        embed=discord.Embed(title='Deleted Reminder', description=f'The reminder was deleted by {by}', color=0x409fe2),
        view=delivered_view(interval, deleted=True))


class SnoozeModal(ReportErrors, discord.ui.Modal):
    """'Other…': snooze until a time typed like in /remindme"""
    def __init__(self, rem: Reminder, *args, **kwargs):
        kwargs.setdefault('timeout', util.interaction.POPUP_TIMEOUT)
        super().__init__(*args, **kwargs)
        self.rem = rem
        self.add_item(discord.ui.InputText(label='Snooze until', placeholder='in 2h, tomorrow 18:00, friday 9:00',
                                           style=discord.InputTextStyle.singleline, max_length=100))

    async def callback(self, interaction: discord.Interaction):
        text = self.children[0].value or ''
        utcnow = timeutil.utcnow()
        at, info = lib.input_parser.parse(text, utcnow, _snooze_tz(self.rem, interaction.user.id))
        if isinstance(at, str):
            error = 'That is a repetition, a snooze needs one date.'
        elif not at or at <= utcnow:
            error = f'Couldn\'t read a date in the future from `{text[:100]}`.'
        else:
            error = None
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await snooze(interaction, self.rem, at, 'other')
