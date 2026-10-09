# -*- coding: utf-8 -*-
"""ALTextToSpeech replacement for NAOqi 2.1, registered through naoqi-bin's broker (ALModule).
Speech itself is done by nao_sim_tts_core (tts container + host speaker)."""
import json
import sys
import time

from naoqi import ALModule, ALProxy

import nao_sim_tts_core as core

LOG = "/home/nao/tts_almodule.jsonl"
_t0 = time.time()


def _log(**f):
    f["t"] = round(time.time() - _t0, 3)
    with open(LOG, "a") as fh:
        fh.write(json.dumps(f, default=repr) + "\n")


class ALTextToSpeech(ALModule):
    def __init__(self, name):
        ALModule.__init__(self, name)
        self.memory = ALProxy("ALMemory")
        self.speaker = core.Speaker(self.memory.raiseEvent, log=_log)
        try:
            self.BIND_PYTHON(name, "say", 1)   # autobind registered the 2-arg form only
        except Exception as e:  # noqa: BLE001
            _log(method="bind-say-1", error=repr(e))

    def say(self, text, lang=None):
        """Says the text, optionally in the given language."""
        if lang:
            old = self.speaker.language
            self.speaker.set_language(lang)
            try:
                self.speaker.say(text)
            finally:
                self.speaker.set_language(old)
        else:
            self.speaker.say(text)

    def sayToFile(self, text, path):
        """Not supported on nao-sim."""
        _log(method="sayToFile", text=text, path=path)

    def stopAll(self):
        """Stops all current speech."""
        self.speaker.stop_all()

    def setLanguage(self, lang):
        """Sets the language."""
        self.speaker.set_language(lang)

    def getLanguage(self):
        """Returns the current language."""
        return self.speaker.language

    def getAvailableLanguages(self):
        """Returns the installed languages."""
        return ["English", "French"]

    def getSupportedLanguages(self):
        """Returns the supported languages."""
        return ["English", "French"]

    def setParameter(self, name, value):
        """Sets a parameter (speed, pitchShift...)."""
        self.speaker.set_parameter(name, value)

    def getParameter(self, name):
        """Gets a parameter."""
        return self.speaker.get_parameter(name)

    def resetSpeed(self):
        """Resets the speed."""
        self.speaker.state["rspd"] = 100

    def setVolume(self, v):
        """Sets the volume."""
        self.speaker.volume = float(v)

    def getVolume(self):
        """Returns the volume."""
        return self.speaker.volume

    def setVoice(self, v):
        """Sets the voice (ignored)."""
        _log(method="setVoice", v=v)

    def getVoice(self):
        """Returns the voice."""
        return "naosim"

    def getAvailableVoices(self):
        """Returns the voices."""
        return ["naosim"]

    def locale(self):
        """Returns the locale."""
        return "en_US"

    def loadVoicePreference(self, name):
        """Loads a voice preference (ignored)."""
        _log(method="loadVoicePreference", name=name)

    def setLanguageDefaultVoice(self, lang, voice):
        """Sets the default voice of a language (ignored)."""
        _log(method="setLanguageDefaultVoice", lang=lang, voice=voice)

    def enableNotifications(self):
        """Deprecated no-op."""
        _log(method="enableNotifications")

    def disableNotifications(self):
        """Deprecated no-op."""
        _log(method="disableNotifications")

    def whoami(self):
        """Identifies this implementation."""
        return "nao-sim ALModule replacement (engine %s)" % core.TTS_URL


ALTextToSpeech = ALTextToSpeech("ALTextToSpeech")
_log(method="registered", tts_url=core.TTS_URL)
sys.stderr.write("[nao_sim_tts_almodule] registered ALTextToSpeech through the broker, engine %s\n" % core.TTS_URL)
