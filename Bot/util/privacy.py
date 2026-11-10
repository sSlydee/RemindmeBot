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

PRIVACY_TEXT_FR = (
    '**Confidentialité**\n'
    'Ce bot tourne sur un serveur de son propriétaire. Il garde ce qu’il lui faut pour envoyer tes rappels, '
    'et ne le partage qu’avec Discord.\n\n'
    '**Ce qui est stocké**\n'
    '• tes rappels : texte, titre, lien d’image, dates et répétitions\n'
    '• qui les a écrits et pour qui, leur serveur et leur salon, et le dernier message de ce salon '
    '(pour le lien *aller à la discussion*)\n'
    '• les réglages du serveur (fuseau horaire, style...), et ton fuseau et ton style si tu les règles en MP\n\n'
    '**Qui peut voir un rappel**\n'
    '• son auteur, et le membre à qui il est destiné ou qu’il mentionne (*Pour moi* dans `/reminder_list`)\n'
    '• les modérateurs du serveur (**Gérer les messages**), dans *Tout le serveur*\n'
    '• le propriétaire du bot, qui gère sa base de données\n\n'
    '**Combien de temps**\n'
    f'• jusqu’à son envoi ou sa suppression (`/reminder_list`), puis {DELIVERED_KEEP.days} jours pour ses boutons\n'
    f'• les sauvegardes quotidiennes sont gardées {BACKUP_KEEP_DAYS} jours\n'
    '• le journal du bot garde les identifiants des membres et des rappels (et le détail des erreurs) '
    'jusqu’à sa rotation\n'
    f'• quand le bot est retiré d’un serveur, les données de ce serveur sont supprimées après '
    f'{Consts.left_guild_keep.days} jours\n\n'
    'Pour faire supprimer tes données plus tôt, supprime tes rappels ou demande au propriétaire du bot.'
)
