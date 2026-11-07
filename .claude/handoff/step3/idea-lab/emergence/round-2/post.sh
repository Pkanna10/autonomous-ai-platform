#!/bin/bash
# usage: post.sh AGENT ROLE <<'MSG' ... MSG
# Appends one numbered, timestamped entry to the round-2 board that sits next
# to this script, under a lock, so concurrent agents never interleave.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
B="$HERE/board.md"
[ "$#" -eq 2 ] || { echo "usage: post.sh AGENT ROLE < message" >&2; exit 2; }
msg=$(cat)
[ -n "$msg" ] || { echo "empty message" >&2; exit 2; }
touch "$B"
exec 9>>"${TMPDIR:-/tmp}/emergence-round-2-board.lock"
flock 9
n=$(( $(grep -c '^### \[' "$B" || true) + 1 ))
printf '\n### [%d] %s (%s), %s\n\n%s\n' "$n" "$1" "$2" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$msg" >> "$B"
echo "posted [$n]"
