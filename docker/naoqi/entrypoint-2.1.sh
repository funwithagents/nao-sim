#!/bin/bash
# NAOqi 2.1 entrypoint. One naoqi-bin process holds every module and is itself the broker on the
# public port 9559; our modules are naoqi.ALModule objects registered on that broker.
#
# Replacing ALTextToSpeech: the in-process modules that hold a proxy to it are left out of the
# autoload file, the built-in exits, our modules load (its Python core among them), its C++ front
# takes the name, then those modules are launched and bind to our replacement (specs/container/service-replacement.md, "Replacing a built-in"). They are launched with
# the built-ins a NAO autoloads but the desktop suite does not, in a NAO's autoload order
# (specs/container/container.md, "Matching a NAO's modules").
. "$(dirname "$0")/entrypoint-lib.sh"

REPLACED="ALTextToSpeech"                              # built-ins our modules take over
RELAY="$NAOQI_HOME/lib/nao-sim/libnao_sim_audio_device_relay.so" # the native relay, loaded before our modules
MODULES="nao_sim_status_almodule nao_sim_speech_almodule nao_sim_audio_device_almodule" # ours, in load order
FRONTS="$NAOQI_HOME/lib/nao-sim/libnao_sim_speech_front.so"      # C++ fronts taking the replaced names, after them
ADDED="ALAudioDevice _NaoSimAudioRelay _NaoSimTextToSpeech" # names no built-in holds, which we register
LATE="expressiveness animatedspeech basicawareness autonomousblinking autonomousmoves autonomouslife dialog"
# LATE, launched after our modules in a NAO's autoload order:
#   animatedspeech, dialog       hold a proxy to ALTextToSpeech (deferred from the autoload file)
#   expressiveness, basicawareness, autonomousblinking, autonomousmoves
#                                a NAO autoloads them, the desktop suite does not
#   autonomouslife               a NAO loads it after those (deferred from the autoload file)
LAST_SERVICE="ALPanoramaCompass"                       # registered last at boot, once LATE is out

start_naoqi tcp://127.0.0.1:9559 \
  -b 0.0.0.0 -p 9559 --autoload-file "$(autoload_without $LATE)" "$@"
wait_for_naoqi ALLauncher ALPythonBridge $REPLACED $LAST_SERVICE
exit_builtins $REPLACED
load_native "$RELAY"
load_modules $MODULES
for front in $FRONTS; do load_native "$front"; done
launch_local $LATE
check_answer replaced $REPLACED
check_answer added $ADDED
mark_ready
