# -*- coding: utf-8 -*-
"""NaoSim status service for NAOqi 2.8, registered as a qi service (the gateway relays it).
The keys and the ready flag live in nao_sim_status_core."""
import os
import sys

import qi

import nao_sim_status_core as core


class NaoSim(object):
    def __init__(self, session):
        memory = session.service("ALMemory")
        self.status = core.Status(memory.insertData, memory.raiseEvent)

    def getVersion(self):
        return self.status.version

    def getNaoqiVersion(self):
        return self.status.naoqi_version

    def isReady(self):
        return self.status.ready

    def setReady(self):
        self.status.set_ready()


_url = "tcp://127.0.0.1:%s" % os.environ.get("NAO_SIM_INTERNAL_PORT", "9559")
_session = qi.Session()
_session.connect(_url)
_service = NaoSim(_session)
_sid = _session.registerService(core.SERVICE, _service)
sys.stderr.write("[nao_sim_status_qiservice] registered %s (id %s; nao-sim %s, NAOqi %s)\n"
                 % (core.SERVICE, _sid, _service.status.version, _service.status.naoqi_version))
