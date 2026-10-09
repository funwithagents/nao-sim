#!/bin/bash
# Start naoqi-bin, then load the nao-sim override modules into its process.
# The desktop naoqi-bin ignores the [python] section of autoload.ini, so we load modules
# through ALLauncher.launchPythonModule (= `from <module> import *` in ALPythonBridge's
# embedded Python 2.7 interpreter, same process as naoqi-bin on 2.1, naoqi-service on 2.8).
#
# The script ends with `[entrypoint] nao-sim ready` only when the whole sequence succeeded and
# every replaced service answers again; any failure exits non-zero so the container shows as
# exited rather than as a half-robot. NAO_SIM_* variables are documented in specs/container.md;
# NAO_SIM_POLL_INTERVAL (seconds between polls, default 1) exists for the host-side tests.
set -u
NAOQI_HOME=${NAOQI_HOME:-/opt/naoqi}
cd "$NAOQI_HOME"
INTERVAL=${NAO_SIM_POLL_INTERVAL:-1}
READY_SERVICE=${NAO_SIM_READY_SERVICE:-ALDialog}

NAOQI_PID=
fail() {
  echo "[entrypoint] $1"
  [ -n "$NAOQI_PID" ] && kill -TERM "$NAOQI_PID" 2>/dev/null
  exit 1
}

# Modules in NAO_SIM_DEFER_MODULES are removed from the autoload file and loaded after our
# overrides with ALLauncher.launchLocal, so they bind to the replaced services, not the built-ins.
AUTOLOAD=$NAOQI_HOME/etc/naoqi/autoload.ini
if [ -n "${NAO_SIM_DEFER_MODULES:-}" ]; then
  AUTOLOAD=${TMPDIR:-/tmp}/autoload.ini
  cp "$NAOQI_HOME/etc/naoqi/autoload.ini" "$AUTOLOAD"
  for m in $NAO_SIM_DEFER_MODULES; do  # no `sed -i`: its syntax differs between GNU and BSD sed
    sed "s/^$m\$/#deferred $m/" "$AUTOLOAD" > "$AUTOLOAD.tmp" && mv "$AUTOLOAD.tmp" "$AUTOLOAD"
  done
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
naoqi-bin $LISTEN_ARGS --autoload-file "$AUTOLOAD" "$@" &
NAOQI_PID=$!
trap 'kill -TERM $NAOQI_PID 2>/dev/null' TERM INT

# NAOqi is ready when every service the sequence touches is registered AND the service list has
# stopped changing for NAO_SIM_SETTLE_POLLS polls. On a slow (cold-cache) boot of 2.8, the ready
# service appears while naoqi-service is still loading modules, and exiting a built-in or loading a
# module into a half-started process kills it; waiting for the list to settle avoids that race.
URL=tcp://127.0.0.1:$INTERNAL_PORT
TRIES=${NAO_SIM_READY_TRIES:-120}
SETTLE=${NAO_SIM_SETTLE_POLLS:-3}
REQUIRED="ALLauncher ALPythonBridge ${NAO_SIM_EXIT_MODULES:-} $READY_SERVICE"
ready=
previous=
stable=0
for i in $(seq 1 "$TRIES"); do
  services=$(qicli info --qi-url $URL 2>/dev/null | sed -n 's/^[0-9]* \[\(.*\)\]$/\1/p')
  present=1
  for s in $REQUIRED; do
    printf '%s\n' "$services" | grep -qx "$s" || present=
  done
  if [ -n "$present" ]; then
    if [ "$services" = "$previous" ]; then stable=$((stable + 1)); else stable=0; fi
    if [ "$stable" -ge "$SETTLE" ]; then ready=1; break; fi
  else
    stable=0
  fi
  previous=$services
  if ! kill -0 "$NAOQI_PID" 2>/dev/null; then fail "naoqi-bin exited"; fi
  sleep "$INTERVAL"
done
[ -n "$ready" ] || fail "NAOqi not ready after $TRIES polls (waiting for $REQUIRED and a stable service list): giving up"
echo "[entrypoint] NAOqi ready after $i polls, $(printf '%s\n' "$services" | wc -l | tr -d ' ') services"

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
  sleep "$INTERVAL"
done
qicli call ALPythonBridge.eval "import sys; sys.path.insert(0, '$NAOQI_HOME/modules')" --qi-url $URL >/dev/null \
  || fail "ALPythonBridge.eval failed"
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

# launchPythonModule does not report an import failure: check that every replaced name answers
# again, otherwise the built-in is gone and nothing took its place.
for m in ${NAO_SIM_EXIT_MODULES:-}; do
  answered=
  for i in $(seq 1 10); do
    if qicli info "$m" --qi-url $URL >/dev/null 2>&1; then answered=1; break; fi
    sleep "$INTERVAL"
  done
  [ -n "$answered" ] || fail "replaced service $m does not answer after loading the modules"
done
qicli call NaoSim.setReady --qi-url $URL >/dev/null 2>&1 || fail "NaoSim.setReady failed: the status module is not loaded"
echo "[entrypoint] nao-sim ready"
wait "$NAOQI_PID"
