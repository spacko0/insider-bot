"""NickServ identification is dropped as soon as the nick quits."""
from core.identity import NickIdentity


def _run(callbacks):
    for callback in callbacks:
        callback()


def test_whois_account_runs_the_queued_command_until_quit():
    gate = NickIdentity()
    ran = []
    assert gate.authorize("Ada", lambda: ran.append("ada")) == "ask"
    _run(gate.note_account("Ada", "ada"))
    assert ran == ["ada"]
    assert gate.is_identified("Ada")
    gate.forget("Ada")
    assert not gate.is_identified("Ada")
    assert gate.authorize("Ada", lambda: ran.append("again")) == "ask"
    assert ran == ["ada"]


def test_unidentified_nick_is_ignored():
    gate = NickIdentity()
    ran = []
    assert gate.authorize("Ada", lambda: ran.append(1)) == "ask"
    assert gate.note_whois_end("Ada") == []
    assert gate.note_status("Ada", 0) == []
    assert ran == []
    assert gate.authorize("Ada", lambda: ran.append(2)) == "drop"


def test_nickserv_status_3_is_enough():
    gate = NickIdentity()
    ran = []
    gate.authorize("Ada", lambda: ran.append(1))
    _run(gate.observe_services("NickServ", "STATUS Ada 3"))
    assert ran == [1]


def test_rename_keeps_the_identified_connection():
    gate = NickIdentity()
    ran = []
    gate.authorize("Ada", lambda: ran.append(1))
    _run(gate.note_account("Ada", "ada"))
    gate.rename("Ada", "Ada_")
    assert not gate.is_identified("Ada")
    assert gate.is_identified("Ada_")
    assert gate.authorize("Ada_", lambda: ran.append(2)) == "run"
    assert ran == [1, 2]


def test_status_below_3_after_whois_does_not_run():
    gate = NickIdentity()
    ran = []
    gate.authorize("Bob", lambda: ran.append(1))
    assert gate.observe_services("NickServ", "Bob ACC 1") == []
    assert gate.note_whois_end("Bob") == []
    assert ran == []
