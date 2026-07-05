#!/usr/bin/env bash
# Pre-merge validation for submissions (MRs/PRs targeting the staging
# branch). Checks layout and publisher declaration; the writer re-validates
# everything after merge, so this is fast feedback, not the gate of record.
#
# Usage: validate-inbox.sh <base-ref>   (e.g. origin/staging)
set -euo pipefail

BASE=${1:?usage: validate-inbox.sh <base-ref>}
INDEX_BRANCH=${INDEX_BRANCH:-main}
REMOTE=${REMOTE:-origin}

git fetch "$REMOTE" "$INDEX_BRANCH" >/dev/null 2>&1 || true
fail=0

mapfile -t CHANGED < <(git diff --name-only --diff-filter=ACMR "$BASE"...HEAD)
[ "${#CHANGED[@]}" -gt 0 ] || { echo "No changes."; exit 0; }

git show "$REMOTE/$INDEX_BRANCH:publishers.toml" > .publishers-authoritative.toml
trap 'rm -f .publishers-authoritative.toml' EXIT

for f in "${CHANGED[@]}"; do
  case "$f" in
    inbox/*/*/*/project.kpar)
      publisher=$(echo "$f" | cut -d/ -f2)
      if ! python3 -c '
import sys, tomllib
with open(".publishers-authoritative.toml", "rb") as fh:
    conf = tomllib.load(fh)
sys.exit(0 if sys.argv[1] in conf.get("publishers", {}) else 1)
' "$publisher"; then
        echo "FAIL: $f - publisher '$publisher' not declared in publishers.toml (on $INDEX_BRANCH)"
        fail=1
      else
        echo "ok:   $f"
      fi
      ;;
    inbox/README.md)
      echo "ok:   $f"
      ;;
    inbox/*)
      echo "FAIL: $f - must match inbox/<publisher>/<name>/<version>/project.kpar"
      fail=1
      ;;
    *)
      echo "FAIL: $f - submissions may only touch inbox/"
      fail=1
      ;;
  esac
done
exit "$fail"
