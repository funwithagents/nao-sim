"""The host sound card: a dumb PCM player the containers stream into.

Protocol (TCP, one connection per stream): a JSON header line, then raw PCM until the
sender closes.  {"cmd": "play", "rate": 22050, "channels": 1, "format": "s16le"}
A connection whose header is {"cmd": "stop"} stops the current playback.
Options: --record FILE appends everything played to a WAV file (tests, CI); --silent skips
the audio device. Playback state is exposed on stdout as one JSON line per start/stop.
"""
import argparse
import json
import socketserver
import threading
import time
import wave


class SoundCard:
    def __init__(self, record=None, silent=False):
        self.record = record
        self.silent = silent
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._gen = 0
        self._wav = None
        self._wav_rate = None
        self.playing_until = 0.0

    def _log(self, **f):
        f["t"] = round(time.time(), 3)
        print(json.dumps(f), flush=True)

    def _open_wav(self, rate):
        if not self.record:
            return
        if self._wav is None or self._wav_rate != rate:
            if self._wav:
                self._wav.close()
            self._wav = wave.open(self.record, "wb")  # noqa: SIM115 (long-lived, closed on rate change or exit)
            self._wav.setnchannels(1); self._wav.setsampwidth(2); self._wav.setframerate(rate)
            self._wav_rate = rate

    def play_stream(self, rfile, header):
        rate = int(header.get("rate", 22050)); channels = int(header.get("channels", 1))
        with self._lock:
            self._gen += 1; gen = self._gen
            self._stop.clear()
        self._log(event="start", rate=rate, channels=channels)
        self._open_wav(rate)
        total = 0
        stream = None
        if not self.silent:
            import sounddevice as sd
            stream = sd.RawOutputStream(samplerate=rate, channels=channels, dtype="int16", blocksize=0)
            stream.start()
        try:
            while True:
                data = rfile.read(rate * 2 * channels // 10)  # 100 ms
                if not data:
                    break
                if self._stop.is_set() or gen != self._gen:
                    self._log(event="interrupted", played_s=round(total / (2.0 * channels * rate), 3))
                    break
                total += len(data)
                if self._wav:
                    self._wav.writeframes(data)
                if stream:
                    stream.write(data)
                else:  # silent mode: pace like a real device so stop and timing behave the same
                    time.sleep(len(data) / (2.0 * channels * rate))
        finally:
            if stream:
                stream.stop(); stream.close()
            self._log(event="end", played_s=round(total / (2.0 * channels * rate), 3))

    def stop(self):
        self._stop.set()
        self._log(event="stop-request")


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline()
        try:
            header = json.loads(line.decode() or "{}")
        except ValueError:
            return
        assert isinstance(self.server, Server)
        card = self.server.card
        if header.get("cmd") == "stop":
            card.stop(); return
        if header.get("cmd") == "play":
            card.play_stream(self.rfile, header)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr, card):
        super().__init__(addr, Handler)
        self.card = card


def main(argv=None):
    ap = argparse.ArgumentParser(description="nao-sim host sound card")
    ap.add_argument("--listen", default="0.0.0.0:9562")
    ap.add_argument("--record", help="WAV file to append everything played to")
    ap.add_argument("--silent", action="store_true", help="do not open the audio device")
    a = ap.parse_args(argv)
    host, port = a.listen.rsplit(":", 1)
    srv = Server((host, int(port)), SoundCard(record=a.record, silent=a.silent))
    print(json.dumps({"event": "listening", "addr": a.listen, "record": a.record, "silent": a.silent}), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if srv.card._wav:
            srv.card._wav.close()


if __name__ == "__main__":
    main()
