import os
import time
from pathlib import Path

import pytest

from georing.step import StepFailed, run_step


def running(argv: list[str]) -> bool:
    """Return whether a process with exactly this command line is alive."""
    wanted = b"\0".join(a.encode() for a in argv) + b"\0"
    for proc in Path("/proc").iterdir():
        try:
            if proc.name.isdigit() and (proc / "cmdline").read_bytes() == wanted:
                return True
        except OSError:
            pass  # it ended while we looked
    return False


def test_a_step_runs_in_a_process_of_its_own_and_hands_back_its_result():
    assert run_step("dump", "json:dumps", {}, 1, obj=[1, 2]) == "[1, 2]"
    assert run_step("pid", "os:getpid", {}, 1) != os.getpid()


def test_a_step_that_exits_with_an_error_has_failed():
    with pytest.raises(StepFailed, match="exited with"):
        run_step("no such key", "os:getenv", {}, 1)  # getenv() without a key raises


def test_a_step_that_does_not_finish_in_time_is_stopped_with_what_it_started():
    started = time.monotonic()
    with pytest.raises(StepFailed, match="stopped after 1 s"):
        run_step("stall", "subprocess:run", {}, 1, timeout_s=1, args=["sleep", "31.4159"])
    assert time.monotonic() - started < 10
    assert not running(["sleep", "31.4159"])


def test_a_step_inherits_no_credential_and_gets_the_ones_it_is_handed(monkeypatch):
    monkeypatch.setenv("EUMETSAT_CONSUMER_SECRET", "inherited")
    monkeypatch.setenv("GEORING_S3_SECRET_ACCESS_KEY", "inherited")
    for name in ("EUMETSAT_CONSUMER_SECRET", "GEORING_S3_SECRET_ACCESS_KEY"):
        assert run_step("read", "os:getenv", {}, 1, key=name, default="absent") == "absent"
    handed = run_step("read", "os:getenv", {"EUMETSAT_CONSUMER_SECRET": "handed"}, 1,
                      key="EUMETSAT_CONSUMER_SECRET")
    assert handed == "handed"
