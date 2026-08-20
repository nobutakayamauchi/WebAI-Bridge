from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "runtime/production_server.py"
spec = importlib.util.spec_from_file_location("production_server", PATH)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def test_launcher_pins_single_worker_no_reload_no_access_log_and_proxy_trust(monkeypatch):
    captured = {}

    def fake_run(app, **kwargs):
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(m.uvicorn, "run", fake_run)
    assert m.main(["commercial_handoff:app", "--no-access-log"]) == 0
    assert captured == {
        "app": "commercial_handoff:app",
        "host": "127.0.0.1",
        "port": 8080,
        "workers": 1,
        "reload": False,
        "factory": False,
        "access_log": False,
        "proxy_headers": True,
        "forwarded_allow_ips": "127.0.0.1",
        "server_header": False,
    }


def test_launcher_refuses_different_application():
    with pytest.raises(SystemExit):
        m.main(["runtime.app:app", "--no-access-log"])


def test_launcher_refuses_access_log_flag_omission():
    with pytest.raises(SystemExit):
        m.main(["commercial_handoff:app"])
