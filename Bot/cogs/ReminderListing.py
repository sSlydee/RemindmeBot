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
#import lib.ReminderRepeater


log = logging.getLogger('Remindme.Listing')



class ReminderListView(util.interaction.CustomView):
    def __init__(self, stm, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.stm:util.reminderInteraction.STM = stm
        self.owner_id = stm.ctx.author.id
        self.update_dropdown()

    def get_embed(self) -> discord.Embed:
    
        if self.stm.scope.is_private:
            title_str = 'Your private reminders'
        else:
            title_str = f'Your reminders · {self.stm.ctx.guild.name}'

        return ReminderListing.get_reminder_list_eb(self.stm.reminders, self.stm.page, title_str, self.stm.tz_str, self.stm.scope.user_id)

    
    def option_description(self, rem: Reminder) -> str:
        """date and channel under a dropdown entry (plain text: no Discord timestamps there)"""
        parts = []
        if getattr(rem, 'paused', False):
            parts.append('⏸️ paused')
        if rem.at:
            local = rem.at.replace(tzinfo=tz.UTC).astimezone(tz.gettz(self.stm.tz_str))
            parts.append(local.strftime('%a %d %b %H:%M'))
        else:
            parts.append('no next date')
        parts.append(f'#{rem.ch_name}' if rem.ch_id and rem.ch_name else 'DM')
        prefix = '🔁 ' if isinstance(rem, IntervalReminder) else ''
        return (prefix + ' · '.join(parts))[:100]


    def page_count(self) -> int:
        return max(math.ceil(len(self.stm.reminders) / 9), 1)


    def refresh_reminders(self):
        """reload the reminders and keep the page in range
           (the last page can disappear after a deletion)
        """
        self.stm.reminders = Connector.get_scoped_reminders(self.stm.scope)
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
                options=reminder_opts
            )
            dd.callback = self.dropdown_callback
            self.add_item(dd)



    @discord.ui.button(emoji='⏪', style=discord.ButtonStyle.secondary)
    async def prev_page(self, button:  discord.ui.Button, interaction: discord.Interaction):
        self.refresh_reminders()
        self.stm.page = (self.stm.page - 1) % self.page_count()

        self.update_dropdown(refresh=False)
        await self.show(interaction, embed=self.get_embed(), view=self)



    @discord.ui.button(emoji='⏩', style=discord.ButtonStyle.secondary)
    async def next_page(self, button:  discord.ui.Button, interaction: discord.Interaction):
        self.refresh_reminders()
        self.stm.page = (self.stm.page + 1) % self.page_count()

        self.update_dropdown(refresh=False)
        await self.show(interaction, embed=self.get_embed(), view=self)



    async def dropdown_callback(self, interaction: discord.Interaction):
        

        # do not update reminder list
        # otherwise the user selected reminder could be another one than the actual one
        page_rems = ReminderListing.get_reminders_on_page(self.stm.reminders, self.stm.page)
        values = interaction.data.get('values') or []

        if not values or int(values[0]) >= len(page_rems):
            # nothing selected, or the list is not long enough anymore
            # update ui to show the current list
            self.update_dropdown()
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
        self.update_dropdown()
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
    def _entry(number: int, rem: Reminder, author_id=None) -> str:
        """one reminder of the list: its name, then its date, channel and repetition

        The dates are Discord timestamps: each viewer sees them in their own
        language and timezone, and 'in 3 days' stays up to date
        """
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
        details.append(f'<#{rem.ch_id}>' if rem.ch_id else 'by DM')
        if rem.target and rem.target != rem.author:
            details.append(f'for {rem.target_name or f"<@{rem.target}>"}')
        if author_id and rem.author != author_id:
            details.append(f'from <@{rem.author}>')

        lines = [head, '\u2003' + ' · '.join(details)]
        if is_interval:
            lines.append('\u2003↳ ' + ReminderListing._rule_summary(rem))
        return '\n'.join(lines)


    @staticmethod
    def get_reminder_list_eb(reminders: list[Reminder], page, title_start='Reminders', tz_str='UTC', author_id=None):
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
            description = '\n\n'.join(ReminderListing._entry(i + 1, r, author_id) for i, r in enumerate(selectables))
        else:
            description = 'No pending reminders. Create one with `/remindme`.'

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
        # first fetch of reminders
        stm.reminders = Connector.get_scoped_reminders(stm.scope)

        # manually send initial message to init view
        view = ReminderListView(stm)
        eb = view.get_embed()    
        view.origin = await stm.ctx.respond(embed=eb, view=view, ephemeral=True)


    # =====================
    # commands functions
    # =====================

    @commands.slash_command(name='reminder_list', description='List all reminders created by you',
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