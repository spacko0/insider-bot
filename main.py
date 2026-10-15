"""InsiderBot entry point."""
from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time

from commands.handler import CommandHandler
from core.connection import IRCConnection
from store.registry import Registry
from utils.config import REPO_ROOT, Config
from utils.irc_format import is_znc_playback
from utils.logging import setup_logging
from version import __version__

for _sub in ("logs", "data"):
    (REPO_ROOT / _sub).mkdir(parents=True, exist_ok=True)

logger = setup_logging()


class GracefulExiter:
    def __init__(self):
        self.state = False
        self.lock = threading.Lock()
        self._application = None
        signal.signal(signal.SIGINT, self.change_state)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, self.change_state)

    def bind_application(self, app) -> None:
        self._application = app

    def change_state(self, signum, frame):
        with self.lock:
            if not self.state:
                logger.info("Shutdown requested (signal %s)", signum)
                self.state = True
        app = self._application
        if app is not None:
            app.schedule_force_exit(1.0)

    def should_exit(self) -> bool:
        with self.lock:
            return self.state


class Application:
    def __init__(self):
        self.exiter = GracefulExiter()
        self._exit_schedule_lock = threading.Lock()
        self._force_exit_armed = False
        self.config = Config()
        self.connection = IRCConnection(self.config)
        self.registry = Registry(self.config.DATABASE_PATH)
        self.commands = CommandHandler(self.config, self.connection, self.registry, self)
        self._link_components()
        self._start_terminal_input()
        self._connect_irc()
        self.exiter.bind_application(self)

    def schedule_force_exit(self, delay: float = 1.0) -> None:
        with self.exiter.lock:
            self.exiter.state = True
        with self._exit_schedule_lock:
            if self._force_exit_armed:
                return
            self._force_exit_armed = True

        def _run():
            try:
                time.sleep(delay)
            finally:
                try:
                    self.shutdown_for_exit()
                except Exception as exc:
                    logger.debug("shutdown_for_exit: %s", exc)
                os._exit(0)

        threading.Thread(target=_run, daemon=True, name="InsiderBotForceExit").start()

    def shutdown_for_exit(self) -> None:
        try:
            self.connection.should_reconnect = False
        except Exception:
            pass
        try:
            self.connection.stop_irc_health_monitor()
        except Exception:
            pass
        try:
            self.connection.disconnect()
        except Exception:
            pass

    def _link_components(self) -> None:
        reactor = self.connection.reactor
        for handler_type in ("pubmsg", "privmsg"):
            reactor.handlers[handler_type] = []

        def add_handler(handler_type, callback):
            def wrapper(connection, event):
                callback(connection, event)

            reactor.add_global_handler(handler_type, wrapper)

        add_handler("pubmsg", self.handle_irc_message)
        add_handler("privmsg", self.handle_irc_message)

    def handle_irc_message(self, connection, event) -> None:
        self.connection.touch_irc_activity()
        try:
            if not event.arguments:
                return
            source_nick = event.source.split("!")[0] if event.source else "unknown"
            text = event.arguments[0]
            if source_nick.casefold() == "nickserv":
                self.connection._run_identity(self.connection.identity.observe_services(source_nick, text))
                return
            if event.type == "privmsg":
                simulated = {
                    "message": event.arguments[0],
                    "target": source_nick,
                    "source": source_nick,
                    "incoming_type": event.type,
                    "incoming_target": event.target,
                }
            else:
                simulated = {
                    "message": event.arguments[0],
                    "target": event.target,
                    "source": source_nick,
                    "incoming_type": event.type,
                    "incoming_target": event.target,
                }
            if self._defer_until_identified(source_nick, text, simulated):
                return
            self.commands.handle(simulated)
        except Exception:
            logger.error("Error handling IRC message", exc_info=True)

    def _defer_until_identified(self, nick: str, message: str, simulated: dict) -> bool:
        """True when the command must wait for a NickServ check, or was dropped."""
        if not self.config.REQUIRE_IDENTIFIED:
            return False
        if is_znc_playback(message):
            return False
        body = (message or "").strip()
        prefix = self.config.COMMAND_PREFIX
        if not body.startswith(prefix):
            return False
        command = body[len(prefix) :].strip().split(" ", 1)[0].lower()
        if not command or command == "help":
            return False
        decision = self.connection.identity.authorize(nick, lambda: self.commands.handle(simulated))
        if decision == "ask":
            logger.info("Checking NickServ identification for %s", nick)
            self.connection.request_identification(nick)
        elif decision == "drop":
            logger.info("Ignored %s from %s; nick is not identified with NickServ", command, nick)
        return True

    def _connect_irc(self) -> bool:
        if not self.config.IRC_SERVER or not self.config.irc_connect_nickname:
            logger.warning(
                "IRC connection skipped. Set IRC_SERVER and a nickname in .env, then restart."
            )
            return False
        attempts = 0
        max_attempts = 5
        logger.info(
            "Connecting to IRC %s:%s as %s",
            self.config.IRC_SERVER,
            self.config.IRC_PORT,
            self.config.irc_connect_nickname,
        )
        while not self.exiter.should_exit() and attempts < max_attempts:
            try:
                started = self.connection.connect(
                    server=self.config.IRC_SERVER,
                    port=self.config.IRC_PORT,
                    nickname=self.config.irc_connect_nickname,
                )
                if started and self.connection.connection_established.wait(timeout=self.config.IRC_WELCOME_TIMEOUT):
                    logger.info("IRC connection established")
                    return True
                logger.error("IRC connection timed out waiting for welcome")
            except Exception:
                logger.error("IRC connection error", exc_info=True)
            attempts += 1
            delay = min(30, 5 * attempts)
            logger.info("Retrying IRC connection in %ss", delay)
            time.sleep(delay)
        logger.error("Failed to establish IRC connection")
        return False

    def _start_terminal_input(self) -> None:
        existing = getattr(self, "_terminal_thread", None)
        if existing is not None and existing.is_alive():
            return

        def terminal_input():
            logger.info("Console ready. Owner commands work from this prompt, including .reconnect and .exit.")
            while not self.exiter.should_exit():
                try:
                    cmd = input("> ").strip()
                    if cmd and self.commands is not None:
                        self.commands.handle({"message": cmd, "target": "terminal", "source": "terminal"})
                except EOFError:
                    logger.info("stdin closed; shutting down")
                    self.schedule_force_exit(1.0)
                    break
                except KeyboardInterrupt:
                    print("Use .exit to stop. Ctrl+C also requests shutdown.", flush=True)
                    self.exiter.change_state(signal.SIGINT, None)
                except Exception as exc:
                    logger.error("Terminal input error: %s", exc)

        self._terminal_thread = threading.Thread(target=terminal_input, daemon=True, name="TerminalInputThread")
        self._terminal_thread.start()

    def main_loop(self) -> None:
        logger.info("InsiderBot %s running", __version__)
        while not self.exiter.should_exit():
            time.sleep(0.5)
        logger.info("Main loop exiting")
        self.shutdown_for_exit()


if __name__ == "__main__":
    try:
        Application().main_loop()
    except Exception as exc:
        logging.getLogger("insiderbot").critical("Fatal error: %s", exc, exc_info=True)
        sys.exit(1)
