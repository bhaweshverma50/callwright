#!/usr/bin/env bash
# Refresh the vendored disposable email domain list (CC0, disposable-email-domains project).
set -euo pipefail
dest="$(cd "$(dirname "$0")/.." && pwd)/services/api/app/auth/disposable_domains.txt"
url="https://raw.githubusercontent.com/disposable-email-domains/disposable-email-domains/main/disposable_email_blocklist.conf"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
curl -fsSL "$url" -o "$tmp"
# Refuse an empty or malformed download rather than overwrite a good list.
[ "$(wc -l <"$tmp")" -gt 1000 ] || { echo "download too short, keeping the current list" >&2; exit 1; }
! grep -vqE '^[a-z0-9.-]+\.[a-z0-9-]+$' "$tmp" || { echo "unexpected line format, keeping the current list" >&2; exit 1; }
mv "$tmp" "$dest"
trap - EXIT
echo "updated $dest ($(wc -l <"$dest") domains)"
