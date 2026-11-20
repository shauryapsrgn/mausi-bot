# Mausi ji: the house bot for *mera mirchidaar bhosada*

Mausi ji is **already invited to your server**. Its role sits just below *ranivati hijdavati*. It shows as offline until you run this program.

## What it does

- **Reaction roles:** panels for pronouns, vibes, colours, identity, and interests and pings.
- **Welcome messages:** a welcome post, an optional DM, an optional goodbye post, and the *abhi tak shareef* auto-role.
- **Moderation:**
  - Each command only works for the tier it belongs to: helpers (*rishwatkhor munshi*), mods (*lathi-charge wali aunty*) and co-admins.
  - Nobody can moderate someone at or above their own role.
  - Every action goes to the mod log.
- **Auto-reactions:** say "slay", "mother", "chai", "drama", "aunty", "happy birthday" and other trigger words, and Mausi ji reacts. Each channel has a cooldown, so chats don't drown in emoji.
- **Starboard:** a message that gets 3 ⭐ is reposted in #tareef-ki-deewar.
- **Join-to-create voice:** join "➕ naya kamra banao" and you get your own room. Rename, limit or lock it with `/kamra`. It's deleted when it empties.
- **Embed maker:** make fancy embed posts (rules, announcements, event cards) with a live preview in the dashboard and saved templates, or use `/embed create` and `/embed edit` in Discord.
- **Locked commands:** every mod and admin command (warn, timeout, kick, ban, purge, lock, slowmode, embed and the rest) works only for the tier you choose, which you set on the dashboard's **Command access** page. Ordinary members can't even see those commands; they only get `/help` and `/kamra`.
- **Role sorting:** one click puts every role in order: mods, khaas log, colours, vibes, members, pronouns, then *abhi tak shareef*.
- **Dashboard:** a web page where you change all of the above without typing commands.
- **`/panel`** shows a quick status view inside Discord.

## 1. Get the token (2 minutes)

1. Open <https://discord.com/developers/applications>, then **Mausi ji → Bot**.
2. Click **Reset Token** and copy it. **This is the bot's password.** Never paste it in chat, on GitHub, or anywhere else.
3. Server Members Intent and Message Content Intent are already switched on.

## 2. Run it

You need Python 3.10 or newer.

```bash
pip install -r requirements.txt
cp .env.example .env      # then open .env and fill in DISCORD_TOKEN and DASHBOARD_PASSWORD
python main.py
```

When you see `Mausi ji aa gayi`, the bot is online. Open **http://localhost:8080** and log in with your `DASHBOARD_PASSWORD`.

## 3. First time in the dashboard

1. **Roles & channels → Create missing channels.** This makes #mausi-ke-commands, #tareef-ki-deewar (read-only), #drag-ka-dangal, #sher-o-shayari and the "➕ naya kamra banao" voice lobby, and connects the starboard and the lobby.
2. **Roles & channels → Sort roles in Discord now.** This finishes the role ladder, moving the colour roles above the vibe roles.
3. **Mod tiers:**
   - helpers = *rishwatkhor munshi*
   - mods = *lathi-charge wali aunty*
   - admins = *ranivati hijdavati*
   - mod log = #aunty-ki-kitty-party

   `/setup quickstart` in Discord fills all of this in at once.
4. **Welcome:** set the channel to #aao-baitho-intro-do, the auto-role to *abhi tak shareef*, and edit the text if you like.
5. **Role panels:** post `pronouns`, `colours`, `vibes`, `identity` and `interests` in #mata-ke-roles. Leave "create roles" ticked so the identity and interest roles get made.

## 4. Keeping it online 24/7

The bot and the dashboard only run while `python main.py` is running.

- **Railway or Render:**
  - Upload this folder.
  - Set `DISCORD_TOKEN`, `GUILD_ID`, `DASHBOARD_PASSWORD` and `DASHBOARD_HOST=0.0.0.0` as environment variables.
  - The `Procfile` starts it, and the host gives you a URL for the dashboard.
  - Use a long password, since anyone with the URL can reach the login page.
- **Your own computer:** fine for testing. The bot sleeps when your computer does.

Settings live in `data.json`. Back it up if you move hosts.

## Who can do what (defaults)

You can change who can use each locked command on the dashboard's **Command access** page.

| | Helpers | Mods | Co-admins / Administrator |
|---|:-:|:-:|:-:|
| `/warn`, `/warnings`, `/untimeout` | ✅ | ✅ | ✅ |
| `/timeout` | up to 1h | up to 28d | up to 28d |
| `/kick`, `/ban`, `/unban`, `/purge`, `/slowmode`, `/lock`, `/unlock`, `/clearwarnings`, `/embed` | | ✅ | ✅ |
| `/panel`, `/setup …`, `/welcome …`, `/reactionroles …`, `/autoreact …`, `/starboard …`, `/voicerooms …`, dashboard | | | ✅ |
| `/help`, `/kamra …` (your own room) | everyone | | |

There are two locks on every one of these commands:

- **Discord hides them** from members who don't have the matching Discord permission.
- **Mausi ji double-checks the tier** before doing anything.

If you open a command up to a lower tier, also give that role the Discord permission. Otherwise, allow the command for that role under Server Settings → Integrations → Mausi ji.

## Welcome message placeholders

- `{user}` mentions the new member.
- `{name}` is their display name.
- `{server}` is the server name.
- `{count}` is the member count.
- `{#channel-name}` becomes a clickable channel link, for example `{#samvidhaan}`.

## Files

```
main.py                     starts everything, syncs slash commands
bot/storage.py              data.json settings + defaults (triggers, role order)
bot/actions.py              shared: sort roles, create channels, post panels
bot/util.py                 tiers, checks, placeholders, durations
bot/cogs/dashboard.py       the web dashboard
bot/cogs/welcome.py         join/leave, DM, auto-roles
bot/cogs/reaction_roles.py  reaction-role panels
bot/cogs/moderation.py      warn/timeout/kick/ban/purge/lock
bot/cogs/autoreact.py       keyword reactions
bot/cogs/starboard.py       starboard
bot/cogs/voicerooms.py      join-to-create voice
bot/cogs/embeds.py          /embed create and /embed edit
bot/cogs/setup.py           tiers, log channel, quickstart, channels, sortroles
bot/cogs/panel.py           /panel and /help
presets.json                reaction-role panels (edit freely)
```
