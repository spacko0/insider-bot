from pathlib import Path

import pytest

from commands.format import format_banned
from commands.urls import classify_url
from store.registry import Registry, RegistryError
from tests.support import base_env, channel_event, make_handler, pm_event, visible
from utils.config import Config


def _plain(lines: list[str]) -> str:
    return "\n".join(line.replace("\u00a0", " ").replace("\x11", "") for line in lines)


def test_same_nick_bans_share_one_row():
    same_day = _plain(
        format_banned(
            [
                {
                    "nick": "nzbs",
                    "display_nick": "nzbs",
                    "site": "HHD",
                    "reason": "Disrespectful",
                    "added_at": "2026-10-14 08:26 UTC",
                },
                {
                    "nick": "nzbs",
                    "display_nick": "nzbs",
                    "site": "MNS",
                    "reason": "Invite Trading",
                    "added_at": "2026-10-14 08:19 UTC",
                },
            ],
            colors=False,
        )
    )
    assert "Banned (1)" in same_day
    assert "MNS, HHD" in same_day
    assert "Invite Trading, Disrespectful" in same_day
    assert same_day.count("nzbs") == 1
    other_day = _plain(
        format_banned(
            [
                {
                    "nick": "nzbs",
                    "display_nick": "nzbs",
                    "site": "HHD",
                    "reason": "Disrespectful",
                    "added_at": "2026-10-15 08:26 UTC",
                },
                {
                    "nick": "nzbs",
                    "display_nick": "nzbs",
                    "site": "MNS",
                    "reason": "Invite Trading",
                    "added_at": "2026-10-14 08:19 UTC",
                },
            ],
            colors=False,
        )
    )
    assert "2026-10-14" in other_day
    assert "MNS, HHD (10-15)" in other_day
    assert "Invite Trading, Disrespectful" in other_day
    header, data = [line for line in other_day.splitlines() if "|" in line]
    assert len(header) == len(data)


def test_classify_reddit_and_articles():
    assert classify_url("https://www.reddit.com/r/news/comments/abc/title") == "reddit"
    assert classify_url("https://redd.it/abc") == "reddit"
    assert classify_url("https://v.redd.it/xyz") == "reddit"
    assert classify_url("https://example.com/story") == "article"
    assert classify_url("ftp://example.com/file") is None
    assert classify_url("not a url") is None


def test_addnews_title_before_the_url_is_stored(tmp_path):
    handler, conn, registry = make_handler(tmp_path)
    handler.handle(channel_event(".register MidnightScene Editor", "Carol"))
    conn.sent.clear()
    handler.handle(
        channel_event(
            ".addnews OTW Leak https://www.reddit.com/r/trackers/comments/1x1v652/comment/pexnesy/",
            "Carol",
        )
    )
    assert "OTW Leak" in visible(conn)
    row = registry.list_news(5)[0]
    assert row["note"] == "OTW Leak"
    assert row["kind"] == "reddit"


def test_addnews_without_a_title_uses_the_page_heading(tmp_path, monkeypatch):
    monkeypatch.setattr("commands.handler.fetch_page_title", lambda url: "OTW Leak")
    handler, conn, registry = make_handler(tmp_path)
    handler.handle(channel_event(".register MidnightScene Editor", "Carol"))
    conn.sent.clear()
    handler.handle(channel_event(".addnews https://example.com/story", "Carol"))
    assert "OTW Leak" in visible(conn)
    assert registry.list_news(5)[0]["note"] == "OTW Leak"


def test_page_heading_parsers():
    from commands.titles import title_from_html, title_from_reddit_json

    assert title_from_html("<html><title>Hello &amp; Co</title></html>") == "Hello & Co"
    assert title_from_html('<meta property="og:title" content="Post title"><title>Other</title>') == "Post title"
    payload = [{"data": {"children": [{"data": {"title": "Tracker thread"}}]}}]
    assert title_from_reddit_json(payload) == "Tracker thread"
    assert title_from_reddit_json({"title": "Oldtoons database and website leak"}) == "Oldtoons database and website leak"
    assert title_from_html("<html><title>reddit</title></html>") is None
    assert title_from_html("<html><title>Welcome to Reddit</title></html>") is None


def test_placeholder_reddit_title_is_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "commands.handler.fetch_page_title",
        lambda url: "Oldtoons database and website leak",
    )
    handler, _conn, registry = make_handler(tmp_path)
    url = "https://www.reddit.com/r/trackers/comments/1x1v652/comment/pexnesy/"
    registry.add_news(url, "reddit", "reddit", by="carol")
    handler.handle(channel_event(f".addnews {url}", "OwnerNick"))
    assert registry.list_news(5)[0]["note"] == "Oldtoons database and website leak"


def test_registry_register_ban_and_news(tmp_path):
    registry = Registry(tmp_path / "t.db")
    assert registry.register("Ada", "MidnightScene", "Editor", by="ada") == "created"
    assert registry.register("ada", "MidnightScene", "Senior Editor", by="ada") == "updated"
    row = registry.get_registered("ADA")
    assert row["position"] == "Senior Editor"
    assert row["site"] == "MidnightScene"
    assert registry.is_registered("ada")
    assert registry.ban("Eve", "MidnightScene", "leaked screenshots", by="ada") == "created"
    assert registry.ban("eve", "OtherSite", "spam", by="ada") == "created"
    assert registry.ban("Eve", "midnightscene", "still leaking", by="bob") == "updated"
    banned = registry.list_banned("MidnightScene")
    assert len(banned) == 1
    assert banned[0]["reason"] == "still leaking"
    assert len(registry.list_banned()) == 2
    assert registry.unban("Eve", "OtherSite") == 1
    assert len(registry.list_banned()) == 1
    status, item = registry.add_news("https://redd.it/abc", "reddit", "thread", by="ada")
    assert status == "created"
    again, dup = registry.add_news("https://redd.it/abc", "reddit", "", by="ada")
    assert again == "duplicate"
    assert dup["id"] == item["id"]
    assert registry.delete_news(item["id"])
    assert registry.list_news(10) == []
    _, reused = registry.add_news("https://example.com/next", "article", "next", by="ada")
    assert reused["id"] == 1
    _, kept = registry.add_news("https://example.com/kept", "article", "kept", by="ada")
    assert kept["id"] == 2
    assert registry.delete_news(reused["id"])
    _, filled = registry.add_news("https://example.com/filled", "article", "filled", by="ada")
    assert filled["id"] == 1
    hole = Registry(tmp_path / "hole.db")
    hole.add_news("https://example.com/a", "article", "a", by="ada")
    hole.add_news("https://example.com/b", "article", "b", by="ada")
    assert hole.delete_news(1)
    reopened = Registry(tmp_path / "hole.db")
    packed = reopened.list_news(5)
    assert packed[0]["id"] == 1
    assert packed[0]["url"] == "https://example.com/b"
    with pytest.raises(RegistryError):
        registry.register("has space", "Site", "Role", by="ada")


def test_admin_updates_a_position_and_old_rows_keep_multiple_sites(tmp_path):
    import sqlite3

    handler, conn, registry = make_handler(tmp_path)
    handler.handle(channel_event(".update Carol MidnightScene Editor", "Alice"))
    conn.sent.clear()
    handler.handle(channel_event(".update Carol MidnightScene Senior Editor", "Alice"))
    assert registry.get_registered("carol", "MidnightScene")["position"] == "Senior Editor"
    assert "Updated Carol" in visible(conn)
    conn.sent.clear()
    handler.handle(channel_event(".update Carol OtherSite Uploader", "Alice"))
    assert len(registry.registrations_for("carol")) == 2
    handler.handle(channel_event(".unregister Carol OtherSite", "Alice"))
    assert registry.get_registered("carol", "OtherSite") is None
    assert registry.is_registered("carol")

    legacy = tmp_path / "legacy.db"
    db = sqlite3.connect(legacy)
    db.execute(
        """
        CREATE TABLE registered (
            nick TEXT PRIMARY KEY,
            display_nick TEXT NOT NULL,
            site_key TEXT NOT NULL,
            site TEXT NOT NULL,
            position TEXT NOT NULL,
            registered_by TEXT NOT NULL,
            registered_at TEXT NOT NULL
        )
        """
    )
    db.execute(
        "INSERT INTO registered VALUES ('ada', 'Ada', 'mns', 'MNS', 'Editor', 'ada', '2026-01-01 00:00 UTC')"
    )
    db.commit()
    db.close()
    migrated = Registry(legacy)
    assert migrated.register("Ada", "Other", "Mod", by="ada") == "created"
    assert {row["site"] for row in migrated.registrations_for("ada")} == {"MNS", "Other"}


def test_stranger_must_register_before_member_commands(tmp_path):
    handler, conn, _registry = make_handler(tmp_path)
    handler.handle(channel_event(".news", "Carol"))
    assert conn.sent == []
    conn.sent.clear()
    handler.handle(channel_event("hello", "Carol"))
    assert conn.sent == []


def test_anyone_can_register_own_nick_not_someone_else(tmp_path):
    handler, conn, registry = make_handler(tmp_path)
    handler.handle(channel_event(".register MidnightScene Editor", "Carol"))
    assert registry.is_registered("carol")
    assert registry.get_registered("carol")["position"] == "Editor"
    assert "Registered Carol" in visible(conn)
    conn.sent.clear()
    handler.handle(channel_event(".register OtherSite Moderator", "Carol"))
    assert {row["site"] for row in registry.registrations_for("carol")} == {"MidnightScene", "OtherSite"}
    conn.sent.clear()
    handler.handle(channel_event(".update Alice MidnightScene Editor", "Carol"))
    assert conn.sent == []
    assert registry.get_registered("alice") is None


def test_admin_can_register_someone_else(tmp_path):
    handler, conn, registry = make_handler(tmp_path)
    handler.handle(channel_event(".update Carol OtherSite Uploader", "Alice"))
    assert registry.get_registered("carol")["site"] == "OtherSite"
    assert "Registered Carol" in visible(conn)


def test_registered_user_can_add_news_and_bans_but_not_the_roster(tmp_path):
    handler, conn, _registry = make_handler(tmp_path)
    handler.handle(channel_event(".register MidnightScene Moderator", "Dave"))
    conn.sent.clear()
    handler.handle(channel_event(".addnews https://example.com/a insider note", "Dave"))
    assert "Added #1 (article)" in visible(conn)
    conn.sent.clear()
    handler.handle(channel_event(".addnews https://www.reddit.com/r/x/comments/1/post", "Dave"))
    assert "reddit post" in visible(conn)
    conn.sent.clear()
    handler.handle(channel_event(".addnews https://example.com/a", "Dave"))
    assert "Already listed as #1" in visible(conn)
    conn.sent.clear()
    handler.handle(channel_event(".news 1", "Dave"))
    text = visible(conn)
    assert "[reddit]" in text
    assert "example.com/a" not in text
    conn.sent.clear()
    handler.handle(channel_event(".banuser Eve MidnightScene leaked a screen", "Dave"))
    assert "Banned for Eve on MidnightScene" in visible(conn)
    conn.sent.clear()
    handler.handle(channel_event(".banned MidnightScene", "Dave"))
    text = visible(conn)
    assert "Eve" in text
    assert "leaked a screen" in text
    assert "MidnightScene" in text
    assert "Date" in text
    lines = [message.replace("\u00a0", " ").replace("\x11", "") for _target, message in conn.sent]
    assert not any(line.strip() == "MidnightScene" for line in lines)
    header = next(line for line in lines if line.startswith("Date"))
    data = next(line for line in lines if "Eve" in line)
    assert len(header) == len(data)
    conn.sent.clear()
    handler.handle(channel_event(".registered", "Dave"))
    assert conn.sent == []


def test_bot_user_can_use_member_commands_without_registering(tmp_path):
    handler, conn, registry = make_handler(tmp_path)
    assert not registry.is_registered("bob")
    handler.handle(channel_event(".addnews https://example.com/from-bot", "Bob"))
    assert "Added #1" in visible(conn)
    conn.sent.clear()
    handler.handle(channel_event(".banuser Eve Scene spam links", "Bob"))
    assert "Banned for Eve" in visible(conn)


def test_registered_list_is_pm_from_a_channel(tmp_path):
    handler, conn, _registry = make_handler(tmp_path)
    handler.handle(channel_event(".register MidnightScene Editor", "Carol"))
    conn.sent.clear()
    handler.handle(channel_event(".registered", "Alice", "#staff"))
    targets = {target for target, _message in conn.sent}
    assert "Alice" in targets
    assert "#staff" in targets
    private = visible_for(conn, "Alice")
    assert "Date" in private and "Position" in private
    assert "Carol" in private
    assert "Editor" in private
    assert "MidnightScene" in private
    assert "private message" in visible_for(conn, "#staff")


def test_registered_list_in_pm_stays_in_pm(tmp_path):
    handler, conn, _registry = make_handler(tmp_path)
    handler.handle(pm_event(".update Carol MidnightScene Editor", "Alice"))
    conn.sent.clear()
    handler.handle(pm_event(".registered", "Alice"))
    assert {target for target, _message in conn.sent} == {"Alice"}
    assert "Carol" in visible(conn)
    assert "private message" not in visible(conn)


def test_commands_outside_command_channels_are_ignored(tmp_path):
    handler, conn, registry = make_handler(tmp_path)
    handler.handle(channel_event(".register Carol MidnightScene Editor", "Carol", "#random"))
    assert conn.sent == []
    assert not registry.is_registered("carol")


def test_playback_timestamp_is_not_a_command(tmp_path):
    handler, conn, _registry = make_handler(tmp_path)
    handler.handle(pm_event("[22:13:40] .help", "Carol"))
    handler.handle(pm_event("[20:09:16] .banned", "OwnerNick"))
    assert conn.sent == []


def test_help_groups_member_commands_and_hides_admin(tmp_path):
    handler, conn, _registry = make_handler(tmp_path)
    handler.handle(pm_event(".help", "OwnerNick"))
    text = visible(conn)
    assert text.index(".help —") < text.index(".register")
    assert text.index(".unregister") < text.index(".news")
    assert text.index(".news") < text.index(".addnews")
    assert text.index(".banned") < text.index(".banuser")
    assert ".unban" not in text
    assert ".delnews" not in text
    assert ".join" not in text
    assert ".reconnect" not in text
    assert ".exit" not in text
    conn.sent.clear()
    handler.handle(pm_event(".help admin", "OwnerNick"))
    admin = visible(conn)
    assert admin.index(".registered") < admin.index(".unban")
    assert ".delnews" in admin
    assert admin.index(".join") < admin.index(".part")
    assert ".reconnect" not in admin
    assert ".exit" not in admin
    assert ".update" in admin
    assert ".adduser" in admin
    assert ".deluser" in admin
    conn.sent.clear()
    handler.handle(pm_event(".help admin", "Carol"))
    assert conn.sent == []


def test_ban_without_a_site_uses_the_registered_site(tmp_path):
    handler, conn, registry = make_handler(tmp_path)
    handler.handle(channel_event(".update Eve MidnightScene Editor", "Alice"))
    conn.sent.clear()
    handler.handle(channel_event(".ban Eve leaked a screen", "Bob"))
    assert "on MidnightScene" in visible(conn)
    row = registry.list_banned()[0]
    assert row["site"] == "MidnightScene"
    assert row["reason"] == "leaked a screen"
    assert row["added_at"][:10].count("-") == 2
    conn.sent.clear()
    handler.handle(channel_event(".banuser Eve MidnightScene still leaking", "Bob"))
    assert registry.list_banned()[0]["reason"] == "still leaking"
    conn.sent.clear()
    handler.handle(channel_event(".ban Stranger nowhere", "Bob"))
    assert "not registered" in visible(conn)


def test_pm_is_handled_even_if_the_target_nick_differs(tmp_path):
    handler, conn, _registry = make_handler(tmp_path)
    event = pm_event(".help", "Carol")
    event["incoming_target"] = "OtherNick"
    handler.handle(event)
    assert "InsiderBot" in visible(conn)


def test_admin_maintenance_and_owner_exit(tmp_path):
    handler, conn, registry = make_handler(tmp_path)

    class App:
        def __init__(self):
            self.exited = False

        def schedule_force_exit(self, delay=1.0):
            self.exited = True

    app = App()
    handler.application = app
    handler.handle(channel_event(".register MidnightScene Editor", "Carol"))
    handler.handle(channel_event(".banuser Eve MidnightScene reason", "Carol"))
    handler.handle(channel_event(".addnews https://example.com/z", "Carol"))
    conn.sent.clear()
    handler.handle(channel_event(".unban Eve MidnightScene", "Bob"))
    assert conn.sent == []
    assert registry.list_banned()
    conn.sent.clear()
    handler.handle(channel_event(".unban Eve", "Alice", "#staff"))
    assert registry.list_banned() == []
    conn.sent.clear()
    handler.handle(channel_event(".delnews 1", "Alice", "#staff"))
    assert registry.list_news(5) == []
    conn.sent.clear()
    handler.handle(channel_event(".unregister Carol", "Alice", "#staff"))
    assert not registry.is_registered("carol")
    conn.sent.clear()
    handler.handle(channel_event(".join #extra", "Alice", "#staff"))
    assert conn.joined == ["#extra"]
    conn.sent.clear()
    handler.handle(channel_event(".exit", "Alice", "#staff"))
    assert app.exited is False
    assert conn.sent == []
    conn.sent.clear()
    handler.handle(channel_event(".exit", "OwnerNick", "#staff"))
    assert app.exited is True


def test_owner_can_add_and_remove_a_bot_user(tmp_path):
    handler, conn, registry = make_handler(tmp_path)
    handler.handle(channel_event(".adduser NewNick", "Alice", "#staff"))
    assert conn.sent == []
    assert not registry.is_bot_user("NewNick")
    handler.handle(channel_event(".adduser NewNick", "OwnerNick", "#staff"))
    assert "Added NewNick as a bot user." in visible(conn)
    assert registry.is_bot_user("newnick")
    reopened = Registry(registry.path)
    assert reopened.is_bot_user("NewNick")
    conn.sent.clear()
    handler.handle(channel_event(".news", "NewNick"))
    assert "No news yet" in visible(conn)
    conn.sent.clear()
    handler.handle(channel_event(".adduser NewNick", "OwnerNick", "#staff"))
    assert "already a bot user" in visible(conn)
    conn.sent.clear()
    handler.handle(channel_event(".deluser Bob", "OwnerNick", "#staff"))
    assert "settings file" in visible(conn)
    conn.sent.clear()
    handler.handle(channel_event(".deluser NewNick", "OwnerNick", "#staff"))
    assert "Removed bot user NewNick." in visible(conn)
    assert not registry.is_bot_user("NewNick")
    conn.sent.clear()
    handler.handle(channel_event(".news", "NewNick"))
    assert conn.sent == []


def test_moderator_below_channel_rank_is_silent_for_admin_command(tmp_path):
    handler, conn, _registry = make_handler(tmp_path)
    handler.handle(channel_event(".registered", "ModNick", "#staff"))
    assert conn.sent == []
    handler.handle(channel_event(".registered", "ModNick", "#insiders"))
    assert conn.sent == []


def test_auth_tiers_and_channel_gate():
    config = Config(
        base_env(
            Path("data/unused.db"),
            CODER="DevNick",
            TEAM_LEADERS="LeadNick",
        )
    )
    assert config.resolve_user_auth_tier("OwnerNick") == "owner"
    assert config.resolve_user_auth_tier("DevNick") == "coder"
    assert config.resolve_user_auth_tier("LeadNick") == "team_leaders"
    assert config.resolve_user_auth_tier("Alice") == "admin"
    assert config.resolve_user_auth_tier("ModNick") == "moderators"
    assert config.resolve_user_auth_tier("Bob") == "torrent_moderators"
    assert config.resolve_user_auth_tier("Carol") is None
    assert config.is_admin_or_above("LeadNick")
    assert not config.is_admin_or_above("ModNick")
    assert not config.is_owner("DevNick")
    assert config.pubmsg_min_rank_for_channel("#staff") == 3
    assert config.pubmsg_min_rank_for_channel("#insiders") == 0
    assert config.is_bot_user("Bob")


def test_znc_and_sasl_warns_and_keeps_znc(tmp_path):
    config = Config(
        base_env(
            tmp_path / "x.db",
            IRC_USE_ZNC="true",
            IRC_USE_SASL="true",
            ZNC_USERNAME="InsiderBot/Example",
            ZNC_PASSWORD="secret",
            SASL_PASSWORD="secret",
        )
    )
    assert config.IRC_USE_SASL is False
    assert any("SASL is ignored" in message for message in config.warnings)


def test_znc_blank_server_uses_znc_server_not_localhost(tmp_path):
    config = Config(
        base_env(
            tmp_path / "x.db",
            IRC_SERVER="",
            IRC_NICKNAME="",
            IRC_PORT="6667",
            IRC_TLS="true",
            IRC_USE_ZNC="true",
            ZNC_SERVER="bouncer.example.net:6697",
            ZNC_USERNAME="InsiderBot/Example",
            ZNC_PASSWORD="secret",
            ZNC_IRC_NICK="InsiderBot",
        )
    )
    assert config.IRC_SERVER == "bouncer.example.net"
    assert config.IRC_PORT == 6697
    assert config.IRC_TLS is True
    assert config.IRC_NICKNAME == "InsiderBot"
    assert config.ZNC_PASSWORD == "secret"
    assert config.IRC_SERVER != "127.0.0.1"


def test_znc_without_server_does_not_use_localhost(tmp_path):
    config = Config(
        base_env(
            tmp_path / "x.db",
            IRC_SERVER="",
            IRC_USE_ZNC="true",
            ZNC_USERNAME="InsiderBot/Example",
            ZNC_PASSWORD="secret",
        )
    )
    assert config.IRC_SERVER == ""
    assert any(message.startswith("IRC_SERVER is not set") for message in config.warnings)


def test_nick_is_not_taken_from_the_bouncer_login(tmp_path):
    config = Config(
        base_env(
            tmp_path / "x.db",
            IRC_NICKNAME="",
            IRC_USE_ZNC="true",
            ZNC_USERNAME="SharedLogin/Example",
            ZNC_PASSWORD="secret",
            ZNC_IRC_NICK="InsiderBot",
        )
    )
    assert config.IRC_NICKNAME == "InsiderBot"
    assert config.irc_connect_nickname == "InsiderBot"
    assert config.znc_ident_username == "SharedLogin/Example"
    assert config.IRC_ZNC_STATUS_CONNECT is False


def test_settings_come_only_from_the_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "IRC_SERVER=from-file.example",
                "IRC_PORT=6667",
                "IRC_NICKNAME=InsiderBot",
                "BOT_OWNER=OwnerNick",
                "IRC_USE_ZNC=true",
                "ZNC_USERNAME=InsiderBot/Example",
                "ZNC_PASSWORD=secret",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("IRC_SERVER", "from-shell.example")
    monkeypatch.setenv("ZNC_USERNAME", "ModBot")
    monkeypatch.setenv("ZNC_PASSWORD", "from-shell")
    config = Config(env_file=env_file)
    assert config.IRC_SERVER == "from-file.example"
    assert config.ZNC_USERNAME == "InsiderBot/Example"
    assert config.ZNC_PASSWORD == "secret"
    assert config.settings_path == env_file


def test_missing_server_and_owner_are_warnings(tmp_path):
    config = Config(base_env(tmp_path / "x.db", IRC_SERVER="", BOT_OWNER=""))
    assert any(message.startswith("IRC_SERVER is not set") for message in config.warnings)
    assert any(message.startswith("BOT_OWNER is not set") for message in config.warnings)


def visible_for(connection, target: str) -> str:
    text = "\n".join(message for sent_target, message in connection.sent if sent_target == target)
    return text.replace("\u00a0", " ").replace("\x11", "")
