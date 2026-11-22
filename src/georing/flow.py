"""The Prefect flow: one run of ``georing-slot`` builds one Slot.

The flow carries the project's name and every run that of its Slot, so that
they can be told apart on a server shared with other flows. A backfill is
nothing but runs of the same flow for past Slots; ``backfill`` queues them.

Every heavy step runs in a child process of its own (``georing.step``), so
the flow process stays small and a step that stalls can be stopped.
"""

from __future__ import annotations

import os
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from prefect import flow, get_run_logger, runtime, task
from prefect.deployments import run_deployment
from prefect.futures import as_completed

from georing.catalogue import Catalogue, mosaic_id, stamp, to_slot
from georing.download import DiskMissing
from georing.lights.cog import LOGIN, NoLogin, lights_path
from georing.satellites import InDataStore, by_position
from georing.settings import Settings, load_dotenv, settings
from georing.step import SCRATCH_NEEDED_GB, StepFailed, run_step, runtime_env

SLOT_DEPLOYMENT = "georing-slot/hourly"
# Rebuilds and backfills wait in a queue of their own, which the worker serves
# after the default one: they must not hold up the Slot of the hour.
CATCH_UP_QUEUE = "catch-up"
# How long a download waits before it asks its source again.
POLL = timedelta(minutes=1)
# Past the hour, a Slot builds without a Disk that has not arrived by then.
# The measurement behind it is in the notes, under "Arrival times".
DEADLINE = timedelta(minutes=35)
# A step that has not finished by then is stopped. The slowest takes five minutes.
STEP_TIMEOUT = timedelta(minutes=30)
# A download that has not finished by then is stopped, and asked for again
# until the deadline. The slowest takes 80 s; one that hangs on a source in
# trouble must not hold the Slot long past its deadline.
DOWNLOAD_TIMEOUT = timedelta(minutes=5)
# A rebuild that got nothing, as when a source answers a search but not a
# download, is asked for again after this long.
REBUILD_AGAIN = timedelta(hours=6)
# A Slot that was never built is made up for only this long. An outage longer
# than that is a backfill, which someone asks for.
RETRY_UNBUILT = timedelta(hours=6)
# How far back the run of the hour looks for Slots that lack a Disk.
LOOK_BACK = timedelta(hours=48)
# Building the city lights downloads 51 GB once. A build stopped by this
# limit goes on from where it was in the next run.
LIGHTS_TIMEOUT = timedelta(hours=4)
# A scratch directory untouched for this long was left by a run that died.
STALE_SCRATCH = timedelta(hours=3)


def scheduled_slot(slot: datetime | None) -> datetime:
    """Return the Slot a run is for: the one asked for, else the hour the run was scheduled in.

    Not the hour it starts in. A run that starts late, after an outage or
    behind another run, still builds its own hour.
    """
    return to_slot(slot or runtime.flow_run.scheduled_start_time)


def _env(cfg: Settings, scratch: Path, threads: int | None = None) -> dict[str, str]:
    return {**runtime_env(cfg.static, threads or cfg.all_cores, _lights(cfg)), "TMPDIR": str(scratch / "tmp")}


def _lights(cfg: Settings) -> Path:
    return lights_path(cfg.work_dir.resolve())


def _credentials(names: tuple[str, ...]) -> dict[str, str]:
    """Return the credentials ``names``: from the environment, else from ``.env``; all of them or none."""
    found = {n: os.environ[n] for n in names if os.environ.get(n)}
    if len(found) < len(names):
        found = {n: v for n, v in load_dotenv(Path(".env")).items() if n in names and v}
    return found if len(found) == len(names) else {}


def _secrets() -> dict[str, str]:
    """Return the EUMETSAT key and secret, which the Data Store wants."""
    return _credentials(("EUMETSAT_CONSUMER_KEY", "EUMETSAT_CONSUMER_SECRET"))


def _askable(cfg: Settings) -> list[str]:
    """Return the positions whose source can be asked: without its key the Data Store cannot."""
    secrets = _secrets()
    return [p for p in cfg.satellite_set if secrets or not isinstance(by_position(p), InDataStore)]


def _step(cfg: Settings, step: str, target: str, env: dict[str, str], timeout: timedelta = STEP_TIMEOUT, **kwargs):
    return run_step(step, target, env, cfg.all_cores, timeout_s=timeout.total_seconds(), **kwargs)


@task
def download(position: str, slot: datetime, scratch: str, deadline: datetime) -> None:
    """Download one Disk, asking its source once a minute until ``deadline``.

    Fails if the source does not hold all of the Disk by then.
    """
    cfg = settings()
    log = get_run_logger()
    # Only the EUMETSAT Data Store wants a key.
    secrets = _secrets() if isinstance(by_position(position), InDataStore) else {}
    said = None
    while True:
        try:
            lacking = _step(
                cfg, f"download {position}", "georing.download:poll_disk",
                {**_env(cfg, Path(scratch)), **secrets}, timeout=DOWNLOAD_TIMEOUT,
                position=position, slot=slot.isoformat(), dest=f"{scratch}/{position}",
            )
        except StepFailed as failure:
            lacking = str(failure)
        if lacking is None:
            return
        if datetime.now(UTC) + POLL > deadline:
            raise DiskMissing(lacking)
        if lacking != said:
            # Not every minute: Meteosat's answer stays the same for many.
            log.info("%s; asking every minute until %s", lacking, f"{deadline:%H:%M}")
            said = lacking
        time.sleep(POLL.total_seconds())


@task(task_run_name="city-lights")
def city_lights() -> str:
    """Make sure the city-lights COG the Recipe reads is there; build it if it is not.

    Built once, from NASA's tiles (``georing.lights``). Every render waits
    for it.
    """
    cfg = settings()
    path = _lights(cfg)
    if path.exists():
        return str(path)
    credentials = _credentials(LOGIN)
    if not credentials:
        raise NoLogin(path)
    get_run_logger().info("Building the city lights at %s; this downloads 51 GB once", path)
    return run_step(
        "city lights", "georing.lights.cog:build_city_lights",
        {**runtime_env(cfg.static, 1, path), **credentials}, cfg.all_cores,
        timeout_s=LIGHTS_TIMEOUT.total_seconds(), dest=str(path),
    )


@task
def render(position: str, slot: datetime, scratch: str) -> None:
    """Render one Disk to a lossless Rendering on scratch."""
    cfg = settings()
    # A render keeps to its own share of the cores; others may run beside it.
    _step(
        cfg, f"render {position}", "georing.render:render_disk", _env(cfg, Path(scratch), cfg.cores),
        position=position, disk_dir=f"{scratch}/{position}",
        grid_dir=str(cfg.work_dir.resolve() / "grids"), dest=f"{scratch}/{position}.tif", threads=cfg.cores,
    )


@task(task_run_name="join")
def join(sources: dict[str, str], slot: datetime, scratch: str) -> None:
    """Join the renders of the Slot into a lossless Mosaic on scratch."""
    cfg = settings()
    _step(
        cfg, "mosaic join", "georing.mosaic:join_renderings", _env(cfg, Path(scratch)),
        renders=sources, dest=f"{scratch}/mosaic.tif", slot=slot.isoformat(), threads=cfg.all_cores,
    )


@task(task_run_name="encode")
def encode(slot: datetime, scratch: str) -> None:
    """Write the Mosaic as the COG that is published, and check its tile layout."""
    cfg = settings()
    _step(
        cfg, "mosaic encode", "georing.mosaic:encode_mosaic", _env(cfg, Path(scratch)),
        source=f"{scratch}/mosaic.tif", dest=f"{scratch}/{mosaic_id(slot)}.tif", threads=cfg.all_cores,
    )


@task(task_run_name="publish")
def publish(slot: datetime, disks: list[str], scratch: str) -> None:
    """Put the Mosaic in the store, and its Item beside it."""
    cfg = settings()
    missing = [p for p in cfg.satellite_set if p not in disks]
    Catalogue(cfg.store).publish(slot, Path(f"{scratch}/{mosaic_id(slot)}.tif"), disks, missing)


@task(task_run_name="index")
def index() -> dict:
    """Rewrite the catalogue's list of Mosaics and ``latest.json``."""
    return Catalogue(settings().store).index()


@task(task_run_name="late-disks")
def late_disks(before: datetime) -> dict[str, list[str]]:
    """Return, by Slot time, the Disks that earlier Slots lack and their sources now hold.

    The last 48 Slots are looked at. A Slot with no Mosaic at all lacks every
    Disk: its run failed or never started. It counts for six hours, and only
    if an older Mosaic exists, so that neither a new deployment nor a long
    outage builds days of Slots unasked.

    The sources are asked in a step of its own, under the step time limit: a
    request that stalls must not hold up the Slots after this one.
    """
    cfg = settings()
    catalogue = Catalogue(cfg.store)
    secrets = _secrets()
    askable = _askable(cfg)
    slots = [before - timedelta(hours=h) for h in range(1, LOOK_BACK // timedelta(hours=1) + 1)]
    items = {slot: catalogue.mosaic(slot) for slot in slots}
    oldest = min((slot for slot in slots if items[slot]), default=None)
    lacking = {}
    for slot in slots:
        if items[slot]:
            missing = items[slot]["properties"]["georing:missing_disks"]
        elif oldest and slot > oldest and before - slot <= RETRY_UNBUILT:
            missing = cfg.satellite_set
        else:
            continue
        if wanted := [p for p in missing if p in askable]:
            lacking[slot.isoformat()] = wanted
    if not lacking:
        return {}
    return _step(
        cfg, "late disks", "georing.download:disks_available",
        {**runtime_env(cfg.static, 1, _lights(cfg)), **secrets}, wanted=lacking,
    )


def _slot_run_name() -> str:
    return f"georing-slot-{stamp(scheduled_slot(runtime.flow_run.parameters.get('slot')))}"


@flow(name="georing-slot", flow_run_name=_slot_run_name)
def build_slot(slot: datetime | None = None, force: bool = False) -> dict:
    """Build the Slot ``slot``, or the one of the hour the run was scheduled in.

    A Slot that is done is left alone. A Slot that was built without one of
    its Disks is built again, from all its Disks, and replaced if that adds a
    Disk. ``force`` builds a Slot again whatever it has, and replaces it
    unless that would lose a Disk.
    """
    log = get_run_logger()
    cfg = settings()
    hourly = slot is None
    slot = scheduled_slot(slot)
    if slot > to_slot(None):
        raise ValueError(f"Slot {stamp(slot)} has not begun")
    catalogue = Catalogue(cfg.store)
    done = catalogue.mosaic(slot)
    previous = done["properties"]["georing:disks"] if done else []
    if done and not force and all(p in previous for p in cfg.satellite_set):
        log.info("Slot %s is done", stamp(slot))
        return {"slot": slot.isoformat(), "built": False, "disks": previous}

    root = cfg.work_dir.resolve() / "scratch"
    _clear_stale_scratch(root)
    scratch = root / stamp(slot)
    (scratch / "tmp").mkdir(parents=True, exist_ok=True)
    try:
        free_gb = shutil.disk_usage(scratch).free / 1e9
        if free_gb < SCRATCH_NEEDED_GB:
            raise RuntimeError(f"{free_gb:.0f} GB free at {scratch}, {SCRATCH_NEEDED_GB} GB needed")
        built = _build(cfg, slot, scratch, previous, force)
    finally:
        # Also after a failure: scratch that stays would fill the disk.
        shutil.rmtree(scratch, ignore_errors=True)

    if not built:
        if done:
            log.info("Slot %s stays as it was, with %s", stamp(slot), ", ".join(previous))
            return {"slot": slot.isoformat(), "built": False, "disks": previous}
        raise RuntimeError(f"No Disk could be had for Slot {stamp(slot)}")
    disks, indexed = built
    # Only the run of the hour looks back; a rebuild would queue the same again.
    if hourly and runtime.deployment.id and cfg.rebuild_late:
        try:
            _queue_rebuilds(slot)
        except Exception as failure:  # noqa: BLE001 (the store, a source or Prefect, whatever it raises)
            # The Slot is published. Looking back is tried again next hour.
            log.warning("Could not look back for late Disks: %r", failure)
    return {"slot": slot.isoformat(), "built": True, "disks": disks, "latest": indexed["latest"]}


def _queue_rebuilds(slot: datetime) -> None:
    """Queue a rebuild for each earlier Slot that can now get a Disk it lacks."""
    log = get_run_logger()
    hours = REBUILD_AGAIN // timedelta(hours=1)
    asked = slot.replace(hour=slot.hour - slot.hour % hours)
    for late, lacking in late_disks(slot).items():
        log.info("Slot %s can now get %s; queueing its rebuild", late, ", ".join(lacking))
        late_slot = datetime.fromisoformat(late)
        run_deployment(
            SLOT_DEPLOYMENT, parameters={"slot": late}, timeout=0,
            # Named now: a run that waits would show a random name until it starts.
            flow_run_name=f"georing-slot-{stamp(late_slot)}", work_queue_name=CATCH_UP_QUEUE,
            # Not a child of this run: cancelling it must not cancel the rebuilds.
            as_subflow=False,
            # The same rebuild is asked for once in each REBUILD_AGAIN.
            idempotency_key=f"rebuild-{stamp(late_slot)}-{'+'.join(lacking)}-{stamp(asked)}",
        )


def _build(
    cfg: Settings, slot: datetime, scratch: Path, previous: list[str], force: bool
) -> tuple[list[str], dict] | None:
    """Download, render, join, encode, publish and index.

    ``previous`` names the Disks of the Mosaic that is there, if one is.
    Returns None, with nothing joined, if no Disk could be rendered or if
    the Mosaic there is at least as good.
    """
    log = get_run_logger()
    deadline = slot + DEADLINE

    def fetch(positions: list[str]) -> dict:
        return {
            download.with_options(task_run_name=f"download-{p}").submit(p, slot, str(scratch), deadline): p
            for p in positions
        }

    # A rebuild first fetches the Disks its Mosaic lacks. If none can be had
    # it stops there, before downloading and rendering the Disks it has: a
    # source that is down must not cost a run of half an hour every hour.
    arrived: list[str] = []
    lacking = [p for p in cfg.satellite_set if p not in previous] if previous and not force else []
    for finished, position in fetch(lacking).items():
        if isinstance(outcome := finished.result(raise_on_failure=False), BaseException):
            log.warning("No Disk for %s: %s", position, outcome)
        else:
            arrived.append(position)
    if lacking and not arrived:
        log.info("Slot %s is left as it is: no Disk it lacks could be had", stamp(slot))
        return None
    downloads = fetch([p for p in cfg.satellite_set if p not in lacking])
    # Every render reads the city lights. Waiting for them here, the Disks
    # still download meanwhile: a build of the lights must not make one late.
    try:
        city_lights()
    except BaseException:
        # The downloads write into the scratch that is removed as the run
        # ends; left running, they would fill it again after that, with
        # nothing to remove it for hours.
        for downloading in downloads:
            downloading.wait()
        raise

    renders: dict[str, str] = {}
    # Render each Disk as it arrives: a late one must not hold up the others.
    # ``cfg.parallel_renders`` run at once; a Disk that arrives meanwhile waits.
    rendering = {}
    while downloads or arrived or rendering:
        while arrived and len(rendering) < cfg.parallel_renders:
            position = arrived.pop(0)
            started = render.with_options(task_run_name=f"render-{position}").submit(position, slot, str(scratch))
            rendering[started] = position
        finished = next(as_completed([*downloads, *rendering]))
        outcome = finished.result(raise_on_failure=False)
        if finished in downloads:
            position = downloads.pop(finished)
            if isinstance(outcome, BaseException):
                log.warning("No Disk for %s by the deadline: %s", position, outcome)
                continue
            arrived.append(position)
        else:
            position = rendering.pop(finished)
            if isinstance(outcome, BaseException):
                # One Disk that cannot be rendered must not cost the Slot the
                # other three.
                log.error("Rendering %s failed: %r", position, outcome)
                continue
            renders[position] = f"{scratch}/{position}.tif"
    if not renders:
        return None

    # A rebuild replaces a Mosaic only by a better one.
    if lost := [p for p in previous if p not in renders]:
        log.warning("Slot %s is left as it is: a rebuild would lose %s", stamp(slot), ", ".join(lost))
        return None
    if previous and not force and len(renders) == len(previous):
        log.info("Slot %s is left as it is: no Disk it lacks could be had", stamp(slot))
        return None
    sources = {p: renders[p] for p in cfg.satellite_set if p in renders}
    join(sources, slot, str(scratch))
    encode(slot, str(scratch))
    publish(slot, list(sources), str(scratch))
    return list(sources), index()


def _clear_stale_scratch(root: Path) -> None:
    """Remove the scratch of runs that died before they could: what nothing has touched for hours."""
    if not root.exists():
        return
    cutoff = time.time() - STALE_SCRATCH.total_seconds()
    for path in root.iterdir():
        if path.is_dir() and path.stat().st_mtime < cutoff:
            get_run_logger().warning("Removing scratch left by an earlier run: %s", path.name)
            shutil.rmtree(path, ignore_errors=True)


def backfill(start: datetime, end: datetime | None = None, force: bool = False) -> list[str]:
    """Queue a run for every Slot from ``start`` to ``end`` that is not done, newest first.

    ``end`` defaults to the last full hour. The runs go to the catch-up queue,
    so they do not hold up the Slot of the hour. Returns the Slots queued.
    """
    cfg = settings()
    catalogue = Catalogue(cfg.store)
    askable = _askable(cfg)
    asked = datetime.now(UTC)
    first, last = to_slot(start), to_slot(end) if end else to_slot(None) - timedelta(hours=1)
    if last > to_slot(None):
        raise ValueError(f"Slot {stamp(last)} has not begun")

    queued = []
    slot = last
    while slot >= first:
        item = catalogue.mosaic(slot)
        # A Disk whose source cannot be asked would only be missed again.
        if force or not item or any(p in askable for p in item["properties"]["georing:missing_disks"]):
            run_deployment(
                SLOT_DEPLOYMENT, parameters={"slot": slot.isoformat(), "force": force}, timeout=0,
                flow_run_name=f"georing-slot-{stamp(slot)}", work_queue_name=CATCH_UP_QUEUE,
                # Asking again later queues again; a retry of this call does not.
                idempotency_key=f"backfill-{stamp(slot)}-{asked:%Y%m%dT%H%M%S}",
            )
            queued.append(stamp(slot))
        slot -= timedelta(hours=1)
    return queued
