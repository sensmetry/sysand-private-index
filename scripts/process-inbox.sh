#!/usr/bin/env bash
# Index writer: process inbox/ entries on the staging branch into the index
# of record (main). Design: priv-index-plan explorations 0011 (staged writer)
# and 0008 (race lessons).
#
# Invariants:
# - Runs serialized: GitHub Actions `concurrency:` / GitLab `resource_group`.
# - Prior index state is read from git, never from a deployed/served copy.
# - Only this script's CI identity may push to $INDEX_BRANCH (protected).
# - Published versions are immutable: this script only ever adds.
#
# Expects: cwd = repo root, checkout of $STAGING_BRANCH tip, push credentials
# configured on $REMOTE, `sysand` and `python3` (>=3.11) on PATH.
set -euo pipefail

REMOTE=${REMOTE:-origin}
INDEX_BRANCH=${INDEX_BRANCH:-main}
STAGING_BRANCH=${STAGING_BRANCH:-staging}
GIT_USER=${GIT_USER:-index-writer}
GIT_EMAIL=${GIT_EMAIL:-index-writer@example.invalid}
MAX_RETRIES=${MAX_RETRIES:-5}

command -v sysand >/dev/null || { echo "ERROR: sysand CLI not on PATH" >&2; exit 1; }

git config user.name "$GIT_USER"
git config user.email "$GIT_EMAIL"
git fetch "$REMOTE" "$INDEX_BRANCH" "$STAGING_BRANCH"

# 1. Collect inbox entries: inbox/<publisher>/<name>/<version>/project.kpar
mapfile -t ENTRIES < <(find inbox -mindepth 4 -maxdepth 4 -type f -name project.kpar 2>/dev/null | sort)
if [ "${#ENTRIES[@]}" -eq 0 ]; then
  echo "Inbox empty - nothing to do."
  exit 0
fi
echo "Processing ${#ENTRIES[@]} submission(s):"
printf '  %s\n' "${ENTRIES[@]}"

# 2. Authorization: every publisher namespace must be declared in
#    publishers.toml *on the index branch* (config-as-code lives with the
#    index of record, not with the submission). Identity verification per
#    channel: MR review + CODEOWNERS today; verified OIDC at the gateway
#    later — same file, stronger gate (exploration 0011).
git show "$REMOTE/$INDEX_BRANCH:publishers.toml" > .publishers-authoritative.toml
trap 'rm -f .publishers-authoritative.toml' EXIT
for entry in "${ENTRIES[@]}"; do
  IFS=/ read -r _ publisher _name _version _file <<<"$entry"
  python3 - "$publisher" .publishers-authoritative.toml <<'PY'
import sys, tomllib
pub, path = sys.argv[1], sys.argv[2]
with open(path, "rb") as f:
    conf = tomllib.load(f)
if pub not in conf.get("publishers", {}):
    sys.exit(f"ERROR: publisher namespace '{pub}' not declared in publishers.toml")
PY
done

# 3. Apply all entries to a fresh checkout of the index branch; retry the
#    whole batch on push races (rebase-retry, serialized writer).
cleanup_worktree() { git worktree remove --force .index-work 2>/dev/null || true; git worktree prune; }
for attempt in $(seq 1 "$MAX_RETRIES"); do
  git fetch "$REMOTE" "$INDEX_BRANCH"
  cleanup_worktree
  git worktree add --detach .index-work "$REMOTE/$INDEX_BRANCH"
  for entry in "${ENTRIES[@]}"; do
    IFS=/ read -r _ publisher name version _file <<<"$entry"
    # Explicit IRI derived from the inbox path pins path<->identity consistency.
    sysand index add "pkg:sysand/$publisher/$name" \
      --kpar-path "$entry" --index-root .index-work/index
    # The KPAR's declared version must land at the inbox-declared path;
    # otherwise the submission mis-states its version.
    if [ ! -e ".index-work/index/$publisher/$name/$version/project.kpar" ]; then
      echo "ERROR: $entry: KPAR metadata does not match inbox path (publisher/name/version)" >&2
      exit 1
    fi
  done
  git -C .index-work add -A index
  git -C .index-work -c user.name="$GIT_USER" -c user.email="$GIT_EMAIL" \
    commit -m "index: publish ${ENTRIES[*]#inbox/}"
  if git -C .index-work push "$REMOTE" "HEAD:refs/heads/$INDEX_BRANCH"; then
    cleanup_worktree
    break
  fi
  echo "Push to $INDEX_BRANCH rejected (concurrent write) - retry $attempt/$MAX_RETRIES"
  if [ "$attempt" -eq "$MAX_RETRIES" ]; then
    echo "ERROR: giving up after $MAX_RETRIES attempts" >&2
    exit 1
  fi
done

# 4. Remove processed entries from staging. "[skip ci]" prevents writer
#    recursion (belt); an empty inbox no-ops anyway (suspenders).
for entry in "${ENTRIES[@]}"; do
  git rm -rq "$(dirname "$entry")"
done
git commit -m "inbox: processed ${#ENTRIES[@]} submission(s) [skip ci]"
for attempt in $(seq 1 "$MAX_RETRIES"); do
  if git push "$REMOTE" "HEAD:refs/heads/$STAGING_BRANCH"; then
    exit 0
  fi
  echo "Push to $STAGING_BRANCH rejected - rebasing, retry $attempt/$MAX_RETRIES"
  git pull --rebase "$REMOTE" "$STAGING_BRANCH"
done
echo "ERROR: could not update $STAGING_BRANCH" >&2
exit 1
