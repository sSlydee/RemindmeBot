import logging
from typing import Union


import discord
from discord.ext import commands

from util.consts import Consts
import lib.permissions
import util.interaction
import util.timezones
from lib.Connector import Connector


log = logging.getLogger('Remindme.Settings')

class SettingsView(util.interaction.CustomView):
    def __init__(self, scope: Connector.Scope, author: Union[discord.User, discord.Member], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scope: Connector.Scope = scope
        self.update_ui_elements()

        # server settings need 'Manage Server' (administrators have it)
        self.forbidden = not lib.permissions.can_change_settings(author)

        if scope.is_private or self.forbidden:
            self.disable_all()


    def update_ui_elements(self):
        self.server_tz_val.label = Connector.get_timezone(self.scope.instance_id)
        rem_type = Connector.get_reminder_type(self.scope.instance_id)
        del_type = Connector.get_auto_delete(self.scope.instance_id)

        

        if rem_type==Connector.ReminderType.HYBRID:
            self.style_hybrid.style=discord.ButtonStyle.success
            self.style_hybrid.disabled=True
            self.style_embed.style=discord.ButtonStyle.secondary
            self.style_embed.disabled=False
            self.style_text.style=discord.ButtonStyle.secondary
            self.style_text.disabled=False
            self.style_bare.style=discord.ButtonStyle.secondary
            self.style_bare.disabled=False
        elif rem_type==Connector.ReminderType.EMBED_ONLY:
            self.style_hybrid.style=discord.ButtonStyle.secondary
            self.style_hybrid.disabled=False
            self.style_embed.style=discord.ButtonStyle.success
            self.style_embed.disabled=True
            self.style_text.style=discord.ButtonStyle.secondary
            self.style_text.disabled=False
            self.style_bare.style=discord.ButtonStyle.secondary
            self.style_bare.disabled=False
        elif rem_type==Connector.ReminderType.BAREBONE:
            self.style_hybrid.style=discord.ButtonStyle.secondary
            self.style_hybrid.disabled=False
            self.style_embed.style=discord.ButtonStyle.secondary
            self.style_embed.disabled=False
            self.style_text.style=discord.ButtonStyle.secondary
            self.style_text.disabled=False
            self.style_bare.style=discord.ButtonStyle.success
            self.style_bare.disabled=True
        else:
            self.style_hybrid.style=discord.ButtonStyle.secondary
            self.style_hybrid.disabled=False
            self.style_embed.style=discord.ButtonStyle.secondary
            self.style_embed.disabled=False
            self.style_text.style=discord.ButtonStyle.success
            self.style_text.disabled=True
            self.style_bare.style=discord.ButtonStyle.secondary
            self.style_bare.disabled=False

        if del_type==Connector.AutoDelete.NEVER:
            self.del_never.style=discord.ButtonStyle.success
            self.del_never.disabled=True
            self.del_timeout.style=discord.ButtonStyle.secondary
            self.del_timeout.disabled=False
            self.del_hidden.style=discord.ButtonStyle.secondary
            self.del_hidden.disabled=False
        elif del_type==Connector.AutoDelete.TIMEOUT:
            self.del_never.style=discord.ButtonStyle.secondary
            self.del_never.disabled=False
            self.del_timeout.style=discord.ButtonStyle.success
            self.del_timeout.disabled=True
            self.del_hidden.style=discord.ButtonStyle.secondary
            self.del_hidden.disabled=False
        else:
            self.del_never.style=discord.ButtonStyle.secondary
            self.del_never.disabled=False
            self.del_timeout.style=discord.ButtonStyle.secondary
            self.del_timeout.disabled=False
            self.del_hidden.style=discord.ButtonStyle.success
            self.del_hidden.disabled=True


    def get_embed(self) -> discord.Embed:
        eb = discord.Embed(title='Remindme Settings',
                description='Server Managers can edit these settings by pressing the '\
                            'corresponding buttons below.\n'\
                            'The grayed-out buttons are the current selected options.')

        if self.forbidden:
            eb.color = Consts.col_err
            eb.description = 'You need the `Manage Server` permission to change the settings of this server.'

        return eb
    

    async def send_update_ui(self, interaction: discord.Interaction):
        self.update_ui_elements()
        await self.show(interaction, view=self)

    
    
    @discord.ui.button(label='Server Timezone', style=discord.ButtonStyle.primary, row=0)
    async def server_tz(self, button: discord.ui.Button, interaction: discord.Interaction):
        # same as the value button: show the current timezone
        await self.server_tz_val.callback(interaction)

    @discord.ui.button(label='UTC', style=discord.ButtonStyle.secondary, row=0)
    async def server_tz_val(self, button: discord.ui.Button, interaction: discord.Interaction):
        # show timezone embed
        eb = util.timezones.timezone_embed(Connector.get_timezone(self.scope.instance_id),
                                           title='Current Timezone', intro='The timezone is set to',
                                           outro='\nUse `/timezone` to edit this value')
        await interaction.response.send_message(embed=eb, ephemeral=True)


    @discord.ui.button(label='Preferred Reminder Style', style=discord.ButtonStyle.primary, row=1)
    async def reminder_style(self, button: discord.ui.Button, interaction: discord.Interaction):
        # label only: acknowledge, or Discord reports that the bot did not respond
        await interaction.response.defer()
    @discord.ui.button(label='Hybrid Reminders', style=discord.ButtonStyle.secondary, row=1)
    async def style_hybrid(self, button: discord.ui.Button, interaction: discord.Interaction):
        Connector.set_reminder_type(self.scope.instance_id, Connector.ReminderType.HYBRID)
        await self.send_update_ui(interaction)

    @discord.ui.button(label='Embed-Only Reminders', style=discord.ButtonStyle.secondary, row=1)
    async def style_embed(self, button: discord.ui.Button, interaction: discord.Interaction):
        Connector.set_reminder_type(self.scope.instance_id, Connector.ReminderType.EMBED_ONLY)
        await self.send_update_ui(interaction)

    @discord.ui.button(label='Text-Only Reminders', style=discord.ButtonStyle.secondary, row=1)
    async def style_text(self, button: discord.ui.Button, interaction: discord.Interaction):
        Connector.set_reminder_type(self.scope.instance_id, Connector.ReminderType.TEXT_ONLY)
        await self.send_update_ui(interaction)

    @discord.ui.button(label='Barebone Reminder', style=discord.ButtonStyle.secondary, row=1)
    async def style_bare(self, button: discord.ui.Button, interaction: discord.Interaction):
        Connector.set_reminder_type(self.scope.instance_id, Connector.ReminderType.BAREBONE)
        await self.send_update_ui(interaction)


    @discord.ui.button(label='Delete Creation Style', style=discord.ButtonStyle.primary, row=2)
    async def delete_style(self, button: discord.ui.Button, interaction: discord.Interaction):
        # label only: acknowledge, or Discord reports that the bot did not respond
        await interaction.response.defer()

    @discord.ui.button(label='Delete after Timeout', style=discord.ButtonStyle.secondary, row=2)
    async def del_timeout(self, button: discord.ui.Button, interaction: discord.Interaction):
        Connector.set_auto_delete(self.scope.instance_id, Connector.AutoDelete.TIMEOUT)
        await self.send_update_ui(interaction)

    @discord.ui.button(label='Never Delete', style=discord.ButtonStyle.secondary, row=2)
    async def del_never(self, button: discord.ui.Button, interaction: discord.Interaction):
        Connector.set_auto_delete(self.scope.instance_id, Connector.AutoDelete.NEVER)
        await self.send_update_ui(interaction)

    @discord.ui.button(label='Only Show to author', style=discord.ButtonStyle.secondary, row=2)
    async def del_hidden(self, button: discord.ui.Button, interaction: discord.Interaction):
        Connector.set_auto_delete(self.scope.instance_id, Connector.AutoDelete.HIDE)
        await self.send_update_ui(interaction)



class SettingsModule(commands.Cog):
    
    ##################
    # Statics
    #################

    def __init__(self, client):
        self.client = client

        
    ################
    # Helper methods
    ################
    



    ################
    # Event methods
    ################

    @commands.Cog.listener()
    async def on_ready(self):
        log.info('loaded')

    
    ##################
    # Commands methods
    ##################


    @commands.slash_command(name='settings', description='Get an overview over all settings') 
    async def settings_menu_cmd(self, ctx):
        # answer Discord before reading the database
        await ctx.defer(ephemeral=True)

        scope = Connector.Scope(
            is_private=(not ctx.guild),
            guild_id=ctx.guild.id if ctx.guild else None,
            user_id = ctx.author.id
        )


        view = SettingsView(scope=scope, author=ctx.author)
        view.origin = await ctx.respond(embed=view.get_embed(), view=view, ephemeral=True)




def setup(client):
    client.add_cog(SettingsModule(client))