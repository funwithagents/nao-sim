import hashlib
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from nao_sim import suite
from nao_sim.suite import SUITES, Suite, SuiteError, fetch, main

PAYLOAD = b"not really a suite\n" * 100_000  # ~1.9 MB: several chunks
DOCKER = Path(__file__).resolve().parent.parent / "docker"


class Origin:
    """A local stand-in for media.githubusercontent.com serving one file, counting requests."""

    def __init__(self, body: bytes):
        origin = self
        self.requests = 0

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                origin.requests += 1
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/suite.tar.gz"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def origin():
    o = Origin(PAYLOAD)
    yield o
    o.close()


def pinned(url: str, body: bytes = PAYLOAD) -> Suite:
    return Suite("2.1", url, "suite.tar.gz", hashlib.sha256(body).hexdigest())


def test_downloads_and_verifies_into_vendor(origin, tmp_path):
    vendor = tmp_path / "vendor"  # created on demand
    path = fetch(pinned(origin.url), vendor)
    assert path == vendor / "suite.tar.gz"
    assert path.read_bytes() == PAYLOAD
    assert sorted(p.name for p in vendor.iterdir()) == ["suite.tar.gz"]  # no .part left


def test_keeps_a_suite_already_present(origin, tmp_path):
    s = pinned(origin.url)
    fetch(s, tmp_path)
    fetch(s, tmp_path)
    assert origin.requests == 1


def test_rejects_a_download_with_the_wrong_hash(origin, tmp_path):
    with pytest.raises(SuiteError, match="SHA-256"):
        fetch(pinned(origin.url, b"something else"), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_leaves_a_mismatching_local_file_alone(origin, tmp_path):
    lfs_pointer = b"version https://git-lfs.github.com/spec/v1\noid sha256:...\n"
    (tmp_path / "suite.tar.gz").write_bytes(lfs_pointer)
    with pytest.raises(SuiteError, match="Delete it"):
        fetch(pinned(origin.url), tmp_path)
    assert (tmp_path / "suite.tar.gz").read_bytes() == lfs_pointer
    assert origin.requests == 0


def test_cli_fetches_the_named_version_and_reports_failures(
    origin, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(suite, "SUITES", {"2.1": pinned(origin.url)})
    assert main(["2.1", "--vendor", str(tmp_path)]) == 0
    assert (tmp_path / "suite.tar.gz").read_bytes() == PAYLOAD

    (tmp_path / "suite.tar.gz").write_bytes(b"corrupt")
    assert main(["--vendor", str(tmp_path)]) == 1
    assert "error:" in capsys.readouterr().err

    with pytest.raises(SystemExit):
        main(["3.0", "--vendor", str(tmp_path)])


@pytest.mark.parametrize("version", ["2.1", "2.8"])
def test_pinned_suite_is_the_one_the_dockerfile_builds_from(version):
    s = SUITES[version]
    dockerfile = (DOCKER / f"Dockerfile.naoqi-{version}").read_text()
    assert re.search(rf"^ARG SUITE={re.escape(s.filename)}$", dockerfile, re.MULTILINE)
    assert s.url.startswith("https://media.githubusercontent.com/media/aldebaran/")
    assert s.url.endswith("/" + s.filename)
    assert re.fullmatch(r"[0-9a-f]{64}", s.sha256)
