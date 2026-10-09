"""Where nao-sim finds its recipes and keeps the image data, in a checkout and installed as a
git dependency (specs/runtime/api.md, "Files on disk")."""

import subprocess
import sys
from pathlib import Path

from nao_sim import files
from nao_sim.files import locate

REPO = Path(__file__).resolve().parent.parent


def checkout(root: Path) -> Path:
    """A checkout: src/nao_sim/ with docker/ beside src/."""
    package = root / "src" / "nao_sim"
    package.mkdir(parents=True)
    (root / "docker").mkdir()
    (root / "docker" / "compose.yaml").write_text("name: nao-sim\n")
    return package


def installed(root: Path) -> Path:
    """An installed wheel: site-packages/nao_sim/ holding docker/ as package data."""
    package = root / "site-packages" / "nao_sim"
    (package / "docker").mkdir(parents=True)
    (package / "docker" / "compose.yaml").write_text("name: nao-sim\n")
    return package


def test_a_checkout_uses_its_docker_folder_and_its_image_data_folder(tmp_path):
    found = locate(checkout(tmp_path), {}, tmp_path / "user-data")

    assert found.recipes == tmp_path / "docker"
    assert found.image_data == tmp_path / "docker" / "image-data"
    assert not found.installed


def test_an_installed_package_reads_its_recipes_and_keeps_the_image_data_outside(
    tmp_path,
):
    package = installed(tmp_path)

    found = locate(package, {}, tmp_path / "user-data")

    assert found.recipes == package / "docker"
    assert found.image_data == tmp_path / "user-data" / "image-data"
    assert found.installed


def test_nao_sim_image_data_names_the_folder_either_way(tmp_path):
    shared = tmp_path / "shared"
    environ = {"NAO_SIM_IMAGE_DATA": str(shared)}

    assert locate(installed(tmp_path / "a"), environ, tmp_path).image_data == shared
    assert locate(checkout(tmp_path / "b"), environ, tmp_path).image_data == shared


def test_compose_gets_the_image_data_folder_as_an_absolute_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    env = files.compose_env(Path("image-data"))

    assert env["NAO_SIM_IMAGE_DATA"] == str(tmp_path.resolve() / "image-data")


def test_this_checkout_is_found_as_a_checkout():
    # The editable install has no package data: the repository's docker/ and docker/image-data/.
    assert (files.RECIPES, files.INSTALLED) == (REPO / "docker", False)


def test_nao_sim_image_data_is_read_from_the_environment(tmp_path):
    # The variable is read at import: a fresh interpreter, as a user's shell starts one.
    out = subprocess.run(
        [sys.executable, "-c", "from nao_sim import files; print(files.IMAGE_DATA)"],
        env={"NAO_SIM_IMAGE_DATA": str(tmp_path), "PATH": ""},
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == str(tmp_path.resolve())
