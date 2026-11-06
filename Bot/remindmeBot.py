import os
import discord
import logging
import logging.handlers
import time
import traceback
import sys
import uuid

from pathlib import Path
from discord.ext.help import Help, HelpElement, HelpPage

from lib.Connector import Connector
from util.consts import Consts


# Logging
# - LOG_FILE (default ./logs/bot.log): everything, rotated at 5 MB, 5 old files kept
# - stderr: warnings and errors only (journald / systemd keeps them)
# - LOG_LEVEL (default INFO) for the bot's own loggers, DEBUG for details
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
LOG_FILE = os.getenv('LOG_FILE', './logs/bot.log')

_formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s', datefmt='%Y-%m-%dT%H:%M:%SZ')
_formatter.converter = time.gmtime  # log times in UTC, whatever the machine timezone

_file_handler = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
_file_handler.setFormatter(_formatter)

_stderr_handler = logging.StreamHandler()
_stderr_handler.setLevel(logging.WARNING)
_stderr_handler.setFormatter(_formatter)

logging.basicConfig(level=logging.INFO, handlers=[_file_handler, _stderr_handler]) # general 3rd party
logging.getLogger('discord').setLevel(logging.WARNING) # reduce warning for discord lib

log = logging.getLogger('Remindme')
log.setLevel(LOG_LEVEL) # own code, all 'Remindme.*' loggers inherit it


token: str = os.getenv('BOT_TOKEN')
intents = discord.Intents.none()
intents.guilds = True # required for member roles -> permissions
#intents.reactions = True
#intents.messages = True

# a personal bot runs on a few servers: no sharding needed
bot: discord.Bot = discord.Bot(intents=intents)

SYNTAX_HELP_PAGE = \
                'basic example:\n'\
                '> /remindme `time: 2d` `message: Hello World`\n'\
                '> /remind `target: @User` `time: 2d` `message: Hello World`\n'\
                '> /remind `target: @Role` `time: 2d` `message: Hello World`\n'\
                '\n'\
                'create repeating reminders\n'\
                '> /remindme `time: every friday at 14:15` `message: important appointment`\n'\
                '> /remindme `time: every other year on 2nd july` `message: interesting`\n'\
                '\n'\
                'combine relative intervals\n'\
                '```1y 1mo 2 days -5h```'\
                '\n'\
                'try different formats\n'\
                '```'\
                '• 5 jul, 5th july or july 5\n'\
                '• 3pm or 15:00\n'\
                '• every second monday each other month\n'\
                '• 2021-09-02T12:25:00+02:00\n'\
                '\n'\
                'Note: the parser uses day-first and year-least\n'\
                '      (01/02/03 -> 1st February 2003)\n'\
                '```'\
                '\n'\
                'use abbreviations for common terms\n'\
                '```'\
                '• eoy, eom, eow, eod - end of year/month/week/day\n'\
                '\n'\
                '• y(ears), mo(nths), w(eeks)\n'\
                '• d(ays), h(ours), m(ins)\n'\
                '\n'\
                'Note: eow is end of the working week (Friday Evening)\n'\
                '```'

TIMEZONE_HELP_PAGE = \
                    'Set a new timezone with `/timezone <string>`\n'\
                    '\n'\
                    'The bot will try to suggest valid timezone options, while you are typing\n'\
                    '\n'\
                    '• Allowed are all timezones [defined by the IANA](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)\n'\
                    '• Some timezones are marked as \'deprecated\' but can be used with a warning\n'\
                    '• geo-referencing timezones (e.g. `Europe/Berlin`) should be preferred\n'\
                    '  over more general (and deprecated) timezones (e.g. `CET`)'

# ###########
# Methods
# ###########
async def log_exception(ctx: discord.ApplicationContext, error: Exception, error_id: str):
    """log the given exception to the local logger

    Args:
        ctx (discord.ApplicationContext): _description_
        error (Exception): _description_
        error_id (str): _description_
    """
    if isinstance(error, discord.NotFound):
        log.warning('interaction timed out (not found)')
    else:
        t = (type(error), error, error.__traceback__)
        ex_str = ''.join(traceback.format_exception(*t))
        log.error(f'ErrorCode: {error_id}\n{ex_str}')


# ###########
# Events
# ###########

@bot.event
async def on_ready():
    log.info('Logged in as')
    log.info(bot.user)
    log.info(bot.user.id)
    log.info('----------------')

    config_help()

    await bot.change_presence(activity=discord.Game(name='/remindme'))



@bot.event
async def on_application_command_error(ctx: discord.ApplicationContext, error: Exception):
    err_id = str(uuid.uuid4())

    await log_exception(ctx, error, error_id=err_id)

    def get_err_embed(error_id):
        eb = discord.Embed(title='An unknown error has ocurred', 
                            description='The bot crashed while execution your command and we don\'t know why\n\n'\
                                        'If you want to help improving this bot, '\
                                        f'please report this crash with the error code on [GitHub]({Consts.github_url}/issues)')
        eb.color = 0xff0000  # red

        eb.add_field(name='Error Code', value=str(error_id))
        return eb

    # not all commands are equally report-worthy
    # decide what to show based on the exception type
    # if isinstance(error, discord.ext.commands.errors.MissingPermissions):
    #     await ctx.send('You do not have permission to execute this command')
    # elif isinstance(error, discord.ext.commands.errors.NoPrivateMessage):
    #     await ctx.send('This command is only to be used on servers')
    # elif isinstance(error, discord.NotFound):
    #     print(''.join(error.args))

    
    try:
        await ctx.respond(embed=get_err_embed(err_id), ephemeral=True)
    except:
        # prevent recursion with wildcard catch
        pass


@bot.event
async def on_error(event_method, *args, **kwargs):
    exc_info = sys.exc_info()
    log.critical('non-application error occurred', exc_info=exc_info)



@bot.event
async def on_guild_remove(guild):
    # leaving a server deletes its reminders and settings
    del_rem, del_intvl = Connector.delete_guild(guild.id)
    log.info(f'removed from guild {guild.id}: deleted {del_rem} reminder(s) and {del_intvl} interval(s)')




@bot.event
async def on_guild_join(guild):
    log.info(f'added to guild {guild.id} (total count: {len(bot.guilds)})')

# #############
# # Commands
# ############

def config_help():

    custom_footer = f'If you find a bug, please report it on [GitHub]({Consts.github_url}/issues).'

    Help.init_help(bot, auto_detect_commands=True)

    Help.set_default_footer(custom_footer)
    # no direct feedback, support server, ToS or privacy notice:
    # those of the original author's public bot don't apply to this instance
    Help.invite_permissions(
        # the permissions the bot actually needs (same as the README invite link)
        discord.Permissions(view_channel=True, send_messages=True, send_messages_in_threads=True,
                            embed_links=True, read_message_history=True)
    )
    Help.set_github_url(Consts.github_url)


    page = HelpPage(
        name='syntax',
        title='Syntax Help',
        emoji='✏️', # pencil2
        description=SYNTAX_HELP_PAGE
    )
    Help.add_page(page)


    page = HelpPage(
        name='timezone',
        title='Timezone Help',
        emoji='⏱️', # stopwatch
        description=TIMEZONE_HELP_PAGE
    )
    Help.add_page(page)




def main():
    Connector.init()

    for filename in os.listdir(Path(__file__).parent / 'cogs'):
        if filename.endswith('.py'):
            bot.load_extension(f'cogs.{filename[:-3]}')

    bot.load_extension('discord.ext.help.help')

    bot.run(token)




if __name__ == '__main__':
    main()

