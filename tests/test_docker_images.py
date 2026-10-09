"""Fetching, building and verifying the Docker images, and the check a start runs on them, against
the fake `docker` first on PATH (tests/fake_docker.py)."""

import asyncio
import hashlib
import socket
from pathlib import Path

import pytest

from nao_sim import docker_images, suite
from nao_sim.cli import main
from nao_sim.docker_images import (
    IMAGES,
    TTS_IMAGE,
    check_images,
    fetch_and_build_images,
)
from nao_sim.errors import (
    BootError,
    DockerUnavailableError,
    FetchError,
    ImageBuildError,
    ImagesMissingError,
    ImagesOutdatedError,
    PortInUseError,
)
from nao_sim.suite import PACKAGE, PinnedFile, Version

SUITE_BODY = b"not really a suite\n"
PKG_BODY = b"not really a package\n"


@pytest.fixture
def image_data(tmp_path, monkeypatch) -> Path:
    """Image data folders already holding pinned (fake) files, so fetching downloads nothing."""
    folder = tmp_path / "image-data"
    pinned = {}
    for name in IMAGES:
        (folder / name).mkdir(parents=True)
        (folder / name / "suite.tar.gz").write_bytes(SUITE_BODY)
        (folder / name / PACKAGE).write_bytes(PKG_BODY)
        pinned[name] = Version(
            name,
            PinnedFile(
                "https://example.invalid/suite.tar.gz",
                hashlib.sha256(SUITE_BODY).hexdigest(),
            ),
            PinnedFile("https://example.invalid/image.opn", "0" * 64),
            "/animations.pkg",
            hashlib.sha256(PKG_BODY).hexdigest(),
        )
    monkeypatch.setattr(suite, "VERSIONS", pinned)
    return folder


def build(*versions: str, image_data: Path) -> None:
    asyncio.run(fetch_and_build_images(versions or None, image_data=image_data))


def test_the_build_reads_the_image_data_from_the_folder_it_was_fetched_into(
    docker, image_data
):
    # The image data folder is outside the recipes (as for an installed nao-sim): compose gets it
    # as the NAOqi build's `image-data` context.
    assert not image_data.is_relative_to(docker_images.DOCKER)
    build("2.1", image_data=image_data)

    assert docker.read()["image_data_contexts"] == {
        "naoqi21": str(image_data.resolve() / "2.1")
    }
    check_images("2.1", image_data)


def test_built_and_verified_images_pass_the_check(docker, image_data):
    build("2.1", image_data=image_data)

    check_images("2.1", image_data)
    labels = {tag: image["Labels"] for tag, image in docker.read()["images"].items()}
    built = {
        "io.nao-sim.version": docker_images.nao_sim_version(),
        "io.nao-sim.recipes": docker_images.recipes_digest(),
    }
    assert labels == {"nao-sim/naoqi:2.1.4.13": built, TTS_IMAGE: built}
    # The verification boot was taken down again.
    assert docker.read()["containers"] == {}
    # 2.8 was not asked for: it is neither built nor verified.
    with pytest.raises(ImagesMissingError, match="nao-sim fetch-and-build-images 2.8"):
        check_images("2.8", image_data)


def test_no_versions_means_all_of_them(docker, image_data):
    build(image_data=image_data)
    check_images("2.1", image_data)
    check_images("2.8", image_data)
    assert any("--profile 2.1 build tts naoqi21" in c for c in docker.calls)
    assert any("--profile 2.8 build tts naoqi28" in c for c in docker.calls)


def test_an_image_that_does_not_boot_is_not_verified(docker, image_data):
    docker.set(boot="exited")
    with pytest.raises(BootError, match="fake log line"):
        build("2.1", image_data=image_data)

    # Built, but never recorded: a start refuses it, and nothing is left running.
    assert "nao-sim/naoqi:2.1.4.13" in docker.read()["images"]
    with pytest.raises(ImagesMissingError, match="not verified"):
        check_images("2.1", image_data)
    assert docker.read()["containers"] == {}


def test_a_container_that_never_turns_healthy_times_out(
    docker, image_data, monkeypatch
):
    monkeypatch.setattr(docker_images, "READY_TIMEOUT", 0.05)
    docker.set(boot="starting")
    with pytest.raises(BootError, match="not healthy after"):
        build("2.1", image_data=image_data)
    assert docker.read()["containers"] == {}


def test_a_silent_tts_engine_fails_the_verification(docker, image_data, monkeypatch):
    monkeypatch.setattr(docker_images, "TTS_TIMEOUT", 0.05)
    docker.set(tts_answers=False)
    with pytest.raises(BootError, match="tts engine"):
        build("2.1", image_data=image_data)


def test_a_failed_build_says_why(docker, image_data):
    docker.set(build_fails=True)
    with pytest.raises(ImageBuildError, match="boom"):
        build("2.1", image_data=image_data)
    assert not any(" up " in c for c in docker.calls)


def test_images_rebuilt_from_changed_sources_need_a_new_verification(
    docker, image_data
):
    build("2.1", image_data=image_data)
    # Rebuilt by hand after changing docker/modules: same tag, another image.
    docker.set(source="changed modules")
    state = docker.read()
    tag = "nao-sim/naoqi:2.1.4.13"
    state["images"][tag]["Id"] = "sha256:" + "f" * 64
    docker.write(state)
    with pytest.raises(ImagesMissingError, match="not verified"):
        check_images("2.1", image_data)

    build("2.1", image_data=image_data)
    check_images("2.1", image_data)


def test_an_edit_under_docker_makes_the_images_outdated(
    docker, image_data, tmp_path, monkeypatch
):
    recipes = tmp_path / "recipes"
    (recipes / "modules" / "__pycache__").mkdir(parents=True)
    (recipes / "image-data").mkdir()
    module = recipes / "modules" / "nao_sim_tts_core.py"
    module.write_text("# version 1\n")
    monkeypatch.setattr(docker_images, "DOCKER", recipes)
    build("2.1", image_data=image_data)

    # Image data, caches and hidden files are not recipes: the images stay current.
    (recipes / "image-data" / "images.json").write_text("{}")
    (recipes / "modules" / "__pycache__" / "x.pyc").write_bytes(b"cache")
    (recipes / ".DS_Store").write_bytes(b"finder")
    check_images("2.1", image_data)

    module.write_text("# version 2\n")
    with pytest.raises(ImagesOutdatedError, match="docker/ changed since"):
        check_images("2.1", image_data)
    build("2.1", image_data=image_data)
    check_images("2.1", image_data)


def test_images_from_another_nao_sim_version_are_outdated(
    docker, image_data, monkeypatch
):
    build("2.1", image_data=image_data)
    monkeypatch.setattr(docker_images, "nao_sim_version", lambda: "9.9.9")
    with pytest.raises(
        ImagesOutdatedError, match=r"built by nao-sim .* this is nao-sim 9\.9\.9"
    ):
        check_images("2.1", image_data)


def test_missing_images_name_the_command_to_run(docker, image_data):
    with pytest.raises(
        ImagesMissingError,
        match=r"is not built: run `nao-sim fetch-and-build-images 2\.1`",
    ):
        check_images("2.1", image_data)


def test_without_docker_nothing_is_attempted(docker, image_data):
    docker.set(down=True)
    with pytest.raises(DockerUnavailableError):
        build("2.1", image_data=image_data)
    assert docker.calls == ["info"]


def test_a_taken_naoqi_port_stops_the_verification(docker, image_data):
    with socket.socket() as s:
        s.bind(("127.0.0.1", docker_images.NAOQI_PORT))
        s.listen()
        with pytest.raises(PortInUseError, match=str(docker_images.NAOQI_PORT)):
            build("2.1", image_data=image_data)
    assert not any(" up " in c for c in docker.calls)


def test_a_pinned_file_with_the_wrong_hash_stops_before_building(docker, image_data):
    (image_data / "2.1" / "suite.tar.gz").write_bytes(b"a git lfs pointer")
    with pytest.raises(FetchError, match="Delete it"):
        build("2.1", image_data=image_data)
    assert not any(c.startswith("compose") for c in docker.calls)


def test_an_unknown_version_is_refused(docker, image_data):
    with pytest.raises(ValueError, match="3.0"):
        build("3.0", image_data=image_data)


def test_the_command_reports_failures_and_exit_codes(docker, image_data, capsys):
    assert main(["fetch-and-build-images", "2.1", "--image-data", str(image_data)]) == 0
    check_images("2.1", image_data)

    docker.set(build_fails=True)
    assert main(["fetch-and-build-images", "2.1", "--image-data", str(image_data)]) == 1
    assert "error: docker compose build failed" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exit_:
        main(["fetch-and-build-images", "3.0", "--image-data", str(image_data)])
    assert exit_.value.code == 2
