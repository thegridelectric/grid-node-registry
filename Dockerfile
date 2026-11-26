# syntax=docker/dockerfile:1
#
# The registry as one image:
#
#     docker build -t gnr .
#
# The image holds the gnr package with its locked dependencies and the
# alembic migrations, and runs `gnr`. Its command picks the process:
# `rabbit` (the write loop, the default), `api` (the read façade) or
# `seed-dev`. The schema is created with alembic from the same image:
#
#     docker run --entrypoint alembic gnr upgrade head
#
# Every setting comes from GNR_ environment variables (template.env lists
# them). No .env is baked in.

FROM python:3.12-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src/ src/
RUN uv sync --locked --no-dev --no-editable && rm -rf /root/.cache/uv

FROM python:3.12-slim-bookworm
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY alembic.ini ./
COPY alembic/ alembic/
RUN groupadd --gid 1000 gnr \
    && useradd --uid 1000 --gid 1000 --create-home gnr
USER gnr
ENV PATH="/app/.venv/bin:$PATH"
ENTRYPOINT ["gnr"]
CMD ["rabbit"]
