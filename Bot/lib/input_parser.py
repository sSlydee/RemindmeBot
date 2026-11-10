import itertools
import re
import threading
import zoneinfo
import lib.timeutil as timeutil
from datetime import datetime, timedelta

import dateutil.parser
from dateutil.relativedelta import *
from dateutil import tz
import dateutil.rrule as rr
from parsedatetime import parsedatetime

from lib.recurrent.src.recurrent.event_parser import RecurringEvent


_parse_consts = parsedatetime.Constants(localeID='en_US', usePyICU=True)
_parse_consts.useMeridian = False
_parse_consts.use24 = True
_parse_consts.dateFormats = {
    'full': 'EEEE, d. MMMM yyyy',
    'long': 'd. MMMM yyyy',
    'medium': 'dd.MM.yyyy',
    'short': 'dd.MM.yy',
}
_parse_consts.timeFormats = {
    'full': 'HH:mm:ss v',
    'long': 'HH:mm:ss z',
    'medium': 'HH:mm:ss',
    'short': 'HH:mm',
}
_parse_consts.dp_order = ['d', 'm', 'y']


def num_to_emoji(num: int):
    """convert a single digit to the numbers emoji
    Arguments:
        num {int}
    Returns:
        [str] -- unicode emoji, * if num was out of range [0..9]
    """
    if num == 1:
        return '1️⃣'
    elif num == 2:
        return '2️⃣'
    elif num == 3:
        return '3️⃣'
    elif num == 4:
        return '4️⃣'
    elif num == 5:
        return '5️⃣'
    elif num == 6:
        return '6️⃣'
    elif num == 7:
        return '7️⃣'
    elif num == 8:
        return '8️⃣'
    elif num == 9:
        return '9️⃣'
    elif num == 0:
        return '0️⃣'
    else:
        return '*️⃣'


def _split_arg(arg):

    num_regex = re.search(r'-?\d+', arg)

    if num_regex:
        num_arg = num_regex.group()

        return (int(num_arg), arg.replace(num_arg, ''))
    else:
        return (None, arg)


def _join_spaced_args(args):

    joined_args = []
    
    i = 0
    while i < len(args):
        arg = args[i]

        if i+1 >= len(args):
            # cannot perform operation on last element
            joined_args.append(arg)

        # i+1 is guaranteed to exist
        elif (arg[0] != None and not arg[1]) and (not args[i+1][0] and args[i+1][1]):
            joined_args.append((arg[0], args[i+1][1]))
            i += 1 # skip next element

        else:
            # element is not complete, but following element doesn't allow joinup
            # this is caused by args like eom, eoy, ...
            joined_args.append(arg)
            
        i += 1

    return joined_args
            

def _parse_relative(args, utcnow):
    """parse the date to relative arguments
       (2y, 5d,...)

       gives the absolute utc-date when the reminder
       should be triggered

    Args:
        args ([]]): list of arguments
        utcnow (datetime): current utc datetime

    Returns:
        (datetime, str, exception): non tz-aware date when reminder is trigger (in utc time), =utcnow on error
                                    info string for parsing errors/warnings
                                    exception if one was caught, which is of interest for further processing
    """

    total_intvl = timedelta(hours=0)
    info = ''
    previous_unit = ''

    for arg in args:

        intvl = timedelta(hours=0) # default in case of no-match

        if arg[0] == None:
            return (utcnow, f'• Argument {arg} is starting with a number\n', None)

        if arg[1] == '' and previous_unit.startswith('h'):
            # '1h30': the minutes after the hours
            arg = (arg[0], 'm')
        previous_unit = arg[1]

        if arg[1].startswith('y'):
            intvl = relativedelta(years=arg[0])

        elif arg[1].startswith('mo'):
            intvl = relativedelta(months=arg[0])

        elif arg[1].startswith('w'):
            intvl = relativedelta(weeks=arg[0])

        elif arg[1] == 'd' or arg[1].startswith('da'):
            # condition must not detect the month 'december'
            intvl = timedelta(days=arg[0]) 

        elif arg[1].startswith('h'):
            intvl = timedelta(hours=arg[0])

        elif arg[1].startswith('mi'):
            intvl = timedelta(minutes=arg[0])
        
        elif arg[1] == 'm':
            intvl = timedelta(minutes=arg[0])
        else:
            return (utcnow, f'• Unknown parameter {arg}', None)
            
        total_intvl += intvl

    try:
        eval_interval = utcnow + total_intvl
    except ValueError as ex:
        return (utcnow, 'The interval is out of bounds/not a number', ex)

    return (eval_interval, info, None)


def _parse_iso(input, utcnow, display_tz):

    try:
        remind_parse = dateutil.parser.isoparse(input)
    except ValueError as e:
        info = '• ' + ' '.join(e.args)
        remind_parse = None
    except:
        info = '• Unexpected parser error occurred'
        remind_parse = None
    else:
        info = ''

    # if the input string doesn't hold any timezone
    # it is converted into the local timzone
    # otherwise not modified
    # error assumes current utc time
    if remind_parse and not remind_parse.tzinfo:
        remind_aware = remind_parse.replace(tzinfo=display_tz)
    elif not remind_parse:
        remind_aware = utcnow.replace(tzinfo=tz.UTC)
    else:
        remind_aware = remind_parse


    # convert the parsed time back into a non-tz aware string
    # at utc
    remind_utc = remind_aware.astimezone(tz.UTC)
    remind_at = remind_utc.replace(tzinfo=None)

    return (remind_at, info, None)


def _parse_fuzzy(input, utcnow, display_tz):
    """parse a fuzzy input string using dateutil

       gives the absolute utc-date when the reminder
       should be triggered

    Args:
        input (str): input string, provided by user
        utcnow (datetime): current utc datetime
        display_tz (tzfile): the timezone of the guild/user

    Returns:
        (datetime, str, exception): non tz-aware date when reminder is trigger (in utc time), =utcnow on error
                         info string for parsing errors/warnings
    """

    info = ''
    localnow = utcnow.replace(tzinfo=tz.UTC).astimezone(display_tz)

    eod_re = re.compile(r'\b(end of day)|eod\b')
    eow_re = re.compile(r'\b(end of week)|eow\b')
    eom_re = re.compile(r'\b(end of month)|eom\b')
    eoy_re = re.compile(r'\b(end of year)|eoy\b')
    
    replace_datetime = None
    matched_regex = None
    
    # remove timezone awareness, on each date w/o converting to utc
    # parser wil assume local time for natural language
    if eod_re.match(input):
        tmp = localnow.replace(hour=0, minute=0, second=0, microsecond=0)
        replace_datetime = tmp + relativedelta(hours=17)  # could be one-liner, but stay consistent with other cases
        matched_regex = eod_re

    elif eow_re.match(input):
        w_day = localnow.weekday()
        tmp = localnow - timedelta(days=w_day)
        tmp = tmp.replace(hour=0, minute=0, second=0, microsecond=0)
        replace_datetime = tmp + relativedelta(days=5, hours=-7)  # 17:00 on last day of week
        if w_day >= 5:
            # on the weekend, the working week to end is the next one
            replace_datetime += relativedelta(weeks=1)

        matched_regex = eow_re

    elif eom_re.match(input):
        tmp = localnow.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        replace_datetime = tmp + relativedelta(months=1, hours=-12)  # 12:00 on last day of month
        matched_regex = eom_re

    elif eoy_re.match(input):
        tmp = localnow.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        replace_datetime = tmp + relativedelta(years=1, hours=-15)  # 9:00 on last day of year
        matched_regex = eoy_re

    # without regex match, no replacement can happend (obviously)
    if replace_datetime is not None and matched_regex is not None:
        # the absolute date could be called on the last day, but after the default reminding hour
        # for that case, the reminder is pushed back by 2 hours, or by the last millisecond of the day
        # whatever is earlier
        if replace_datetime < localnow:
            delta_option = (localnow + relativedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
            fixed_option = replace_datetime.replace(hour=0) + relativedelta(hours=24, microseconds=-1)
            replace_datetime = min(delta_option, fixed_option)
        
        # disregard the timezone
        replace_datetime = replace_datetime.replace(tzinfo=None)
        # export microseconds here
        # although the parser is ignoring them
        input = matched_regex.sub(replace_datetime.strftime('%d/%m/%Y %H:%M:%S.%f'), input)

    r = RecurringEvent(now_date=localnow, preferred_time_range=(0,12), parse_constants=_parse_consts)
    remind_parse = r.parse(input)

    if remind_parse is None:
        # try additional approach
        # this is mainly executed to get a verbose error message
        # which is not provided by recurrent
        try:
            remind_parse = dateutil.parser.parse(input, fuzzy=True, dayfirst=True, yearfirst=False)
        except dateutil.parser.ParserError as e:
            info = f'• {e}'
            remind_parse = None
        except Exception as e:
            remind_parse = None
            info = '• Unexpected parser error occurred ({:s})'.format(''.join(e.args))
        else:
            info = ''
    
    if isinstance(remind_parse, datetime):
        remind_parse = remind_parse.replace(tzinfo=display_tz)
        remind_utc = remind_parse.astimezone(tz.UTC)
        remind_at = remind_utc.replace(tzinfo=None)
    elif isinstance(remind_parse, str):
        remind_at = remind_parse
    else:
        remind_at = None  # could be hit in case of error in parser

    return (remind_at, info, None)


_MONTH = r'(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'

def _ordinal(day: str) -> str:
    n = int(day)
    return f'{n}th' if 10 <= n % 100 <= 20 else f'{n}' + {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')


_DAYS_FR = {'lundi': 'monday', 'mardi': 'tuesday', 'mercredi': 'wednesday', 'jeudi': 'thursday',
            'vendredi': 'friday', 'samedi': 'saturday', 'dimanche': 'sunday'}
_MONTHS_FR = {'janvier': 'january', 'février': 'february', 'fevrier': 'february', 'mars': 'march',
              'avril': 'april', 'mai': 'may', 'juin': 'june', 'juillet': 'july', 'août': 'august',
              'aout': 'august', 'septembre': 'september', 'octobre': 'october', 'novembre': 'november',
              'décembre': 'december', 'decembre': 'december'}
_DAY_FR = '(' + '|'.join(_DAYS_FR) + ')'
_I = re.IGNORECASE

# French into English, read by the English parsers ('demain à 18h30', 'tous les lundis à 9h')
_FRENCH = [
    # 'day after tomorrow' is read as tomorrow; 'in 2 days 10h' would be a duration
    (re.compile(r'\bapr[eè]s[-\s]demain(?:\s+(?:à|a)?\s*(?=\d|midi\b))', _I), 'in 2 days at '),
    (re.compile(r'\bapr[eè]s[-\s]demain\b', _I), 'in 2 days'),
    (re.compile(r"\baujourd['’]\s?hui\b", _I), 'today'),
    (re.compile(r'\bdemain\b', _I), 'tomorrow'),
    (re.compile(r'\bce\s+soir\b', _I), 'tonight'),
    (re.compile(rf'\b{_DAY_FR}\s+prochain\b', _I), r'next \1'),
    (re.compile(r'\bla\s+semaine\s+prochaine\b', _I), 'next week'),
    (re.compile(r'\ble\s+mois\s+prochain\b', _I), 'next month'),
    (re.compile(r'\b(?:tous\s+les|chaque)\s+jours?\s+(?:de\s+(?:la\s+)?semaine|ouvr[ée]s?)\b|\ben\s+semaine\b', _I),
     'every weekday'),
    (re.compile(r'\b(?:tous|toutes)\s+les\b|\bchaque\b', _I), 'every'),
    (re.compile(r"\bjusqu['’]?\s*(?:au|à|a)\b", _I), 'until'),
    (re.compile(r'(\d+)\s*heures?\b', _I), r'\1 hours'),
    (re.compile(r'(\d+)\s*jours?\b', _I), r'\1 days'),
    (re.compile(r'(\d+)\s*semaines?\b', _I), r'\1 weeks'),
    (re.compile(r'(\d+)\s*mois\b', _I), r'\1 months'),
    (re.compile(r'(\d+)\s*(?:ans?|ann[ée]es?)\b', _I), r'\1 years'),
    (re.compile(r'\bevery\s+jours?\b', _I), 'every day'),
    (re.compile(r'\bevery\s+semaines?\b', _I), 'every week'),
    (re.compile(r'\bevery\s+mois\b', _I), 'every month'),
    (re.compile(r'\bevery\s+(?:ans|ann[ée]es)\b', _I), 'every year'),
    (re.compile(r'\bevery\s+heures?\b', _I), 'every hour'),
    (re.compile(r'\bweek-?ends?\b', _I), 'weekend'),
    # 'tous les mois le 15', 'tous les ans le 1er juillet'
    (re.compile(r'\bevery\s+month\s+le\s+(\d{1,2})(?:er)?\b', _I), lambda m: f'every month on the {_ordinal(m[1])}'),
    (re.compile(r'\bevery\s+year\s+le\s+', _I), 'every year on '),
    (re.compile(r'\b(\d{1,2})er\b', _I), r'\1'),
    (re.compile(r'\ble\s+(?=\d)', _I), ''),
    (re.compile(r'\b(?:premi(?:er|ère)s?|1(?:er|ère|re))\s+(?=' + _DAY_FR[1:-1] + ')', _I), 'first '),
    (re.compile(r'\b(?:deuxi[eè]me|2e|2ème)s?\s+(?=' + _DAY_FR[1:-1] + ')', _I), 'second '),
    (re.compile(r'\b(?:troisi[eè]me|3e|3ème)s?\s+(?=' + _DAY_FR[1:-1] + ')', _I), 'third '),
    (re.compile(r'\b(?:quatri[eè]me|4e|4ème)s?\s+(?=' + _DAY_FR[1:-1] + ')', _I), 'fourth '),
    (re.compile(r'\bderni(?:er|ère)s?\s+(?=' + _DAY_FR[1:-1] + ')', _I), 'last '),
    (re.compile(r'\bdu\s+mois\b', _I), 'of the month'),
    (re.compile(rf'\b{_DAY_FR}s?\b', _I), lambda m: _DAYS_FR[m[1].lower()]),
    (re.compile(r'\b(' + '|'.join(_MONTHS_FR) + r')\b', _I), lambda m: _MONTHS_FR[m[1].lower()]),
    (re.compile(r'\bmidi\b', _I), 'noon'),
    (re.compile(r'\bminuit\b', _I), 'midnight'),
    (re.compile(r'\bdans\b', _I), 'in'),
    (re.compile(r'(?:\bà|\ba)\s+(?=\d|noon\b|midnight\b)', _I), 'at '),
    (re.compile(r'\bet\b', _I), 'and'),
]

# rewrites of inputs the parsers misread, into forms they read well
_REWRITES = [
    # 'every 2h' was read as today 02:00
    (re.compile(r'\bevery\s+(\d+)\s*h(?:rs?|ours?)?\b', re.IGNORECASE), r'every \1 hours'),
    (re.compile(r'\bevery\s+(\d+)\s*(?:mn|min|m)\b', re.IGNORECASE), r'every \1 minutes'),
    # parsedatetime knows 'sep' and 'september', 'thu' and 'thursday' only
    (re.compile(r'\bsept\b\.?', re.IGNORECASE), 'sep'),
    (re.compile(r'\bthurs?\b\.?', re.IGNORECASE), 'thu'),
    # 'every year on the 1st of july' / 'every 1 july': recurrent reads 'every july 1'
    (re.compile(rf'\bevery\s+(?:year\s+(?:on|at|in)\s+)?(?:the\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH})\b', re.IGNORECASE),
     r'every \2 \1'),
    (re.compile(rf'\bevery\s+year\s+(?:on|at|in)\s+(?=(?:the\s+)?{_MONTH}\b)', re.IGNORECASE), 'every '),
    # '2 aug 3pm' was read as 02:00 on 2 August: '2 aug at 3pm'
    (re.compile(rf'^(\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\.?(?:\s+\d{{4}})?)\s+(?=\d{{1,2}}(?::\d{{2}})?\s*(?:am|pm)?$)',
                re.IGNORECASE), r'\1 at '),
]

# a time of day alone ('9:00', '9am', 'at 9', 'noon'): once passed, it means tomorrow
# (not a bare number: '9' is read as the 9th of the month)
_TIME_ONLY_RE = re.compile(r'^(?:at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?|\d{1,2}:\d{2}\s*(?:am|pm)?|\d{1,2}\s*(?:am|pm)|noon|midnight)$',
                           re.IGNORECASE)


# '9h', '18h30', '18 h 30': a time of day, once the input is not a duration ('1h30' alone)
_H_TIME_RE = re.compile(r'(?<![\w:])([01]?\d|2[0-3])\s?h(?:\s?([0-5]\d))?(?!\w)', re.IGNORECASE)


def _rewrite(text: str) -> str:
    for pattern, replacement in _FRENCH + _REWRITES:
        text = pattern.sub(replacement, text)
    return text


# a time right after a repetition or 'in 2 days' needs an 'at' ('every friday 18:00' lost its time)
_AT_TIME_RE = re.compile(r'\b((?:every|in\s+\d+\s+days?)\b[^:]*?[a-z])\s+(\d{1,2}:\d{2})\b', re.IGNORECASE)


# compact durations ('1y', '2d', '5mi'): their 'h' is a duration too
_COMPACT_DURATION_RE = re.compile(r'\b\d+(?:y|mo|w|d|mi|min|m)\b', re.IGNORECASE)


def _h_times(text: str) -> str:
    if not _COMPACT_DURATION_RE.search(text):
        text = _H_TIME_RE.sub(lambda m: f'{m[1]}:{m[2] or "00"}', text)
    return _AT_TIME_RE.sub(lambda m: m[0] if m[1].lower().endswith(' at') else f'{m[1]} at {m[2]}', text)


def parse(input, utcnow, timezone='UTC'):
    """parse the input string, see _parse; a date too far away is an error"""
    try:
        return _parse(input, utcnow, timezone)
    except OverflowError:
        # e.g. '999999999d': beyond the year 9999
        return (utcnow, '• the given date is too far in the future\n')


def _parse(input, utcnow, timezone='UTC'):
    """parse the input string into a datetime object
       this can be either relative or absolute, in relation to the input utcnow
       the function can respect the given timezone, for absolute and semi-absolute dates (e.g. oy)

    Args:
        input (str): input string, provided by the user
        utcnow (datetime): current utc time
        timezone (str, optional): target timezone (tzfile string). Defaults to 'UTC'.

    Raises:
        e: [description]

    Returns:
        (Datetime, str): Datetime: input target, returns utcnow on failure, might return dates in the past, can be None
                         str: info string on why the parser failed/ignored parts of the input
 
        (str, str):      str: rrule of reocurring event, can be None
                         str: info string on why the parser failed/gnored parst of the input
    """

    display_tz = tz.gettz(timezone)
    input = _rewrite(input.strip())

    # first split into the different arguments
    # next separate number form char arguments

    rx = re.compile(r'[^a-zA-Z0-9-]') # allow negative sign
    # 'in 1h30' is the duration '1h30'
    args = rx.split(re.sub(r'^in\s+', '', input, flags=re.IGNORECASE))
    # numbers and units written together: '1h30m' -> '1', 'h', '30', 'm'
    args = [part for arg in args for part in re.findall(r'-?\d+|[^\d-]+', arg)]

    args = list(filter(lambda a: a != None and a != '', args))
    args = list(map(_split_arg, args))
    args = _join_spaced_args(args)
    
  
    remind_at, info, ex = _parse_relative(args, utcnow)
    early_abort = (ex != None)

    if remind_at == utcnow and not early_abort:
        # not a duration: '9h' / '18h30' are times of day
        input = _h_times(input)

    if remind_at == utcnow and not early_abort:
        remind_at, info_iso, ex = _parse_iso(input, utcnow, display_tz)
        early_abort = (ex != None)
        
        # iso date will only override info on success
        # error is not overriding and only shown when no prev. info is avail.
        if (remind_at != utcnow) or (not info):
            info = info_iso

    if remind_at == utcnow and not early_abort:
        remind_at, info, ex = _parse_fuzzy(input, utcnow, display_tz)
        early_abort = (ex != None)

    if isinstance(remind_at, datetime) and remind_at != utcnow and _TIME_ONLY_RE.match(input):
        local = remind_at.replace(tzinfo=tz.UTC).astimezone(display_tz).replace(tzinfo=None)
        if ':' not in input and re.search(r'\d', input):
            # 'at 9' is 9:00 (the parser keeps the current minutes)
            local = local.replace(minute=0, second=0, microsecond=0)
        if local.replace(tzinfo=display_tz).astimezone(tz.UTC).replace(tzinfo=None) < utcnow:
            # a time of day that already passed today: tomorrow at that time
            local += timedelta(days=1)
        remind_at = local.replace(tzinfo=display_tz).astimezone(tz.UTC).replace(tzinfo=None)

    # negative intervals are not allowed
    if isinstance(remind_at, datetime) and remind_at < utcnow:
        to_local = lambda d: d.replace(tzinfo=tz.UTC).astimezone(display_tz)
        info += '• the given date must be in the future\n'
        info += '  now:        {:s}\n'.format(to_local(utcnow).strftime('%Y-%m-%d %H:%M'))
        info += '  understood: {:s}\n'.format(to_local(remind_at).strftime('%Y-%m-%d %H:%M'))
        # return negative intervals, but keep warning
    elif isinstance(remind_at, datetime):
        # protect against out of epoch dates
        try:
            datetime.timestamp(remind_at)
        except OSError:
            info =  '• the given date is exceeding the linux epoch\n'
            info += '  please choose an earlier date'
            return (utcnow, info)

    return (remind_at, info)



def rrule_to_english(rrule, now=None):
    """convert a rrule or rrule string back to an english natural interval
       can aswell suport datetime objects as input

    Args:
        rrule (rrule.rrule or str or datetime.datetime): input argument 
        now (datetime.datetime, optional): current time for parser. Defaults to utcnow()

    Returns:
        [str]: description of inputted interval or date in english
    """
    
    if not now:
        now = timeutil.utcnow()

    r = RecurringEvent(now_date=now, preferred_time_range=(0,12), parse_constants=_parse_consts)
    text = r.format(rrule)
    
    return text


_FR_DAY = {'MO': 'lundi', 'TU': 'mardi', 'WE': 'mercredi', 'TH': 'jeudi', 'FR': 'vendredi',
           'SA': 'samedi', 'SU': 'dimanche'}
_FR_MONTH = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre',
             'octobre', 'novembre', 'décembre']
_WEEKDAYS = ['MO', 'TU', 'WE', 'TH', 'FR']


def _fr_join(items: list) -> str:
    return items[0] if len(items) == 1 else ', '.join(items[:-1]) + ' et ' + items[-1]


def _fr_nth(n: int) -> str:
    """1 → '1er', 2 → '2e', -1 → 'dernier', -2 → 'avant-dernier'"""
    if n == -1:
        return 'dernier'
    if n == -2:
        return 'avant-dernier'
    if n < 0:
        raise ValueError(n)
    return '1er' if n == 1 else f'{n}e'


def _rule_fr(rule_str: str, start=True) -> str:
    """a repetition rule in French words; ValueError for the rules it can't say"""
    from lib.i18n import date_str
    dtstart = None
    parts = {}
    for line in rule_str.splitlines():
        line = line.strip()
        if line.upper().startswith('DTSTART'):
            value = line.split(':', 1)[1]
            dtstart = datetime.strptime(value.rstrip('Z')[:15], '%Y%m%dT%H%M%S')
        elif line.upper().startswith('RRULE:') or ('FREQ=' in line.upper() and '=' in line):
            body = line.split(':', 1)[1] if line.upper().startswith('RRULE:') else line
            parts = dict(part.split('=', 1) for part in body.upper().split(';') if part)
    if not parts or set(parts) - {'FREQ', 'INTERVAL', 'BYDAY', 'BYMONTHDAY', 'BYMONTH', 'BYHOUR', 'BYMINUTE',
                                  'BYSECOND', 'COUNT', 'UNTIL', 'WKST'}:
        raise ValueError('not supported')
    if parts.get('BYSECOND', '0') != '0':
        raise ValueError('seconds')

    freq = parts['FREQ']
    n = int(parts.get('INTERVAL', 1))
    days = [d for d in parts.get('BYDAY', '').split(',') if d]
    monthdays = [int(d) for d in parts.get('BYMONTHDAY', '').split(',') if d]
    months = [int(m) for m in parts.get('BYMONTH', '').split(',') if m]

    if freq == 'MINUTELY':
        text = 'toutes les minutes' if n == 1 else f'toutes les {n} minutes'
    elif freq == 'HOURLY':
        text = 'toutes les heures' if n == 1 else f'toutes les {n} heures'
    elif freq == 'DAILY':
        text = 'tous les jours' if n == 1 else f'tous les {n} jours'
    elif freq == 'WEEKLY':
        every = '' if n == 1 else f', toutes les {n} semaines'
        if any(not d.isalpha() for d in days):
            raise ValueError('nth day in a week')
        if sorted(days) == ['SA', 'SU']:
            text = 'tous les week-ends' + every
        elif sorted(days) == sorted(_WEEKDAYS):
            text = 'en semaine' + every
        elif days:
            text = 'tous les ' + _fr_join([_FR_DAY[d] + 's' for d in days]) + every
        else:
            text = 'toutes les semaines' if n == 1 else f'toutes les {n} semaines'
    elif freq == 'MONTHLY':
        each = ' de chaque mois' if n == 1 else f', tous les {n} mois'
        if days:
            nths = []
            for d in days:
                m = re.fullmatch(r'([+-]?\d+)?([A-Z]{2})', d)
                if not m or not m[1]:
                    raise ValueError('day without its rank')
                nths.append(f'{_fr_nth(int(m[1]))} {_FR_DAY[m[2]]}')
            text = 'le ' + _fr_join(nths) + each
        elif monthdays:
            if any(d < -1 for d in monthdays):
                raise ValueError('day from the end')
            text = 'le ' + _fr_join(['dernier jour' if d == -1 else ('1er' if d == 1 else str(d)) for d in monthdays]) + each
        else:
            text = 'tous les mois' if n == 1 else f'tous les {n} mois'
    elif freq == 'YEARLY':
        every = 'tous les ans' if n == 1 else f'tous les {n} ans'
        if days:
            raise ValueError('days in a year')
        if months and monthdays and len(months) == 1:
            text = every + ' le ' + _fr_join(['1er' if d == 1 else str(d) for d in monthdays]) + f' {_FR_MONTH[months[0] - 1]}'
        elif months and not monthdays:
            text = every + ' en ' + _fr_join([_FR_MONTH[m - 1] for m in months])
        elif not months and not monthdays:
            text = every
        else:
            raise ValueError('several months with days')
    else:
        raise ValueError(freq)

    hours = [int(h) for h in parts.get('BYHOUR', '').split(',') if h]
    minutes = [int(m) for m in parts.get('BYMINUTE', '').split(',') if m]
    if hours:
        if len(minutes) > 1:
            raise ValueError('several minutes')
        minute = minutes[0] if minutes else 0
        text += ' à ' + _fr_join([f'{h}h{minute:02d}' if minute else f'{h}h' for h in hours])
    elif minutes and freq == 'HOURLY':
        text += ' à ' + _fr_join([f'{m:02d}' for m in minutes]) + ' min'

    if start and dtstart:
        text += f', à partir du {date_str(dtstart, "fr", with_year=True)}'
    if 'UNTIL' in parts:
        until = datetime.strptime(parts['UNTIL'].rstrip('Z')[:8], '%Y%m%d')
        text += f' jusqu’au {"1er" if until.day == 1 else until.day} {_FR_MONTH[until.month - 1]} {until.year}'
    if 'COUNT' in parts:
        count = int(parts['COUNT'])
        text += ', 1 fois' if count == 1 else f', {count} fois'
    return text


def rule_text(rule, lang='en', now=None, start=True) -> str:
    """a repetition rule in words, in that language

    start: with the date it starts on ('starting Thu Nov 12, 2026 9am')
    A rule that French can't say yet stays in English.
    """
    if lang == 'fr':
        try:
            return _rule_fr(str(rule), start)
        except (ValueError, KeyError, IndexError):
            pass
    text = rrule_to_english(rule, now=now)
    return text if start else text.split(' starting ')[0]


_UNTIL_VALUE_RE = re.compile(r'^(\d{8})(?:T(\d{6}))?(Z)?$', re.IGNORECASE)


def _split_until(rrule_str: str, tz_str: str):
    """take the UNTIL part out of a rule string

    dateutil refuses an UTC UNTIL (with 'Z', what RRULE generators produce)
    together with a naive DTSTART, so UNTIL is handled here:
    - UTC values are converted into the local time of the rule frame
    - a date without time includes that whole day

    Returns:
        (str, datetime): the rule string without UNTIL, and the naive local
                         UNTIL (None when absent). Unknown formats are left
                         in the string, for dateutil to report them.
    """
    until = None
    out_lines = []
    for line in rrule_str.splitlines() or [rrule_str]:
        name, sep, value = line.partition(':')
        if not sep:
            name, value = '', line  # a bare rule like 'FREQ=DAILY;UNTIL=...'
        elif name.strip().upper() not in ('RRULE', 'EXRULE'):
            out_lines.append(line)  # DTSTART and other properties
            continue

        parts = []
        for part in value.split(';'):
            key, _, val = part.partition('=')
            match = _UNTIL_VALUE_RE.match(val.strip()) if key.strip().upper() == 'UNTIL' else None
            if not match:
                parts.append(part)
                continue

            date_part, time_part, utc = match.groups()
            if time_part:
                until = datetime.strptime(date_part + time_part, '%Y%m%d%H%M%S')
                if utc:
                    until = until.replace(tzinfo=tz.UTC).astimezone(tz.gettz(tz_str)).replace(tzinfo=None)
            else:
                until = datetime.strptime(date_part, '%Y%m%d').replace(hour=23, minute=59, second=59)

        value = ';'.join(parts)
        out_lines.append(f'{name}{sep}{value}' if sep else value)

    return '\n'.join(out_lines), until


_DTSTART_RE = re.compile(r'^DTSTART(?:;TZID=([^:;]+))?:(\d{8}T\d{6})(Z?)$', re.IGNORECASE)


def _find_zone(name: str):
    """the timezone of a TZID, also when its case was changed ('europe/paris')"""
    zone = tz.gettz(name)
    if zone is None:
        lower = name.lower()
        for known in zoneinfo.available_timezones():
            if known.lower() == lower:
                return tz.gettz(known)
    return zone


def _split_dtstart(rrule_str: str, tz_str: str):
    """take a DTSTART with a timezone (UTC 'Z' or TZID) out of a rule string

    The rule frame is naive local time, where dateutil would read such a
    DTSTART as local time: convert it into the local time of the server/user.

    Returns:
        (str, datetime): the rule string without that DTSTART, and the naive
                         local DTSTART (None when absent or without timezone)
    Raises:
        ValueError: unknown TZID
    """
    start = None
    out_lines = []
    for line in rrule_str.splitlines() or [rrule_str]:
        match = _DTSTART_RE.match(line.strip())
        if not match or not (match.group(1) or match.group(3)):
            out_lines.append(line)
            continue

        tzid, value, utc = match.groups()
        zone = tz.UTC if utc else _find_zone(tzid)
        if zone is None:
            raise ValueError(f'Unknown timezone `{tzid}` in DTSTART')
        start = datetime.strptime(value.upper(), '%Y%m%dT%H%M%S').replace(tzinfo=zone)
        start = start.astimezone(tz.gettz(tz_str)).replace(tzinfo=None)

    return '\n'.join(out_lines), start


# reminders can't repeat more often than this (no spam)
MIN_REPEAT_GAP = timedelta(minutes=10)
# a rule must have a date within this many years from its start
CHECK_YEARS = 10
# seconds to find the first dates of a rule
CHECK_TIMEOUT = 1.0


_MAX_MONTH_DAYS = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _impossible_month_day(rule) -> bool:
    """a day of the month that none of the rule's months has (30 February)"""
    days = rule._original_rule.get('bymonthday')
    if not days:
        return False  # none, or the day of DTSTART: a real date
    longest = max(_MAX_MONTH_DAYS[month - 1] for month in (rule._bymonth or range(1, 13)))
    return all(abs(day) > longest for day in days)


def _first_dates(rule, dtstart, count=100) -> list:
    """the first dates of a rule, within CHECK_YEARS

    dateutil only stops at UNTIL once it found a date: an impossible rule
    (30 February) is searched until the year 9999, taking seconds. The search
    runs in a thread, so that it doesn't block the bot past CHECK_TIMEOUT
    (the thread finishes on its own).

    Raises:
        TimeoutError: no answer within CHECK_TIMEOUT
    """
    horizon = dtstart + relativedelta(years=CHECK_YEARS)
    probe = rule.replace(count=None, until=min(rule._until, horizon) if rule._until else horizon)
    result = {}

    def search():
        try:
            result['dates'] = list(itertools.islice(probe, count))
        except Exception as e:
            result['error'] = e

    worker = threading.Thread(target=search, name='rule-check', daemon=True)
    worker.start()
    worker.join(CHECK_TIMEOUT)
    if worker.is_alive():
        raise TimeoutError()
    if 'error' in result:
        raise result['error']
    return result['dates']

# where a property starts, also when glued to the previous one ('...ZRRULE:FREQ=...')
_PROPERTY_START_RE = re.compile(r'(?=(?:DTSTART|RRULE|EXRULE|RDATE|EXDATE)[:;])', re.IGNORECASE)


def _split_properties(rrule_str: str) -> str:
    """the rule text with one property per line

    dateutil accepts properties separated by spaces, but the DTSTART and UNTIL
    handling here reads the text line by line
    """
    parts = []
    for token in rrule_str.split():
        parts.extend(part for part in _PROPERTY_START_RE.split(token) if part)
    return '\n'.join(parts)


def rrule_normalize(rrule_str, dtstart, tz_str='UTC'):
    """generate the rrule of the given rrule string
       in the rule frame: naive datetimes in the local time of the server/user

    Args:
        rrule_str (str): the rule, e.g. 'FREQ=WEEKLY;BYDAY=FR;UNTIL=20261231T230000Z'
        dtstart (datetime): start date of repeat, naive local date of the server/user
        tz_str (str): timezone of the server/user, used to convert an UTC UNTIL

    Returns:
        (rule, str): normalized rule, None on failure, error string
    """

    if 'interval=0' in rrule_str.lower():
        return (None, 'Please specify an interval greater than 0')

    # the popup field is a single line: pasted line breaks arrive as spaces (or not at all)
    rrule_str = _split_properties(rrule_str)

    try:
        rrule_str, own_start = _split_dtstart(rrule_str, tz_str)
    except ValueError as e:
        return None, str(e)
    if own_start:
        dtstart = own_start

    # to the minute: an occurrence at 20:15:27 would never match an exception date at 20:15
    dtstart = timeutil.to_minute(dtstart)

    rule_str, until = _split_until(rrule_str, tz_str)

    try:
        rule = rr.rrulestr(rule_str, dtstart=dtstart, ignoretz=True)
        if 'bysecond' in rule_str.lower():
            rule = rule.replace(bysecond=0)
    except Exception as e:
        return None, str(e)

    if rule._dtstart is not None and rule._dtstart.tzinfo is not None:
        # the rule frame is naive local time
        return None, 'Unsupported DTSTART: use e.g. `DTSTART:20261110T090000Z` or `DTSTART;TZID=Europe/Paris:20261110T090000`'

    if until:
        try:
            rule = rule.replace(until=until)
        except Exception as e:
            # e.g. UNTIL together with COUNT
            return None, str(e)


    norm_str = str(rule).lower()

    if 'minutely' in norm_str:
        return (None, 'Minutely repetitions are not supported by this bot (yet)')
    elif 'secondly' in norm_str:
        return (None, 'Secondly repetitions would be classified as spam by the discord TOS.')

    if _impossible_month_day(rule):
        return (None, 'This repetition has no date: none of its months has that day')

    try:
        dates = _first_dates(rule, dtstart)
    except TimeoutError:
        return (None, 'This repetition takes too long to check, it may have no date at all')
    except Exception as e:
        return None, str(e)

    if not dates:
        return (None, f'This repetition has no date in the future (checked {CHECK_YEARS} years)')

    # not more often than MIN_REPEAT_GAP, also with a list (FREQ=HOURLY;BYMINUTE=0,5,10,...)
    for previous, occurrence in zip(dates, dates[1:]):
        if occurrence - previous < MIN_REPEAT_GAP:
            return (None, f'A reminder can repeat every {int(MIN_REPEAT_GAP.total_seconds() // 60)} minutes at most')

    return rule, None
