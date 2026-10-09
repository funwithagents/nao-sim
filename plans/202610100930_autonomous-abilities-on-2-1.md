# Autonomous abilities on 2.1

**Status:** Done

Implements `specs/container/container.md` ("Entrypoint", `LATE`; "Matching a NAO's modules"): the 2.1 entrypoint launches the built-ins a NAO 2.1 autoloads and the desktop suite ships without loading (`expressiveness`, `basicawareness`, `autonomousblinking`, `autonomousmoves`), and defers `autonomouslife` until after them, in a NAO's autoload order, so `ALBasicAwareness` and `ALAutonomousMoves` exist on 2.1 as on a robot. Leaves out the other shipped-but-not-loaded modules (container.md, open question 3); 2.8 needs nothing.

## Scope

- `docker/entrypoint-lib.sh` — new `launch_local <entries...>`: `ALLauncher.launchLocal` per entry, in order, exiting 1 (after terminating `naoqi-bin`, as `fail` does) when a launch registers no module (an empty list in `qicli`'s output)
- `docker/entrypoint-2.1.sh` — `DEPENDENTS` becomes `LATE="expressiveness animatedspeech basicawareness autonomousblinking autonomousmoves autonomouslife dialog"` (commented, entry by entry: dependent, added, or needing the added ones); `autoload_without $LATE` (a no-op for the entries the desktop does not autoload); `launch_local $LATE` in place of the current loop; `LAST_SERVICE="ALPanoramaCompass"`
- `tests/test_entrypoint.py` — the fake `qicli` answers `launchLocal` with the module it registers (`ALLauncher.launchLocal: [ "X" ]`), or an empty list for entries in a `FAKE_QICLI_EMPTY_LAUNCH` variable; the 2.1 sequence test expects `autonomouslife` and `dialog` out of the autoload copy, `ALPanoramaCompass` waited for, and the seven `LATE` launches in order; a new test: a `LATE` entry that registers nothing fails the boot, with no ready mark
- `tests-e2e/test_modules_live.py` — new: the modules a NAO of each version runs are there (step 4)
- `specs/container/container.md`, `specs/_index.md` — status back to `Implemented`

## Steps

1. `launch_local` in `entrypoint-lib.sh`, used by `entrypoint-2.1.sh` for `LATE`. The deferred dependents get the same check: today a failed `launchLocal animatedspeech` would go unnoticed.
2. Fake `qicli`: return value of `launchLocal`, the empty-launch switch.
3. Fast tests: updated 2.1 sequence; the failing `LATE` launch; 2.8's sequence unchanged.
4. Live test, `tests-e2e/test_modules_live.py`: `ALBasicAwareness` and `ALAutonomousLife` are registered on both versions and `ALAutonomousLife.getState()` answers; on 2.1, `ALAutonomousMoves` is registered too. `ALAutonomousMoves` does not exist on 2.8 (its abilities moved to `ALBackgroundMovement` and friends), so that assertion is 2.1 only. The existing speech and package live tests cover `animatedspeech` and `dialog` still working when launched late.
5. Rebuild the 2.1 image (the live tier does it, since `docker/` changed), run the live tier on both versions, and check the 2.1 boot time stays within the healthcheck's start period.
6. `container.md` to `Implemented`, this plan `Done`, in both files and both indexes; remove the plan link from the overview's "still to build" bullet.

## Verification

`uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest` (fast tier, `tests/test_entrypoint.py` included), then `uv run pytest tests-e2e` on 2.1 and 2.8. Mark this plan `Done` (here and in [_index.md](_index.md)) only once all pass.
