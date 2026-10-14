"""Dot-prefix commands for the insider lists."""
from __future__ import annotations

import logging
import os
import re
import threading
import time

from commands.format import format_banned, format_news, format_registered
from commands.urls import classify_url
from store.registry import RegistryError
from utils.irc_burst import send_via_connection

logger = logging.getLogger(__name__)

_PLAYBACK_PREFIX = re.compile(
    r"^\[(?:\d{4}-\d{2}-\d{2}[ T])?\d{1,2}:\d{2}(?::\d{2})?\]\s*"
)

PUBLIC_COMMANDS = frozenset({"help", "register"})
MEMBER_COMMANDS = frozenset({"news", "addnews", "banned", "banuser", "unregister"})
ADMIN_COMMANDS = frozenset({"registered", "unban", "delnews", "join", "part"})
OWNER_COMMANDS = frozenset({"reconnect", "exit"})


class CommandHandler:
    def __init__(self, config, connection, registry, application=None):
        self.config = config
        self.connection = connection
        self.registry = registry
        self.application = application

    def handle(self, event) -> bool:
        try:
            message = _PLAYBACK_PREFIX.sub("", (event.get("message") or "").strip())
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
                    self._reply(
                        event,
                        f"Register first: {prefix}register <nick> <site> <position>",
                    )
                    return False
                return self._dispatch(command, nick, event, args)
            if command in ADMIN_COMMANDS:
                if not self.config.is_admin_or_above(nick):
                    self._reply(event, "That command is limited to bot admins and above.")
                    return False
                return self._dispatch(command, nick, event, args)
            if command in OWNER_COMMANDS:
                if not self.config.is_owner(nick):
                    self._reply(event, "That command is limited to the bot owner.")
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

    def _is_member(self, nick: str) -> bool:
        if nick.lower() == "terminal":
            return True
        if self.config.is_bot_user(nick):
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
            if min_rank > 0 and self.config.user_rank(event.get("source") or "") < min_rank:
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
        prefix = self._prefix()
        lines = [
            "InsiderBot",
            f"{prefix}register <nick> <site> <position> — register a nick, site, and position",
            f"{prefix}help — this list",
        ]
        if self._is_member(nick):
            lines.extend(
                [
                    f"{prefix}news [count] — recent articles and reddit posts",
                    f"{prefix}addnews <url> [note] — add a news URL",
                    f"{prefix}banned [site] — users banned from sites",
                    f"{prefix}banuser <user> <site> <reason> — record a site ban",
                    f"{prefix}unregister <nick> — remove your registration",
                ]
            )
        if self.config.is_admin_or_above(nick):
            lines.extend(
                [
                    f"{prefix}registered [site] — registered nicks (admins and above; PM from a channel)",
                    f"{prefix}unban <user> [site] — remove a ban",
                    f"{prefix}delnews <id> — remove a news item",
                    f"{prefix}join <#channel>",
                    f"{prefix}part <#channel>",
                ]
            )
        if self.config.is_owner(nick):
            lines.extend([f"{prefix}reconnect", f"{prefix}exit"])
        if not self._is_member(nick):
            lines.append("News, bans, and the registered list unlock after you register, or if your nick is a bot user.")
        self._reply(event, lines)
        return True

    def cmd_register(self, nick: str, event: dict, args: str) -> bool:
        prefix = self._prefix()
        parts = args.split(maxsplit=2)
        if len(parts) < 3:
            self._reply(event, f"Usage: {prefix}register <nick> <site> <position>")
            return False
        target, site, position = parts
        if target.lower() != nick.lower() and not self.config.is_admin_or_above(nick):
            self._reply(event, "You can register your own nick. Bot admins can register someone else.")
            return False
        try:
            status = self.registry.register(target, site, position, by=nick)
        except RegistryError as exc:
            self._reply(event, str(exc))
            return False
        verb = "Updated" if status == "updated" else "Registered"
        self._reply(event, f"{verb} {target.strip()} on {site.strip()} as {position.strip()}.")
        return True

    def cmd_unregister(self, nick: str, event: dict, args: str) -> bool:
        prefix = self._prefix()
        target = args.split(maxsplit=1)[0] if args else ""
        if not target:
            self._reply(event, f"Usage: {prefix}unregister <nick>")
            return False
        if target.lower() != nick.lower() and not self.config.is_admin_or_above(nick):
            self._reply(event, "You can unregister your own nick. Bot admins can unregister someone else.")
            return False
        if not self.registry.unregister(target):
            self._reply(event, f"{target} is not registered.")
            return False
        self._reply(event, f"Unregistered {target}.")
        return True

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
        if not args:
            self._reply(event, f"Usage: {prefix}addnews <url> [note]")
            return False
        url, _, note = args.partition(" ")
        kind = classify_url(url)
        if kind is None:
            self._reply(event, "Give an http(s) URL. Reddit links are stored as reddit posts.")
            return False
        try:
            status, row = self.registry.add_news(url.strip(), kind, note.strip(), by=nick)
        except RegistryError as exc:
            self._reply(event, str(exc))
            return False
        if status == "duplicate":
            self._reply(event, f"Already listed as #{row['id']} ({row['kind']}).")
            return False
        label = "reddit post" if kind == "reddit" else "article"
        self._reply(event, f"Added #{row['id']} ({label}).")
        return True

    def cmd_banned(self, nick: str, event: dict, args: str) -> bool:
        rows = self.registry.list_banned(args or None)
        self._reply(event, format_banned(rows, colors=self._colors()))
        return True

    def cmd_banuser(self, nick: str, event: dict, args: str) -> bool:
        prefix = self._prefix()
        parts = args.split(maxsplit=2)
        if len(parts) < 3:
            self._reply(event, f"Usage: {prefix}banuser <user> <site> <reason>")
            return False
        user, site, reason = parts
        try:
            status = self.registry.ban(user, site, reason, by=nick)
        except RegistryError as exc:
            self._reply(event, str(exc))
            return False
        verb = "Updated ban" if status == "updated" else "Banned"
        self._reply(event, f"{verb} for {user.strip()} on {site.strip()}: {reason.strip()}")
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
