from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_DIR / "deploy" / "render_deployment.py"
spec = importlib.util.spec_from_file_location("render_deployment_query_logging", MODULE_PATH)
render = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(render)


def _values() -> dict:
    return render.validate_inputs(
        domain="ai.example.com",
        runtime_dir="/opt/webai-bridge/runtime",
        state_dir="/var/lib/webai-bridge",
        revision="b" * 40,
        user="webai",
        group="webai",
    )


def test_production_uvicorn_access_log_is_disabled_for_handoff_query_authority(tmp_path: Path) -> None:
    written = render.write_outputs(_values(), tmp_path, creator_studio=True)
    unit = Path(written["webai-bridge.service"]).read_text(encoding="utf-8")

    exec_start = next(line for line in unit.splitlines() if line.startswith("ExecStart="))
    assert "commercial_handoff:app" in exec_start
    assert "--no-access-log" in exec_start

    manifest = json.loads(Path(written["deployment-manifest.json"]).read_text(encoding="utf-8"))
    assert manifest["uvicorn_access_log_enabled"] is False
    assert manifest["query_authority_retention"] is False


def test_buyer_only_production_also_does_not_retain_query_strings(tmp_path: Path) -> None:
    written = render.write_outputs(_values(), tmp_path, creator_studio=False)
    unit = Path(written["webai-bridge.service"]).read_text(encoding="utf-8")

    exec_start = next(line for line in unit.splitlines() if line.startswith("ExecStart="))
    assert "commercial:app" in exec_start
    assert "--no-access-log" in exec_start
