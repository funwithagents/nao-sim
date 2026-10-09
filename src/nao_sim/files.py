"""Where nao-sim's files are (specs/runtime/api.md, "Files on disk").

The recipes (Dockerfiles, compose, entrypoints, the override modules, the tts engine) are the
package's own `docker/` when it is installed from a wheel, as a git dependency is, and the
checkout's `docker/` otherwise: the editable install of a checkout has no package data. The image data
(Aldebaran's suites and `animations.pkg`, with `hashes.json` and `images.json`) are in
`NAO_SIM_IMAGE_DATA` when it is set, else in the checkout's `docker/image-data/`, or in the user data
directory when installed: never inside the package.

Every compose call gets the image data folder as `NAO_SIM_IMAGE_DATA`, which compose turns into the
`image-data` build context of each NAOqi image (`COPY --from=image-data`).
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import platformdirs

ENV = "NAO_SIM_IMAGE_DATA"


@dataclass(frozen=True)
class Files:
    recipes: Path
    image_data: Path
    installed: bool


def locate(package: Path, environ: Mapping[str, str], user_data: Path) -> Files:
    """The recipes and the image data folder of the `nao_sim` package in `package`."""
    bundled = package / "docker"
    installed = (bundled / "compose.yaml").is_file()
    recipes = bundled if installed else package.parents[1] / "docker"
    if environ.get(ENV):
        image_data = Path(environ[ENV]).expanduser().resolve()
    elif installed:
        image_data = user_data / "image-data"
    else:
        image_data = recipes / "image-data"
    return Files(recipes, image_data, installed)


_FILES = locate(
    Path(__file__).resolve().parent,
    os.environ,
    Path(platformdirs.user_data_dir("nao-sim", appauthor=False)),
)
RECIPES = _FILES.recipes
IMAGE_DATA = _FILES.image_data
INSTALLED = _FILES.installed


def compose_env(image_data: Path = IMAGE_DATA) -> dict[str, str]:
    """The environment of a compose call: this process's, with the image data folder."""
    return {**os.environ, ENV: str(image_data.resolve())}
