# Remindme Bot

<img src="logo.png" alt="Remindme Bot" width="96" align="right">

A Discord bot to set reminders with slash commands: one-time or repeating,
for you, another user or a role, in a channel or by DM.

This repository is a **personal, self-hosted fork** of
[Mayerch1/RemindmeBot](https://github.com/Mayerch1/RemindmeBot). It is not a
public bot you can invite: run your own instance (see [Self-hosting](#self-hosting)).

## Features

* **Plain-language times**: `in 2h`, `tomorrow 9:00`, `friday 18:30`, `24 dec at 6pm`,
  or an ISO timestamp. While you type, the bot shows how it reads it:
  `friday 18:30 → Fri 13 Nov 18:30 (in 6 days)`.
* **Repeating reminders**: `every friday at 20:15`, `every weekday at 8:30`, a
  *Quick repeat* menu, or full iCalendar rules (RRULE), with exceptions,
  extra dates, pause and *skip next*.
* **Buttons under each delivered reminder**: snooze (+10 min, +1 hour,
  tomorrow 9:00, or any time), skip the next date, delete. They keep working
  after a restart.
* **One list to manage everything**: `/reminder_list` shows your reminders
  with their dates in your own language and timezone, and lets you edit,
  move, pause or delete them.
* **Timezones** per server, or per user in DMs, with daylight saving.
* **Install it on your account** to use `/remindme` everywhere, even in DMs
  and servers the bot is not in: those reminders come by DM.

## Using the bot

### Create a reminder

```
/remindme time: in 2h  message: drink some water
/remindme time: friday 18:30  message: call the garage
/remind target: @Alex  time: tomorrow 9:00  message: the meeting moved to 10:00
/remindme time: every monday at 9:00  message: weekly report
```

`/remindme` reminds you, `/remind` reminds another user or a role. The reply
shows when the reminder will come, with three buttons: **Set Interval** (make
it repeat), **Edit** and 🗑️.

As it pings other members, `/remind` is for members with the **Manage
Messages** permission by default. A server admin can open it to other roles
or channels in *Server Settings → Integrations → Remind Me*. `/remindme` is
open to everyone.

The reminder is posted in the channel where you created it, mentioning its
target. If the bot can't post there anymore, it sends it by DM instead.

A reminder for one member can go to them by DM instead: **Edit Channel →
Send by DM** in `/reminder_list`, or for all the new ones with `/settings` →
*Members' reminders: By DM*. If the DM fails (closed DMs), it is posted in its
channel. Reminders for a role always go to the channel.

### Writing the time

Times are read in the timezone of the server (yours in DMs).

| You write | Meaning |
|---|---|
| `2h`, `90 min`, `3d`, `1 week`, `2 years` | after that duration |
| `1h30`, `1h 30m`, `1y 1mo 2 days -5h` | durations can be combined |
| `in 2h`, `in 1h30`, `in 3 days at 9:00` | the same, in words |
| `9:00`, `at 3pm`, `at 18h30`, `noon` | that time today, or tomorrow once it has passed |
| `tomorrow 9:00`, `tomorrow 18h30`, `tomorrow at 3pm`, `tonight` | a time tomorrow or today |
| `friday 18:30`, `friday 9h`, `monday at 8am`, `next friday` | the next such day |
| `24 dec 6pm`, `2 aug 15:00`, `july 1st at 10:00`, `23/09 15:00` | a date (day first: `01/02/27` is 1 February 2027) |
| `23 september 2027 15:00`, `2027-01-15 09:00` | a date with its year |
| `2027-01-15T09:00:00+01:00` | an ISO timestamp (its own offset wins over the server timezone) |
| `eod` | today at 17:00 |
| `eow` | the end of the working week (Friday 17:00, the next one on weekends) |
| `eom`, `eoy` | the last day of the month, of the year |

Without a time, most dates keep the current time of day: `monday` is next
Monday at the time you typed it (`next friday` is at 9:00).

`9h` and `18h30` are times of day after a day or `at` (`tomorrow 18h30`,
`at 9h`); alone, `1h30` or `18h30` stays a duration. French works too:
`demain à 18h30`, `vendredi 9h`, `après-demain 10h`, `dans 3 jours`,
`le 15 janvier à 9h`, `midi`.

Reminders are delivered within a minute of their time. When the bot or
Discord was down, they are sent once it is back (up to a day later), marked
*⏰ Sent late* with the time they were due.

### Repeating reminders

Write the repetition in the `time` field:

```
every friday at 20:15
every weekday at 8:30
every 2 weeks
every first monday of the month
every month on the 15th at 9:00
every year on 1 july at 10:00
tous les lundis à 9h
tous les jours à 8h30 jusqu'au 20 décembre
```

Or create a one-time reminder, then press **Set Interval** (or **Edit
Interval** in `/reminder_list`):

* **Quick repeat**: every day, every weekday, every weekend, every week, every
  2 weeks, every month, every year, from the date of the reminder (that date
  stays the first one, even if it isn't on a weekday or a weekend);
* **Add Repeating Rule**: plain words (`every friday at 7`) or an
  [RRULE](https://www.textmagic.com/free-tools/rrule-generator) such as
  `FREQ=MONTHLY;BYDAY=1MO`. A rule pasted from a generator, with its
  `DTSTART` in UTC or with a `TZID`, is converted to the server's time;
* **Add Exception Rule**: dates to skip (`every saturday`);
* **Add Single Date** / **Add Exception Date**: one extra date, or one date to skip.

Before adding a rule, the bot shows up to five of its next dates; the menus of
a repeating reminder and its *New Interval Created* message show up to five
next occurrences. An exception rule that would remove every future date is
refused (delete the reminder instead). A repeating reminder can combine up to
25 rules and dates. In `/reminder_list` you can
also **Pause** it (its dates go on, nothing is sent) or **Skip next**.

### When a reminder is delivered

Under the reminder:

| Button | Effect |
|---|---|
| ⏱️ **+10 min**, ⏱️ **+1 hour** | sends it again after that time |
| ⏱️ **Tomorrow 9:00** | sends it again tomorrow at 9:00 |
| **Other…** | sends it again at any time, written like in `/remindme` |
| ⏭️ **Skip next** | repeating reminders: don't send the next date |
| 🗑️ | repeating reminders: delete it |

Anyone can snooze: when someone else than the author does, the copy is
theirs and comes to their DMs (*Tomorrow 9:00* then uses their own
timezone). Only the author can skip. The author, the member it is for, the
members it mentions and members with **Manage Messages** can delete; when
someone else deletes it, the author gets a DM saying who did.

The buttons keep working after a restart of the bot: for 7 days on a
one-time reminder, as long as it exists on a repeating one.

`@everyone`, `@here` and roles written in a reminder only ping when its
author may ping them in that channel, like in a message of their own. The
role given to `/remind` also pings when it is mentionable.

A reminder whose author has left the server is deleted when it comes due,
instead of being sent.

### Manage your reminders

`/reminder_list` shows your reminders, sorted by date:

> 1️⃣ **Take out the trash**
> 　8 November 2026 09:00 · in 20 hours · #general
>
> 2️⃣ 🔁 **Check the feed**
> 　13 November 2026 07:00 · in 6 days · #general
> 　↳ every Fri, 1 exception

Dates are shown in your own language and timezone. Pick a reminder in the
menu below the list to:

* **Edit**: title, text, image and date;
* **Edit Channel**: deliver it somewhere else (a channel you can post in);
* **Set Interval** / **Edit Interval**: add or remove repetitions;
* **Pause** / **Resume**, **Skip next**: repeating reminders;
* **Delete**.

On a server, the buttons under the list switch what it shows:

* **My reminders**: the ones you created;
* **For me**: the ones other members created for you with `/remind`, or
  that mention you. You can delete them (their author gets a DM), not edit
  them;
* **Whole server**: all the reminders of the server, with their author. Only
  for members with the **Manage Messages** permission, who can delete them
  (and edit only their own).

The list is only visible to you. Menus close after 14 minutes without use.

### Settings

`/timezone Europe/Paris` sets the timezone of the server (any
[IANA timezone](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones),
suggested as you type; the default is UTC). In a DM with the bot, or where only
you installed the app, it sets your own timezone. Repeating reminders keep their
local time when it changes.

`/settings` shows the server settings:

* **Reminder style**: *Hybrid* (mention, start of the text and an embed, the
  default), *Embed-Only*, *Text-Only* or *Barebone* (mention and text only). The
  buttons under delivered reminders come with the two embed styles.
* **Creation reply**: deleted after 5 minutes (the default), never deleted, or
  only shown to its author.
* **Members' reminders**: new reminders for one member are posted in their
  channel (the default) or sent by DM.

Changing the server settings needs the **Manage Server** permission.

When the bot is removed from a server, its reminders and settings are kept 7
days, and nothing is sent meanwhile. Added back within that time, it picks up
where it was (the reminders missed in between are sent, marked *⏰ Sent late*);
after that, they are deleted.

### Limits

| | |
|---|---|
| message | 4000 characters (longer text-only reminders are sent in several messages) |
| pending reminders | 100 per user |
| repetitions | at most every 10 minutes, with a date in the next 10 years |
| rules of a repeating reminder | 25 |

## Commands

| Command | |
|---|---|
| `/remindme time message` | remind yourself |
| `/remind target time message` | remind another user or a role (Manage Messages by default) |
| `/reminder_list` | list, edit and delete your reminders (and the ones for you, or the whole server's) |
| `/timezone timezone` | set the timezone of the server, or your own in DMs |
| `/settings` | reminder style, creation reply and DM delivery of the server |
| `/help` | help pages, with the time syntax |

## Troubleshooting

* **The commands don't show up**: the user needs the **Use Application
  Commands** permission in that channel (granted to @everyone by default). After
  an update of the bot, restart Discord (Ctrl+R) to get the new commands.
* **A reminder came by DM instead of the channel**: the bot couldn't post there
  (channel deleted, or missing permissions). It needs *View Channel*, *Send
  Messages* (*in Threads* for threads) and *Embed Links*.
* **No DM at all**: the bot can only DM users who share a server with it and
  accept DMs from its members.

## Self-hosting

### Requirements

* Python 3.11 or newer (tested on 3.11 and 3.13)
* MongoDB, with authentication
* A Discord application with a bot user
  ([Developer Portal](https://discord.com/developers/applications)); no
  privileged intent is needed

### Install

```bash
git clone --recurse-submodules https://github.com/sSlydee/RemindmeBot.git
cd RemindmeBot
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

`--recurse-submodules` is required: the natural language parser lives in the
`Bot/lib/recurrent` submodule.

### Configuration

The bot reads environment variables:

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | yes | token of the Discord bot |
| `MONGO_CONN` | yes | MongoDB host, e.g. `127.0.0.1` |
| `MONGO_PORT` | yes | MongoDB port, e.g. `27017` |
| `MONGO_ROOT_USER` | yes | MongoDB user (authenticated against `admin`) |
| `MONGO_ROOT_PASS` | yes | MongoDB password |
| `LOG_LEVEL` | no | `INFO` (default) or `DEBUG` |
| `LOG_FILE` | no | default `logs/bot.log` (relative to `Bot/`), rotated at 5 MB, 5 old files kept |
| `UPTIME_KUMA_PUSH_URL` | no | push URL of an [Uptime Kuma](https://github.com/louislam/uptime-kuma) *Push* monitor |

The data is stored in the `reminderBot` database: `settings`, `reminders`,
`intervals`, and `delivered` (one-time reminders kept 7 days for their buttons).

With `UPTIME_KUMA_PUSH_URL`, the bot sends a heartbeat about every 50 seconds
while both delivery loops run and it is connected to Discord; set the monitor's
interval to 60 seconds or more.

### Run

```bash
cd Bot
set -a; . ../.env; set +a   # or any other way to set the variables above
../.venv/bin/python remindmeBot.py
```

To keep it running, use a service manager, e.g. a systemd service with
`WorkingDirectory=.../Bot`, `EnvironmentFile=.../.env` and `Restart=on-failure`.
Back up the database regularly (`mongodump`).

The `Dockerfile` and `docker-compose.yml` come from the original project and
are not tested in this fork.

### Invite the bot

Replace `CLIENT_ID` with the application id of your bot:

```
https://discord.com/oauth2/authorize?client_id=CLIENT_ID&permissions=274877991936&scope=bot%20applications.commands
```

The permissions are View Channels, Send Messages, Send Messages in Threads,
Embed Links and Read Message History. `/help` has an *Invite Me* button with
the same link. Then set the server timezone with `/timezone`.

### Install on your account (optional)

`/remindme`, `/reminder_list` and `/timezone` can also be installed on a user
account, to use them in DMs, group DMs and servers the bot is not in. There,
reminders are private: they come by DM, in the user's own timezone (set with
`/timezone` in such a place or in a DM with the bot), and the replies are only
visible to the user.

1. In the [Developer Portal](https://discord.com/developers/applications),
   *Installation*: tick **User Install** and add the `applications.commands`
   scope to its default install settings.
2. Open this link and choose *Add to My Apps*:
   ```
   https://discord.com/oauth2/authorize?client_id=CLIENT_ID&integration_type=1&scope=applications.commands
   ```

The bot must be able to DM you (for example, by sharing a server with you).

## Development

Run the tests from the repository root:

```bash
.venv/bin/pip install mongomock
.venv/bin/python -m unittest discover -s unit_tests -t . -p '*Test.py'
```

They also run on GitHub Actions on every push (Python 3.11 and 3.13), with
CodeQL.

The menu, button and delivery tests use an in-memory database (`mongomock`,
skipped without it) and a small stand-in for Discord
(`unit_tests/fakediscord.py`): clicks and popups go through py-cord's own code,
with Discord's rules (ephemeral messages, one answer per interaction within
3 seconds, 15-minute tokens, single-line popup fields).

## Changes from the original bot

Removed, as a personal bot doesn't need them: statistics (Prometheus), top.gg
server count, sharding, the community mode (moderator roles; changing settings
now needs **Manage Server**), legacy UTC intervals and the experimental settings.

Added or reworked: the time preview while typing, *Quick repeat* and
plain-language rules, rules kept in local time across daylight saving, the
persistent buttons with more snooze choices and *skip next*, pause, the new
`/reminder_list`, user install, mentions limited to what the author may ping,
`/remind` for moderators by default, reminders of members who left dropped,
reminders for you and of the whole server (moderators) in `/reminder_list`,
retries when Discord is unreachable, and many fixes to the menus and the
delivery (see the commit history).

## Credits

Original bot by [Mayerch1](https://github.com/Mayerch1/RemindmeBot).

Logo: the Bell icon from [Fluent Emoji](https://github.com/microsoft/fluentui-emoji)
(3D style), © Microsoft Corporation,
[MIT License](https://github.com/microsoft/fluentui-emoji/blob/main/LICENSE),
on a coloured disc.
