"""ALMemory as the Memory boxes use it (Get Data, Insert Data, Raise Event, Remove Data, Subscribe
to Event; 2.8's Expression Watcher), from a host client (plans/202610132100_api-coverage-from-boxes.md)."""

import threading
import uuid

import pytest


def key(name: str) -> str:
    return f"NaoqiSimTest/{name}/{uuid.uuid4().hex[:8]}"


class Received:
    """What a signal delivered, for a test to wait on."""

    def __init__(self):
        self.values: list = []
        self._got = threading.Event()

    def __call__(self, value):
        self.values.append(value)
        self._got.set()

    def wait(self, timeout: float = 3.0) -> list:
        assert self._got.wait(timeout), "nothing received"
        return self.values


@pytest.mark.parametrize(
    "value", [42, 0.5, "text", [1, "two", 3.0]], ids=["int", "float", "str", "list"]
)
def test_inserted_data_reads_back(nao, value):
    memory = nao.service("ALMemory")
    name = key("data")
    memory.insertData(name, value)
    try:
        assert memory.getData(name) == value
    finally:
        memory.removeData(name)


def test_list_data_reads_several_keys(nao):
    memory = nao.service("ALMemory")
    names = [key("a"), key("b")]
    for i, name in enumerate(names):
        memory.insertData(name, i)
    try:
        assert memory.getListData(names) == [0, 1]
    finally:
        for name in names:
            memory.removeData(name)


def test_removed_data_is_gone(nao):
    memory = nao.service("ALMemory")
    name = key("removed")
    memory.insertData(name, 1)
    memory.removeData(name)
    assert name not in memory.getDataListName()
    with pytest.raises(RuntimeError):
        memory.getData(name)


def test_a_raised_event_reaches_a_subscriber(nao):
    memory = nao.service("ALMemory")
    name = key("event")
    received = Received()
    subscriber = memory.subscriber(name)
    link = subscriber.signal.connect(received)
    try:
        memory.raiseEvent(name, "hello")
        assert received.wait() == ["hello"]
        assert memory.getData(name) == "hello"  # an event keeps its last value
    finally:
        subscriber.signal.disconnect(link)
        memory.removeData(name)


def test_a_declared_event_is_listed(nao):
    memory = nao.service("ALMemory")
    name = key("declared")
    memory.declareEvent(name)
    try:
        assert name in memory.getEventList()
    finally:
        memory.removeData(name)


def test_an_expression_watcher_reports_its_condition(nao):
    """2.8's Expression Watcher box: a signal when an ALMemory condition turns true."""
    if nao.version.name != "2.8":
        pytest.skip("ALExpressionWatcher and its box are 2.8's")
    memory = nao.service("ALMemory")
    name = key("watched")
    memory.insertData(name, 0)
    received = Received()
    rising_edge = 2
    watcher = nao.service("ALExpressionWatcher").add(f"('{name}' > 5)", rising_edge)
    link = watcher.signal.connect(received)
    try:
        memory.insertData(name, 3)
        memory.insertData(name, 7)
        assert received.wait()
    finally:
        watcher.signal.disconnect(link)
        memory.removeData(name)
