"""Real native scans exercise GUI polling, controls, completion, and worker isolation."""

# ruff: noqa: PLR2004 -- polling limits and fixture totals are contract assertions.

import os
import threading
from collections.abc import Iterator
from importlib.util import find_spec
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

if find_spec("PySide6") is None:
    if os.environ.get("DAFREE_REQUIRE_GUI") == "1":
        pytest.fail("PySide6 is required when DAFREE_REQUIRE_GUI=1", pytrace=False)
    pytest.skip("PySide6 is not installed", allow_module_level=True)

from PySide6.QtCore import QCoreApplication, QEvent, QTimer

from dafree.api import (
    Backend,
    EntryKind,
    IssueKind,
    NodeFlags,
    Notice,
    NoticeKind,
    ScanHandle,
    ScanModeUsed,
    ScanProgress,
    ScanRequest,
    ScanResult,
    ScanState,
    Tree,
    scan,
)
from dafree.api.testing import MockEntry, MockSpec, make_mock_backend
from dafree.api.types import ScanIssue
from dafree.gui.controllers import scan_controller as module
from dafree.gui.controllers.scan_controller import ScanController
from dafree.gui.controllers.task_runner import TaskRunner

pytestmark = pytest.mark.gui


def native_backend(root: Path, directories: int = 20, delay: int = 80) -> Backend:
    """Build a delayed native filesystem entirely under a test-owned root."""
    entries = [MockEntry(root, EntryKind.DIR)]
    for index in range(directories):
        folder = root / f"dir{index}"
        entries.extend(
            [MockEntry(folder, EntryKind.DIR), MockEntry(folder / "file", size=index + 1)]
        )
    return make_mock_backend(MockSpec(entries, delay_ms=delay))


@pytest.fixture
def owned(qtbot: QtBot) -> Iterator[list[ScanController]]:
    """Finish every test scan before its temporary namespace is removed."""
    controllers: list[ScanController] = []
    yield controllers
    for controller in controllers:
        if controller.running:
            controller.cancel()
            controller._poll()
            qtbot.waitUntil(lambda controller=controller: not controller.running, timeout=10_000)
        controller.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    controllers.clear()


def test_progress_signals_emitted(
    qtbot: QtBot, tmp_path: Path, owned: list[ScanController]
) -> None:
    """A delayed native scan yields monotonic GUI updates and one final result."""
    controller = ScanController(backend=native_backend(tmp_path))
    owned.append(controller)
    progress: list[ScanProgress] = []
    completed: list[ScanResult] = []
    controller.progressChanged.connect(progress.append)
    controller.finished.connect(completed.append)
    with qtbot.waitSignal(controller.finished, timeout=10_000) as done:
        controller.start(ScanRequest([tmp_path], threads=1))
        assert controller.running
    assert done.args is not None
    assert len(progress) >= 2
    assert [item.files for item in progress] == sorted(item.files for item in progress)
    assert progress[-1].state == ScanState.DONE
    assert completed[0].summary.files == 20
    assert completed[0].summary.bytes == sum(range(1, 21))
    assert len(completed) == 1
    assert not controller.running
    assert not controller._timer.isActive()


def test_cancel_emits_finished_with_partial(
    qtbot: QtBot, tmp_path: Path, owned: list[ScanController]
) -> None:
    """Cancel stays asynchronous and returns native partial metadata exactly once."""
    controller = ScanController(backend=native_backend(tmp_path, directories=60))
    owned.append(controller)
    progress: list[ScanProgress] = []
    controller.progressChanged.connect(progress.append)
    controller.start(ScanRequest([tmp_path], threads=1))
    qtbot.waitUntil(lambda: bool(progress) and progress[-1].files > 0, timeout=5000)
    with qtbot.waitSignal(controller.finished, timeout=10_000) as done:
        controller.cancel()
    assert done.args is not None
    result = done.args[0]
    assert result.summary.cancelled
    assert result.tree.meta().cancelled
    assert result.summary.files < 60
    assert any(result.tree.node(node).flags & NodeFlags.PARTIAL for node in range(len(result.tree)))
    assert not controller.running


def test_pause_stops_progress_growth(
    qtbot: QtBot, tmp_path: Path, owned: list[ScanController]
) -> None:
    """After in-flight reads settle, paused counters remain stable and resume grows them."""
    controller = ScanController(backend=native_backend(tmp_path, directories=60))
    owned.append(controller)
    progress: list[ScanProgress] = []
    controller.progressChanged.connect(progress.append)
    controller.start(ScanRequest([tmp_path], threads=1))
    qtbot.waitUntil(lambda: bool(progress) and progress[-1].files > 0, timeout=5000)
    controller.pause()
    qtbot.waitUntil(lambda: progress[-1].state == ScanState.PAUSED, timeout=5000)
    qtbot.wait(350)
    before = (progress[-1].files, progress[-1].dirs, progress[-1].bytes)
    qtbot.wait(750)
    assert (progress[-1].files, progress[-1].dirs, progress[-1].bytes) == before
    controller.resume()
    qtbot.waitUntil(lambda: progress[-1].files > before[0], timeout=5000)
    with qtbot.waitSignal(controller.finished, timeout=10_000):
        controller.cancel()


def test_cancel_during_startup_keeps_gui_responsive_and_copies_request(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owned: list[ScanController]
) -> None:
    """Root validation is off-thread; startup controls survive until the handle arrives."""
    backend = native_backend(tmp_path, directories=60)
    original = module.start_scan
    release, entered, heartbeat = threading.Event(), threading.Event(), threading.Event()
    gui_thread = threading.get_ident()
    worker_threads: list[int] = []

    def delayed(req: ScanRequest, *, backend: Backend | None = None) -> ScanHandle:
        worker_threads.append(threading.get_ident())
        entered.set()
        assert release.wait(5)
        return original(req, backend=backend)

    monkeypatch.setattr(module, "start_scan", delayed)
    controller = ScanController(backend=backend)
    owned.append(controller)
    request = ScanRequest([tmp_path], threads=1)
    try:
        with qtbot.waitSignal(controller.finished, timeout=10_000) as done:
            controller.start(request)
            qtbot.waitUntil(entered.is_set, timeout=2000)
            request.targets = []
            QTimer.singleShot(0, heartbeat.set)
            qtbot.waitUntil(heartbeat.is_set, timeout=2000)
            with pytest.raises(RuntimeError, match="already running"):
                controller.start(request)
            controller.pause()
            controller.resume()
            controller.cancel()
            release.set()
        assert done.args is not None
        assert done.args[0].summary.cancelled
        assert worker_threads and all(thread != gui_thread for thread in worker_threads)
    finally:
        release.set()


def test_start_failure_is_reported_and_controller_can_restart(
    qtbot: QtBot, tmp_path: Path, owned: list[ScanController]
) -> None:
    """An invalid target has a distinct error signal and does not leave a busy controller."""
    controller = ScanController(backend=native_backend(tmp_path, directories=1, delay=0))
    owned.append(controller)
    finished: list[ScanResult] = []
    controller.finished.connect(finished.append)
    with qtbot.waitSignal(controller.failed, timeout=5000) as failed:
        controller.start(ScanRequest([tmp_path / "missing"], threads=1))
    assert failed.args and failed.args[0]
    assert not controller.running
    assert not finished
    with qtbot.waitSignal(controller.finished, timeout=5000):
        controller.start(ScanRequest([tmp_path], threads=1))
    assert len(finished) == 1


class _Probe(ScanHandle):
    """Observe public API calls while retaining a real native result/tree."""

    def __init__(self, result: ScanResult, root: Path) -> None:
        self.result, self.root = result, root
        self.done = False
        self.batches: list[int] = []
        self.partial_calls = 0
        self.waits: list[tuple[int, int]] = []
        self.take_threads: list[int] = []
        self.issues = [ScanIssue(str(root / "bad-\ud800"), IssueKind.IO, "first")]
        self.notices = [Notice(NoticeKind.NETWORK_VOLUME, "first")]
        self.bad_progress = False
        self.bad_result = False

    def progress(self) -> ScanProgress:
        if self.bad_progress:
            raise RuntimeError("poll failure")
        return ScanProgress(
            1,
            0,
            1,
            1,
            1,
            str(self.root),
            0,
            ScanState.DONE if self.done else ScanState.RUNNING,
            None,
            ScanModeUsed.WALK,
        )

    def drain_issues(self, max: int = 1000) -> list[ScanIssue]:
        self.batches.append(max)
        items, self.issues = self.issues[:max], self.issues[max:]
        return items

    def drain_notices(self) -> list[Notice]:
        items, self.notices = self.notices, []
        return items

    def partial_tree(self) -> Tree:
        self.partial_calls += 1
        return self.result.tree

    def wait(self, timeout_ms: int) -> bool:
        self.waits.append((threading.get_ident(), timeout_ms))
        return self.done

    def take_result(self) -> ScanResult:
        self.take_threads.append(threading.get_ident())
        if self.bad_result:
            raise RuntimeError("result failure")
        self.issues.append(ScanIssue(str(self.root), IssueKind.IO, "late"))
        self.notices.append(Notice(NoticeKind.ROTATIONAL_DISK, "late"))
        return self.result

    def cancel(self) -> None:
        self.done = True


def test_poll_protocol_partial_rate_and_final_drains(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owned: list[ScanController]
) -> None:
    """Every fourth tick requests a snapshot, no faster than 1/s; final drains precede finished."""
    result = scan(ScanRequest([tmp_path], threads=1), backend=native_backend(tmp_path, 1, 0))
    probe = _Probe(result, tmp_path)
    now = [0.0]
    monkeypatch.setattr(module, "monotonic", lambda: now[0])
    monkeypatch.setattr(module, "start_scan", lambda _req, **_kwargs: probe)
    controller = ScanController()
    owned.append(controller)
    issues: list[ScanIssue] = []
    notices: list[Notice] = []
    partials: list[object] = []
    controller.issuesAdded.connect(issues.extend)
    controller.noticeReceived.connect(notices.append)
    controller.partialTreeReady.connect(partials.append)
    controller.start(ScanRequest([tmp_path]))
    qtbot.waitUntil(lambda: controller._handle is probe, timeout=5000)
    controller._timer.stop()
    assert controller._timer.interval() == 250
    for tick in range(1, 13):
        now[0] = tick * 0.25
        controller._poll()
    assert probe.partial_calls == 3
    assert len(partials) == 3
    for _tick in range(4):
        controller._poll()  # Four callbacks without elapsed time must not request another copy.
    assert probe.partial_calls == 3
    assert issues[0].path.endswith("bad-\ud800")
    gui_thread = threading.get_ident()
    with qtbot.waitSignal(controller.finished, timeout=5000):
        probe.done = True
        controller._poll()
    assert [issue.message for issue in issues] == ["first", "late"]
    assert [notice.detail for notice in notices] == ["first", "late"]
    assert all(batch == 1000 for batch in probe.batches)
    assert len(probe.take_threads) == 1 and probe.take_threads[0] != gui_thread
    assert all(timeout == 0 for thread, timeout in probe.waits if thread == gui_thread)


def test_poll_failure_cancels_and_joins_off_thread(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owned: list[ScanController]
) -> None:
    """Even an unexpected polling failure consumes the cancelled handle in a worker."""
    result = scan(ScanRequest([tmp_path], threads=1), backend=native_backend(tmp_path, 1, 0))
    probe = _Probe(result, tmp_path)
    monkeypatch.setattr(module, "start_scan", lambda _req, **_kwargs: probe)
    controller = ScanController()
    owned.append(controller)
    controller.start(ScanRequest([tmp_path]))
    qtbot.waitUntil(lambda: controller._handle is probe, timeout=5000)
    with qtbot.waitSignal(controller.failed, timeout=5000) as failed:
        probe.bad_progress = True
        controller._poll()
    assert failed.args == ["poll failure"]
    assert not controller.running
    assert probe.take_threads and probe.take_threads[0] != threading.get_ident()


def test_result_collection_failure_is_distinct_from_finished(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owned: list[ScanController]
) -> None:
    """A take_result error reaches failed without fabricating a completed ScanResult."""
    result = scan(ScanRequest([tmp_path], threads=1), backend=native_backend(tmp_path, 1, 0))
    probe = _Probe(result, tmp_path)
    probe.bad_result = True
    monkeypatch.setattr(module, "start_scan", lambda _req, **_kwargs: probe)
    controller = ScanController()
    owned.append(controller)
    finished: list[ScanResult] = []
    controller.finished.connect(finished.append)
    controller.start(ScanRequest([tmp_path]))
    qtbot.waitUntil(lambda: controller._handle is probe, timeout=5000)
    with qtbot.waitSignal(controller.failed, timeout=5000) as failed:
        probe.done = True
        controller._poll()
    assert failed.args == ["result failure"]
    assert not finished
    assert not controller.running
    assert probe.take_threads and probe.take_threads[0] != threading.get_ident()


def test_shared_runner_does_not_mix_other_jobs_with_scan_results(
    qtbot: QtBot, tmp_path: Path, owned: list[ScanController]
) -> None:
    """Unrelated successes and failures in a shared pool cannot finish or fail this scan."""
    runner = TaskRunner()
    controller = ScanController(runner=runner, backend=native_backend(tmp_path, 5, 50))
    owned.append(controller)
    errors: list[str] = []
    controller.failed.connect(errors.append)

    def unrelated() -> None:
        raise ValueError("unrelated")

    with qtbot.waitSignal(controller.finished, timeout=10_000) as finished:
        controller.start(ScanRequest([tmp_path], threads=1))
        runner.submit(unrelated, task_id="other failure")
        runner.submit(lambda: "other result", task_id="other success")
    assert finished.args is not None and finished.args[0].summary.files == 5
    assert not errors
