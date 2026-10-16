#!/bin/bash
# Run on the VM as root from /opt/callwright (sudo ./install-idle.sh). Idempotent.
#   * docker and containerd start at boot, so the compose services (restart: unless-stopped)
#     come back by themselves after the VM is started again;
#   * every compose service is checked for that restart policy;
#   * callwright-idle.timer runs idle-shutdown.sh every minute (decisions in journald:
#     journalctl -t callwright-idle -f).
set -euo pipefail
cd "$(dirname "$0")"

if [ "$(id -u)" -ne 0 ]; then
  echo "run as root: sudo $0" >&2
  exit 1
fi

for tool in curl openssl docker python3; do
  command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }
done

systemctl enable docker.service containerd.service

services="$(docker compose config --services | sort)"
missing=""
for service in $services; do
  policy="$(docker compose config --format json \
    | python3 -c 'import json, sys; print(json.load(sys.stdin)["services"][sys.argv[1]].get("restart", ""))' "$service")"
  [ "$policy" = "unless-stopped" ] || missing="$missing $service"
done
if [ -n "$missing" ]; then
  echo "these services lack restart: unless-stopped:$missing" >&2
  exit 1
fi
echo "restart policy ok for: $(echo "$services" | tr '\n' ' ')"

chmod 0755 idle-shutdown.sh
install -m 0644 systemd/callwright-idle.service /etc/systemd/system/callwright-idle.service
install -m 0644 systemd/callwright-idle.timer /etc/systemd/system/callwright-idle.timer
systemctl daemon-reload
systemctl enable --now callwright-idle.timer
systemctl list-timers callwright-idle.timer --no-pager
echo "installed. Keep the VM up during maintenance with: sudo touch /opt/callwright/keep-awake"
