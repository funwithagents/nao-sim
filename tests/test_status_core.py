"""The NaoSim status service's shared logic: what it publishes in ALMemory and when it is ready."""

import nao_sim_status_core as core


class FakeMemory:
    """Records insertData/raiseEvent as the real ALMemory would see them."""

    def __init__(self):
        self.data: dict[str, object] = {}
        self.events: list[tuple[str, object]] = []

    def insert(self, key, value):
        self.data[key] = value

    def raise_event(self, key, value):
        self.data[key] = value
        self.events.append((key, value))


ENV = {"NAO_SIM_VERSION": "0.3.1", "NAO_SIM_NAOQI_VERSION": "2.8.7.4"}


def test_publishes_versions_and_idle_sources_at_load():
    memory = FakeMemory()
    status = core.Status(memory.insert, memory.raise_event, env=ENV)

    assert status.version == "0.3.1"
    assert status.naoqi_version == "2.8.7.4"
    assert memory.data == {
        "NaoSim/Version": "0.3.1",
        "NaoSim/NaoqiVersion": "2.8.7.4",
        "NaoSim/Ready": 0,
        "NaoSim/Camera/Source": "none",
        "NaoSim/Audio/Source": "none",
        "NaoSim/Audio/Channels": "none",
    }


def test_versions_default_when_the_image_sets_none():
    assert core.versions({}) == ("dev", "unknown")
    assert core.versions({"NAO_SIM_VERSION": "", "NAO_SIM_NAOQI_VERSION": ""}) == (
        "dev",
        "unknown",
    )


def test_not_ready_until_set_ready_then_the_event_is_raised():
    memory = FakeMemory()
    status = core.Status(memory.insert, memory.raise_event, env=ENV)
    assert status.ready is False
    assert memory.events == [("NaoSim/Ready", 0)]

    status.set_ready()

    assert status.ready is True
    assert memory.data["NaoSim/Ready"] == 1
    assert memory.events[-1] == ("NaoSim/Ready", 1)
