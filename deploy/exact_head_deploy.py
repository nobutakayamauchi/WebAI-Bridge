from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
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


def live_service_working_directory() -> Path:
    raw = run(
        "systemctl",
        "show",
        "webai-bridge.service",
        "--property=WorkingDirectory",
        "--value",
    )
    if not raw:
        raise GateError("current production WorkingDirectory is not established")
    return Path(raw).resolve(strict=False)


def verify_control() -> None:
    if not (CONTROL / ".git").exists():
        raise GateError(f"missing separate controller clone: {CONTROL}")
    origin = git(CONTROL, "remote", "get-url", "origin").removesuffix("/").removesuffix(".git")
    if origin != ORIGIN.removesuffix(".git"):
        raise GateError(f"unexpected controller origin: {origin}")
    if not CONSTRAINTS.is_file() or CONSTRAINTS.is_symlink() or sha256(CONSTRAINTS) != CONSTRAINTS_SHA256:
        raise GateError("runtime-tests #228 constraints evidence is missing or changed")

    dirty = git(CONTROL, "status", "--porcelain", "--untracked-files=all")
    if dirty:
        raise GateError("controller worktree must be completely clean")

    run("git", "-C", str(CONTROL), "fetch", "--no-tags", "origin", "main")
    branch = git(CONTROL, "rev-parse", "--abbrev-ref", "HEAD")
    if branch != "main":
        raise GateError(f"controller must run canonical main, got: {branch}")
    if git(CONTROL, "rev-parse", "HEAD") != git(CONTROL, "rev-parse", "origin/main"):
        raise GateError("controller main is not exactly synchronized with origin/main")

    if overlap(live_service_working_directory(), CONTROL):
        raise GateError("controller clone overlaps actual production WorkingDirectory")


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
    if VENV.parent.is_symlink():
        raise GateError("venv root must not be a symlink")
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
    python_version = run(str(python), "--version")
    if created:
        run(str(python), "-m", "pip", "install", "pip==26.2.1", capture=False)
        run(str(pip), "install", "-r", str(RELEASE / "runtime/requirements.txt"), "-c", str(CONSTRAINTS), capture=False)
        freeze = tuple(sorted(x for x in run(str(pip), "freeze", "--all").splitlines() if x))
        marker.write_text(json.dumps({
            "schema": "webai-exact-head-venv-v1",
            "target_sha": TARGET_SHA,
            "constraints_sha256": CONSTRAINTS_SHA256,
            "python": python_version,
            "freeze": list(freeze),
        }, indent=2) + "\n", encoding="utf-8")
        os.chmod(marker, 0o444)
    else:
        data = json.loads(marker.read_text(encoding="utf-8"))
        freeze = tuple(sorted(x for x in run(str(pip), "freeze", "--all").splitlines() if x))
        if (
            data.get("target_sha") != TARGET_SHA
            or data.get("constraints_sha256") != CONSTRAINTS_SHA256
            or data.get("python") != python_version
            or data.get("freeze") != list(freeze)
        ):
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
            dirs.add(p.as_posix())
            p = p.parent
    for root, child_dirs, files in os.walk(RELEASE, topdown=True, followlinks=False):
        rootp = Path(root)
        for name in list(child_dirs):
            p = rootp / name
            rel = p.relative_to(RELEASE).as_posix()
            if rel == ".git":
                child_dirs.remove(name)
                continue
            if rel == "runtime/.venv":
                if not p.is_symlink() or p.resolve() != VENV.resolve():
                    raise GateError("unpinned runtime/.venv")
                child_dirs.remove(name)
                continue
            if rel not in dirs and rel not in tracked:
                raise GateError(f"untracked directory in release: {rel}")
        for name in files:
            rel = (rootp / name).relative_to(RELEASE).as_posix()
            if rel == ".git":
                continue
            if rel not in tracked:
                raise GateError(f"untracked file in release: {rel}")


def render() -> tuple[Path, Path, Path]:
    out = (Path("/run") if os.geteuid() == 0 else Path(tempfile.gettempdir())) / "webai-exact-head" / TARGET_SHA
    if out.exists():
        if out.is_symlink():
            raise GateError("render output is a symlink")
        shutil.rmtree(out)
    out.mkdir(parents=True, mode=0o700)
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    run(
        str(VENV / "bin/python"),
        str(RELEASE / "deploy/render_deployment.py"),
        "--domain",
        DOMAIN,
        "--runtime-dir",
        str(RELEASE / "runtime"),
        "--state-dir",
        str(STATE),
        "--revision",
        TARGET_SHA,
        "--creator-studio",
        "--output-dir",
        str(out),
        env=env,
    )
    service, manifest = out / "webai-bridge.service", out / "deployment-manifest.json"
    text = service.read_text(encoding="utf-8")
    required = [
        f"WorkingDirectory={RELEASE}/runtime",
        f"Environment=DEPLOYED_REVISION={TARGET_SHA}",
        f"Environment=WEB_AI_CONFIG_DIR={STATE}/apps",
        "Environment=WEB_AI_ROUTE_SURFACE=commercial_handoff:app",
        f"EnvironmentFile=-{ENV_FILE}",
        "ProtectSystem=strict",
        f"ReadWritePaths={STATE}",
        "--no-access-log",
    ]
    if any(x not in text for x in required):
        raise GateError("rendered service lost an exact-head control")
    m = json.loads(manifest.read_text(encoding="utf-8"))
    expected = {
        "revision": TARGET_SHA,
        "domain": DOMAIN,
        "profile": "CREATOR_STUDIO_COMMERCIAL_V1",
        "runtime_dir": f"{RELEASE}/runtime",
        "state_dir": str(STATE),
        "route_surface": "commercial_handoff:app",
        "creator_studio_enabled": True,
        "creator_auth_required": True,
        "uvicorn_access_log_enabled": False,
        "query_authority_retention": False,
        "secret_values_in_manifest": False,
    }
    if any(m.get(k) != v for k, v in expected.items()):
        raise GateError("deployment manifest mismatch")
    return out, service, manifest


def transient(name: str, body: str) -> None:
    if os.geteuid() != 0:
        raise GateError("transient systemd gates require root")
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+\.service", name):
        raise GateError("unsafe unit name")
    path = Path("/run/systemd/system") / name
    if path.exists() or path.is_symlink():
        raise GateError(f"transient unit exists: {name}")
    path.write_text(body, encoding="utf-8")
    os.chmod(path, 0o600)
    try:
        run("systemctl", "daemon-reload")
        run("systemctl", "start", name)
    finally:
        subprocess.run(["systemctl", "reset-failed", name], capture_output=True)
        path.unlink(missing_ok=True)
        subprocess.run(["systemctl", "daemon-reload"], capture_output=True)


def candidate_preflight(service: Path) -> None:
    keep, pre = [], None
    inside = False
    prefixes = (
        "User=",
        "Group=",
        "UMask=",
        "WorkingDirectory=",
        "EnvironmentFile=",
        "Environment=",
        "NoNewPrivileges=",
        "PrivateTmp=",
        "ProtectSystem=",
        "ProtectHome=",
        "ReadWritePaths=",
    )
    for line in service.read_text(encoding="utf-8").splitlines():
        if line == "[Service]":
            inside = True
            continue
        if inside and line.startswith("["):
            inside = False
        if not inside:
            continue
        if line.startswith("ExecStartPre="):
            pre = "ExecStart=" + line.split("=", 1)[1]
        elif line.startswith(prefixes):
            keep.append(line)
    if not pre:
        raise GateError("rendered service has no preflight")
    body = "\n".join(["[Service]", "Type=oneshot", *keep, "Environment=PYTHONDONTWRITEBYTECODE=1", pre, ""])
    transient(f"webai-preflight-{TARGET_SHA[:12]}.service", body)


def systemd_composition() -> None:
    fragment = run("systemctl", "show", "webai-bridge.service", "--property=FragmentPath", "--value")
    if Path(fragment).resolve(strict=False) != SERVICE.resolve(strict=False):
        raise GateError(f"unexpected FragmentPath: {fragment}")
    dropins = run("systemctl", "show", "webai-bridge.service", "--property=DropInPaths", "--value")
    if dropins:
        raise GateError(f"systemd drop-ins forbidden: {dropins}")


def process_revision(pid: int) -> str:
    env = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    prefix = b"DEPLOYED_REVISION="
    for item in env:
        if item.startswith(prefix):
            revision = item[len(prefix):].decode(errors="replace").strip()
            if revision:
                return revision
    raise GateError(f"process {pid} has no DEPLOYED_REVISION identity")


def current_service_snapshot() -> dict:
    run("systemctl", "is-active", "--quiet", "webai-bridge.service")
    pid_s = run("systemctl", "show", "webai-bridge.service", "--property=MainPID", "--value")
    if not pid_s.isdigit() or int(pid_s) <= 0:
        raise GateError("current production service has no live MainPID")
    pid = int(pid_s)
    cwd = Path(os.readlink(f"/proc/{pid}/cwd")).resolve()
    return {
        "active": True,
        "pid": pid,
        "cwd": str(cwd),
        "revision": process_revision(pid),
        "service_sha256": sha256(SERVICE),
    }


def running_identity() -> dict:
    run("systemctl", "is-active", "--quiet", "webai-bridge.service")
    pid_s = run("systemctl", "show", "webai-bridge.service", "--property=MainPID", "--value")
    if not pid_s.isdigit() or int(pid_s) <= 0:
        raise GateError("missing MainPID")
    pid = int(pid_s)
    cwd = Path(os.readlink(f"/proc/{pid}/cwd")).resolve()
    if cwd != (RELEASE / "runtime").resolve():
        raise GateError(f"running cwd mismatch: {cwd}")
    revision = process_revision(pid)
    if revision.lower() != TARGET_SHA:
        raise GateError(f"running revision mismatch: {revision}")
    cmd = [x.decode(errors="replace") for x in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0") if x]
    if "commercial_handoff:app" not in cmd or "--no-access-log" not in cmd:
        raise GateError("running command surface mismatch")
    return {"pid": pid, "cwd": str(cwd), "revision": TARGET_SHA, "no_access_log": True}


def https_health() -> dict:
    with urllib.request.urlopen(f"https://{DOMAIN}/health", timeout=15) as r:
        if r.status != 200:
            raise GateError(f"HTTPS health={r.status}")
        r.read(4096)
    return {"url": f"https://{DOMAIN}/health", "status": 200}


def stripe_acceptance() -> None:
    body = "\n".join([
        "[Service]",
        "Type=oneshot",
        "User=webai",
        "Group=webai",
        "UMask=0077",
        f"WorkingDirectory={RELEASE}/runtime",
        f"EnvironmentFile=-{ENV_FILE}",
        "Environment=PYTHONDONTWRITEBYTECODE=1",
        f"ExecStart={RELEASE}/runtime/.venv/bin/python {RELEASE}/runtime/stripe_external_acceptance.py --domain {DOMAIN} --config-dir {STATE}/apps",
        "NoNewPrivileges=true",
        "PrivateTmp=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
        "",
    ])
    transient(f"webai-stripe-{TARGET_SHA[:12]}.service", body)


def prepare() -> dict:
    verify_control()
    fetch_exact()
    ensure_release()
    freeze = ensure_venv()
    verify_source()
    out, service, manifest = render()
    verify_source()
    candidate_preflight(service)
    return {
        "target_sha": TARGET_SHA,
        "tree": TARGET_TREE,
        "domain": DOMAIN,
        "controller_revision": git(CONTROL, "rev-parse", "HEAD"),
        "release": str(RELEASE),
        "render": str(out),
        "service_sha256": sha256(service),
        "manifest_sha256": sha256(manifest),
        "constraints_sha256": CONSTRAINTS_SHA256,
        "dependency_freeze": list(freeze),
        "source_identity": "PASS",
        "candidate_preflight": "PASS",
        "production_mutation": False,
    }


def evidence(payload: dict) -> Path:
    d = STATE / "deploy-evidence"
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    unique = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{time.time_ns()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    p = d / f"{unique}-{TARGET_SHA[:12]}.json"
    t = d / f".{p.name}.tmp"
    with t.open("x", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.chmod(t, 0o600)
    os.replace(t, p)
    os.chmod(p, 0o400)
    return p


def atomic_install(source: Path, destination: Path, mode: int) -> None:
    tmp = destination.parent / f".{destination.name}.new-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    if tmp.exists() or tmp.is_symlink():
        raise GateError(f"atomic install temporary path exists: {tmp}")
    try:
        shutil.copyfile(source, tmp)
        os.chmod(tmp, mode)
        with tmp.open("rb") as f:
            os.fsync(f.fileno())
        os.replace(tmp, destination)
        dfd = os.open(destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        tmp.unlink(missing_ok=True)


def restore_previous_service(
    backup: Path,
    *,
    expected_hash: str,
    expected_mode: int,
    previous: dict,
) -> dict:
    atomic_install(backup, SERVICE, expected_mode)
    run("systemctl", "daemon-reload")
    systemd_composition()
    restored_hash = sha256(SERVICE)
    if restored_hash != expected_hash:
        raise GateError("rollback service hash mismatch after restore")
    run("systemctl", "restart", "webai-bridge.service")
    run("systemctl", "is-active", "--quiet", "webai-bridge.service")
    pid_s = run("systemctl", "show", "webai-bridge.service", "--property=MainPID", "--value")
    if not pid_s.isdigit() or int(pid_s) <= 0:
        raise GateError("rollback restart produced no live MainPID")
    pid = int(pid_s)
    cwd = Path(os.readlink(f"/proc/{pid}/cwd")).resolve()
    revision = process_revision(pid)
    if str(cwd) != previous.get("cwd"):
        raise GateError(f"rollback cwd mismatch: {cwd}")
    if revision != previous.get("revision"):
        raise GateError(f"rollback revision mismatch: {revision}")
    return {
        "verified": True,
        "service_sha256": restored_hash,
        "pid": pid,
        "cwd": str(cwd),
        "revision": revision,
    }


def apply(approval: str) -> Path:
    if approval.lower() != TARGET_SHA:
        raise GateError("approval must exactly equal pinned target SHA")
    if os.geteuid() != 0:
        raise GateError("apply requires root")

    prepared = prepare()
    systemd_composition()
    if not SERVICE.is_file() or SERVICE.is_symlink():
        raise GateError("production service file is unsafe")
    previous = current_service_snapshot()

    rendered = Path(prepared["render"]) / "webai-bridge.service"
    backups = STATE / "deploy-backups"
    backups.mkdir(parents=True, exist_ok=True)
    os.chmod(backups, 0o700)
    backup = backups / f"webai-bridge.service.before-{TARGET_SHA[:12]}-{time.time_ns()}"
    old_mode = stat.S_IMODE(SERVICE.stat().st_mode)
    shutil.copy2(SERVICE, backup, follow_symlinks=False)
    os.chmod(backup, 0o600)
    old_hash, new_hash = sha256(SERVICE), sha256(rendered)
    if old_hash != previous["service_sha256"]:
        raise GateError("production service changed during pre-switch snapshot")

    switched = False
    try:
        verify_source()
        atomic_install(rendered, SERVICE, 0o644)
        switched = True
        run("systemctl", "daemon-reload")
        systemd_composition()
        run("systemctl", "restart", "webai-bridge.service")
        running = running_identity()
        health = https_health()
        stripe_acceptance()
        verify_source()
    except Exception as exc:
        rollback: dict = {"attempted": switched, "verified": False}
        rollback_error = None
        if switched:
            try:
                rollback = {
                    "attempted": True,
                    **restore_previous_service(
                        backup,
                        expected_hash=old_hash,
                        expected_mode=old_mode,
                        previous=previous,
                    ),
                }
            except Exception as rb_exc:
                rollback_error = str(rb_exc)
                rollback = {"attempted": True, "verified": False, "error": rollback_error}
        status = "ROLLBACK_VERIFIED_AFTER_FAILURE" if rollback.get("verified") else (
            "ROLLBACK_FAILED" if switched else "PRE_SWITCH_FAILURE"
        )
        p = evidence({
            **prepared,
            "status": status,
            "error": str(exc),
            "old_service_sha256": old_hash,
            "candidate_service_sha256": new_hash,
            "previous_service": previous,
            "rollback": rollback,
            "production_mutation": switched,
            "live_payment_performed": False,
            "secrets_recorded": False,
        })
        if rollback_error:
            raise GateError(
                f"deploy failed and rollback verification failed; evidence={p}; "
                f"deploy_cause={exc}; rollback_cause={rollback_error}"
            ) from exc
        raise GateError(f"deploy failed; evidence={p}; cause={exc}") from exc

    return evidence({
        **prepared,
        "status": "DEPLOYED_AND_EXTERNAL_ACCEPTANCE_PASS",
        "production_mutation": True,
        "previous_service": previous,
        "running_identity": running,
        "https_health": health,
        "stripe_external_acceptance": "PASS",
        "old_service_sha256": old_hash,
        "new_service_sha256": new_hash,
        "backup_service": str(backup),
        "live_payment_performed": False,
        "secrets_recorded": False,
    })


def main() -> int:
    ap = argparse.ArgumentParser(description="Pinned WebAI Bridge exact-head reality deploy capsule")
    ap.add_argument("action", choices=["prepare", "apply"])
    ap.add_argument("--approve", default="")
    args = ap.parse_args()
    try:
        if args.action == "prepare":
            prepared = prepare()
            prepared_evidence = evidence({
                **prepared,
                "status": "PREPARED_CANDIDATE_PASS",
                "live_payment_performed": False,
                "secrets_recorded": False,
            })
            result = {**prepared, "evidence": str(prepared_evidence)}
        else:
            result = {"evidence": str(apply(args.approve))}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except GateError as exc:
        print(f"exact-head deploy: FAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
