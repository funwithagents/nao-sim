#!/bin/bash
# Docker healthcheck: healthy once the NaoSim service, reached on the public port (2.8: through
# the suite's gateway, 2.1: the broker), says the entrypoint finished and the replacements answer.
out=$(qicli call NaoSim.isReady --qi-url "tcp://127.0.0.1:${NAO_SIM_PUBLIC_PORT:-9559}" 2>/dev/null) || exit 1
# 2.1's qicli prints `NaoSim.isReady: true`; 2.8's prints `true` and then its [W] warnings on stdout.
first=${out%%$'\n'*}
case "${first##*: }" in
  true) exit 0 ;;
  *) exit 1 ;;
esac
