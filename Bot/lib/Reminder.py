import discord # for reminder
import heapq
import re
import itertools
from dateutil import tz
import dateutil.rrule as rr

import logging

import lib.input_parser
import lib.text
from lib.i18n import tr, hints, plural
import lib.timeutil as timeutil
from lib.timeutil import utc_timestamp, utc_from_timestamp  # noqa: F401 (re-exported)
import lib.Connector  # KEEP this syntax, circular import

# the 🔁 before the footer of repeating reminders: Twemoji, from a CDN copy of a
# fixed version (the Emojipedia URL used before is gone)
REPEAT_ICON_URL = 'https://cdn.jsdelivr.net/gh/jdecked/twemoji@15.1.0/assets/72x72/1f501.png'
# how many next dates are shown for a repeating reminder or a new rule
UPCOMING_COUNT = 5
# dates looked at past 'now' before giving up: exception rules that remove every
# date of an endless rule would otherwise make the search run until year 9999
SEARCH_LIMIT = 10_000


log = logging.getLogger('Remindme.Reminder')




class Reminder:

    def __init__(self, json = {}):
        if not json:
            json = {}

        self.msg = json.get('msg', None)
        self.title = json.get('title', None)
        self.img_url = json.get('img_url', None)

        self._id = json.get('_id', None)

        g_id = json.get('g_id', None)
        self.g_id = int(g_id) if g_id else None

        ch_id = json.get('ch_id', None)
        self.ch_id = int(ch_id) if ch_id else None

        target = json.get('target', None)
        self.target = int(target) if target else None

        self.target_mention = json.get('target_mention', None)
        self.target_name = json.get('target_name', None)
        self.ch_name = json.get('ch_name', None)
        # a server reminder sent to its member by DM (its channel stays the fallback)
        self.by_dm = json.get('by_dm', False)
        # the date it was due, when it is sent late (not stored)
        self.late_due_at = None
        # the language of its author ('en', 'fr'): of what the bot sends later
        self.lang = json.get('lang', 'en')

        author = json.get('author', None)
        self.author = int(author) if author else None

        last_msg_id = json.get('last_msg_id', None)
        self.last_msg_id = int(last_msg_id) if last_msg_id else None

        self.at = json.get('at', None)
        if self.at:
            self.at = utc_from_timestamp(self.at)

        self.created_at = json.get('created_at', None)
        if self.created_at:
            self.created_at = utc_from_timestamp(self.created_at)


    def __eq__(self, other):
        # equals allows None
        return self.at == other.at

    def __lt__(self, other):
        return (self.at or timeutil.utcnow()) < (other.at or timeutil.utcnow())

    def __le__(self, other):
        return (self.at or timeutil.utcnow()) <= (other.at or timeutil.utcnow())

    def __gt__(self, other):
        return (self.at or timeutil.utcnow()) > (other.at or timeutil.utcnow())

    def __ge__(self, other):
        return (self.at or timeutil.utcnow()) >= (other.at or timeutil.utcnow())

    def __ne__(self, other):
        # unequals allows None
        return self.at != other.at


    def _to_json(self):
        d = dict()

        d['msg'] = self.msg


        d['title'] = self.title if self.title else None
        d['img_url'] = self.img_url if self.img_url else None
        d['g_id'] = str(self.g_id) if self.g_id else None
        d['ch_id'] = str(self.ch_id) if self.ch_id else None
        d['target'] = str(self.target) if self.target else None
        d['target_mention'] = self.target_mention
        d['target_name'] = self.target_name
        d['ch_name'] = self.ch_name
        d['by_dm'] = self.by_dm
        d['lang'] = self.lang
        d['author'] = str(self.author) if self.author else None
        d['last_msg_id'] = str(self.last_msg_id) if self.last_msg_id else None
        
        if self.created_at:
            d['created_at'] = utc_timestamp(self.created_at)

        if self.at:
            d['at'] = utc_timestamp(self.at)
        else:
            d['at'] = None

        return d


    
    def get_interval_string(self, now=None, use_timestamp=False, lang=None):
        """get a string describing the interval until reminder is triggered
           if self.at is None, returns verbose string showing no future occurrence

        Returns:
            [str]: [description]
        """

        lang = lang or self.lang
        if not self.at:
            return tr(lang, 'No future occurrence')
        
        if not now:
            now = timeutil.utcnow()  
            
            
        if use_timestamp:
            at = self.at.replace(tzinfo=tz.UTC)
            return f'<t:{int(at.timestamp())}:R>'
          
        delta = self.at - now
        total_secs = int(max(0, delta.total_seconds()))

        hours, rem = divmod(total_secs, 3600)
        mins = rem // 60
        
        days, rem = divmod(total_secs, 3600*24)
        hour_days = int(rem/3600)
        
        weeks, rem = divmod(total_secs, 3600*24*7)
        days_weeks = int(rem/(3600*24))
        
        years, rem = divmod(total_secs, 3600*24*365)
        weeks_years = int(rem/(3600*24*7))


        if weeks > 104:
            text = tr(lang, '{y} years and {w} weeks', y=years, w=weeks_years)
        elif weeks > 10:
            text = tr(lang, '{w} weeks and {d} days', w=weeks, d=days_weeks)
        elif days > 14:
            text = tr(lang, '{d} days and {h} hours', d=days, h=hour_days)
        elif hours > 48:
            text = tr(lang, '{d} days ({h} hours)', d=int(hours/24), h=f'{int(hours):02d}')
        elif hours > 0:
            text = tr(lang, '{h} h {m} m', h=f'{int(hours):02d}', m=f'{int(mins):02d}')
        else:
            text = tr(lang, '{m} minutes', m=int(mins))
        return plural(lang, text)


    async def get_string(self, client=None, is_dm=False, barebone=False, lang=None):
        """return string description of this reminder

        Args:
            is_dm (bool, optional): deprecated, is ignored

        Returns:
            [type]: [description]
        """

        lang = lang or self.lang
        # only get the author object
        # if the author is actually required
        author = None
        if self.author != self.target:
            try:
                author = await client.fetch_user(self.author)
            except discord.errors.NotFound:
                pass

        if not is_dm:
            out_str = self.target_mention or f'<@!{self.target}>'
        else:
            out_str = ''

        if barebone:
            out_str += f' {self.msg}'
        else:
            if self.target == self.author:
                out_str += f' {self.msg}'
            elif author:
                out_str += ' ' + tr(lang, '{text} (by {name})', text=self.msg, name=author.display_name)
            else:
                out_str += ' ' + tr(lang, '{text} (by {name})', text=self.msg, name=f'<@!{self.author}>')

            if self.img_url:
                out_str += f'\n{self.img_url}'
            if self.late_due_at:
                out_str += f'\n⏰ {self.late_text(lang)}'

        return out_str


    def _get_embed_body(self, title, author=None, tz_str='UTC', lang=None):
        # Discord refuses embeds with a longer description
        eb = discord.Embed(title=title, description=lib.text.shorten(f'{self.msg}', lib.text.MAX_DESCRIPTION), color=0xe4ff1e)

        if self.created_at:
            # Discord shows the embed timestamp in each viewer's local time
            # (a naive value would be read in the machine timezone)
            eb.timestamp = self.created_at.replace(tzinfo=tz.UTC)
            eb.set_footer(text=tr(lang or self.lang, 'created: '))

        if author:
            avatar_url = author.avatar.url if author.avatar else author.default_avatar.url
            eb.set_author(name=author.display_name, icon_url=avatar_url)
        elif self.target != self.author:
            # fallback if author couldn't be determined
            eb.add_field(name=tr(lang or self.lang, 'by'), value=f'<@!{self.author}>', inline=False)

        return eb
    

    def get_tiny_embed(self, title=None, now=None, info:str=None, rrule_override=None, lang=None):
        """return a tiny info embed of the reminder
           used upon reminder creation, to not bloat main chat
           Show interval till next/first trigger
           
           rrule_override is ignored

        Returns:
            [type]: [description]
        """

        lang = lang or self.lang
        title = title or tr(lang, 'New Reminder Created')
        if not now:
            now = timeutil.utcnow()

        at_utc = self.at.replace(tzinfo=tz.UTC)
        when = f'<t:{int(at_utc.timestamp())}:R>'
        if self.target == self.author:
            description = tr(lang, 'Reminding you {when}', when=when)
        else:
            description = tr(lang, 'Reminding {target} {when}', target=self.target_name or f'<@!{self.target}>', when=when)

        if info:
            description += f'\n```{tr(lang, "Parsing hints")}:\n{hints(lang, info)}```'
    
        eb = discord.Embed(title=title, description=description, color=0x409fe2)
        eb.timestamp = at_utc

        return eb


    def is_for_a_member(self) -> bool:
        """for one member (it can go by DM), not a role or @everyone"""
        return bool(re.fullmatch(r'<@!?\d+>', self.target_mention or f'<@{self.target}>'))


    def late_text(self, lang=None) -> str:
        """why it comes late, '' when it is on time"""
        if not self.late_due_at:
            return ''
        ts = int(utc_timestamp(self.late_due_at))
        return tr(lang or self.lang, 'Due <t:{ts}:f> (<t:{ts}:R>): the bot couldn\'t send it on time.', ts=ts)


    def mentioned_ids(self) -> set:
        """the members mentioned in the title or the text (not the roles)"""
        return {int(uid) for uid in re.findall(r'<@!?(\d+)>', f'{self.title or ""} {self.msg or ""}')}


    def get_info_embed(self, tz_str='UTC', title=None, lang=None):
        """return info embed of this reminders
           used for reminder management.
           Shows due-date, instead of link to channel

        Returns:
            [type]: [description]
        """

        lang = lang or self.lang
        eb = self._get_embed_body(title or tr(lang, 'Reminder Info'), tz_str=tz_str, lang=lang)
        eb.color = 0x409fe2


        if self.author != self.target:
            eb.add_field(name=tr(lang, 'Target user/role'), value=self.target_name or f'<@!{self.target}>')

        if self.at:
            at_utc = self.at.replace(tzinfo=tz.UTC)
            at_ts = int(at_utc.timestamp())
            at_str = f'<t:{at_ts}> <t:{at_ts}:R>'
        else:
            at_str = f'`{tr(lang, "No future occurrences")}`'

        eb.add_field(name=tr(lang, 'Due date'), value=at_str, inline=False)

        return eb


    async def get_embed(self, client, is_dm=False, tz_str='UTC', lang=None):
        """return embed of this reminders
           will resolve user mentions.
           Used for elapsed reminders

        Args:
            client ([type]): bot client object, for resolving user names
            is_dm (bool, optional): legacy, is ignored

        Returns:
            discord.Embed: embed of reminder
        """
        lang = lang or self.lang

        if self.target != self.author:
            try:
                author = await client.fetch_user(self.author)
                title = tr(lang, 'Reminds you')
            except discord.errors.NotFound:
                author = None
                title = tr(lang, 'Reminder')
        else:
            author = None
            title = tr(lang, 'Reminder')
        if self.title:
            # its own title (the author shows above it)
            title = lib.text.shorten(self.title, 256)

        eb = self._get_embed_body(title, author=author, tz_str=tz_str, lang=lang)

        if self.g_id and self.last_msg_id:
            url = f'https://discord.com/channels/{self.g_id}/{self.ch_id}/{self.last_msg_id}'
            eb.add_field(name='\u200B', value=f'[{tr(lang, "jump to the chat")}]({url})', inline=False)
        elif self.last_msg_id:
            # private dm
            url = f'https://discord.com/channels/@me/9/{self.last_msg_id}'
            eb.add_field(name='\u200B', value=f'[{tr(lang, "jump to the chat")}]({url})', inline=False)

        if self.late_due_at:
            eb.add_field(name=tr(lang, '⏰ Sent late'), value=self.late_text(lang), inline=False)

        if self.img_url:
            eb.set_image(url=self.img_url)
            eb.set_footer(text=tr(lang, '*Images are provided by the author*, created: '))

        return eb


    def get_embed_text(self, is_dm=False):
        """returns a short text intented to be sent in combination 
           with the get_embed
           
           holds a mention for the user/role and the beginning of the reminder message
        """
        
        if not is_dm:
            tmp = self.target_mention or f'<@{self.target}>'
        else:
            tmp = ''

        tmp += ' '

        content = self.title or self.msg
        tmp += content if len(content) < 100 else f'{content[0:100]} [...]'

        return tmp

class IntervalReminder(Reminder):
    
    def __init__(self, json = {}):
        if not json:
            json = {}

        super().__init__(json)


        self.first_at = json.get('first_at', None)
        if self.first_at:
            # first_at is in the rule frame (server local time), stored like the UTC values
            self.first_at = utc_from_timestamp(self.first_at)

        self.exdates = json.get('exdates', [])
        self.exrules = json.get('exrules', [])
        self.rdates = json.get('rdates', [])
        self.rrules = json.get('rrules', [])
        # a paused interval keeps its schedule but is not delivered
        self.paused = json.get('paused', False)


    def _to_json(self):
        d = super()._to_json()

        d['exdates'] = self.exdates
        d['exrules'] = self.exrules
        d['rdates'] = self.rdates
        d['rrules'] = self.rrules

        if self.first_at:
            d['first_at'] = utc_timestamp(self.first_at)

        d['paused'] = self.paused

        return d


    def upcoming(self, count=UPCOMING_COUNT, tz_str=None) -> list:
        """the next occurrences (naive UTC), starting with .at"""
        if not self.at:
            return []
        # one pass: each search replays the rules from their start
        return [self.at] + list(itertools.islice(self._occurrences(self.at, tz_str), max(count - 1, 0)))


    def add_upcoming_field(self, eb: discord.Embed, tz_str=None, lang=None):
        """add the next occurrences to the embed, to check the rules at a glance

        Args:
            tz_str: the timezone of the rules, default: the server's (the user's in DMs)
        """
        dates = self.upcoming(UPCOMING_COUNT, tz_str=tz_str)
        if not dates:
            return
        lines = [f'<t:{int(utc_timestamp(d))}:F>' for d in dates]
        name = 'Next occurrences (paused, not delivered)' if self.paused else 'Next occurrences'
        name = tr(lang or self.lang, name)
        eb.add_field(name=name, value='\n'.join(lines), inline=False)


    def get_tiny_embed(self, title=None, now=None, info:str=None, rrule_override=None, lang=None):
        """return a tiny info embed of the reminder
           used upon reminder creation, to not bloat main chat
           Show interval till next/first trigger

        Returns:
            [type]: [description]
        """

        lang = lang or self.lang
        title = title or tr(lang, 'New Interval Created')
        if not now:
            now = timeutil.utcnow()

        when = self.get_interval_string(now, use_timestamp=True, lang=lang)
        if self.target == self.author:
            description = tr(lang, 'Reminding you the first time {when}', when=when)
        else:
            description = tr(lang, 'Reminding {target} the first time {when}',
                             target=self.target_name or f'<@!{self.target}>', when=when)
        description += tr(lang, '\n\nCall `/reminder_list` to edit all pending reminders')

        if info:
            description += f'\n```{tr(lang, "Parsing hints")}:\n{hints(lang, info)}```'

        eb = discord.Embed(title=title, description=description, color=0x409fe2)
        self.add_upcoming_field(eb, lang=lang)
        
        
        if rrule_override:
            rrule = rrule_override
        elif self.rrules:
            rule_str = self.rrules[0]
            rrule = rr.rrulestr(rule_str)
        else:
            rrule = None

        if rrule:
            interval_txt = lib.input_parser.rule_text(rrule, lang, now=now)
        else:
            interval_txt = '\u200b'

        eb.set_footer(text=interval_txt, icon_url=REPEAT_ICON_URL)
        
        return eb


    def get_info_embed(self, tz_str='UTC', title=None, lang=None):
        """return info embed of this reminders
           used for reminder management.
           Shows due-date, instead of link to channel

        Returns:
            [type]: [description]
        """
        lang = lang or self.lang
        eb = super().get_info_embed(tz_str=tz_str, title=title or tr(lang, 'Interval Info'), lang=lang)
        eb.timestamp = None
        # the rules are in the timezone of the server, whatever the display timezone
        self.add_upcoming_field(eb, lang=lang)

        in_str = self.get_interval_string(lang=lang)
        prefix = 'Next in ' if self.at else ''
        if self.paused:
            prefix = 'Paused, next in ' if self.at else 'Paused, '
        prefix = tr(lang, prefix) if prefix else ''
        
        eb.set_footer(text=f'{prefix}{in_str}', icon_url=REPEAT_ICON_URL)

        return eb


    async def get_embed(self, client, is_dm=False, tz_str='UTC', lang=None):
        """return embed of this reminders
           will resolve user mentions.
           Used for elapsed reminders

        Args:
            client ([type]): bot client object, for resolving user names
            is_dm (bool, optional): legacy, is ignored

        Returns:
            discord.Embed: embed of reminder
        """
        
        lang = lang or self.lang
        eb = await super().get_embed(client, is_dm, tz_str, lang=lang)

        
        if self.img_url:
            disclaimer = tr(lang, '*Images are provided by the author*')
        else:
            disclaimer = ''

        in_str = self.get_interval_string(lang=lang)
        prefix = tr(lang, 'Next in ') if self.at else ''
        postfix = f', {disclaimer}' if disclaimer else ''
        
        eb.set_footer(text=f'{prefix}{in_str}{postfix}', icon_url=REPEAT_ICON_URL)
        
        return eb


    def get_rule_cnt(self):
        """return the amount of rules
           saved for this reminder

        Returns:
            int: number of rules
        """

        return len(self.rrules) + len(self.exrules) +\
                len(self.rdates) + len(self.exdates)


    def get_rule_dicts(self, lang=None) -> list:
        """get a list of dictionaries
           each describing a set rule (or exclusion)

           'label': is a short title of the rule
           'descr': is more descriptive about the rule
        """

        ret = []

        for rule in self.rrules:
            ret.append({'label': tr(lang or self.lang, 'Repeating rule'),
                        'descr': lib.input_parser.rule_text(rule, lang or self.lang)[0:100], 'default': False})

        for rule in self.exrules:
            ret.append({'label': tr(lang or self.lang, 'Exception rule'),
                        'descr': lib.input_parser.rule_text(rule, lang or self.lang)[0:100], 'default': False})

        for date in self.rdates:
            ret.append({'label': tr(lang or self.lang, 'Single date'), 'descr': date.strftime('%Y-%m-%d %H:%M'), 'default': False})

        for date in self.exdates:
            ret.append({'label': tr(lang or self.lang, 'Exception date'), 'descr': date.strftime('%Y-%m-%d %H:%M'), 'default': False})
        
        return ret


    def _local_occurrences(self, local_after):
        """the dates after local_after, in the rule frame (local time), in order
           and without duplicates; ends after SEARCH_LIMIT candidates
        """

        def valid_rule(rule_str):
            if 'interval=0' in rule_str.lower():
                log.warning(f'rrule {rule_str} has a zero interval, ignored')
                return False
            return True

        def to_minute_rule(rule_str):
            # rules saved before the minute rounding may start at e.g. 20:15:27
            rule = rr.rrulestr(rule_str)
            start = rule._dtstart
            if start and (start.second or start.microsecond):
                rule = rule.replace(dtstart=timeutil.to_minute(start))
            return rule

        # everything to the minute, so that exception dates match the occurrences.
        # The date of the initial remindme is always included
        dates = sorted(timeutil.to_minute(d) for d in [self.first_at, *self.rdates] if d)
        sources = [(d for d in dates if d > local_after)]
        sources += [to_minute_rule(r).xafter(local_after) for r in self.rrules if valid_rule(r)]
        excluded = heapq.merge(*(to_minute_rule(r).xafter(local_after) for r in self.exrules if valid_rule(r)))
        exdates = {timeutil.to_minute(d) for d in self.exdates}

        try:
            next_excluded = next(excluded, None)
            last = None
            for checked, date in enumerate(heapq.merge(*sources)):
                if checked >= SEARCH_LIMIT:
                    log.warning(f'interval {self._id}: no date in the next {SEARCH_LIMIT} candidates, giving up')
                    return
                if date == last:
                    continue
                last = date
                while next_excluded is not None and next_excluded < date:
                    next_excluded = next(excluded, None)
                if date != next_excluded and date not in exdates:
                    yield date
        except (ValueError, OverflowError):
            # a rule went past year 9999
            log.warning(f'interval {self._id}: no date before year 9999, giving up')


    def _occurrences(self, utcnow, tz_str=None):
        """the dates after utcnow, as naive UTC, in order"""
        if not tz_str:
            instance_id = self.g_id if self.g_id else self.author
            tz_str = lib.Connector.Connector.get_timezone(instance_id)

        # the rules are in the local time of the server (or user, in DMs):
        # find the next events in local time, then convert them back to UTC
        local_tz = tz.gettz(tz_str)
        local_now = utcnow.replace(tzinfo=tz.UTC).astimezone(local_tz).replace(tzinfo=None)

        for local_next in self._local_occurrences(local_now):
            utc_next = local_next.replace(tzinfo=local_tz).astimezone(tz.UTC).replace(tzinfo=None)
            # a local time that happens twice (end of daylight saving time) is read
            # as its first pass: when now is in the second pass, the first one is over.
            # Don't send it again, move on to the next occurrence
            if utc_next > utcnow:
                yield utc_next


    def next_trigger(self, utcnow, tz_str=None):
        """the next date after utcnow (naive UTC), None if there is none"""
        return next(self._occurrences(utcnow, tz_str), None)
