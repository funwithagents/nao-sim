# Drop the NaoSim/Perception/Source key

**Status:** Done

Implements the change to `specs/container/status-service.md` ("ALMemory keys"): perception runs in the clients, not in nao-sim, so the `NaoSim` status module stops writing `NaoSim/Perception/Source`. The camera and audio source keys, the versions and readiness are unchanged; nothing else in the service moves.

## Scope

- `docker/modules/nao_sim_status_core.py` — `DEVICES` loses `"Perception"`
- `tests/test_status_core.py` — the keys written at load no longer include `NaoSim/Perception/Source`
- `tests-e2e/test_status_live.py` — the live target no longer has the key (checked with `ALMemory.getDataListName()`, since `getData` on a missing key raises)
- `specs/container/status-service.md`, `specs/_index.md` — drop the "as built" note, status back to `Implemented`

## Steps

1. Remove `"Perception"` from `DEVICES` in the core module.
2. Update the fast test's expected key table.
3. Update the live test: assert the camera and audio keys as today, and that `NaoSim/Perception/Source` is not in `getDataListName()`.
4. Rebuild the images (`nao-sim fetch-and-build-images`; the live tier does it on its own since `docker/` changed) and run the live tier on 2.1 and 2.8.
5. Remove the "As built, the module still writes it" sentence from `status-service.md`; spec to `Implemented`, this plan `Done`, in both files and both indexes.

## Verification

`uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest` (fast tier, `tests/test_status_core.py` included), then `uv run pytest tests-e2e/test_status_live.py` on both versions. Mark this plan `Done` (here and in [_index.md](_index.md)) only once all pass.
