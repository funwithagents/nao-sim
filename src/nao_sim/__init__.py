"""nao-sim: a NAO in a box. The front door re-exports what a caller needs."""

from nao_sim.docker_images import check_images, fetch_and_build_images
from nao_sim.errors import (
    BootError,
    DockerUnavailableError,
    FetchError,
    ImageBuildError,
    ImagesMissingError,
    ImagesOutdatedError,
    NaoSimError,
    PortInUseError,
)

__all__ = [
    "BootError",
    "DockerUnavailableError",
    "FetchError",
    "ImageBuildError",
    "ImagesMissingError",
    "ImagesOutdatedError",
    "NaoSimError",
    "PortInUseError",
    "check_images",
    "fetch_and_build_images",
]
