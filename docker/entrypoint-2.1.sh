#!/bin/bash
# NAOqi 2.1 entrypoint. One naoqi-bin process holds every module and is itself the broker on the
# public port 9559; our modules are naoqi.ALModule objects registered on that broker.
#
# Replacing ALTextToSpeech: the in-process modules that hold a proxy to it are left out of the
# autoload file, the built-in exits, our modules load, then those modules are launched and bind to
# our replacement (specs/container/service-replacement.md, "Replacing a built-in"). They are launched with
# the built-ins a NAO autoloads but the desktop suite does not, in a NAO's autoload order
# (specs/container/container.md, "Matching a NAO's modules").
. "$(dirname "$0")/entrypoint-lib.sh"

REPLACED="ALTextToSpeech"                              # built-ins our modules take over
MODULES="nao_sim_status_almodule nao_sim_tts_almodule" # ours, in load order
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
load_modules $MODULES
launch_local $LATE
check_answer $REPLACED
mark_ready
