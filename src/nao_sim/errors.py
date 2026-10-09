"""nao-sim's own errors, shared by its modules. Each message says what to do about it."""


class NaoSimError(RuntimeError):
    """The base of nao-sim's own errors."""


class NotRunningError(NaoSimError):
    """A `NaoSim` member that needs it running was used before `start()` or after `stop()`."""


class DockerUnavailableError(NaoSimError):
    """Docker is not installed or does not answer."""


class PortInUseError(NaoSimError):
    """A port nao-sim needs is taken (another nao-sim, a stack or audio output started by hand)."""


class ImagesMissingError(NaoSimError):
    """A version's images are not built, or were not verified by `fetch_and_build_images`."""


class ImagesOutdatedError(NaoSimError):
    """A version's images were built by another nao-sim version: their override modules are stale."""


class MissingExtraError(NaoSimError):
    """The config needs an optional dependency that is not installed (`nao-sim[viewer]`)."""


class DeviceNotBuiltError(NaoSimError):
    """The config asks for a host device source that is not built yet."""


class BootError(NaoSimError):
    """The NAOqi container exited, turned unhealthy or was not healthy in time."""


class FetchError(NaoSimError):
    """A vendor file could not be fetched or does not have its pinned hash."""


class ImageBuildError(NaoSimError):
    """`docker compose build` failed."""
