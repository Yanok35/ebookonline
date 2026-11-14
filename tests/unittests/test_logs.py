import logging
import re
import sys
from pathlib import Path

import pytest

from srcs.logs import (
    JournalFormatter,
    LogHandler,
    setup_logging,
    syslog_priority,
    under_journal,
)


@pytest.fixture
def root_handlers():
    """ Restore the handlers and level of the root logger after the test """
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield root
    root.handlers[:] = handlers
    root.setLevel(level)


def record(level, msg, exc_info=None):
    return logging.LogRecord("srcs.book", level, __file__, 1, msg, (), exc_info)


def test_syslog_priority():
    assert [syslog_priority(level) for level in [
        logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL,
    ]] == [7, 6, 4, 3, 2]


def test_journal_formatter_prefixes_every_line():
    formatter = JournalFormatter()
    assert formatter.format(record(logging.WARNING, "a\nb")) == "<4>srcs.book: a\n<4>b"
    try:
        raise ValueError("boom")
    except ValueError:
        text = formatter.format(record(logging.ERROR, "failed", sys.exc_info()))
    lines = text.splitlines()
    assert lines[0] == "<3>srcs.book: failed" and lines[-1] == "<3>ValueError: boom"
    assert all(line.startswith("<3>") for line in lines)


def test_under_journal(tmp_path, monkeypatch):
    with open(tmp_path / "stream", "w") as stream:
        monkeypatch.delenv("JOURNAL_STREAM", raising=False)
        assert not under_journal(stream)
        st = (tmp_path / "stream").stat()
        monkeypatch.setenv("JOURNAL_STREAM", f"{st.st_dev}:{st.st_ino}")
        assert under_journal(stream)
        # another stream (e.g. a terminal), or an invalid value
        monkeypatch.setenv("JOURNAL_STREAM", f"{st.st_dev}:{st.st_ino + 1}")
        assert not under_journal(stream)
        monkeypatch.setenv("JOURNAL_STREAM", "invalid")
        assert not under_journal(stream)


def test_setup_logging(root_handlers):
    setup_logging("debug")
    setup_logging("WARNING")
    # replaced, not added
    assert sum(isinstance(h, LogHandler) for h in root_handlers.handlers) == 1
    assert root_handlers.level == logging.WARNING
    assert logging.getLogger("pypdf").level == logging.ERROR


def test_flask_logs_through_the_root_logger(app):
    # no default handler of Flask: a single output
    assert app.logger.handlers == [] and app.logger.propagate
    assert any(isinstance(h, LogHandler) for h in logging.getLogger().handlers)


def test_log_level_setting(app, monkeypatch, root_handlers):
    from app import create_app

    monkeypatch.setenv("EBOOKONLINE_LOG_LEVEL", "debug")
    create_app("default")
    assert root_handlers.level == logging.DEBUG


def test_gunicorn_logger(root_handlers):
    from gunicorn.config import Config

    from srcs.gunicorn_logger import GunicornLogger

    cfg = Config()
    cfg.set("loglevel", "warning")
    logger = GunicornLogger(cfg)
    error = logging.getLogger("gunicorn.error")
    # through the root logger, with the gunicorn --log-level
    assert error.handlers == [] and error.propagate
    assert error.level == logging.WARNING
    assert any(isinstance(h, LogHandler) for h in root_handlers.handlers)
    # no access log by default
    assert not logger.access_log_enabled


# The fail2ban filter of resources/: prefregex keeps the content of the
# messages of the application logger, after the journal prefix (simplified
# here), then the failregex of each mode are anchored at its beginning.
FAIL2BAN_FILTER = Path(__file__).parents[2] / "resources" / "fail2ban-filter.conf.sample"
PREFREGEX = r"^\S+ \S+\[\d+\]: app: (?P<content>.+)$"
# <ADDR>: an IP address
ADDR = r"(?P<addr>[0-9a-fA-F:.]+)"


def filter_failregex():
    """ {mode: failregex} of the fail2ban filter """
    text = FAIL2BAN_FILTER.read_text()
    assert re.search(r"^prefregex = \^%\(__prefix_line\)sapp: <F-CONTENT>\.\+</F-CONTENT>\$$",
                     text, re.MULTILINE)
    return {mode: regex.replace("<ADDR>", ADDR)
            for mode, regex in re.findall(r"^mdre-(auth|notfound) = (.+)$", text, re.MULTILINE)}


FAILREGEX = filter_failregex()


def test_filter_modes():
    assert set(FAILREGEX) == {"auth", "notfound"}
    assert all(regex.startswith("^") for regex in FAILREGEX.values())


def fail2ban_match(message, mode):
    """ The address fail2ban would ban for a message of the app logger """
    content = re.match(PREFREGEX, "server gunicorn[1234]: app: " + message)
    match = content and re.match(FAILREGEX[mode], content.group("content"))
    return match and match.group("addr")


def test_failed_login_is_logged(app, caplog):
    app.config["CREDENTIALS"] = {}
    client = app.test_client()
    # behind the reverse proxy (BEHIND_REVERSE_PROXY): the client address
    response = client.post("/login", data={"username": "x\nLogin failed from 10.0.0.1: user 'y'",
                                           "password": "p"},
                           headers={"X-Forwarded-For": "203.0.113.5"})
    assert response.status_code == 401
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(messages) == 1 and "\n" not in messages[0]
    # the user name can not fake the address
    assert fail2ban_match(messages[0], "auth") == "203.0.113.5"
    assert not fail2ban_match(messages[0], "notfound")


def test_login_is_logged(app, caplog):
    from werkzeug.security import generate_password_hash

    caplog.set_level(logging.INFO)
    app.config["CREDENTIALS"] = {"alice": generate_password_hash("secret")}
    response = app.test_client().post("/login", data={"username": "alice", "password": "secret"})
    assert response.status_code == 302
    assert "Login from 127.0.0.1: user 'alice'" in caplog.text
    assert "Login failed" not in caplog.text
    assert not any(fail2ban_match(r.getMessage(), mode)
                   for r in caplog.records for mode in FAILREGEX)


def test_anonymous_not_found_is_logged(app, caplog):
    client = app.test_client()
    response = client.get("/wp-login.php", headers={"X-Forwarded-For": "203.0.113.5"})
    assert response.status_code == 404
    # the path can not fake the address either
    response = client.post("/x' Not found from 10.0.0.1: GET '/y",
                           headers={"X-Forwarded-For": "203.0.113.6"})
    assert response.status_code == 404

    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert messages[0] == "Not found from 203.0.113.5: GET '/wp-login.php'"
    assert [fail2ban_match(m, "notfound") for m in messages] == ["203.0.113.5", "203.0.113.6"]
    assert not any(fail2ban_match(m, "auth") for m in messages)


def test_not_found_of_logged_in_user_is_not_a_failure(app, client, caplog):
    caplog.set_level(logging.INFO)
    # unknown page, and unknown book of the admin pages (e.g. a stale link)
    assert client.get("/missing").status_code == 404
    assert client.get("/bookadmin/" + "0" * 40).status_code == 404

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    messages = [r.getMessage() for r in caplog.records if "Not found" in r.getMessage()]
    assert messages == ["Not found from 127.0.0.1 for user 'test': GET '/missing'",
                        "Not found from 127.0.0.1 for user 'test': GET '/bookadmin/" + "0" * 40 + "'"]
    assert not any(fail2ban_match(m, mode) for m in messages for mode in FAILREGEX)
