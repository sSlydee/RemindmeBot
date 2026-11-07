# Remindme Bot (personal fork)

A Discord bot to set reminders with slash commands, inspired by the reddit remindme bot.

This repository is a **self-hosted, personal fork** of
[Mayerch1/RemindmeBot](https://github.com/Mayerch1/RemindmeBot). It is not the
public bot of the original author: to use it, run your own instance (see
[Self-hosting](#self-hosting)).

* Create as many reminders as you want
* Repeating reminders (`every friday at 20:15`) and complex patterns (iCalendar RRULE, RFC 5545)
* See the date being typed: `/remindme time: friday 18:30` suggests `Fri 13 Nov 18:30 (in 6 days)`
* Remind other users and roles
* Per-server timezone (per-user in DMs), with daylight saving
* Snooze delivered reminders (10 min, 1 hour, tomorrow 9:00 or any time), skip the
  next date of repeating ones, edit them with `/reminder_list`, pause them
* Install it on your Discord account to use `/remindme` everywhere, even where the bot is not

<img src="res/remindme.gif" alt="Create a reminder">

<img src="res/remindInterval.gif" alt="Create an interval"/>


## Differences with the original bot

Removed, as a personal bot does not need them:
* statistics (Prometheus metrics server), top.gg server count, sharding
* community mode (moderator roles and per-feature restrictions):
  changing the server settings (`/settings`, `/timezone`) needs the
  **Manage Server** permission
* legacy UTC intervals and the experimental settings page

Fixed or added:
* repeating reminders keep their local time when built with the buttons,
  and `UNTIL` in UTC is accepted in repeating rules
* repeating rules without RRULE: a *Quick repeat* menu and natural language
  (`every friday at 7`); the next three dates are shown, and repeating
  reminders can be paused
* user install: `/remindme` everywhere, delivered by DM
* reminders are deleted only after their delivery attempt,
  and the delivery loops survive database errors
* snooze counts from the click and keeps the whole message; more snooze
  choices, and the buttons under delivered reminders (also in DMs) keep
  working after a restart, for 7 days
* skip the next date of a repeating reminder, from the delivered message or
  `/reminder_list`
* the date read from `time` is shown while typing it (`/remindme`, `/remind`)
* editing a reminder's date (`/remindme` syntax) and image works
* native Discord channel picker, many interaction fixes
* timestamps independent of the machine timezone
* rotating log file, optional [Uptime Kuma](https://github.com/louislam/uptime-kuma) heartbeat
* unit tests on GitHub Actions


## Some users cannot use the bot?


### Permissions
Make sure the user has sufficient permission to execute **Application Commands** (`slash-commands` in earlier versions).
This permission can be used to restrict access to bots, but is usually enabled for @everyone by default

<img src="res/slashPermissions.jpg" alt="Application command permissions">

### User Settings
If the permissions are all set, but certain users are still not able to use slash-commands, the discord application might be setup incorrectly. Tell the affected user(s) to open their `user settings` and navigate to the `Text & images` section.

In the lower part of said settings page, you can find an option to toggle the usage of slash-commands.
<img src="res/slashSettings.jpg" alt="User settings">



Make sure the user has the permission to `Use Application commands`.
This is a recently introduced discord permission, and can control the access to bot commands.
By default `@everyone` is allowed to use `slash`-commands.


## Create Repeating intervals

There's two ways of setting interval reminders. Through natural language, or by directly inputting `rrules` based on `rfc5545`.

### Natural Language

Create a reminder with `/remindme` or `/remind` and specify the interval as natural language when setting the `time` argument.
This could be e.g. `every week` or `first monday each month` or `every friday at 20`.

### Inputting Rules

Create a "normal" interval with `/remindme` or `/remind` and set the `time` argument to be the first occurrence of your repeating event.
You can then press the `Set Interval` button to add repeating rules for the event.

The bot supports the full `rfc5545`-spec and allows the combination of up to 25 independent rules to define your custom repeating patterns and to add exception rules.

## Commands

|Commands||
|---|---|
|```remindme <time> <message>```  | reminds you after the given `<time>` period| 
|```remind <mentionable> <time> <message>``` | reminds another user/role after the given `<time>` period|
|```reminder_list``` | manage your reminders for this server (only visible to you) |
|```settings``` | show and change the server settings (changes need **Manage Server**) |
|```timezone <timezone>``` | set the timezone of your server using a [time zone defined by IANA](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones#List), defaults to UTC (needs **Manage Server**; in DMs it sets your own timezone)|
|```help``` | show the help page for this bot |


### Examples

```
/remindme 1y Hello future me
/remindme 2years This is a long time
/remindme 2 h drink some water
/remindme eow Buy groceries
/remindme 5 m Whatever
/remindme 2 aug 3pm Is it hot outside?
/remindme 2021-09-02T12:25:00+02:00 iso is cool

/remind @User 1 mon What's up
/remind @Role 24 dec Merry Christmas
/remind @everyone eoy Happy new year

/remindme every friday at 20:15 do stuff
/remind @User every year at 1st july happy birthday

/timezone Australia/Melbourne
```

## Time parsing

The time parser allows multiple formats for specifying the reminder period.

At the moment, different parameters cannot be combined.

```
	allowed absolutes are
		• eoy - remind at end of year
		• eom - remind at end of month
		• eow - remind at end of working week (Friday night)
		• eod - remind at end of day
	
	allowed intervals are
		• y(ears)
		• mo(nths)
		• w(eeks)
		• d(ays)
		• h(ours)
		• m(ins)
	
	you can combine relative intervals like this
		1y 1mo 2 days -5h

	iso-timestamps are supported
		be aware that specifying a timezone will ignore the server timezone
	
	dates are supported, you can try different formats
		• 5 jul, 5th july, july 5
		• 23 sept at 3pm, 23 sept at 15:00
		• 2030

	Note: the parser uses day-first and year-least
	      (01/02/03 -> 1st February 2003)

	the reminder can occur as much as 1 minute delayed
```


### Note
The correct plural of the time interval does not matter
`/remindme 1 weeks Hey` is just as valid as `/remindme 2 week Ho`


## Self-hosting

### Requirements
* Python 3.11 or newer (tested on 3.11 and 3.13)
* MongoDB (any recent version, with authentication)
* A Discord application with a bot user
  ([Developer Portal](https://discord.com/developers/applications)), no privileged intent needed

### Install
```bash
git clone --recurse-submodules https://github.com/sSlydee/RemindmeBot.git
cd RemindmeBot
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```
The `--recurse-submodules` is required: the natural language parser lives in
the `Bot/lib/recurrent` submodule.

### Configuration
The bot reads its configuration from environment variables:

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | yes | token of the Discord bot |
| `MONGO_CONN` | yes | MongoDB host, e.g. `127.0.0.1` |
| `MONGO_PORT` | yes | MongoDB port, e.g. `27017` |
| `MONGO_ROOT_USER` | yes | MongoDB user (authenticated against `admin`) |
| `MONGO_ROOT_PASS` | yes | MongoDB password |
| `LOG_LEVEL` | no | log level of the bot, `INFO` (default) or `DEBUG` |
| `LOG_FILE` | no | log file, default `logs/bot.log` (relative to `Bot/`), rotated at 5 MB |
| `UPTIME_KUMA_PUSH_URL` | no | push URL of an Uptime Kuma *Push* monitor: each successful delivery run sends a heartbeat |

The data is stored in the `reminderBot` database.

### Run
```bash
cd Bot
set -a; . ../.env; set +a   # or any other way to set the variables above
../.venv/bin/python remindmeBot.py
```
To keep it running, use a service manager (for example a systemd service with
`WorkingDirectory=.../Bot`, `EnvironmentFile=.../.env` and `Restart=on-failure`).

The `Dockerfile` and `docker-compose.yml` come from the original project and
are not tested in this fork.

### Invite the bot
Replace `CLIENT_ID` with the application id of your bot:
```
https://discord.com/oauth2/authorize?client_id=CLIENT_ID&permissions=274877991936&scope=bot%20applications.commands
```
The permissions are: View Channels, Send Messages, Send Messages in Threads,
Embed Links and Read Message History. `/help` also has an *Invite Me* button
with the same link.

Set the server timezone with `/timezone` (for example `Europe/Paris`), the
default is UTC.

### Install on your account (optional)
`/remindme`, `/reminder_list` and `/timezone` can also be installed on a user
account, to use them in DMs, group DMs and servers the bot is not part of.
There, reminders are private: they are delivered by DM, with the user's own
timezone (set it with `/timezone` in such a place, or in a DM with the bot), and
the bot's replies are only visible to the user.

1. In the [Developer Portal](https://discord.com/developers/applications),
   *Installation*: tick **User Install**, and add the `applications.commands`
   scope to its default install settings.
2. Open this link and choose *Add to My Apps*:
   ```
   https://discord.com/oauth2/authorize?client_id=CLIENT_ID&integration_type=1&scope=applications.commands
   ```

The bot must be able to send you DMs (for example by sharing a server with you).


## Development

Run the unit tests from the repository root:
```bash
.venv/bin/python -m unittest discover -s unit_tests -t . -p '*Test.py'
```
They run on GitHub Actions on every push (Python 3.11 and 3.13).

The menu tests (`unit_tests/MenuFlowTest.py`) click through the menus on a small
stand-in for Discord (`unit_tests/fakediscord.py`) with an in-memory database.
They need `mongomock` (`.venv/bin/pip install mongomock`) and are skipped without it.


## Credits

Original bot by [Mayerch1](https://github.com/Mayerch1/RemindmeBot).
