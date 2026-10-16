# A failed boot fails fast, once

**Status:** Done

Implements [status-service.md](../specs/container/status-service.md) ("Readiness"), [container.md](../specs/container/container.md) ("Entrypoint") and [testing.md](../specs/testing/testing.md) ("A boot is checked before the tests that need it"). On `main`'s CI run after #10, a 2.8 restart in the live tier never became ready: its log stopped after the last service registered, the entrypoint said nothing, Docker called the container unhealthy two and a half minutes later, and every later 2.8 test failed for want of a robot. The entrypoint's wait polls `qicli info` with no time limit per call, so a call that hangs freezes it silently (the likely cause; not reproduced). Two changes: the entrypoint bounds every `qicli` call and says what it waits for; the live tier retries a failed boot once, then reports it once and skips the rest of that version.

## Scope

- `docker/naoqi/entrypoint-lib.sh` — `qi`, a plain-bash timeout around `qicli` (macOS, where the fast tier also runs the scripts, has no `timeout`); `call`, `wait_for_naoqi` and `check_answer` use it; three timed-out polls in a row fail the boot; a progress line every 10 polls; `NAOQI_SIM_QICLI_TIMEOUT`, `NAOQI_SIM_QICLI_HANGS`
- `tests/test_entrypoint.py` — the fake `qicli` hangs on chosen calls (`FAKE_QICLI_HANG`); a boot whose polls all hang fails in about a second with its reason; one hung poll does not fail a boot; the progress line names what is awaited
- `tests-e2e/conftest.py` — `Nao.start()` retries a `BootError` once and remembers a second one; the session fixture no longer boots; `_the_robot_runs`, an autouse fixture, starts the robot before a test that needs it when it is not running, fails the first test that needs a robot that did not boot (naming the test after which it was being brought back) and skips the others; a collection hook moves `test_the_robot_boots` to the head of each version's tests
- `tests-e2e/test_boot_live.py` — new: `test_the_robot_boots`
- `tests-e2e/test_install_live.py`, `test_naoqisim_live.py`, `test_audio_loopback_live.py` — the tests that stop the session's robot for their own needs no longer start it again in their cleanup
- The three specs (`Updated` until this plan is `Done`)

## Result (Oct 16, 2026)

- Fast tier: 321 passed, 1 skipped; ruff, format and pyright clean.
- CI (PR #12, second commit): all six jobs green; both images rebuilt with the new entrypoint, `test_the_robot_boots` first and passing on 2.1 and 2.8, the whole live tier green on both.

## Verification

`uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest`; the live tier's boot handling checked with throwaway plugins without Docker: `test_the_robot_boots` heads each version's tests; every boot failing fails it after two attempts and the rest skip; a robot stopped by a test and not booting again fails the next test, naming the test it follows, and the rest skip; the entrypoint change in real images through CI's live tier on 2.1 and 2.8 (not locally: rebuilding would overwrite the images another agent works with on this machine). Then the specs go back to `Implemented` and this plan to `Done`.
