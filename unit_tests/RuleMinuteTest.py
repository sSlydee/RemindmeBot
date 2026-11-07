import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import lib.Connector
import lib.input_parser as p
import lib.text
import lib.Reminder
from lib.Reminder import IntervalReminder

TZ = 'Europe/Paris'


def _interval(first_at, rrules, exdates=()):
    rem = IntervalReminder({'msg': 'x', 'g_id': '1', 'ch_id': '2', 'author': '3', 'target': '3'})
    rem.first_at = first_at
    rem.rrules = list(rrules)
    rem.exdates = list(exdates)
    return rem


class RuleMinuteTest(unittest.TestCase):
    """repeating reminders work to the minute, so exception dates match"""

    def test_new_rule_starts_on_the_minute(self):
        # /remindme "every friday at 20:15" sent at 14:03:27.123456 (Paris)
        utcnow = datetime(2026, 11, 6, 13, 3, 27, 123456)
        text, _ = p.parse('every friday at 20:15', utcnow, TZ)
        rule, err = p.rrule_normalize(text, datetime(2026, 11, 6, 14, 3, 27, 123456), TZ)
        self.assertIsNone(err)
        self.assertIn('DTSTART:20261106T140300', str(rule))
        self.assertEqual(rule.after(datetime(2026, 11, 6, 15)), datetime(2026, 11, 6, 20, 15))

    def test_exception_date_skips_the_occurrence(self):
        utcnow = datetime(2026, 11, 6, 13, 3, 27, 123456)
        text, _ = p.parse('every friday at 20:15', utcnow, TZ)
        rule, _ = p.rrule_normalize(text, datetime(2026, 11, 6, 14, 3, 27, 123456), TZ)
        # Friday 6 Nov: today 20:15 is skipped, next is 13 Nov 20:15 Paris = 19:15 UTC
        rem = _interval(datetime(2026, 11, 6, 14, 3), [str(rule)], exdates=[datetime(2026, 11, 6, 20, 15)])
        self.assertEqual(rem.next_trigger(utcnow, tz_str=TZ), datetime(2026, 11, 13, 19, 15))

    def test_rules_saved_with_seconds_still_match(self):
        # saved before the rounding: DTSTART and first_at with seconds
        rem = _interval(datetime(2026, 11, 6, 20, 15, 27, 5),
                        ['DTSTART:20261106T201527\nRRULE:FREQ=WEEKLY;BYDAY=FR'],
                        exdates=[datetime(2026, 11, 13, 20, 15)])
        self.assertEqual(rem.next_trigger(datetime(2026, 11, 7), tz_str=TZ), datetime(2026, 11, 20, 19, 15))

    def test_first_date_can_be_skipped(self):
        rem = _interval(datetime(2026, 11, 13, 20, 15, 27, 5),
                        ['DTSTART:20261113T201527\nRRULE:FREQ=WEEKLY'],
                        exdates=[datetime(2026, 11, 13, 20, 15)])
        self.assertEqual(rem.next_trigger(datetime(2026, 11, 7), tz_str=TZ), datetime(2026, 11, 20, 19, 15))

    def test_bysecond_is_ignored(self):
        rule, err = p.rrule_normalize('freq=daily;bysecond=30', datetime(2026, 11, 6, 9, 0, 12), TZ)
        self.assertIsNone(err)
        self.assertEqual(rule.after(datetime(2026, 11, 6, 10)), datetime(2026, 11, 7, 9, 0, 0))


class DaylightSavingTest(unittest.TestCase):
    """25 Oct 2026, Paris: 03:00 CEST -> 02:00 CET, 02:00-02:59 local happens twice"""

    def setUp(self):
        rule, _ = p.rrule_normalize('freq=daily', datetime(2026, 10, 20, 2, 30), TZ)
        self.rem = _interval(datetime(2026, 10, 20, 2, 30), [str(rule)])

    def test_first_pass(self):
        # 02:10 CEST = 00:10 UTC: today 02:30 CEST = 00:30 UTC
        self.assertEqual(self.rem.next_trigger(datetime(2026, 10, 25, 0, 10), tz_str=TZ),
                         datetime(2026, 10, 25, 0, 30))

    def test_second_pass_moves_on(self):
        # 02:10 CET = 01:10 UTC: 02:30 was sent on the first pass, next is tomorrow 02:30 CET
        self.assertEqual(self.rem.next_trigger(datetime(2026, 10, 25, 1, 10), tz_str=TZ),
                         datetime(2026, 10, 26, 1, 30))

    def test_late_loop_sends_once(self):
        # the bot was down from 00:20 to 01:10 UTC, the loop runs every 45 s
        at = datetime(2026, 10, 25, 0, 30)
        now = datetime(2026, 10, 25, 1, 10)
        sent = 0
        while now < datetime(2026, 10, 25, 3):
            if at <= now:
                sent += 1
                at = self.rem.next_trigger(now, tz_str=TZ)
            now += timedelta(seconds=45)
        self.assertEqual(sent, 1)
        self.assertEqual(at, datetime(2026, 10, 26, 1, 30))

    def test_spring_forward(self):
        # 29 Mar 2027: 02:00 CET -> 03:00 CEST, 02:30 doesn't exist
        nxt = self.rem.next_trigger(datetime(2027, 3, 28, 0, 0), tz_str=TZ)
        self.assertGreater(nxt, datetime(2027, 3, 28, 0, 0))
        self.assertLessEqual(nxt, datetime(2027, 3, 28, 1, 30))


class MessageSplitTest(unittest.TestCase):

    def test_short_text_is_one_message(self):
        self.assertEqual(lib.text.split_message('hello'), ['hello'])
        self.assertEqual(lib.text.split_message(''), [''])

    def test_long_text_is_cut_at_line_breaks(self):
        text = '\n'.join(['a' * 900] * 5)
        parts = lib.text.split_message(text)
        # 2 lines per message (1801 characters), the line break between messages is dropped
        self.assertEqual([len(x) for x in parts], [1801, 1801, 900])
        self.assertEqual('\n'.join(parts), text)

    def test_text_without_spaces(self):
        parts = lib.text.split_message('x' * 4500)
        self.assertEqual([len(x) for x in parts], [2000, 2000, 500])

    def test_shorten(self):
        self.assertEqual(lib.text.shorten('abc', 5), 'abc')
        self.assertEqual(lib.text.shorten('abcdef', 4), 'abc…')

    def test_long_message_fits_in_the_embed(self):
        rem = _interval(datetime(2026, 11, 6, 20, 15), [])
        rem.msg = 'y' * 5000
        with patch.object(lib.Connector.Connector, 'get_timezone', return_value=TZ):
            eb = rem.get_info_embed(TZ)
        self.assertEqual(len(eb.description), 4096)


class IntervalFooterTest(unittest.IsolatedAsyncioTestCase):

    async def footer(self, img_url=None):
        rem = _interval(datetime(2026, 11, 6, 20, 15), ['DTSTART:20261106T201500\nRRULE:FREQ=WEEKLY'])
        rem.at = datetime(2099, 1, 1)
        rem.img_url = img_url
        return (await rem.get_embed(client=None)).footer.text

    async def test_no_trailing_comma(self):
        self.assertFalse((await self.footer()).rstrip().endswith(','))

    async def test_repeat_icon(self):
        rem = _interval(datetime(2026, 11, 6, 20, 15), ['DTSTART:20261106T201500\nRRULE:FREQ=WEEKLY'])
        rem.at = datetime(2099, 1, 1)
        with patch.object(lib.Connector.Connector, 'get_timezone', return_value=TZ):
            embeds = [await rem.get_embed(client=None), rem.get_info_embed(TZ), rem.get_tiny_embed()]
        for eb in embeds:
            self.assertEqual(eb.footer.icon_url, lib.Reminder.REPEAT_ICON_URL)

    async def test_image_disclaimer(self):
        self.assertTrue((await self.footer('https://example.com/a.png')).endswith('*Images are provided by the author*'))


if __name__ == '__main__':
    unittest.main()
