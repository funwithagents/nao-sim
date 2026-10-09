"""The `nao-sim` command: a thin shell over the library, which owns every check and step.

A `NaoSimError` prints its message and exits 1; argument errors exit 2 (argparse).
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from nao_sim import docker_images
from nao_sim.errors import NaoSimError


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="nao-sim", description="A NAO in a box.")
    ap.add_argument("--verbose", action="store_true", help="debug logging")
    commands = ap.add_subparsers(dest="command", required=True)
    build = commands.add_parser(
        "fetch-and-build-images",
        help="fetch the vendor files, build the images and verify they boot",
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
        "--vendor", type=Path, default=docker_images.VENDOR, help="default: %(default)s"
    )
    return ap


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
                docker_images.fetch_and_build_images(a.versions, vendor=a.vendor)
            )
    except NaoSimError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
