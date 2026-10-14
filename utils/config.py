"""IRC connection settings and nick command tiers.

A higher rank inherits every lower rank.
Owner commands require the owner tier exactly.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, FrozenSet, Mapping, Optional

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent

# Higher number = more privilege.
AUTH_TIER_RANK: Dict[str, int] = {
    "owner": 6,
    "coder": 5,
    "team_leaders": 4,
    "admin": 3,
    "moderators": 2,
    "torrent_moderators": 1,
}

AUTH_TIER_ALIASES: Dict[str, str] = {
    "mods": "moderators",
    "mod": "moderators",
    "staff": "moderators",
    "tor": "torrent_moderators",
    "tors": "torrent_moderators",
    "torrent_mod": "torrent_moderators",
    "torrent_mods": "torrent_moderators",
    "torrentmoderators": "torrent_moderators",
    "torrent_moderator": "torrent_moderators",
    "admin": "admin",
    "admins": "admin",
    "team_lead": "team_leaders",
    "teamlead": "team_leaders",
    "tl": "team_leaders",
    "dev": "coder",
    "devs": "coder",
    "bot_owner": "owner",
    "users": "torrent_moderators",
    "bot": "torrent_moderators",
    "bot_user": "torrent_moderators",
    "bot_users": "torrent_moderators",
}


def read_env_file(path: Path) -> dict[str, str]:
    """Read one env file. Nothing else is consulted."""
    found: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return found
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, _, value = text.partition("=")
        key = key.strip()
        if key:
            found[key] = value.strip().strip('"').strip("'")
    return found


def _env_csv(source: Mapping[str, str], key: str) -> list:
    raw = source.get(key)
    if raw is None:
        raw = ""
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def _flag(source: Mapping[str, str], key: str, default: str = "false") -> bool:
    return str(source.get(key, default)).strip().lower() in ("true", "1", "yes")


class Config:
    def __init__(self, environ: Mapping[str, str] | None = None, env_file: Path | None = None):
        if environ is None:
            path = env_file or (REPO_ROOT / ".env")
            self._env: Mapping[str, str] = read_env_file(path)
            self.settings_path = path
            logger.info("Loaded settings from %s", path)
        else:
            self._env = environ
            self.settings_path = None
        self._load()
        self._validate()

    def _get(self, key: str, default: str = "") -> str:
        raw = self._env.get(key)
        if raw is None or str(raw).strip() == "":
            return default
        return str(raw)

    def _csv(self, key: str) -> list:
        return _env_csv(self._env, key)

    def _load(self) -> None:
        self.AUTO_JOIN_CHANNELS = _flag(self._env, "AUTO_JOIN_CHANNELS", "true")
        self.IRC_SERVER = self._get("IRC_SERVER").strip()
        self.IRC_PORT = int(self._get("IRC_PORT", "6667"))
        self.IRC_NICKNAME = self._get("IRC_NICKNAME").strip()
        self.IRC_CHANNELS = self._csv("IRC_CHANNELS")
        self.IRC_COMMAND_CHANNELS = self._csv("IRC_COMMAND_CHANNELS")
        self.COMMAND_PREFIX = self._get("COMMAND_PREFIX", ".").strip() or "."
        self.IRC_COLORS = _flag(self._env, "IRC_COLORS", "true")
        self.NEWS_DEFAULT_LIMIT = max(1, int(self._get("NEWS_DEFAULT_LIMIT", "8")))
        self.NEWS_MAX_LIMIT = max(self.NEWS_DEFAULT_LIMIT, int(self._get("NEWS_MAX_LIMIT", "25")))
        self.IRC_USE_SASL = _flag(self._env, "IRC_USE_SASL", "false")
        self.SASL_ACCOUNT = self._get("SASL_ACCOUNT").strip()
        self.SASL_PASSWORD = self._get("SASL_PASSWORD")
        self.IRC_USE_ZNC = _flag(self._env, "IRC_USE_ZNC", "false")
        self.ZNC_PASSWORD = self._get("ZNC_PASSWORD")
        self.ZNC_USERNAME = self._get("ZNC_USERNAME").strip()
        self.ZNC_USER = self._get("ZNC_USER").strip()
        self.ZNC_NETWORK = self._get("ZNC_NETWORK").strip()
        self.ZNC_IRC_NICK = self._get("ZNC_IRC_NICK").strip()
        self.IRC_TLS = _flag(self._env, "IRC_TLS", "false")
        self.IRC_TLS_VERIFY = _flag(self._env, "IRC_TLS_VERIFY", "true")
        self._apply_connection_fallbacks()
        self.IRC_WELCOME_TIMEOUT = int(self._get("IRC_WELCOME_TIMEOUT", "90"))
        self.IRC_HEALTH_MONITOR = _flag(self._env, "IRC_HEALTH_MONITOR", "true")
        self.IRC_ACTIVITY_TIMEOUT = int(self._get("IRC_ACTIVITY_TIMEOUT", "900"))
        self.IRC_HEALTH_CHECK_INTERVAL = int(self._get("IRC_HEALTH_CHECK_INTERVAL", "60"))
        self.IRC_STALLED_REGISTRATION_SECONDS = int(self._get("IRC_STALLED_REGISTRATION_SECONDS", "120"))
        client_ping = self._get("IRC_CLIENT_PING").strip().lower()
        if not client_ping:
            self.IRC_CLIENT_PING_ENABLED = self.IRC_USE_ZNC
        else:
            self.IRC_CLIENT_PING_ENABLED = client_ping in ("true", "1", "yes")
        self.IRC_CLIENT_PING_INTERVAL = int(self._get("IRC_CLIENT_PING_INTERVAL", "120"))
        self.IRC_CLIENT_PING_TIMEOUT = int(self._get("IRC_CLIENT_PING_TIMEOUT", "15"))
        self.IRC_RECONNECT_DELAY = int(self._get("IRC_RECONNECT_DELAY", "30"))
        self.IRC_MAX_RECONNECT_ATTEMPTS = int(self._get("IRC_MAX_RECONNECT_ATTEMPTS", "10"))
        self.IRC_RECONNECT_ON_SEND_FAILURE = _flag(self._env, "IRC_RECONNECT_ON_SEND_FAILURE", "true")
        self.IRC_ZNC_STATUS_CONNECT = False
        self.AUTO_IDENTIFY = _flag(self._env, "AUTO_IDENTIFY", "true")
        self.NICKSERV_PASSWORD = self._get("NICKSERV_PASSWORD")
        self.IRC_BURST_MAX_LINES = max(1, int(self._get("IRC_BURST_MAX_LINES", "8")))
        self.IRC_BURST_PAUSE_SECONDS = max(0, int(self._get("IRC_BURST_PAUSE_SECONDS", "10")))
        db_raw = self._get("DATABASE_PATH", "data/insider.db")
        db_path = Path(db_raw)
        if not db_path.is_absolute():
            db_path = REPO_ROOT / db_path
        self.DATABASE_PATH = db_path

        self._command_pubmsg_whitelist: FrozenSet[str] = frozenset()
        self._command_pubmsg_min_rank: Dict[str, int] = {}
        self._command_pubmsg_allowed_commands: Dict[str, FrozenSet[str]] = {}
        self._rebuild_command_channel_rules()
        self._rebuild_channel_allowed_commands()
        self._load_auth_sets()
        self.warnings: list[str] = []

    def _apply_connection_fallbacks(self) -> None:
        """A blank IRC_SERVER can be filled from ZNC_SERVER or ZNC_HOST in this environment."""
        if not self.IRC_SERVER:
            for key in ("ZNC_SERVER", "ZNC_HOST"):
                host = self._get(key).strip()
                if host:
                    self._take_host(host)
                    logger.info("Using bouncer address from %s", key)
                    break
        if self.IRC_NICKNAME:
            return
        if self.ZNC_IRC_NICK and "/" not in self.ZNC_IRC_NICK:
            self.IRC_NICKNAME = self.ZNC_IRC_NICK
            logger.info("IRC nick is %s", self.IRC_NICKNAME)

    def _take_host(self, host: str) -> None:
        if ":" in host and host.count(":") == 1:
            name, _, port = host.partition(":")
            self.IRC_SERVER = name.strip()
            if port.strip().isdigit():
                self.IRC_PORT = int(port.strip())
            return
        self.IRC_SERVER = host

    def _load_auth_sets(self) -> None:
        owner_users = [u.lower() for u in self._csv("OWNER_USERS")]
        bot_owner = [u.lower() for u in self._csv("BOT_OWNER")]
        self.BOT_OWNER_USERS = bot_owner or owner_users
        self.ADMIN_USERS = self._csv("ADMIN_USERS")
        self.STAFF_USERS = self._csv("STAFF_USERS")

        def group(key: str) -> list:
            return [u.strip().lower() for u in self._csv(key) if u.strip()]

        self._auth_bot_owner_set = frozenset(self.BOT_OWNER_USERS)
        self._auth_coder_set = frozenset(group("CODER"))
        self._auth_team_leaders_set = frozenset(group("TEAM_LEADERS"))
        self._auth_admin_set = frozenset(group("ADMIN_GROUP"))
        self._auth_moderators_set = frozenset(group("MODERATORS"))
        self._auth_torrent_mods_set = frozenset(group("TORRENT_MODERATORS"))
        self._auth_bot_users_set = frozenset(group("BOT_USERS"))
        self._auth_legacy_admin_set = frozenset(u.strip().lower() for u in self.ADMIN_USERS if u.strip())
        self._auth_legacy_staff_set = frozenset(u.strip().lower() for u in self.STAFF_USERS if u.strip())

    def _normalize_tier_token(self, raw: str) -> Optional[str]:
        if not raw:
            return None
        token = raw.strip().lower().replace("-", "_")
        token = AUTH_TIER_ALIASES.get(token, token)
        if token in AUTH_TIER_RANK:
            return token
        return None

    def _rebuild_command_channel_rules(self) -> None:
        specs = self.IRC_COMMAND_CHANNELS or self.IRC_CHANNELS
        whitelist: set = set()
        ranks: Dict[str, int] = {}
        for raw in specs:
            token = (raw or "").strip()
            if not token:
                continue
            if ":" in token:
                left, right = token.split(":", 1)
                channel = self.normalize_irc_channel(left.strip())
                if not channel:
                    continue
                whitelist.add(channel)
                tier_key = self._normalize_tier_token(right)
                if tier_key is None:
                    logger.warning(
                        "Unknown tier suffix in IRC_COMMAND_CHANNELS entry %r — channel allowed without a rank gate",
                        raw,
                    )
                    continue
                ranks[channel] = AUTH_TIER_RANK[tier_key]
            else:
                channel = self.normalize_irc_channel(token)
                if channel:
                    whitelist.add(channel)
        self._command_pubmsg_whitelist = frozenset(whitelist)
        self._command_pubmsg_min_rank = ranks

    def _rebuild_channel_allowed_commands(self) -> None:
        raw = self._get("IRC_CHANNEL_ALLOWED_COMMANDS")
        allowed: Dict[str, FrozenSet[str]] = {}
        if not raw.strip():
            self._command_pubmsg_allowed_commands = allowed
            return
        current_ch: Optional[str] = None
        current_cmds: list = []
        prefix = self.COMMAND_PREFIX
        for token in raw.split(","):
            token = (token or "").strip()
            if not token:
                continue
            if token.startswith("#"):
                if current_ch and current_cmds:
                    allowed[current_ch] = frozenset(current_cmds)
                if ":" not in token:
                    logger.warning("IRC_CHANNEL_ALLOWED_COMMANDS entry %r missing ':' — skipped", token)
                    current_ch = None
                    current_cmds = []
                    continue
                ch_part, cmd_part = token.split(":", 1)
                current_ch = self.normalize_irc_channel(ch_part.strip())
                cmd = cmd_part.strip().lower()
                if cmd.startswith(prefix):
                    cmd = cmd[len(prefix) :]
                current_cmds = [cmd] if cmd else []
            elif current_ch:
                cmd = token.lower()
                if cmd.startswith(prefix):
                    cmd = cmd[len(prefix) :]
                if cmd:
                    current_cmds.append(cmd)
            else:
                logger.warning("IRC_CHANNEL_ALLOWED_COMMANDS orphan command %r — skipped", token)
        if current_ch and current_cmds:
            allowed[current_ch] = frozenset(current_cmds)
        self._command_pubmsg_allowed_commands = allowed

    @staticmethod
    def normalize_irc_channel(name: str) -> str:
        if not name or not str(name).strip():
            return ""
        cleaned = str(name).strip()
        if ":" in cleaned:
            cleaned = cleaned.split(":", 1)[0].strip()
        if not cleaned.startswith("#"):
            cleaned = "#" + cleaned
        return cleaned.casefold()

    @staticmethod
    def channel_join_name(token: str) -> str:
        """Channel to JOIN. Drops a ``:tier`` suffix if one was copied onto IRC_CHANNELS."""
        name = (token or "").strip()
        if not name:
            return ""
        if ":" in name:
            name = name.split(":", 1)[0].strip()
        if not name.startswith("#"):
            name = "#" + name
        return name

    @property
    def effective_command_channels(self) -> FrozenSet[str]:
        return self._command_pubmsg_whitelist

    def pubmsg_min_rank_for_channel(self, normalized_channel: str) -> int:
        return self._command_pubmsg_min_rank.get(normalized_channel, 0)

    def pubmsg_allowed_commands_for_channel(self, normalized_channel: str) -> Optional[FrozenSet[str]]:
        return self._command_pubmsg_allowed_commands.get(normalized_channel)

    def resolve_user_auth_tier(self, username: str) -> Optional[str]:
        """Highest bot-user tier for an IRC nick. ``terminal`` is the console owner."""
        nick = (username or "").split("!")[0].strip().lower()
        if not nick:
            return None
        if nick == "terminal":
            return "owner"
        rank = 0
        if nick in self._auth_bot_owner_set:
            rank = max(rank, AUTH_TIER_RANK["owner"])
        if nick in self._auth_coder_set:
            rank = max(rank, AUTH_TIER_RANK["coder"])
        if nick in self._auth_team_leaders_set:
            rank = max(rank, AUTH_TIER_RANK["team_leaders"])
        if nick in self._auth_admin_set:
            rank = max(rank, AUTH_TIER_RANK["admin"])
        if nick in self._auth_moderators_set:
            rank = max(rank, AUTH_TIER_RANK["moderators"])
        if nick in self._auth_torrent_mods_set or nick in self._auth_bot_users_set:
            rank = max(rank, AUTH_TIER_RANK["torrent_moderators"])
        if nick in self._auth_legacy_admin_set:
            rank = max(rank, AUTH_TIER_RANK["admin"])
        if nick in self._auth_legacy_staff_set:
            rank = max(rank, AUTH_TIER_RANK["moderators"])
        if rank == 0:
            return None
        for tier_id, tier_rank in AUTH_TIER_RANK.items():
            if tier_rank == rank:
                return tier_id
        return None

    def user_rank(self, username: str) -> int:
        tier = self.resolve_user_auth_tier(username)
        if not tier:
            return 0
        return AUTH_TIER_RANK[tier]

    def is_bot_user(self, username: str) -> bool:
        return self.resolve_user_auth_tier(username) is not None

    def is_owner(self, username: str) -> bool:
        return self.resolve_user_auth_tier(username) == "owner"

    def is_admin_or_above(self, username: str) -> bool:
        return self.user_rank(username) >= AUTH_TIER_RANK["admin"]

    @property
    def znc_ident_username(self) -> str:
        if self.ZNC_USERNAME:
            return self.ZNC_USERNAME
        if self.ZNC_USER and self.ZNC_NETWORK:
            return f"{self.ZNC_USER}/{self.ZNC_NETWORK}"
        return self.ZNC_USER

    @property
    def irc_connect_nickname(self) -> str:
        if self.IRC_USE_ZNC and self.ZNC_IRC_NICK:
            return self.ZNC_IRC_NICK
        return self.IRC_NICKNAME

    def _warn_config(self, message: str) -> None:
        self.warnings.append(message)
        logger.warning(message)

    def _validate(self) -> None:
        if not self.COMMAND_PREFIX or any(ch.isspace() for ch in self.COMMAND_PREFIX):
            self.COMMAND_PREFIX = "."
            self._warn_config("COMMAND_PREFIX is invalid. Using '.'")
        if not self.IRC_SERVER:
            self._warn_config("IRC_SERVER is not set.")
        if not self.IRC_NICKNAME:
            self._warn_config("IRC_NICKNAME is not set.")
        if not self.BOT_OWNER_USERS:
            self._warn_config("BOT_OWNER is not set. No IRC nick has the owner tier.")
        if self.IRC_USE_ZNC and self.IRC_USE_SASL:
            self.IRC_USE_SASL = False
            self._warn_config("IRC_USE_ZNC and IRC_USE_SASL are both set. SASL is ignored.")
        if self.IRC_USE_SASL and not (self.SASL_PASSWORD or self.NICKSERV_PASSWORD):
            self._warn_config("IRC_USE_SASL is set but SASL_PASSWORD and NICKSERV_PASSWORD are empty.")
        if self.IRC_USE_ZNC:
            if self.IRC_NICKNAME and "/" in self.IRC_NICKNAME:
                self._warn_config("IRC_NICKNAME contains '/'. Put user/network in ZNC_USERNAME, not NICK.")
            if self.ZNC_IRC_NICK and "/" in self.ZNC_IRC_NICK:
                self._warn_config("ZNC_IRC_NICK contains '/'. That form belongs in ZNC_USERNAME.")
            if not self.znc_ident_username or not self.ZNC_PASSWORD:
                self._warn_config(
                    "IRC_USE_ZNC is set but ZNC_PASSWORD or ZNC_USERNAME (or ZNC_USER + ZNC_NETWORK) is empty."
                )
        tls_ports = {6697, 6699, 7000, 7070, 9999}
        if not self.IRC_TLS and self.IRC_PORT in tls_ports:
            logger.error(
                "IRC_TLS=false but IRC_PORT=%s is normally TLS-only. Set IRC_TLS=true.",
                self.IRC_PORT,
            )
