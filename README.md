# InsiderBot

IRC bot for a private roster of people, the sites they work on, news links, and site bans. It is a separate project from mod-bot. The IRC connection (TLS, SASL or ZNC, health checks, reconnect) and the nick tiers use the same settings.

Commands use a `.` prefix so they do not collide with mod-bot's `!` commands in a shared channel. Run InsiderBot with its own nick. If you use ZNC, give it its own user (for example `InsiderBot/Network`), not mod-bot's.

**Version:** [`version.py`](version.py)

## Requirements

- Python 3.10+
- Network access to your IRC server

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python main.py
```

On Unix, activate with `source .venv/bin/activate`.

Set at least `IRC_SERVER`, `IRC_NICKNAME`, and `BOT_OWNER`.

The console prompt accepts the same commands. That session counts as the bot owner.

## tmux

On the server, from the repo root after `.env` is filled in:

```bash
./deploy/start-insiderbot-tmux.sh
```

That starts a detached session named `insider-bot`, separate from mod-bot. Attach with `tmux attach -t insider-bot`. Detach with `Ctrl-b` then `d`. Stop with `tmux kill-session -t insider-bot`.

## Two kinds of people

**Bot users** are nicks listed in `.env` (`BOT_OWNER`, `CODER`, `TEAM_LEADERS`, `ADMIN_GROUP`, `MODERATORS`, `TORRENT_MODERATORS`, `BOT_USERS`, plus legacy `ADMIN_USERS` / `STAFF_USERS`). Higher tiers include the lower ones. Owner commands require the owner tier exactly, same as mod-bot.

**Registered users** are nicks stored by `.register`, with a site and a position. Anyone can register their own nick. A bot admin (admin, team leader, coder, or owner) can register someone else.

Member commands (news and bans) work for a registered nick or any bot user.

## Commands

| Command | Who |
| --- | --- |
| `.register <nick> <site> <position>` | Anyone, for their own nick. Admins and above can register another nick. |
| `.help` | Anyone |
| `.news [count]` | Registered users and bot users |
| `.addnews <url> [note]` | Registered users and bot users. Reddit hosts are stored as reddit posts; other http(s) links are articles. |
| `.banned [site]` | Registered users and bot users |
| `.banuser <user> <site> <reason>` | Registered users and bot users. Site is included so a ban records where it happened. |
| `.unregister <nick>` | Your own nick, or any nick if you are an admin or above |
| `.registered [site]` | Bot admins and above. From a channel the list is sent in a private message. |
| `.unban <user> [site]` | Bot admins and above. Omit the site to clear every site for that nick. |
| `.delnews <id>` | Bot admins and above |
| `.join <#channel>` / `.part <#channel>` | Bot admins and above |
| `.reconnect` / `.exit` | Bot owner |

`.registered` is grouped by site, with nick and position on each line. `.banned` is grouped by site, with the reason and who added it.

Public commands are accepted in `IRC_COMMAND_CHANNELS` (or `IRC_CHANNELS` when that list is empty) and in a private message to the bot. A `:tier` suffix on a command channel still blocks admin and owner commands from nicks below that tier. News, bans, `.register`, and `.help` stay available to the people listed above even in a rank-gated channel.

Lists are stored in `data/insider.db`.
