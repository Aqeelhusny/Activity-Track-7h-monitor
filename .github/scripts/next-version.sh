#!/usr/bin/env bash
# Decides which version to release; prints ver=<x.y.z> and notes=<one line> for $GITHUB_OUTPUT.
#  - VERSION in core.py has no tag yet -> release it as is (first release, or you bumped it by hand, e.g. to 2.0.0)
#  - it is already tagged              -> bump it: "[major]" or "BREAKING" in a commit subject -> major, "feat" -> minor, else patch
set -euo pipefail
cur=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' core.py | tr -d '\r')  # tr: tolerate CRLF checkouts on Windows
if git rev-parse -q --verify "refs/tags/v$cur" >/dev/null; then
  subjects=$(git log --format=%s "v$cur..HEAD")
  IFS=. read -r ma mi pa <<< "$cur"
  if grep -qiE '\[major\]|BREAKING' <<< "$subjects"; then ver="$((ma + 1)).0.0"
  elif grep -qiE '^feat' <<< "$subjects"; then ver="$ma.$((mi + 1)).0"
  else ver="$ma.$mi.$((pa + 1))"; fi
else
  ver="$cur"; subjects=$(git log -5 --format=%s)
fi
notes=$( (grep -v '^chore: release' <<< "$subjects" || true) | head -3 | paste -sd ';' - | cut -c1-200)
echo "ver=$ver"
echo "notes=$notes"
