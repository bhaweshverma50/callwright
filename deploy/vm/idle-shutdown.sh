#!/bin/bash
# Powers the realtime VM off after 15 idle minutes. Run every minute by callwright-idle.timer
# (install-idle.sh); every decision is printed, so it lands in journald:
#   journalctl -t callwright-idle -f
#
# Idle means ALL of these hold, checked each minute, for 15 consecutive minutes:
#   1. no LiveKit room has participants (RoomService.ListRooms on the local server);
#   2. the arq queue is empty (arq:queue, deferred jobs included) and no job is in progress
#      (arq:in-progress:* keys; the periodic cron housekeeping jobs are ignored);
#   3. the API has not been used for 15 minutes (cw:last_api_activity, written by the API).
# Any check that cannot be read counts as busy, so a broken check keeps the VM up.
#
# Safety: nothing happens in the first 10 minutes after boot, and the file
# /opt/callwright/keep-awake keeps the VM up (touch it before maintenance, remove it after).
# DRY_RUN=1 logs the decision without powering off.
#
# The API wakes the VM again on the next request (app/core/vm_waker.py).
set -uo pipefail

CW_DIR="${CW_DIR:-/opt/callwright}"
STATE_DIR="${CW_IDLE_STATE_DIR:-/run/callwright-idle}"
IDLE_LIMIT_S="${CW_IDLE_LIMIT_S:-900}"
BOOT_GRACE_S="${CW_BOOT_GRACE_S:-600}"
ACTIVITY_LIMIT_S="${CW_ACTIVITY_LIMIT_S:-900}"
LIVEKIT_HTTP="${CW_LIVEKIT_HTTP:-http://127.0.0.1:7880}"
KEEP_AWAKE="${CW_KEEP_AWAKE_FILE:-$CW_DIR/keep-awake}"

log() { echo "$*"; }

busy() {
  rm -f "$STATE_DIR/idle-since"
  log "busy: $*"
  exit 0
}

# Value of KEY from an env file written by render-env.sh (KEY='value' or KEY=value).
env_value() {
  local file="$1" key="$2" raw
  raw="$(grep -m1 "^${key}=" "$file" 2>/dev/null | cut -d= -f2-)" || true
  raw="${raw#\'}"
  printf '%s' "${raw%\'}"
}

redis_cli() {
  if [ -n "${CW_REDIS_CLI:-}" ]; then
    # Test hook: a command prefix such as "docker exec -i some-redis redis-cli".
    # shellcheck disable=SC2086
    $CW_REDIS_CLI "$@"
  else
    docker compose --project-directory "$CW_DIR" exec -T -e REDISCLI_AUTH="$REDIS_PASSWORD" \
      redis redis-cli --raw "$@"
  fi
}

b64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }

livekit_token() {
  local now header payload signature
  now="$(date +%s)"
  header="$(printf '{"alg":"HS256","typ":"JWT"}' | b64url)"
  payload="$(printf '{"iss":"%s","sub":"idle-check","nbf":%d,"exp":%d,"video":{"roomList":true}}' \
    "$LIVEKIT_API_KEY" "$((now - 10))" "$((now + 60))" | b64url)"
  signature="$(printf '%s.%s' "$header" "$payload" \
    | openssl dgst -sha256 -hmac "$LIVEKIT_API_SECRET" -binary | b64url)"
  printf '%s.%s.%s' "$header" "$payload" "$signature"
}

mkdir -p "$STATE_DIR"

if [ -e "$KEEP_AWAKE" ]; then
  busy "keep-awake file $KEEP_AWAKE is present"
fi

uptime_s="$(cut -d. -f1 /proc/uptime 2>/dev/null || echo 0)"
if [ "${CW_UPTIME_S:-$uptime_s}" -lt "$BOOT_GRACE_S" ]; then
  busy "boot grace period (up ${CW_UPTIME_S:-$uptime_s}s of ${BOOT_GRACE_S}s)"
fi

REDIS_PASSWORD="${REDIS_PASSWORD:-$(env_value "$CW_DIR/.env" REDIS_PASSWORD)}"
LIVEKIT_API_KEY="${LIVEKIT_API_KEY:-$(env_value "$CW_DIR/worker.env" LIVEKIT_API_KEY)}"
LIVEKIT_API_SECRET="${LIVEKIT_API_SECRET:-$(env_value "$CW_DIR/worker.env" LIVEKIT_API_SECRET)}"
[ -n "$LIVEKIT_API_KEY" ] && [ -n "$LIVEKIT_API_SECRET" ] || busy "LiveKit keys not found (run render-env.sh)"

# 1. LiveKit rooms with participants.
rooms_json="$(curl -fsS -m 5 -X POST -H "Authorization: Bearer $(livekit_token)" \
  -H 'Content-Type: application/json' -d '{}' "$LIVEKIT_HTTP/twirp/livekit.RoomService/ListRooms")" \
  || busy "LiveKit room list unavailable"
occupied="$(printf '%s' "$rooms_json" | grep -Eo '"num_?[pP]articipants": *[0-9]+' \
  | grep -Eo '[0-9]+$' | awk '$1 > 0 { n++ } END { print n + 0 }')"
[ "$occupied" -eq 0 ] || busy "$occupied LiveKit room(s) with participants"

# 2. arq queue and jobs in progress.
queued="$(redis_cli ZCARD arq:queue)" || busy "Redis unavailable"
[[ "$queued" =~ ^[0-9]+$ ]] || busy "unexpected arq:queue answer: $queued"
[ "$queued" -eq 0 ] || busy "$queued job(s) queued"
in_progress="$(redis_cli --scan --pattern 'arq:in-progress:*')" || busy "Redis unavailable"
running="$(printf '%s\n' "$in_progress" | grep -v '^arq:in-progress:cron:' | grep -c . || true)"
[ "$running" -eq 0 ] || busy "$running job(s) in progress"

# 3. Recent API use.
now="$(date +%s)"
last_api="$(redis_cli GET cw:last_api_activity)" || busy "Redis unavailable"
if [[ "$last_api" =~ ^[0-9]+$ ]] && [ "$((now - last_api))" -lt "$ACTIVITY_LIMIT_S" ]; then
  busy "API used $((now - last_api))s ago"
fi

# Everything is idle: count consecutive idle minutes.
if [ ! -f "$STATE_DIR/idle-since" ]; then
  echo "$now" > "$STATE_DIR/idle-since"
fi
since="$(cat "$STATE_DIR/idle-since")"
idle_for="$((now - since))"
if [ "$idle_for" -lt "$IDLE_LIMIT_S" ]; then
  log "idle for ${idle_for}s (powering off at ${IDLE_LIMIT_S}s)"
  exit 0
fi

if [ "${DRY_RUN:-0}" = "1" ]; then
  log "idle for ${idle_for}s: would power off now (DRY_RUN)"
  exit 0
fi
log "idle for ${idle_for}s: powering off"
rm -f "$STATE_DIR/idle-since"
/sbin/shutdown -h now
