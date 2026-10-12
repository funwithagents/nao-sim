# -*- coding: utf-8 -*-
"""Shared logic of the ALTextToSpeech replacement (Python 2.7, inside NAOqi).

Turns NAOqi's tagged text into neutral items for the tts container, asks it to speak,
raises the ALMemory events the built-in raises (at the returned marker offsets), and
returns from say() when the audio is over. Falls back to a token clock when the engine
is unreachable, so nao-sim keeps working without sound.

Used by nao_sim_speech_almodule (2.1, ALModule) and nao_sim_speech_qiservice (2.8, qi service), which
register it as the hidden _NaoSimTextToSpeech; ALTextToSpeech itself is the C++ front
(docker/services/speech/nao_sim_speech_front.cpp), which gives every call its NAOqi task id so callers can stop it by
id (specs/services/speech.md, "Architecture: a C++ front over the Python core").
"""
import json
import os
import re
import sys
import threading
import time

try:
    import urllib2
except ImportError:  # Python 3, for the host-side tests
    import urllib.request as urllib2

TTS_URL = os.environ.get("NAO_SIM_TTS_URL", "http://tts:8080")
FALLBACK_SECONDS_PER_TOKEN = 0.3
# Ids for the calls the front makes blocking (no task id): above any task id the broker hands out.
FIRST_OWN_ID = 1000000

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
    """Speaks one call at a time, in arrival order; each call carries its id (the front's task id).
    `raise_event(key, value)` and `signal(name, *args)` are injected by the module so the same
    code serves ALModule and qi.Session objects."""

    def __init__(self, raise_event, signal=None, log=None):
        self.raise_event = raise_event
        self.signal = signal or (lambda *a: None)
        self.log = log or (lambda **f: None)
        self.language = "English"
        self.volume = 1.0
        self.state = {}
        self._own_id = FIRST_OWN_ID - 1
        self._stop = threading.Event()  # set: the speaking call ends
        self._turn = threading.Condition()  # guards the fields below
        self._waiting = []  # ids waiting for their turn, in arrival order
        self._speaking = None  # the id of the call speaking
        self._dropped = set()  # waiting ids stopped before their turn
        self._running = {}  # id -> Event set when that started call is over
        self.last = {}

    def new_id(self):
        """An id for a call that has no task id."""
        with self._turn:
            self._own_id += 1
            return self._own_id

    # -- engine --------------------------------------------------------------
    def _engine_say(self, items, rate, pitch, language):
        body = json.dumps({"language": language, "rate": rate, "pitch": pitch, "items": items}).encode("utf-8")
        req = urllib2.Request(TTS_URL + "/say", body, {"Content-Type": "application/json"})
        resp = urllib2.urlopen(req, timeout=30)
        return json.loads(resp.read())

    def _engine_stop(self):
        try:
            urllib2.urlopen(urllib2.Request(TTS_URL + "/stop", b"{}", {"Content-Type": "application/json"}), timeout=5).read()
        except Exception as e:  # noqa: BLE001
            self.log(method="engine-stop-failed", error=repr(e))

    # -- NAOqi side ------------------------------------------------------------
    def _wait_turn(self, sid):
        """Blocks until `sid` may speak; False if it was stopped while waiting."""
        with self._turn:
            self._waiting.append(sid)
            while sid not in self._dropped and (self._speaking is not None or self._waiting[0] != sid):
                self._turn.wait()
            self._waiting.remove(sid)
            if sid in self._dropped:
                self._dropped.discard(sid)
                self._turn.notify_all()
                return False
            self._speaking = sid
            self._stop.clear()  # before the engine call: a stopAll during synthesis must not be lost
            return True

    def _end_turn(self):
        with self._turn:
            self._speaking = None
            self._turn.notify_all()

    def say(self, text, sid=None, language=None):
        """Speaks `text` (in `language` for this call only, if given) once its turn comes, and
        returns when the audio is over or the call is stopped."""
        if sid is None:
            sid = self.new_id()
        if not self._wait_turn(sid):
            self.log(method="say-dropped", id=sid, text=text)
            return
        try:
            self._speak(text, sid, language or self.language)
        finally:
            self._end_turn()

    def _speak(self, text, sid, language):
        self.log(method="say", id=sid, text=text, lang=language)
        items, rate, pitch = parse(text, self.state)
        ev = self.raise_event
        ev("ALTextToSpeech/Status", [sid, "enqueued"])
        ev("ALTextToSpeech/TextStarted", 1)
        ev("ALTextToSpeech/TextDone", 0)
        try:
            r = self._engine_say(items, rate, pitch, language)
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

    def stop_call(self, sid):
        """stop(id): the speaking call ends as with stopAll; a waiting one is dropped unspoken;
        an unknown or finished id is ignored."""
        with self._turn:
            if sid == self._speaking:
                self.log(method="stop", id=sid, state="speaking")
                self._stop.set()
            elif sid in self._waiting:
                self.log(method="stop", id=sid, state="waiting")
                self._dropped.add(sid)
                self._turn.notify_all()

    def start(self, sid, text, language=None):
        """Runs say() for the front on a thread and returns at once; wait_done() follows it."""
        done = threading.Event()
        with self._turn:
            self._running[sid] = done
        t = threading.Thread(target=self._run, args=(sid, text, language, done), name="say-%s" % sid)
        t.daemon = True
        t.start()

    def _run(self, sid, text, language, done):
        try:
            self.say(text, sid, language)
        except Exception as e:  # noqa: BLE001
            self.log(method="say-failed", id=sid, error=repr(e))
        finally:
            with self._turn:
                self._running.pop(sid, None)
            done.set()

    def wait_done(self, sid, timeout_s):
        """True once the call started as `sid` is over (or unknown), waiting at most timeout_s."""
        with self._turn:
            done = self._running.get(sid)
        return done is None or done.wait(timeout_s)

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
