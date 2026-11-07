#!/usr/bin/env bash
# Rolling voice worker deploy (014 FR-001 to FR-003). Starts the image pinned in .env in the idle
# slot (voice or voice-b), waits until it answers on its health port, then stops the old slot in
# the background. The old worker drains: no new calls, and live calls run to their end
# (stop_grace_period in docker-compose.yml). The idle shutdown counts those calls' rooms as busy.
# Run on the VM after render-env.sh: cd /opt/callwright && sudo ./roll-voice.sh
set -euo pipefail
cd "$(dirname "$0")"

running() { [ -n "$(docker compose ps -q --status running "$1")" ]; }

if running voice && ! running voice-b; then
  new=voice-b old=voice port=8195
else
  new=voice old=voice-b port=8190
fi

docker compose pull "$new"
docker compose up -d "$new"
for _ in $(seq 90); do
  curl -fsS -o /dev/null "http://127.0.0.1:$port" && break
  sleep 2
done
if ! curl -fsS -o /dev/null "http://127.0.0.1:$port"; then
  echo "$new is not healthy on :$port after 3 minutes; $old keeps serving" >&2
  exit 1
fi

if running "$old"; then
  # ponytail: the drain outlives this ssh session; its log is the only progress report.
  # Removing the drained container frees its image for the next prune (the disk is small).
  nohup sh -c "docker compose stop $old && docker compose rm -f $old" \
    >"/tmp/voice-drain-$old.log" 2>&1 < /dev/null &
  disown
  echo "$new serving on :$port; $old draining (log /tmp/voice-drain-$old.log)"
else
  echo "$new serving on :$port"
fi
