"""The images `fetch_and_build_images` leaves behind, on each NAOqi version: labelled with this
nao-sim's version, verified, and accepted by the check a start runs."""

import json
import subprocess

from nao_sim import docker_images


def _label(tag: str) -> str | None:
    res = subprocess.run(
        ["docker", "image", "inspect", tag], capture_output=True, text=True, check=True
    )
    return (json.loads(res.stdout)[0]["Config"]["Labels"] or {}).get(
        docker_images.LABEL
    )


def test_the_images_are_built_by_this_nao_sim_and_verified(nao):
    version = docker_images.nao_sim_version()
    assert _label(nao.version.image) == version
    assert _label(docker_images.TTS_IMAGE) == version
    assert nao.container.image_env()["NAO_SIM_VERSION"] == version
    docker_images.check_images(
        nao.version.name
    )  # raises if missing, outdated or unverified
