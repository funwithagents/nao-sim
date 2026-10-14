#!/bin/bash
# NAOqi 2.8 entrypoint. naoqi-bin is a launcher on the loopback port 9558: the classic modules run
# in naoqi-service, the suite's packages run as services under ALServiceManager, and the core
# package's qi-secure-gateway serves the public port 9559, relaying every process, as on a NAO 6.
# Our modules are qi.Session services in naoqi-service, which connect to NAOQI_SIM_INTERNAL_PORT.
#
# Our modules take the place of ALTextToSpeech and ALAudioPlayer in NAOqi's own boot: naoqi-service
# loads an autoload copy without the built-ins' libraries and with ours right after pythonbridge
# (the relay, the loader, which loads our Python modules, then the C++ fronts, with the hidden
# signals ALAnimatedSpeech connects to). The package services that call them (ALDialog,
# ALAnimatedSpeech...) register after them (specs/container/service-replacement.md, "Replacing a
# built-in"; specs/container/container.md, "Entrypoint").
. "$(dirname "$0")/entrypoint-lib.sh"

LEFT_OUT="audioplayer ttsinterface"       # ALAudioPlayer's and ALTextToSpeech's libraries
OURS="naoqi_sim_audio_device_relay,naoqi_sim_loader,naoqi_sim_speech_front,naoqi_sim_audio_player_front"
MODULES="naoqi_sim_status_qiservice naoqi_sim_speech_qiservice naoqi_sim_audio_device_qiservice naoqi_sim_audio_player_qiservice" # ours, loaded by the loader in order
REPLACED="ALTextToSpeech ALAudioPlayer"   # the built-in names our C++ fronts take
ADDED="ALAudioDevice _NaoqiSimAudioRelay _NaoqiSimTextToSpeech _NaoqiSimAudioPlayer" # names no built-in holds, which we register
# Registered last at boot: the last autoload entry, and the package services that call our modules.
LAST="ALPanoramaCompass ALAnimatedSpeech ALDialog ALAutonomousLife"

write_autoload "$LEFT_OUT" "pythonbridge:$OURS"
export NAOQI_SIM_PYTHON_MODULES="$MODULES" NAOQI_SIM_MODULES_DIR="$NAOQI_HOME/modules"
export NAOQI_SIM_INTERNAL_PORT=9558  # inherited by naoqi-service, where our modules read it
start_naoqi tcp://127.0.0.1:9558 \
  --qi-listen-url tcp://127.0.0.1:9558 --autoload-file "$AUTOLOAD" "$@"
wait_for_naoqi ALLauncher ALPythonBridge $LAST
check_answer replaced $REPLACED
check_answer added $ADDED
mark_ready
