#!/usr/bin/env python3
"""CI logic for this private sysand index.

Subcommands:
  process-inbox     The writer: publish inbox/ entries from the staging
                    branch into the index of record, then clear them.
  validate BASEREF  Pre-merge validation for MRs/PRs targeting staging
                    (fast feedback; the writer re-validates after merge).

A submission is a KPAR file exactly as `sysand build` produced it, placed
directly in inbox/. The project's identity — publisher, name, version —
comes from the KPAR's own metadata; the writer only publishes into
namespaces declared in publishers.toml.

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
import json
import os
import re
import subprocess
import sys
import zipfile
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
ENTRY_RE = re.compile(r"^inbox/[^/]+\.kpar$")
# Files under inbox/ that are not submissions but are allowed to exist.
INBOX_ALLOWED = {Path("inbox/README.md")}


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


def git_out(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ("git", *args), cwd=cwd, check=True, text=True, capture_output=True
    ).stdout


def kpar_metadata(path: Path) -> dict:
    """Read .project.json out of the KPAR (a zip archive)."""
    try:
        with zipfile.ZipFile(path) as zf:
            return json.loads(zf.read(".project.json"))
    except Exception as exc:
        raise Fail(f"{path}: not a readable KPAR ({exc})") from exc


def declared_publishers() -> set[str]:
    """publishers.toml is read from the index branch, so a submission
    cannot grant itself a publisher namespace."""
    text = git_out("show", f"{REMOTE}/{INDEX_BRANCH}:publishers.toml")
    return set(tomllib.loads(text).get("publishers", {}))


def find_entries() -> list[Path]:
    entries: list[Path] = []
    for path in sorted(INBOX.rglob("*")):
        if path.is_dir() or path in INBOX_ALLOWED:
            continue
        if not ENTRY_RE.match(path.as_posix()):
            raise Fail(f"{path}: submissions must be .kpar files directly in inbox/")
        entries.append(path)
    return entries


def remove_worktree() -> None:
    git("worktree", "remove", "--force", str(WORKTREE), check=False, quiet=True)
    git("worktree", "prune", quiet=True)


def add_entry(entry: Path, publishers: set[str]) -> None:
    """Add one KPAR to the index worktree; sysand derives the project's
    identity (and its normalization) from the KPAR metadata. Then enforce
    that everything the add touched lies inside a namespace declared in
    publishers.toml, and stage it."""
    run("sysand", "index", "add", "--kpar-path", str(entry),
        "--index-root", str(WORKTREE / "index"))
    changed = [
        line[3:] for line in
        git_out("status", "--porcelain", "index", cwd=WORKTREE).splitlines()
    ]
    for path in changed:
        parts = path.split("/")
        if path == "index/index.json" or (len(parts) > 2 and parts[1] in publishers):
            continue
        raise Fail(
            f"{entry}: publishes to '{path}', which is not inside any "
            "publisher namespace declared in publishers.toml"
        )
    if not changed:
        raise Fail(f"{entry}: sysand index add changed nothing")
    git("add", "-A", "index", cwd=WORKTREE, quiet=True)


def publish_batch(entries: list[Path], publishers: set[str]) -> None:
    """Apply all entries to a fresh checkout of the index branch; retry the
    whole batch on push races (rebase-retry, serialized writer)."""
    summary = " ".join(e.name for e in entries)
    for attempt in range(1, MAX_RETRIES + 1):
        git("fetch", REMOTE, INDEX_BRANCH, quiet=True)
        remove_worktree()
        git("worktree", "add", "--detach", str(WORKTREE), f"{REMOTE}/{INDEX_BRANCH}", quiet=True)
        try:
            for entry in entries:
                add_entry(entry, publishers)
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


def clear_inbox(entries: list[Path]) -> None:
    """Remove processed entries from staging. "[skip ci]" prevents writer
    recursion (belt); an empty inbox no-ops anyway (suspenders)."""
    for entry in entries:
        git("rm", "-q", str(entry))
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
        meta = kpar_metadata(entry)
        print(f"  {entry}: {meta.get('publisher')}/{meta.get('name')} {meta.get('version')}")

    publishers = declared_publishers()
    publish_batch(entries, publishers)
    clear_inbox(entries)
    return 0


def cmd_validate(base_ref: str) -> int:
    """Validate the diff BASE_REF...HEAD: submissions may only add KPAR
    files, directly in inbox/, for declared publishers."""
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
        if ENTRY_RE.match(path):
            try:
                meta = kpar_metadata(Path(path))
            except Fail as exc:
                print(f"FAIL: {exc}")
                failures += 1
                continue
            publisher = meta.get("publisher")
            if publisher not in publishers:
                print(
                    f"FAIL: {path} - publisher '{publisher}' not declared "
                    f"in publishers.toml (on {INDEX_BRANCH})"
                )
                failures += 1
                continue
            print(f"ok:   {path} - {publisher}/{meta.get('name')} {meta.get('version')}")
        elif Path(path) in INBOX_ALLOWED:
            print(f"ok:   {path}")
        elif path.startswith("inbox/"):
            print(f"FAIL: {path} - submissions must be .kpar files directly in inbox/")
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
