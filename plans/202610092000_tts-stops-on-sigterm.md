# tts stops on SIGTERM

**Status:** Done

Implements `specs/container/tts-engine.md` ("Image", the `SIGTERM` bullet). Measured with `docker stop` on a healthy 2.8 stack: the NAOqi container stops in 0.2 s (its entrypoint traps `TERM`), the `tts` container in 10.2 s with exit code 137, because its Python server is PID 1 and ignores `SIGTERM`. Every stack stop paid those 10 s (live-tier teardowns, the packages test's down and up). Leaves the NAOqi side unchanged.

## Scope

- `docker/tts/server.py` — a `SIGTERM` handler that exits with code 0.
- `specs/container/tts-engine.md` — the bullet (the spec stays `Implemented`: the code matches it again).

## Steps

1. Install the handler before the voices load, so a stop during start-up is prompt too.
2. Rebuild and verify with `nao-sim fetch-and-build-images` (the recipes changed), then time `docker stop` on each container again.

## Verification

`docker stop nao-sim-tts` returns in under a second with exit code 0; `uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest`, `uv run pytest tests-e2e`. Then mark this plan `Done`.
