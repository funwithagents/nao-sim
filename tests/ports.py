"""Ports for the tests that name one before something binds it (naoqi-sim's fixed ports, moved).

Binding port 0, reading it and closing the socket leaves a gap before the real bind, in which the
OS may hand that port to any client connection, another worker's included (macOS picks ephemeral
ports at random). These ports come from below every OS's ephemeral range (Linux 32768 and up,
macOS and Windows 49152 and up), where no client connection lands, in a block of 500 per xdist
worker, so two workers never take the same one.
"""

import itertools
import os
import socket

_WORKER = int(os.environ.get("PYTEST_XDIST_WORKER", "gw0").removeprefix("gw") or 0)
_PORTS = itertools.count(20000 + 500 * _WORKER)


def free_port() -> int:
    """A port nothing listens on, this worker's alone (a port something else holds is skipped)."""
    for port in _PORTS:
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise AssertionError("unreachable: the count is endless")
