"""French for the members whose Discord is in French; English for everyone else

The English text is the key: tr('fr', 'Saved.') gives 'Enregistré.', and any
text missing from FR stays in English. Placeholders use str.format names:
tr(lang, 'Snoozed until {when}.', when=...).

Interactions say the language of the user's Discord (interaction.locale).
A reminder keeps the language of its author (Reminder.lang) for what the bot
sends later, without an interaction: the delivered reminder and its buttons.
"""
import re
from datetime import datetime

EN = 'en'
FR = 'fr'

_FR_DAYS = ['lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.', 'dim.']
_FR_MONTHS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.']


def lang_of(obj) -> str:
    """'fr' or 'en': the language of the user's Discord, from an interaction or a command context"""
    interaction = getattr(obj, 'interaction', None) or obj
    locale = getattr(interaction, 'locale', None)
    return FR if isinstance(locale, str) and locale.lower().startswith('fr') else EN


def tr(lang: str, text: str, **kwargs) -> str:
    """text in that language (English when there is no translation)"""
    if lang == FR:
        text = FR_TEXTS.get(text, text)
    return text.format(**kwargs) if kwargs else text


def date_str(dt: datetime, lang: str, with_year=False) -> str:
    """'Wed 11 Nov 08:00' / 'mer. 11 nov. 08:00' (local time, naive or aware)"""
    if lang != FR:
        return dt.strftime('%a %d %b %Y %H:%M' if with_year else '%a %d %b %H:%M')
    year = f' {dt.year}' if with_year else ''
    return f'{_FR_DAYS[dt.weekday()]} {dt.day:02d} {_FR_MONTHS[dt.month - 1]}{year} {dt:%H:%M}'


# messages of the time parser (lib.input_parser), shown as 'parsing hints'
_HINTS_FR = [
    ('the given date must be in the future', 'la date doit être dans le futur'),
    ('the given date is too far in the future', 'la date est trop loin dans le futur'),
    ('this repetition has no date in the future', 'cette répétition n’a aucune date à venir'),
    ('String does not contain a date:', 'Aucune date dans :'),
    ('now:        ', 'maintenant : '),
    ('understood: ', 'compris :    '),
]


def hints(lang: str, info: str) -> str:
    """the parser's hints in that language (the ones it doesn't know stay in English)"""
    if lang != FR or not info:
        return info
    for en, fr in _HINTS_FR:
        info = info.replace(en, fr)
    return info


def _plural_fr(text: str) -> str:
    return re.sub(r'\b1 (jour|semaine|heure|an)s\b', r'1 \1', text)


FR_TEXTS = {
    # ---------- the time preview while typing (/remindme, /remind) ----------
    'in {n} min': 'dans {n} min',
    'in {h} h {m}': 'dans {h} h {m}',
    'in {h} h': 'dans {h} h',
    'in {d} days': 'dans {d} jours',
    'repeats, first {date} ({when})': 'se répète, d’abord {date} ({when})',
    'invalid repetition': 'répétition invalide',
    '⚠ this repetition has no date in the future': '⚠ cette répétition n’a aucune date à venir',
    '⚠ can\'t read this date': '⚠ date illisible',
    '⚠ this date is in the past': '⚠ cette date est passée',

    # ---------- creation ----------
    'Failed to create the reminder': 'Impossible de créer le rappel',
    'You already have {n} pending reminders. Delete some with `/reminder_list` first.':
        'Tu as déjà {n} rappels en attente. Supprimes-en avec `/reminder_list` d’abord.',
    'Make sure your server is using the correct timezone `/timezone`':
        'Vérifie que le serveur a le bon fuseau horaire (`/timezone`)',
    'The time formats are on the syntax page of /help.': 'Les formats d’heure sont sur la page syntax de /help.',
    '\n• Failed to resolve the target channel. The reminder *might* not be delivered due to missing permissions.':
        '\n• Salon introuvable : le rappel *pourrait* ne pas être envoyé, faute de permissions.',
    '\n• This reminder will be delivered to `{channel}`.\nMake sure this bot has permission to send messages into that channel':
        '\n• Ce rappel sera envoyé dans `{channel}`.\nVérifie que le bot peut écrire dans ce salon',
    'New Reminder Created': 'Rappel créé',
    'New Interval Created': 'Rappel répété créé',
    'Reminding you {when}': 'Je te le rappelle {when}',
    'Reminding {target} {when}': 'Je le rappelle à {target} {when}',
    'Reminding you the first time {when}': 'Je te le rappelle une première fois {when}',
    'Reminding {target} the first time {when}': 'Je le rappelle à {target} une première fois {when}',
    '\n\nCall `/reminder_list` to edit all pending reminders': '\n\n`/reminder_list` pour modifier tes rappels',
    'Parsing hints': 'Indications',
    'Set Interval': 'Répéter',
    'Edit Interval': 'Répétition',
    'Edit': 'Modifier',
    'Cannot edit reminders of other users': 'Tu ne peux pas modifier le rappel de quelqu’un d’autre',
    'Cannot delete reminders of other users': 'Tu ne peux pas supprimer le rappel de quelqu’un d’autre',
    'Deleted the reminder': 'Rappel supprimé',
    'Failed to delete reminder due to an unknown issue': 'Impossible de supprimer le rappel (erreur inconnue)',
    'Saved.': 'Enregistré.',
    'This reminder was delivered or deleted while you edited it.':
        'Ce rappel a été envoyé ou supprimé pendant ta modification.',

    'Edit the Reminder': 'Modifier le rappel',

    # ---------- the delivered reminder ----------
    'Reminder': 'Rappel',
    'Reminds you': 'Rappel pour toi',
    'by': 'de',
    '{text} (by {name})': '{text} (de {name})',
    'created: ': 'créé : ',
    '*Images are provided by the author*, created: ': '*Images fournies par l’auteur*, créé : ',
    '*Images are provided by the author*': '*Images fournies par l’auteur*',
    'jump to the chat': 'aller à la discussion',
    '⏰ Sent late': '⏰ Envoyé en retard',
    'Due <t:{ts}:f> (<t:{ts}:R>): the bot couldn\'t send it on time.':
        'Prévu <t:{ts}:f> (<t:{ts}:R>) : le bot n’a pas pu l’envoyer à l’heure.',
    'Next in ': 'Prochain dans ',
    'No future occurrence': 'Plus aucune date',
    '{y} years and {w} weeks': '{y} ans et {w} semaines',
    '{w} weeks and {d} days': '{w} semaines et {d} jours',
    '{d} days and {h} hours': '{d} jours et {h} heures',
    '{d} days ({h} hours)': '{d} jours ({h} heures)',
    '{h} h {m} m': '{h} h {m} min',
    '{m} minutes': '{m} minutes',
    'Next occurrences': 'Prochaines dates',
    'Next occurrences (paused, not delivered)': 'Prochaines dates (en pause, pas envoyées)',
    '\n**WARNING: the reminder couldn\'t get queued for future invocations** '
    '(likely due to an invalid repetition rule). **This reminder will not be delivered anymore**':
        '\n**ATTENTION : impossible de calculer la prochaine date de ce rappel** '
        '(sans doute une règle de répétition invalide). **Il ne sera plus envoyé**',
    '\n||This reminder can be more beautiful with `Embed Links` permissions||':
        '\n||Ce rappel serait plus joli avec la permission `Intégrer des liens`||',
    '`You are receiving this DM, as the channel \'{channel}\' on \'{guild}\' of this reminder can\'t be used (anymore).`':
        '`Tu reçois ce MP car le salon \'{channel}\' de \'{guild}\' de ce rappel n’est plus utilisable.`',
    '`You are receiving this DM, as I can\'t post in \'{channel}\' on \'{guild}\'.`':
        '`Tu reçois ce MP car je ne peux pas écrire dans \'{channel}\' sur \'{guild}\'.`',
    'Failed to deliver Reminder': 'Rappel non envoyé',
    'Couldn\'t send the reminder into the requested channel\n\n'
    '• Make sure I have permission to send messages into the channel `{channel}` on `{guild}`\n'
    '• or make sure the receiver allows to receive DMs from me\n'
    '• or edit the Reminder to be send into an existing channel':
        'Impossible d’envoyer le rappel dans son salon\n\n'
        '• Vérifie que je peux écrire dans `{channel}` sur `{guild}`\n'
        '• ou que son destinataire accepte mes MP\n'
        '• ou choisis un autre salon pour ce rappel',
    'Unresolved Guild': 'Serveur introuvable',
    'Unresolved Channel': 'Salon introuvable',

    'Reminder Info': 'Rappel',
    'Interval Info': 'Rappel répété',
    'Target user/role': 'Pour',
    'Due date': 'Date',
    'No future occurrences': 'Plus aucune date',
    'Paused, next in ': 'En pause, prochain dans ',
    'Paused, ': 'En pause, ',

    # ---------- the buttons under a delivered reminder ----------
    '+10 min': '+10 min',
    '+1 hour': '+1 heure',
    'Tomorrow 9:00': 'Demain 9:00',
    'Other…': 'Autre…',
    'Skip next': 'Passer le prochain',
    'Snoozed until {when}.': 'Reporté au {when}.',
    ' It will remind only you, not the whole role.': ' Il ne rappellera que toi, pas tout le rôle.',
    'Snoozed until {when}. It will be delivered to your DMs, as you are not the author: '
    'make sure I\'m allowed to message you.':
        'Reporté au {when}. Il arrivera en MP car tu n’es pas l’auteur : vérifie que j’ai le droit de t’écrire.',
    'This reminder is gone: deleted, or delivered more than 7 days ago.':
        'Ce rappel n’existe plus : supprimé, ou envoyé il y a plus de 7 jours.',
    'Unknown button.': 'Bouton inconnu.',
    'Only the author of this reminder can change it.': 'Seul l’auteur de ce rappel peut le modifier.',
    'This reminder has no next date.': 'Ce rappel n’a pas de prochaine date.',
    'Skipped {skipped}. Next one: {next}.\nTo undo, delete the exclusion date in `/reminder_list` > Edit Interval.':
        '{skipped} sauté. Prochain : {next}.\nPour annuler, supprime la date d’exception dans `/reminder_list` > '
        'Répétition.',
    'none': 'aucun',
    'Only the author of this reminder, the members it is for or mentions, or a moderator can delete it.':
        'Seuls l’auteur de ce rappel, les membres à qui il est destiné ou qu’il mentionne, et les modérateurs '
        'peuvent le supprimer.',
    'Deleted Reminder': 'Rappel supprimé',
    'The reminder was deleted by {by}': 'Le rappel a été supprimé par {by}',
    'its author': 'son auteur',
    'Snooze the reminder': 'Reporter le rappel',
    'Snooze until': 'Reporter à',
    'in 2h, tomorrow 18:00, friday 9:00': 'dans 2h, demain 18h, vendredi 9h',
    'That is a repetition, a snooze needs one date.': 'C’est une répétition : un report demande une seule date.',
    'Couldn\'t read a date in the future from `{text}`.': 'Je ne trouve pas de date à venir dans `{text}`.',
    'Something went wrong, sorry. The error was logged.': 'Une erreur est survenue, désolé. Elle a été notée.',

    # ---------- notices ----------
    'Your reminder was deleted': 'Ton rappel a été supprimé',
    '**{name}** ({where})\nDeleted by {who}.': '**{name}** ({where})\nSupprimé par {who}.',
    'by DM': 'par MP',
    '#{channel} on {guild}': '#{channel} sur {guild}',

    # ---------- errors of a command ----------
    'Something went wrong': 'Une erreur est survenue',
    'The bot couldn\'t finish this command. The error was logged with the code below: if it keeps happening, '
    'give it to a moderator or to the owner of the bot.':
        'Le bot n’a pas pu terminer cette commande. L’erreur a été notée avec le code ci-dessous : si elle revient, '
        'donne-le à un modérateur ou au propriétaire du bot.',
    'Error Code': 'Code d’erreur',
}


def plural(lang: str, text: str) -> str:
    """'1 jours' → '1 jour' (the English texts don't care)"""
    return _plural_fr(text) if lang == FR else text
