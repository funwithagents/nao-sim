#!/bin/bash
# NAOqi 2.8 entrypoint. naoqi-bin is a launcher on the loopback port 9558: the classic modules run
# in naoqi-service, the suite's packages run as services under ALServiceManager, and the core
# package's qi-secure-gateway serves the public port 9559, relaying every process, as on a NAO 6.
# Our modules are qi.Session services in naoqi-service, which connect to NAO_SIM_INTERNAL_PORT.
#
# Replacing ALTextToSpeech: the package service that holds a proxy to it is stopped, the built-in
# exits, our modules load, then that service starts again and binds to our replacement
# (specs/service-replacement.md, "Replacing a built-in").
. "$(dirname "$0")/entrypoint-lib.sh"

REPLACED="ALTextToSpeech"                                   # built-ins our modules take over
MODULES="nao_sim_status_qiservice nao_sim_tts_qiservice"    # ours, in load order
DEPENDENTS="expressivity.autonomousabilitiesmodules"        # package services holding a proxy to it (ALAnimatedSpeech)
LAST_SERVICE="ALPanoramaCompass"                            # registered last at boot

export NAO_SIM_INTERNAL_PORT=9558  # inherited by naoqi-service, where our modules read it
start_naoqi tcp://127.0.0.1:9558 \
  --qi-listen-url tcp://127.0.0.1:9558 --autoload-file "$(autoload_without)" "$@"
wait_for_naoqi ALLauncher ALPythonBridge $REPLACED $LAST_SERVICE
for svc in $DEPENDENTS; do
  log "stopping service $svc"
  call ALServiceManager.stopService "$svc"
done
exit_builtins $REPLACED
load_modules $MODULES
for svc in $DEPENDENTS; do
  log "starting service $svc"
  call ALServiceManager.startService "$svc"
done
check_answer $REPLACED
mark_ready
