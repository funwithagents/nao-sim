"""The `nao-sim` command: a thin shell over the library, which owns every check and step
(specs/runtime/cli.md).

A `ConfigError` prints its message and exits 2, as do argument errors (argparse); any other
`NaoSimError` exits 1. `run` exits 0 once Ctrl-C (or SIGTERM) has stopped the robot.
"""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from nao_sim import docker_images, stack
from nao_sim.config import ConfigError, NaoSimConfig
from nao_sim.errors import NaoSimError
from nao_sim.sim import NaoSim


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="nao-sim", description="A NAO in a box.")
    ap.add_argument("--verbose", action="store_true", help="debug logging")
    commands = ap.add_subparsers(dest="command", required=True)
    build = commands.add_parser(
        "fetch-and-build-images",
        help="fetch the image data, build the images and verify they boot",
        description="Fetch the pinned Choregraphe suite and the robot's animations package "
        "(Aldebaran's software, from Aldebaran's GitHub repositories, hash-checked), build "
        "the NAOqi and tts images, and verify they boot. Run once before starting nao-sim, "
        "and again after changing docker/.",
    )
    build.add_argument(
        "versions",
        nargs="*",
        metavar="VERSION",
        help=f"{', '.join(docker_images.IMAGES)} (default: all)",
    )
    build.add_argument(
        "--image-data",
        type=Path,
        default=docker_images.IMAGE_DATA,
        help="default: %(default)s",
    )
    run = commands.add_parser(
        "run",
        help="run a simulated NAO in the foreground, until Ctrl-C",
        description="Start the simulated NAO the config file describes (no file: the "
        "defaults, NAOqi 2.1 with the sim window) and keep it running until Ctrl-C.",
    )
    run.add_argument("--config", type=Path, help="a NaoSimConfig JSON file")
    commands.add_parser(
        "status",
        help="the containers and the robot's state; exits 0 when it is ready",
    )
    commands.add_parser(
        "cleanup",
        help="remove the containers a run that died without stopping left behind",
    )
    logs = commands.add_parser("logs", help="the containers' logs")
    logs.add_argument("--follow", "-f", action="store_true", help="keep following")
    logs.add_argument("--tail", type=int, metavar="N", help="only the last N lines")
    return ap


async def _run(sim: NaoSim) -> int:
    """Start, wait for Ctrl-C or SIGTERM, stop. A signal during the start cancels it."""
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    starting = asyncio.create_task(sim.start())

    def on_signal() -> None:
        if starting.done():
            stop.set()
        else:
            starting.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, on_signal)
    try:
        try:
            await starting
        except asyncio.CancelledError:
            print("start cancelled", file=sys.stderr)
            return 130
        status = await sim.status()
        print(
            f"nao-sim {status.version} on NAOqi {status.naoqi_version} ready at {sim.url} "
            "(Ctrl-C to stop)",
            flush=True,
        )
        await stop.wait()
        print("stopping", file=sys.stderr, flush=True)
        await sim.stop()
        return 0
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
        await sim.stop()  # a no-op once stopped; covers a failure after the start


def _print_status(status: stack.StackStatus) -> None:
    if not status.containers:
        print("nao-sim is not running")
        return
    for c in status.containers:
        print(f"{c.name:<20} {c.state}{f' ({c.health})' if c.health else ''}")
    if status.naoqi is None:
        print("NaoSim service: not reachable yet (the NAOqi container is not healthy)")
        return
    n = status.naoqi
    print(
        f"nao-sim {n.version} on NAOqi {n.naoqi_version}, ready: {str(n.ready).lower()}"
    )
    print(f"camera source: {n.camera_source}, audio source: {n.audio_source}")


def main(argv: list[str] | None = None) -> int:
    ap = _parser()
    a = ap.parse_args(argv)
    if unknown := [
        v for v in getattr(a, "versions", []) if v not in docker_images.IMAGES
    ]:
        ap.error(
            f"unknown version(s) {', '.join(unknown)}; choose from {', '.join(docker_images.IMAGES)}"
        )
    logging.basicConfig(
        level=logging.DEBUG if a.verbose else logging.INFO,
        format="%(message)s",
        stream=sys.stderr,
    )
    try:
        if a.command == "fetch-and-build-images":
            asyncio.run(
                docker_images.fetch_and_build_images(
                    a.versions, image_data=a.image_data
                )
            )
        elif a.command == "run":
            config = (
                NaoSimConfig.from_json_file(a.config) if a.config else NaoSimConfig()
            )
            return asyncio.run(_run(NaoSim(config)))
        elif a.command == "status":
            status = asyncio.run(stack.read_status())
            _print_status(status)
            return 0 if status.ready else 1
        elif a.command == "cleanup":
            removed = asyncio.run(stack.cleanup())
            print(f"removed {', '.join(removed)}" if removed else "nothing to remove")
        elif a.command == "logs":
            return stack.show_logs(follow=a.follow, tail=a.tail)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except NaoSimError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
