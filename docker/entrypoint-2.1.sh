#!/bin/bash
# NAOqi 2.1 entrypoint. One naoqi-bin process holds every module and is itself the broker on the
# public port 9559; our modules are naoqi.ALModule objects registered on that broker.
#
# Replacing ALTextToSpeech: the in-process modules that hold a proxy to it are left out of the
# autoload file, the built-in exits, our modules load, then those modules are launched and bind to
# our replacement (specs/service-replacement.md, "Replacing a built-in").
. "$(dirname "$0")/entrypoint-lib.sh"

REPLACED="ALTextToSpeech"                              # built-ins our modules take over
MODULES="nao_sim_status_almodule nao_sim_tts_almodule" # ours, in load order
DEPENDENTS="animatedspeech dialog"                     # autoload entries holding a proxy to ALTextToSpeech
LAST_SERVICE="ALAutonomousLife"                        # registered last at boot

start_naoqi tcp://127.0.0.1:9559 \
  -b 0.0.0.0 -p 9559 --autoload-file "$(autoload_without $DEPENDENTS)" "$@"
wait_for_naoqi ALLauncher ALPythonBridge $REPLACED $LAST_SERVICE
exit_builtins $REPLACED
load_modules $MODULES
for m in $DEPENDENTS; do
  log "launching deferred module $m"
  call ALLauncher.launchLocal "$m"
done
check_answer $REPLACED
mark_ready
