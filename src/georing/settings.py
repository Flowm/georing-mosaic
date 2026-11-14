"""Settings: the defaults here, each changed by an environment variable.

``GEORING_OUTPUT_URL=s3://bucket/georing`` overrides ``output_url``, and so on
for every field. A variable that is set but empty counts as not set.
"""

from __future__ import annotations

from functools import cache, cached_property
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """What differs between the places this runs."""

    model_config = SettingsConfigDict(env_prefix="GEORING_", env_ignore_empty=True)

    # Positions that contribute Disks, by their names in georing.satellites.
    satellite_set: list[str] = ["goes-east", "goes-west", "himawari", "meteosat-0", "meteosat-iodc"]
    # Where products and the catalogue go: a directory, or s3://bucket/prefix.
    output_url: str = "out"
    # For a bucket only. The endpoint is for a service other than AWS, such as
    # https://<account>.r2.cloudflarestorage.com.
    s3_endpoint_url: str | None = None
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    # Scratch space for downloads and intermediate files, about 10 GB per Slot,
    # and the static files.
    work_dir: Path = Path("work")
    static_dir: Path | None = None  # default: <work_dir>/static
    # CPUs one render uses.
    cores: int = Field(default=8, ge=1)
    # Renders the flow runs at once. The worker then uses ``cores`` CPUs for
    # each, as one pool, and needs memory for the largest together: Meteosat's
    # render peaks at 22 GB, each of the others at 12. One fits 8 CPUs and
    # 32 GB; two want 16 CPUs and 64 GB.
    parallel_renders: int = Field(default=1, ge=1)

    @field_validator("satellite_set")
    @classmethod
    def _known_positions(cls, positions: list[str]) -> list[str]:
        from georing.satellites import SATELLITE_SET

        known = [sat.position for sat in SATELLITE_SET]
        if unknown := [p for p in positions if p not in known]:
            raise ValueError(f"no such position: {', '.join(unknown)}; there are {', '.join(known)}")
        if len(set(positions)) != len(positions):
            raise ValueError("a position is named twice")
        return positions

    @property
    def all_cores(self) -> int:
        """CPUs the worker uses: those of all the renders that run at once."""
        return self.cores * self.parallel_renders

    @property
    def static(self) -> Path:
        return (self.static_dir or self.work_dir / "static").resolve()

    @cached_property
    def store(self):
        """The store ``output_url`` names (``georing.storage``)."""
        from georing.storage import open_store

        key, secret = self.s3_access_key_id, self.s3_secret_access_key
        return open_store(
            self.output_url, endpoint_url=self.s3_endpoint_url,
            access_key_id=key and key.get_secret_value(),
            secret_access_key=secret and secret.get_secret_value(),
        )


def load_dotenv(path: Path) -> dict[str, str]:
    """Read ``KEY=value`` lines from ``path``. The values are never logged."""
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key and not key.startswith("#"):
                values[key] = value.strip().strip("\"'")
    return values


@cache
def settings() -> Settings:
    """Return the settings, read once."""
    return Settings()
