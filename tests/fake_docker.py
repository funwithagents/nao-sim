"""A fake `docker` first on PATH, for the tests of what nao-sim asks Docker.

The fake keeps its state in a JSON file: the images (ID and labels, set by `compose build` from
the environment's `NAO_SIM_VERSION` and `NAO_SIM_RECIPES`, the same ID for the same inputs, as
Docker's cache), the containers and how the NAOqi one boots (`boot`: healthy, starting,
unhealthy, exited), whether the tts engine answers, and whether Docker is up or a build fails.
Every invocation is logged, and `up` records the `NAO_SIM_TTS_ENGINE` it was given.
"""

import json
import os
import socket
import sys
import textwrap
from pathlib import Path

import pytest

from nao_sim import docker_images
from nao_sim.docker_images import IMAGES, TTS_IMAGE

FAKE_DOCKER = textwrap.dedent(
    """\
    import hashlib, json, os, sys
    path = os.environ["FAKE_DOCKER_STATE"]
    state = json.load(open(path))
    args = sys.argv[1:]
    state["calls"].append(" ".join(args))
    def done(code=0):
        json.dump(state, open(path, "w"))
        sys.exit(code)
    if state.get("down"):
        done(1)
    if args[0] == "info":
        done()
    if args[:2] == ["image", "inspect"]:
        image = state["images"].get(args[2])
        if image is None:
            done(1)
        print(json.dumps([{"Id": image["Id"], "Config": {"Labels": image["Labels"]}}]))
        done()
    if args[0] == "compose":
        verb = next(a for a in args if a in ("build", "up", "down", "ps", "logs"))
        services = args[args.index(verb) + 1:]
        services = [s for s in services if not s.startswith("-")]
        if verb == "build":
            if state.get("build_fails"):
                print("failed to solve: boom", file=sys.stderr)
                done(1)
            labels = {
                "io.nao-sim.version": os.environ.get("NAO_SIM_VERSION", "dev"),
                "io.nao-sim.recipes": os.environ.get("NAO_SIM_RECIPES", ""),
            }
            for s in services:
                tag = state["services"][s]["image"]
                inputs = tag + json.dumps(labels, sort_keys=True) + state.get("source", "")
                state["images"][tag] = {
                    "Id": "sha256:" + hashlib.sha256(inputs.encode()).hexdigest(),
                    "Labels": labels,
                }
        elif verb == "up":
            state["up_tts_engine"] = os.environ.get("NAO_SIM_TTS_ENGINE")
            for s in services:
                name = state["services"][s]["container"]
                state["containers"][name] = state["boot"] if s != "tts" else "running"
        elif verb == "logs":
            print("nao-sim-naoqi21  | [entrypoint] fake log line")
        elif verb == "ps":
            looks = {"healthy": ("running", "healthy"), "starting": ("running", "starting"),
                     "unhealthy": ("running", "unhealthy"), "exited": ("exited", ""),
                     "running": ("running", "")}
            for s, info in state["services"].items():
                status = state["containers"].get(info["container"])
                if status is not None:
                    st, health = looks[status]
                    print(json.dumps({"Name": info["container"], "Service": s,
                                      "State": st, "Health": health}))
        else:
            state["containers"] = {}
        done()
    if args[0] == "inspect":
        status = state["containers"].get(args[-1])
        if status is None:
            done(1)
        print({"healthy": "running healthy", "starting": "running starting",
               "unhealthy": "running unhealthy", "exited": "exited ",
               "running": "running "}[status])
        done()
    if args[0] == "exec":
        done(0 if state.get("tts_answers", True) else 1)
    if args[0] == "logs":
        print("[entrypoint] fake log line")
        done()
    done(2)
    """
)


class FakeDocker:
    def __init__(self, path: Path):
        self.path = path
        services = {
            i.service: {"image": i.image, "container": i.container}
            for i in IMAGES.values()
        }
        services["tts"] = {"image": TTS_IMAGE, "container": docker_images.TTS_CONTAINER}
        self.write(
            {
                "calls": [],
                "images": {},
                "containers": {},
                "boot": "healthy",
                "services": services,
            }
        )

    def read(self) -> dict:
        return json.loads(self.path.read_text())

    def write(self, state: dict) -> None:
        self.path.write_text(json.dumps(state))

    def set(self, **values) -> None:
        self.write({**self.read(), **values})

    @property
    def calls(self) -> list[str]:
        return self.read()["calls"]


@pytest.fixture
def docker(tmp_path, monkeypatch) -> FakeDocker:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "docker"
    script.write_text(f"#!{sys.executable}\n{FAKE_DOCKER}")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DOCKER_STATE", str(tmp_path / "docker.json"))
    monkeypatch.setattr(docker_images, "POLL", 0.01)
    # Verification needs the NAOqi port free; use one nothing listens on.
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        monkeypatch.setattr(docker_images, "NAOQI_PORT", s.getsockname()[1])
    return FakeDocker(tmp_path / "docker.json")
