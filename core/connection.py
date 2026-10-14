# core/connection.py
"""IRC session: TLS, SASL or ZNC, welcome gate, health checks, reconnect.

The health monitor starts as soon as the socket connects, so a missing 001
is noticed. An in-progress reconnect does not schedule a second one.
"""
from __future__ import annotations

import functools
import logging
import ssl
import threading
import time
from datetime import datetime

from irc.client import Event, ServerConnection, SimpleIRCClient
from irc.connection import Factory

logger = logging.getLogger(__name__)


def _apply_jaraco_sasl_cap_ack_fix():
    """jaraco irc checks ``'sasl' in event.arguments`` as a whole-string membership.

    CAP ACK usually splits capability tokens into separate arguments, and a trailing
    space (``sasl ``) makes that check fail. AUTHENTICATE PLAIN is then never sent
    and the server drops the socket with a registration timeout.
    """
    if getattr(ServerConnection, "_insiderbot_sasl_cap_ack_patched", False):
        return

    def _sasl_cap_req_fixed(self, event):
        if event.type != "cap" or len(event.arguments) <= 1:
            return
        sub = event.arguments[0]
        if sub == "ACK":
            caps_tokens = []
            for arg in event.arguments[1:]:
                caps_tokens.extend(arg.strip().split())
            if any(token.lower() == "sasl" for token in caps_tokens):
                logger.debug("SASL CAP ACK tokens %r → sending AUTHENTICATE PLAIN", caps_tokens)
                self.send_items("AUTHENTICATE", "PLAIN")
                self._sasl_step = self._sasl_auth_plain
            return
        if sub == "NAK":
            fail = Event("login_failed", event.target, ["server refused sasl protocol"])
            self._handle_event(fail)
            self._sasl_end()

    ServerConnection._sasl_cap_req = _sasl_cap_req_fixed
    ServerConnection._insiderbot_sasl_cap_ack_patched = True


_apply_jaraco_sasl_cap_ack_fix()


class IRCConnection(SimpleIRCClient):
    def __init__(self, config):
        super().__init__()
        self.message_lock = threading.Lock()
        self.config = config
        self.connection_established = threading.Event()
        self.nickname = config.irc_connect_nickname
        self.lock = threading.Lock()
        self._irc_connected = False
        self._channels = []
        if config.AUTO_JOIN_CHANNELS:
            for raw in config.IRC_CHANNELS:
                name = config.channel_join_name(raw)
                if name and name.lower() not in self._channels:
                    self._channels.append(name.lower())
        self._reactor_process_forever_started = False
        self._conn_op_lock = threading.RLock()
        self._last_irc_activity_monotonic = 0.0
        self._registration_started_monotonic = 0.0
        self._health_stop = threading.Event()
        self._health_thread = None
        self._pending_health_ping_at = None
        self._pending_health_ping_token = None
        self._last_health_client_ping_mono = 0.0
        self.should_reconnect = True
        self._welcome_received = False
        self._intentional_disconnect = False
        self._suppress_auto_reconnect = False
        self.reconnect_attempts = 0
        self.last_reconnect_attempt_time = None
        self._reconnect_lock = threading.Lock()
        self._reconnect_thread = None
        self._reconnect_reset_timer = None
        self.last_disconnect_reason = ""
        self._send_skip_log_mono = 0.0

    def is_irc_ready(self) -> bool:
        conn = getattr(self, "connection", None)
        if conn is None or not getattr(conn, "connected", False):
            return False
        with self.lock:
            return self._irc_connected and self.connection_established.is_set()

    def wait_for_ready(self, timeout=None) -> bool:
        limit = timeout if timeout is not None else self.config.IRC_WELCOME_TIMEOUT
        if self.connection_established.wait(timeout=limit):
            return True
        if getattr(self.config, "IRC_USE_ZNC", False):
            logger.error(
                "ZNC: no 001 within %ss after connect — check *status, ZNC_PASSWORD, "
                "and that IRC_SERVER/IRC_PORT point at the bouncer",
                limit,
            )
        else:
            logger.error("IRC: no 001 welcome within %ss after connect", limit)
        return False

    def touch_irc_activity(self):
        self._last_irc_activity_monotonic = time.monotonic()

    def _on_incoming_ping(self, connection, event):
        self.touch_irc_activity()
        if event.arguments:
            try:
                connection.pong(event.arguments[0])
            except Exception as exc:
                logger.debug("PONG reply failed: %s", exc)

    def _on_pong_health(self, connection, event):
        self.touch_irc_activity()
        token = self._pending_health_ping_token
        if token and event.arguments and token in " ".join(event.arguments):
            self._pending_health_ping_at = None
            self._pending_health_ping_token = None

    def start_irc_health_monitor(self):
        if not self.config.IRC_HEALTH_MONITOR:
            return
        if self._health_thread is not None and self._health_thread.is_alive():
            return
        self._health_stop.clear()
        self._health_thread = threading.Thread(
            target=self._irc_health_loop,
            daemon=True,
            name="IRCHealthMonitor",
        )
        self._health_thread.start()
        logger.debug("IRC health monitor started")

    def stop_irc_health_monitor(self):
        self._health_stop.set()

    def _irc_health_loop(self):
        tick = min(30, max(5, self.config.IRC_HEALTH_CHECK_INTERVAL // 3 or 5))
        while not self._health_stop.wait(tick):
            try:
                self._irc_health_tick()
            except Exception:
                logger.error("IRC health tick error", exc_info=True)

    def _irc_health_tick(self):
        if not getattr(self.config, "IRC_HEALTH_MONITOR", True):
            return
        conn = getattr(self, "connection", None)
        if conn is None:
            return
        now = time.monotonic()
        sock_up = getattr(conn, "connected", False)

        if (
            sock_up
            and not self.irc_connected
            and self._registration_started_monotonic > 0
            and (now - self._registration_started_monotonic) > self.config.IRC_STALLED_REGISTRATION_SECONDS
        ):
            logger.warning(
                "IRC stalled: socket up but no welcome for %ss — reconnecting",
                int(now - self._registration_started_monotonic),
            )
            self._clear_pending_health_ping()
            self._schedule_reconnect()
            return

        if sock_up and not self.irc_connected and self._welcome_received:
            if not (
                self._registration_started_monotonic > 0
                and (now - self._registration_started_monotonic) <= self.config.IRC_STALLED_REGISTRATION_SECONDS
            ):
                logger.warning("IRC socket up but not registered — scheduling reconnect")
                self._clear_pending_health_ping()
                self._schedule_reconnect()
                return

        if not sock_up and self._welcome_received:
            logger.warning("IRC socket down — scheduling reconnect")
            self._clear_pending_health_ping()
            self._schedule_reconnect()
            return

        if not self.irc_connected:
            self._clear_pending_health_ping()
            if self._welcome_received:
                self._schedule_reconnect()
            return

        last = self._last_irc_activity_monotonic
        if last > 0 and (now - last) > self.config.IRC_ACTIVITY_TIMEOUT:
            logger.warning(
                "IRC idle for %.0fs (limit %ss) — reconnecting",
                now - last,
                self.config.IRC_ACTIVITY_TIMEOUT,
            )
            self._clear_pending_health_ping()
            self._schedule_reconnect()
            return

        if not self.config.IRC_CLIENT_PING_ENABLED or not sock_up:
            return

        if self._pending_health_ping_at is not None:
            if now - self._pending_health_ping_at > self.config.IRC_CLIENT_PING_TIMEOUT:
                logger.warning(
                    "IRC client PING timed out after %ss — reconnecting",
                    self.config.IRC_CLIENT_PING_TIMEOUT,
                )
                self._clear_pending_health_ping()
                self._schedule_reconnect()
            return

        interval = self.config.IRC_CLIENT_PING_INTERVAL
        if self._last_health_client_ping_mono <= 0:
            self._last_health_client_ping_mono = now
        if now - self._last_health_client_ping_mono < interval:
            return

        token = f"insider-hlth-{int(now * 1000)}"
        try:
            conn.ping(token)
            self._pending_health_ping_at = now
            self._pending_health_ping_token = token
            self._last_health_client_ping_mono = now
            logger.debug("IRC health client PING sent")
        except Exception as exc:
            logger.warning("IRC health PING failed: %s — reconnecting", exc)
            self._clear_pending_health_ping()
            self._schedule_reconnect()

    def _send_error_triggers_reconnect(self, exc: Exception) -> bool:
        if not getattr(self.config, "IRC_RECONNECT_ON_SEND_FAILURE", True):
            return False
        msg = str(exc)
        needles = ("Not connected", "EPIPE", "Broken pipe", "Connection reset", "Connection aborted")
        return any(needle in msg for needle in needles)

    def _schedule_reconnect(self, force_reset=False):
        if not self.should_reconnect or self._intentional_disconnect or self._suppress_auto_reconnect:
            return
        if self.last_reconnect_attempt_time:
            elapsed = (datetime.now() - self.last_reconnect_attempt_time).total_seconds()
            if elapsed > 300:
                self.reconnect_attempts = 0
        if force_reset:
            self.reconnect_attempts = 0
        max_attempts = getattr(self.config, "IRC_MAX_RECONNECT_ATTEMPTS", 10)
        if self.reconnect_attempts >= max_attempts:
            logger.error("IRC max reconnect attempts (%s) reached; retrying in 5 minutes", max_attempts)
            if self._reconnect_reset_timer:
                try:
                    self._reconnect_reset_timer.cancel()
                except Exception:
                    pass
            self._reconnect_reset_timer = threading.Timer(300, self._reset_reconnect_attempts)
            self._reconnect_reset_timer.daemon = True
            self._reconnect_reset_timer.start()
            return
        if self._reconnect_thread is not None and self._reconnect_thread.is_alive():
            return
        self.reconnect_attempts += 1
        self.last_reconnect_attempt_time = datetime.now()
        delay = getattr(self.config, "IRC_RECONNECT_DELAY", 30)
        logger.info(
            "Scheduling IRC reconnect %s/%s in %ss",
            self.reconnect_attempts,
            max_attempts,
            delay,
        )
        self._reconnect_thread = threading.Thread(
            target=self._delayed_reconnect,
            daemon=True,
            name="IRCDelayedReconnect",
        )
        self._reconnect_thread.start()

    def _reset_reconnect_attempts(self):
        self.reconnect_attempts = 0
        self.last_reconnect_attempt_time = None
        logger.info("IRC reconnect attempt counter reset")
        if self.should_reconnect and not self._intentional_disconnect:
            self._schedule_reconnect()

    def _try_znc_status_connect(self) -> bool:
        if not getattr(self.config, "IRC_USE_ZNC", False):
            return False
        if not getattr(self.config, "IRC_ZNC_STATUS_CONNECT", True):
            return False
        conn = getattr(self, "connection", None)
        if not conn or not getattr(conn, "connected", False):
            return False
        try:
            conn.privmsg("*status", "connect")
            logger.info("Sent ZNC *status connect before full reconnect")
        except Exception as exc:
            logger.warning("ZNC *status connect failed: %s", exc)
            return False
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.irc_connected and self.connection_established.is_set():
                logger.info("IRC restored after ZNC *status connect")
                self.touch_irc_activity()
                return True
            time.sleep(0.5)
        return False

    def _delayed_reconnect(self):
        if not self._reconnect_lock.acquire(blocking=False):
            logger.debug("IRC reconnect already in progress")
            return
        try:
            delay = getattr(self.config, "IRC_RECONNECT_DELAY", 30)
            for _ in range(delay):
                if not self.should_reconnect or self._intentional_disconnect:
                    return
                time.sleep(1)
            if self.irc_connected and self.connection_established.is_set():
                logger.info("IRC reconnect cancelled — connection already up")
                return
            if self._try_znc_status_connect():
                return
            self.reconnect()
        except Exception:
            logger.error("Delayed IRC reconnect error", exc_info=True)
        finally:
            self._reconnect_lock.release()

    def _clear_pending_health_ping(self):
        self._pending_health_ping_at = None
        self._pending_health_ping_token = None
        self._last_health_client_ping_mono = 0.0

    def reconnect(self, wait_for_welcome=True) -> bool:
        with self._conn_op_lock:
            self._suppress_auto_reconnect = True
            try:
                current = getattr(self, "connection", None)
                if current is not None and getattr(current, "connected", False):
                    self.disconnect()
                self._intentional_disconnect = False
                time.sleep(2)
                if not self.connect(
                    server=self.config.IRC_SERVER,
                    port=self.config.IRC_PORT,
                    nickname=self.config.irc_connect_nickname,
                ):
                    return False
                if not wait_for_welcome:
                    return True
                return self.wait_for_ready()
            except Exception:
                logger.error("Reconnect failed", exc_info=True)
                return False
            finally:
                self._suppress_auto_reconnect = False

    @property
    def irc_connected(self):
        with self.lock:
            return self._irc_connected

    @irc_connected.setter
    def irc_connected(self, value):
        with self.lock:
            self._irc_connected = value

    def connect(self, server, port, nickname):
        with self._conn_op_lock:
            try:
                self._intentional_disconnect = False
                self._clear_pending_health_ping()
                self._registration_started_monotonic = time.monotonic()
                self.connection_established.clear()
                self._irc_connected = False
                self._welcome_received = False
                self.reactor.remove_global_handler("welcome", self.on_welcome)
                self.reactor.remove_global_handler("disconnect", self.on_disconnect)
                self.reactor.add_global_handler("welcome", self.on_welcome)
                self.reactor.add_global_handler("disconnect", self.on_disconnect)
                connect_kwargs = {"server": server, "port": port, "nickname": nickname}
                if self.config.IRC_TLS:
                    context = ssl.create_default_context()
                    if not self.config.IRC_TLS_VERIFY:
                        context.check_hostname = False
                        context.verify_mode = ssl.CERT_NONE
                        logger.warning("IRC TLS certificate verification is disabled")
                    connect_kwargs["connect_factory"] = Factory(
                        wrapper=functools.partial(context.wrap_socket, server_hostname=server)
                    )
                    logger.info(
                        "IRC TLS active (server=%s port=%s verify_cert=%s)",
                        server,
                        port,
                        self.config.IRC_TLS_VERIFY,
                    )
                if self.config.IRC_USE_ZNC:
                    ident = self.config.znc_ident_username
                    connect_kwargs["username"] = ident
                    connect_kwargs["password"] = self.config.ZNC_PASSWORD
                    logger.info(
                        "IRC ZNC: USER(%r) + NICK(%s) → %s:%s",
                        ident,
                        nickname,
                        server,
                        port,
                    )
                elif self.config.IRC_USE_SASL:
                    account = self.config.SASL_ACCOUNT or nickname
                    password = self.config.SASL_PASSWORD or self.config.NICKSERV_PASSWORD
                    connect_kwargs["sasl_login"] = account
                    connect_kwargs["password"] = password
                    logger.info("IRC connection will use SASL PLAIN (account=%s)", account)

                old = getattr(self, "connection", None)
                if old is not None:
                    try:
                        old.disconnect("Reconnecting")
                    except Exception:
                        try:
                            old.close()
                        except Exception:
                            pass

                self.connection = self.reactor.server().connect(**connect_kwargs)
                self.nickname = nickname
                self.connection.add_global_handler("join", self._on_join)
                self.connection.add_global_handler("nick", self._on_nick)
                self.connection.add_global_handler("nicknameinuse", self._on_nicknameinuse)
                self.connection.add_global_handler("privmsg", self._on_privmsg)
                self.connection.add_global_handler("ping", self._on_incoming_ping)
                self.connection.add_global_handler("pong", self._on_pong_health)
                self.connection.add_global_handler("notice", self.on_notice)
                if not self._reactor_process_forever_started:
                    threading.Thread(
                        target=self._run_reactor,
                        daemon=True,
                        name="IRCReactorProcessForever",
                    ).start()
                    self._reactor_process_forever_started = True
                self.start_irc_health_monitor()
                logger.info("Connecting to IRC server...")
                return True
            except Exception as exc:
                logger.error("Connection failed: %s", exc)
                return False

    def _run_reactor(self):
        try:
            self.reactor.process_forever()
        except Exception:
            logger.error("IRC reactor stopped", exc_info=True)
            self.irc_connected = False
            self.connection_established.clear()

    def on_welcome(self, connection, event):
        self.touch_irc_activity()
        self.irc_connected = True
        self._welcome_received = True
        self.reconnect_attempts = 0
        self.last_reconnect_attempt_time = None
        self.connection_established.set()
        real_nick = (getattr(connection, "real_nickname", None) or "").strip()
        if real_nick:
            self.nickname = real_nick
        logger.info(
            "IRC connection established (nick=%s, channels=%s)",
            self.nickname,
            ", ".join(self._channels) if self._channels else "(none configured)",
        )
        logger.info("Private messages must be sent to %s", self.nickname)
        self.start_irc_health_monitor()
        if self.config.IRC_USE_ZNC and getattr(self.config, "IRC_ZNC_STATUS_CONNECT", True):
            try:
                connection.privmsg("*status", "connect")
                logger.info("Asked the bouncer to connect its IRC network")
            except Exception as exc:
                logger.warning("Bouncer status connect failed: %s", exc)
        if self.config.AUTO_IDENTIFY and self.config.NICKSERV_PASSWORD and not self.config.IRC_USE_SASL:
            connection.privmsg("NickServ", f"IDENTIFY {self.config.NICKSERV_PASSWORD}")
            logger.info("Sent auto-identify to NickServ")
        if self.config.AUTO_JOIN_CHANNELS:
            for channel in self._channels:
                if channel.strip():
                    connection.join(channel.strip())

    def _on_privmsg(self, connection, event):
        self.touch_irc_activity()
        text = event.arguments[0] if event.arguments else ""
        source = str(event.source or "unknown").split("!")[0]
        logger.info("PM from %s to %s: %s", source, event.target, text)

    def _on_nick(self, connection, event):
        self.touch_irc_activity()
        new_nick = str(event.arguments[0]).lstrip(":").strip() if event.arguments else ""
        source = str(event.source or "").split("!")[0]
        previous = (self.nickname or "").strip()
        real = (getattr(connection, "real_nickname", None) or "").strip()
        if new_nick and source.casefold() in {previous.casefold(), real.casefold(), ""}:
            if new_nick != previous:
                logger.info("IRC nick changed from %s to %s", previous or "(none)", new_nick)
                logger.info("Private messages must be sent to %s", new_nick)
            self.nickname = new_nick

    def _on_nicknameinuse(self, connection, event):
        detail = " ".join(str(part) for part in (event.arguments or []))
        logger.error(
            "IRC nick %s is already in use (%s). A private message to that nick will not reach this bot.",
            self.nickname,
            detail or "no detail",
        )

    def on_notice(self, connection, event):
        self.touch_irc_activity()
        source = str(event.source or "").split("!")[0]
        text = event.arguments[0] if event.arguments else ""
        if source.startswith("*"):
            logger.info("Bouncer notice from %s: %s", source, text)
        if event.arguments and "You are now identified" in event.arguments[0]:
            logger.info("Authenticated with NickServ")
            if self.config.AUTO_JOIN_CHANNELS:
                for channel in self._channels:
                    connection.join(channel)

    def join(self, channel):
        name = self.config.channel_join_name(channel)
        if not name:
            return
        key = name.lower()
        if key not in self._channels:
            self._channels.append(key)
        if self.connection:
            self.connection.join(name)

    def _on_join(self, connection, event):
        self.touch_irc_activity()
        channel = (event.target or "").lower()
        if channel and channel not in self._channels:
            self._channels.append(channel)

    def part(self, channel):
        name = self.config.channel_join_name(channel)
        if self.connection and name:
            self.connection.part(name)
        key = name.lower()
        if key in self._channels:
            self._channels.remove(key)

    def send_message(self, target, message):
        with self.message_lock:
            if not self.connection:
                return
            if not self.is_irc_ready():
                now = time.monotonic()
                if now - self._send_skip_log_mono > 60:
                    self._send_skip_log_mono = now
                    logger.warning("IRC not ready (no 001); dropped PRIVMSG to %s", target)
                if (
                    self.should_reconnect
                    and not self._intentional_disconnect
                    and not self._suppress_auto_reconnect
                    and not (self._reconnect_thread is not None and self._reconnect_thread.is_alive())
                ):
                    self._schedule_reconnect()
                return
            try:
                for line in str(message).split("\n"):
                    if line != "":
                        self.connection.privmsg(target, line)
            except Exception as exc:
                if "EPIPE" in str(exc) or "Broken pipe" in str(exc):
                    logger.warning("Connection closed during send")
                else:
                    logger.error("Send message error: %s", exc)
                if self._send_error_triggers_reconnect(exc):
                    self._schedule_reconnect()

    def on_disconnect(self, connection, event):
        self._clear_pending_health_ping()
        was_established = self._welcome_received
        self.irc_connected = False
        self.connection_established.clear()
        self._welcome_received = False
        args = getattr(event, "arguments", None) or []
        reason = " ".join(args) if args else "(no server reason string)"
        self.last_disconnect_reason = reason
        now = time.monotonic()
        if (
            reason == getattr(self, "_dedupe_disconnect_reason", None)
            and now - getattr(self, "_dedupe_disconnect_time", 0) < 0.35
        ):
            return
        self._dedupe_disconnect_reason = reason
        self._dedupe_disconnect_time = now
        logger.warning("IRC connection lost: %s", reason)
        if was_established and self.should_reconnect and not self._intentional_disconnect and not self._suppress_auto_reconnect:
            self._schedule_reconnect()

    def get_channels(self):
        return [chan.lower() for chan in self._channels]

    @property
    def is_connected(self):
        with self.lock:
            return self.irc_connected

    def disconnect(self):
        self._intentional_disconnect = True
        self.stop_irc_health_monitor()
        if self._reconnect_reset_timer:
            try:
                self._reconnect_reset_timer.cancel()
            except Exception:
                pass
        try:
            conn = getattr(self, "connection", None)
            if not conn:
                return
            if getattr(conn, "connected", False):
                try:
                    conn.quit("Shutting down")
                except OSError:
                    pass
            try:
                conn.close()
            except Exception:
                pass
        except Exception as exc:
            logger.debug("IRC disconnect cleanup: %s", exc)
