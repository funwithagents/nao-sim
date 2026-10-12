"""The ALAudioDevice replacement's shared logic, against a real host link.

The host side is `nao_sim.host_link.HostLink` with a recording handler, so the two framings are
tested against each other; the relay's `deliver` is a fake that records what each subscriber gets.
"""

import threading
import time

import nao_sim_audiodevice_core as core
import pytest

from nao_sim.host_link import Connection, HostLink


class Host:
    """The host end: remembers the last need, sends what a test asks for."""

    def __init__(self):
        self.needs: list[dict] = []
        self.conn: Connection | None = None
        self.changed = threading.Condition()

    def connected(self, conn: Connection) -> None:
        with self.changed:
            self.conn = conn
            self.changed.notify_all()

    def message(self, conn: Connection, header: dict, payload: bytes) -> None:
        with self.changed:
            if header["type"] == "need":
                self.needs.append(header)
            self.changed.notify_all()

    def disconnected(self, conn: Connection) -> None:
        with self.changed:
            if self.conn is conn:
                self.conn = None
            self.changed.notify_all()

    def wait_need(self, predicate, timeout: float = 2.0) -> dict:
        with self.changed:
            assert self.changed.wait_for(
                lambda: bool(self.needs) and predicate(self.needs[-1]), timeout
            ), self.needs
            return self.needs[-1]

    def pcm(self, fmt: tuple, channels: int, samples: int, payload: bytes) -> None:
        assert self.conn is not None
        self.conn.send(
            {
                "type": "pcm",
                "format": core.format_header(fmt),
                "channels": channels,
                "samples": samples,
            },
            payload,
        )


class Relay:
    """Stands in for _NaoSimAudioRelay: records each delivery per subscriber."""

    def __init__(self):
        self.got: dict[str, list[tuple]] = {}
        self.block: set[str] = set()
        self.fail: set[str] = set()
        self.forgotten: list[str] = []
        self.release = threading.Event()
        self.changed = threading.Condition()

    def deliver(self, name, channels, samples, stamp, buffer):
        if name in self.block:
            self.release.wait(5)
        if name in self.fail:
            raise RuntimeError("subscriber gone")
        with self.changed:
            self.got.setdefault(name, []).append((channels, samples, stamp, buffer))
            self.changed.notify_all()

    def wait(self, name: str, n: int, timeout: float = 2.0) -> list[tuple]:
        with self.changed:
            assert self.changed.wait_for(
                lambda: len(self.got.get(name, [])) >= n, timeout
            ), self.got
            return list(self.got[name])


SERVICES = {"Front", "Front2", "All", "Slow", "Gone"}
FRONT = (16000, "front", False)
ALL = (48000, "all", False)


@pytest.fixture
def link():
    host = Host()
    link = HostLink(0, host="127.0.0.1")
    link.register(core.SERVICE, host)
    yield link, host
    link.close()


@pytest.fixture
def device(link, monkeypatch):
    monkeypatch.setattr(core, "RETRY_S", 0.05)
    hostlink, host = link
    relay = Relay()
    dev = core.AudioDevice(
        relay.deliver,
        exists=lambda name: name in SERVICES,
        forget=relay.forgotten.append,
        address=f"127.0.0.1:{hostlink.port}",
        log=lambda msg: None,
    )
    assert dev.link.connected.wait(2)
    yield dev, host, relay
    dev.close()


@pytest.mark.parametrize(
    ("args", "fmt"),
    [
        ((48000, 0, 0), (48000, "all", False)),
        ((48000, 0, 1), (48000, "all", True)),
        ((16000, 1, 0), (16000, "left", False)),
        ((16000, 2, 0), (16000, "right", False)),
        (
            (16000, 3, 1),
            (16000, "front", False),
        ),  # deinterleaving one channel means nothing
        ((16000, 4, 0), (16000, "rear", False)),
    ],
)
def test_the_formats_naoqi_documents(args, fmt):
    assert core.parse_preferences(*args) == fmt


@pytest.mark.parametrize(
    "args", [(48000, 3, 0), (16000, 0, 0), (44100, 0, 0), (16000, 5, 0), (8000, 3, 0)]
)
def test_other_formats_are_refused(args):
    with pytest.raises(ValueError):
        core.parse_preferences(*args)


def test_the_need_follows_the_subscribers(device):
    dev, host, _ = device
    assert host.wait_need(lambda n: True) == {
        "type": "need",
        "formats": [],
        "energy": False,
    }

    dev.subscribe("All")  # no preferences: 48 kHz, all channels, interleaved
    dev.set_preferences("Front", 16000, 3, 0)
    dev.subscribe("Front")
    dev.set_preferences("Front2", 16000, 3, 0)
    dev.subscribe("Front2")
    need = host.wait_need(lambda n: len(n["formats"]) == 2)
    assert need["formats"] == [core.format_header(FRONT), core.format_header(ALL)]

    dev.unsubscribe("Front")
    dev.unsubscribe("All")
    assert host.wait_need(lambda n: len(n["formats"]) == 1)["formats"] == [
        core.format_header(FRONT)
    ]
    dev.unsubscribe("Front2")
    host.wait_need(lambda n: n["formats"] == [])
    dev.enable_energy()
    assert host.wait_need(lambda n: n["energy"]) == {
        "type": "need",
        "formats": [],
        "energy": True,
    }


def test_preferences_apply_at_the_next_subscribe(device):
    dev, _, _ = device
    dev.subscribe("Front")
    dev.set_preferences("Front", 16000, 3, 0)
    assert dev.subscribers() == {"Front": ALL}
    dev.unsubscribe("Front")
    dev.subscribe("Front")
    assert dev.subscribers() == {"Front": FRONT}
    with pytest.raises(ValueError):
        dev.set_preferences("Front", 44100, 3, 0)
    dev.unsubscribe("Front")
    dev.subscribe("Front")
    assert dev.subscribers() == {"Front": FRONT}  # the refused call changed nothing


def test_subscribing_a_missing_service_raises(device):
    dev, _, _ = device
    with pytest.raises(RuntimeError, match="NoSuchModule"):
        dev.subscribe("NoSuchModule")
    assert dev.subscribers() == {}


def test_each_buffer_reaches_exactly_its_formats_subscribers_unchanged(device):
    dev, host, relay = device
    dev.set_preferences("Front", 16000, 3, 0)
    dev.subscribe("Front")
    dev.subscribe("All")
    host.wait_need(lambda n: len(n["formats"]) == 2)

    host.pcm(FRONT, 1, 3, b"\x01\x00\x02\x00\x03\x00")
    host.pcm(ALL, 4, 1, b"\x00\x01" * 4)
    host.pcm(FRONT, 1, 1, b"\xff\x7f")
    front = relay.wait("Front", 2)
    every = relay.wait("All", 1)
    time.sleep(0.1)
    assert [(c, n, b) for c, n, _, b in relay.got["Front"]] == [
        (1, 3, b"\x01\x00\x02\x00\x03\x00"),
        (1, 1, b"\xff\x7f"),
    ]
    assert [(c, n, b) for c, n, _, b in relay.got["All"]] == [(4, 1, b"\x00\x01" * 4)]
    # Stamped on arrival with the container's clock, [seconds, microseconds].
    (s0, us0), (s1, us1) = front[0][2], front[1][2]
    assert abs(s0 + us0 / 1e6 - time.time()) < 2 and (s1, us1) >= (s0, us0)
    assert 0 <= us0 < 1_000_000 and every[0][2][0] > 0


def test_energy_is_reported_only_while_enabled(device):
    dev, host, _ = device
    assert host.conn is not None
    host.conn.send(
        {"type": "energy", "left": 1.0, "right": 2.0, "front": 300.5, "rear": 4.0}
    )
    time.sleep(0.1)
    assert dev.energy("front") == 0.0
    dev.enable_energy()
    host.wait_need(lambda n: n["energy"])
    host.conn.send(
        {"type": "energy", "left": 1.0, "right": 2.0, "front": 300.5, "rear": 4.0}
    )
    deadline = time.time() + 2
    while dev.energy("front") != 300.5 and time.time() < deadline:
        time.sleep(0.01)
    assert (dev.energy("front"), dev.energy("rear")) == (300.5, 4.0)
    dev.disable_energy()
    assert dev.energy("front") == 0.0


def test_a_slow_subscriber_does_not_delay_another(device):
    dev, host, relay = device
    relay.block.add("Slow")
    dev.set_preferences("Slow", 16000, 3, 0)
    dev.set_preferences("Front", 16000, 3, 0)
    dev.subscribe("Slow")
    dev.subscribe("Front")
    host.wait_need(lambda n: n["formats"] == [core.format_header(FRONT)])
    for i in range(10):  # paced, as the host sends them (every 85 ms in real life)
        host.pcm(FRONT, 1, 1, bytes([i, 0]))
        time.sleep(0.01)
    assert [b for *_, b in relay.wait("Front", 10)] == [
        bytes([i, 0]) for i in range(10)
    ]

    relay.release.set()  # the slow one then gets the first buffer it was given and the newest
    got = relay.wait("Slow", 1 + core.QUEUE_SIZE)
    time.sleep(0.1)
    assert [b for *_, b in got] == [bytes([0, 0])] + [
        bytes([i, 0]) for i in range(10 - core.QUEUE_SIZE, 10)
    ]


def test_a_subscriber_that_keeps_failing_is_dropped(device, monkeypatch):
    monkeypatch.setattr(core, "FAILING_S", 0.05)
    dev, host, relay = device
    relay.fail.add("Gone")
    dev.set_preferences("Gone", 16000, 3, 0)
    dev.set_preferences("Front", 16000, 3, 0)
    dev.subscribe("Gone")
    dev.subscribe("Front")
    host.wait_need(lambda n: len(n["formats"]) == 1)
    for i in range(core.FAILURES + 6):
        host.pcm(FRONT, 1, 1, bytes([i, 0]))
        time.sleep(0.02)
    relay.wait("Front", core.FAILURES + 6)
    deadline = time.time() + 2
    while "Gone" in dev.subscribers() and time.time() < deadline:
        time.sleep(0.01)
    assert dev.subscribers() == {"Front": FRONT}
    assert relay.forgotten == ["Gone"]


def test_a_few_early_failures_do_not_drop_a_subscriber(device):
    dev, host, relay = device  # FAILING_S as shipped: a new subscriber may lag a moment
    relay.fail.add("Front")
    dev.set_preferences("Front", 16000, 3, 0)
    dev.subscribe("Front")
    host.wait_need(lambda n: len(n["formats"]) == 1)
    for i in range(core.FAILURES + 2):
        host.pcm(FRONT, 1, 1, bytes([i, 0]))
        time.sleep(0.02)
    time.sleep(0.1)
    relay.fail.discard("Front")  # reachable now
    host.pcm(FRONT, 1, 1, b"\x09\x00")
    assert relay.wait("Front", 1)[0][3] == b"\x09\x00"
    assert dev.subscribers() == {"Front": FRONT}


def test_the_need_is_sent_again_after_the_host_comes_back(monkeypatch):
    monkeypatch.setattr(core, "RETRY_S", 0.05)
    first = HostLink(0, host="127.0.0.1")
    port = first.port
    first.close()  # nobody listening: subscriptions still work, nothing is delivered
    relay = Relay()
    dev = core.AudioDevice(
        relay.deliver,
        exists=lambda name: True,
        address=f"127.0.0.1:{port}",
        log=lambda msg: None,
    )
    try:
        dev.set_preferences("Front", 16000, 3, 0)
        dev.subscribe("Front")
        assert dev.subscribers() == {"Front": FRONT}

        host = Host()
        second = HostLink(port, host="127.0.0.1")
        second.register(core.SERVICE, host)
        try:
            assert host.wait_need(lambda n: n["formats"], timeout=3)["formats"] == [
                core.format_header(FRONT)
            ]
            host.pcm(FRONT, 1, 1, b"\x05\x00")
            assert relay.wait("Front", 1)[0][3] == b"\x05\x00"
        finally:
            second.close()
    finally:
        dev.close()
