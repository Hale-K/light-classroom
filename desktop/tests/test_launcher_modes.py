"""Mode routing tests use temporary files and never start a GUI or application server."""
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("desktop_launcher", Path(__file__).parents[1] / "launcher.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


@pytest.mark.parametrize("mode,demo", [("normal", False), ("online", False), ("demo", True), ("offline", False)])
def test_package_mode_defaults(tmp_path, mode, demo):
    (tmp_path / "desktop-package.json").write_text(json.dumps({"mode": mode, "server_url": "https://school.example"}), encoding="utf-8-sig")
    assert launcher.package_options(tmp_path, []) == (mode, demo, "https://school.example")


def test_offline_can_contain_demo_seed(tmp_path):
    (tmp_path / "desktop-package.json").write_text('{"mode":"offline","demo":true}', encoding="utf-8")
    assert launcher.package_options(tmp_path, []) == ("offline", True, "")


def test_existing_demo_flag_remains_supported(tmp_path):
    assert launcher.package_options(tmp_path, ["--demo"]) == ("normal", True, "")


def test_separate_user_data_directories(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    directories = {launcher.app_data_dir(demo=mode == "demo", mode=mode) for mode in ("normal", "online", "demo", "offline")}
    assert len(directories) == 4
    assert launcher.app_data_dir(demo=True, mode="offline").name == "LightClassroomOfflineDemo"


def test_local_database_does_not_inherit_developer_server(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://developer/database")
    launcher.prepare_env(tmp_path, 12345)
    assert launcher.os.environ["DATABASE_URL"] == f"sqlite+aiosqlite:///{(tmp_path / 'light-classroom.db').as_posix()}"


@pytest.mark.parametrize("url", ["", "file:///C:/secret", "https://name:password@school.example", "https://school.example/?token=secret", "https://school.example/#fragment"])
def test_invalid_online_url_rejected(url):
    with pytest.raises(ValueError):
        launcher.validate_server_url(url)


def test_school_server_url_preserves_path():
    assert launcher.validate_server_url("https://school.example/app/") == "https://school.example/app"
