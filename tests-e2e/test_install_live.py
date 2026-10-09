"""nao-sim installed in another project as a uv git dependency builds it (specs/project.md,
"Distribution"): a wheel holding the recipes, with nao-sim's own sources for qi and nao-viewer.

The scratch project depends on this checkout as a non-editable path, which uv builds and installs
exactly as it does a git dependency, without pushing a commit. It then runs nao-sim from that
project's environment: the recipes it reads from its package, the commands it installs, and a
`nao-sim run` booting the images this checkout built, through `NAO_SIM_IMAGE_DATA`.
"""

import json
import os
import shutil
import signal
import subprocess
from pathlib import Path

import platformdirs
import pytest
from conftest import live_config
from support import IMAGE_DATA, REPO, unavailable

from nao_sim import docker_images

PYPROJECT = """\
[project]
name = "scratch"
version = "0.1.0"
requires-python = ">=3.12,<3.14"
dependencies = ["nao-sim[viewer]"]

[tool.uv.sources]
nao-sim = {{ path = "{repo}", editable = false }}

[tool.uv]
environments = [
    "sys_platform == 'darwin' and platform_machine == 'arm64'",
    "sys_platform == 'linux' and platform_machine == 'x86_64'",
]
"""

# What the installed package says about itself, run with the project's Python.
_WHERE = """\
import json, os, nao_sim
from nao_sim import docker_images, files
package = os.path.dirname(nao_sim.__file__)
print(json.dumps({
    "package": package,
    "installed": files.INSTALLED,
    "recipes": str(files.RECIPES),
    "image_data": str(files.IMAGE_DATA),
    "digest": docker_images.recipes_digest(),
    "bundled": sorted(
        os.path.relpath(os.path.join(d, f), package)
        for d, _, fs in os.walk(os.path.join(package, "docker")) for f in fs
    ),
}))
"""


class Project:
    """The scratch project, and nao-sim's commands in its environment."""

    def __init__(self, root: Path):
        self.root = root
        self.bin = root / ".venv" / "bin"

    def env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        # Neither this checkout's venv nor a image data folder set for the test run leaks in.
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("VIRTUAL_ENV", "NAO_SIM_IMAGE_DATA")
        }
        return {**env, **(extra or {})}

    def run(
        self, *args: str, env: dict[str, str] | None = None, timeout: float = 120
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.bin / args[0]), *args[1:]],
            cwd=self.root,
            env=self.env(env),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def where(self, env: dict[str, str] | None = None) -> dict:
        res = self.run("python", "-c", _WHERE, env=env)
        assert res.returncode == 0, res.stderr
        return json.loads(res.stdout)


@pytest.fixture(scope="module")
def project(tmp_path_factory) -> Project:
    uv = shutil.which("uv")
    if uv is None:
        unavailable("uv is not installed")
    root = tmp_path_factory.mktemp("scratch")
    (root / "pyproject.toml").write_text(PYPROJECT.format(repo=REPO))
    project = Project(root)
    res = subprocess.run(
        # A path dependency's wheel is cached by uv: rebuild it from the checkout as it is now.
        [uv, "sync", "--python", "3.12", "--reinstall-package", "nao-sim"],
        cwd=root,
        env=project.env(),
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    assert res.returncode == 0, res.stderr[-3000:]
    return project


def test_the_package_carries_the_recipes_and_no_image_data(project):
    where = project.where()

    assert where["installed"]
    assert not Path(where["package"]).is_relative_to(REPO)
    assert where["recipes"] == str(Path(where["package"]) / "docker")
    assert {
        "docker/compose.yaml",
        "docker/Dockerfile.naoqi-2.1",
        "docker/Dockerfile.naoqi-2.8",
        "docker/entrypoint-lib.sh",
        "docker/modules/nao_sim_tts_core.py",
        "docker/tts/server.py",
    } <= set(where["bundled"])
    assert not any(
        "image-data" in path or path.endswith(".pyc") for path in where["bundled"]
    )


def test_the_installed_recipes_are_the_checkouts(project):
    # The same digest: images a checkout built are current for the installed package.
    assert project.where()["digest"] == docker_images.recipes_digest()


def test_the_image_data_goes_to_the_user_data_directory(project):
    user_data = Path(platformdirs.user_data_dir("nao-sim", appauthor=False))

    assert project.where()["image_data"] == str(user_data / "image-data")
    assert project.where({"NAO_SIM_IMAGE_DATA": str(IMAGE_DATA)})["image_data"] == str(
        IMAGE_DATA.resolve()
    )


def test_the_project_has_both_commands(project):
    for command in (("nao-sim", "--help"), ("nao-viewer", "fetch-meshes", "--help")):
        res = project.run(*command)
        assert res.returncode == 0, res.stdout + res.stderr


def test_nao_sim_run_from_the_project(project, nao, tmp_path):
    config = tmp_path / "sim.json"
    config.write_text(json.dumps(live_config(nao.version.name).to_dict()))
    shared = {
        "NAO_SIM_IMAGE_DATA": str(IMAGE_DATA)
    }  # the images this checkout built and verified
    check = project.run(
        "python",
        "-c",
        f"from nao_sim import check_images; check_images({nao.version.name!r})",
        env=shared,
    )
    assert check.returncode == 0, check.stderr

    nao.stop()
    run = subprocess.Popen(
        [str(project.bin / "nao-sim"), "run", "--config", str(config)],
        cwd=project.root,
        env=project.env(shared),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        assert run.stdout is not None
        lines = []
        for line in run.stdout:
            lines.append(line)
            if "ready at tcp://127.0.0.1:9559 (Ctrl-C to stop)" in line:
                break
        else:
            pytest.fail(
                f"nao-sim run exited ({run.wait()}) without being ready:\n{''.join(lines)}"
            )
        status = project.run("nao-sim", "status", env=shared)
        assert status.returncode == 0, status.stdout + status.stderr
        assert "ready: true" in status.stdout
        run.send_signal(signal.SIGINT)
        assert run.wait(timeout=120) == 0
    finally:
        if run.poll() is None:
            run.kill()
            run.wait()
            project.run("nao-sim", "cleanup", env=shared)
        nao.start()
