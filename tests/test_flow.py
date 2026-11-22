import json
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from prefect import get_client
from prefect.logging import disable_run_logger
from prefect.testing.utilities import prefect_test_harness

from georing import download, flow
from georing.lights.cog import NoLogin
from georing.settings import settings
from georing.step import StepFailed

SLOT = datetime(2026, 11, 10, 18, tzinfo=UTC)
ALL = ["goes-east", "goes-west", "himawari", "meteosat-0", "meteosat-iodc"]
DEPLOYMENT = "76ba58a1-aadc-46f3-a9ba-7682e7a94864"


@pytest.fixture(scope="module", autouse=True)
def prefect():
    with prefect_test_harness():
        yield


@pytest.fixture
def steps(tmp_path, monkeypatch):
    """Replace the heavy steps by ones that write empty files, and record what ran."""
    monkeypatch.setenv("GEORING_OUTPUT_URL", str(tmp_path / "out"))
    monkeypatch.setenv("GEORING_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("EARTHDATA_USERNAME", "someone")
    monkeypatch.setenv("EARTHDATA_PASSWORD", "secret")
    settings.cache_clear()
    ran = {"unavailable": set(), "steps": []}

    def run_step(step, target, env, cores, timeout_s, **kwargs):
        ran["steps"].append(step)
        ran.setdefault("timeouts", {})[step] = timeout_s
        if step.startswith("download") and kwargs["position"] in ran["unavailable"]:
            return f"{kwargs['position']}: 0 of 5 files"
        result = None if step.startswith("download") else {}
        if step.startswith("render"):
            Path(kwargs["dest"]).write_bytes(b"lossless")
        if step == "mosaic join":
            Path(kwargs["dest"]).write_bytes(b"joined")
        if step == "mosaic encode":
            Path(kwargs["dest"]).write_bytes(b"mosaic")
        if step == "city lights":
            ran["lights_env"] = env
            Path(kwargs["dest"]).parent.mkdir(parents=True, exist_ok=True)
            Path(kwargs["dest"]).write_bytes(b"lights")
            result = kwargs["dest"]
        if step == "late disks":
            ran["asked"] = kwargs["wanted"]
            result = download.disks_available(kwargs["wanted"])
        return result

    monkeypatch.setattr(flow, "run_step", run_step)
    yield ran
    settings.cache_clear()


def test_a_slot_is_the_full_clock_hour_in_utc():
    assert flow.to_slot(datetime(2026, 11, 10, 18, 42, 7, tzinfo=UTC)) == SLOT
    assert flow.to_slot(datetime(2026, 11, 10, 18, 42)) == SLOT
    assert flow.to_slot(datetime.fromisoformat("2026-11-10T19:59:00+01:00")) == SLOT


def test_a_slot_renders_four_disks_and_publishes_a_mosaic_and_the_catalogue(steps, tmp_path):
    result = flow.build_slot(SLOT)

    assert result["built"] and result["disks"] == ALL
    out = tmp_path / "out"
    assert (out / "mosaic/2026/11/10/georing_mosaic_20261110T1800Z.tif").read_bytes() == b"mosaic"
    assert sorted(s for s in steps["steps"] if s.startswith("render")) == [f"render {p}" for p in ALL]
    assert json.loads((out / "latest.json").read_text())["slot"] == "2026-11-10T18:00:00Z"
    assert (out / "catalog.json").exists()
    assert not (tmp_path / "work/scratch/20261110T1800Z").exists()
    # A download that hangs is stopped long before any other step would be.
    assert steps["timeouts"]["download goes-east"] == 300
    assert steps["timeouts"]["mosaic join"] == 1800


def test_the_city_lights_are_built_once_with_the_earthdata_login(steps, tmp_path):
    flow.build_slot(SLOT)
    flow.build_slot(SLOT - timedelta(hours=1))

    assert steps["steps"].count("city lights") == 1
    assert (tmp_path / "work/lights/VJ146A4.A2025.tif").read_bytes() == b"lights"
    assert steps["lights_env"]["EARTHDATA_USERNAME"] == "someone"


def test_without_the_city_lights_or_a_login_no_disk_is_rendered(steps, monkeypatch):
    monkeypatch.delenv("EARTHDATA_USERNAME")
    monkeypatch.setattr(flow, "load_dotenv", lambda path: {})  # nor in a .env

    with pytest.raises(NoLogin):
        flow.build_slot(SLOT)
    assert not [s for s in steps["steps"] if s.startswith("render")]


def test_a_run_that_fails_for_the_city_lights_leaves_no_scratch_behind_its_downloads(steps, monkeypatch, tmp_path):
    monkeypatch.delenv("EARTHDATA_USERNAME")
    monkeypatch.setattr(flow, "load_dotenv", lambda path: {})
    original = flow.run_step

    def run_step(step, *args, **kwargs):
        if step.startswith("download"):
            time.sleep(0.5)  # still downloading when the lights fail
            Path(kwargs["dest"]).mkdir(parents=True)
            (Path(kwargs["dest"]) / "disk.nc").write_bytes(b"disk")
        return original(step, *args, **kwargs)

    monkeypatch.setattr(flow, "run_step", run_step)
    with pytest.raises(NoLogin):
        flow.build_slot(SLOT)
    assert not (tmp_path / "work/scratch/20261110T1800Z").exists()


def test_a_slot_that_is_done_is_not_built_again(steps):
    flow.build_slot(SLOT)
    steps["steps"].clear()
    assert flow.build_slot(SLOT)["built"] is False
    assert steps["steps"] == []


def test_a_missing_disk_is_left_out_and_recorded(steps, tmp_path):
    steps["unavailable"] = {"meteosat-0"}
    result = flow.build_slot(SLOT)

    assert result["disks"] == ["goes-east", "goes-west", "himawari", "meteosat-iodc"]
    item = json.loads((tmp_path / "out/mosaic/2026/11/10/georing_mosaic_20261110T1800Z.json").read_text())
    assert item["properties"]["georing:missing_disks"] == ["meteosat-0"]
    assert "render meteosat-0" not in steps["steps"]


def test_a_disk_that_arrives_late_does_not_hold_up_the_others(steps, monkeypatch):
    original = flow.run_step
    another_rendered = threading.Event()

    def run_step(step, *args, **kwargs):
        if step == "download goes-east":  # the first position: arrives last
            another_rendered.wait(timeout=30)
        report = original(step, *args, **kwargs)
        if step.startswith("render"):
            another_rendered.set()
        return report

    monkeypatch.setattr(flow, "run_step", run_step)
    result = flow.build_slot(SLOT)

    renders = [s for s in steps["steps"] if s.startswith("render")]
    assert renders[-1] == "render goes-east" and len(renders) == len(ALL)
    assert result["disks"] == ALL


def test_a_late_disk_rebuilds_the_slot_from_all_its_disks(steps, tmp_path):
    steps["unavailable"] = {"meteosat-0"}
    flow.build_slot(SLOT)
    steps["unavailable"] = set()
    steps["steps"].clear()

    result = flow.build_slot(SLOT)

    assert result["built"] and result["disks"] == ALL
    assert sorted(steps["steps"]) == sorted(
        [f"{step} {p}" for p in ALL for step in ("download", "render")] + ["mosaic join", "mosaic encode"])


def test_a_rebuild_that_adds_no_disk_leaves_the_mosaic_as_it_is(steps, tmp_path):
    steps["unavailable"] = {"meteosat-0"}
    flow.build_slot(SLOT)
    steps["steps"].clear()

    result = flow.build_slot(SLOT)       # Meteosat is still not there

    assert result["built"] is False and result["disks"] == ["goes-east", "goes-west", "himawari", "meteosat-iodc"]
    # Only the lacking Disk is asked for: nothing else is downloaded or rendered.
    assert steps["steps"] == ["download meteosat-0"]

def test_a_slot_with_no_disk_at_all_fails(steps):
    steps["unavailable"] = set(ALL)
    with pytest.raises(RuntimeError, match="No Disk"):
        flow.build_slot(SLOT)


def test_a_disk_that_cannot_be_rendered_does_not_cost_the_slot(steps, monkeypatch):
    original = flow.run_step

    def run_step(step, *args, **kwargs):
        if step == "render himawari":
            raise StepFailed("render himawari exited with 1")
        return original(step, *args, **kwargs)

    monkeypatch.setattr(flow, "run_step", run_step)
    assert flow.build_slot(SLOT)["disks"] == ["goes-east", "goes-west", "meteosat-0", "meteosat-iodc"]


@pytest.fixture
def queued(monkeypatch):
    """Record the Slot runs a flow asks for instead of creating them."""
    calls = []

    def run_deployment(name, parameters, **options):
        calls.append({"name": name, **parameters, **options})

    monkeypatch.setattr(flow, "run_deployment", run_deployment)
    return calls


def test_a_backfill_skips_a_slot_that_only_lacks_a_disk_nobody_can_ask_for(steps, queued, monkeypatch):
    newest = flow.to_slot(None) - timedelta(hours=1)
    steps["unavailable"] = {"meteosat-0"}
    flow.build_slot(newest)

    monkeypatch.setattr(flow, "_secrets", dict)              # no EUMETSAT key
    assert flow.backfill(newest) == []
    monkeypatch.setattr(flow, "_secrets", lambda: {"EUMETSAT_CONSUMER_KEY": "k", "EUMETSAT_CONSUMER_SECRET": "s"})
    assert flow.backfill(newest) == [flow.stamp(newest)]


def test_backfill_queues_the_slots_that_are_not_done_newest_first(steps, queued):
    newest = flow.to_slot(None) - timedelta(hours=1)
    flow.build_slot(newest - timedelta(hours=1))                 # done
    steps["unavailable"] = {"himawari"}
    flow.build_slot(newest - timedelta(hours=2))                 # built without a Disk

    asked = flow.backfill(newest - timedelta(hours=3))

    slots = [datetime.fromisoformat(c["slot"]) for c in queued]
    assert slots == [newest, newest - timedelta(hours=2), newest - timedelta(hours=3)]
    assert asked == [flow.stamp(s) for s in slots]
    assert {c["name"] for c in queued} == {"georing-slot/hourly"}
    assert [c["flow_run_name"] for c in queued] == [f"georing-slot-{stamp}" for stamp in asked]
    assert {c["work_queue_name"] for c in queued} == {"catch-up"}
    assert len({c["idempotency_key"] for c in queued}) == 3


def run_name(state) -> str:
    return get_client(sync_client=True).read_flow_run(state.state_details.flow_run_id).name


def test_the_flow_and_each_run_are_named_after_the_project_and_the_slot(steps):
    assert flow.build_slot.name == "georing-slot"
    assert run_name(flow.build_slot(SLOT, return_state=True)) == "georing-slot-20261110T1800Z"

def test_a_run_builds_the_hour_it_was_scheduled_in_however_late_it_starts(steps, monkeypatch):
    monkeypatch.setenv("PREFECT__RUNTIME__FLOW_RUN__SCHEDULED_START_TIME", "2026-11-10T18:10:00+00:00")
    assert flow.build_slot()["slot"] == "2026-11-10T18:00:00+00:00"


def test_a_slot_that_has_not_begun_is_refused(steps, queued):
    ahead = flow.to_slot(None) + timedelta(hours=1)
    with pytest.raises(ValueError, match="has not begun"):
        flow.build_slot(ahead)
    with pytest.raises(ValueError, match="has not begun"):
        flow.backfill(flow.to_slot(None), end=ahead)
    assert steps["steps"] == [] and queued == []


def test_a_failed_run_leaves_no_scratch(steps, monkeypatch, tmp_path):
    original = flow.run_step

    def run_step(step, *args, **kwargs):
        if step == "mosaic join":
            raise StepFailed("mosaic join exited with -9")
        return original(step, *args, **kwargs)

    monkeypatch.setattr(flow, "run_step", run_step)
    with pytest.raises(StepFailed):
        flow.build_slot(SLOT)
    assert not (tmp_path / "work/scratch/20261110T1800Z").exists()


def test_scratch_left_by_a_run_that_died_is_removed(steps, tmp_path):
    died = tmp_path / "work/scratch/20261109T0300Z"
    fresh = tmp_path / "work/scratch/20261110T1700Z"
    for path in (died, fresh):
        path.mkdir(parents=True)
    long_ago = (datetime.now(UTC) - timedelta(hours=5)).timestamp()
    os.utime(died, (long_ago, long_ago))

    flow.build_slot(SLOT)

    assert not died.exists()
    assert fresh.exists()  # another run may be using it


def test_a_forced_rebuild_replaces_a_slot_that_is_done(steps):
    flow.build_slot(SLOT)
    steps["steps"].clear()

    assert flow.build_slot(SLOT, force=True)["built"]
    assert steps["steps"].count("mosaic join") == 1


def test_a_forced_rebuild_that_would_lose_a_disk_leaves_the_mosaic_as_it_is(steps, tmp_path):
    flow.build_slot(SLOT)
    steps["unavailable"] = {"meteosat-0"}
    steps["steps"].clear()

    result = flow.build_slot(SLOT, force=True)

    assert result["built"] is False and result["disks"] == ALL
    assert "mosaic join" not in steps["steps"]
    item = json.loads((tmp_path / "out/mosaic/2026/11/10/georing_mosaic_20261110T1800Z.json").read_text())
    assert item["properties"]["georing:missing_disks"] == []


def test_the_eumetsat_key_is_all_that_is_taken_from_the_env_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("EUMETSAT_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("EUMETSAT_CONSUMER_SECRET", raising=False)
    (tmp_path / ".env").write_text(
        "EUMETSAT_CONSUMER_KEY=key\nEUMETSAT_CONSUMER_SECRET=secret\nGEORING_S3_SECRET_ACCESS_KEY=bucket\n")
    assert flow._secrets() == {"EUMETSAT_CONSUMER_KEY": "key", "EUMETSAT_CONSUMER_SECRET": "secret"}
    (tmp_path / ".env").write_text("EUMETSAT_CONSUMER_KEY=key\nEUMETSAT_CONSUMER_SECRET=\n")
    assert flow._secrets() == {}


def test_a_download_asks_again_each_minute_until_the_deadline(steps, monkeypatch):
    attempts, naps = [], []

    def run_step(step, *args, **kwargs):
        attempts.append(step)
        if len(attempts) == 1:
            raise StepFailed("download himawari exited with 1")
        return "himawari: 58 of 60 files" if len(attempts) == 2 else None

    monkeypatch.setattr(flow, "run_step", run_step)
    monkeypatch.setattr(flow.time, "sleep", naps.append)
    soon = datetime.now(UTC) + timedelta(minutes=10)
    with disable_run_logger():
        flow.download.fn("himawari", SLOT, "/scratch", soon)
        assert len(attempts) == 3 and naps == [60.0, 60.0]

        attempts.clear()
        assert flow.download.fn("himawari", SLOT, "/scratch", datetime.now(UTC)) == "download himawari exited with 1"
        assert len(attempts) == 1


def test_only_meteosats_download_is_handed_the_eumetsat_key(steps, monkeypatch):
    handed = {}

    def run_step(step, target, env, cores, **kwargs):
        handed[step] = "EUMETSAT_CONSUMER_KEY" in env

    monkeypatch.setattr(flow, "run_step", run_step)
    monkeypatch.setenv("EUMETSAT_CONSUMER_KEY", "key")
    monkeypatch.setenv("EUMETSAT_CONSUMER_SECRET", "secret")
    with disable_run_logger():
        for position in ("goes-east", "meteosat-0"):
            flow.download.fn(position, SLOT, "/scratch", SLOT)
    assert handed == {"download goes-east": False, "download meteosat-0": True}


# -- looking back for late Disks ---------------------------------------------


@pytest.fixture
def hourly(steps, queued, monkeypatch):
    """Make ``build_slot()`` the run of 18:10 on 2026-11-10 in a deployment, with every Disk at its source."""
    monkeypatch.setenv("EUMETSAT_CONSUMER_KEY", "key")
    monkeypatch.setenv("EUMETSAT_CONSUMER_SECRET", "secret")
    monkeypatch.setenv("PREFECT__RUNTIME__FLOW_RUN__SCHEDULED_START_TIME", "2026-11-10T18:10:00+00:00")
    monkeypatch.setenv("PREFECT__RUNTIME__DEPLOYMENT__ID", DEPLOYMENT)
    asked = {"down": set()}

    def disk_available(position, slot):
        if position in asked["down"]:
            raise ConnectionError(f"{position}: the source does not answer")
        return True

    monkeypatch.setattr(download, "disk_available", disk_available)
    return asked


def at(hour: int) -> datetime:
    return datetime(2026, 11, 10, hour, tzinfo=UTC)


def test_the_run_of_the_hour_queues_slots_that_lack_a_disk_or_were_never_built(steps, queued, hourly):
    flow.build_slot(at(15))                                      # done
    steps["unavailable"] = {"himawari"}
    flow.build_slot(at(17))                                      # built without a Disk
    steps["unavailable"] = set()
    assert queued == []                                          # a run for a named Slot does not look back

    flow.build_slot()

    rebuilds = {c["slot"]: c["idempotency_key"] for c in queued}
    assert rebuilds == {
        at(17).isoformat(): "rebuild-20261110T1700Z-himawari-20261110T1800Z",
        # 16:00 has no Mosaic, and an older one exists: its run failed.
        at(16).isoformat(): "rebuild-20261110T1600Z-goes-east+goes-west+himawari+meteosat-0+meteosat-iodc-20261110T1800Z",
    }                                                            # nothing before 15:00, the oldest Mosaic
    assert {c["work_queue_name"] for c in queued} == {"catch-up"}
    assert {c["as_subflow"] for c in queued} == {False}  # cancelling this run leaves them queued
    assert sorted(c["flow_run_name"] for c in queued) == ["georing-slot-20261110T1600Z", "georing-slot-20261110T1700Z"]


def test_with_rebuilds_turned_off_the_run_of_the_hour_does_not_look_back(steps, queued, hourly, monkeypatch):
    steps["unavailable"] = {"himawari"}
    flow.build_slot(at(17))                                      # built without a Disk
    steps["unavailable"] = set()
    monkeypatch.setenv("GEORING_REBUILD_LATE", "false")
    settings.cache_clear()

    assert flow.build_slot()["built"]
    assert queued == [] and "late disks" not in steps["steps"]


def test_without_its_key_the_data_store_is_not_asked(steps, queued, hourly, monkeypatch):
    monkeypatch.setattr(flow, "_secrets", dict)
    steps["unavailable"] = {"himawari", "meteosat-0"}
    flow.build_slot(at(17))
    steps["unavailable"] = set()

    flow.build_slot()

    assert steps["asked"] == {at(17).isoformat(): ["himawari"]}
    assert [c["idempotency_key"] for c in queued] == ["rebuild-20261110T1700Z-himawari-20261110T1800Z"]


def test_a_look_back_that_fails_does_not_fail_the_run(steps, hourly, monkeypatch):
    steps["unavailable"] = {"himawari"}
    flow.build_slot(at(17))
    steps["unavailable"] = set()

    def run_deployment(*args, **kwargs):
        raise ConnectionError("the server does not answer")

    monkeypatch.setattr(flow, "run_deployment", run_deployment)
    assert flow.build_slot()["built"]


def test_a_slot_that_was_never_built_is_made_up_for_six_hours_only(steps, queued, hourly):
    flow.build_slot(at(9))

    flow.build_slot()

    assert sorted(c["slot"] for c in queued) == [at(hour).isoformat() for hour in range(12, 18)]


def test_a_rebuild_is_queued_once_every_six_hours_however_often_the_run_of_the_hour_looks(steps, queued, hourly, monkeypatch):
    steps["unavailable"] = {"himawari"}
    flow.build_slot(at(11))
    steps["unavailable"] = set()
    keys = set()
    for hour in (12, 13, 17, 18):
        monkeypatch.setenv("PREFECT__RUNTIME__FLOW_RUN__SCHEDULED_START_TIME", f"2026-11-10T{hour}:10:00+00:00")
        queued.clear()
        flow.build_slot()
        keys.add(next(c["idempotency_key"] for c in queued if c["slot"] == at(11).isoformat()))
    # One key in six hours: Prefect hands back the run it already has for it.
    assert keys == {"rebuild-20261110T1100Z-himawari-20261110T1200Z", "rebuild-20261110T1100Z-himawari-20261110T1800Z"}

def test_a_source_that_cannot_be_asked_does_not_fail_the_run(steps, queued, hourly):
    steps["unavailable"] = {"himawari", "meteosat-0"}
    flow.build_slot(at(17))
    steps["unavailable"] = set()
    hourly["down"] = {"meteosat-0"}

    assert flow.build_slot()["built"]
    assert [c["idempotency_key"] for c in queued] == ["rebuild-20261110T1700Z-himawari-20261110T1800Z"]


# -- renders at once ----------------------------------------------------------


def renders_at_once(steps, monkeypatch) -> tuple[int, set[int], set[str]]:
    """Build SLOT; return the most renders seen running together, and each step's threads and CPUs."""
    original = flow.run_step
    lock = threading.Lock()
    running, seen = [0], {"most": 0, "threads": {}, "cpus": {}}

    def run_step(step, target, env, cores, **kwargs):
        kind = step.split()[0] if step.startswith(("render", "download")) else step
        with lock:
            seen["cpus"][kind] = cores
            if "threads" in kwargs:
                seen["threads"][kind] = (kwargs["threads"], int(env["DASK_NUM_WORKERS"]))
        if kind == "render":
            with lock:
                running[0] += 1
                seen["most"] = max(seen["most"], running[0])
            time.sleep(0.3)
            with lock:
                running[0] -= 1
        return original(step, target, env, cores, **kwargs)

    monkeypatch.setattr(flow, "run_step", run_step)
    assert flow.build_slot(SLOT)["disks"] == ALL
    return seen["most"], seen["threads"], seen["cpus"]


def test_renders_run_one_at_a_time_on_eight_cores_unless_set_otherwise(steps, monkeypatch):
    most, threads, cpus = renders_at_once(steps, monkeypatch)
    assert most == 1
    assert threads == {"render": (8, 8), "mosaic join": (8, 8), "mosaic encode": (8, 8)}
    assert set(cpus.values()) == {8}


def test_each_render_at_once_brings_eight_cores_of_its_own(steps, monkeypatch):
    monkeypatch.setenv("GEORING_PARALLEL_RENDERS", "2")
    settings.cache_clear()
    most, threads, cpus = renders_at_once(steps, monkeypatch)
    assert most == 2
    # A render keeps to eight threads; the join and the encode use all sixteen.
    assert threads == {"render": (8, 8), "mosaic join": (16, 16), "mosaic encode": (16, 16)}
    assert set(cpus.values()) == {16}  # every step may run on any of the sixteen
