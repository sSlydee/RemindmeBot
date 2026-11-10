import asyncio
import logging
import math
from dateutil import tz

import discord
from discord.ext import commands

from lib.Connector import Connector
import lib.permissions
from lib.Reminder import Reminder, IntervalReminder, utc_timestamp
import lib.text
import lib.input_parser

import util.interaction
import util.reminderInteraction
from util.consts import Consts
#import lib.ReminderRepeater


log = logging.getLogger('Remindme.Listing')


# what the list shows on a server (in DMs: always the user's own reminders)
MINE = 'mine'
FOR_ME = 'for_me'    # created by other members for the user: they can delete them
SERVER = 'server'    # all of the server, for moderators

MODE_LABELS = {MINE: 'My reminders', FOR_ME: 'For me', SERVER: 'Whole server'}
EMPTY_TEXTS = {
    MINE: 'No pending reminders. Create one with `/remindme`.',
    FOR_ME: 'No reminders from other members for you. When someone reminds you with `/remind`, '
            'or mentions you in a reminder, you can delete it here.',
    SERVER: 'No pending reminders on this server.',
}


def load_reminders(stm) -> list[Reminder]:
    """the reminders the list shows, sorted by date"""
    if stm.mode == FOR_ME:
        return Connector.get_reminders_for(stm.scope.guild_id, stm.scope.user_id)
    if stm.mode == SERVER:
        return Connector.get_guild_reminders(stm.scope.guild_id)
    return Connector.get_scoped_reminders(stm.scope)


# looking up names must not delay the answer to a click past Discord's 3 seconds
NAME_LOOKUP_TIMEOUT = 1.5


async def resolve_names(stm, reminders: list[Reminder]):
    """the names of the members a page shows (authors, members reminders are
       for) as plain text, in stm.names: a mention only shows a name when the
       viewer's Discord already knows that member, and the dropdown can't show
       mentions at all. Names not found in time are shown as mentions
    """
    guild = stm.ctx.guild
    if guild is None or stm.scope.is_private:
        return
    ids = {rem.author for rem in reminders}
    # a reminder for a member stores its mention as target name (for a role: the role's name)
    ids |= {rem.target for rem in reminders if rem.target_name in (f'<@{rem.target}>', f'<@!{rem.target}>')}
    ids -= set(stm.names) | {stm.scope.user_id, None}
    if not ids:
        return

    async def lookup(user_id):
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except discord.NotFound as e:
                if e.code == Consts.unknown_member:
                    stm.names[user_id] = 'a former member'
                return
        stm.names[user_id] = member.display_name

    try:
        results = await asyncio.wait_for(asyncio.gather(*(lookup(uid) for uid in ids), return_exceptions=True),
                                         NAME_LOOKUP_TIMEOUT)
    except asyncio.TimeoutError:
        log.debug(f'member names: {len(ids) - len(set(stm.names) & ids)} not found in time')
        return
    for error in (r for r in results if isinstance(r, Exception)):
        log.debug(f'member name not found: {error!r}')


class ReminderListView(util.interaction.CustomView):
    def __init__(self, stm, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.stm:util.reminderInteraction.STM = stm
        self.owner_id = stm.ctx.author.id
        self.mode_buttons = {}
        self.add_mode_buttons()
        self.update_dropdown()

    def add_mode_buttons(self):
        if self.stm.scope.is_private:
            return
        modes = [MINE, FOR_ME]
        if lib.permissions.can_moderate(self.stm.ctx.author, self.stm.scope.guild_id):
            modes.append(SERVER)
        for mode in modes:
            button = discord.ui.Button(label=MODE_LABELS[mode], row=2)
            button.callback = self.mode_callback(mode)
            self.mode_buttons[mode] = button
            self.add_item(button)
        self.style_mode_buttons()

    def style_mode_buttons(self):
        for mode, button in self.mode_buttons.items():
            button.style = discord.ButtonStyle.primary if mode == self.stm.mode else discord.ButtonStyle.secondary

    def mode_callback(self, mode):
        async def callback(interaction: discord.Interaction):
            self.stm.mode = mode
            self.stm.page = 0
            self.style_mode_buttons()
            await self.reload()
            await self.show(interaction, embed=self.get_embed(), view=self)
        return callback

    async def reload(self, page_step=0):
        """reload the reminders, move by page_step pages, then build the page
           with the names of the members it shows
        """
        self.refresh_reminders()
        self.stm.page = (self.stm.page + page_step) % self.page_count()
        await resolve_names(self.stm, ReminderListing.get_reminders_on_page(self.stm.reminders, self.stm.page))
        self.update_dropdown(refresh=False)

    def name_of(self, user_id: int) -> str:
        """a member as plain text (the dropdown can't show mentions)"""
        if user_id == self.stm.scope.user_id:
            return 'you'
        return self.stm.names.get(user_id) or 'another member'

    def get_embed(self) -> discord.Embed:

        if self.stm.scope.is_private:
            title_str = 'Your private reminders'
        elif self.stm.mode == FOR_ME:
            title_str = f'Reminders for you · {self.stm.ctx.guild.name}'
        elif self.stm.mode == SERVER:
            title_str = f'All reminders · {self.stm.ctx.guild.name}'
        else:
            title_str = f'Your reminders · {self.stm.ctx.guild.name}'

        return ReminderListing.get_reminder_list_eb(self.stm.reminders, self.stm.page, title_str, self.stm.tz_str,
                                                    self.stm.scope.user_id, empty_text=EMPTY_TEXTS[self.stm.mode],
                                                    names=self.stm.names, all_authors=self.stm.mode == SERVER)


    def option_description(self, rem: Reminder) -> str:
        """date and channel under a dropdown entry, and its author in the views
           with other members' reminders (plain text: no Discord timestamps or
           mentions there)
        """
        parts = []
        if self.stm.mode in (FOR_ME, SERVER):
            parts.append(f'from {self.name_of(rem.author)}')
        if getattr(rem, 'paused', False):
            parts.append('⏸️ paused')
        if rem.at:
            local = rem.at.replace(tzinfo=tz.UTC).astimezone(tz.gettz(self.stm.tz_str))
            parts.append(local.strftime('%a %d %b %H:%M'))
        else:
            parts.append('no next date')
        parts.append(f'#{rem.ch_name}' if rem.ch_id and rem.ch_name and not rem.by_dm else 'DM')
        prefix = '🔁 ' if isinstance(rem, IntervalReminder) else ''
        return (prefix + ' · '.join(parts))[:100]


    def page_count(self) -> int:
        return max(math.ceil(len(self.stm.reminders) / 9), 1)


    def refresh_reminders(self):
        """reload the reminders and keep the page in range
           (the last page can disappear after a deletion)
        """
        self.stm.reminders = load_reminders(self.stm)
        self.stm.page = min(self.stm.page, self.page_count() - 1)


    def update_dropdown(self, refresh=True):
        if refresh:
            self.refresh_reminders()
        page_rems = ReminderListing.get_reminders_on_page(self.stm.reminders, self.stm.page)

        # delete old selects, also when the page is now empty
        for old_sel in [x for x in self.children if isinstance(x, discord.ui.Select)]:
            self.remove_item(old_sel)

        if(len(page_rems) > 25):
            # TODO: debug issue?
            log.warning('too many elements in dropdown in update_dropdown/ReminderListing.py')
            page_rems = page_rems[0:25] # max 25 elements

        if page_rems:
            reminder_opts = []
            for i, r in enumerate(page_rems):
                # labels need 1 to 100 characters
                lbl = (r.title or r.msg or '').replace('\n', ' ').strip()[:80] or '*empty reminder*'

                reminder_opts.append(discord.SelectOption(
                    label= lbl,
                    description= self.option_description(r),
                    emoji= lib.input_parser.num_to_emoji(i+1),
                    value= str(i)))


            dd = discord.ui.Select(
                placeholder='Select a reminder to edit',
                min_values=1,
                max_values=1,
                options=reminder_opts,
                row=1  # between the page buttons and the mode buttons
            )
            dd.callback = self.dropdown_callback
            self.add_item(dd)



    @discord.ui.button(emoji='⏪', style=discord.ButtonStyle.secondary)
    async def prev_page(self, button:  discord.ui.Button, interaction: discord.Interaction):
        await self.reload(page_step=-1)
        await self.show(interaction, embed=self.get_embed(), view=self)



    @discord.ui.button(emoji='⏩', style=discord.ButtonStyle.secondary)
    async def next_page(self, button:  discord.ui.Button, interaction: discord.Interaction):
        await self.reload(page_step=1)
        await self.show(interaction, embed=self.get_embed(), view=self)



    async def dropdown_callback(self, interaction: discord.Interaction):
        

        # do not update reminder list
        # otherwise the user selected reminder could be another one than the actual one
        page_rems = ReminderListing.get_reminders_on_page(self.stm.reminders, self.stm.page)
        values = interaction.data.get('values') or []

        if not values or int(values[0]) >= len(page_rems):
            # nothing selected, or the list is not long enough anymore
            # update ui to show the current list
            await self.reload()
            await self.show(interaction, embed=self.get_embed(), view=self)
            return
        sel = values[0]


        # go ahead with reminder edit
        sel_rem = page_rems[int(sel)]
        view = util.reminderInteraction.ReminderEditView(sel_rem, self.stm)
        if await self.open_child(interaction, view, embed=view.get_embed()):
            # the edit view disabled itself, the menu is over
            return

        # back to the list, reloaded (the reminder may be deleted or changed)
        await self.reload()
        await self.show(embed=self.get_embed(), view=self)




class ReminderListing(commands.Cog):
    def __init__(self, client):
        self.client = client


    # =====================
    # events functions
    # =====================

    @discord.Cog.listener()
    async def on_ready(self):
        log.info('loaded')

    # =====================
    # helper methods
    # =====================

    

    @staticmethod
    def _rule_summary(rem: IntervalReminder) -> str:
        """the repetition of an interval in a few words ('every Fri, 1 exception')"""
        if rem.rrules:
            try:
                # the next date is shown above: drop 'starting Fri Nov 13, 2026 7am'
                text = lib.input_parser.rrule_to_english(rem.rrules[0]).split(' starting ')[0]
            except Exception:
                text = 'custom repetition'
            others = len(rem.rrules) - 1 + len(rem.rdates)
            if others:
                text += f' (+{others} more)'
        else:
            text = f'{len(rem.rdates) + 1} dates'

        exceptions = len(rem.exrules) + len(rem.exdates)
        if exceptions:
            text += f', {exceptions} exception' + ('s' if exceptions > 1 else '')
        return text


    @staticmethod
    def _entry(number: int, rem: Reminder, author_id=None, names=None, all_authors=False) -> str:
        """one reminder of the list: its name, then its date, channel and repetition

        author_id: the user looking at the list ('from' whom, 'for' whom
        when it's someone else)
        names: the names of members by id (resolve_names), else mentions
        all_authors: also 'from you' on the user's own reminders

        The dates are Discord timestamps: each viewer sees them in their own
        language and timezone, and 'in 3 days' stays up to date
        """
        def who(user_id, fallback):
            name = (names or {}).get(user_id)
            return discord.utils.escape_markdown(name) if name else fallback

        is_interval = isinstance(rem, IntervalReminder)
        paused = getattr(rem, 'paused', False)

        name = (rem.title or rem.msg or '').replace('\n', ' ').strip() or '*empty reminder*'
        icons = ('🔁 ' if is_interval else '') + ('⏸️ ' if paused else '')
        head = f'{lib.input_parser.num_to_emoji(number)} {icons}**{discord.utils.escape_markdown(lib.text.shorten(name, 60))}**'

        details = []
        if rem.at:
            ts = int(utc_timestamp(rem.at))
            details += [f'<t:{ts}:f>', 'paused' if paused else f'<t:{ts}:R>']
        else:
            details.append('no next date')
        details.append(f'<#{rem.ch_id}>' if rem.ch_id and not rem.by_dm else 'by DM')
        if rem.target and rem.target not in (rem.author, author_id):
            details.append(f'for {who(rem.target, rem.target_name or f"<@{rem.target}>")}')
        if author_id and rem.author != author_id:
            details.append(f'from {who(rem.author, f"<@{rem.author}>")}')
        elif all_authors:
            details.append('from you')

        lines = [head, '\u2003' + ' · '.join(details)]
        if is_interval:
            lines.append('\u2003↳ ' + ReminderListing._rule_summary(rem))
        return '\n'.join(lines)


    @staticmethod
    def get_reminder_list_eb(reminders: list[Reminder], page, title_start='Reminders', tz_str='UTC', author_id=None,
                             empty_text=EMPTY_TEXTS[MINE], names=None, all_authors=False):
        """the list embed: the reminders of the selected page, numbered like the dropdown

        Args:
            reminders ([]]): all reminders, sorted by date
            page (int): selected page

        Returns:
            discord.Embed: the menu embed
        """
        page_cnt = max(math.ceil(len(reminders) / 9), 1)
        selectables = ReminderListing.get_reminders_on_page(reminders, page)

        if selectables:
            description = '\n\n'.join(ReminderListing._entry(i + 1, r, author_id, names, all_authors)
                                      for i, r in enumerate(selectables))
        else:
            description = empty_text

        embed = discord.Embed(title=title_start, description=lib.text.shorten(description, lib.text.MAX_DESCRIPTION),
                              color=0x409fe2)
        count = len(reminders)
        embed.set_footer(text=f'Page {page + 1}/{page_cnt} · {count} reminder' + ('s' if count != 1 else ''))
        return embed


    @staticmethod
    def get_reminders_on_page(reminders, page):
        """select the reminders which are
           present on the selected page

        Args:
            reminders ([]): list of reminders
            page (int): selected page

        Returns:
            []: list of reminders on page
        """
        
        from_idx = page*9
        # the reminders are selected with a:b syntax
        # which is not inclusive for b
        to_idx = (page*9) + 9
        to_idx = min(to_idx, len(reminders))

        return reminders[from_idx:to_idx]

 
    # =====================
    # stm core
    # =====================

    async def reminder_stm(self, stm: util.reminderInteraction.STM):
        # manually send initial message to init view (it loads the reminders)
        view = ReminderListView(stm)
        await view.reload()  # with the names of the members it shows
        eb = view.get_embed()
        view.origin = await stm.ctx.respond(embed=eb, view=view, ephemeral=True)


    # =====================
    # commands functions
    # =====================

    @commands.slash_command(name='reminder_list', description='List, edit and delete your reminders, and the ones for you',
                            **lib.permissions.EVERYWHERE)
    async def reminder_list(self, ctx):
        # answer Discord before reading the database
        await ctx.defer(ephemeral=True)

        if not lib.permissions.is_personal_context(ctx):
            scope = Connector.Scope(is_private=False, guild_id=ctx.guild.id, user_id=ctx.author.id)
        else:
            scope = Connector.Scope(is_private=True, user_id=ctx.author.id)

        stm = util.reminderInteraction.STM(ctx=ctx, scope=scope)
        stm.tz_str = Connector.get_timezone(scope.instance_id)
        await self.reminder_stm(stm)

def setup(client):
    client.add_cog(ReminderListing(client))