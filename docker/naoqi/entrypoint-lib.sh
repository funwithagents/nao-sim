# What both versions' entrypoints share (entrypoint-2.1.sh, entrypoint-2.8.sh source it): writing the
# autoload copy our modules load from (in place of the built-ins they replace), starting naoqi-bin,
# waiting for a settled service list, checking the replacements answer, and marking boot complete. Each version's script reads as its
# exact procedure; see specs/container/container.md ("Entrypoint") and specs/container/service-replacement.md.
#
# Any failure exits non-zero after terminating naoqi-bin, so a failed boot shows as an exited
# container, never as a half-robot. Tunables (images never change them; the host-side tests do):
# NAOQI_SIM_READY_TRIES, NAOQI_SIM_SETTLE_POLLS, NAOQI_SIM_POLL_INTERVAL, NAOQI_HOME.
set -u
NAOQI_HOME=${NAOQI_HOME:-/opt/naoqi}
cd "$NAOQI_HOME"
INTERVAL=${NAOQI_SIM_POLL_INTERVAL:-1}
TRIES=${NAOQI_SIM_READY_TRIES:-120}
SETTLE=${NAOQI_SIM_SETTLE_POLLS:-3}
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

# write_autoload <left out entries> [<anchor>:<entry>,<entry>...]...: AUTOLOAD, a copy of the suite's
# autoload.ini with the left out entries commented out (`#replaced <entry>`) and each anchor's
# entries inserted right after it, in order. A missing entry or anchor fails the boot: a suite
# without them would otherwise boot without our modules.
write_autoload() {
  local suite=$NAOQI_HOME/etc/naoqi/autoload.ini left=$1 item
  shift
  AUTOLOAD=${TMPDIR:-/tmp}/autoload.ini
  for item in $left "${@%%:*}"; do
    grep -qx "$item" "$suite" || fail "$suite has no entry $item"
  done
  awk -v left="$left" -v inserts="$*" '
    BEGIN {
      n = split(left, l, " "); for (i = 1; i <= n; i++) out[l[i]] = 1
      n = split(inserts, s, " "); for (i = 1; i <= n; i++) { split(s[i], kv, ":"); after[kv[1]] = kv[2] }
    }
    {
      if ($0 in out) print "#replaced " $0; else print
      if ($0 in after) { n = split(after[$0], e, ","); for (i = 1; i <= n; i++) print e[i] }
    }' "$suite" > "$AUTOLOAD" || fail "writing $AUTOLOAD failed"
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
# for SETTLE polls: NAOqi finished booting (on 2.8 the package services keep registering for a few
# seconds after naoqi-service's last autoload entry).
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

# check_answer <what> <names...>: every name must answer. Our modules load inside NAOqi's boot, where
# an import failure (launchPythonModule does not report one) or a library that registers nothing
# shows only as a missing name: a replaced name (the built-in is left out and nothing took its
# place), a name our modules add, or a built-in we add to the autoload.
check_answer() {
  local what=$1 answered i
  shift
  for m in "$@"; do
    answered=
    for i in $(seq 1 10); do
      if qicli info "$m" --qi-url "$URL" >/dev/null 2>&1; then answered=1; break; fi
      sleep "$INTERVAL"
    done
    [ -n "$answered" ] || fail "$what service $m does not answer once NAOqi booted"
  done
}

# mark_ready: the whole sequence succeeded. Then wait on naoqi-bin (signals are forwarded to it).
mark_ready() {
  call NaoqiSim.setReady >/dev/null 2>&1 || fail "NaoqiSim.setReady failed: the status module is not loaded"
  log "naoqi-sim ready"
  wait "$NAOQI_PID"
}
