"""Run each heavy step in a process of its own.

A step is a function named ``module:function`` that takes keyword arguments
and returns something JSON can hold. In a child process it is pinned to its
cores, sees only the credentials it is handed, gives all its memory back when
it ends, and can be stopped when it stalls.
"""

from __future__ import annotations

import ctypes
import importlib
import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from georing.static import static_env

# A Slot's downloads, the unpacked Himawari segments, four lossless renders
# and the lossless Mosaic share the scratch disk.
SCRATCH_NEEDED_GB = 40
# Credentials a step does not inherit. It has one only when it is handed it,
# as Meteosat's download is the EUMETSAT key.
SECRETS = (
    "EUMETSAT_CONSUMER_KEY", "EUMETSAT_CONSUMER_SECRET",
    "GEORING_S3_ACCESS_KEY_ID", "GEORING_S3_SECRET_ACCESS_KEY",
)


def runtime_env(static: Path, cores: int) -> dict[str, str]:
    """Return the environment satpy, dask and GDAL run under in a step."""
    return {
        **static_env(static),
        "SATPY_CONFIG_PATH": str(Path(__file__).parent / "satpy"),  # the Recipe
        "OMP_NUM_THREADS": "1",
        "DASK_NUM_WORKERS": str(cores),
        "DASK_ARRAY__CHUNK_SIZE": "32MiB",
        "GDAL_CACHEMAX": "2048",
    }


class StepFailed(RuntimeError):
    """A step's process exited with an error, or was stopped."""


def run_step(step: str, target: str, env: dict[str, str], cores: int, timeout_s: float | None = None, **kwargs):
    """Run ``target`` in a child process pinned to ``cores`` CPUs and return what it returns.

    A step still running after ``timeout_s`` seconds is killed, with whatever
    it started, and counts as failed: a download that stalls must not hold up
    every Slot after it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        args = Path(tmp) / "args.json"
        result = Path(tmp) / "result.json"
        args.write_text(json.dumps(kwargs))
        inherited = {name: value for name, value in os.environ.items() if name not in SECRETS}
        # In a process group of its own, so that it can be killed with
        # whatever it started, such as the unpacking of Himawari's segments.
        child = subprocess.Popen(
            [sys.executable, "-m", "georing.step", target, str(args), str(result), str(cores)],
            env={**inherited, **env}, start_new_session=True,
        )
        try:
            code = child.wait(timeout_s)
        except subprocess.TimeoutExpired:
            raise StepFailed(f"{step} was stopped after {timeout_s:.0f} s") from None
        finally:
            if child.poll() is None:
                # Timed out, or this process was interrupted while it waited.
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        if code != 0:
            raise StepFailed(f"{step} exited with {code}")
        return json.loads(result.read_text())


def _child(target: str, args: str, result: str, cores: str) -> None:
    # Die with the process that started this step: nothing else would stop
    # it, now that it is in a group of its own. 1 is PR_SET_PDEATHSIG.
    ctypes.CDLL(None).prctl(1, signal.SIGKILL)
    available = sorted(os.sched_getaffinity(0))
    os.sched_setaffinity(0, available[: int(cores)])
    module, function = target.split(":")
    out = getattr(importlib.import_module(module), function)(**json.loads(Path(args).read_text()))
    Path(result).write_text(json.dumps(out))
    # Skip interpreter teardown: on Python 3.14 a raster opened lazily through
    # rioxarray prints "Error in sys.excepthook" there, with nothing wrong.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    _child(*sys.argv[1:])
