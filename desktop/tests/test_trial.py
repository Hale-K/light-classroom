import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location("trial", Path(__file__).parents[1] / "trial.py")
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class Clock:
    wall = 1_800_000_000.0
    tick = 1000.0

    def advance(self, seconds):
        self.wall += seconds
        self.tick += seconds


@pytest.fixture
def setup(tmp_path):
    clock = Clock()
    path = tmp_path / "trial" / "state.json"

    def create(days=30):
        return trial.TrialGuard(path, days, clock=lambda: clock.wall, monotonic=lambda: clock.tick)

    return clock, path, create


@pytest.mark.parametrize("days", [7, 30])
def test_first_launch_expiry_boundary_and_reinstallation(setup, days):
    clock, path, create = setup
    guard = create(days)
    assert guard.check() == ""
    clock.advance(days * 86400 - 1)
    assert guard.check() == ""
    # Simulate reinstall/rebuild and a larger trial setting: no extension.
    assert create(60).state["expires"] == guard.state["expires"]
    clock.advance(1)
    assert "试用期已结束" in create().check()
    assert json.loads(path.read_text())["expired"] is True
    clock.wall -= 86400
    assert "试用期已结束" in create().check()


def test_clock_rollback_and_recovery(setup):
    clock, _, create = setup
    guard = create()
    clock.advance(1000)
    assert guard.check() == ""
    clock.wall -= 1000
    assert "时间回拨" in create().check()
    clock.wall += 1000
    assert create().check() == ""


def test_monotonic_time_expires_even_if_wall_clock_stops(setup):
    clock, _, create = setup
    guard = create(1)
    clock.tick += 86400
    assert "试用期已结束" in guard.check()


@pytest.mark.parametrize("record", ["not json", "[]", "{}", '{"started":NaN}',
    '{"started":1,"last_seen":2,"expires":3,"expired":"false"}'])
def test_corrupt_state_fails_closed(setup, record):
    _, path, create = setup
    path.parent.mkdir()
    path.write_text(record)
    assert create().check()
    assert path.read_text() == record


def test_removed_record_fails_closed_while_running(setup):
    _, path, create = setup
    guard = create()
    path.unlink()
    assert "记录缺失" in guard.check()


def test_read_only_state_fails_closed(setup, monkeypatch):
    clock, _, create = setup
    guard = create()
    monkeypatch.setattr(guard, "_save", lambda: (_ for _ in ()).throw(PermissionError()))
    clock.advance(61)
    assert "无法保存" in guard.check()


def test_embedded_policy_independent_of_mode_json(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "_trial_policy", SimpleNamespace(TRIAL_DAYS=30))
    (tmp_path / "desktop-package.json").write_text('{"trial_days":0}')
    assert trial.bundled_trial_days() == 30
    monkeypatch.setitem(sys.modules, "_trial_policy", SimpleNamespace(TRIAL_DAYS=0))
    assert trial.bundled_trial_days() == 0


def test_missing_policy_fails_closed_in_packaged_app(monkeypatch):
    monkeypatch.setitem(sys.modules, "_trial_policy", None)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    with pytest.raises(ValueError, match="配置缺失"):
        trial.bundled_trial_days()


def test_api_page_websocket_and_lifespan_enforcement(setup):
    clock, _, create = setup
    guard = create(1)
    calls, sent = [], []

    async def app(scope, receive, send):
        calls.append(scope["type"])

    async def send(message):
        sent.append(message)

    async def run():
        middleware = trial.TrialMiddleware(app, guard)
        await middleware({"type": "http", "path": "/api/schools"}, None, send)
        clock.advance(86400)
        await middleware({"type": "http", "path": "/api/schools"}, None, send)
        assert sent[0]["status"] == 403
        assert json.loads(sent[1]["body"])["code"] == "TRIAL_BLOCKED"
        sent.clear()
        await middleware({"type": "http", "path": "/"}, None, send)
        assert sent[0]["status"] == 403
        assert "试用期已结束" in sent[1]["body"].decode()
        sent.clear()
        await middleware({"type": "websocket", "path": "/ws"}, None, send)
        assert sent == [{"type": "websocket.close", "code": 4403}]
        await middleware({"type": "lifespan"}, None, send)
        assert calls == ["http", "lifespan"]

    asyncio.run(run())


def test_notice_escapes_message():
    assert "&lt;script&gt;" in trial.blocked_html("<script>")


def test_active_websocket_closes_at_expiry(setup):
    clock, _, create = setup
    guard = create(1)
    messages = []

    async def app(scope, receive, send):
        clock.advance(86400)
        await asyncio.Event().wait()

    async def send(message):
        messages.append(message)

    asyncio.run(trial.TrialMiddleware(app, guard)({"type": "websocket"}, None, send))
    assert messages == [{"type": "websocket.close", "code": 4403}]


def load_launcher():
    source = Path(__file__).parents[1] / "launcher.py"
    module_spec = importlib.util.spec_from_file_location("trial_test_launcher", source)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def test_expired_startup_never_starts_backend_or_copies_seed(tmp_path, monkeypatch):
    launcher = load_launcher()
    data = tmp_path / "LightClassroomDemo"
    data.mkdir()
    called = []
    monkeypatch.setitem(sys.modules, "trial", trial)
    monkeypatch.setattr(trial, "bundled_trial_days", lambda: 30)
    monkeypatch.setattr(trial, "TrialGuard", lambda *args: SimpleNamespace(check=lambda: "试用期已结束"))
    monkeypatch.setattr(launcher, "package_options", lambda *args: ("demo", True, ""))
    monkeypatch.setattr(launcher, "app_data_dir", lambda **kwargs: data)
    monkeypatch.setattr(launcher, "show_trial_block", lambda *args: called.append(args))
    monkeypatch.setattr(launcher, "install_demo_seed", lambda *args: pytest.fail("must not copy seed"))
    original_out, original_err = sys.stdout, sys.stderr
    try:
        launcher.main()
    finally:
        log = sys.stdout
        sys.stdout, sys.stderr = original_out, original_err
        if log is not original_out:
            log.close()
    assert called == [("试用期已结束", data)]


def test_window_monitor_and_download_bridge_block(setup, monkeypatch):
    clock, _, create = setup
    guard = create(1)
    launcher = load_launcher()
    monkeypatch.setitem(sys.modules, "trial", trial)
    pages = []
    clock.advance(86400)
    launcher.monitor_trial(SimpleNamespace(load_html=pages.append), guard,
                           SimpleNamespace(wait=lambda seconds: False))
    assert len(pages) == 1 and "试用期已结束" in pages[0]
    bridge = launcher._DesktopBridge("https://example.com", trial=guard)
    assert "试用期已结束" in bridge.save_file("/api/export")


@pytest.mark.parametrize("days", [0, 7, 30])
def test_packaging_spec_embeds_policy(tmp_path, monkeypatch, days):
    # Execute the real spec with build operations stubbed: verify the generated
    # module and Analysis paths, without producing a full installer in unit tests.
    import runpy
    import PyInstaller.utils.hooks

    config = tmp_path / "desktop-package.json"
    config.write_text(json.dumps({"trial_days": days}), encoding="utf-8-sig")
    monkeypatch.setenv("LIGHT_DESKTOP_PACKAGE_CONFIG", str(config))
    monkeypatch.delenv("LIGHT_DEMO_SEED_DIR", raising=False)
    monkeypatch.setattr(PyInstaller.utils.hooks, "collect_all", lambda name: ([], [], []))
    captured = {}

    def analysis(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])

    source_dir = Path(__file__).parents[1]
    runpy.run_path(str(source_dir / "light-classroom.spec"), init_globals={
        "SPECPATH": str(source_dir), "workpath": str(tmp_path), "Analysis": analysis,
        "PYZ": lambda *a, **k: None, "EXE": lambda *a, **k: None, "COLLECT": lambda *a, **k: None,
    })
    policy_dir = tmp_path / "trial-policy"
    assert runpy.run_path(str(policy_dir / "_trial_policy.py"))["TRIAL_DAYS"] == days
    assert str(policy_dir) in captured["pathex"]
    assert "_trial_policy" in captured["hiddenimports"]
