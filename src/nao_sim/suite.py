"""Fetch what the NAOqi images are built from into docker/vendor/<version>/: the pinned
Choregraphe suite, and the robot's `animations` package extracted from the public robot image.

These are Aldebaran's files, downloaded from Aldebaran's own GitHub repositories (Git LFS) to
this machine only: they stay in the gitignored docker/vendor/ and in locally built images, never
in the repository or a pushed image.

A file already there with the pinned hash is kept, so the command is cheap to re-run. A file with
the expected name but another hash (a Git LFS pointer, a truncated copy) is an error and is left
alone. Downloads and extractions go to `<file>.part`, are hashed on the fly and only take the
final name once the hash matches.

The robot image (`.opn`) is a 4096-byte `ALDIMAGE` header, an installer shell script whose
variables locate the payload, then the compressed ext3 root filesystem (bzip2 on 2.1, gzip on
2.8). It is decompressed here and streamed into a throwaway Alpine container, whose `debugfs`
writes the package to stdout: no ext3 tooling or mount is needed on the host.
"""

import argparse
import bz2
import hashlib
import re
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
import zlib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[2] / "docker" / "vendor"
CHUNK = 1 << 20
PACKAGE = "animations.pkg"

# Git LFS files are served from media.githubusercontent.com; the raw URL returns the pointer.
_V5 = "https://media.githubusercontent.com/media/aldebaran/NAO-V5-ressources/main/"
_V6 = "https://media.githubusercontent.com/media/aldebaran/nao6-binaries/master/"


class SuiteError(Exception):
    pass


@dataclass(frozen=True)
class VendorFile:
    url: str
    sha256: str

    @property
    def filename(self) -> str:
        return urllib.parse.unquote(self.url.rsplit("/", 1)[1])


@dataclass(frozen=True)
class Version:
    name: str
    suite: VendorFile
    image: VendorFile  # the robot system image the package is extracted from
    package_path: str  # animations.pkg inside the image's root filesystem
    package_sha256: str


VERSIONS = {
    "2.1": Version(
        "2.1",
        VendorFile(
            _V5
            + "Choregraphe/Linux/Binaries/choregraphe-suite-2.1.4.13-linux64.tar.gz",
            "bad0212956e2223f36736cff33bdc1e008311b8bf9efd81a52dcf05895c8abce",
        ),
        VendorFile(
            _V5
            + "NAOqi%202.1.4.13/NAOqi%20Images/opennao-atom-system-image-2.1.4.13_2015-08-27.opn",
            "5d18427ba6f5199d30cf29941b20ad5fa6a06b8f64a29126953cdfa33dbb9a24",
        ),
        "/usr/share/naoqi/apps/animations.pkg",  # version 5.0.9
        "a1d46221f5f28b91c8e7564ade4532f390e5911f14210787b3352a84c2b507e1",
    ),
    "2.8": Version(
        "2.8",
        VendorFile(
            _V6 + "choregraphe-suite-2.8.7.4-linux64.tar.gz",
            "edf95da2ae8ec7573e3a590b6db47a472f9d2733280a4a597841fbf0c1e6c63c",
        ),
        VendorFile(
            _V6 + "nao-x86-2.8.7.4_20210820_094013.opn",
            "d82e5dd221712555f20c430f3ebcbe46825d5179f1bc0e2594629489855e24a4",
        ),
        "/opt/aldebaran/share/naoqi/apps/animations.pkg",  # version 7.0.3
        "8866ddf4bb45eab79068cfe5746c66f3b8f507356fd93affed204bc834002f2c",
    ),
}


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _present(path: Path, sha256: str) -> bool:
    """True if `path` holds the pinned file, False if absent; any other file is an error."""
    if not path.exists():
        return False
    if _sha256(path) != sha256:
        raise SuiteError(
            f"{path} is not the pinned file (SHA-256 mismatch; a Git LFS pointer or a "
            "partial copy?). Delete it to fetch it again."
        )
    _log(f"{path.name}: already present")
    return True


def _write(chunks: Iterable[bytes], dest: Path, sha256: str, source: str) -> None:
    """Write `chunks` to `<dest>.part`, then rename it to `dest` if its hash is `sha256`."""
    part = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    try:
        with part.open("wb") as f:
            for chunk in chunks:
                f.write(chunk)
                h.update(chunk)
        if h.hexdigest() != sha256:
            raise SuiteError(
                f"{source}: got SHA-256 {h.hexdigest()}, expected {sha256}"
            )
        part.rename(dest)
    finally:
        part.unlink(missing_ok=True)
    _log(f"{dest} verified")


def _download(url: str) -> Iterator[bytes]:
    with urllib.request.urlopen(url) as r:
        total = int(r.headers.get("Content-Length") or 0)
        done, shown = 0, -1
        while chunk := r.read(CHUNK):
            yield chunk
            done += len(chunk)
            if total and (pct := done * 100 // total) // 10 != shown:
                shown = pct // 10
                _log(f"  {pct}% of {total // 1_000_000} MB")


def fetch_file(f: VendorFile, folder: Path) -> Path:
    """Make sure `folder` holds the pinned file; download it if absent. Returns its path."""
    dest = folder / f.filename
    if not _present(dest, f.sha256):
        folder.mkdir(parents=True, exist_ok=True)
        _log(f"downloading {f.url}")
        _write(_download(f.url), dest, f.sha256, f.url)
    return dest


@dataclass(frozen=True)
class OpnPayload:
    offset: int
    length: int
    compression: str  # "bzip2" or "gzip"


_MAGIC = {"bzip2": b"BZh", "gzip": b"\x1f\x8b"}


def opn_payload(opn: Path) -> OpnPayload:
    """Where a robot image's compressed root filesystem is, from its installer's variables."""
    with opn.open("rb") as f:
        head = f.read(4096 + 128 * 1024)
        if not head.startswith(b"ALDIMAGE"):
            raise SuiteError(f"{opn} is not a NAO robot image (no ALDIMAGE header)")
        found = dict(
            re.findall(
                rb'^(MAGIC_SIZE|SIZE_BASE|INSTALLER_SIZE|IMAGE_CMP_SIZE)="?(\d+)"?\s*$',
                head,
                re.MULTILINE,
            )
        )
        try:
            magic, base, installer, size = (
                int(found[k])
                for k in (
                    b"MAGIC_SIZE",
                    b"SIZE_BASE",
                    b"INSTALLER_SIZE",
                    b"IMAGE_CMP_SIZE",
                )
            )
        except KeyError as e:
            raise SuiteError(
                f"{opn}: installer variable {e.args[0].decode()} not found"
            ) from None
        offset = magic + installer * base
        f.seek(offset)
        start = f.read(3)
    for compression, m in _MAGIC.items():
        if start.startswith(m):
            return OpnPayload(offset, size * base, compression)
    raise SuiteError(f"{opn}: unknown compression at byte {offset} ({start.hex()})")


def rootfs_chunks(opn: Path) -> Iterator[bytes]:
    """The robot image's root filesystem, decompressed (concatenated streams included)."""
    p = opn_payload(opn)
    magic = _MAGIC[p.compression]

    def new():
        return (
            bz2.BZ2Decompressor()
            if p.compression == "bzip2"
            else zlib.decompressobj(31)
        )

    d = None
    pending = b""
    with opn.open("rb") as f:
        f.seek(p.offset)
        left = p.length
        while left > 0 and (data := f.read(min(CHUNK, left))):
            left -= len(data)
            data = pending + data
            pending = b""
            while data:
                if (
                    d is None
                ):  # between streams: another one, or the padding after the last
                    if len(data) < len(magic):
                        pending = data
                        break
                    if not data.startswith(magic):
                        return
                    d = new()
                if out := d.decompress(data):
                    yield out
                if not d.eof:
                    break
                data = d.unused_data
                d = None
    if d is not None:
        raise SuiteError(f"{opn}: the compressed root filesystem is truncated")


# Runs in alpine: store the filesystem streamed on stdin, then print one file of it ($0).
_DEBUGFS = 'apk add --no-cache -q e2fsprogs-extra >&2 && cat > /rootfs && debugfs -R "cat $0" /rootfs'


def docker_cat(rootfs: Iterable[bytes], path: str) -> Iterator[bytes]:
    """The file at `path` in the ext3 filesystem `rootfs`, read by debugfs in a throwaway container."""
    proc = subprocess.Popen(
        ["docker", "run", "-i", "--rm", "alpine:3.20", "sh", "-c", _DEBUGFS, path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    assert proc.stdin is not None and proc.stdout is not None
    stdin, stdout = proc.stdin, proc.stdout
    failed: list[Exception] = []

    def feed():
        try:
            for chunk in rootfs:
                stdin.write(chunk)
        except BrokenPipeError:
            pass
        except (SuiteError, OSError, zlib.error) as e:  # bad payload: re-raised below
            failed.append(e)
            proc.kill()
        finally:
            stdin.close()

    feeder = threading.Thread(target=feed, daemon=True)
    feeder.start()
    yield from iter(lambda: stdout.read(CHUNK), b"")
    feeder.join()
    if failed:
        raise failed[0]
    if proc.wait() != 0:
        raise SuiteError(
            f"extracting {path} with docker failed (exit {proc.returncode})"
        )


Cat = Callable[[Iterable[bytes], str], Iterable[bytes]]


def fetch(version: Version, vendor: Path = VENDOR, cat: Cat = docker_cat) -> Path:
    """Make sure `<vendor>/<version>/` holds the suite and `animations.pkg`. Returns the folder."""
    folder = vendor / version.name
    _log(f"NAOqi {version.name}")
    fetch_file(version.suite, folder)
    package = folder / PACKAGE
    if not _present(package, version.package_sha256):
        opn = folder / version.image.filename
        users = opn.exists()  # a robot image the user put there is kept
        try:
            fetch_file(version.image, folder)
            _log(f"extracting {version.package_path} from {opn.name} (needs Docker)")
            _write(
                cat(rootfs_chunks(opn), version.package_path),
                package,
                version.package_sha256,
                f"{opn.name}:{version.package_path}",
            )
        finally:
            if not users:
                opn.unlink(missing_ok=True)
    return folder


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Fetch the pinned Choregraphe suite and the robot's animations package "
        "(Aldebaran's software, from Aldebaran's GitHub repositories) into docker/vendor/<version>/, "
        "verifying their SHA-256."
    )
    ap.add_argument("versions", nargs="*", help=f"{', '.join(VERSIONS)} (default: all)")
    ap.add_argument("--vendor", type=Path, default=VENDOR, help="default: %(default)s")
    a = ap.parse_args(argv)
    if unknown := [v for v in a.versions if v not in VERSIONS]:
        ap.error(
            f"unknown version(s) {', '.join(unknown)}; choose from {', '.join(VERSIONS)}"
        )
    try:
        for v in a.versions or VERSIONS:
            fetch(VERSIONS[v], a.vendor, docker_cat)
    except (SuiteError, OSError) as e:
        _log(f"error: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
