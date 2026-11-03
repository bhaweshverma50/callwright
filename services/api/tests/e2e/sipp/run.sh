#!/usr/bin/env bash
# Optional SIPp end-to-end checks for phone numbers (010 T067, quickstart section 6).
#
#   run.sh up               start livekit-sip (livekit/sip) next to a local LiveKit server
#   run.sh inbound_answer   a carrier calls a Callwright number: 200 OK, 8 s of RTP, BYE, call row
#   run.sh outbound_busy    Callwright dials out and the far end answers 486: call ends busy, unbilled
#   run.sh down             stop the livekit-sip container
#
# SIPp (official image, pinned by digest) runs inside the livekit-sip container's network
# namespace, the way the VM runs livekit-sip, the lab PBX and LiveKit on one host network: it
# reaches livekit-sip on 127.0.0.1:5060 and livekit-sip reaches it on 127.0.0.1:5090. See README.md.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
API="${CALLWRIGHT_API:-http://localhost:8100/v1}"
SIP_CONTAINER="${SIP_CONTAINER:-callwright-sip-e2e}"
SIP_IMAGE="${SIP_IMAGE:-livekit/sip:v1.2.0}"
# SIPp 3.5.1 (amd64 only; runs under emulation on arm64 hosts).
SIPP_IMAGE="${SIPP_IMAGE:-ctaloi/sipp@sha256:c459f2340443ddcc159227efc798217dbdaad0dbe88b76b78b1a876aa271986a}"
INBOUND_NUMBER="${SIPP_NUMBER:-+14155550100}"
OUTBOUND_FROM="${SIPP_FROM:-+14155550110}"
OUTBOUND_TO="${SIPP_TO:-+919000000001}"
CALL_TIMEOUT_S="${SIPP_CALL_TIMEOUT_S:-60}"

die() { echo "FAIL: $*" >&2; exit 1; }

api() { # METHOD PATH [JSON] [extra curl args...]
  local method="$1" path="$2" body="${3:-}"
  shift 3 2>/dev/null || shift $#
  [ -n "${CALLWRIGHT_TOKEN:-}" ] || die "set CALLWRIGHT_TOKEN to a signed-in user's access token"
  curl -sS -X "$method" "$API$path" -H "Authorization: Bearer $CALLWRIGHT_TOKEN" \
    -H "Content-Type: application/json" ${body:+-d "$body"} "$@"
}

json() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

sipp() { # sipp arguments...
  docker run --rm --platform linux/amd64 --network "container:$SIP_CONTAINER" \
    -v "$HERE:/scenarios:ro" "$SIPP_IMAGE" -i 127.0.0.1 -trace_err -nostdin "$@"
}

require_sip() {
  [ "$(docker inspect -f '{{.State.Running}}' "$SIP_CONTAINER" 2>/dev/null)" = "true" ] \
    || die "livekit-sip container $SIP_CONTAINER is not running (run.sh up)"
}

# Poll a call until its status is one of $2 (space separated); print the final call JSON.
wait_status() {
  local call_id="$1" want="$2" deadline=$((SECONDS + CALL_TIMEOUT_S)) body status
  while [ $SECONDS -lt $deadline ]; do
    body="$(api GET "/calls/$call_id")"
    status="$(echo "$body" | json 'd.get("status")')"
    for s in $want; do [ "$status" = "$s" ] && { echo "$body"; return 0; }; done
    sleep 2
  done
  die "call $call_id still '$status' after ${CALL_TIMEOUT_S}s (wanted: $want)"
}

up() {
  # LIVEKIT_WS and SIP_REDIS must be the LiveKit server and the Redis it uses (livekit-sip talks
  # to LiveKit through Redis). Defaults: livekit-server on the host at :7880 with Redis on :56379.
  local ws="${LIVEKIT_WS:-ws://host.docker.internal:7880}" redis="${SIP_REDIS:-host.docker.internal:56379}"
  local db="${SIP_REDIS_DB:-0}" dir
  dir="$(mktemp -d)"
  cat >"$dir/config.yaml" <<EOF
api_key: ${LIVEKIT_API_KEY:-devkey}
api_secret: ${LIVEKIT_API_SECRET:-secret}
ws_url: $ws
redis:
  address: $redis
  db: $db
sip_port: 5060
rtp_port: 10000-10100
use_external_ip: false
health_port: 8080
logging:
  level: info
EOF
  docker rm -f "$SIP_CONTAINER" >/dev/null 2>&1 || true
  docker run -d --name "$SIP_CONTAINER" -v "$dir/config.yaml:/sip/config.yaml:ro" "$SIP_IMAGE" >/dev/null
  for _ in $(seq 1 20); do
    docker logs "$SIP_CONTAINER" 2>&1 | grep -q "sip signaling listening" && break
    sleep 1
  done
  docker logs "$SIP_CONTAINER" 2>&1 | grep -q "sip signaling listening" || die "livekit-sip did not start: docker logs $SIP_CONTAINER"
  echo "livekit-sip $SIP_CONTAINER up ($SIP_IMAGE -> $ws)"
}

inbound_answer() {
  require_sip
  local since
  since="$(date -u +%Y-%m-%dT%H:%M:%S)"
  echo "== SIPp calls $INBOUND_NUMBER on livekit-sip"
  local log
  log="$(mktemp)"
  sipp -sf /scenarios/inbound_answer.xml -s "$INBOUND_NUMBER" -m 1 -l 1 -p 5070 -mp 6000 \
    -timeout 60s 127.0.0.1:5060 >"$log" 2>&1 \
    || { tail -30 "$log"; die "SIPp scenario failed (no 200 OK or no 200 to BYE)"; }
  grep -E "(INVITE|100|180|183|200|ACK|BYE) +(-+>|<-+)|Pause" "$log" | tail -8
  local call_id
  call_id="$(api GET "/calls?page_size=10" "" | json "next((c['call_id'] for c in d['items'] if c['channel']=='sip_inbound' and c['to_number']=='$INBOUND_NUMBER' and c['started_at'][:19]>='$since'), '')")"
  [ -n "$call_id" ] || die "no sip_inbound call row for $INBOUND_NUMBER since $since"
  local body
  body="$(wait_status "$call_id" "ended processing completed")"
  echo "$body" | json "'call %s: %s %s, %s s' % (d['call_id'], d['status'], d['disconnect_reason'], d['duration_s'])"
  [ "$(echo "$body" | json 'd["disconnect_reason"]')" = "user_hangup" ] || die "expected disconnect_reason user_hangup"
  echo "PASS inbound_answer"
}

outbound_busy() {
  require_sip
  local log
  log="$(mktemp)"
  echo "== SIPp answers 486 on 127.0.0.1:5090; Callwright dials $OUTBOUND_TO from $OUTBOUND_FROM"
  sipp -sf /scenarios/outbound_busy.xml -m 1 -p 5090 -timeout 60s >"$log" 2>&1 &
  local sipp_pid=$!
  sleep 3
  local resp call_id
  resp="$(api POST /outbound-calls "{\"to_number\":\"$OUTBOUND_TO\",\"from_number\":\"$OUTBOUND_FROM\"}" \
    -H "Idempotency-Key: sipp-busy-$(date +%s)-$$")"
  call_id="$(echo "$resp" | json 'd.get("call_id", "")')"
  [ -n "$call_id" ] || { kill "$sipp_pid" 2>/dev/null || true; die "outbound call refused: $resp"; }
  wait "$sipp_pid" || { tail -20 "$log"; die "SIPp did not see the INVITE and ACK"; }
  local body
  body="$(wait_status "$call_id" "busy no_answer failed completed")"
  echo "$body" | json "'call %s: %s, cost %s' % (d['call_id'], d['status'], d['cost_usd'])"
  [ "$(echo "$body" | json 'd["status"]')" = "busy" ] || die "expected status busy"
  [ "$(echo "$body" | json 'd["cost_usd"]')" = "None" ] || die "a busy call must not be billed"
  echo "PASS outbound_busy"
}

case "${1:-}" in
  up) up ;;
  down) docker rm -f "$SIP_CONTAINER" >/dev/null && echo "livekit-sip $SIP_CONTAINER removed" ;;
  inbound_answer) inbound_answer ;;
  outbound_busy) outbound_busy ;;
  *) echo "usage: $0 up|inbound_answer|outbound_busy|down" >&2; exit 2 ;;
esac
