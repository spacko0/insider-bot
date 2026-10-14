"""IRC readiness and send gating."""
from unittest.mock import MagicMock

from core.connection import IRCConnection


def _config():
    config = MagicMock()
    config.AUTO_JOIN_CHANNELS = False
    config.IRC_CHANNELS = []
    config.IRC_HEALTH_MONITOR = False
    config.IRC_USE_ZNC = False
    config.IRC_WELCOME_TIMEOUT = 5
    config.IRC_RECONNECT_ON_SEND_FAILURE = True
    config.IRC_MAX_RECONNECT_ATTEMPTS = 10
    config.IRC_RECONNECT_DELAY = 30
    config.irc_connect_nickname = "InsiderBot"
    return config


def _connection():
    conn = IRCConnection(_config())
    conn.connection = MagicMock()
    conn.connection.connected = True
    conn.should_reconnect = False
    return conn


def test_is_irc_ready_requires_welcome():
    irc_conn = _connection()
    irc_conn._irc_connected = False
    irc_conn.connection_established.clear()
    assert irc_conn.is_irc_ready() is False
    irc_conn._irc_connected = True
    irc_conn.connection_established.set()
    assert irc_conn.is_irc_ready() is True


def test_send_message_skips_when_not_ready():
    irc_conn = _connection()
    irc_conn._irc_connected = False
    irc_conn.connection_established.clear()
    irc_conn.send_message("#insiders", "hello")
    irc_conn.connection.privmsg.assert_not_called()


def test_send_message_when_ready():
    irc_conn = _connection()
    irc_conn._irc_connected = True
    irc_conn.connection_established.set()
    irc_conn.send_message("#insiders", "hello")
    irc_conn.connection.privmsg.assert_called_once_with("#insiders", "hello")


def test_welcome_does_not_tell_the_bouncer_to_reconnect():
    irc_conn = _connection()
    irc_conn.config.IRC_USE_ZNC = True
    irc_conn.config.IRC_ZNC_STATUS_CONNECT = True
    irc_conn.config.AUTO_IDENTIFY = False
    irc_conn.config.NICKSERV_PASSWORD = ""
    irc_conn.config.IRC_USE_SASL = False
    irc_conn.connection.real_nickname = "InsiderBot"
    event = MagicMock()
    event.arguments = ["InsiderBot"]
    irc_conn.on_welcome(irc_conn.connection, event)
    irc_conn.on_welcome(irc_conn.connection, event)
    irc_conn.connection.privmsg.assert_not_called()
    irc_conn.connection.nick.assert_not_called()


def test_on_disconnect_clears_welcome_and_does_not_reconnect_when_disabled():
    irc_conn = _connection()
    irc_conn._welcome_received = True
    irc_conn._irc_connected = True
    irc_conn.connection_established.set()
    event = MagicMock()
    event.arguments = ["Connection reset by peer"]
    irc_conn.on_disconnect(irc_conn.connection, event)
    assert irc_conn._welcome_received is False
    assert irc_conn.irc_connected is False
    assert not irc_conn.connection_established.is_set()
    assert irc_conn._reconnect_thread is None
