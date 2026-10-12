"""The host link: framing, the hello, one connection per service, and the handler's calls."""

import io
import socket
import threading
import time

import pytest

from nao_sim.host_link import Connection, HostLink, LinkError, encode, read_message


class Recorder:
    """A device on the link: records its calls, answers a `ping` with a `pong`."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.changed = threading.Condition()

    def _add(self, *call):
        with self.changed:
            self.calls.append(call)
            self.changed.notify_all()

    def connected(self, conn: Connection) -> None:
        self._add("connected", conn)

    def message(self, conn: Connection, header: dict, payload: bytes) -> None:
        self._add("message", conn, header, payload)
        if header["type"] == "ping":
            conn.send({"type": "pong", "n": header["n"]}, payload[::-1])

    def disconnected(self, conn: Connection) -> None:
        self._add("disconnected", conn)

    def wait(self, n: int, timeout: float = 2.0) -> list[tuple]:
        with self.changed:
            assert self.changed.wait_for(lambda: len(self.calls) >= n, timeout), (
                self.calls
            )
            return list(self.calls)


@pytest.fixture
def link():
    link = HostLink(0, host="127.0.0.1")
    yield link
    link.close()


class Client:
    """A container-side service's end of the link."""

    def __init__(self, port: int, service: str | None = "ALAudioDevice"):
        self.sock = socket.create_connection(("127.0.0.1", port))
        self.rfile = self.sock.makefile("rb")
        if service is not None:
            self.send({"type": "hello", "service": service})

    def send(self, header: dict, payload: bytes = b"") -> None:
        self.sock.sendall(encode(header, payload))

    def read(self):
        return read_message(self.rfile)

    def closed_by_host(self, timeout: float = 2.0) -> bool:
        self.sock.settimeout(timeout)
        try:
            return self.sock.recv(1) == b""
        except OSError:
            return True

    def close(self):
        self.rfile.close()
        self.sock.close()


def test_framing_round_trips_headers_and_payloads():
    stream = io.BytesIO(
        encode({"type": "pcm", "samples": 4}, b"\x00\x01" * 4)
        + encode({"type": "need", "formats": []})
    )
    assert read_message(stream) == ({"type": "pcm", "samples": 4}, b"\x00\x01" * 4)
    assert read_message(stream) == ({"type": "need", "formats": []}, b"")
    assert read_message(stream) is None  # a clean end


def test_framing_is_big_endian_lengths_then_json_then_payload():
    data = encode({"type": "x"}, b"ab")
    assert data[:8] == (len(b'{"type":"x"}')).to_bytes(4, "big") + (2).to_bytes(
        4, "big"
    )
    assert data[8:] == b'{"type":"x"}ab'


@pytest.mark.parametrize(
    "data",
    [
        encode({"type": "x"}, b"abcd")[:-2],  # cut inside the payload
        (3).to_bytes(4, "big") + (0).to_bytes(4, "big") + b"{x}",  # not JSON
        encode({"no": "type"}),
        (2**30).to_bytes(4, "big") + (0).to_bytes(4, "big"),  # absurd length
    ],
)
def test_malformed_messages_are_errors(data):
    with pytest.raises(LinkError):
        read_message(io.BytesIO(data))


def test_a_service_talks_to_its_handler_both_ways(link):
    device = Recorder()
    link.register("ALAudioDevice", device)
    client = Client(link.port)
    client.send({"type": "ping", "n": 1}, b"abc")
    assert client.read() == ({"type": "pong", "n": 1}, b"cba")
    calls = device.wait(2)
    assert [c[0] for c in calls] == ["connected", "message"]
    assert calls[1][2:] == ({"type": "ping", "n": 1}, b"abc")

    client.close()
    assert device.wait(3)[2][0] == "disconnected"


def test_a_connection_that_does_not_say_hello_first_is_dropped(link):
    device = Recorder()
    link.register("ALAudioDevice", device)
    client = Client(link.port, service=None)
    client.send({"type": "ping", "n": 1})
    assert client.closed_by_host()
    time.sleep(0.1)
    assert device.calls == []


def test_a_second_hello_replaces_the_older_connection(link):
    device = Recorder()
    link.register("ALAudioDevice", device)
    first = Client(link.port)
    device.wait(1)
    second = Client(link.port)

    calls = device.wait(3)
    assert [c[0] for c in calls] == ["connected", "disconnected", "connected"]
    assert calls[0][1] is calls[1][1] and calls[2][1] is not calls[0][1]
    assert first.closed_by_host()
    second.send({"type": "ping", "n": 2})
    assert second.read() == ({"type": "pong", "n": 2}, b"")


def test_a_connection_that_came_before_the_handler_is_handed_over(link):
    client = Client(link.port)
    time.sleep(0.2)  # connected, nobody serving it yet
    device = Recorder()
    link.register("ALAudioDevice", device)
    assert device.wait(1)[0][0] == "connected"
    client.send({"type": "ping", "n": 3})
    assert client.read() == ({"type": "pong", "n": 3}, b"")


def test_close_ends_every_connection(link):
    device = Recorder()
    link.register("ALAudioDevice", device)
    client = Client(link.port)
    device.wait(1)
    link.close()
    assert client.closed_by_host()
    assert [c[0] for c in device.wait(2)] == ["connected", "disconnected"]
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", link.port), timeout=1).recv(1)
