"""The host link: what the containers and the host devices exchange that qi cannot carry
(specs/host/devices.md, "The host link").

One TCP port (9563) the containers connect out to, one connection per container-side service,
each opened with a `hello` naming the service. Messages use the toolkit's framing (nao-viewer's
protocol): `u32 header_len | u32 payload_len | JSON header | raw payload`, big-endian, every header
with a `type`. The device that serves a service is registered as its handler; the device specs own
the other message types (the audio input's in specs/host/audio-input.md).
"""

import json
import logging
import socket
import socketserver
import struct
import threading
from typing import Protocol

log = logging.getLogger(__name__)

_LENGTHS = struct.Struct(">II")
MAX_HEADER = 1 << 20
MAX_PAYLOAD = 64 << 20


class Readable(Protocol):
    def read(self, n: int, /) -> bytes: ...


class LinkError(Exception):
    """A malformed message: the connection is dropped."""


def encode(header: dict, payload: bytes = b"") -> bytes:
    """One framed message."""
    head = json.dumps(header, separators=(",", ":")).encode()
    return _LENGTHS.pack(len(head), len(payload)) + head + payload


def _read_exactly(rfile: Readable, n: int) -> bytes | None:
    data = rfile.read(n)
    if not data and n:
        return None
    if len(data) != n:
        raise LinkError(f"connection closed after {len(data)} of {n} bytes")
    return data


def read_message(rfile: Readable) -> tuple[dict, bytes] | None:
    """The next message from a buffered stream, or None at a clean end of stream."""
    lengths = _read_exactly(rfile, _LENGTHS.size)
    if lengths is None:
        return None
    header_len, payload_len = _LENGTHS.unpack(lengths)
    if header_len > MAX_HEADER or payload_len > MAX_PAYLOAD:
        raise LinkError(f"message too large ({header_len} + {payload_len} bytes)")
    head = _read_exactly(rfile, header_len) or b""
    payload = _read_exactly(rfile, payload_len) or b""
    try:
        header = json.loads(head)
    except ValueError as e:
        raise LinkError(f"header is not JSON: {e}") from None
    if not isinstance(header, dict) or not isinstance(header.get("type"), str):
        raise LinkError("header without a type")
    return header, payload


class Connection:
    """One container-side service's connection; `send` may be called from any thread."""

    def __init__(self, sock: socket.socket, service: str):
        self.service = service
        self._sock = sock
        self._lock = threading.Lock()
        self.closed = False

    def send(self, header: dict, payload: bytes = b"") -> bool:
        """Send one message; False if the connection is gone."""
        data = encode(header, payload)
        with self._lock:
            if self.closed:
                return False
            try:
                self._sock.sendall(data)
                return True
            except OSError:
                self.closed = True
                return False

    def close(self) -> None:
        with self._lock:
            self.closed = True
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


class Handler(Protocol):
    """The device serving one container-side service. Its calls never overlap (they run under the
    link's lock, so they must be quick), and `disconnected(old)` comes before `connected(new)`."""

    def connected(self, conn: Connection) -> None: ...

    def message(self, conn: Connection, header: dict, payload: bytes) -> None: ...

    def disconnected(self, conn: Connection) -> None: ...


class HostLink:
    """The host side: listens on `port`, hands each service's connection to its handler."""

    def __init__(self, port: int, host: str = "0.0.0.0"):
        self._handlers: dict[str, Handler] = {}
        self._current: dict[str, Connection] = {}
        self._lock = threading.RLock()
        self._closing = False
        link = self

        class _Request(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                link._serve(self.request, self.rfile)

        class _Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._server = _Server((host, port), _Request)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="nao-sim-host-link", daemon=True
        )
        self._thread.start()

    def register(self, service: str, handler: Handler) -> None:
        """Serve `service`'s connections with `handler` (one already open is handed over now)."""
        with self._lock:
            self._handlers[service] = handler
            conn = self._current.get(service)
            if conn is not None:
                handler.connected(conn)

    def close(self) -> None:
        """Stop listening and drop every connection."""
        with self._lock:
            self._closing = True
            conns = list(self._current.items())
            self._current.clear()
        for service, conn in conns:
            conn.close()
            handler = self._handlers.get(service)
            if handler is not None:
                handler.disconnected(conn)
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def _serve(self, sock: socket.socket, rfile: Readable) -> None:
        try:
            first = read_message(rfile)
        except LinkError as e:
            log.warning("host link: dropped a connection: %s", e)
            return
        if first is None:
            return
        header, _ = first
        service = header.get("service")
        if header["type"] != "hello" or not isinstance(service, str):
            log.warning("host link: dropped a connection that did not say hello first")
            return
        conn = Connection(sock, service)
        with self._lock:
            if self._closing:
                return
            old = self._current.get(service)
            if (
                old is not None
            ):  # a second hello for the service replaces the older connection
                old.close()
            self._current[service] = conn
            handler = self._handlers.get(service)
            if old is not None and handler is not None:
                handler.disconnected(old)
            if handler is not None:
                handler.connected(conn)
        log.debug("host link: %s connected", service)
        try:
            while (msg := read_message(rfile)) is not None:
                with (
                    self._lock
                ):  # so a replaced connection's message never follows its end
                    handler = self._handlers.get(service)
                    if handler is not None and self._current.get(service) is conn:
                        handler.message(conn, *msg)
        except (LinkError, OSError) as e:
            log.warning("host link: %s: %s", service, e)
        finally:
            conn.closed = True
            with self._lock:
                if self._current.get(service) is conn:
                    del self._current[service]
                    handler = self._handlers.get(service)
                    if handler is not None:
                        handler.disconnected(conn)
            log.debug("host link: %s disconnected", service)
