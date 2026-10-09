# NaoSim status service and healthcheck

**Status:** Done

Implements `specs/container/status-service.md` (all sections): the `NaoSim` service on both NAOqi versions with its ALMemory keys, an entrypoint that verifies the replacements and fails loudly instead of printing a false "ready", a Docker healthcheck built on `NaoSim.isReady`, and the version build argument. Leaves out `nao-sim up` (which will consume the healthcheck) and boot-timing publication.

## Scope

- `docker/modules/nao_sim_status_core.py` — new: versions from the environment, the key table, the ready flag (Python 2.7, importable under Python 3)
- `docker/modules/nao_sim_status_almodule.py` — new: 2.1 `ALModule` shell
- `docker/modules/nao_sim_status_qiservice.py` — new: 2.8 qi service shell
- `docker/healthcheck.sh` — new: `qicli call NaoSim.isReady` on the public port, healthy on `true`
- `docker/entrypoint.sh` — paths from `NAOQI_HOME`, `NAO_SIM_READY_TRIES`, `NAO_SIM_POLL_INTERVAL`, exit non-zero when NAOqi never answers, verify each replaced name answers after loading, call `NaoSim.setReady` last
- `docker/Dockerfile.naoqi-2.1`, `docker/Dockerfile.naoqi-2.8` — `NAO_SIM_VERSION` build arg, `NAO_SIM_NAOQI_VERSION`, the status module first in `NAO_SIM_MODULES`, `HEALTHCHECK`, copy `healthcheck.sh`
- `docker/compose.yaml` — `build.args.NAO_SIM_VERSION`
- `tests/test_status_core.py` — new: keys written at load, versions from the environment and their defaults, readiness transition
- `tests/test_entrypoint.py` — new: runs `entrypoint.sh` on the host with fake `naoqi-bin` and `qicli` on `PATH`; checks the call sequence per version, the timeout, the missing-replacement failure, the dead `naoqi-bin`, and `healthcheck.sh`
- `tests-e2e/support.py` — `naoqi_version` per version, the version build arg, image environment and container health helpers
- `tests-e2e/test_status_live.py` — new: identity and keys over qi, `isReady`, the container turns `healthy`
- `specs/container/status-service.md`, `specs/container/container.md`, `specs/container/service-replacement.md`, `specs/testing/testing.md`, `specs/_overview.md`, `specs/_index.md`, `AGENTS.md`, `README.md` — docs and statuses

## Steps

1. Core module and the two shells; fast tests for the core.
2. Entrypoint rework with the two knobs; `healthcheck.sh`; fast tests driving the real script with fakes.
3. Dockerfiles and compose.
4. Live test and support helpers; rebuild both images; run the live tier.
5. Docs: carve the status-service section out of the overview, close the two entrypoint open questions, add the spec and plan rows; spec to `Implemented`, this plan `Done`.

## Verification

Done on Oct 9, 2026: lint, types and the fast tier pass (53 tests, including 11 that drive the real `entrypoint.sh` and `healthcheck.sh` with fakes); all six override modules compile with the image's Python 2.7.8; both images rebuilt; `uv run pytest tests-e2e` passes on 2.1 and 2.8 (20 tests), with both containers reaching `healthy`. Two things were found live and folded into the spec: 2.8's `qicli` prints the value bare and its `[W]` warnings on stdout (2.1 prefixes `NaoSim.isReady: `), and a cold-cache 2.8 boot right after an image rebuild had the ready service up while `naoqi-service` was still loading, which killed it when the built-in was exited; the entrypoint now waits for every needed service and a settled service list, and the rebuilt-image boot passed twice.

`uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest`; both images rebuilt with the new entrypoint and modules; `uv run pytest tests-e2e` on 2.1 and 2.8, including the new status tests; the modules compile with the image's `python2`. Mark this plan `Done` (here and in [_index.md](_index.md)) only once all pass.
