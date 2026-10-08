#!/bin/bash
# Start naoqi-bin, then load the nao-sim override modules into its process.
# The desktop naoqi-bin ignores the [python] section of autoload.ini, so we load modules
# through ALLauncher.launchPythonModule (= `from <module> import *` in ALPythonBridge's
# embedded Python 2.7 interpreter, same process as naoqi-bin).
set -u
cd /opt/naoqi

# Modules in NAO_SIM_DEFER_MODULES are removed from the autoload file and loaded after our
# overrides with ALLauncher.launchLocal, so they bind to the replaced services, not the built-ins.
AUTOLOAD=/opt/naoqi/etc/naoqi/autoload.ini
if [ -n "${NAO_SIM_DEFER_MODULES:-}" ]; then
  AUTOLOAD=/tmp/autoload.ini
  cp /opt/naoqi/etc/naoqi/autoload.ini $AUTOLOAD
  for m in $NAO_SIM_DEFER_MODULES; do sed -i "s/^$m\$/#deferred $m/" $AUTOLOAD; done
fi
# Where naoqi-bin listens. 2.1: the broker itself is the public port. 2.8: naoqi-bin should listen
# on an internal loopback port so the suite's qi-secure-gateway (core package) can take 0.0.0.0:9559
# and relay every service process through that single port, as on a real NAO 6.
INTERNAL_PORT=${NAO_SIM_INTERNAL_PORT:-9559}
if [ -n "${NAO_SIM_LISTEN_URL:-}" ]; then
  LISTEN_ARGS="--qi-listen-url $NAO_SIM_LISTEN_URL"
else
  LISTEN_ARGS="-b 0.0.0.0 -p $INTERNAL_PORT"
fi
naoqi-bin $LISTEN_ARGS --autoload-file $AUTOLOAD "$@" &
NAOQI_PID=$!
trap 'kill -TERM $NAOQI_PID 2>/dev/null' TERM INT

URL=tcp://127.0.0.1:$INTERNAL_PORT
for i in $(seq 1 120); do
  if qicli info ALLauncher --qi-url $URL >/dev/null 2>&1 && qicli info ${NAO_SIM_READY_SERVICE:-ALDialog} --qi-url $URL >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 $NAOQI_PID 2>/dev/null; then echo "[entrypoint] naoqi-bin exited"; exit 1; fi
  sleep 1
done

# 2.8: services that hold a proxy to a replaced module run in their own process under
# ALServiceManager; stop them before the replacement and start them again after.
for svc in ${NAO_SIM_RESTART_SERVICES:-}; do
  echo "[entrypoint] stopping service $svc"
  qicli call ALServiceManager.stopService "$svc" --qi-url $URL
done
# Built-ins we replace must leave the broker first, or in-process modules keep finding them.
for m in ${NAO_SIM_EXIT_MODULES:-}; do
  echo "[entrypoint] exiting built-in $m"
  qicli call "$m.exit" --qi-url $URL
  sleep 1
done
qicli call ALPythonBridge.eval "import sys; sys.path.insert(0, '/opt/naoqi/modules')" --qi-url $URL >/dev/null
for m in ${NAO_SIM_MODULES:-}; do
  echo "[entrypoint] loading module $m"
  qicli call ALLauncher.launchPythonModule "$m" --qi-url $URL
done
for svc in ${NAO_SIM_RESTART_SERVICES:-}; do
  echo "[entrypoint] starting service $svc"
  qicli call ALServiceManager.startService "$svc" --qi-url $URL
done
for m in ${NAO_SIM_DEFER_MODULES:-}; do
  echo "[entrypoint] launching deferred module $m"
  qicli call ALLauncher.launchLocal "$m" --qi-url $URL
done
echo "[entrypoint] nao-sim ready"
wait $NAOQI_PID
