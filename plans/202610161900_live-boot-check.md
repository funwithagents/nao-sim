# A failed boot fails fast, once

**Status:** In progress

Implements [status-service.md](../specs/container/status-service.md) ("Readiness"), [container.md](../specs/container/container.md) ("Entrypoint") and [testing.md](../specs/testing/testing.md) ("A boot is checked before the tests that need it"). On `main`'s CI run after #10, a 2.8 restart in the live tier never became ready: its log stopped after the last service registered, the entrypoint said nothing, Docker called the container unhealthy two and a half minutes later, and every later 2.8 test failed for want of a robot. The entrypoint's wait polls `qicli info` with no time limit per call, so a call that hangs freezes it silently (the likely cause; not reproduced). Two changes: the entrypoint bounds every `qicli` call and says what it waits for; the live tier retries a failed boot once, then reports it once and skips the rest of that version.

## Scope

- `docker/naoqi/entrypoint-lib.sh` — `qi`, a plain-bash timeout around `qicli` (macOS, where the fast tier also runs the scripts, has no `timeout`); `call`, `wait_for_naoqi` and `check_answer` use it; three timed-out polls in a row fail the boot; a progress line every 10 polls; `NAOQI_SIM_QICLI_TIMEOUT`, `NAOQI_SIM_QICLI_HANGS`
- `tests/test_entrypoint.py` — the fake `qicli` hangs on chosen calls (`FAKE_QICLI_HANG`); a boot whose polls all hang fails in about a second with its reason; one hung poll does not fail a boot; the progress line names what is awaited
- `tests-e2e/conftest.py` — `Nao.start()` retries a `BootError` once and remembers a second one; the session fixture keeps going after a failed first boot; `_the_robot_booted`, an autouse fixture, fails the first test that needs a robot that did not boot and skips the others
- The three specs (`Updated` until this plan is `Done`)

## Verification

`uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest`; the live tier's boot handling checked with a throwaway plugin that fails every boot (one error carrying the boot's message after two attempts, the rest skipped; a restart failing inside a test fails that test, the next skips); the entrypoint change in real images through CI's live tier on 2.1 and 2.8 (not locally: rebuilding would overwrite the images another agent works with on this machine). Then the specs go back to `Implemented` and this plan to `Done`.
