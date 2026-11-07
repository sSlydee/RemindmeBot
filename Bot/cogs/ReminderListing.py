import logging
import math
from unidecode import unidecode
from dateutil import tz

import discord
from discord.ext import commands

from lib.Connector import Connector
import lib.permissions
from lib.Reminder import Reminder
import lib.input_parser

import util.interaction
import util.reminderInteraction
import util.formatting
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
            title_str = f'**Private** Reminder list'
        else:
            title_str = f'Reminder list for {self.stm.ctx.guild.name}'

        return ReminderListing.get_reminder_list_eb(self.stm.reminders, self.stm.page, title_str, self.stm.tz_str, self.stm.scope.user_id)

    
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
                # make sure to always have between 1 and 25 chars in any label
                # *AFTER* unidecode
                lbl = unidecode(r.title)[:25] if r.title and unidecode(r.title) else unidecode(r.msg)[:25]
                lbl = lbl if lbl else '*empty reminder*'

                reminder_opts.append(discord.SelectOption(
                    label= lbl, 
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
    def _create_reminder_list(reminders, tz_str, author_id=None):
        """convert the inputed reminder list
           into a menu-string, with leading emojis

        Args:
            reminders ([]]): list of reminders

        Returns:
            str: reminder list string
        """

        rows = []
        for i, r in enumerate(reminders):

            MAX_FIELD_LEN = 33
            MAX_MSG_LEN = 26

            at_local = r.at.replace(tzinfo=tz.UTC).astimezone(tz.gettz(tz_str)) if r.at else None


            content = r.title[0:MAX_MSG_LEN] if r.title else r.msg[0:MAX_MSG_LEN]

            sfx = ''
            if author_id and r.author != author_id:
                sfx = '*'


            # a total of 33 chars are possible before overflow
            #
            # the message will get up to 26 chars
            # the channel len will get the rest, but at least 7
            max_ch_len = MAX_FIELD_LEN-min(len(content), MAX_MSG_LEN)
            
            rows.append((str(i+1)+'.'+sfx,
                        ('paused' if getattr(r, 'paused', False) else at_local.strftime('%d.%b %H:%M')) if at_local else '-',
                        (r.ch_name or 'Unknown')[0:max_ch_len],
                        content))

        table = util.formatting.generate_code_table(['No.', 'Next', 'Channel', 'Message'], rows, description='Given in your server timezone')

        return '\n'.join(table)


    @staticmethod
    def get_reminder_list_eb(reminders: list[Reminder], page, title_start='Reminder list', tz_str='UTC', author_id=None):
        """get the menu embed for all reminders
           in respect to the selected page

           if title_start is specified, will onld add page counter
           at end of title_start

        Args:
            reminders ([]]): reminder list
            page (int): selected page

        Returns:
            discord.Embed: the menu embed
        """

        page_cnt = math.ceil(len(reminders) / 9)
        selectables = ReminderListing.get_reminders_on_page(reminders, page)

        out_str = ReminderListing._create_reminder_list(selectables, tz_str, author_id=author_id)

        embed = discord.Embed(title=f'{title_start} {page+1}/{max(page_cnt, 1)}',
                                description=out_str)
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