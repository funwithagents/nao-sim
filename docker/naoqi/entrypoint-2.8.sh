#!/bin/bash
# NAOqi 2.8 entrypoint. naoqi-bin is a launcher on the loopback port 9558: the classic modules run
# in naoqi-service, the suite's packages run as services under ALServiceManager, and the core
# package's qi-secure-gateway serves the public port 9559, relaying every process, as on a NAO 6.
# Our modules are qi.Session services in naoqi-service, which connect to NAOQI_SIM_INTERNAL_PORT.
#
# Replacing ALTextToSpeech and ALAudioPlayer: the package services whose code calls them are
# stopped (last started, first stopped), the built-ins exit, our modules load (their Python cores
# among them), the C++ fronts take the names with the hidden signals ALAnimatedSpeech connects to,
# then those services start again, in boot order, and bind to them
# (specs/container/service-replacement.md, "Replacing a built-in").
. "$(dirname "$0")/entrypoint-lib.sh"

REPLACED="ALTextToSpeech ALAudioPlayer"                                   # built-ins our modules take over
RELAY="$NAOQI_HOME/lib/naoqi-sim/libnaoqi_sim_audio_device_relay.so"     # the native relay, loaded before our modules
MODULES="naoqi_sim_status_qiservice naoqi_sim_speech_qiservice naoqi_sim_audio_device_qiservice naoqi_sim_audio_player_qiservice" # ours, in load order
FRONTS="$NAOQI_HOME/lib/naoqi-sim/libnaoqi_sim_speech_front.so $NAOQI_HOME/lib/naoqi-sim/libnaoqi_sim_audio_player_front.so"           # C++ fronts taking the replaced names, after them
ADDED="ALAudioDevice _NaoqiSimAudioRelay _NaoqiSimTextToSpeech _NaoqiSimAudioPlayer" # names no built-in holds, which we register
# Package services whose code names ALTextToSpeech or ALAudioPlayer, in boot order: started before
# the replacement, ALDialog kept calling the exited built-in ("module destroyed").
DEPENDENTS="dialog.dialog dialog.Conversation expressivity.thinkingexpression expressivity.expressiveness expressivity.notificationreader expressivity.autonomousabilitiesmodules life.autonomouslife"
LAST_SERVICE="ALPanoramaCompass"                            # registered last at boot

export NAOQI_SIM_INTERNAL_PORT=9558  # inherited by naoqi-service, where our modules read it
start_naoqi tcp://127.0.0.1:9558 \
  --qi-listen-url tcp://127.0.0.1:9558 --autoload-file "$(autoload_without)" "$@"
wait_for_naoqi ALLauncher ALPythonBridge $REPLACED $LAST_SERVICE
reversed=""
for svc in $DEPENDENTS; do reversed="$svc $reversed"; done
for svc in $reversed; do
  log "stopping service $svc"
  call ALServiceManager.stopService "$svc"
done
exit_builtins $REPLACED
load_native "$RELAY"
load_modules $MODULES
for front in $FRONTS; do load_native "$front"; done
for svc in $DEPENDENTS; do
  log "starting service $svc"
  call ALServiceManager.startService "$svc"
done
check_answer replaced $REPLACED
check_answer added $ADDED
mark_ready
