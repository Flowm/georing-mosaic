"""The commands for a shell: build one Slot now, or queue past Slots for the worker.

    georing-slot 2026-11-10T18:00
    georing-backfill 2026-11-10T04:00 2026-11-10T09:00

``georing-slot`` runs the flow in this process, with a temporary Prefect server
of its own and no worker. ``georing-backfill`` asks a running server for one
run per Slot.
"""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
from pathlib import Path

from georing.catalogue import stamp, to_slot
from georing.settings import settings


def parse_slot(text: str) -> datetime:
    """Parse a Slot time: a full clock hour in UTC."""
    when = datetime.fromisoformat(text)
    slot = to_slot(when)
    if slot != when.replace(tzinfo=when.tzinfo or UTC):
        raise argparse.ArgumentTypeError(f"a Slot is a full clock hour, not {text}")
    return slot


def slot_main(argv: list[str] | None = None) -> int:
    """Build one Slot with the flow, here and now."""
    parser = argparse.ArgumentParser(description=slot_main.__doc__)
    parser.add_argument("slot", type=parse_slot, help="Slot time, e.g. 2026-11-10T18:00")
    parser.add_argument("--out", type=Path, help="product directory; default: the output_url setting")
    parser.add_argument("--work", type=Path, help="scratch and static files; default: the work_dir setting")
    parser.add_argument("--force", action="store_true", help="build the Slot again even if it is done")
    args = parser.parse_args(argv)

    # The flow reads the settings itself, so the options go in as settings.
    if args.out:
        os.environ["GEORING_OUTPUT_URL"] = str(args.out.resolve())
    if args.work:
        os.environ["GEORING_WORK_DIR"] = str(args.work.resolve())
    cfg = settings()
    # Without a server to talk to, Prefect starts a temporary one with a
    # database of its own. Keep that with the scratch, not in the home directory.
    os.environ.setdefault("PREFECT_HOME", str(cfg.work_dir.resolve() / "prefect"))

    from georing.flow import build_slot
    from georing.static import fetch_static

    fetch_static(str(cfg.static))
    result = build_slot(args.slot, force=args.force)
    if not result["built"]:
        print(f"Slot {stamp(args.slot)} was left as it is, with {', '.join(result['disks']) or 'no Disk'}.")
        return 0
    print(f"Slot {stamp(args.slot)} built from {', '.join(result['disks'])}.")
    return 0


def backfill_main(argv: list[str] | None = None) -> int:
    """Queue a run of georing-slot for every Slot from START to END that is not done."""
    parser = argparse.ArgumentParser(description=backfill_main.__doc__)
    parser.add_argument("start", type=parse_slot, help="first Slot, e.g. 2026-11-10T04:00")
    parser.add_argument("end", type=parse_slot, nargs="?", help="last Slot; default: the last full hour")
    parser.add_argument("--force", action="store_true", help="also queue Slots that are done, to build them again")
    args = parser.parse_args(argv)
    if not os.environ.get("PREFECT_API_URL"):
        parser.error("PREFECT_API_URL is not set. Run this where the Prefect server is known, "
                     "as in the worker container: docker compose exec worker georing-backfill ...")

    from georing.flow import backfill

    queued = backfill(args.start, args.end, force=args.force)
    print(f"Queued {len(queued)} Slots" + (f", {queued[-1]} to {queued[0]}." if queued else "."))
    return 0
