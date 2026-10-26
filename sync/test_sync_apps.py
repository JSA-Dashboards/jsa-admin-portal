"""A source the sync can't clone is skipped (mirror untouched, loudly reported); real failures still fail.

    python -m pytest sync/test_sync_apps.py
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sync_apps as sa  # noqa: E402

DENIED = "JSA-Dashboards/bad: git clone -q --depth: remote: Write access to repository not granted."


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A tiny portal with three sources, one of which (`bad`) cannot be cloned."""
    sources = {}
    for name in ("good1", "good2", "private_one"):
        src = tmp_path / "src" / name
        src.mkdir(parents=True)
        (src / "app.py").write_text(f"import streamlit as st\nst.write('{name}')\n", encoding="utf-8")
        sources[name] = src
    monkeypatch.setattr(sa, "CONFIG", {
        "defaults": {"branch": "main", "entry": "app.py", "exclude": [".git"]},
        "apps": {"good1": {"repo": "o/good1"}, "bad": {"repo": "o/bad"}, "good2": {"repo": "o/good2"}},
        "root_files": []})
    (tmp_path / "apps").mkdir()
    monkeypatch.setattr(sa, "APPS", tmp_path / "apps")

    def fake_fetch(spec):
        name = spec["repo"].split("/")[1]
        if name == "bad":
            raise sa.FetchError(DENIED)
        return sources[name], "abcdef0123456789"

    monkeypatch.setattr(sa, "fetch", fake_fetch)
    for var in ("GITHUB_ACTIONS", "GITHUB_STEP_SUMMARY", "CI", "SYNC_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    sa.SKIPPED.clear()
    yield tmp_path
    sa.SKIPPED.clear()


def test_an_unclonable_source_is_skipped_and_the_others_still_sync(world, capsys):
    old = world / "apps" / "bad"
    old.mkdir()
    (old / "app.py").write_text("OLD\n")
    assert sa.cmd_apply([]) == 0                                   # the run succeeds
    assert (world / "apps" / "good1" / "app.py").exists() and (world / "apps" / "good2" / ".sync.json").exists()
    assert (old / "app.py").read_text() == "OLD\n"                 # the skipped app's mirror is untouched
    assert [what for what, _ in sa.SKIPPED] == ["bad"]
    out = capsys.readouterr().out
    assert "SKIPPED bad:" in out and "synced good1" in out and "synced good2" in out and "FAILED" not in out


def test_a_run_where_every_source_is_skipped_fails(world, monkeypatch):
    monkeypatch.setattr(sa, "CONFIG", {**sa.CONFIG, "apps": {"bad": {"repo": "o/bad"}}})
    assert sa.cmd_apply([]) == 1                                   # nothing synced is not a quiet success


def test_naming_an_unclonable_app_fails_but_naming_a_good_one_does_not(world):
    assert sa.cmd_apply(["bad"]) == 1
    sa.SKIPPED.clear()
    assert sa.cmd_apply(["good1"]) == 0


def test_a_problem_that_is_not_a_clone_failure_still_fails(world):
    (world / "src" / "good2" / "app.py").unlink()                  # entry file missing: not a fetch problem
    assert sa.cmd_apply([]) == 1
    assert (world / "apps" / "good1" / "app.py").exists()          # the rest still synced


def test_a_private_source_without_a_token_in_ci_is_a_skip(world, monkeypatch):
    monkeypatch.setenv("CI", "true")
    monkeypatch.setattr(sa, "CONFIG", {**sa.CONFIG, "apps": {
        "good1": {"repo": "o/good1"}, "private_one": {"repo": "o/private_one", "private": True}}})
    assert sa.cmd_apply([]) == 0
    assert [what for what, _ in sa.SKIPPED] == ["private_one"] and "no SYNC_TOKEN" in sa.SKIPPED[0][1]


def test_plan_and_diff_survive_a_skipped_source(world, capsys):
    sa.cmd_plan([])
    sa.cmd_diff([])
    out = capsys.readouterr().out
    assert "SKIPPED bad" in out and "== good1" in out and "== good2" in out


def test_github_actions_gets_an_annotation_and_a_run_summary(world, monkeypatch, capsys):
    summary = world / "summary.md"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert sa.cmd_apply([]) == 0
    out = capsys.readouterr().out
    assert "::warning title=Sync skipped bad::" in out
    text = summary.read_text(encoding="utf-8")
    assert "Skipped by the sync" in text and "**bad**" in text and "Write access to repository not granted" in text
    # a clean run writes nothing
    sa.SKIPPED.clear()
    summary.unlink()
    monkeypatch.setattr(sa, "CONFIG", {**sa.CONFIG, "apps": {"good1": {"repo": "o/good1"}}})
    assert sa.cmd_apply([]) == 0 and not summary.exists()


def test_fetch_turns_git_failures_into_fetcherror(tmp_path, monkeypatch):
    monkeypatch.setattr(sa, "CACHE", tmp_path / "cache")

    def boom(*args, cwd=None):
        raise RuntimeError("git clone -q --depth: remote: Write access to repository not granted.")

    monkeypatch.setattr(sa, "_git", boom)
    with pytest.raises(sa.FetchError) as err:
        sa.fetch({"repo": "o/private", "branch": "main"})
    assert "o/private" in str(err.value) and "Write access" in str(err.value) and isinstance(err.value, RuntimeError)


def test_the_token_is_used_for_the_clone_but_never_appears_in_a_message(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNC_TOKEN", "SECRET-TOKEN-XYZ")
    monkeypatch.setattr(sa, "CACHE", tmp_path / "cache")
    commands = []

    class Result:
        returncode = 128
        stdout = ""
        stderr = "fatal: unable to access 'https://github.com/o/private.git/': The requested URL returned error: 403"

    monkeypatch.setattr(sa.subprocess, "run", lambda cmd, **kw: commands.append(cmd) or Result())
    with pytest.raises(sa.FetchError) as err:
        sa.fetch({"repo": "o/private", "branch": "main"})
    assert any("SECRET-TOKEN-XYZ" in part for part in commands[0])      # it was used to authenticate the clone
    assert "SECRET-TOKEN-XYZ" not in str(err.value)                    # and never reaches a log line
