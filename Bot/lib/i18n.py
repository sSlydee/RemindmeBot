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


def tr(lang: str, text: str, /, **kwargs) -> str:
    """text in that language (English when there is no translation)

    lang and text are positional only: any placeholder name can be passed (text=..., lang=...)
    """
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

    # ---------- menus (util.interaction) ----------
    'Only the person who opened this menu can use it.': 'Seule la personne qui a ouvert ce menu peut l’utiliser.',
    'Menu closed': 'Menu fermé',
    'This reminder was changed in another menu, delivered or deleted meanwhile. Open `/reminder_list` again.':
        'Ce rappel a été modifié dans un autre menu, envoyé ou supprimé entre-temps. Rouvre `/reminder_list`.',
    'Saved. ': 'Enregistré. ',
    'This menu has expired, open it again with `/reminder_list`.': 'Ce menu a expiré, rouvre-le avec `/reminder_list`.',
    'Confirm': 'Confirmer',
    'Confirmed': 'Confirmé',
    'Abort': 'Annuler',
    'Aborted': 'Annulé',

    # ---------- /reminder_list ----------
    'My reminders': 'Mes rappels',
    'For me': 'Pour moi',
    'Whole server': 'Tout le serveur',
    'No pending reminders. Create one with `/remindme`.': 'Aucun rappel en attente. Crée-en un avec `/remindme`.',
    'No reminders from other members for you. When someone reminds you with `/remind`, '
    'or mentions you in a reminder, you can delete it here.':
        'Aucun rappel d’autres membres pour toi. Quand quelqu’un te rappelle quelque chose avec `/remind`, '
        'ou te mentionne dans un rappel, tu peux le supprimer ici.',
    'No pending reminders on this server.': 'Aucun rappel en attente sur ce serveur.',
    'a former member': 'un ancien membre',
    'you': 'toi',
    'another member': 'un autre membre',
    'Your private reminders': 'Tes rappels privés',
    'Reminders for you · {guild}': 'Rappels pour toi · {guild}',
    'All reminders · {guild}': 'Tous les rappels · {guild}',
    'Your reminders · {guild}': 'Tes rappels · {guild}',
    'from {name}': 'de {name}',
    'for {name}': 'pour {name}',
    'from you': 'de toi',
    '⏸️ paused': '⏸️ en pause',
    'paused': 'en pause',
    'no next date': 'pas de prochaine date',
    'DM': 'MP',
    '*empty reminder*': '*rappel vide*',
    'Select a reminder to edit': 'Choisis un rappel à modifier',
    'custom repetition': 'répétition personnalisée',
    ' (+{n} more)': ' (+{n} autres)',
    '{n} dates': '{n} dates',
    ', 1 exception': ', 1 exception',
    ', {n} exceptions': ', {n} exceptions',
    'Page {page}/{pages} · 1 reminder': 'Page {page}/{pages} · 1 rappel',
    'Page {page}/{pages} · {n} reminders': 'Page {page}/{pages} · {n} rappels',

    # ---------- edit menu, channel ----------
    'Edit Channel': 'Salon',
    'Resume': 'Reprendre',
    'Pause': 'Pause',
    'Return': 'Retour',
    'Delete': 'Supprimer',
    'Cancel': 'Annuler',
    'Skip the next date?': 'Sauter la prochaine date ?',
    'The reminder won\'t be sent on {date}.\nThis adds an exclusion date, which you can delete in `Edit Interval`.':
        'Le rappel ne sera pas envoyé le {date}.\nÇa ajoute une date à sauter, que tu peux supprimer dans `Répétition`.',
    'Delete Reminder?': 'Supprimer le rappel ?',
    'Select the channel for this reminder': 'Choisis le salon de ce rappel',
    'Send in the channel': 'Envoyer dans le salon',
    'Send by DM': 'Envoyer en MP',
    'Select a new channel': 'Choisis un nouveau salon',
    'by DM (in its channel if the DM fails)': 'par MP (dans son salon si le MP échoue)',
    'Sent': 'Envoi',
    'Failed to edit Reminder': 'Impossible de modifier le rappel',
    'Couldn\'t resolve the selected channel. Ensure that I have sufficient permissions.':
        'Salon introuvable. Vérifie que j’ai les permissions nécessaires.',
    'Failed to set new Channel': 'Impossible de changer de salon',
    'I am missing permissions to send messages in `{channel}`': 'Il me manque la permission d’écrire dans `{channel}`',
    'You can\'t send messages in `{channel}` yourself': 'Tu ne peux pas écrire toi-même dans `{channel}`',
    'New Notification Channel': 'Nouveau salon',
    'Do you want to deliver this reminder to `{channel}`?': 'Envoyer ce rappel dans `{channel}` ?',

    # ---------- the Edit popup ----------
    'Title': 'Titre',
    '(optional)': '(facultatif)',
    'Content': 'Contenu',
    'Image Url (optional)': 'Lien d’image (facultatif)',
    'Remind at (e.g. tomorrow 9:00, 13 Nov 18:30)': 'Date (ex. demain 9h, 13 nov 18h30)',
    'Remind at': 'Date',
    'Repeating: change its dates with Edit Interval': 'Rappel répété : change ses dates avec Répétition',
    'Didn\'t change the image: `{url}` is not a valid URL.\n': 'Image inchangée : `{url}` n’est pas un lien valide.\n',
    'Didn\'t change the reminder date: couldn\'t read `{text}`.\n': 'Date inchangée : impossible de lire `{text}`.\n',
    'Repeating dates must be added with `Set Interval`.\n': 'Les répétitions s’ajoutent avec `Répéter`.\n',
    'Didn\'t change the reminder date: it must be in the future.\n': 'Date inchangée : elle doit être dans le futur.\n',
    'The `Interval` attribute must be edited with `Edit Interval`.\n': 'Les répétitions se modifient avec `Répétition`.\n',
    'Reminder updated': 'Rappel modifié',

    # ---------- repetition menus ----------
    'Add new rules': 'Ajouter des règles',
    'Pick a quick repetition below, or add a rule written like '
    '`every friday at 7`, `every 2 weeks`, `every weekday` or `every weekend`.\n'
    'RRULEs work too (e.g. `FREQ=MONTHLY;BYDAY=1MO`): you can use an [RRULE Generator]({url}).':
        'Choisis une répétition rapide ci-dessous, ou ajoute une règle écrite comme `tous les vendredis à 7h`, '
        '`toutes les 2 semaines`, `en semaine` ou `tous les week-ends`.\n'
        'Les RRULE marchent aussi (ex. `FREQ=MONTHLY;BYDAY=1MO`) : tu peux utiliser un [générateur de RRULE]({url}).',
    'Quick repeat...': 'Répétition rapide...',
    'Every day': 'Tous les jours',
    'Every weekday (Mon-Fri)': 'En semaine (lun-ven)',
    'Every weekend (Sat-Sun)': 'Le week-end (sam-dim)',
    'Every week': 'Toutes les semaines',
    'Every 2 weeks': 'Toutes les 2 semaines',
    'Every month': 'Tous les mois',
    'Every year': 'Tous les ans',
    'Add Repeating Rule': 'Règle de répétition',
    'Add Exception Rule': 'Règle d’exception',
    'Add Single Date': 'Date en plus',
    'Add Exception Date': 'Date à sauter',
    'This rule has no date in the future.': 'Cette règle n’a aucune date à venir.',
    'This exception removes every future date of the reminder. To stop the reminder, delete it instead.':
        'Cette exception supprime toutes les dates à venir du rappel. Pour l’arrêter, supprime-le plutôt.',
    'Couldn\'t read this rule.': 'Impossible de lire cette règle.',
    'Invalid rule': 'Règle invalide',
    '\nPlease try again. You can build an RRULE with an [RRULE Generator]({url}).':
        '\nRéessaie. Tu peux construire une RRULE avec un [générateur de RRULE]({url}).',
    'New Repeating Rule': 'Nouvelle répétition',
    'New Exception Rule': 'Nouvelle exception',
    'Add **{rule}**? The reminder will be sent on the dates of this rule.':
        'Ajouter **{rule}** ? Le rappel sera envoyé aux dates de cette règle.',
    'Add **{rule}**? The reminder will not be sent on the dates of this rule.':
        'Ajouter **{rule}** ? Le rappel ne sera pas envoyé aux dates de cette règle.',
    'Skipped dates': 'Dates sautées',
    'Next dates of this rule': 'Prochaines dates de cette règle',
    'This is a repetition, not a single date: use `Add Repeating Rule` for it.':
        'C’est une répétition, pas une date : utilise `Règle de répétition`.',
    'Couldn\'t read a date from `{text}`.': 'Impossible de lire une date dans `{text}`.',
    'Only dates in the future are allowed.': 'Seules les dates à venir sont acceptées.',
    'Invalid input date': 'Date invalide',
    '\nPlease try again.': '\nRéessaie.',
    'New single date': 'Nouvelle date',
    'New date exception': 'Nouvelle date à sauter',
    'Add `{date}` as a new single date?': 'Ajouter la date `{date}` ?',
    'Add `{date}` as a new date exception?': 'Sauter la date `{date}` ?',
    'Repeat, e.g. "every friday at 7" or an RRULE': 'Répétition, ex. « tous les vendredis à 7h »',
    'Skip, e.g. "every saturday" or an RRULE': 'À sauter, ex. « tous les samedis »',
    'Write the repetition in plain words (`every friday at 7`, `every 2 weeks`, `every weekday`, `every weekend`) '
    'or paste an RRULE.\nBuild an RRULE with the [RRULE Generator]({url}).':
        'Écris la répétition en mots (`tous les vendredis à 7h`, `toutes les 2 semaines`, `en semaine`, '
        '`tous les week-ends`) ou colle une RRULE.\nConstruis une RRULE avec le [générateur de RRULE]({url}).',
    'The reminder will **not** be sent on the dates of this rule. Write it in plain words (`every saturday`) '
    'or paste an RRULE.\nBuild an RRULE with the [RRULE Generator]({url}).':
        'Le rappel ne sera **pas** envoyé aux dates de cette règle. Écris-la en mots (`tous les samedis`) '
        'ou colle une RRULE.\nConstruis une RRULE avec le [générateur de RRULE]({url}).',
    'Enter a new date (fuzzy or iso)': 'Nouvelle date (ex. demain 9h)',
    'Add a single occurrence date': 'Ajouter une date',
    'Enter an exclusion date (fuzzy or iso)': 'Date à sauter (ex. vendredi 9h)',
    'Add a single exclusion date': 'Ajouter une date à sauter',
    'Select a rule or a date below to see it in full, or to delete it.':
        'Choisis une règle ou une date ci-dessous pour la voir en entier, ou la supprimer.',
    'Show/Delete existing rules': 'Voir/supprimer les règles',
    'Select a rule/date for more info': 'Choisis une règle ou une date',
    'Add New Rule': 'Ajouter une règle',
    'Delete Selected': 'Supprimer la sélection',
    'Danger': 'Attention',
    'Are you sure to delete the rule `{rule}`?': 'Supprimer vraiment la règle `{rule}` ?',
    'Orphan warning': 'Plus aucune date',
    'The reminder has no further events pending. It will be deleted soon, if no new rule is added':
        'Le rappel n’a plus aucune date à venir. Il sera bientôt supprimé si aucune règle n’est ajoutée.',
    'Repeating rule': 'Règle de répétition',
    'Exception rule': 'Règle d’exception',
    'Single date': 'Date en plus',
    'Exception date': 'Date à sauter',

    # ---------- /settings ----------
    'Remindme Settings': 'Réglages de Remindme',
    'Server Managers can edit these settings by pressing the corresponding buttons below.\n'
    'The grayed-out buttons are the current selected options.\n\n'
    '**Members\' reminders**: new reminders for one member are sent in their channel, '
    'or by DM (in the channel if the DM fails). Reminders for a role stay in the channel.':
        'Les membres qui peuvent gérer le serveur changent ces réglages avec les boutons ci-dessous.\n'
        'Les boutons grisés sont les choix actuels.\n\n'
        '**Rappels des membres** : les nouveaux rappels pour un membre sont envoyés dans leur salon, '
        'ou en MP (dans le salon si le MP échoue). Les rappels pour un rôle restent dans le salon.',
    'Your own settings: the style of the reminders the bot sends you by DM. The other settings are for servers.':
        'Tes propres réglages : le style des rappels que le bot t’envoie en MP. Les autres réglages concernent les serveurs.',
    'You need the `Manage Server` permission to change the settings of this server.':
        'Il faut la permission `Gérer le serveur` pour changer les réglages de ce serveur.',
    'Missing Permissions': 'Permission manquante',
    'Server Timezone': 'Fuseau horaire',
    'Preferred Reminder Style': 'Style des rappels',
    'Hybrid Reminders': 'Hybride',
    'Embed-Only Reminders': 'Embed seul',
    'Text-Only Reminders': 'Texte seul',
    'Barebone Reminders': 'Minimal',
    'Creation Reply': 'Réponse à la création',
    'Delete after Timeout': 'Supprimer après 5 min',
    'Never Delete': 'Ne jamais supprimer',
    'Only Show to author': 'Visible par l’auteur seul',
    "Members' reminders": 'Rappels des membres',
    'In the channel': 'Dans le salon',
    'By DM': 'En MP',

    # ---------- /timezone ----------
    'Current Timezone': 'Fuseau horaire actuel',
    'New Timezone': 'Nouveau fuseau horaire',
    'The timezone is set to': 'Le fuseau horaire est',
    'The timezone will be set to': 'Le fuseau horaire sera',
    '\nUse `/timezone` to edit this value': '\n`/timezone` pour le changer',
    'This corresponds to a local time of `{time}`': 'Il est actuellement `{time}` dans ce fuseau',
    '\n• Consider using your local timezone (instead of `UTC+X`), in order to automatically adjust to daylight-saving*':
        '\n• Préfère ton fuseau local (plutôt que `UTC+X`), pour suivre automatiquement l’heure d’été*',
    '\n• Consider using `{zone}` to respect daylight saving during winter':
        '\n• Préfère `{zone}` pour suivre l’heure d’hiver',
    '\n• `{zone}` seems to be a deprecated timezone and could be discontinued in future versions.\n'
    '• Try and use a geo-referenced timezone that _observes_ `{zone}` instead (e.g. `Europe/Berlin`)':
        '\n• `{zone}` semble être un fuseau obsolète, qui pourrait disparaître.\n'
        '• Préfère un fuseau géographique qui _suit_ `{zone}` (ex. `Europe/Paris`)',
    'Invalid Timezone configuration': 'Fuseau horaire invalide',
    'or select one from the list below': 'ou choisis-en un ci-dessous',
    'The timezone `{zone}` is not valid\n'
    'Please re-invoke the command with a valid timezone {select}\n\n'
    'You can have a look at all available timezones on this '
    '[wikipedia list](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)':
        'Le fuseau `{zone}` n’existe pas.\nRelance la commande avec un fuseau valide {select}\n\n'
        'La liste complète est sur '
        '[Wikipédia](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones).',
    'Select a timezone': 'Choisis un fuseau horaire',

    # ---------- /help ----------
    'Something looks wrong? Tell a moderator of your server.': 'Un souci ? Demande à un modérateur de ton serveur.',
    'Self-Test': 'Autotest',
    'Privacy': 'Confidentialité',
    'Please select a category': 'Choisis une page',
    'Overview Page': 'Commandes',
    'Syntax Page': 'Syntaxe',
    'Timezone Page': 'Fuseau horaire',
    'Overview': 'Toutes les commandes',
    'Syntax': 'Écrire une date ou une répétition',
    'Timezone': 'Régler le fuseau horaire',
    'Test Message': 'Message de test',
    'You can safely delete this message': 'Tu peux supprimer ce message',
    'Test Message, *please ignore this*': 'Message de test, *ignore-le*',
    'Self-testing... *please ignore this.*': 'Autotest... *ignore ce message.*',
    '*Text Only*': '*Texte seul*',
    '**Failed**': '**Échec**',
    '• Enable `Embed Links` permissions, to allow for a better reminder display\n':
        '• Donne-moi la permission `Intégrer des liens` pour de plus jolis rappels\n',
    '• Enable `Send Message` permissions for this text channel\n':
        '• Donne-moi la permission `Envoyer des messages` dans ce salon\n',
    '• Allow me to send you DMs to configure reminders and to receive error information, '
    '[change your preferences]({url}) and test again.':
        '• Autorise mes MP pour recevoir tes rappels et les erreurs : '
        '[change tes préférences]({url}) et refais le test.',
    'Reminder delivery': 'Envoi des rappels',
    'DM permissions': 'MP',
    'Local Time': 'Heure locale',
    '{time} (based on timezone settings)': '{time} (selon le fuseau horaire réglé)',
    'Discord API Latency': 'Latence de Discord',
    'Library Latency*': 'Latence du bot*',
    'Self-Test Duration*': 'Durée du test*',
    '*this includes server and discord time inaccuracies towards `Coordinated Universal Time`':
        '*inclut les écarts d’horloge du serveur et de Discord avec l’heure universelle',

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
