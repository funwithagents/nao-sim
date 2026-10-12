# -*- coding: utf-8 -*-
"""The ALAudioPlayer replacement's logic (Python 2.7, inside NAOqi; importable under Python 3 for
the host-side tests): specs/services/audio-player.md.

ALAudioPlayer itself is the C++ front (nao_sim_audio_player_front.cpp), which gives every play
call its NAOqi task id and polls it here, so callers start, wait for and stop a sound by task id
as on a NAO. This core decodes the file with the suite's libsndfile (`sndfile-convert`, WAV, OGG,
FLAC: what a virtual robot plays), and plays each task as its own stream of the host audio
output, `player:<id>`, which mixes it with the speech and the other sounds.

Used by nao_sim_audio_player_almodule (2.1, ALModule) and nao_sim_audio_player_qiservice (2.8, qi
service), which register it as the hidden _NaoSimAudioPlayer.
"""
import json
import math
import os
import socket
import struct
import subprocess
import tempfile
import threading
import time
import wave

SOUNDCARD = os.environ.get("NAO_SIM_SOUNDCARD", "host.docker.internal:9562")
SNDFILE_CONVERT = os.environ.get("NAO_SIM_SNDFILE_CONVERT", "/opt/naoqi/bin/sndfile-convert")
# Where the package store unpacks packages; a sound set is a package named soundset<name>.
APPS = os.environ.get("NAO_SIM_APPS", "/home/nao/.local/share/PackageManager/apps")
FIRST_OWN_ID = 1000000  # loaded files and blocking calls: above any task id the broker gives
CHUNK_S = 0.05  # what each send carries
SINE_RATE = 22050
SOUND_EXTENSIONS = (".ogg", ".wav", ".flac")


class PlayerError(Exception):
    """A call the player refuses, with the message a caller sees."""


def decode(path):
    """(rate, channels, s16le pcm) of a sound file, through the suite's libsndfile."""
    if not os.path.isfile(path):
        raise PlayerError("file not found: %s" % path)
    try:
        return _read_wav(path)
    except (wave.Error, EOFError, PlayerError):
        pass
    fd, out = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        env = dict(os.environ)
        env["LD_LIBRARY_PATH"] = "/opt/naoqi/lib:" + env.get("LD_LIBRARY_PATH", "")
        p = subprocess.Popen(
            [SNDFILE_CONVERT, "-pcm16", path, out],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
        message = p.communicate()[0]
        if p.returncode != 0:
            text = message.decode("utf-8", "replace") if isinstance(message, bytes) else message
            raise PlayerError(
                "cannot play %s: %s" % (path, " ".join(text.split()) or "unknown format")
            )
        return _read_wav(out)
    finally:
        os.remove(out)


def _read_wav(path):
    w = wave.open(path, "rb")
    try:
        if w.getsampwidth() != 2:
            raise PlayerError("not 16-bit PCM")
        return w.getframerate(), w.getnchannels(), w.readframes(w.getnframes())
    finally:
        w.close()


def sine(frequency, gain, duration):
    """playSine's tone: mono s16le at SINE_RATE, gain in percent of full scale."""
    level = 32767.0 * max(0, min(100, gain)) / 100.0
    n = int(SINE_RATE * max(0.0, duration))
    samples = [int(level * math.sin(2 * math.pi * frequency * i / SINE_RATE)) for i in range(n)]
    return struct.pack("<%dh" % n, *samples)


class Task(object):
    """One playback: a stream of the audio output, `player:<id>`."""

    def __init__(self, tid, rate, channels, pcm, volume, pan, loop, position, file_id=None):
        self.id = tid
        self.rate = rate
        self.channels = channels
        self.pcm = pcm
        self.volume = volume  # this task's own, before the master volume
        self.pan = pan
        self.loop = loop
        self.start_position = position
        self.file_id = file_id
        self.stopped = False
        self.paused_at = None
        self.paused_total = 0.0
        self.started = time.time()
        self.done = threading.Event()
        self.restart = None  # a goTo: the position to send from, on a new connection
        self.sock = None  # the connection to the audio output, while it plays

    @property
    def stream(self):
        return "player:%d" % self.id

    @property
    def length(self):
        return len(self.pcm) / (2.0 * self.channels * self.rate)

    def position(self):
        now = self.paused_at if self.paused_at is not None else time.time()
        played = max(0.0, now - self.started - self.paused_total)
        position = self.start_position + played
        if self.loop and self.length > 0:
            return position % self.length
        return min(position, self.length)


class Player(object):
    """The ALAudioPlayer contract; the front's long calls go through start/wait_done/stop_call."""

    def __init__(self, log=None, soundcard=None, apps=None):
        self.log = log or (lambda **f: None)
        self.soundcard = soundcard or SOUNDCARD
        self.apps = apps or APPS
        self.master = 1.0
        self.panorama = None  # setPanorama: overrides every task's pan once set
        self.tasks = {}  # id -> Task
        self.files = {}  # loaded file id -> path
        self.loaded_sets = []
        self._own_id = FIRST_OWN_ID - 1
        self._lock = threading.Lock()

    def new_id(self):
        with self._lock:
            self._own_id += 1
            return self._own_id

    # -- the front's long calls -----------------------------------------------------------
    def start(self, tid, kind, params):
        """Starts call `tid` (kind "file", "loaded", "soundset" or "sine"; params a JSON object)
        and returns at once; wait_done() follows it. A refused call raises PlayerError."""
        p = json.loads(params)
        volume = float(p.get("volume", 1.0))
        pan = float(p.get("pan", 0.0))
        loop = bool(p.get("loop", False))
        position = float(p.get("position", 0.0))
        file_id = None
        if kind == "loaded":
            file_id = int(p["id"])
            paused = self._paused_task_of(file_id)
            if paused is not None:  # play() of a paused file resumes it
                self._resume(paused)
                with self._lock:
                    self.tasks[tid] = paused
                return
            path = self.files.get(file_id)
            if path is None:
                raise PlayerError("no loaded file with id %d" % file_id)
            rate, channels, pcm = decode(path)
        elif kind == "file":
            rate, channels, pcm = decode(p["path"])
        elif kind == "soundset":
            rate, channels, pcm = decode(self._sound_set_file(p.get("set"), p["file"]))
        elif kind == "sine":
            rate, channels = SINE_RATE, 1
            pcm = sine(float(p["frequency"]), float(p["gain"]), float(p["duration"]))
            pan = max(-1.0, min(1.0, pan))
        else:
            raise PlayerError("unknown kind %r" % kind)
        task = Task(tid, rate, channels, pcm, volume, pan, loop, position, file_id)
        with self._lock:
            self.tasks[tid] = task
        self.log(method="start", id=tid, kind=kind, params=p, seconds=round(task.length, 3))
        t = threading.Thread(target=self._play, args=(task,), name="player-%d" % tid)
        t.daemon = True
        t.start()

    def wait_done(self, tid, timeout_s):
        """True once call `tid` is over (or unknown), waiting at most timeout_s."""
        task = self.tasks.get(tid)
        if task is None:
            return True
        if task.done.wait(timeout_s):
            with self._lock:
                if self.tasks.get(tid) is task:
                    del self.tasks[tid]
            return True
        return False

    def stop_call(self, tid):
        """stop(id), for a task id or a loaded file's id."""
        task = self.tasks.get(tid) or self._task_of_file(tid)
        if task is not None:
            self._stop(task)

    # -- playing ------------------------------------------------------------------------------
    def _play(self, task):
        position = task.start_position
        try:
            while not task.stopped:
                sent = self._stream(task, position)
                if task.restart is not None and not task.stopped:
                    position = task.restart
                    task.restart = None
                    continue
                if not sent:  # no audio output: keep the caller's clock
                    self._wait(task, task.length - position)
                break
        except Exception as e:  # noqa: BLE001 (logged; the call ends)
            self.log(method="play-failed", id=task.id, error=repr(e))
        finally:
            task.done.set()
            self.log(method="done", id=task.id, stopped=task.stopped)

    def _stream(self, task, position):
        """Sends the task from `position` to the audio output and returns once it has played;
        False if the audio output is unreachable."""
        host, port = self.soundcard.rsplit(":", 1)
        try:
            s = socket.create_connection((host, int(port)), timeout=5)
        except (socket.error, OSError) as e:
            self.log(method="audio-output-unreachable", error=repr(e))
            return False
        s.settimeout(None)
        task.sock = s
        frame = 2 * task.channels
        start = min(len(task.pcm), int(position * task.rate) * frame)
        chunk = max(frame, int(task.rate * CHUNK_S) * frame)
        header = {
            "cmd": "play",
            "stream": task.stream,
            "rate": task.rate,
            "channels": task.channels,
            "format": "s16le",
            "volume": task.volume * self.master,
            "pan": self._pan(task),
        }
        if task.restart is None:
            task.started = time.time()
            task.start_position = position
            task.paused_total = 0.0
        try:
            s.sendall((json.dumps(header) + "\n").encode("utf-8"))
            offset = start
            while not task.stopped and task.restart is None:
                if offset >= len(task.pcm):
                    if not task.loop or not task.pcm:
                        break
                    offset = 0
                end = min(len(task.pcm), offset + chunk)
                s.sendall(task.pcm[offset:end])
                offset = end
            if task.restart is not None:
                return True  # closed at once: the new play of the stream replaces this one
            try:
                s.shutdown(socket.SHUT_WR)
            except (socket.error, OSError):
                pass
            while s.recv(4096):  # the audio output closes once the stream has played
                pass
        except (socket.error, OSError):
            pass  # the audio output cut the stream (a stop), or a goTo closed it
        finally:
            task.sock = None
            s.close()
        return True

    def _wait(self, task, seconds):
        end = time.time() + max(0.0, seconds)
        while not task.stopped and time.time() < end:
            time.sleep(0.02)

    def _command(self, header):
        host, port = self.soundcard.rsplit(":", 1)
        try:
            s = socket.create_connection((host, int(port)), timeout=5)
            try:
                s.sendall((json.dumps(header) + "\n").encode("utf-8"))
            finally:
                s.close()
        except (socket.error, OSError) as e:
            self.log(method="audio-output-unreachable", error=repr(e), command=header)

    def _stop(self, task):
        task.stopped = True
        self._command({"cmd": "stop", "stream": task.stream})

    def _pan(self, task):
        return self.panorama if self.panorama is not None else task.pan

    def _set(self, task):
        self._command(
            {
                "cmd": "set",
                "stream": task.stream,
                "volume": task.volume * self.master,
                "pan": self._pan(task),
            }
        )

    def _resume(self, task):
        if task.paused_at is not None:
            task.paused_total += time.time() - task.paused_at
            task.paused_at = None
            self._command({"cmd": "resume", "stream": task.stream})

    def _task_of_file(self, file_id):
        for task in list(self.tasks.values()):
            if task.file_id == file_id and not task.done.is_set():
                return task
        return None

    def _paused_task_of(self, file_id):
        task = self._task_of_file(file_id)
        return task if task is not None and task.paused_at is not None else None

    def _task(self, tid):
        task = self.tasks.get(tid) or self._task_of_file(tid)
        if task is None:
            raise PlayerError("no task with id %d" % tid)
        return task

    # -- the rest of the contract ----------------------------------------------------------------
    def stop_all(self):
        for task in list(self.tasks.values()):
            self._stop(task)

    def pause(self, tid):
        task = self._task(tid)
        if task.paused_at is None:
            task.paused_at = time.time()
            self._command({"cmd": "pause", "stream": task.stream})

    def go_to(self, tid, position):
        task = self._task(tid)
        position = max(0.0, min(float(position), task.length))
        task.started = time.time()
        task.start_position = position
        task.paused_total = 0.0
        task.restart = position
        # The sender may have sent everything already: close its connection so it starts again
        # from the position; that newer play of the same stream replaces it in the audio output.
        sock = task.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except (socket.error, OSError):
                pass

    def get_current_position(self, tid):
        return self._task(tid).position()

    def get_file_length(self, tid):
        if tid in self.files:
            rate, channels, pcm = decode(self.files[tid])
            return len(pcm) / (2.0 * channels * rate)
        return self._task(tid).length

    def set_volume(self, tid, volume):
        task = self._task(tid)
        task.volume = float(volume)
        self._set(task)

    def get_volume(self, tid):
        return self._task(tid).volume

    def set_master_volume(self, volume):
        self.master = max(0.0, min(1.0, float(volume)))
        for task in list(self.tasks.values()):
            self._set(task)

    def get_master_volume(self):
        return self.master

    def set_panorama(self, pan):
        self.panorama = max(-1.0, min(1.0, float(pan)))
        for task in list(self.tasks.values()):
            self._set(task)

    def load_file(self, path):
        decode(path)  # refused now rather than at play time
        fid = self.new_id()
        self.files[fid] = path
        return fid

    def unload_file(self, fid):
        self.files.pop(fid, None)

    def unload_all_files(self):
        self.files.clear()

    def get_loaded_files_ids(self):
        return [str(fid) for fid in sorted(self.files)]

    def get_loaded_files_names(self):
        return [self.files[fid] for fid in sorted(self.files)]

    # -- sound sets: packages named soundset<name> in the package store ------------------------
    def _sound_set_dirs(self):
        found = {}
        if os.path.isdir(self.apps):
            for name in sorted(os.listdir(self.apps)):
                if name.lower().startswith("soundset") and len(name) > len("soundset"):
                    set_name = name[len("soundset"):]
                    found[set_name[0].upper() + set_name[1:]] = os.path.join(self.apps, name)
        return found

    def _set_dir(self, name):
        for set_name, path in self._sound_set_dirs().items():
            if set_name.lower() == str(name).lower():
                return set_name, path
        raise PlayerError("sound set not installed: %s" % name)

    def get_installed_sound_sets_list(self):
        return sorted(self._sound_set_dirs())

    def is_sound_set_installed(self, name):
        try:
            self._set_dir(name)
            return True
        except PlayerError:
            return False

    def load_sound_set(self, name):
        set_name, _ = self._set_dir(name)
        if set_name not in self.loaded_sets:
            self.loaded_sets.append(set_name)

    def unload_sound_set(self, name):
        self.loaded_sets = [s for s in self.loaded_sets if s.lower() != str(name).lower()]

    def get_loaded_sound_sets_list(self):
        return list(self.loaded_sets)

    def is_sound_set_loaded(self, name):
        return any(s.lower() == str(name).lower() for s in self.loaded_sets)

    def get_sound_set_file_names(self, name):
        _, path = self._set_dir(name)
        return sorted(
            os.path.splitext(f)[0]
            for f in os.listdir(path)
            if os.path.splitext(f)[1].lower() in SOUND_EXTENSIONS
        )

    def is_sound_set_file_installed(self, name, file_name):
        try:
            self._sound_set_file(name, file_name)
            return True
        except PlayerError:
            return False

    def _sound_set_file(self, name, file_name):
        """The path of a sound of a set (any loaded set when `name` is empty)."""
        names = [name] if name else list(self.loaded_sets)
        if not names:
            raise PlayerError("no sound set loaded")
        for set_name in names:
            _, path = self._set_dir(set_name)
            base = os.path.splitext(file_name)[0]
            for ext in ("",) + SOUND_EXTENSIONS:
                candidate = os.path.join(path, (file_name if not ext else base + ext))
                if os.path.isfile(candidate):
                    return candidate
        raise PlayerError("no sound %s in %s" % (file_name, ", ".join(names)))
