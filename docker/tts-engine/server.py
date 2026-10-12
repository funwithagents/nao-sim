"""nao-sim speech engine. One HTTP endpoint, standard library only.

POST /say   {"language": "English", "rate": 100, "pitch": 100, "engine": "piper"|"espeak",
             "items": [{"type":"text","text":"Hello"}, {"type":"mark","id":1}, {"type":"pause","ms":500}]}
        ->  {"duration": s, "marks": {"1": offset_s}, "rate": 22050, "engine": "piper"}
            The PCM is streamed to the host sound card (NAO_SIM_SOUNDCARD) before the reply.
POST /stop  stops streaming and asks the sound card to stop.
GET  /health

Markers are exact: every text item is synthesized on its own and concatenated, so a mark's
offset is the sum of the durations before it.
"""

import io
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

VOICES = {"english": "en_US-lessac-medium", "french": "fr_FR-siwis-medium"}
ESPEAK_LANG = {"english": "en-us", "french": "fr"}
VOICE_DIR = "/voices"
SOUNDCARD = os.environ.get("NAO_SIM_SOUNDCARD", "host.docker.internal:9562")
DEFAULT_ENGINE = os.environ.get("NAO_SIM_TTS_ENGINE", "piper")

_piper_voices = {}
_lock = threading.Lock()
_stop = threading.Event()
_current = {"sock": None}


def piper_voice(lang):
    name = VOICES.get(lang.lower(), VOICES["english"])
    with _lock:
        if name not in _piper_voices:
            from piper import PiperVoice

            _piper_voices[name] = PiperVoice.load(
                os.path.join(VOICE_DIR, name + ".onnx")
            )
    return name, _piper_voices[name]


def synth_piper(text, lang, rate):
    name, voice = piper_voice(lang)
    sr = voice.config.sample_rate
    chunks = []
    try:
        from piper import SynthesisConfig

        cfg = SynthesisConfig(length_scale=100.0 / max(rate, 20))
        for ch in voice.synthesize(text, cfg):
            chunks.append(np.frombuffer(ch.audio_int16_bytes, dtype=np.int16))
    except ImportError:  # older piper API
        for ch in voice.synthesize_stream_raw(text, length_scale=100.0 / max(rate, 20)):
            chunks.append(np.frombuffer(ch, dtype=np.int16))
    pcm = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)
    return pcm, sr, name


def synth_espeak(text, lang, rate, pitch):
    v = ESPEAK_LANG.get(lang.lower(), "en-us")
    wpm = int(175 * rate / 100.0)
    out = subprocess.run(
        [
            "espeak-ng",
            "-v",
            v,
            "-s",
            str(wpm),
            "-p",
            str(int(pitch / 2)),
            "--stdout",
            text,
        ],
        capture_output=True,
        check=True,
    ).stdout
    with wave.open(io.BytesIO(out)) as w:
        sr = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return pcm, sr, "espeak-ng:" + v


def resample(pcm, sr_from, sr_to):
    if sr_from == sr_to or len(pcm) == 0:
        return pcm
    n = int(len(pcm) * sr_to / sr_from)
    x = np.linspace(0, len(pcm) - 1, n)
    return np.interp(x, np.arange(len(pcm)), pcm.astype(np.float32)).astype(np.int16)


def render(req):
    engine = req.get("engine") or DEFAULT_ENGINE
    lang = req.get("language") or "English"
    rate = float(req.get("rate") or 100)
    pitch = float(req.get("pitch") or 100)
    parts, marks, sr, used = [], {}, None, engine
    total = 0.0
    for item in req.get("items", []):
        t = item.get("type")
        if t == "text":
            text = (item.get("text") or "").strip()
            if not text:
                continue
            if engine == "espeak":
                pcm, sr_i, used = synth_espeak(text, lang, rate, pitch)
            else:
                pcm, sr_i, used = synth_piper(text, lang, rate)
            if sr is None:
                sr = sr_i
            pcm = resample(pcm, sr_i, sr)
            parts.append(pcm)
            total += len(pcm) / float(sr)
        elif t == "mark":
            marks[str(item.get("id"))] = round(total, 4)
        elif t == "pause":
            if sr is None:
                sr = 22050
            n = int(sr * float(item.get("ms") or 0) / 1000.0)
            parts.append(np.zeros(n, dtype=np.int16))
            total += n / float(sr)
    if sr is None:
        sr = 22050
    pcm = np.concatenate(parts) if parts else np.zeros(0, dtype=np.int16)
    return pcm, sr, marks, used


def soundcard_connect():
    host, port = SOUNDCARD.rsplit(":", 1)
    s = socket.create_connection((host, int(port)), timeout=5)
    return s


def stream_to_soundcard(pcm, sr):
    """Send a header line then raw PCM; the sound card plays as it receives. Returns when sent."""
    _stop.clear()
    s = soundcard_connect()
    _current["sock"] = s
    try:
        s.sendall(
            (
                json.dumps(
                    {"cmd": "play", "rate": sr, "channels": 1, "format": "s16le"}
                )
                + "\n"
            ).encode()
        )
        data = pcm.tobytes()
        chunk = sr * 2 // 10  # 100 ms
        for i in range(0, len(data), chunk):
            if _stop.is_set():
                break
            s.sendall(data[i : i + chunk])
    finally:
        try:
            s.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        s.close()
        _current["sock"] = None


def soundcard_stop():
    try:
        s = soundcard_connect()
        s.sendall((json.dumps({"cmd": "stop"}) + "\n").encode())
        s.close()
    except OSError as e:
        print("stop: sound card unreachable:", e)


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self._json(
                200,
                {
                    "ok": True,
                    "engine": DEFAULT_ENGINE,
                    "voices": VOICES,
                    "soundcard": SOUNDCARD,
                },
            )
        self._json(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        req = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/stop":
            _stop.set()
            soundcard_stop()
            return self._json(200, {"stopped": True})
        if self.path != "/say":
            return self._json(404, {"error": "not found"})
        t0 = time.time()
        try:
            pcm, sr, marks, used = render(req)
        except Exception as e:  # noqa: BLE001
            print("render error:", repr(e))
            return self._json(500, {"error": repr(e)})
        synth = time.time() - t0
        duration = len(pcm) / float(sr)
        # Stream in the background so the reply (and the caller's clock) starts with the audio.
        th = threading.Thread(target=self._safe_stream, args=(pcm, sr), daemon=True)
        th.start()
        print(f"say: {used} {duration:.2f}s audio, synth {synth:.2f}s, marks {marks}")
        self._json(
            200,
            {
                "duration": round(duration, 4),
                "marks": marks,
                "rate": sr,
                "engine": used,
                "synth_time": round(synth, 3),
            },
        )

    def _safe_stream(self, pcm, sr):
        try:
            stream_to_soundcard(pcm, sr)
        except OSError as e:
            print(f"sound card unreachable ({e}): audio dropped")

    def log_message(self, fmt, *args):  # quieter
        pass


if __name__ == "__main__":
    # The server is the container's PID 1, to which the kernel applies no default signal action:
    # without a handler `docker stop` would wait its 10 s grace period, then kill it.
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))
    print(f"nao-sim tts: engine={DEFAULT_ENGINE} soundcard={SOUNDCARD} voices={VOICES}")
    if (
        DEFAULT_ENGINE == "piper"
    ):  # pre-load the voices so the first say() does not pay for it
        for lang, name in VOICES.items():
            t = time.time()
            piper_voice(lang)
            print(f"loaded {name} in {time.time() - t:.2f}s")
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
