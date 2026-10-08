# -*- coding: utf-8 -*-
"""ALTextToSpeech replacement for NAOqi 2.8, registered as a qi service (the gateway relays it).
Carries the built-in's hidden signals (_started, synchroTTS, languageTTS) and _sayWithLocale,
which ALAnimatedSpeech 2.8 needs. Speech itself is done by nao_sim_tts_core."""
import json
import os
import sys
import time

import qi

import nao_sim_tts_core as core

LOG = "/home/nao/tts_qiservice.jsonl"
_t0 = time.time()


def _log(**f):
    f["t"] = round(time.time() - _t0, 3)
    with open(LOG, "a") as fh:
        fh.write(json.dumps(f, default=repr) + "\n")


@qi.multiThreaded()
class ALTextToSpeech(object):
    """multiThreaded: say() blocks for the audio, stopAll() must still get through."""
    def __init__(self, session):
        self._started = qi.Signal("(s)")
        self.synchroTTS = qi.Signal("(L)")
        self.languageTTS = qi.Signal("(s)")
        self.memory = session.service("ALMemory")
        self.speaker = core.Speaker(self.memory.raiseEvent, signal=self._signal, log=_log)

    def _signal(self, name, *args):
        sig = getattr(self, name, None)
        if sig is not None:
            sig(*args)

    def say(self, text, *lang):
        if lang and lang[0]:
            old = self.speaker.language
            self.speaker.set_language(lang[0])
            try:
                self.speaker.say(text)
            finally:
                self.speaker.set_language(old)
        else:
            self.speaker.say(text)

    def _sayWithLocale(self, text, locale, extra):
        _log(method="_sayWithLocale", locale=locale, extra=extra)
        self.speaker.say(text)

    def sayToFile(self, text, path):
        _log(method="sayToFile", text=text, path=path)

    def stopAll(self):
        self.speaker.stop_all()

    def setLanguage(self, lang):
        self.speaker.set_language(lang)

    def getLanguage(self):
        return self.speaker.language

    def getAvailableLanguages(self):
        return ["English", "French"]

    def getSupportedLanguages(self):
        return ["English", "French"]

    def resetSpeed(self):
        self.speaker.state["rspd"] = 100

    def setParameter(self, name, value):
        self.speaker.set_parameter(name, value)

    def getParameter(self, name):
        return self.speaker.get_parameter(name)

    def setVoice(self, v):
        _log(method="setVoice", v=v)

    def getVoice(self):
        return "naosim"

    def getAvailableVoices(self):
        return ["naosim"]

    def setVolume(self, v):
        self.speaker.volume = float(v)

    def getVolume(self):
        return self.speaker.volume

    def locale(self):
        return "en_US"

    def loadVoicePreference(self, name):
        _log(method="loadVoicePreference", name=name)

    def setLanguageDefaultVoice(self, lang, voice):
        _log(method="setLanguageDefaultVoice", lang=lang, voice=voice)

    def _pause(self):
        _log(method="_pause")

    def _resume(self):
        _log(method="_resume")

    def reset(self):
        _log(method="reset")

    def whoami(self):
        return "nao-sim qi.Session replacement (2.8, engine %s)" % core.TTS_URL


_url = "tcp://127.0.0.1:%s" % os.environ.get("NAO_SIM_INTERNAL_PORT", "9559")
_session = qi.Session()
_session.connect(_url)
_service = ALTextToSpeech(_session)
_sid = _session.registerService("ALTextToSpeech", _service)
_log(method="registered", id=_sid, url=_url, tts_url=core.TTS_URL)
sys.stderr.write("[nao_sim_tts_qiservice] registered ALTextToSpeech (id %s), engine %s\n" % (_sid, core.TTS_URL))
