"""Shared fixtures for InsiderBot tests."""
from __future__ import annotations

from pathlib import Path

from commands.handler import CommandHandler
from store.registry import Registry
from utils.config import Config


def base_env(db_path: Path, **overrides: str) -> dict:
    env = {
        "IRC_SERVER": "irc.example.org",
        "IRC_PORT": "6667",
        "IRC_NICKNAME": "InsiderBot",
        "IRC_CHANNELS": "#insiders,#staff",
        "IRC_COMMAND_CHANNELS": "#insiders,#staff:admin",
        "BOT_OWNER": "OwnerNick",
        "ADMIN_GROUP": "Alice",
        "MODERATORS": "ModNick",
        "BOT_USERS": "Bob",
        "COMMAND_PREFIX": ".",
        "IRC_COLORS": "false",
        "IRC_BURST_PAUSE_SECONDS": "0",
        "IRC_BURST_MAX_LINES": "20",
        "NEWS_DEFAULT_LIMIT": "8",
        "NEWS_MAX_LIMIT": "25",
        "IRC_HEALTH_MONITOR": "false",
        "AUTO_JOIN_CHANNELS": "false",
        "DATABASE_PATH": str(db_path),
    }
    env.update(overrides)
    return env


class FakeConn:
    def __init__(self, nickname: str = "InsiderBot"):
        self.nickname = nickname
        self.sent: list[tuple[str, str]] = []
        self.joined: list[str] = []
        self.parted: list[str] = []

    def send_message(self, target, message):
        self.sent.append((target, message))

    def join(self, channel):
        self.joined.append(channel)

    def part(self, channel):
        self.parted.append(channel)


def make_handler(tmp_path: Path, **env_overrides):
    config = Config(base_env(tmp_path / "insider.db", **env_overrides))
    registry = Registry(config.DATABASE_PATH)
    connection = FakeConn(config.IRC_NICKNAME)
    return CommandHandler(config, connection, registry), connection, registry


def visible(connection: FakeConn) -> str:
    text = "\n".join(message for _target, message in connection.sent)
    return text.replace("\u00a0", " ").replace("\x11", "")


def channel_event(message: str, nick: str, channel: str = "#insiders") -> dict:
    return {
        "message": message,
        "source": nick,
        "target": channel,
        "incoming_type": "pubmsg",
        "incoming_target": channel,
    }


def pm_event(message: str, nick: str, bot: str = "InsiderBot") -> dict:
    return {
        "message": message,
        "source": nick,
        "target": nick,
        "incoming_type": "privmsg",
        "incoming_target": bot,
    }
