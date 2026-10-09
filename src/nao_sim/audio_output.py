"""The audio output: the simulated robot's loudspeaker on the host, a dumb PCM player the
containers stream into (specs/host/audio-output.md).

Protocol (TCP, one connection per stream): a JSON header line, then raw PCM until the
sender closes.  {"cmd": "play", "rate": 22050, "channels": 1, "format": "s16le"}
A connection whose header is {"cmd": "stop"} stops the current playback.
Where the audio goes is an `AudioSink`: the output device, nothing, a WAV file or memory.
The audio output paces every sink in real time, so stop and timing behave the same. A running
`NaoSim` owns it; there is no command to start it on its own.
"""

import dataclasses
import io
import json
import logging
import socketserver
import threading
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

log = logging.getLogger(__name__)

CHUNK_S = 0.1  # the unit of feeding, pacing and stop latency


class AudioSink(Protocol):
    def begin(self, rate: int, channels: int) -> None:
        """A new stream starts."""

    def feed(self, chunk: bytes) -> None:
        """Interleaved s16le PCM, at most 100 ms."""

    def end(self, interrupted: bool) -> None:
        """The stream finished, or was cut by a stop or a newer stream."""


class NullSink:
    """Discards the audio (the audio output still paces it)."""

    def begin(self, rate: int, channels: int) -> None:
        pass

    def feed(self, chunk: bytes) -> None:
        pass

    def end(self, interrupted: bool) -> None:
        pass


class DevicePlayer:
    """Plays on an output device; `sounddevice` is imported at the first stream."""

    def __init__(self, device: int | str | None = None):
        self.device = device
        self._stream: Any = None

    def begin(self, rate: int, channels: int) -> None:
        import sounddevice as sd

        self._stream = sd.RawOutputStream(
            samplerate=rate,
            channels=channels,
            dtype="int16",
            blocksize=0,
            device=self.device,
        )
        self._stream.start()

    def feed(self, chunk: bytes) -> None:
        if self._stream is not None:
            self._stream.write(chunk)

    def end(self, interrupted: bool) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            # A cut stream stops at once; a finished one plays out what is queued.
            if interrupted:
                stream.abort()
            else:
                stream.stop()
        finally:
            stream.close()


class WavSink:
    """Writes mono 16-bit WAV, reopened (overwritten) when the sample rate changes."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._wav: wave.Wave_write | None = None
        self._rate: int | None = None
        self._channels = 1

    def begin(self, rate: int, channels: int) -> None:
        self._channels = channels
        if self._wav is None or self._rate != rate:
            self.close()
            self._wav = wave.open(str(self.path), "wb")  # noqa: SIM115 (spans streams, closed by close())
            self._wav.setnchannels(1)
            self._wav.setsampwidth(2)
            self._wav.setframerate(rate)
            self._rate = rate

    def feed(self, chunk: bytes) -> None:
        if self._wav is None:
            return
        if self._channels > 1:
            samples = np.frombuffer(chunk, dtype="<i2")
            frames = len(samples) // self._channels
            chunk = (
                samples[: frames * self._channels]
                .reshape(frames, self._channels)
                .mean(axis=1)
                .astype("<i2")
                .tobytes()
            )
        self._wav.writeframes(
            chunk
        )  # patches the header: the file is readable between streams

    def end(self, interrupted: bool) -> None:
        pass

    def close(self) -> None:
        """Finish the file."""
        if self._wav is not None:
            self._wav.close()
            self._wav = None


@dataclass
class Playback:
    """One stream as a `MemorySink` received it; times are `time.monotonic()` seconds."""

    rate: int
    channels: int
    pcm: bytes = b""
    started_at: float = 0.0
    ended_at: float | None = None
    interrupted: bool = False

    @property
    def duration_s(self) -> float:
        return len(self.pcm) / (2.0 * self.channels * self.rate)


class MemorySink:
    """Keeps every stream, for tests to assert on the audio actually played."""

    def __init__(self) -> None:
        self._playbacks: list[Playback] = []
        self._changed = threading.Condition()

    @property
    def playbacks(self) -> list[Playback]:
        with self._changed:
            return [dataclasses.replace(p) for p in self._playbacks]

    def wait_for(
        self, predicate: Callable[[Playback], bool], timeout: float = 5.0
    ) -> Playback:
        """The first ended playback the predicate accepts."""
        end = time.monotonic() + timeout
        with self._changed:
            while True:
                for p in self._playbacks:
                    if p.ended_at is not None and predicate(p):
                        return dataclasses.replace(p)
                left = end - time.monotonic()
                if left <= 0:
                    raise TimeoutError(f"no matching playback in {timeout} s")
                self._changed.wait(left)

    def begin(self, rate: int, channels: int) -> None:
        with self._changed:
            self._playbacks.append(
                Playback(rate, channels, started_at=time.monotonic())
            )
            self._changed.notify_all()

    def feed(self, chunk: bytes) -> None:
        with self._changed:
            self._playbacks[-1].pcm += chunk

    def end(self, interrupted: bool) -> None:
        with self._changed:
            current = self._playbacks[-1]
            current.ended_at = time.monotonic()
            current.interrupted = interrupted
            self._changed.notify_all()


def _sleep_until(deadline: float) -> None:
    left = deadline - time.monotonic()
    if left > 0:
        time.sleep(left)


class AudioOutput:
    """Plays one stream at a time into its sink, the newest wins."""

    def __init__(
        self,
        sink: AudioSink,
        on_event: Callable[[dict], None] | None = None,
    ):
        self.sink = sink
        self._on_event = on_event or (lambda e: log.debug("audio output: %s", e))
        self._lock = threading.Lock()  # generations
        self._sink_lock = threading.Lock()  # one stream in the sink at a time
        self._gen = 0
        self._stopped_gen = 0  # a stop cuts this generation and the older ones
        # When the audio fed so far finishes playing (time.monotonic()); read by the
        # microphone gate from other threads, a float assignment being atomic.
        self.playing_until = 0.0

    def _cut(self, gen: int) -> bool:
        return gen != self._gen or gen <= self._stopped_gen

    def play_stream(self, rfile: io.BufferedIOBase, header: dict) -> None:
        rate = int(header.get("rate", 22050))
        channels = int(header.get("channels", 1))
        bytes_per_s = 2 * channels * rate
        chunk_bytes = int(rate * CHUNK_S) * 2 * channels
        with self._lock:
            self._gen += 1
            gen = self._gen
        # The current stream sees it is stale at its next chunk and leaves the sink.
        with self._sink_lock:
            if self._cut(gen):
                return  # a newer stream or a stop came while waiting
            self._on_event({"event": "start", "rate": rate, "channels": channels})
            fed = 0
            completed = False
            try:
                self.sink.begin(rate, channels)
                while True:
                    data = rfile.read(chunk_bytes)
                    if not data:
                        completed = True
                        break
                    if self._cut(gen):
                        self._on_event(
                            {
                                "event": "interrupted",
                                "played_s": round(fed / bytes_per_s, 3),
                            }
                        )
                        break
                    self.sink.feed(data)
                    fed += len(data)
                    start = max(self.playing_until, time.monotonic())
                    self.playing_until = start + len(data) / bytes_per_s
                    # One chunk ahead, so a device never runs dry.
                    _sleep_until(self.playing_until - CHUNK_S)
                if completed:
                    _sleep_until(self.playing_until)
            finally:
                if not completed:
                    self.playing_until = time.monotonic()
                self.sink.end(interrupted=not completed)
                self._on_event(
                    {"event": "end", "played_s": round(fed / bytes_per_s, 3)}
                )

    def stop(self) -> None:
        with self._lock:
            self._stopped_gen = self._gen
        self.playing_until = min(self.playing_until, time.monotonic())
        self._on_event({"event": "stop-request"})


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline()
        try:
            header = json.loads(line.decode() or "{}")
        except ValueError:
            return
        assert isinstance(self.server, Server)
        audio_output = self.server.audio_output
        if header.get("cmd") == "stop":
            audio_output.stop()
            return
        if header.get("cmd") == "play":
            audio_output.play_stream(self.rfile, header)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr, audio_output: AudioOutput):
        super().__init__(addr, Handler)
        self.audio_output = audio_output
