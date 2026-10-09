# Split the entrypoint per version

**Status:** Done

Implements `specs/container.md` ("Entrypoint"): one script per NAOqi version, each reading top to bottom as that version's procedure, with the shared steps in a sourced library and the version's facts as constants in its script instead of image environment variables. The procedure itself is unchanged; replacing built-ins by not loading them is left out.

## Scope

- `docker/entrypoint-2.1.sh`, `docker/entrypoint-2.8.sh` — new: each version's sequence and constants (`REPLACED`, `MODULES`, `DEPENDENTS`, `LAST_SERVICE`); 2.8 exports `NAO_SIM_INTERNAL_PORT` for its qi services.
- `docker/entrypoint-lib.sh` — new: `start_naoqi`, `wait_for_naoqi`, `autoload_without`, `exit_builtins`, `load_modules`, `check_answer`, `mark_ready`, `fail`.
- `docker/entrypoint.sh` — removed.
- `docker/Dockerfile.naoqi-2.1`, `docker/Dockerfile.naoqi-2.8` — copy their script and the library; the `NAO_SIM_*` procedure variables go.
- `tests/test_entrypoint.py` — each test runs the version's script; a check that 2.8's `naoqi-bin` inherits `NAO_SIM_INTERNAL_PORT`.
- Specs (`container.md`, `service-replacement.md`, `status-service.md`), `README.md`, `AGENTS.md`.

## Steps

1. Library, then the two scripts calling it.
2. Dockerfiles.
3. Tests against the fakes, unchanged expectations.
4. Rebuild and verify both images, live tier.

## Verification

`uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest`, `uv run pytest tests-e2e` (rebuilds and verifies both versions: the recipes changed). Then mark this plan `Done`.
