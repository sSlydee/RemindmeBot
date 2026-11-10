"""What members whose Discord is in French see (lib.i18n); English stays the default

The tests use an in-memory database (mongomock) and fakediscord.py.
"""
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

try:
    import mongomock
except ImportError:  # pragma: no cover
    mongomock = None

import cogs.ReminderCreation as creation
from cogs.ReminderCreation import ReminderCreation, describe_time
from cogs.ReminderListing import ReminderListing
from cogs.SettingsModule import SettingsModule
from cogs.TimezoneModule import TimezoneModule
from discord.ext.help.help import Help
import lib.i18n as i18n
import lib.timeutil as timeutil
from lib.Connector import Connector
from lib.Reminder import Reminder, IntervalReminder
import util.notices
import util.reminderButtons as buttons
from unit_tests.CreationTest import FakeContext
from unit_tests.fakediscord import FakeDiscord, OWNER, STRANGER

GUILD = 1
NOW = datetime(2026, 11, 10, 13, 0)  # Tuesday 14:00 in Paris


class LanguageTest(unittest.TestCase):

    def test_language_of_the_user(self):
        self.assertEqual(i18n.lang_of(SimpleNamespace(locale='fr')), 'fr')
        self.assertEqual(i18n.lang_of(SimpleNamespace(interaction=SimpleNamespace(locale='fr'))), 'fr')
        for locale in ('en-US', 'en-GB', 'de', None):
            self.assertEqual(i18n.lang_of(SimpleNamespace(locale=locale)), 'en')
        self.assertEqual(i18n.lang_of(SimpleNamespace()), 'en')

    def test_english_unless_translated(self):
        self.assertEqual(i18n.tr('fr', 'Saved.'), 'Enregistré.')
        self.assertEqual(i18n.tr('en', 'Saved.'), 'Saved.')
        self.assertEqual(i18n.tr('fr', 'not in the catalogue'), 'not in the catalogue')
        self.assertEqual(i18n.tr('fr', 'Snoozed until {when}.', when='X'), 'Reporté au X.')

    def test_dates(self):
        self.assertEqual(i18n.date_str(datetime(2026, 11, 11, 8, 0), 'fr'), 'mer. 11 nov. 08:00')
        self.assertEqual(i18n.date_str(datetime(2027, 1, 4, 18, 30), 'fr', with_year=True), 'lun. 04 janv. 2027 18:30')
        self.assertEqual(i18n.date_str(datetime(2026, 11, 11, 8, 0), 'en'), 'Wed 11 Nov 08:00')

    def test_catalogue_placeholders(self):
        # every French text has the placeholders of its English text
        import re
        for en, fr in i18n.FR_TEXTS.items():
            self.assertEqual(sorted(set(re.findall(r'{(\w+)}', en))), sorted(set(re.findall(r'{(\w+)}', fr))), en)

    def test_command_descriptions(self):
        commands = [ReminderCreation.remindme, ReminderCreation.remind_user, ReminderListing.reminder_list,
                    SettingsModule.settings_menu_cmd, TimezoneModule.set_timezone_sub_cmd, Help.help]
        for command in commands:
            self.assertIn('fr', command.description_localizations or {}, command.name)
            self.assertLessEqual(len(command.description_localizations['fr']), 100, command.name)


class PreviewTest(unittest.TestCase):
    """the preview while the time is typed (the screenshot of the request)"""

    def fr(self, text):
        return describe_time(text, NOW, 'Europe/Paris', 'fr')

    def test_dates(self):
        self.assertEqual(self.fr('demain 9h'), 'mer. 11 nov. 09:00 (dans 19 h)')
        self.assertEqual(self.fr('dans 2h'), 'mar. 10 nov. 16:00 (dans 2 h)')
        self.assertEqual(self.fr('dans 10 minutes'), 'mar. 10 nov. 14:10 (dans 10 min)')
        self.assertEqual(self.fr('dans 3 jours'), 'ven. 13 nov. 14:00 (dans 3 jours)')
        self.assertEqual(self.fr('le 15 janvier à 9h'), 'ven. 15 janv. 2027 09:00 (dans 65 jours)')

    def test_repetition(self):
        self.assertEqual(self.fr('en semaine a 8h'), 'se répète, d’abord mer. 11 nov. 08:00 (dans 18 h)')

    def test_problems(self):
        self.assertEqual(self.fr('xyz'), '⚠ date illisible')
        self.assertEqual(self.fr('1 jan 2020'), '⚠ cette date est passée')

    def test_english_unchanged(self):
        self.assertEqual(describe_time('tomorrow 9:00', NOW, 'Europe/Paris'), 'Wed 11 Nov 09:00 (in 19 h)')

    def test_examples_in_french(self):
        interaction = SimpleNamespace(locale='fr', guild_id=GUILD, user=SimpleNamespace(id=OWNER),
                                      authorizing_integration_owners=SimpleNamespace(guild_id=GUILD, user_id=None))
        with patch.object(Connector, 'get_timezone', return_value='Europe/Paris'):
            import asyncio
            choices = asyncio.run(creation.time_autocomplete(SimpleNamespace(value='', interaction=interaction)))
        self.assertEqual([c.value for c in choices], creation.TIME_EXAMPLES_FR)
        self.assertTrue(choices[1].name.startswith('demain 9h → '))


@unittest.skipUnless(mongomock, 'needs mongomock')
class CreationTest(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        Connector.db = mongomock.MongoClient().reminderBot
        Connector.set_timezone(GUILD, 'Europe/Paris')
        self.discord = FakeDiscord()
        self.ctx = FakeContext(self.discord)
        self.ctx.interaction.locale = 'fr'

    async def remindme(self, time):
        await ReminderCreation(client=None).process_reminder(self.ctx, self.ctx.author, self.ctx.author, time,
                                                             'bonjour', channel=self.ctx.channel)

    async def test_created_in_french(self):
        await self.remindme('demain à 9h')
        [doc] = list(Connector.db.reminders.find({}))
        self.assertEqual(doc['lang'], 'fr')
        eb = self.ctx.answers[-1]
        self.assertEqual(eb.title, 'Rappel créé')
        self.assertTrue(eb.description.startswith('Je te le rappelle <t:'))

    async def test_error_in_french(self):
        await self.remindme('xyz')
        eb = self.ctx.answers[-1]
        self.assertEqual(eb.title, 'Impossible de créer le rappel')
        self.assertIn('Indications', eb.description)
        self.assertIn('Aucune date dans', eb.description)
        self.assertIn('exemple simple', eb.description)
        self.assertEqual(eb.footer.text, 'Les formats d’heure sont sur la page syntax de /help.')

    async def test_english_by_default(self):
        self.ctx.interaction.locale = None
        await self.remindme('tomorrow 9:00')
        self.assertEqual(Connector.db.reminders.find_one({})['lang'], 'en')
        self.assertEqual(self.ctx.answers[-1].title, 'New Reminder Created')


class DeliveredTest(unittest.IsolatedAsyncioTestCase):
    """what the bot sends later: in the language of the author"""

    def reminder(self, **fields):
        data = {'msg': 'sortir les poubelles', 'author': '3', 'target': '3', 'lang': 'fr'}
        data.update(fields)
        rem = Reminder(data)
        rem._id = 'id'
        rem.created_at = NOW - timedelta(days=1)
        return rem

    async def test_embed(self):
        rem = self.reminder()
        rem.late_due_at = NOW
        eb = await rem.get_embed(client=None)
        self.assertEqual(eb.title, 'Rappel')
        self.assertEqual(eb.footer.text, 'créé : ')
        [late] = [f for f in eb.fields if f.name == '⏰ Envoyé en retard']
        self.assertTrue(late.value.startswith('Prévu <t:'))
        self.assertIn('⏰ Prévu', await rem.get_string())

    async def test_repeating(self):
        rem = IntervalReminder(self.reminder()._to_json())
        rem.at = timeutil.utcnow() + timedelta(days=1, hours=1)
        eb = await rem.get_embed(client=None)
        self.assertTrue(eb.footer.text.startswith('Prochain dans '), eb.footer.text)
        self.assertEqual(rem.get_interval_string(lang='fr', now=rem.at - timedelta(days=3)),
                         '3 jours (72 heures)')

    async def test_buttons(self):
        rem = self.reminder()
        labels = [item.label for item in buttons.delivered_view(rem).children]
        self.assertEqual(labels, ['+10 min', '+1 heure', 'Demain 9:00', 'Autre…'])
        rem.lang = 'en'
        labels = [item.label for item in buttons.delivered_view(rem).children]
        self.assertEqual(labels, ['+10 min', '+1 hour', 'Tomorrow 9:00', 'Other…'])


@unittest.skipUnless(mongomock, 'needs mongomock')
class ClickTest(unittest.IsolatedAsyncioTestCase):
    """the answer to a click: in the language of whoever clicked"""

    def setUp(self):
        Connector.db = mongomock.MongoClient().reminderBot
        Connector.set_timezone(GUILD, 'Europe/Paris')
        self.discord = FakeDiscord()

    def delivered(self, lang):
        rem = Reminder({'msg': 'meeting', 'g_id': str(GUILD), 'ch_id': '2', 'ch_name': 'general', 'lang': lang,
                        'author': str(OWNER), 'target': str(OWNER), 'target_mention': f'<@{OWNER}>'})
        rem.created_at = timeutil.utcnow() - timedelta(days=1)
        rem.at = timeutil.utcnow() - timedelta(minutes=1)
        rem._id = Connector.add_reminder(rem)
        Connector.archive_delivered(rem)
        msg = self.discord.new_message(ephemeral=False)
        msg.apply(view=buttons.delivered_view(rem))
        return msg

    async def test_snooze_in_french(self):
        self.discord.locale = 'fr'
        msg = self.delivered('en')
        await self.discord.press(msg, '+10 min')
        self.assertTrue(self.discord.last_message().content.startswith('Reporté au <t:'))

    async def test_copy_for_someone_else_keeps_their_language(self):
        self.discord.locale = 'fr'
        msg = self.delivered('en')
        await self.discord.press(msg, '+1 hour', user_id=STRANGER)
        [copy] = [Reminder(doc) for doc in Connector.db.reminders.find({'author': str(STRANGER)})]
        self.assertEqual(copy.lang, 'fr')
        self.assertIn('Il arrivera en MP', self.discord.last_message().content)


class NoticeTest(unittest.IsolatedAsyncioTestCase):

    async def test_author_told_in_their_language(self):
        world = FakeDiscord()
        rem = Reminder({'msg': 'réunion', 'g_id': str(GUILD), 'ch_id': '2', 'ch_name': 'general',
                        'author': str(OWNER), 'target': str(OWNER), 'lang': 'fr'})
        by = SimpleNamespace(id=STRANGER, mention=f'<@{STRANGER}>', display_name='Bob')
        self.assertTrue(await util.notices.tell_author_deleted(world.client, rem, by))
        [dm] = world.dms
        self.assertEqual(dm.embed.title, 'Ton rappel a été supprimé')
        self.assertIn('(#general sur Test)', dm.embed.description)
        self.assertIn(f'Supprimé par <@{STRANGER}> (Bob).', dm.embed.description)


if __name__ == '__main__':
    unittest.main()
