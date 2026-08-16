from __future__ import annotations

import importlib.util
import stat
import sys
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[2]
DEPLOY_DIR = REPO_DIR / "deploy"
MODULE_PATH = DEPLOY_DIR / "paid_dogfood_host.py"
if str(DEPLOY_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOY_DIR))
spec = importlib.util.spec_from_file_location("paid_dogfood_host_auto", MODULE_PATH)
launcher = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(launcher)


def test_cookie_secret_is_persistent_owner_only_and_not_regenerated(tmp_path):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    path = state / "cookie.secret"
    first = launcher.ensure_private_secret(path, parent=state)
    second = launcher.ensure_private_secret(path, parent=state)
    assert first == second
    assert len(first) >= 32
    assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0


def test_paid_env_carries_cookie_secret_and_optional_stripe_key_without_print_contract(tmp_path):
    runtime = tmp_path / "repo" / "runtime"
    state = tmp_path / "state"
    config = state / "apps"
    runtime.mkdir(parents=True)
    config.mkdir(parents=True)
    env = launcher.build_paid_env(
        base={"WEB_AI_STRIPE_SECRET_KEY": "rk_live_example"},
        runtime_dir=runtime,
        state_dir=state,
        config_dir=config,
        revision="a" * 40,
        cookie_secret="c" * 48,
    )
    assert env["WEB_AI_STRIPE_SECRET_KEY"] == "rk_live_example"
    assert env["WEB_AI_ENTITLEMENT_COOKIE_SECRET"] == "c" * 48
    assert env["WEB_AI_ALLOW_INSECURE_HTTP"] == "0"
