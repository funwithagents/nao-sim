# -*- coding: utf-8 -*-
"""Shared logic of the ALTextToSpeech replacement (Python 2.7, inside NAOqi).

Turns NAOqi's tagged text into neutral items for the tts container, asks it to speak,
raises the ALMemory events the built-in raises (at the returned marker offsets), and
returns from say() when the audio is over. Falls back to a token clock when the engine
is unreachable, so nao-sim keeps working without sound.

Used by nao_sim_tts_almodule (2.1, ALModule) and nao_sim_tts_qiservice (2.8, qi service).
"""
import json
import os
import re
import sys
import threading
import time
import urllib2

TTS_URL = os.environ.get("NAO_SIM_TTS_URL", "http://tts:8080")
FALLBACK_SECONDS_PER_TOKEN = 0.3

_TAG = re.compile(r"\\(pau|rspd|vct|mrk|mrkpause|vol|emph|bound|readmode|rst|tn)(?:=([^\\]*))?\\", re.I)


def parse(text, state):
    """NAOqi tagged text -> (items, state). state holds rspd/vct carried across calls."""
    items = []
    pos = 0
    rate = state.get("rspd", 100)
    pitch = state.get("vct", 100)

    def flush(seg):
        seg = seg.strip()
        if seg:
            items.append({"type": "text", "text": seg})

    for m in _TAG.finditer(text):
        flush(text[pos:m.start()])
        pos = m.end()
        tag, val = m.group(1).lower(), m.group(2)
        if tag == "pau":
            items.append({"type": "pause", "ms": int(float(val or 0))})
        elif tag in ("mrk", "mrkpause"):
            items.append({"type": "mark", "id": int(float(val or 0))})
        elif tag == "rspd":
            rate = float(val or 100)
        elif tag == "vct":
            pitch = float(val or 100)
        elif tag == "rst":
            rate, pitch = 100, 100
        # vol, emph, bound, readmode, tn: ignored in v1
    flush(text[pos:])
    state["rspd"], state["vct"] = rate, pitch
    return items, rate, pitch


class Speaker(object):
    """Drives one say() at a time. `raise_event(key, value)` and `signal(name, *args)` are
    injected by the module so the same code serves ALModule and qi.Session objects."""

    def __init__(self, raise_event, signal=None, log=None):
        self.raise_event = raise_event
        self.signal = signal or (lambda *a: None)
        self.log = log or (lambda **f: None)
        self.language = "English"
        self.volume = 1.0
        self.state = {}
        self._id = 0
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.last = {}

    # -- engine --------------------------------------------------------------
    def _engine_say(self, items, rate, pitch):
        body = json.dumps({"language": self.language, "rate": rate, "pitch": pitch, "items": items})
        req = urllib2.Request(TTS_URL + "/say", body, {"Content-Type": "application/json"})
        resp = urllib2.urlopen(req, timeout=30)
        return json.loads(resp.read())

    def _engine_stop(self):
        try:
            urllib2.urlopen(urllib2.Request(TTS_URL + "/stop", "{}", {"Content-Type": "application/json"}), timeout=5).read()
        except Exception as e:  # noqa: BLE001
            self.log(method="engine-stop-failed", error=repr(e))

    # -- NAOqi side ------------------------------------------------------------
    def say(self, text):
        with self._lock:
            self._id += 1
            sid = self._id
            self.log(method="say", id=sid, text=text, lang=self.language)
            items, rate, pitch = parse(text, self.state)
            ev = self.raise_event
            ev("ALTextToSpeech/Status", [sid, "enqueued"])
            ev("ALTextToSpeech/TextStarted", 1)
            ev("ALTextToSpeech/TextDone", 0)
            try:
                r = self._engine_say(items, rate, pitch)
                t0 = time.time()
                duration = float(r.get("duration", 0.0))
                marks = sorted((float(off), int(k)) for k, off in r.get("marks", {}).items())
                engine = r.get("engine", "?")
            except Exception as e:  # noqa: BLE001
                t0 = time.time()
                self.log(method="engine-unreachable", error=repr(e))
                tokens = text.split()
                duration = FALLBACK_SECONDS_PER_TOKEN * max(len(tokens), 1)
                marks = []
                acc = 0.0
                for tok in tokens:
                    for mk in re.findall(r"\\mrk(?:pause)?=(\d+)\\", tok):
                        marks.append((acc, int(mk)))
                    acc += FALLBACK_SECONDS_PER_TOKEN
                engine = "fallback-clock"
            self.last = {"id": sid, "duration": duration, "marks": marks, "engine": engine}
            ev("ALTextToSpeech/Status", [sid, "started"])
            ev("ALTextToSpeech/CurrentSentence", text)
            self.signal("_started", text)
            self._stop.clear()
            interrupted = False
            for off, mk in marks:
                if self._stop.wait(max(0.0, t0 + off - time.time())):
                    interrupted = True
                    break
                ev("ALTextToSpeech/CurrentBookMark", mk)
            if not interrupted and self._stop.wait(max(0.0, t0 + duration - time.time())):
                interrupted = True
            if interrupted:
                self._engine_stop()
                ev("ALTextToSpeech/TextInterrupted", 1)
            ev("ALTextToSpeech/Status", [sid, "done"])
            ev("ALTextToSpeech/CurrentSentence", "")
            ev("ALTextToSpeech/TextDone", 1)
            ev("ALTextToSpeech/CurrentBookMark", 0)
            ev("ALTextToSpeech/TextStarted", 0)
            self.log(method="say-done", id=sid, engine=engine, duration=round(duration, 3), interrupted=interrupted)

    def stop_all(self):
        self.log(method="stopAll")
        self._stop.set()

    def set_language(self, lang):
        self.language = lang
        self.signal("languageTTS", lang)

    def set_parameter(self, name, value):
        n = name.lower()
        if n in ("speed", "defaultvoicespeed"):
            self.state["rspd"] = float(value)
        elif n in ("pitchshift",):
            self.state["vct"] = float(value) * 100.0 if float(value) < 10 else float(value)
        self.log(method="setParameter", name=name, value=value)

    def get_parameter(self, name):
        n = name.lower()
        if n in ("speed", "defaultvoicespeed"):
            return float(self.state.get("rspd", 100))
        if n == "pitchshift":
            return float(self.state.get("vct", 100)) / 100.0
        return 0.0
