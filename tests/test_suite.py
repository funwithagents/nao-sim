import bz2
import gzip
import hashlib
import re
import threading
from collections.abc import Callable, Iterable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from nao_sim.errors import FetchError
from nao_sim.suite import (
    PACKAGE,
    VERSIONS,
    VendorFile,
    Version,
    fetch,
    opn_payload,
    rootfs_chunks,
)

DOCKER = Path(__file__).resolve().parent.parent / "docker"
SUITE = b"not really a suite\n" * 100_000  # ~1.9 MB: several chunks
ROOTFS = bytes(range(256)) * 12_000  # ~3 MB: several chunks, compressed and not
BASE = 1024


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def make_opn(
    payload: bytes,
    compress: Callable[[bytes], bytes],
    installer_kb: int = 4,
    trailing: bytes = b"\0" * 5000,
) -> bytes:
    """A robot image laid out like Aldebaran's: header, installer script, compressed payload."""
    data = compress(payload)
    cmp_kb = -(-len(data) // BASE)
    script = (
        "#!/bin/sh\n# Set at image creation time\n"
        f'SIZE_BASE="{BASE}"\nIMAGE_CMP_SIZE="{cmp_kb}"\n'
        f'INSTALLER_SIZE="{installer_kb}"\nMAGIC_SIZE=4096\n'
    ).encode()
    return (
        b"ALDIMAGE".ljust(4096, b"\0")
        + script.ljust(installer_kb * BASE, b"\0")
        + data.ljust(cmp_kb * BASE, b"\0")
        + trailing
    )


def two_bzip2_streams(b: bytes) -> bytes:
    return bz2.compress(b[:1000]) + bz2.compress(b[1000:])


def two_gzip_members(b: bytes) -> bytes:
    return gzip.compress(b[:1000]) + gzip.compress(b[1000:])


@pytest.mark.parametrize(
    ("compress", "compression"),
    [
        (bz2.compress, "bzip2"),
        (gzip.compress, "gzip"),
        (two_bzip2_streams, "bzip2"),
        (two_gzip_members, "gzip"),
    ],
)
def test_reads_the_root_filesystem_out_of_a_robot_image(
    tmp_path, compress, compression
):
    opn = tmp_path / "nao.opn"
    opn.write_bytes(make_opn(ROOTFS, compress, installer_kb=7))
    payload = opn_payload(opn)
    assert payload.offset == 4096 + 7 * BASE
    assert payload.compression == compression
    assert b"".join(rootfs_chunks(opn)) == ROOTFS


def test_rejects_what_is_not_a_robot_image(tmp_path):
    opn = tmp_path / "nao.opn"
    opn.write_bytes(b"version https://git-lfs.github.com/spec/v1\n")
    with pytest.raises(FetchError, match="ALDIMAGE"):
        opn_payload(opn)


def test_rejects_a_truncated_robot_image(tmp_path):
    opn = tmp_path / "nao.opn"
    whole = make_opn(ROOTFS, bz2.compress, trailing=b"")
    opn.write_bytes(whole[: len(whole) // 2])
    with pytest.raises(FetchError, match="truncated"):
        b"".join(rootfs_chunks(opn))


class Origin:
    """A local stand-in for media.githubusercontent.com, counting requests per path."""

    def __init__(self, files: dict[str, bytes]):
        origin = self
        self.files = files
        self.requests: list[str] = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                origin.requests.append(self.path)
                body = origin.files[self.path]
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def echo_cat(rootfs: Iterable[bytes], path: str) -> Iterable[bytes]:
    """Stands in for debugfs in Docker: the synthetic root filesystem *is* the package."""
    return rootfs


PKG = ROOTFS  # what echo_cat yields for a robot image made from ROOTFS
OPN = make_opn(ROOTFS, bz2.compress)


@pytest.fixture
def origin():
    o = Origin({"/suite.tar.gz": SUITE, "/nao%20image.opn": OPN})
    yield o
    o.close()


def version(
    origin: Origin, package_sha256: str = sha(PKG), suite_body: bytes = SUITE
) -> Version:
    return Version(
        "2.1",
        VendorFile(f"{origin.base}/suite.tar.gz", sha(suite_body)),
        VendorFile(f"{origin.base}/nao%20image.opn", sha(OPN)),
        "/usr/share/naoqi/apps/animations.pkg",
        package_sha256,
    )


def test_fills_the_version_folder(origin, tmp_path):
    folder = fetch(version(origin), tmp_path, echo_cat)
    assert folder == tmp_path / "2.1"
    assert (folder / "suite.tar.gz").read_bytes() == SUITE
    assert (folder / PACKAGE).read_bytes() == PKG
    # The robot image it downloaded only to extract the package is gone, and nothing half-done is left.
    assert sorted(p.name for p in folder.iterdir()) == [PACKAGE, "suite.tar.gz"]


def test_downloads_nothing_when_everything_is_there(origin, tmp_path):
    fetch(version(origin), tmp_path, echo_cat)
    fetch(version(origin), tmp_path, echo_cat)
    assert len(origin.requests) == 2  # the suite and the robot image, once each


def test_uses_and_keeps_a_robot_image_the_user_put_there(origin, tmp_path):
    (tmp_path / "2.1").mkdir()
    (tmp_path / "2.1" / "nao image.opn").write_bytes(OPN)
    fetch(version(origin), tmp_path, echo_cat)
    assert origin.requests == ["/suite.tar.gz"]
    assert (tmp_path / "2.1" / "nao image.opn").exists()
    assert (tmp_path / "2.1" / PACKAGE).read_bytes() == PKG


def test_rejects_an_extracted_package_with_the_wrong_hash(origin, tmp_path):
    with pytest.raises(FetchError, match="SHA-256"):
        fetch(
            version(origin, package_sha256=sha(b"another package")), tmp_path, echo_cat
        )
    assert sorted(p.name for p in (tmp_path / "2.1").iterdir()) == ["suite.tar.gz"]


def test_rejects_a_download_with_the_wrong_hash(origin, tmp_path):
    with pytest.raises(FetchError, match="SHA-256"):
        fetch(version(origin, suite_body=b"something else"), tmp_path, echo_cat)
    assert list((tmp_path / "2.1").iterdir()) == []


def test_leaves_a_mismatching_local_file_alone(origin, tmp_path):
    lfs_pointer = b"version https://git-lfs.github.com/spec/v1\noid sha256:...\n"
    (tmp_path / "2.1").mkdir()
    (tmp_path / "2.1" / "suite.tar.gz").write_bytes(lfs_pointer)
    with pytest.raises(FetchError, match="Delete it"):
        fetch(version(origin), tmp_path, echo_cat)
    assert (tmp_path / "2.1" / "suite.tar.gz").read_bytes() == lfs_pointer
    assert origin.requests == []


@pytest.mark.parametrize("name", ["2.1", "2.8"])
def test_the_dockerfile_builds_from_the_fetched_files(name):
    v = VERSIONS[name]
    dockerfile = (DOCKER / f"Dockerfile.naoqi-{name}").read_text()
    assert re.search(
        rf"^ARG SUITE={re.escape(v.suite.filename)}$", dockerfile, re.MULTILINE
    )
    assert f"COPY vendor/{name}/${{SUITE}} " in dockerfile
    assert (
        f"COPY vendor/{name}/{PACKAGE} /opt/naoqi/share/naoqi/apps/{PACKAGE}"
        in dockerfile
    )
    for f in (v.suite, v.image):
        assert f.url.startswith("https://media.githubusercontent.com/media/aldebaran/")
        assert re.fullmatch(r"[0-9a-f]{64}", f.sha256)
