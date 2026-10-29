import json
import os
import subprocess

import pytest

from all_tomorrow.adapters import push_guard
from all_tomorrow.adapters.workers import _worker_environment

pytestmark = pytest.mark.skipif(subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
                                reason="git not installed")


def git(cwd, *args, env=None):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, env=env,
                          capture_output=True, text=True)


def repo(tmp_path, name):
    remote = tmp_path / f"{name}.git"
    git(tmp_path, "init", "--bare", "-b", "main", str(remote))
    work = tmp_path / name
    git(tmp_path, "init", "-b", "main", str(work))
    git(work, "remote", "add", "origin", str(remote))
    (work / "a.txt").write_text("1")
    git(work, "add", ".")
    git(work, "commit", "-m", "one")
    return work


@pytest.fixture
def setup(tmp_path):
    solo, team, unmarked = repo(tmp_path, "solo"), repo(tmp_path, "team"), repo(tmp_path, "unmarked")
    registry = tmp_path / "projects.json"
    registry.write_text(json.dumps({"projects": {
        "solo": {"path": str(solo), "team_repo": False},
        "team": {"path": str(team).replace("\\", "/"), "team_repo": True},
        "unmarked": {"path": str(unmarked)}}}), encoding="utf-8")
    env = {**os.environ, **push_guard.git_environment(dict(os.environ), tmp_path / "hooks", registry)}
    return solo, team, unmarked, env


def test_solo_pushes_team_and_unmarked_are_blocked(setup):
    solo, team, unmarked, env = setup
    assert git(solo, "push", "origin", "main", env=env).returncode == 0
    for blocked in (team, unmarked):
        result = git(blocked, "push", "origin", "main", env=env)
        assert result.returncode != 0 and "push guard" in result.stderr
    # the same push without the guard goes through: the hook, not the remote, refused it
    assert git(team, "push", "origin", "main").returncode == 0


def test_force_push_and_remote_delete_are_blocked_even_when_solo(setup):
    solo, _, _, env = setup
    assert git(solo, "push", "origin", "main", env=env).returncode == 0
    (solo / "a.txt").write_text("2")
    git(solo, "commit", "-am", "two")
    assert git(solo, "push", "origin", "main", env=env).returncode == 0
    git(solo, "reset", "--soft", "HEAD~1")
    git(solo, "commit", "-m", "rewritten")
    result = git(solo, "push", "--force", "origin", "main", env=env)
    assert result.returncode != 0 and "force push" in result.stderr
    result = git(solo, "push", "origin", ":main", env=env)
    assert result.returncode != 0 and "deleting" in result.stderr


def test_repository_hooks_still_run(setup):
    solo, _, _, env = setup
    hook = solo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho own hook >&2\nexit 1\n", newline="\n")
    hook.chmod(0o755)
    (solo / "a.txt").write_text("3")
    result = git(solo, "commit", "-am", "three", env=env)
    assert result.returncode != 0 and "own hook" in result.stderr


def test_worker_environment_carries_guard_and_keeps_existing_git_config(monkeypatch, tmp_path):
    monkeypatch.setattr(push_guard, "HOOKS_DIR", tmp_path / "hooks")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.name")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "x")
    env = _worker_environment({})
    assert env["GIT_CONFIG_COUNT"] == "2" and env["GIT_CONFIG_KEY_0"] == "user.name"
    assert env["GIT_CONFIG_KEY_1"] == "core.hooksPath" and (tmp_path / "hooks" / "pre-push").exists()
