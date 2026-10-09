# -*- coding: utf-8 -*-
"""Shared logic of the NaoSim status service (Python 2.7, inside NAOqi).

The identity of a nao-sim target: the nao-sim and NAOqi versions, which host devices are
attached, and whether boot is complete, published as ALMemory keys under `NaoSim/`.

Used by nao_sim_status_almodule (2.1, ALModule) and nao_sim_status_qiservice (2.8, qi service).
Kept importable under Python 3 so the host's fast tests cover it.
"""
import os

SERVICE = "NaoSim"
PREFIX = "NaoSim/"
NONE = "none"  # no host device attached to that service
DEVICES = ("Camera", "Audio", "Perception")
DEFAULT_VERSION = "dev"
UNKNOWN = "unknown"


def versions(env=None):
    """(nao-sim version, NAOqi version) from the image's environment."""
    if env is None:
        env = os.environ
    return (
        env.get("NAO_SIM_VERSION") or DEFAULT_VERSION,
        env.get("NAO_SIM_NAOQI_VERSION") or UNKNOWN,
    )


class Status(object):
    """Writes the NaoSim/ keys at creation and flips NaoSim/Ready on set_ready().

    insert(key, value) writes an ALMemory key; raise_event(key, value) also notifies the
    subscribers of that key (ALMemory.insertData / ALMemory.raiseEvent on the real thing)."""

    def __init__(self, insert, raise_event, env=None):
        self.version, self.naoqi_version = versions(env)
        self.ready = False
        self._raise_event = raise_event
        insert(PREFIX + "Version", self.version)
        insert(PREFIX + "NaoqiVersion", self.naoqi_version)
        for device in DEVICES:
            insert(PREFIX + device + "/Source", NONE)
        raise_event(PREFIX + "Ready", 0)

    def set_ready(self):
        self.ready = True
        self._raise_event(PREFIX + "Ready", 1)
