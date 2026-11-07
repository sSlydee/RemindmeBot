import re
import logging

import difflib
from dateutil import tz
import zoneinfo
from pytz import common_timezones as pytz_common_timezones

import discord
from discord.ext import commands

import lib.permissions
import util.interaction
import util.timezones
from lib.Connector import Connector


log = logging.getLogger('Remindme.Timezones')


class TimezoneModule(discord.Cog):

    ##################
    # Statics
    #################

    # IANA names from the system tz database (or the tzdata package)
    timezones = sorted(z for z in zoneinfo.available_timezones() if z != 'localtime')

    
    def __init__(self, client):
        self.client = client
    

    ################
    # autocomplete
    ################
     
    async def get_timezone_autocomplete(ctx: discord.AutocompleteContext):
        """Returns a list of colors that begin with the characters entered so far."""
        user_input = ctx.value.upper()
        return list(filter(lambda z: user_input in z.upper(), TimezoneModule.timezones)) # upper every iteration, to return case-sinsitive result to user


        
    ################
    # Helper methods
    ################
    


    def _get_tz_error_eb(self, zone, no_list=False):
        
        select_str = '' if no_list else 'or select one from the list below'

        eb = discord.Embed(title='Invalid Timezone configuration',
                        color=0xde4b55,  # red-ish
                        description=f'The timezone `{zone}` is not valid\n'\
                                    f'Please re-invoke the command with a valid timezone '\
                                    f'{select_str}\n\n'\
                                    f'You can have a look at all available timezones on this '\
                                     '[wikipedia list](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)')

        return eb
    
    
    ################
    # idk whats that
    ################


    async def set_timezone(self, ctx: discord.ApplicationContext, instance_id: int, value: str, ephemeral: bool = False):
        
        responded=False

        # tz lib will break on lower case utc
        re_utc = r'utc\+\d{1,2}'
        if re.match(re_utc, value):
            value = value.upper()

        tz_obj = tz.gettz(value)
        if not tz_obj:
            all_zones = TimezoneModule.timezones

            closest_tz = difflib.get_close_matches(value, all_zones, n=5)
            if not closest_tz:
                closest_tz = difflib.get_close_matches(value.upper(), all_zones, n=5)

            if value.upper() == 'PST':
                closest_tz = ['PST8PDT']  # manual override
            elif value.upper() == 'CST':
                closest_tz = ['CST6CDT']  # manual override
            elif value.upper() == 'MDT':
                closest_tz = ['MST7MDT']
            elif value.upper() == 'EDT':
                closest_tz = ['EST5EDT']
            
            if not closest_tz:
                # nothing to suggest, Discord refuses an empty dropdown
                await ctx.respond(embed=self._get_tz_error_eb(value, no_list=True), ephemeral=True)
                return

            # create a dropdown list
            options = [discord.SelectOption(
                    label=opt,
                    emoji='🔹' if opt in pytz_common_timezones else '🔸',
                    value=opt) for opt in closest_tz
                ]
            # hand the dropdown to managing class
            dd = discord.ui.Select(
                    placeholder='Select a timezone',
                    min_values=1,
                    max_values=1,
                    options=options
                )

            tz_eb = self._get_tz_error_eb(value)
            view = util.interaction.MulitDropdownView([dd])

            view.origin = await ctx.respond(embed=tz_eb, view=view, ephemeral=ephemeral)
            responded = True
            await view.wait()

            value = view.value
            tz_obj = tz.gettz(value)


            if not value:
                # timeout
                return
            elif not tz_obj:
                # bug
                raise ValueError(f'User selected invalid timezone from dropdown {value}')


        tz_eb = util.timezones.timezone_embed(value, title='New Timezone', intro='The timezone will be set to')
        view = util.interaction.ConfirmDenyView(dangerous_action=False)

        if not responded:
            view.origin = await ctx.respond(embed=tz_eb, view=view, ephemeral=ephemeral)
        else:
            await ctx.edit(embed=tz_eb, view=view)

        await view.wait()
        if view.value:
            Connector.set_timezone(instance_id, value)

        

    ################
    # Event methods
    ################

    @discord.Cog.listener()
    async def on_ready(self):
        log.info('loaded')


    ##################
    # Commands methods
    ##################
    
    @commands.slash_command(name='timezone', description='Set the timezone of this server (your own one in DMs)',
                            **lib.permissions.EVERYWHERE)
    async def set_timezone_sub_cmd(self, 
                                    ctx: discord.ApplicationContext, 
                                    new_timezone: discord.Option(
                                        str,
                                        "name of new timezone name",
                                        autocomplete=get_timezone_autocomplete
                                    )):

        # if no guild is present
        # assume dm context
        # DMs, or a server where only the user installed the app: the user's own timezone
        if lib.permissions.is_personal_context(ctx):
            await self.set_timezone(ctx, ctx.author.id, new_timezone, ephemeral=True)
            return

        if not lib.permissions.can_change_settings(ctx.author):
            await ctx.respond(embed=lib.permissions.missing_settings_permission_embed(), ephemeral=True)
            return

        await self.set_timezone(ctx, ctx.guild.id, new_timezone)


def setup(client):
    client.add_cog(TimezoneModule(client))