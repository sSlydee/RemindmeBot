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
  *Quick repeat* menu, or iCalendar rules (RRULE) in the repetition menus,
  with exceptions, extra dates, pause and *skip next*.
* **Buttons under each delivered reminder**: snooze (+10 min, +1 hour,
  tomorrow 9:00, or any time), skip the next date, delete. They keep working
  after a restart.
* **One list to manage everything**: `/reminder_list` shows your reminders
  with their dates in your own language and timezone, and lets you edit,
  move, pause or delete them.
* **Timezones** per server, or per user in DMs, with daylight saving.
* **In French** for members whose Discord is in French, and French times are
  understood for everyone: `demain 9h`, `tous les lundis à 9h`.
* **For shared servers**: `/remind` for moderators by default; members see
  the reminders for them (*For me*), moderators every reminder of the server;
  delivery by DM per reminder or for the whole server; a privacy note in
  `/help`.
* **Late, not lost**: a reminder sent late says so, and a server that removes
  the bot by mistake keeps its reminders for 7 days.
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

`/remindme` reminds you, `/remind` reminds another user or a role. The reply,
only shown to you by default (see `/settings`), says when the reminder will
come, with three buttons: **Set Interval** (make it repeat; **Edit Interval**
for a repeating one), **Edit** and 🗑️.

As it pings other members, `/remind` is for members with the **Manage
Messages** permission by default. A server admin can open it to other roles
or channels in *Server Settings → Integrations →* (the bot). `/remindme` is
open to everyone.

The reminder is posted in the channel where you created it, mentioning its
target. If the bot can't post there anymore, it sends it to the member by DM
instead. A reminder for a role, or for a member whose DMs are closed, is then
not sent: its author gets a DM saying it failed.

A reminder for one member can go to them by DM instead: **Edit Channel →
Send by DM** in `/reminder_list`, or for all the new ones (your own `/remindme`
ones too) with `/settings` → *Members' reminders: By DM*. If the DM fails (closed DMs), it is posted in its
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

Reminders are delivered within a minute of their time. When the bot was
stopped, the missed ones are sent once it is back (a repeating reminder once,
not once per missed date). When Discord can't be reached, the bot tries again
for a day, then drops the reminder. A reminder sent more than 5 minutes after
its time says when it was due (*⏰ Sent late*, or a *⏰ Due* line in the
*Text-Only* style; nothing in *Barebone*).

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
tous les 15 du mois à 9h
tous les jours à 8h30 jusqu'au 20 décembre
```

Or create a one-time reminder, then press **Set Interval** (in the reply, or in
`/reminder_list`):

* **Quick repeat**: every day, every weekday, every weekend, every week, every
  2 weeks, every month, every year, from the date of the reminder (that date
  stays the first one, even if it isn't on a weekday or a weekend);
* **Add Repeating Rule**: plain words (`every friday at 7`) or an
  [RRULE](https://www.textmagic.com/free-tools/rrule-generator) such as
  `FREQ=MONTHLY;BYDAY=1MO`. A rule pasted from a generator, with its
  `DTSTART` in UTC or with a `TZID`, is converted to the server's time;
* **Add Exception Rule**: dates to skip (`every saturday`);
* **Add Single Date** / **Add Exception Date**: one extra date, or one date to skip.

On a repeating reminder, **Edit Interval** lists its rules and dates: pick one
to see it in full or delete it, or press **Add New Rule** for the choices above.

Before adding a rule, the bot shows its next dates (up to five); a repeating
reminder's reply and menus show its next occurrences (up to five). An exception rule that would remove every future date is
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

Anyone can snooze: when someone other than the author does, the copy is
theirs and comes to their DMs (*Tomorrow 9:00* and *Other…* then use their own
timezone, set with `/timezone` in a DM with the bot; UTC until they set one). When the author snoozes a reminder for a role, the copy reminds
only them, not the whole role again. Only the author can skip. The author, the
member it is for, the members it mentions (in a reminder for one member, not
for a role) and members with **Manage Messages** can delete; when someone else
deletes it, the author gets a DM saying who did.

The buttons work for 7 days after a one-time reminder is sent, and as long as
a repeating one exists, even after the bot restarts.

`@everyone`, `@here` and roles written in a reminder ping only when its author
has the *Mention @everyone, @here and All Roles* permission in that channel.
The role given to `/remind` also pings when it is mentionable.

A reminder whose author has left the server is deleted when it comes due,
instead of being sent.

When the bot is removed from a server, its reminders and settings are kept for
7 days, and nothing is sent meanwhile. Added back within that time, it picks up
where it was (the reminders missed in between are sent, marked as late); after
that, they are deleted.

### Manage your reminders

`/reminder_list` shows your reminders, sorted by date: on a server, the ones
of that server; in a DM with the bot, your private ones.

> 1️⃣ **Take out the trash**
> 　8 November 2026 09:00 · in 20 hours · #general
>
> 2️⃣ 🔁 **Check the feed**
> 　13 November 2026 07:00 · in 6 days · #general
> 　↳ every Fri, 1 exception

The dates of the list are shown in your own language and timezone (the menu
below it uses the server's timezone). Pick a reminder in that menu to:

* **Edit**: title, text, image and date;
* **Edit Channel**: deliver it somewhere else (a channel you can post in);
* **Set Interval** / **Edit Interval**: add or remove repetitions;
* **Pause** / **Resume**, **Skip next**: repeating reminders;
* **Delete**.

On a server, the buttons under the list switch what it shows:

* **My reminders**: the ones you created;
* **For me**: the ones other members created for you with `/remind`, or
  that mention you (in a channel you can read; not reminders for a role). You
  can delete them (their author gets a DM), not edit them;
* **Whole server**: all the reminders of the server, with their author. Only
  for members with the **Manage Messages** permission, who can delete them
  (and edit only their own).

The list is only visible to you. Menus close after 14 minutes without use.

### Settings

`/timezone Europe/Paris` sets the timezone of the server (any
[IANA timezone](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones),
suggested as you type; the default is UTC). In a DM with the bot, or where only
you installed the app, it sets your own timezone. On a server it needs **Manage
Server**, and asks you to confirm. Repeating reminders keep their local time
when it changes.

`/settings` shows the server settings (in a DM with the bot: your own
reminder style, for the reminders it sends you by DM):

* **Reminder style**: *Hybrid* (mention, start of the text and an embed, the
  default), *Embed-Only*, *Text-Only* or *Barebone* (mention and text only). In
  channels, the buttons under delivered reminders come with the two embed
  styles; in DMs every style gets them (*Barebone* is sent like *Hybrid*).
* **Creation reply**: only shown to its author (the default), deleted after 5
  minutes, or never deleted.
* **Members' reminders**: new reminders for one member (your own `/remindme`
  ones too) are posted in their channel (the default) or sent by DM.

Changing the server settings needs the **Manage Server** permission.

### Language

Members whose Discord is in French get the bot in French: the command
descriptions, the time preview while typing (`demain 9h → mer. 11 nov.
09:00`), the replies, the menus of `/reminder_list`, `/settings`,
`/timezone` and `/help` (with a French syntax page), and the repetitions
written in words (*tous les lundis à 9h*; a rare rule French can't say yet
stays in English). A reminder is delivered in the language of its author,
with its buttons; a click is answered in the language of whoever clicked.
Everyone else gets English.

### Privacy

`/help` → **Privacy** shows this note to members (in French to the members
whose Discord is in French):

The bot runs on a machine its owner manages. It keeps what it needs to send
the reminders, and shares it with no one but Discord.

**What is stored**

* the reminders: text, title, image link, dates and repetitions, and the
  language of their author's Discord (to send them in it);
* who wrote them and who they are for, their server and channel, and the last
  message of that channel (for the *jump to the chat* link);
* the settings of the server (timezone, style...), and a user's own timezone
  and style if they set them in DMs.

**Who can see a reminder**

* its author, and the member it is for (*For me* in `/reminder_list`); the
  members it mentions too, when it is for one member and they can read its
  channel;
* the moderators of the server (**Manage Messages**), in *Whole server*;
* the owner of the bot, who runs its database.

**How long**

* until it is sent or deleted (`/reminder_list`), then 7 days more for the
  buttons under it;
* the daily backups are kept 14 days;
* the log of the bot keeps user and reminder IDs (and error details) until it
  is rotated out;
* when the bot is removed from a server, the data of that server is deleted
  after 7 days.

To have their data deleted sooner, members delete their reminders or ask the
owner of the bot.

### Limits

| | |
|---|---|
| message | 4000 characters (a text-only reminder over 2000 characters is sent as several messages) |
| time | 100 characters |
| pending reminders | 100 per user |
| repetitions | at most every 10 minutes, with a date in the next 10 years |
| rules of a repeating reminder | 25 |

## Commands

| Command | |
|---|---|
| `/remindme time message` | remind yourself |
| `/remind target time message` | remind another user or a role (Manage Messages by default) |
| `/reminder_list` | list, edit and delete your reminders (and the ones for you, or the whole server's) |
| `/timezone new_timezone` | set the timezone of the server, or your own in DMs |
| `/settings` | reminder style, creation reply and DM delivery of the server |
| `/help` | help pages (commands, time syntax, timezone), the privacy note and a self-test, only shown to you |

## Troubleshooting

* **The commands don't show up**: the user needs the **Use Application
  Commands** permission in that channel (granted to @everyone by default). After
  an update of the bot, restart Discord (Ctrl+R) to get the new commands.
* **`/remind` is missing**: by default only members with **Manage Messages**
  see it (see *Create a reminder*).
* **A reminder came by DM instead of the channel**: the bot couldn't post there
  (channel deleted, or missing permissions). It needs *View Channel* and *Send
  Messages* (*Send Messages in Threads* in threads).
* **A reminder came as plain text, without buttons**: the bot lacks *Embed
  Links* in that channel.
* **No DM at all**: the bot can only DM users who share a server with it and
  allow direct messages from members of that server (Discord privacy
  settings).
* **Something else**: `/help` → **Self-Test** checks that the bot can post in
  the channel and DM you, and shows the local time it uses.

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
`Bot/lib/recurrent` submodule (cloned without it: `git submodule update --init`).

### Configuration

The bot reads environment variables, for example from a `.env` file at the
root of the repository (one `NAME=value` per line, see *Run*):

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
`intervals`, and `delivered` (one-time reminders kept for 7 days for their buttons).

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
`WorkingDirectory=.../Bot`, `EnvironmentFile=.../.env`,
`ExecStart=.../.venv/bin/python remindmeBot.py` and `Restart=on-failure`.
Back up the database regularly (`mongodump`).

Before members use it, adapt the privacy note shown by `/help`
(`Bot/util/privacy.py`, in English and French): it describes this instance,
such as its backups kept 14 days (`BACKUP_KEEP_DAYS`).

The `Dockerfile` and `docker-compose.yml` come from the original project and
are not tested in this fork.

### Invite the bot

Replace `CLIENT_ID` with the application id of your bot:

```
https://discord.com/oauth2/authorize?client_id=CLIENT_ID&permissions=274877991936&scope=bot%20applications.commands
```

The permissions are View Channels, Send Messages, Send Messages in Threads,
Embed Links and Read Message History. Then set the server timezone with
`/timezone`.

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

Added or reworked:

* times: the preview while typing, French inputs, `9h` / `18h30`;
* repetitions: *Quick repeat*, plain-language rules, rules kept in local time
  across daylight saving, pause, *skip next*;
* the buttons under delivered reminders, with more snooze choices, kept across
  restarts;
* the new `/reminder_list`, with *For me* and *Whole server* (moderators);
* shared servers: `/remind` for moderators by default, pings limited to what
  the author may ping, deletion by the members a reminder mentions (its author
  is told), reminders of members who left dropped, delivery by DM;
* delivery: retries when Discord is unreachable, the *Sent late* mark, a
  removed server's data kept for 7 days;
* the bot in French, user install, the privacy note, `/help` only shown to
  whoever asks it (without *Invite Me*), the creation reply hidden by default;
* many fixes to the menus and the delivery (see the commit history).

## Credits

Original bot by [Mayerch1](https://github.com/Mayerch1/RemindmeBot).

Logo: the Bell icon from [Fluent Emoji](https://github.com/microsoft/fluentui-emoji)
(3D style), © Microsoft Corporation,
[MIT License](https://github.com/microsoft/fluentui-emoji/blob/main/LICENSE),
on a coloured disc.
