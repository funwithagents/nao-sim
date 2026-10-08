"""Fetch the pinned Choregraphe suites into docker/vendor/, where the NAOqi images are built from.

The suites are Aldebaran's software, downloaded from Aldebaran's own GitHub repositories (Git
LFS) to this machine only: they stay in the gitignored docker/vendor/ and in locally built
images, never in the repository or a pushed image. The pinned hashes are docker/suite-*.sha256.

A suite already in docker/vendor/ with the pinned hash is kept, so the command is cheap to
re-run. A file with the suite's name but another hash (a Git LFS pointer, a truncated copy) is
an error and is left alone. Downloads go to `<file>.part`, are hashed on the fly and only take
the final name once the hash matches.
"""

import argparse
import hashlib
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

DOCKER = Path(__file__).resolve().parents[2] / "docker"
VENDOR = DOCKER / "vendor"
CHUNK = 1 << 20

# Git LFS files are served from media.githubusercontent.com; the raw URL returns the pointer.
URLS = {
    "2.1": "https://media.githubusercontent.com/media/aldebaran/NAO-V5-ressources/main/Choregraphe/Linux/Binaries/",
    "2.8": "https://media.githubusercontent.com/media/aldebaran/nao6-binaries/master/",
}


class SuiteError(Exception):
    pass


@dataclass(frozen=True)
class Suite:
    version: str
    url: str
    filename: str
    sha256: str


def _load(version: str) -> Suite:
    """The suite pinned in docker/suite-<version>.sha256 (`<sha256>  <filename>`)."""
    sha256, filename = (DOCKER / f"suite-{version}.sha256").read_text().split()
    return Suite(version, URLS[version] + filename, filename, sha256)


SUITES = {v: _load(v) for v in URLS}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def fetch(suite: Suite, vendor: Path = VENDOR) -> Path:
    """Make sure `vendor` holds the pinned suite; download it if absent. Returns its path."""
    dest = vendor / suite.filename
    if dest.exists():
        if _sha256(dest) != suite.sha256:
            raise SuiteError(
                f"{dest} is not the pinned suite (SHA-256 mismatch; a Git LFS pointer or a "
                "partial copy?). Delete it to download it again."
            )
        _log(f"NAOqi {suite.version}: {dest.name} already present")
        return dest
    vendor.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    _log(f"NAOqi {suite.version}: downloading {suite.url}")
    try:
        with urllib.request.urlopen(suite.url) as r, part.open("wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done, shown = 0, -1
            while chunk := r.read(CHUNK):
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if total and (pct := done * 100 // total) // 10 != shown:
                    shown = pct // 10
                    _log(f"  {pct}% of {total // 1_000_000} MB")
        if h.hexdigest() != suite.sha256:
            raise SuiteError(
                f"{suite.url}: downloaded file has SHA-256 {h.hexdigest()}, expected {suite.sha256}"
            )
        part.rename(dest)
    finally:
        part.unlink(missing_ok=True)
    _log(f"NAOqi {suite.version}: {dest} verified")
    return dest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Download the pinned Choregraphe suites (Aldebaran's software, from Aldebaran's "
        "GitHub repositories) into docker/vendor/, verifying their SHA-256."
    )
    ap.add_argument("versions", nargs="*", help=f"{', '.join(SUITES)} (default: all)")
    ap.add_argument("--vendor", type=Path, default=VENDOR, help="default: %(default)s")
    a = ap.parse_args(argv)
    if unknown := [v for v in a.versions if v not in SUITES]:
        ap.error(
            f"unknown version(s) {', '.join(unknown)}; choose from {', '.join(SUITES)}"
        )
    try:
        for v in a.versions or SUITES:
            fetch(SUITES[v], a.vendor)
    except (SuiteError, OSError) as e:
        _log(f"error: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
