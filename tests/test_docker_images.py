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
from nao_sim.suite import PACKAGE, VendorFile, Version

SUITE_BODY = b"not really a suite\n"
PKG_BODY = b"not really a package\n"


@pytest.fixture
def vendor(tmp_path, monkeypatch) -> Path:
    """Vendor folders already holding pinned (fake) files, so fetching downloads nothing."""
    folder = tmp_path / "vendor"
    pinned = {}
    for name in IMAGES:
        (folder / name).mkdir(parents=True)
        (folder / name / "suite.tar.gz").write_bytes(SUITE_BODY)
        (folder / name / PACKAGE).write_bytes(PKG_BODY)
        pinned[name] = Version(
            name,
            VendorFile(
                "https://example.invalid/suite.tar.gz",
                hashlib.sha256(SUITE_BODY).hexdigest(),
            ),
            VendorFile("https://example.invalid/image.opn", "0" * 64),
            "/animations.pkg",
            hashlib.sha256(PKG_BODY).hexdigest(),
        )
    monkeypatch.setattr(suite, "VERSIONS", pinned)
    return folder


def build(*versions: str, vendor: Path) -> None:
    asyncio.run(fetch_and_build_images(versions or None, vendor=vendor))


def test_built_and_verified_images_pass_the_check(docker, vendor):
    build("2.1", vendor=vendor)

    check_images("2.1", vendor)
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
        check_images("2.8", vendor)


def test_no_versions_means_all_of_them(docker, vendor):
    build(vendor=vendor)
    check_images("2.1", vendor)
    check_images("2.8", vendor)
    assert any("--profile 2.1 build tts naoqi21" in c for c in docker.calls)
    assert any("--profile 2.8 build tts naoqi28" in c for c in docker.calls)


def test_an_image_that_does_not_boot_is_not_verified(docker, vendor):
    docker.set(boot="exited")
    with pytest.raises(BootError, match="fake log line"):
        build("2.1", vendor=vendor)

    # Built, but never recorded: a start refuses it, and nothing is left running.
    assert "nao-sim/naoqi:2.1.4.13" in docker.read()["images"]
    with pytest.raises(ImagesMissingError, match="not verified"):
        check_images("2.1", vendor)
    assert docker.read()["containers"] == {}


def test_a_container_that_never_turns_healthy_times_out(docker, vendor, monkeypatch):
    monkeypatch.setattr(docker_images, "READY_TIMEOUT", 0.05)
    docker.set(boot="starting")
    with pytest.raises(BootError, match="not healthy after"):
        build("2.1", vendor=vendor)
    assert docker.read()["containers"] == {}


def test_a_silent_tts_engine_fails_the_verification(docker, vendor, monkeypatch):
    monkeypatch.setattr(docker_images, "TTS_TIMEOUT", 0.05)
    docker.set(tts_answers=False)
    with pytest.raises(BootError, match="tts engine"):
        build("2.1", vendor=vendor)


def test_a_failed_build_says_why(docker, vendor):
    docker.set(build_fails=True)
    with pytest.raises(ImageBuildError, match="boom"):
        build("2.1", vendor=vendor)
    assert not any(" up " in c for c in docker.calls)


def test_images_rebuilt_from_changed_sources_need_a_new_verification(docker, vendor):
    build("2.1", vendor=vendor)
    # Rebuilt by hand after changing docker/modules: same tag, another image.
    docker.set(source="changed modules")
    state = docker.read()
    tag = "nao-sim/naoqi:2.1.4.13"
    state["images"][tag]["Id"] = "sha256:" + "f" * 64
    docker.write(state)
    with pytest.raises(ImagesMissingError, match="not verified"):
        check_images("2.1", vendor)

    build("2.1", vendor=vendor)
    check_images("2.1", vendor)


def test_an_edit_under_docker_makes_the_images_outdated(
    docker, vendor, tmp_path, monkeypatch
):
    recipes = tmp_path / "recipes"
    (recipes / "modules" / "__pycache__").mkdir(parents=True)
    (recipes / "vendor").mkdir()
    module = recipes / "modules" / "nao_sim_tts_core.py"
    module.write_text("# version 1\n")
    monkeypatch.setattr(docker_images, "DOCKER", recipes)
    build("2.1", vendor=vendor)

    # Vendor files, caches and hidden files are not recipes: the images stay current.
    (recipes / "vendor" / "images.json").write_text("{}")
    (recipes / "modules" / "__pycache__" / "x.pyc").write_bytes(b"cache")
    (recipes / ".DS_Store").write_bytes(b"finder")
    check_images("2.1", vendor)

    module.write_text("# version 2\n")
    with pytest.raises(ImagesOutdatedError, match="docker/ changed since"):
        check_images("2.1", vendor)
    build("2.1", vendor=vendor)
    check_images("2.1", vendor)


def test_images_from_another_nao_sim_version_are_outdated(docker, vendor, monkeypatch):
    build("2.1", vendor=vendor)
    monkeypatch.setattr(docker_images, "nao_sim_version", lambda: "9.9.9")
    with pytest.raises(
        ImagesOutdatedError, match=r"built by nao-sim .* this is nao-sim 9\.9\.9"
    ):
        check_images("2.1", vendor)


def test_missing_images_name_the_command_to_run(docker, vendor):
    with pytest.raises(
        ImagesMissingError,
        match=r"is not built: run `nao-sim fetch-and-build-images 2\.1`",
    ):
        check_images("2.1", vendor)


def test_without_docker_nothing_is_attempted(docker, vendor):
    docker.set(down=True)
    with pytest.raises(DockerUnavailableError):
        build("2.1", vendor=vendor)
    assert docker.calls == ["info"]


def test_a_taken_naoqi_port_stops_the_verification(docker, vendor):
    with socket.socket() as s:
        s.bind(("127.0.0.1", docker_images.NAOQI_PORT))
        s.listen()
        with pytest.raises(PortInUseError, match=str(docker_images.NAOQI_PORT)):
            build("2.1", vendor=vendor)
    assert not any(" up " in c for c in docker.calls)


def test_a_vendor_file_with_the_wrong_hash_stops_before_building(docker, vendor):
    (vendor / "2.1" / "suite.tar.gz").write_bytes(b"a git lfs pointer")
    with pytest.raises(FetchError, match="Delete it"):
        build("2.1", vendor=vendor)
    assert not any(c.startswith("compose") for c in docker.calls)


def test_an_unknown_version_is_refused(docker, vendor):
    with pytest.raises(ValueError, match="3.0"):
        build("3.0", vendor=vendor)


def test_the_command_reports_failures_and_exit_codes(docker, vendor, capsys):
    assert main(["fetch-and-build-images", "2.1", "--vendor", str(vendor)]) == 0
    check_images("2.1", vendor)

    docker.set(build_fails=True)
    assert main(["fetch-and-build-images", "2.1", "--vendor", str(vendor)]) == 1
    assert "error: docker compose build failed" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exit_:
        main(["fetch-and-build-images", "3.0", "--vendor", str(vendor)])
    assert exit_.value.code == 2
