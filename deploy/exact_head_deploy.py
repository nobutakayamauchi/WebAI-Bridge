from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

TARGET_SHA = "0dffd30f362b5cf2d144fc9e5e47b6d11bbf7f98"
TARGET_TREE = "38be7d9d9145cfcf9bc3aba47eccb4f453da4439"
DOMAIN = "webai.140-238-62-74.sslip.io"
ORIGIN = "https://github.com/nobutakayamauchi/WebAI-Bridge.git"
CONSTRAINTS_SHA256 = "d41b7b3f4605e145baa0d6bed8ed4f07bdc673e645076df11b73d61622008dbf"
CONTROL = Path("/opt/webai-bridge-control")
RELEASE = Path("/opt/webai-bridge-releases") / TARGET_SHA
VENV = Path("/opt/webai-bridge-venvs") / TARGET_SHA
STATE = Path("/var/lib/webai-bridge")
ENV_FILE = Path("/etc/webai-bridge/webai-bridge.env")
SERVICE = Path("/etc/systemd/system/webai-bridge.service")
CONSTRAINTS = CONTROL / "deploy/runtime-tests-228.constraints.txt"


class GateError(RuntimeError):
    pass


def run(*argv: str, capture: bool = True, env: dict[str, str] | None = None) -> str:
    p = subprocess.run(argv, text=True, capture_output=capture, env=env, check=False)
    if p.returncode:
        detail = ((p.stderr or "") if capture else "").strip() or ((p.stdout or "") if capture else "").strip()
        raise GateError(f"command failed: {' '.join(argv[:3])}: {detail or p.returncode}")
    return (p.stdout or "").strip()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git(repo: Path, *args: str) -> str:
    return run("git", "-C", str(repo), *args)


def overlap(a: Path, b: Path) -> bool:
    a, b = a.resolve(strict=False), b.resolve(strict=False)
    return a == b or a in b.parents or b in a.parents


def verify_control() -> None:
    if not (CONTROL / ".git").exists():
        raise GateError(f"missing separate controller clone: {CONTROL}")
    origin = git(CONTROL, "remote", "get-url", "origin").removesuffix("/").removesuffix(".git")
    if origin != ORIGIN.removesuffix(".git"):
        raise GateError(f"unexpected controller origin: {origin}")
    if not CONSTRAINTS.is_file() or CONSTRAINTS.is_symlink() or sha256(CONSTRAINTS) != CONSTRAINTS_SHA256:
        raise GateError("runtime-tests #228 constraints evidence is missing or changed")
    if SERVICE.is_file() and not SERVICE.is_symlink():
        for line in SERVICE.read_text(encoding="utf-8").splitlines():
            if line.startswith("WorkingDirectory="):
                if overlap(Path(line.split("=", 1)[1]), CONTROL):
                    raise GateError("controller clone overlaps current production WorkingDirectory")
                break


def fetch_exact() -> None:
    run("git", "-C", str(CONTROL), "fetch", "--no-tags", "origin", TARGET_SHA)
    if git(CONTROL, "rev-parse", f"{TARGET_SHA}^{{commit}}").lower() != TARGET_SHA:
        raise GateError("exact commit identity mismatch")
    if git(CONTROL, "rev-parse", f"{TARGET_SHA}^{{tree}}").lower() != TARGET_TREE:
        raise GateError("exact tree identity mismatch")


def ensure_release() -> None:
    RELEASE.parent.mkdir(parents=True, exist_ok=True)
    if RELEASE.parent.is_symlink():
        raise GateError("release root must not be a symlink")
    if RELEASE.exists():
        if RELEASE.is_symlink() or not (RELEASE / ".git").exists() or git(RELEASE, "rev-parse", "HEAD").lower() != TARGET_SHA:
            raise GateError("existing release directory is not the exact target worktree")
    else:
        run("git", "-C", str(CONTROL), "worktree", "add", "--detach", str(RELEASE), TARGET_SHA)


def ensure_venv() -> tuple[str, ...]:
    if sys.version_info[:2] != (3, 12):
        raise GateError(f"Python 3.12 required to match CI #228; got {sys.version.split()[0]}")
    VENV.parent.mkdir(parents=True, exist_ok=True)
    marker = VENV / ".webai-exact-head.json"
    created = False
    if VENV.exists():
        if VENV.is_symlink() or not VENV.is_dir() or not marker.is_file() or marker.is_symlink():
            raise GateError("existing exact-head venv is not trusted")
    else:
        run(sys.executable, "-m", "venv", str(VENV))
        created = True
    python, pip = VENV / "bin/python", VENV / "bin/pip"
    if not python.is_file() or not pip.is_file():
        raise GateError("exact-head venv is incomplete")
    if created:
        run(str(python), "-m", "pip", "install", "pip==26.2.1", capture=False)
        run(str(pip), "install", "-r", str(RELEASE / "runtime/requirements.txt"), "-c", str(CONSTRAINTS), capture=False)
        freeze = tuple(sorted(x for x in run(str(pip), "freeze", "--all").splitlines() if x))
        marker.write_text(json.dumps({
            "schema": "webai-exact-head-venv-v1",
            "target_sha": TARGET_SHA,
            "constraints_sha256": CONSTRAINTS_SHA256,
            "python": run(str(python), "--version"),
            "freeze": list(freeze),
        }, indent=2) + "\n", encoding="utf-8")
        os.chmod(marker, 0o444)
    else:
        data = json.loads(marker.read_text(encoding="utf-8"))
        freeze = tuple(sorted(x for x in run(str(pip), "freeze", "--all").splitlines() if x))
        if data.get("target_sha") != TARGET_SHA or data.get("constraints_sha256") != CONSTRAINTS_SHA256 or data.get("freeze") != list(freeze):
            raise GateError("exact-head venv drifted from its immutable marker")
    link = RELEASE / "runtime/.venv"
    if link.exists() or link.is_symlink():
        if not link.is_symlink() or link.resolve() != VENV.resolve():
            raise GateError("runtime/.venv is not the pinned external venv")
    else:
        link.symlink_to(VENV.resolve(), target_is_directory=True)
    return freeze


def verify_source() -> None:
    if git(RELEASE, "rev-parse", "HEAD").lower() != TARGET_SHA:
        raise GateError("release HEAD drifted")
    run("git", "-C", str(RELEASE), "diff", "--exit-code", "--ignore-submodules=none")
    run("git", "-C", str(RELEASE), "diff", "--cached", "--exit-code", "--ignore-submodules=none")
    tracked = {x for x in run("git", "-C", str(RELEASE), "ls-files", "-z").split("\0") if x}
    dirs = set()
    for item in tracked:
        p = Path(item).parent
        while str(p) != ".":
            dirs.add(p.as_posix()); p = p.parent
    for root, child_dirs, files in os.walk(RELEASE, topdown=True, followlinks=False):
        rootp = Path(root)
        for name in list(child_dirs):
            p = rootp / name; rel = p.relative_to(RELEASE).as_posix()
            if rel == ".git": child_dirs.remove(name); continue
            if rel == "runtime/.venv":
                if not p.is_symlink() or p.resolve() != VENV.resolve(): raise GateError("unpinned runtime/.venv")
                child_dirs.remove(name); continue
            if rel not in dirs and rel not in tracked: raise GateError(f"untracked directory in release: {rel}")
        for name in files:
            rel = (rootp / name).relative_to(RELEASE).as_posix()
            if rel == ".git": continue
            if rel not in tracked: raise GateError(f"untracked file in release: {rel}")


def render() -> tuple[Path, Path, Path]:
    out = (Path("/run") if os.geteuid() == 0 else Path(tempfile.gettempdir())) / "webai-exact-head" / TARGET_SHA
    if out.exists():
        if out.is_symlink(): raise GateError("render output is a symlink")
        shutil.rmtree(out)
    out.mkdir(parents=True, mode=0o700)
    env = dict(os.environ); env["PYTHONDONTWRITEBYTECODE"] = "1"
    run(str(VENV / "bin/python"), str(RELEASE / "deploy/render_deployment.py"),
        "--domain", DOMAIN, "--runtime-dir", str(RELEASE / "runtime"), "--state-dir", str(STATE),
        "--revision", TARGET_SHA, "--creator-studio", "--output-dir", str(out), env=env)
    service, manifest = out / "webai-bridge.service", out / "deployment-manifest.json"
    text = service.read_text(encoding="utf-8")
    required = [
        f"WorkingDirectory={RELEASE}/runtime", f"Environment=DEPLOYED_REVISION={TARGET_SHA}",
        f"Environment=WEB_AI_CONFIG_DIR={STATE}/apps", "Environment=WEB_AI_ROUTE_SURFACE=commercial_handoff:app",
        f"EnvironmentFile=-{ENV_FILE}", "ProtectSystem=strict", f"ReadWritePaths={STATE}", "--no-access-log",
    ]
    if any(x not in text for x in required): raise GateError("rendered service lost an exact-head control")
    m = json.loads(manifest.read_text(encoding="utf-8"))
    expected = {"revision": TARGET_SHA, "domain": DOMAIN, "profile": "CREATOR_STUDIO_COMMERCIAL_V1",
                "runtime_dir": f"{RELEASE}/runtime", "state_dir": str(STATE), "route_surface": "commercial_handoff:app",
                "creator_studio_enabled": True, "creator_auth_required": True, "uvicorn_access_log_enabled": False,
                "query_authority_retention": False, "secret_values_in_manifest": False}
    if any(m.get(k) != v for k, v in expected.items()): raise GateError("deployment manifest mismatch")
    return out, service, manifest


def transient(name: str, body: str) -> None:
    if os.geteuid() != 0: raise GateError("transient systemd gates require root")
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+\.service", name): raise GateError("unsafe unit name")
    path = Path("/run/systemd/system") / name
    if path.exists() or path.is_symlink(): raise GateError(f"transient unit exists: {name}")
    path.write_text(body, encoding="utf-8"); os.chmod(path, 0o600)
    try:
        run("systemctl", "daemon-reload"); run("systemctl", "start", name)
    finally:
        subprocess.run(["systemctl", "reset-failed", name], capture_output=True)
        path.unlink(missing_ok=True); subprocess.run(["systemctl", "daemon-reload"], capture_output=True)


def candidate_preflight(service: Path) -> None:
    keep, pre = [], None; inside = False
    prefixes = ("User=", "Group=", "UMask=", "WorkingDirectory=", "EnvironmentFile=", "Environment=",
                "NoNewPrivileges=", "PrivateTmp=", "ProtectSystem=", "ProtectHome=", "ReadWritePaths=")
    for line in service.read_text(encoding="utf-8").splitlines():
        if line == "[Service]": inside = True; continue
        if inside and line.startswith("["): inside = False
        if not inside: continue
        if line.startswith("ExecStartPre="): pre = "ExecStart=" + line.split("=", 1)[1]
        elif line.startswith(prefixes): keep.append(line)
    if not pre: raise GateError("rendered service has no preflight")
    body = "\n".join(["[Service]", "Type=oneshot", *keep, "Environment=PYTHONDONTWRITEBYTECODE=1", pre, ""])
    transient(f"webai-preflight-{TARGET_SHA[:12]}.service", body)


def systemd_composition() -> None:
    fragment = run("systemctl", "show", "webai-bridge.service", "--property=FragmentPath", "--value")
    if Path(fragment).resolve(strict=False) != SERVICE.resolve(strict=False): raise GateError(f"unexpected FragmentPath: {fragment}")
    dropins = run("systemctl", "show", "webai-bridge.service", "--property=DropInPaths", "--value")
    if dropins: raise GateError(f"systemd drop-ins forbidden: {dropins}")


def running_identity() -> dict:
    run("systemctl", "is-active", "--quiet", "webai-bridge.service")
    pid_s = run("systemctl", "show", "webai-bridge.service", "--property=MainPID", "--value")
    if not pid_s.isdigit() or int(pid_s) <= 0: raise GateError("missing MainPID")
    pid = int(pid_s); cwd = Path(os.readlink(f"/proc/{pid}/cwd")).resolve()
    if cwd != (RELEASE / "runtime").resolve(): raise GateError(f"running cwd mismatch: {cwd}")
    env = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    if f"DEPLOYED_REVISION={TARGET_SHA}".encode() not in env: raise GateError("running revision mismatch")
    cmd = [x.decode(errors="replace") for x in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0") if x]
    if "commercial_handoff:app" not in cmd or "--no-access-log" not in cmd: raise GateError("running command surface mismatch")
    return {"pid": pid, "cwd": str(cwd), "revision": TARGET_SHA, "no_access_log": True}


def https_health() -> dict:
    with urllib.request.urlopen(f"https://{DOMAIN}/health", timeout=15) as r:
        if r.status != 200: raise GateError(f"HTTPS health={r.status}")
        r.read(4096)
    return {"url": f"https://{DOMAIN}/health", "status": 200}


def stripe_acceptance() -> None:
    body = "\n".join([
        "[Service]", "Type=oneshot", "User=webai", "Group=webai", "UMask=0077",
        f"WorkingDirectory={RELEASE}/runtime", f"EnvironmentFile=-{ENV_FILE}", "Environment=PYTHONDONTWRITEBYTECODE=1",
        f"ExecStart={RELEASE}/runtime/.venv/bin/python {RELEASE}/runtime/stripe_external_acceptance.py --domain {DOMAIN} --config-dir {STATE}/apps",
        "NoNewPrivileges=true", "PrivateTmp=true", "ProtectSystem=strict", "ProtectHome=true", ""])
    transient(f"webai-stripe-{TARGET_SHA[:12]}.service", body)


def prepare() -> dict:
    verify_control(); fetch_exact(); ensure_release(); freeze = ensure_venv(); verify_source(); out, service, manifest = render(); verify_source()
    candidate_preflight(service)
    return {"target_sha": TARGET_SHA, "tree": TARGET_TREE, "domain": DOMAIN, "release": str(RELEASE), "render": str(out),
            "service_sha256": sha256(service), "manifest_sha256": sha256(manifest), "constraints_sha256": CONSTRAINTS_SHA256,
            "dependency_freeze": list(freeze), "source_identity": "PASS", "candidate_preflight": "PASS", "production_mutation": False}


def evidence(payload: dict) -> Path:
    d = STATE / "deploy-evidence"; d.mkdir(parents=True, exist_ok=True); os.chmod(d, 0o700)
    p = d / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{TARGET_SHA[:12]}.json"; t = d / f".{p.name}.tmp"
    t.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); os.chmod(t, 0o600); os.replace(t, p); return p


def apply(approval: str) -> Path:
    if approval.lower() != TARGET_SHA: raise GateError("approval must exactly equal pinned target SHA")
    if os.geteuid() != 0: raise GateError("apply requires root")
    prepared = prepare(); systemd_composition()
    if not SERVICE.is_file() or SERVICE.is_symlink(): raise GateError("production service file is unsafe")
    rendered = Path(prepared["render"]) / "webai-bridge.service"
    backups = STATE / "deploy-backups"; backups.mkdir(parents=True, exist_ok=True); os.chmod(backups, 0o700)
    backup = backups / f"webai-bridge.service.before-{TARGET_SHA[:12]}-{int(time.time())}"
    shutil.copy2(SERVICE, backup, follow_symlinks=False); os.chmod(backup, 0o600)
    old_hash, new_hash = sha256(SERVICE), sha256(rendered); switched = False
    try:
        tmp = SERVICE.parent / f".{SERVICE.name}.new-{os.getpid()}"; shutil.copyfile(rendered, tmp); os.chmod(tmp, 0o644); os.replace(tmp, SERVICE); switched = True
        run("systemctl", "daemon-reload"); systemd_composition(); run("systemctl", "restart", "webai-bridge.service")
        running = running_identity(); health = https_health(); stripe_acceptance(); verify_source()
    except Exception as exc:
        if switched:
            shutil.copyfile(backup, SERVICE); os.chmod(SERVICE, 0o644)
            subprocess.run(["systemctl", "daemon-reload"], capture_output=True); subprocess.run(["systemctl", "restart", "webai-bridge.service"], capture_output=True)
        p = evidence({**prepared, "status": "ROLLED_BACK_AFTER_FAILURE" if switched else "PRE_SWITCH_FAILURE", "error": str(exc),
                      "old_service_sha256": old_hash, "candidate_service_sha256": new_hash})
        raise GateError(f"deploy failed; evidence={p}; cause={exc}") from exc
    return evidence({**prepared, "status": "DEPLOYED_AND_EXTERNAL_ACCEPTANCE_PASS", "production_mutation": True,
                     "running_identity": running, "https_health": health, "stripe_external_acceptance": "PASS",
                     "old_service_sha256": old_hash, "new_service_sha256": new_hash, "backup_service": str(backup),
                     "live_payment_performed": False, "secrets_recorded": False})


def main() -> int:
    ap = argparse.ArgumentParser(description="Pinned WebAI Bridge exact-head reality deploy capsule")
    ap.add_argument("action", choices=["prepare", "apply"]); ap.add_argument("--approve", default="")
    args = ap.parse_args()
    try:
        result = prepare() if args.action == "prepare" else {"evidence": str(apply(args.approve))}
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
    except GateError as exc:
        print(f"exact-head deploy: FAIL: {exc}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
