# 2.8: every package service that calls the replaced built-ins restarts after them

**Status:** Done

Implements [service-replacement.md](../specs/container/service-replacement.md) ("Replacing a built-in") and [container.md](../specs/container/container.md) ("Entrypoint") on 2.8. The API coverage tests (plan 202610132100) found 2.8's `ALDialog` still calling the `ALTextToSpeech` the entrypoint had exited: a topic's answer failed with "module destroyed". Only `expressivity.autonomousabilitiesmodules` was restarted around the replacement. This plan restarts every package service whose code names `ALTextToSpeech` or `ALAudioPlayer`, which is what 2.1 does already (its `LATE` entries start after the replacement). It leaves 2.1 unchanged.

## Scope

- `docker/naoqi/entrypoint-2.8.sh` — `DEPENDENTS`: the package services found by the scan below, in boot order; stopped in reverse order before the built-ins exit, started in order after the fronts
- `tests/test_entrypoint.py` — the 2.8 sequence with the new stops and starts
- `tests-e2e/test_sound_live.py` — `test_a_dialog_topic_answers_aloud`, from plan 202610132100 (committed with that plan), now passes on 2.8
- `specs/container/service-replacement.md`, `specs/container/container.md` — the 2.8 dependents and how they were found

## The dependents (measured Oct 14, 2026)

The 2.8 suite's package services (`ALServiceManager.services()`) whose files name `ALTextToSpeech` or `ALAudioPlayer` (a search of the unpacked `dialog`, `expressivity`, `life` and `semantic` packages; translations, topics and behaviors left out), in boot order:

| Service | Library naming them |
|---|---|
| `dialog.dialog` (`ALDialog`) | `libaldialog.so`, `libdialogplayer.so` |
| `dialog.Conversation` | `libconversation_module.so` |
| `expressivity.thinkingexpression` | `libthinkingexpression_service.so` |
| `expressivity.expressiveness` | `libexpressiveness.so` |
| `expressivity.notificationreader` | `libnotificationreader.so` |
| `expressivity.autonomousabilitiesmodules` (`ALAnimatedSpeech`, already restarted) | `libanimatedspeech.so` |
| `life.autonomouslife` (`ALAutonomousLife`) | `libautonomouslife.so`, `libautonomouslaunchpad.so`, `libstiffnesssounds.so` |

## Steps

1. `entrypoint-2.8.sh`: `DEPENDENTS` lists the seven services in boot order; stop them in reverse order, start them in order.
2. `tests/test_entrypoint.py`: the 2.8 sequence expects the reverse stops, then the starts.
3. Specs: the 2.8 column of "Replacing a built-in" and the "Dependents" row name the seven services and the rule that finds them; status `Updated` until this plan is `Done`.
4. Rebuild the 2.8 image (the live tier does it) and run `test_sound_live.py`, `test_speech_live.py`, `test_audio_player_live.py`, `test_behaviors_live.py`, `test_modules_live.py` on 2.8; check the boot time.

## Result (Oct 14, 2026)

On 2.8, with the image rebuilt: `test_a_dialog_topic_answers_aloud` passes, and so do `test_speech_live.py`, `test_audio_player_live.py`, `test_behaviors_live.py`, `test_modules_live.py` and `test_status_live.py` (34 passed, 1 skipped; the 2 failures are the speaker volume and recording, gaps of plan 202610132100). A 2.8 start takes 35 s, against about 30 s with one restarted service.

## Verification

`uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest`, and the live files above on 2.8. Then the specs go back to `Implemented` and this plan to `Done`.
