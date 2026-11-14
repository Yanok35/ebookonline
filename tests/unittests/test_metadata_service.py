"""
Background analysis of the books (srcs/metadata/service.py), with real
worker processes.
"""

import os
import signal

import pytest

from srcs.metadata import store
from srcs.metadata.service import MetadataService
from tests.conftest import make_book_pdf, wait_until


@pytest.fixture
def service(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    s = MetadataService(str(cache_dir), workers=1, nice=0)
    yield s
    s.stop()


def book(tmp_path, name):
    return str(make_book_pdf(tmp_path / name, [[(24, name)], [(9, "Dépôt légal : 2012")]]))


def test_request_writes_the_cache_file(service, tmp_path):
    service.start()
    service.request("a" * 40, book(tmp_path, "a.pdf"))
    assert wait_until(lambda: service.read("a" * 40) is not None and
                      not service.is_pending("a" * 40), timeout=20)
    assert service.read("a" * 40)["error"] is None
    # known up to date: not queued again
    service.request("a" * 40, book(tmp_path, "a.pdf"))
    assert not service.is_pending("a" * 40)


def test_requests_are_ignored_when_not_running(tmp_path):
    s = MetadataService(str(tmp_path), writable=False)
    s.start()
    s.request("a" * 40, "a.pdf")
    assert s.pending_count() == 0 and not s._processes


def test_urgent_request_goes_first(service):
    # queue only, without processes
    service._running = True
    for c in "abc":
        service.request(c * 40, c + ".pdf")
    service.request("c" * 40, "c.pdf", urgent=True)
    service.request("b" * 40, "moved/b.pdf")
    assert list(service._todo) == ["c" * 40, "a" * 40, "b" * 40]
    # the last path is kept
    assert service._todo["b" * 40] == ("moved/b.pdf", False)
    service._running = False


def test_dead_worker_is_restarted(service, tmp_path):
    service.start()
    pid = service._processes[0].pid
    os.kill(pid, signal.SIGKILL)
    assert wait_until(lambda: service._processes[0].pid != pid
                      and service._processes[0].is_alive(), timeout=10)
    service.request("b" * 40, book(tmp_path, "b.pdf"))
    assert wait_until(lambda: service.read("b" * 40) is not None, timeout=20)


def test_book_of_a_dead_worker_is_saved_as_failed(service, tmp_path):
    service.start()
    with service._cond:
        service._busy[0] = "c" * 40
        service._sent.add("c" * 40)
    os.kill(service._processes[0].pid, signal.SIGKILL)
    assert wait_until(lambda: service.read("c" * 40) is not None, timeout=10)
    entry = service.read("c" * 40)
    assert entry["error"].startswith("the PDF reader stopped")
    assert store.is_current(entry) and not service.is_pending("c" * 40)
