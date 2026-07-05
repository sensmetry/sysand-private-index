#!/usr/bin/env python3
"""CI logic for a staged-writer private sysand index.

Design: priv-index-plan explorations 0011 (staged writer) and 0008 (race
lessons).

Subcommands:
  process-inbox     The writer: publish inbox/ entries from the staging
                    branch into the index of record, then clear them.
  validate BASEREF  Pre-merge validation for MRs/PRs targeting staging
                    (fast feedback; the writer re-validates after merge).

Invariants:
- The writer runs serialized (GitHub `concurrency:` / GitLab `resource_group`).
- Prior index state is read from git, never from a deployed/served copy.
- Only the writer's CI identity may push to the index branch (protected).
- Published versions are immutable: the writer only ever adds.

Requires: Python >= 3.11 (tomllib), git, sysand on PATH.
Expects: cwd = repo root, checkout of the staging branch tip, push
credentials configured on the remote.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import tomllib

REMOTE = os.environ.get("REMOTE", "origin")
INDEX_BRANCH = os.environ.get("INDEX_BRANCH", "main")
STAGING_BRANCH = os.environ.get("STAGING_BRANCH", "staging")
GIT_USER = os.environ.get("GIT_USER", "index-writer")
GIT_EMAIL = os.environ.get("GIT_EMAIL", "index-writer@example.invalid")
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "5"))

INBOX = Path("inbox")
WORKTREE = Path(".index-work")
ENTRY_RE = re.compile(
    r"^inbox/(?P<publisher>[^/]+)/(?P<name>[^/]+)/(?P<version>[^/]+)/project\.kpar$"
)
# Files under inbox/ that are not submissions but are allowed to exist.
INBOX_ALLOWED = {Path("inbox/README.md")}


@dataclass(frozen=True)
class Entry:
    publisher: str
    name: str
    version: str
    path: Path

    @property
    def iri(self) -> str:
        # Explicit IRI derived from the inbox path pins path<->identity
        # consistency; sysand rejects a KPAR whose name disagrees.
        return f"pkg:sysand/{self.publisher}/{self.name}"

    @property
    def index_path(self) -> Path:
        return Path("index") / self.publisher / self.name / self.version


class Fail(Exception):
    """Validation or publish failure with a user-facing message."""


def run(
    *args: str, cwd: Path | None = None, check: bool = True, quiet: bool = False
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=check,
        text=True,
        stdout=subprocess.PIPE if quiet else None,
        stderr=subprocess.STDOUT if quiet else None,
    )


def git(*args: str, cwd: Path | None = None, check: bool = True, quiet: bool = False):
    return run("git", *args, cwd=cwd, check=check, quiet=quiet)


def git_out(*args: str) -> str:
    return subprocess.run(
        ("git", *args), check=True, text=True, capture_output=True
    ).stdout


def parse_entry(path: str) -> Entry | None:
    m = ENTRY_RE.match(path)
    if not m:
        return None
    return Entry(m["publisher"], m["name"], m["version"], Path(path))


def declared_publishers() -> set[str]:
    """publishers.toml is read from the index branch: config-as-code lives
    with the index of record, not with the submission."""
    text = git_out("show", f"{REMOTE}/{INDEX_BRANCH}:publishers.toml")
    return set(tomllib.loads(text).get("publishers", {}))


def find_entries() -> list[Entry]:
    entries: list[Entry] = []
    for path in sorted(INBOX.rglob("*")):
        if path.is_dir() or path in INBOX_ALLOWED:
            continue
        entry = parse_entry(path.as_posix())
        if entry is None:
            raise Fail(
                f"{path}: does not match inbox/<publisher>/<name>/<version>/project.kpar"
            )
        entries.append(entry)
    return entries


def check_authorized(entries: list[Entry]) -> None:
    publishers = declared_publishers()
    for entry in entries:
        if entry.publisher not in publishers:
            raise Fail(
                f"publisher namespace '{entry.publisher}' not declared in "
                f"publishers.toml (on {INDEX_BRANCH})"
            )


def remove_worktree() -> None:
    git("worktree", "remove", "--force", str(WORKTREE), check=False, quiet=True)
    git("worktree", "prune", quiet=True)


def publish_batch(entries: list[Entry]) -> None:
    """Apply all entries to a fresh checkout of the index branch; retry the
    whole batch on push races (rebase-retry, serialized writer)."""
    summary = " ".join(str(e.path.relative_to(INBOX)) for e in entries)
    for attempt in range(1, MAX_RETRIES + 1):
        git("fetch", REMOTE, INDEX_BRANCH, quiet=True)
        remove_worktree()
        git("worktree", "add", "--detach", str(WORKTREE), f"{REMOTE}/{INDEX_BRANCH}", quiet=True)
        try:
            for entry in entries:
                run(
                    "sysand", "index", "add", entry.iri,
                    "--kpar-path", str(entry.path),
                    "--index-root", str(WORKTREE / "index"),
                )
                if not (WORKTREE / entry.index_path / "project.kpar").exists():
                    raise Fail(
                        f"{entry.path}: KPAR metadata does not match the "
                        "inbox path (publisher/name/version)"
                    )
            git("add", "-A", "index", cwd=WORKTREE)
            git(
                "-c", f"user.name={GIT_USER}", "-c", f"user.email={GIT_EMAIL}",
                "commit", "-m", f"index: publish {summary}",
                cwd=WORKTREE, quiet=True,
            )
            push = git(
                "push", REMOTE, f"HEAD:refs/heads/{INDEX_BRANCH}",
                cwd=WORKTREE, check=False,
            )
            if push.returncode == 0:
                return
            print(
                f"Push to {INDEX_BRANCH} rejected (concurrent write) - "
                f"retry {attempt}/{MAX_RETRIES}"
            )
        finally:
            remove_worktree()
    raise Fail(f"could not push to {INDEX_BRANCH} after {MAX_RETRIES} attempts")


def clear_inbox(entries: list[Entry]) -> None:
    """Remove processed entries from staging. "[skip ci]" prevents writer
    recursion (belt); an empty inbox no-ops anyway (suspenders)."""
    for entry in entries:
        git("rm", "-rq", str(entry.path.parent))
    git("commit", "-m", f"inbox: processed {len(entries)} submission(s) [skip ci]", quiet=True)
    for attempt in range(1, MAX_RETRIES + 1):
        if git("push", REMOTE, f"HEAD:refs/heads/{STAGING_BRANCH}", check=False).returncode == 0:
            return
        print(f"Push to {STAGING_BRANCH} rejected - rebasing, retry {attempt}/{MAX_RETRIES}")
        git("pull", "--rebase", REMOTE, STAGING_BRANCH)
    raise Fail(f"could not update {STAGING_BRANCH}")


def cmd_process_inbox() -> int:
    run("sysand", "--version", quiet=True)  # fail fast if missing
    git("config", "user.name", GIT_USER)
    git("config", "user.email", GIT_EMAIL)
    git("fetch", REMOTE, INDEX_BRANCH, STAGING_BRANCH, quiet=True)

    entries = find_entries()
    if not entries:
        print("Inbox empty - nothing to do.")
        return 0
    print(f"Processing {len(entries)} submission(s):")
    for entry in entries:
        print(f"  {entry.path}")

    check_authorized(entries)
    publish_batch(entries)
    clear_inbox(entries)
    return 0


def cmd_validate(base_ref: str) -> int:
    """Validate the diff BASE_REF...HEAD: submissions may only add
    well-formed inbox entries for declared publishers."""
    changed = git_out(
        "diff", "--name-only", "--diff-filter=ACMR", f"{base_ref}...HEAD"
    ).splitlines()
    if not changed:
        print("No changes.")
        return 0

    git("fetch", REMOTE, INDEX_BRANCH, check=False, quiet=True)
    publishers = declared_publishers()
    failures = 0
    for path in changed:
        entry = parse_entry(path)
        if entry is not None:
            if entry.publisher in publishers:
                print(f"ok:   {path}")
            else:
                print(
                    f"FAIL: {path} - publisher '{entry.publisher}' not "
                    f"declared in publishers.toml (on {INDEX_BRANCH})"
                )
                failures += 1
        elif Path(path) in INBOX_ALLOWED:
            print(f"ok:   {path}")
        elif path.startswith("inbox/"):
            print(f"FAIL: {path} - must match inbox/<publisher>/<name>/<version>/project.kpar")
            failures += 1
        else:
            print(f"FAIL: {path} - submissions may only touch inbox/")
            failures += 1
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("process-inbox", help="run the writer (staging -> index branch)")
    validate = sub.add_parser("validate", help="validate a submission diff")
    validate.add_argument("base_ref", help="merge base, e.g. origin/staging")
    args = parser.parse_args()
    try:
        if args.command == "process-inbox":
            return cmd_process_inbox()
        return cmd_validate(args.base_ref)
    except Fail as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        cmd = " ".join(map(str, exc.cmd))
        if exc.stdout:
            print(exc.stdout, file=sys.stderr)
        print(f"ERROR: command failed ({exc.returncode}): {cmd}", file=sys.stderr)
        return exc.returncode or 1


if __name__ == "__main__":
    sys.exit(main())
