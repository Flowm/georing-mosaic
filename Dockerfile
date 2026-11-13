# The worker: the georing package with its static files, on Python 3.14.
FROM python:3.14-slim-bookworm

# pbzip2 unpacks Himawari's segments on all cores. rasterio's wheel needs libexpat.
RUN apt-get update \
    && apt-get install -y --no-install-recommends pbzip2 libexpat1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

# Dependencies first, so that a change in our own code reuses this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
# The package's metadata names the licence file.
COPY LICENSE ./
COPY src ./src
RUN uv sync --locked --no-dev
# Fail the build, not a Slot, if a wheel misses a system library.
RUN python -c "import rasterio, hdf5plugin, netCDF4, pykdtree.kdtree, satpy.readers.generic_image, georing.flow"

# satpy's and pyspectral's static files, fetched here so that a run downloads
# only satellite data.
ENV GEORING_STATIC_DIR=/opt/georing/static
RUN georing-static

# The worker runs as whoever owns the output directory, so these are open.
RUN mkdir -p /data/out /data/work && chmod 1777 /data/out /data/work
ENV HOME=/data/work/home

COPY prefect.yaml worker.sh ./
CMD ["./worker.sh"]
