# nao-sim speech engine container: Piper (onnxruntime) with eSpeak NG underneath.
# Native architecture (no emulation). Knows nothing about NAOqi: it synthesizes a list of
# text / mark / pause items, streams PCM to the host audio output and returns the timings.
FROM python:3.12-slim

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends espeak-ng curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir piper-tts numpy

# Voices (MIT / CC licensed models from rhasspy/piper-voices). One per NAOqi language name.
ARG VOICE_BASE=https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0
WORKDIR /voices
RUN for v in en/en_US/lessac/medium/en_US-lessac-medium fr/fr_FR/siwis/medium/fr_FR-siwis-medium; do \
      n=$(basename $v); curl -sSL -o $n.onnx $VOICE_BASE/$v.onnx && curl -sSL -o $n.onnx.json $VOICE_BASE/$v.onnx.json; \
    done && ls -la /voices

COPY server.py /app/server.py
ENV NAO_SIM_SOUNDCARD=host.docker.internal:9562 \
    NAO_SIM_TTS_ENGINE=piper
EXPOSE 8080
CMD ["python", "-u", "/app/server.py"]
