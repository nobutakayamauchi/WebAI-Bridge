from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "deploy/exact_head_deploy_envsafe_apply_ready.py"
spec = importlib.util.spec_from_file_location("exact_head_deploy_envsafe_apply_bootstrap", PATH)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def test_normal_clone_config_has_no_external_authority_escape():
    text = """[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n\tbare = false\n\tlogallrefupdates = true\n[remote \"origin\"]\n\turl = https://github.com/nobutakayamauchi/WebAI-Bridge.git\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n[branch \"main\"]\n\tremote = origin\n\tmerge = refs/heads/main\n"""
    m._reject_git_config_authority_escapes(text)


@pytest.mark.parametrize(
    "text",
    [
        "[include]\npath = /tmp/attacker.cfg\n",
        "[includeIf \"gitdir:/opt/**\"]\npath = /tmp/attacker.cfg\n",
        "[url \"https://evil.example/\"]\ninsteadOf = https://github.com/\n",
        "[http]\nproxy = http://127.0.0.1:9999\n",
        "[http \"https://github.com\"]\nsslCAInfo = /tmp/ca.pem\n",
        "[core]\nhooksPath = /tmp/hooks\n",
        "[core]\nworktree = /tmp/other-tree\n",
        "[remote \"origin\"]\nuploadpack = /tmp/fake-upload-pack\n",
        "[remote \"origin\"]\nproxy = http://127.0.0.1:9999\n",
    ],
)
def test_external_git_authority_config_is_rejected(text: str):
    with pytest.raises(RuntimeError, match="forbidden"):
        m._reject_git_config_authority_escapes(text)


def test_bootstrap_trust_authority_id_is_explicit():
    assert m.BOOTSTRAP_CONTROLLER_TRUST_AUTHORITY == "ROOT_OWNED_GIT_NO_EXTERNAL_AUTHORITY_V2"
