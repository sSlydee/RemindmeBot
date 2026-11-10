"""The privacy note, shown by the Privacy button of /help"""
from util.consts import Consts
from util.reminderButtons import DELIVERED_KEEP

# backup-mongo.sh next to the bot (KEEP_DAYS): outside of this code
BACKUP_KEEP_DAYS = 14

# one message: at most 2000 characters
PRIVACY_TEXT = (
    '**Privacy**\n'
    'This bot runs on a server of its owner. It keeps what it needs to send your reminders, '
    'and shares it with no one but Discord.\n\n'
    '**What is stored**\n'
    '• your reminders: text, title, image link, dates and repetitions\n'
    '• who wrote them and who they are for, their server and channel, and the last message of '
    'that channel (for the *jump to the chat* link)\n'
    '• the settings of the server (timezone, style...), and your timezone and style if you set them in DMs\n\n'
    '**Who can see a reminder**\n'
    '• its author, and the member it is for or mentions (*For me* in `/reminder_list`)\n'
    '• the moderators of the server (**Manage Messages**), in *Whole server*\n'
    '• the owner of the bot, who runs its database\n\n'
    '**How long**\n'
    f'• until it is sent or deleted (`/reminder_list`), then {DELIVERED_KEEP.days} days more for the buttons under it\n'
    f'• the daily backups are kept {BACKUP_KEEP_DAYS} days\n'
    '• the log of the bot keeps user and reminder IDs (and error details) until it is rotated out\n'
    f'• when the bot is removed from a server, the data of that server is deleted after '
    f'{Consts.left_guild_keep.days} days\n\n'
    'To have your data deleted sooner, delete your reminders or ask the owner of the bot.'
)
