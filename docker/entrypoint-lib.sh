# What both versions' entrypoints share (entrypoint-2.1.sh, entrypoint-2.8.sh source it): starting
# naoqi-bin, waiting for a settled service list, removing built-ins, loading our Python modules,
# checking the replacements answer, and marking boot complete. Each version's script reads as its
# exact procedure; see specs/container/container.md ("Entrypoint") and specs/container/service-replacement.md.
#
# Any failure exits non-zero after terminating naoqi-bin, so a failed boot shows as an exited
# container, never as a half-robot. Tunables (images never change them; the host-side tests do):
# NAO_SIM_READY_TRIES, NAO_SIM_SETTLE_POLLS, NAO_SIM_POLL_INTERVAL, NAOQI_HOME.
set -u
NAOQI_HOME=${NAOQI_HOME:-/opt/naoqi}
cd "$NAOQI_HOME"
INTERVAL=${NAO_SIM_POLL_INTERVAL:-1}
TRIES=${NAO_SIM_READY_TRIES:-120}
SETTLE=${NAO_SIM_SETTLE_POLLS:-3}
NAOQI_PID=
URL=

log() { echo "[entrypoint] $*"; }

fail() {
  log "$1"
  [ -n "$NAOQI_PID" ] && kill -TERM "$NAOQI_PID" 2>/dev/null
  exit 1
}

# call <Service.method> [args...]: a qicli call to NAOqi from inside the container.
call() { qicli call "$@" --qi-url "$URL"; }

# autoload_without [entries...]: the path of an autoload file without those entries (commented out
# in a copy), or the suite's own file when there are none.
autoload_without() {
  local autoload=$NAOQI_HOME/etc/naoqi/autoload.ini
  [ $# -eq 0 ] && { echo "$autoload"; return; }
  local copy=${TMPDIR:-/tmp}/autoload.ini
  cp "$autoload" "$copy"
  for m in "$@"; do  # no `sed -i`: its syntax differs between GNU and BSD sed
    sed "s/^$m\$/#deferred $m/" "$copy" > "$copy.tmp" && mv "$copy.tmp" "$copy"
  done
  echo "$copy"
}

# start_naoqi <url the entrypoint reaches NAOqi on> <naoqi-bin arguments...>
start_naoqi() {
  URL=$1
  shift
  naoqi-bin "$@" &
  NAOQI_PID=$!
  trap 'kill -TERM $NAOQI_PID 2>/dev/null' TERM INT
}

# wait_for_naoqi <services...>: until every one is registered AND the service list has not changed
# for SETTLE polls. On a slow (cold-cache) 2.8 boot the last service appears while naoqi-service is
# still loading modules, and exiting a built-in or loading a module then kills it.
wait_for_naoqi() {
  local services previous= stable=0 present i
  for i in $(seq 1 "$TRIES"); do
    services=$(qicli info --qi-url "$URL" 2>/dev/null | sed -n 's/^[0-9]* \[\(.*\)\]$/\1/p')
    present=1
    for s in "$@"; do
      printf '%s\n' "$services" | grep -qx "$s" || present=
    done
    if [ -n "$present" ]; then
      if [ "$services" = "$previous" ]; then stable=$((stable + 1)); else stable=0; fi
      if [ "$stable" -ge "$SETTLE" ]; then
        log "NAOqi ready after $i polls, $(printf '%s\n' "$services" | wc -l | tr -d ' ') services"
        return
      fi
    else
      stable=0
    fi
    previous=$services
    kill -0 "$NAOQI_PID" 2>/dev/null || fail "naoqi-bin exited"
    sleep "$INTERVAL"
  done
  fail "NAOqi not ready after $TRIES polls (waiting for $* and a stable service list): giving up"
}

# exit_builtins <names...>: built-ins we replace leave the broker and the ServiceDirectory first,
# or in-process modules keep finding them.
exit_builtins() {
  for m in "$@"; do
    log "exiting built-in $m"
    call "$m.exit"
    sleep "$INTERVAL"
  done
}

# load_modules <modules...>: `from <module> import *` in ALPythonBridge's embedded Python 2.7
# (naoqi-bin's own interpreter ignores the [python] section of autoload.ini), in order.
load_modules() {
  call ALPythonBridge.eval "import sys; sys.path.insert(0, '$NAOQI_HOME/modules')" >/dev/null \
    || fail "ALPythonBridge.eval failed"
  for m in "$@"; do
    log "loading module $m"
    call ALLauncher.launchPythonModule "$m"
  done
}

# load_relay <path>: the native relay, a C++ module (specs/container/service-replacement.md, "Binary
# arguments: the native relay"), loaded with launchLocal like a built-in; it must register a module.
load_relay() {
  local out
  log "loading the native relay $1"
  out=$(call ALLauncher.launchLocal "$1" 2>&1) || fail "loading the relay $1 failed: $out"
  printf '%s\n' "$out" | grep -q '\[ *"' || fail "the relay $1 registered no module: $out"
}

# launch_local <entries...>: ALLauncher.launchLocal each autoload entry, in order. It answers with the
# modules the library registered (`[ "ALBasicAwareness" ]`); an empty list means it registered none.
launch_local() {
  local out
  for m in "$@"; do
    log "launching built-in $m"
    out=$(call ALLauncher.launchLocal "$m" 2>&1) || fail "launching $m failed: $out"
    printf '%s\n' "$out" | grep -q '\[ *"' || fail "launching $m registered no module: $out"
  done
}

# check_answer <replaced|added> <names...>: launchPythonModule does not report an import failure, so
# every replaced name must answer again (otherwise the built-in is gone and nothing took its place),
# and every name our modules add must answer.
check_answer() {
  local what=$1 answered i
  shift
  for m in "$@"; do
    answered=
    for i in $(seq 1 10); do
      if qicli info "$m" --qi-url "$URL" >/dev/null 2>&1; then answered=1; break; fi
      sleep "$INTERVAL"
    done
    [ -n "$answered" ] || fail "$what service $m does not answer after loading the modules"
  done
}

# mark_ready: the whole sequence succeeded. Then wait on naoqi-bin (signals are forwarded to it).
mark_ready() {
  call NaoSim.setReady >/dev/null 2>&1 || fail "NaoSim.setReady failed: the status module is not loaded"
  log "nao-sim ready"
  wait "$NAOQI_PID"
}
