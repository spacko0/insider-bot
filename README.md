# InsiderBot

IRC bot for a private roster of people, the sites they work on, news links, and site bans. It has its own repository, its own `.env`, and its own database. It does not read settings from any other bot.

Commands use a `.` prefix. Run it with its own nick. If you use ZNC, give it its own user (for example `InsiderBot/Network`) and set `IRC_SERVER` to that bouncer. One bouncer login holds one IRC nick, so a shared login will not receive private messages sent to a different nick.

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

That starts a detached session named `insider-bot`. Attach with `tmux attach -t insider-bot`. Detach with `Ctrl-b` then `d`. Stop with `tmux kill-session -t insider-bot`.

## Two kinds of people

**Bot users** are nicks listed in `.env` (`BOT_OWNER`, `CODER`, `TEAM_LEADERS`, `ADMIN_GROUP`, `MODERATORS`, `TORRENT_MODERATORS`, `BOT_USERS`, plus legacy `ADMIN_USERS` / `STAFF_USERS`). Higher tiers include the lower ones. Owner commands require the owner tier exactly.

**Registered users** are nicks stored by `.register <site> <position>`. The same nick can be on more than one site, each with its own position. A bot admin sets someone else's site and position with `.update <nick> <site> <position>`.

Member commands (news and bans) work for a registered nick or any bot user.

## Commands

| Command | Who |
| --- | --- |
| `.register <site> <position>` | Anyone, for their own nick. Repeat it to add another site or change the position on a site. |
| `.help` | Anyone |
| `.news [count]` | Registered users and bot users |
| `.addnews [title] <url>` | Registered users and bot users. Reddit hosts are stored as reddit posts; other http(s) links are articles. Leave the title out and the page heading is stored. |
| `.banned [site]` | Registered users and bot users |
| `.banuser <user> <site> <reason>` | Registered users and bot users. Site is included so a ban records where it happened. |
| `.unregister [site]` | Your own sites. Omit the site to drop every site. Admins and above can use `.unregister <nick> [site]`. |
| `.registered [site]` | Bot admins and above. From a channel the list is sent in a private message. |
| `.update <nick> <site> <position>` | Bot admins and above. Sets that nick's position on a site, or adds the site. |
| `.unban <user> [site]` | Bot admins and above. Omit the site to clear every site for that nick. |
| `.delnews <id>` | Bot admins and above |
| `.join <#channel>` / `.part <#channel>` | Bot admins and above |
| `.reconnect` / `.exit` | Bot owner |

`.registered` is grouped by site, with nick and position on each line. `.banned` is grouped by site, with the reason and who added it.

Public commands are accepted in `IRC_COMMAND_CHANNELS` (or `IRC_CHANNELS` when that list is empty) and in a private message to the bot. A `:tier` suffix on a command channel still blocks admin and owner commands from nicks below that tier. News, bans, `.register`, and `.help` stay available to the people listed above even in a rank-gated channel.

Lists are stored in `data/insider.db`.
