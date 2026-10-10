# -*- coding: utf-8 -*-
"""ALAudioDevice replacement for NAOqi 2.8, registered as a qi service (the gateway relays it).
The desktop suite has no ALAudioDevice, so the name is registered directly. The logic lives in
nao_sim_audiodevice_core; buffers reach a subscriber through the native relay (_NaoSimAudioRelay),
which this module calls through its own session."""
import os
import sys

import qi

import nao_sim_audiodevice_core as core

_url = "tcp://127.0.0.1:%s" % os.environ.get("NAO_SIM_INTERNAL_PORT", "9559")
_session = qi.Session()
_session.connect(_url)


def _deliver(name, channels, samples, stamp, buffer):
    _session.service(core.RELAY).deliver(name, channels, samples, stamp, buffer)


def _forget(name):
    _session.service(core.RELAY).forget(name)


def _exists(name):
    return any(s["name"] == name for s in _session.services())


@qi.multiThreaded()
class ALAudioDevice(object):
    def __init__(self):
        self.device = core.AudioDevice(_deliver, _exists, _forget)

    def setClientPreferences(self, name, sampleRate, channels, deinterleaved):
        try:
            self.device.set_preferences(name, sampleRate, channels, deinterleaved)
        except ValueError as e:
            raise RuntimeError("ALAudioDevice.setClientPreferences: %s" % e)

    def subscribe(self, name):
        self.device.subscribe(name)

    def unsubscribe(self, name):
        self.device.unsubscribe(name)

    def enableEnergyComputation(self):
        self.device.enable_energy()

    def disableEnergyComputation(self):
        self.device.disable_energy()

    def getFrontMicEnergy(self):
        return self.device.energy("front")

    def getRearMicEnergy(self):
        return self.device.energy("rear")

    def getLeftMicEnergy(self):
        return self.device.energy("left")

    def getRightMicEnergy(self):
        return self.device.energy("right")

    def openAudioInputs(self):
        pass

    def closeAudioInputs(self):
        pass

    def isInputMuted(self):
        return False

    def getOutputVolume(self):
        return self.device.output_volume

    def setOutputVolume(self, volume):
        self.device.output_volume = int(volume)


_service = ALAudioDevice()
_sid = _session.registerService(core.SERVICE, _service)
sys.stderr.write("[nao_sim_audiodevice_qiservice] registered %s (id %s)\n" % (core.SERVICE, _sid))
