# Project L

Project L is a Discord bot with moderation, tickets and modmail, reaction roles,
music, invite tracking, giveaways, economy games, welcome messages, logging,
sticky messages, Twitch notifications, YouTube notifications, and server stats.

## Quick start on Windows

Project L is tested with Python 3.11. The included setup script installs missing
Python 3.11, FFmpeg, and Node.js LTS through Winget or Chocolatey when available,
creates an isolated `.venv`, installs every Python dependency, backs up existing
databases, verifies all bot extensions, and opens a graphical configuration
wizard.

1. Open PowerShell in this project directory and run:

   ```powershell
   .\setup.ps1
   ```

2. In the setup wizard, use **Open Developer Portal** to create an
   application. Open its **Bot** page, create/add the bot if Discord offers that
   option, then reset and copy its token. The Discord application and token
   remain under your account; Project L never creates an account or asks you to
   send the token anywhere.
3. On the bot page, enable these privileged gateway intents and save the
   changes:

   - Presence Intent
   - Server Members Intent
   - Message Content Intent

4. In the setup window, enter the Discord bot token and server ID, confirm the
   three intent switches, then select **Invite Bot to Server**. Discord opens an
   invite for that exact server with the application-command scopes and only
   the permissions Project L uses. If needed, **Open This Bot's Settings**
   resolves the Bot page directly from the entered token. Authorize the invite,
   return to setup, choose **Check Readiness**, then **Save & Create**.
5. Project L creates or reuses its verified and streamer roles, secured
   categories and channels, statistics counters, a dedicated Self Roles category, a
   private-voice creation panel, and a help ticket channel. It
   also creates `#verify`, `#welcome`, a general chat channel, rules,
   announcements, boosts, giveaways, XP progress, three level lounges,
   and a public voice-creation panel. Members can name a public voice room;
   temporary rooms are deleted when empty. It
   remembers all generated IDs automatically; no channel or category IDs are
   requested.
6. Start the bot:

   ```powershell
   .\start.ps1
   ```

The first setup can take several minutes. Future starts only need
`.\start.ps1`. Startup automatically reruns dependency setup when
`requirements.txt` changes, creates a verified database snapshot, prevents a
second copy from the same folder, and restarts the bot up to five times after an
unexpected crash. If required configuration is missing or its provisioning
version is outdated, start opens the wizard automatically. Run
`.\configure.ps1` whenever you want to change settings or repair deleted
managed resources.

The wizard masks secret fields, validates related settings together, checks the
bot's permissions and role hierarchy, reuses valid Project L resources, creates
anything missing, and saves generated IDs to the local, Git-ignored
`Data/config.json` and `Data/roles.json` files. Running setup again is
idempotent and preserves unrelated server channels. After the new public-voice
panel is live, the bot removes only its own old fixed Custom Voice Chat if empty.

The setup reuses the original managed welcome channel as `#verify`, preserving
its history, and uses a separate `#welcome` for the bot's welcome messages.
An Information category holds verify, welcome, and rules; an Announcements
category holds announcements, boosts, and giveaways. Rules and announcements
are read-only for regular members; add your own text after setup.

Self Roles and Help each have their own category. General Chat is first in
Community. Reaching a higher chat or voice milestone retains all earlier
lounge roles, so lower-level lounges remain accessible.

The Voice Creation category holds short `create-private` and
`create-public` panel channels. Public rooms appear in Public Voice, are visible
to verified members, and are removed after everyone leaves. A never-joined
room expires after two minutes. Streamers can name their private room in a
button dialog. The original fixed Custom Voice Chat can be
removed once it is empty and the public creation panel is working.

The Branding page lets an owner select local PNG, JPG, or animated GIF artwork
for managed panels and channel headers. Setup copies selected art into
`Data/art/custom` so it remains with that installation. It also contains editable server rules.
Save and restart the bot to refresh its own existing embeds. The bundled GIFs
cover Rules, Announcements, Giveaways, Server Boosts, and Stream Alerts.
`Data/art/project_l_avatar.gif` is an optional animated bot avatar for manual
upload in the Discord Developer Portal; setup will not overwrite the bot's
profile image automatically.

Stream Alerts is created even when YouTube and Twitch are left blank, so its
animated header and place in Announcements are consistent on a fresh install.
Notification checks stay disabled until an integration is configured. Run
`python live_smoke_test.py` from the project virtual environment after the bot
starts to verify managed panels and animated headers.

The setup window combines descriptive pages into Server Layout and adds a
Moderation page. Its optional anti-spam and Discord-invite filters are off by
default, exempt staff with Manage Messages, and notify a member privately at
most once per minute when a message is removed.

Chat and voice XP are separate. Eligible chat messages earn XP at most once
per minute. Voice XP is counted once per minute only when at least two
non-bot members are present and the member is not muted or deafened; Discord
does not expose reliable proof of actual speaking to this bot. `/rank` shows
the exact totals privately. The `#xp-progress` channel posts only at levels
5, 15, and 30; these roles unlock matching level lounges. Admin and Moderator
roles are created without assigning them to anyone. Review their permissions
and assign them manually to trusted staff.

To keep the bot token out of JSON entirely, set it before opening the wizard:

```powershell
$env:DISCORD_BOT_TOKEN = "your bot token"
.\setup.ps1
```

For unattended checks, `-NoGui` prevents a window from opening and returns an
error when required settings are incomplete:

```powershell
.\setup.ps1 -NoGui
.\start.ps1 -NoGui
```

Use `.\setup.ps1 -SkipSystemDependencies` only when Python 3.11 is already
installed and you intentionally do not want setup to install optional system
tools.

## Configuration

The graphical wizard is the recommended configuration method. Channel and
category IDs in `Data/config.json` are internal setup state; users do not need
to find or enter them. You may still edit the file manually for advanced use:
Discord IDs must be JSON numbers without quotes, `0` disables an optional role,
and an empty string disables an optional account or API credential.

Important settings:

- `guildId`: the one Discord server this bot is allowed to handle.
- `client_id`: discovered from the bot token during setup.
- `welcome`: automatic welcome output channel. Generated welcome images are
  attached directly to the welcome message.
- `verified` and `streamRole`: safe roles created automatically
  under the bot's highest role. The verified role is granted by the Verify
  button; the streamer role permits private-voice creation. Members can opt in
  to the separate Now Streaming Pings self-role for primary Twitch alerts.
- `invitechannel`, `modmail`, `transcripts`, `voicecategory`, `tickets`,
  `serverStatChannelIds`, and `logChannelIds` are filled automatically by the
  wizard. Audit events share one private staff log channel.
- `kickMemberFunction`: leave `false` unless you intentionally want the monthly
  cleanup of members who have remained unverified for more than 30 days.
- `logMessageContent`: privacy-sensitive and `false` by default. Enable it only
  if staff logs should include edited/deleted message text and attachment URLs;
  metadata logging continues when it is disabled.

YouTube notifications only require `ytChannel`; setup creates the Discord alert
channel. The source accepts an `@handle`, a `UC...` channel ID, or a full
YouTube channel URL. Twitch notifications require `twClientId`,
`twClientsecret`, and at least one streamer username. Primary and friend stream
alerts share the automatic alert channel. Twitch secrets can instead be
supplied as environment variables:

```powershell
$env:TWITCH_CLIENT_ID = "your client id"
$env:TWITCH_CLIENT_SECRET = "your client secret"
```

Reaction-role menu IDs can be entered in the wizard. They are stored in
`Data/roles.json` as a JSON list; `Data/roles.example.json` is the safe manual
template:

```json
[
  123456789012345678,
  234567890123456789
]
```

## Verification and troubleshooting

Check the installation without connecting to Discord:

```powershell
.\.venv\Scripts\python.exe bot.py --check
```

Check whether the required configuration is complete without opening the GUI:

```powershell
.\.venv\Scripts\python.exe configure_gui.py --check
```

After the bot has started once, run the read-only live smoke test. It checks the
bot account, permissions, managed channels, roles, hierarchy, and all automatic
panels against the real Discord server:

```powershell
.\smoke-test.ps1
```

Useful checks:

```powershell
.\.venv\Scripts\python.exe -m pip check
ffmpeg -version
node --version
```

FFmpeg must be on `PATH` for `/play`. Node is used by current `yt-dlp` releases
for YouTube extraction. Setup attempts to install both; if the current
PowerShell process cannot see a newly installed command, restart the bot.
The `/play` command checks that FFmpeg can read the selected stream before it
announces playback; YouTube may still deny some videos or streams.

If Discord rejects the connection for privileged intents, enable all three
listed intents in the Developer Portal and restart. If a managed channel is
deleted or unavailable, run `.\configure.ps1` again; setup recreates only the
missing Project L resources.

Saved sticky-message warnings come from `sticky.db`; they indicate that the bot
cannot access an older saved channel. Grant access if it is still used, or run
`/unsticky` from that channel before removing it.

Ticket channels are created privately: `@everyone` is denied access, while the
ticket opener, bot, administrators, and roles with Manage Channels are allowed.
Modmail also requires a staff-only category that denies View Channel to
`@everyone`. Users receive a delivery receipt after a successful modmail DM.

Use `/help` in Discord after the application commands finish syncing.

## Runtime recovery and logs

Every normal start creates a consistent SQLite snapshot under `Backups/` and
keeps the newest 14 snapshots. Runtime output is saved under
`Data/bot-runtime-YYYYMMDD-HHMMSS.log`; the newest 10 logs are retained. These
directories are ignored by Git.

List or verify snapshots with:

```powershell
.\.venv\Scripts\python.exe runtime_backup.py list
.\.venv\Scripts\python.exe runtime_backup.py verify "Backups\<snapshot>"
```

To restore, stop the bot first. Restore verifies hashes and SQLite integrity,
then creates a recovery snapshot of the current databases before replacing
them. The explicit `--force` flag prevents accidental restores:

```powershell
.\.venv\Scripts\python.exe runtime_backup.py restore "Backups\<snapshot>" --force
```

Use `.\start.ps1 -NoRestart` to disable crash restarts or
`.\start.ps1 -NoRuntimeLog` to disable transcript logging for one run. The
restart count and delay can be changed with `-MaxRestarts` and
`-RestartDelaySeconds`.

## Self-role panels

On first startup, Project L creates the built-in self-role choices and posts a
**Self Roles** banner first, followed by separate Color, Pronoun, Platform, Age,
and Event Pings button panels. Each group has its own animated GIF. The Verify
button goes in `#welcome`; private-voice, ticket, and configured reaction-role
panels go in the automatic `project-l-panels` channel. A previously misplaced
bot-authored Verify panel is removed from `project-l-panels` only after a new
one is posted in `#welcome`. Existing panels are detected by their stable component IDs, so
restarts do not post duplicates. Existing text-only managed panels are upgraded
in place with their local art while preserving their buttons. Verification,
private-voice, and ticket panels upload their matching banner from `Data/art/`
directly to Discord. New
`/reactionroles` panels do the same with `Data/self_roles.gif`, so the embedded
images do not depend on a third-party host and do not expire. Images supplied
to `/say` are also reuploaded as durable message attachments.

If older Color, Gender, Age, Platform, Server Notification, or Game role panels
show **Image failed to load**, run `/repairselfroles` in that channel as an
administrator. It attaches the matching group GIF. The command edits only recognized bot-authored panels, preserves
their existing buttons and unrelated attachments, and is safe to run again.

## Included art pack

Project L includes local artwork for every setup-managed visual:

- `Data/art/project_l_logo.png`: square bot/application avatar and server icon.
- `Data/art/project_l_server_banner.png`: 16:9 Discord server banner.
- `Data/art/verification.png`, `private_voice.png`, and `tickets.png`: durable
  setup-panel banners uploaded automatically with their embeds.
- `Data/art/emojis/`: five transparent feature emojis. Setup creates only
  missing `projectl_*` names and never replaces or deletes server emojis.
- `Data/welcome.jpg`: background used to generate personalized welcome cards.
- `Data/self_roles.gif`: animated reaction-role panel banner and legacy-panel
  opening self-role banner.
- `Data/art/self_roles_*.gif`: distinct animated Color, Pronoun, Platform, Age,
  and Event Pings artwork for the matching button panels and legacy repairs.

The setup-managed panel art is automatic. Discord deliberately keeps bot
application branding and server branding behind account/server-owner controls,
so upload the included logo and banner in the Developer Portal or **Server
Settings > Overview**. Exact dimensions and usage notes are in
`Data/art/README.md`. Missing optional panel artwork never prevents the panel
buttons from working; the bot falls back to a text-only embed. Emoji slot,
permission, or file problems are non-blocking setup warnings.

## Verification gate

Project L makes `#welcome` the only channel visible to ordinary new members.
The Verify button gives them `Project L Verified`, which unlocks public channels
and hides `#welcome`. Private staff, modmail, and ticket areas keep their
existing access rules. Server owners and administrators bypass ordinary channel
visibility restrictions, so test the gate with a non-administrator account.

## Browser dashboard (optional)

The browser dashboard is part of the bot process and is **off by default**. It
lets server owners edit rules, panel art, moderation thresholds, warning
escalation, and ticket forms/priorities. Staff can review moderation cases,
tickets, appeals, response times, private case/ticket notes, and opt-in searchable transcripts. Members
can submit one open appeal at a time. Discord sign-in and current server
permissions are checked on every request; only owners or people with Manage
Server can change settings. Raid detection and warning escalation are off until
an owner explicitly enables them.
Owners can set a first-response target; overdue tickets alert the configured
`logs` channel once, without pinging members. A transcript retention period
purges expired locally searchable transcripts every ten minutes. Zero disables
either policy. The dashboard also keeps a limited history of changes to its
rules, moderation, ticket, and branding configuration (not credentials).
Owners can restore one of those snapshots; the current settings are saved first.
The owner dashboard also shows bot health and can schedule one-time text
announcements up to a year ahead. Announcements never ping roles or members,
can be cancelled before sending, and retain sent/failed status. If the bot
crashes during a send, that item is marked failed for manual review rather
than risk a duplicate post.
Until the browser dashboard is configured, server managers can use
`/scheduleannouncement` and `/cancelannouncement` in Discord. These commands
are restricted to the configured server and require Manage Server permission.
Administrators can optionally set `expires_days` on `/warn`. Expired warnings
stay in the database for history but no longer appear in `/warnings` or count
toward warning escalation. Existing warnings have no expiry.

To enable it, register `https://YOUR-DOMAIN/oauth/callback` as an OAuth2
redirect URL for this bot in the Discord Developer Portal. Set these
environment variables on the bot host (never commit the secrets):

```text
PROJECTL_DASHBOARD_PUBLIC_URL=https://YOUR-DOMAIN
DISCORD_CLIENT_SECRET=<the bot application's OAuth2 client secret>
PROJECTL_DASHBOARD_SESSION_SECRET=<at least 32 random characters>
PROJECTL_DASHBOARD_PORT=8765
```

Point a TLS-enabled reverse proxy for that domain at `127.0.0.1:8765` on the
bot host, then restart the bot and open the public URL. The dashboard binds
only to loopback, so do not expose port 8765 directly to the internet. For a
local-only trial, `http://localhost:8765` is permitted as the public URL if it
is also registered in Discord OAuth2. A public HTTPS domain and the OAuth2
client secret are still required for access away from the bot's PC. Treat
`Data/dashboard.db` and retained ticket transcripts as private server data and
back them up securely. Appeals record decisions; staff must perform any
unban or other Discord action separately. The bot attempts to DM the member
after an appeal decision and DM a newly assigned ticket staff member. If
Discord blocks the DM, the dashboard reports that follow-up is needed.
Discord's native AutoMod can be
configured in Server Settings alongside the bot's optional anti-spam controls.

## Data and privacy

- Ticket attachments remain on Discord; the bot no longer uploads them to a
  third-party image service.
- Ticket transcript files are uniquely named and deleted locally after the
  Discord upload attempt.
- Runtime `.db` files, credentials, virtual environments, and transcript text
  files are ignored by Git.
- Edited/deleted message content and attachment URLs are excluded from logs by
  default. Enable the clearly labeled privacy option in the setup GUI only if
  your server policy requires them.
- Twitch access tokens are cached in memory only. Sent stream IDs are retained
  locally in SQLite so restarts do not repeat old notifications.
- The databases included with this extracted copy contain existing Discord
  records. Back them up and treat them as private; do not publish the archive.
