import os
import subprocess
import sys
from pathlib import Path

import pytest

from model_meta.core import blender_connection
from model_meta.core.app_connection import PathState
from model_meta.core.blender_connection import BlenderConnection, ProbeOutcome

posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="fake exe is a POSIX shell script"
)
not_root = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root ignores the exec bit, so a non-executable file still runs",
)


def _make_exe(path, body):
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(0o755)
    return path


def _candidate_paths() -> list[Path]:
    return [c.path for c in BlenderConnection.candidates()]


# --- candidates() ----------------------------------------------------------


def test_candidates_appends_which_result(monkeypatch, tmp_path):
    fake = tmp_path / "blender"
    fake.write_text("")
    monkeypatch.setattr(blender_connection.sys, "platform", "linux")
    monkeypatch.setattr(blender_connection.shutil, "which", lambda name: str(fake))
    assert fake in _candidate_paths()


def test_candidates_empty_when_nothing_found(monkeypatch):
    monkeypatch.setattr(blender_connection.sys, "platform", "linux")
    monkeypatch.setattr(blender_connection.shutil, "which", lambda name: None)
    # Standard Linux prefixes are absent in the test environment.
    assert BlenderConnection.candidates() == []


def test_candidates_dedupes_which_against_base(monkeypatch, tmp_path):
    fake = tmp_path / "blender.exe"
    fake.write_text("")
    monkeypatch.setattr(blender_connection.sys, "platform", "win32")
    monkeypatch.setattr(blender_connection.Path, "glob", lambda self, pattern: [fake])
    monkeypatch.setattr(blender_connection.shutil, "which", lambda name: str(fake))
    assert _candidate_paths() == [fake]


def test_candidates_macos_resolves_app_binary(monkeypatch):
    monkeypatch.setattr(blender_connection.sys, "platform", "darwin")
    monkeypatch.setattr(blender_connection.Path, "exists", lambda self: True)
    monkeypatch.setattr(blender_connection.shutil, "which", lambda name: None)
    assert _candidate_paths() == [
        Path("/Applications/Blender.app/Contents/MacOS/Blender")
    ]


# --- state() ---------------------------------------------------------------


def test_state_missing_for_absent_path(tmp_path):
    assert BlenderConnection(tmp_path / "nope").state() is PathState.MISSING


@posix_only
def test_state_ok_for_executable_file(tmp_path):
    exe = _make_exe(tmp_path / "blender", 'echo "Blender 4.5.0"')
    assert BlenderConnection(exe).state() is PathState.OK


@posix_only
@not_root
def test_state_invalid_for_plain_file(tmp_path):
    plain = tmp_path / "notblender"
    plain.write_text("just text")  # no exec bit
    assert BlenderConnection(plain).state() is PathState.INVALID


def test_state_windows_treats_any_file_as_ok(monkeypatch, tmp_path):
    plain = tmp_path / "blender.exe"
    plain.write_text("just text")
    monkeypatch.setattr(blender_connection.sys, "platform", "win32")
    assert BlenderConnection(plain).state() is PathState.OK


def test_state_macos_accepts_app_bundle(monkeypatch, tmp_path):
    bundle = tmp_path / "Blender.app"
    bundle.mkdir()
    monkeypatch.setattr(blender_connection.sys, "platform", "darwin")
    assert BlenderConnection(bundle).state() is PathState.OK


def test_state_invalid_for_plain_directory(tmp_path):
    assert BlenderConnection(tmp_path).state() is PathState.INVALID


# --- probe() outcomes ------------------------------------------------------


@posix_only
def test_probe_ok_parses_version(tmp_path):
    exe = _make_exe(tmp_path / "blender", 'echo "Blender 4.5.0"')
    result = BlenderConnection(exe).probe()
    assert result.outcome is ProbeOutcome.OK
    assert result.ok
    assert result.version == "4.5.0"


@posix_only
def test_probe_ok_ignores_leading_banner(tmp_path):
    exe = _make_exe(tmp_path / "blender", 'echo "startup noise"; echo "Blender 4.5.0"')
    result = BlenderConnection(exe).probe()
    assert result.outcome is ProbeOutcome.OK
    assert result.version == "4.5.0"


def test_probe_not_found_when_path_missing(tmp_path):
    result = BlenderConnection(tmp_path / "does-not-exist").probe()
    assert result.outcome is ProbeOutcome.NOT_FOUND
    assert not result.ok


@posix_only
@not_root
def test_probe_not_exe_for_non_executable_file(tmp_path):
    plain = tmp_path / "notblender"
    plain.write_text("just text")  # no exec bit
    result = BlenderConnection(plain).probe()
    assert result.outcome is ProbeOutcome.NOT_EXE


@posix_only
def test_probe_unparseable_when_output_isnt_blender(tmp_path):
    exe = _make_exe(tmp_path / "notblender", 'echo "GNU bash, version 5"')
    result = BlenderConnection(exe).probe()
    assert result.outcome is ProbeOutcome.UNPARSEABLE


@posix_only
def test_probe_unparseable_on_nonzero_exit(tmp_path):
    exe = _make_exe(tmp_path / "blender", 'echo "Blender 4.5.0"; exit 1')
    result = BlenderConnection(exe).probe()
    assert result.outcome is ProbeOutcome.UNPARSEABLE


@posix_only
def test_probe_timeout_when_it_hangs(tmp_path):
    exe = _make_exe(tmp_path / "blender", "sleep 5")
    result = BlenderConnection(exe).probe(timeout=0.3)
    assert result.outcome is ProbeOutcome.TIMEOUT


# --- is_running() ----------------------------------------------------------


def _fake_run(monkeypatch, platform, stdout):
    monkeypatch.setattr(blender_connection.sys, "platform", platform)
    monkeypatch.setattr(
        blender_connection.subprocess,
        "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0, stdout, ""),
    )


def test_is_running_finds_macos_blender(monkeypatch):
    _fake_run(
        monkeypatch,
        "darwin",
        "/usr/bin/zsh\n/Applications/Blender.app/Contents/MacOS/Blender\n",
    )
    assert BlenderConnection.is_running()


def test_is_running_ignores_thumbnailer(monkeypatch):
    thumbnailer = "/Applications/Blender.app/Contents/MacOS/blender-thumbnailer"
    _fake_run(monkeypatch, "darwin", f"/usr/bin/zsh\n{thumbnailer}\n")
    assert not BlenderConnection.is_running()


def test_is_running_finds_linux_blender(monkeypatch):
    _fake_run(monkeypatch, "linux", "bash\nblender\n")
    assert BlenderConnection.is_running()


def test_is_running_finds_windows_blender(monkeypatch):
    _fake_run(
        monkeypatch, "win32", '"blender.exe","1234","Console","1","512,000 K"\r\n'
    )
    assert BlenderConnection.is_running()


def test_is_running_false_on_windows_no_match(monkeypatch):
    _fake_run(
        monkeypatch,
        "win32",
        "INFO: No tasks are running which match the specified criteria.\r\n",
    )
    assert not BlenderConnection.is_running()


def test_is_running_false_when_lookup_fails(monkeypatch):
    def run(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(blender_connection.subprocess, "run", run)
    assert not BlenderConnection.is_running()
