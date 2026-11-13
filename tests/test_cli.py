import argparse
import os
from datetime import UTC, datetime

import pytest

from georing import cli, flow, static
from georing.settings import settings


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    """Keep the settings, and what a command puts in the environment, to one test."""
    for name in ("GEORING_OUTPUT_URL", "GEORING_WORK_DIR", "PREFECT_HOME", "PREFECT_API_URL"):
        monkeypatch.delenv(name, raising=False)
    settings.cache_clear()
    yield
    for name in ("GEORING_OUTPUT_URL", "GEORING_WORK_DIR", "PREFECT_HOME"):
        os.environ.pop(name, None)
    settings.cache_clear()


def test_a_slot_is_a_full_clock_hour_in_utc():
    assert cli.parse_slot("2026-11-10T18:00") == datetime(2026, 11, 10, 18, tzinfo=UTC)
    assert cli.parse_slot("2026-11-10T19:00+01:00") == datetime(2026, 11, 10, 18, tzinfo=UTC)
    for not_an_hour in ("2026-11-10T18:10", "2026-11-10T18:00:30+00:00"):
        with pytest.raises(argparse.ArgumentTypeError):
            cli.parse_slot(not_an_hour)


def test_georing_slot_runs_the_flow_with_its_options_as_settings(tmp_path, monkeypatch, capsys):
    seen = {}

    def build_slot(slot, force):
        cfg = settings()
        seen.update(slot=slot, force=force, out=cfg.output_url, work=cfg.work_dir, home=os.environ["PREFECT_HOME"])
        return {"built": True, "disks": ["goes-east", "himawari"]}

    monkeypatch.setattr(flow, "build_slot", build_slot)
    monkeypatch.setattr(static, "fetch_static", lambda static_dir: seen.update(static=static_dir))

    assert cli.slot_main(["2026-11-10T19:00+01:00", "--out", str(tmp_path / "o"), "--work", str(tmp_path / "w"),
                          "--force"]) == 0

    assert seen["slot"] == datetime(2026, 11, 10, 18, tzinfo=UTC) and seen["force"] is True
    assert (seen["out"], str(seen["work"])) == (str(tmp_path / "o"), str(tmp_path / "w"))
    # The temporary server's database and the static files stay under the work directory.
    assert seen["home"] == str(tmp_path / "w" / "prefect")
    assert seen["static"] == str(tmp_path / "w" / "static")
    assert "built from goes-east, himawari" in capsys.readouterr().out


def test_georing_backfill_refuses_to_run_without_a_server(capsys):
    with pytest.raises(SystemExit):
        cli.backfill_main(["2026-11-10T04:00"])
    assert "PREFECT_API_URL is not set" in capsys.readouterr().err


def test_georing_backfill_queues_the_range_it_is_given(monkeypatch, capsys):
    monkeypatch.setenv("PREFECT_API_URL", "http://server:4200/api")
    asked = {}

    def backfill(start, end, force):
        asked.update(start=start, end=end, force=force)
        return ["20261110T0500Z", "20261110T0400Z"]

    monkeypatch.setattr(flow, "backfill", backfill)
    assert cli.backfill_main(["2026-11-10T04:00", "2026-11-10T05:00"]) == 0
    assert asked == {"start": datetime(2026, 11, 10, 4, tzinfo=UTC), "end": datetime(2026, 11, 10, 5, tzinfo=UTC),
                     "force": False}
    assert "Queued 2 Slots, 20261110T0400Z to 20261110T0500Z." in capsys.readouterr().out
