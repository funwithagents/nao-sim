# nao-sim

nao-sim is a NAO in a box: NAOqi (`naoqi-bin` from the user's own Choregraphe suite, 2.1.4.13 or 2.8) runs in a local Docker container, and Python 2.7 override modules loaded inside its process replace the services a desktop virtual robot lacks (`ALTextToSpeech`, `ALAudioDevice`, perception), so the container looks like a real robot from the outside on port 9559. The host is a dumb device: it plays PCM, captures microphone and camera, and renders the MuJoCo world; every NAOqi-specific decision stays in the containers. Any qi client (nao-bridge, Choregraphe, existing scripts) then runs unchanged against nao-sim and a real NAO. It is one of three packages (with nao-bridge and nao-viewer); the cross-package design is in [_overview.md](_overview.md).

## Specs

<!-- One row per concept spec. Keep the Status column in sync with each spec's `**Status:**` line. -->

| Spec | Description | Status |
|---|---|---|
| [project.md](project.md) | Project structure and tooling: Python version, packaging with uv, layout conventions | Implemented |
| [testing.md](testing.md) | Testing strategy: two-tier `tests/`/`tests-e2e/` split, functional-test philosophy, skip-without-credentials live tier | Implemented |
| [speech.md](speech.md) | `ALTextToSpeech` replacement, `tts` engine container and host sound card: real-voice `say()` with NAOqi's events and timing | Draft |

[_overview.md](_overview.md) is the full toolkit specification (architecture, licensing, model pipeline, nao-bridge, nao-viewer, nao-sim, measured NAOqi 2.1/2.8 behaviour, milestones). It is reference material without a status; concept specs are extracted from it as work on each concept starts.

Each spec also opens with a YAML **frontmatter** block declaring the `code:` and `tests:` files it governs — the spec → code/tests mapping the spec-drift checks use to scope what they compare. Keep it current when files move, and see [AGENTS.md](../AGENTS.md) ("Spec frontmatter") for the full convention.

### Status legend

- **Not started** — no design decisions made yet
- **Draft** — actively being brainstormed/defined, contains open questions
- **Stable** — design settled, reviewed and validated (open questions are deferrals only), **ready to implement but not necessarily implemented yet**. This is the design-review gate, before code is written.
- **Implemented** — a **Stable** spec that a `Done` plan has built: the code now exists and matches the spec (design and code in sync)
- **Updated** — an **Implemented** spec since edited in a way that needs new code, so the code no longer matches it; a new implementation plan is needed (or in progress) to catch up. Returns to **Implemented** once that plan is `Done`.
