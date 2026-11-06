import re
from datetime import datetime

import discord
from dateutil import tz
from pytz import common_timezones


def timezone_hints(name: str) -> str:
    """advice for timezone names that don't follow daylight saving or are deprecated"""
    if re.match(r'^UTC\+\d+$', name):
        return '\n• Consider using your local timezone (instead of `UTC+X`), in order to automatically adjust to daylight-saving*'
    elif name.lower() == 'mst':
        return '\n• Consider using `MST7MDT` to respect daylight saving during winter'
    elif name.lower() == 'est':
        return '\n• Consider using `EST5EDT` to respect daylight saving during winter'
    elif name not in common_timezones:
        return f'\n• `{name}` seems to be a deprecated timezone and could be discontinued in future versions.\n'\
               f'• Try and use a geo-referenced timezone that _observes_ `{name}` instead (e.g. `Europe/Berlin`)'
    return ''


def timezone_embed(name: str, title: str, intro: str, outro: str = '') -> discord.Embed:
    """describe a timezone: offset, current local time and hints

    Args:
        name (str): IANA name of the timezone
        title (str): embed title, the timezone name is appended
        intro (str): start of the description, followed by the timezone name
        outro (str, optional): text appended after the hints
    """
    now = datetime.now(tz.gettz(name))
    hints = timezone_hints(name)

    # green without hints, slightly yellow with non-critical hints
    color = 0xcceb67 if hints else 0x69eb67

    # the title must not exceed 256 chars
    return discord.Embed(title=f'{title} {name}'[:256],
                         color=color,
                         description=f'{intro} `{name}` (`UTC{now.strftime("%z")}`)\n'
                                     f'This corresponds to a local time of `{now.strftime("%H:%M")}`\n'
                                     f'{hints}{outro}')
