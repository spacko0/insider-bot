"""Dot-prefix commands for the insider lists."""
from __future__ import annotations

import logging
import os
import threading
import time

from commands.format import format_banned, format_news, format_registered
from commands.urls import classify_url, split_news_args
from commands.titles import fetch_page_title
from store.registry import RegistryError
from utils.config import AUTH_TIER_RANK
from utils.irc_burst import send_via_connection
from utils.irc_format import is_znc_playback

logger = logging.getLogger(__name__)

PUBLIC_COMMANDS = frozenset({"help", "register"})
MEMBER_COMMANDS = frozenset({"news", "addnews", "banned", "ban", "banuser", "unregister"})
ADMIN_COMMANDS = frozenset({"registered", "update", "unban", "delnews", "join", "part"})
OWNER_COMMANDS = frozenset({"reconnect", "exit", "adduser", "deluser"})

_ROLE_LABELS = {
    "owner": "owner",
    "coder": "coder",
    "team_leaders": "team leader",
    "admin": "admin",
    "moderators": "moderator",
    "torrent_moderators": "bot user",
}
_ROLE_HELP = "bot user, moderator, admin, team leader, coder, or owner"


class CommandHandler:
    def __init__(self, config, connection, registry, application=None):
        self.config = config
        self.connection = connection
        self.registry = registry
        self.application = application

    def handle(self, event) -> bool:
        try:
            message = (event.get("message") or "").strip()
            if is_znc_playback(message):
                return False
            source = (event.get("source") or "unknown").strip()
            prefix = self.config.COMMAND_PREFIX
            if not message.startswith(prefix):
                return False
            body = message[len(prefix) :].strip()
            if not body:
                return False
            command, _, args = body.partition(" ")
            command = command.lower()
            args = args.strip()
            nick = source.split("!")[0].strip()
            if nick.lower() == (self.connection.nickname or "").lower() and nick.lower() != "terminal":
                return False
            if not self._delivery_ok(event, command):
                logger.info(
                    "Ignored %s%s from %s to %s",
                    prefix,
                    command,
                    nick,
                    event.get("incoming_target") or event.get("target") or "",
                )
                return False
            logger.info("Command %s%s from %s", prefix, command, nick)

            if command in PUBLIC_COMMANDS:
                return self._dispatch(command, nick, event, args)
            if command in MEMBER_COMMANDS:
                if not self._is_member(nick):
                    return False
                return self._dispatch(command, nick, event, args)
            if command in ADMIN_COMMANDS:
                if not self._is_admin(nick):
                    return False
                return self._dispatch(command, nick, event, args)
            if command in OWNER_COMMANDS:
                if not self._is_owner(nick):
                    return False
                return self._dispatch(command, nick, event, args)
            if self._is_member(nick):
                self._reply(event, f"Unknown command: {prefix}{command}. Try {prefix}help")
            return False
        except Exception:
            logger.error("Command error", exc_info=True)
            self._reply(event, "Command processing error")
            return False

    def _dispatch(self, command: str, nick: str, event: dict, args: str) -> bool:
        handler = getattr(self, f"cmd_{command}", None)
        if handler is None:
            return False
        return bool(handler(nick, event, args))

    def _nick_only(self, username: str) -> str:
        return (username or "").split("!")[0].strip()

    def _rank(self, username: str) -> int:
        nick = self._nick_only(username)
        if nick.lower() == "terminal":
            return AUTH_TIER_RANK["owner"]
        stored = AUTH_TIER_RANK.get(self.registry.bot_user_role(nick) or "", 0)
        return max(self.config.user_rank(nick), stored)

    def _is_admin(self, username: str) -> bool:
        return self._rank(username) >= AUTH_TIER_RANK["admin"]

    def _is_owner(self, username: str) -> bool:
        nick = self._nick_only(username)
        if nick.lower() == "terminal":
            return True
        if self.config.is_owner(nick):
            return True
        return self.registry.bot_user_role(nick) == "owner"

    def _role_phrase(self, tier: str) -> str:
        label = _ROLE_LABELS.get(tier, tier.replace("_", " "))
        article = "an" if label[:1] in "aeiou" else "a"
        return f"{article} {label}"

    def _parse_role(self, text: str) -> str | None:
        token = " ".join((text or "bot user").split()).lower().replace("-", " ").replace("_", " ")
        token = "_".join(token.split())
        return self.config._normalize_tier_token(token)

    def _is_member(self, nick: str) -> bool:
        if nick.lower() == "terminal":
            return True
        if self.config.is_bot_user(nick):
            return True
        if self.registry.is_bot_user(nick):
            return True
        return self.registry.is_registered(nick)

    def _delivery_ok(self, event: dict, command: str) -> bool:
        if event.get("source") == "terminal" or event.get("target") == "terminal":
            return True
        incoming = event.get("incoming_type")
        raw_target = event.get("incoming_target") or ""
        if incoming == "privmsg":
            target = raw_target.strip()
            if target.startswith(("#", "&")):
                return False
            return True
        if incoming == "pubmsg":
            channel = self.config.normalize_irc_channel(raw_target)
            if channel not in self.config.effective_command_channels:
                return False
            if command in PUBLIC_COMMANDS:
                return True
            allowed = self.config.pubmsg_allowed_commands_for_channel(channel)
            if allowed is not None and command not in allowed:
                return False
            if command in MEMBER_COMMANDS:
                return True
            min_rank = self.config.pubmsg_min_rank_for_channel(channel)
            if min_rank > 0 and self._rank(event.get("source") or "") < min_rank:
                return False
            return True
        return True

    def _reply(self, event: dict, lines, target: str | None = None) -> None:
        if isinstance(lines, str):
            lines = [lines]
        lines = [line for line in lines if line is not None and str(line) != ""]
        if not lines:
            return
        final = target or event.get("target") or event.get("source")
        if final == "terminal":
            print("\n".join(lines), flush=True)
            return
        send_via_connection(
            self.connection,
            final,
            lines,
            max_lines=self.config.IRC_BURST_MAX_LINES,
            pause_sec=self.config.IRC_BURST_PAUSE_SECONDS,
        )

    def _colors(self) -> bool:
        return bool(self.config.IRC_COLORS)

    def _prefix(self) -> str:
        return self.config.COMMAND_PREFIX

    def cmd_help(self, nick: str, event: dict, args: str) -> bool:
        topic = args.split(maxsplit=1)[0].lower() if args.strip() else ""
        if topic == "admin":
            return self._help_admin(nick, event)
        if topic:
            self._reply(event, f"Unknown help topic. Try {self._prefix()}help or {self._prefix()}help admin")
            return False
        prefix = self._prefix()
        lines = [
            "InsiderBot",
            f"{prefix}help — this list",
            f"{prefix}register <site> <position> — add or update your position on a site",
        ]
        if self._is_member(nick):
            lines.extend(
                [
                    f"{prefix}unregister [site] — drop one of your sites, or all of them",
                    f"{prefix}news [count] — recent articles and reddit posts",
                    f"{prefix}addnews [title] <url> — add a news URL. The page heading is used when the title is left out",
                    f"{prefix}banned [site] — users banned from sites",
                    f"{prefix}ban <user> [site] <reason> — record a site ban",
                    f"{prefix}banuser <user> [site] <reason> — same as {prefix}ban",
                ]
            )
        if self._is_admin(nick):
            lines.append(f"{prefix}help admin — admin commands")
        if not self._is_member(nick):
            lines.append("News and bans unlock after you register, or if your nick is a bot user.")
        self._reply(event, lines)
        return True

    def _help_admin(self, nick: str, event: dict) -> bool:
        if not self._is_admin(nick):
            return False
        prefix = self._prefix()
        lines = [
            "Admin",
            f"{prefix}registered [site] — registered users and sites (PM from a channel)",
            f"{prefix}update <nick> <site> <position> — set a nick's site and position",
            f"{prefix}unban <user> [site] — remove a ban",
            f"{prefix}delnews <id> — remove a news item",
            f"{prefix}join <#channel>",
            f"{prefix}part <#channel>",
        ]
        if self._is_owner(nick):
            lines.extend(
                [
                    f"{prefix}adduser <nick> [role] — add a bot user ({_ROLE_HELP})",
                    f"{prefix}deluser <nick> — remove a bot user added from IRC",
                ]
            )
        self._reply(event, lines)
        return True

    def cmd_register(self, nick: str, event: dict, args: str) -> bool:
        prefix = self._prefix()
        parts = args.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            self._reply(event, f"Usage: {prefix}register <site> <position>")
            return False
        site, position = parts[0], parts[1].strip()
        try:
            status = self.registry.register(nick, site, position, by=nick)
        except RegistryError as exc:
            self._reply(event, str(exc))
            return False
        verb = "Updated" if status == "updated" else "Registered"
        self._reply(event, f"{verb} {nick} on {site} as {position}.")
        return True

    def cmd_update(self, nick: str, event: dict, args: str) -> bool:
        prefix = self._prefix()
        parts = args.split(maxsplit=2)
        if len(parts) < 3 or not parts[2].strip():
            self._reply(event, f"Usage: {prefix}update <nick> <site> <position>")
            return False
        target, site, position = parts[0], parts[1], parts[2].strip()
        try:
            status = self.registry.register(target, site, position, by=nick)
        except RegistryError as exc:
            self._reply(event, str(exc))
            return False
        verb = "Updated" if status == "updated" else "Registered"
        self._reply(event, f"{verb} {target} on {site} as {position}.")
        return True

    def cmd_unregister(self, nick: str, event: dict, args: str) -> bool:
        prefix = self._prefix()
        text = args.strip()
        if not text:
            if not self.registry.unregister(nick):
                self._reply(event, f"{nick} is not registered.")
                return False
            self._reply(event, f"Unregistered {nick}.")
            return True
        target, _, site = text.partition(" ")
        site = site.strip()
        if site:
            if target.lower() != nick.lower() and not self._is_admin(nick):
                return False
        elif self._owns_site(nick, target):
            site = target
            target = nick
        elif target.lower() != nick.lower() and not self._is_admin(nick):
            return False
        if not self.registry.unregister(target, site or None):
            where = f" on {site}" if site else ""
            self._reply(event, f"{target} is not registered{where}.")
            return False
        if site:
            self._reply(event, f"Unregistered {target} on {site}.")
        else:
            self._reply(event, f"Unregistered {target}.")
        return True

    def _owns_site(self, nick: str, site: str) -> bool:
        key = " ".join(site.split()).casefold()
        return any(row.get("site_key") == key for row in self.registry.registrations_for(nick))

    def cmd_news(self, nick: str, event: dict, args: str) -> bool:
        prefix = self._prefix()
        limit = self.config.NEWS_DEFAULT_LIMIT
        if args:
            if not args.isdigit():
                self._reply(event, f"Usage: {prefix}news [count]")
                return False
            limit = min(self.config.NEWS_MAX_LIMIT, max(1, int(args)))
        rows = self.registry.list_news(limit)
        self._reply(event, format_news(rows, colors=self._colors(), prefix=prefix))
        return True

    def cmd_addnews(self, nick: str, event: dict, args: str) -> bool:
        prefix = self._prefix()
        parsed = split_news_args(args)
        if parsed is None:
            self._reply(event, f"Usage: {prefix}addnews [title] <url>")
            return False
        url, title = parsed
        kind = classify_url(url)
        if not title:
            title = fetch_page_title(url) or ""
        try:
            status, row = self.registry.add_news(url.strip(), kind, title, by=nick)
        except RegistryError as exc:
            self._reply(event, str(exc))
            return False
        if status == "duplicate":
            self._reply(event, f"Already listed as #{row['id']} ({row['kind']}).")
            return False
        if status == "refreshed":
            self._reply(event, f"Updated #{row['id']}: {row['note']}")
            return True
        label = "reddit post" if kind == "reddit" else "article"
        if title:
            self._reply(event, f"Added #{row['id']} ({label}): {title}")
        else:
            self._reply(event, f"Added #{row['id']} ({label}).")
        return True

    def cmd_banned(self, nick: str, event: dict, args: str) -> bool:
        rows = self.registry.list_banned(args or None)
        self._reply(event, format_banned(rows, colors=self._colors()))
        return True

    def cmd_ban(self, nick: str, event: dict, args: str) -> bool:
        return self._record_ban(nick, event, args)

    def cmd_banuser(self, nick: str, event: dict, args: str) -> bool:
        return self._record_ban(nick, event, args)

    def _record_ban(self, nick: str, event: dict, args: str) -> bool:
        prefix = self._prefix()
        parts = args.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            self._reply(event, f"Usage: {prefix}ban <user> [site] <reason>")
            return False
        user, rest = parts[0], parts[1].strip()
        rows = self.registry.registrations_for(user)
        by_site = {str(row.get("site_key") or ""): row.get("site") for row in rows}
        head, _, tail = rest.partition(" ")
        head_key = " ".join(head.split()).casefold()
        if head_key in by_site and tail.strip():
            site = by_site[head_key]
            reason = tail.strip()
        elif len(rows) == 1:
            site = rows[0]["site"]
            reason = rest
        elif len(rows) > 1:
            names = ", ".join(row["site"] for row in rows)
            self._reply(event, f"{user.strip()} is on {names}. Usage: {prefix}ban <user> <site> <reason>")
            return False
        elif tail.strip():
            site = head
            reason = tail.strip()
        else:
            self._reply(event, f"{user.strip()} is not registered. Usage: {prefix}ban <user> <site> <reason>")
            return False
        try:
            status = self.registry.ban(user, site, reason, by=nick)
        except RegistryError as exc:
            self._reply(event, str(exc))
            return False
        verb = "Updated ban" if status == "updated" else "Banned"
        self._reply(event, f"{verb} for {user.strip()} on {site}: {reason}")
        return True

    def cmd_registered(self, nick: str, event: dict, args: str) -> bool:
        rows = self.registry.list_registered(args or None)
        lines = format_registered(rows, colors=self._colors())
        if event.get("incoming_type") == "pubmsg":
            self._reply(event, lines, target=nick)
            self._reply(event, "Sent the registered list in a private message.")
            return True
        self._reply(event, lines)
        return True

    def cmd_unban(self, nick: str, event: dict, args: str) -> bool:
        prefix = self._prefix()
        parts = args.split(maxsplit=1)
        if not parts or not parts[0]:
            self._reply(event, f"Usage: {prefix}unban <user> [site]")
            return False
        user = parts[0]
        site = parts[1] if len(parts) > 1 else None
        removed = self.registry.unban(user, site)
        if not removed:
            self._reply(event, f"No ban matched {user}" + (f" on {site}" if site else "") + ".")
            return False
        where = f" on {site.strip()}" if site else ""
        self._reply(event, f"Removed {removed} ban(s) for {user.strip()}{where}.")
        return True

    def cmd_delnews(self, nick: str, event: dict, args: str) -> bool:
        prefix = self._prefix()
        token = args.split(maxsplit=1)[0] if args else ""
        if not token.isdigit():
            self._reply(event, f"Usage: {prefix}delnews <id>")
            return False
        if not self.registry.delete_news(int(token)):
            self._reply(event, f"No news item #{token}.")
            return False
        self._reply(event, f"Removed news #{token}.")
        return True

    def cmd_join(self, nick: str, event: dict, args: str) -> bool:
        if not args:
            self._reply(event, f"Usage: {self._prefix()}join <#channel>")
            return False
        self.connection.join(args.split()[0])
        self._reply(event, f"Joining {args.split()[0]}")
        return True

    def cmd_part(self, nick: str, event: dict, args: str) -> bool:
        if not args:
            self._reply(event, f"Usage: {self._prefix()}part <#channel>")
            return False
        self.connection.part(args.split()[0])
        self._reply(event, f"Left {args.split()[0]}")
        return True

    def cmd_adduser(self, nick: str, event: dict, args: str) -> bool:
        prefix = self._prefix()
        parts = args.split(maxsplit=1)
        if not parts or not parts[0].strip():
            self._reply(event, f"Usage: {prefix}adduser <nick> [role]")
            return False
        target = parts[0].strip()
        role = self._parse_role(parts[1] if len(parts) > 1 else "bot user")
        if role is None:
            self._reply(event, f"Unknown role. Use {_ROLE_HELP}.")
            return False
        phrase = self._role_phrase(role)
        env_rank = self.config.user_rank(target)
        if env_rank >= AUTH_TIER_RANK[role]:
            current = self.config.resolve_user_auth_tier(target) or "torrent_moderators"
            self._reply(
                event,
                f"{target} is already {self._role_phrase(current)} from the settings file.",
            )
            return False
        try:
            status = self.registry.add_bot_user(target, by=nick, role=role)
        except RegistryError as exc:
            self._reply(event, str(exc))
            return False
        if status == "exists":
            self._reply(event, f"{target} is already {phrase}.")
            return False
        if status == "updated":
            self._reply(event, f"Updated {target} to {phrase}.")
            return True
        self._reply(event, f"Added {target} as {phrase}.")
        return True

    def cmd_deluser(self, nick: str, event: dict, args: str) -> bool:
        prefix = self._prefix()
        parts = args.split()
        if len(parts) != 1:
            self._reply(event, f"Usage: {prefix}deluser <nick>")
            return False
        target = parts[0]
        removed = self.registry.remove_bot_user(target)
        if self.config.is_bot_user(target):
            self._reply(event, f"{target} stays a bot user from the settings file.")
            return False
        if not removed:
            self._reply(event, f"{target} is not a bot user added from IRC.")
            return False
        self._reply(event, f"Removed bot user {target}.")
        return True

    def cmd_reconnect(self, nick: str, event: dict, args: str) -> bool:
        reply_target = event.get("target")

        def _run():
            try:
                self.connection.should_reconnect = True
                ok = self.connection.reconnect(wait_for_welcome=True)
                msg = (
                    "IRC reconnect complete — ready (001 received)."
                    if ok
                    else "IRC reconnect finished without a 001 welcome. Check the log."
                )
                self._reply(event, msg, target=reply_target)
            except Exception as exc:
                logger.error("reconnect failed: %s", exc, exc_info=True)
                self._reply(event, f"IRC reconnect error: {exc}", target=reply_target)

        self._reply(event, "IRC reconnect started.", target=reply_target)
        threading.Thread(target=_run, daemon=True, name="IRCReconnectCmd").start()
        return True

    def cmd_exit(self, nick: str, event: dict, args: str) -> bool:
        self._reply(event, "Shutting down...")
        app = self.application
        if app is not None:
            app.schedule_force_exit(1.0)
        else:
            logger.error("exit: application reference missing; forcing process exit")
            time.sleep(1)
            os._exit(0)
        return True
