"""Where nao-sim's files are (specs/runtime/api.md, "Files on disk").

The recipes (Dockerfiles, compose, entrypoints, the override modules, the tts engine) are the
package's own `docker/` when it is installed from a wheel, as a git dependency is, and the
checkout's `docker/` otherwise: the editable install of a checkout has no package data. The vendor
files (Aldebaran's suites and `animations.pkg`, with `hashes.json` and `images.json`) are in
`NAO_SIM_VENDOR` when it is set, else in the checkout's `docker/vendor/`, or in the user data
directory when installed: never inside the package.

Every compose call gets the vendor folder as `NAO_SIM_VENDOR`, which compose turns into the
`vendor` build context of each NAOqi image (`COPY --from=vendor`).
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import platformdirs

ENV = "NAO_SIM_VENDOR"


@dataclass(frozen=True)
class Files:
    recipes: Path
    vendor: Path
    installed: bool


def locate(package: Path, environ: Mapping[str, str], user_data: Path) -> Files:
    """The recipes and the vendor folder of the `nao_sim` package in `package`."""
    bundled = package / "docker"
    installed = (bundled / "compose.yaml").is_file()
    recipes = bundled if installed else package.parents[1] / "docker"
    if environ.get(ENV):
        vendor = Path(environ[ENV]).expanduser().resolve()
    elif installed:
        vendor = user_data / "vendor"
    else:
        vendor = recipes / "vendor"
    return Files(recipes, vendor, installed)


_FILES = locate(
    Path(__file__).resolve().parent,
    os.environ,
    Path(platformdirs.user_data_dir("nao-sim", appauthor=False)),
)
RECIPES = _FILES.recipes
VENDOR = _FILES.vendor
INSTALLED = _FILES.installed


def compose_env(vendor: Path = VENDOR) -> dict[str, str]:
    """The environment of a compose call: this process's, with the vendor folder."""
    return {**os.environ, ENV: str(vendor.resolve())}
