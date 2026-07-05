#!/usr/bin/env python3
"""CI logic for this private sysand index.

Subcommands:
  process-inbox     The writer: publish inbox/ entries into the generated
                    index branch, then clear them from the source branch.
  validate BASEREF  Pre-merge validation for MRs/PRs.
                    Writes kpar-report.md describing every submission so
                    reviewers see exactly what is being added (CI posts it
                    on the PR/MR).

A submission is a KPAR file exactly as `sysand build` produced it, placed
directly in inbox/ on the default branch. The project's identity —
publisher, name, version — comes from the KPAR's own metadata. Review of
the pull/merge request is the publishing gate: what reviewers approve gets
published. The writer publishes into the generated, writer-only index
branch and then clears the inbox.

Invariants:
- The writer runs serialized (GitHub `concurrency:` / GitLab `resource_group`).
- Prior index state is read from git, never from a deployed/served copy.
- Only the writer's CI identity may push to the index branch (protected).
- Published versions are immutable: the writer only ever adds.

Requires: Python >= 3.11, git, sysand on PATH.
Expects: cwd = repo root, checkout of the source branch tip, push
credentials configured on the remote.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

REMOTE = os.environ.get("REMOTE", "origin")
INDEX_BRANCH = os.environ.get("INDEX_BRANCH", "index")
SOURCE_BRANCH = os.environ.get("SOURCE_BRANCH", "main")
GIT_USER = os.environ.get("GIT_USER", "index-writer")
GIT_EMAIL = os.environ.get("GIT_EMAIL", "index-writer@example.invalid")
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "5"))

INBOX = Path("inbox")
WORKTREE = Path(".index-work")
REPORT = Path("kpar-report.md")
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


def kpar_metadata(path: Path) -> tuple[dict, dict]:
    """Read (.project.json, .meta.json) out of the KPAR (a zip archive)."""
    try:
        with zipfile.ZipFile(path) as zf:
            project = json.loads(zf.read(".project.json"))
            try:
                meta = json.loads(zf.read(".meta.json"))
            except KeyError:
                meta = {}
            return project, meta
    except Fail:
        raise
    except Exception as exc:
        raise Fail(f"{path}: not a readable KPAR ({exc})") from exc


def describe_kpar(path: Path) -> str:
    """Markdown section describing one submission, for reviewers."""
    project, meta = kpar_metadata(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    size = path.stat().st_size
    usages = project.get("usage") or []
    deps = (
        ", ".join(f"`{u.get('resource', u)}`" for u in usages) if usages else "none"
    )
    with zipfile.ZipFile(path) as zf:
        files = ", ".join(f"`{n}`" for n in zf.namelist() if not n.startswith("."))
    lines = [
        f"### `{path.name}`",
        "",
        "| | |",
        "| --- | --- |",
        f"| project | **{project.get('publisher')}/{project.get('name')}** |",
        f"| version | {project.get('version')} |",
        f"| license | {project.get('license', '(none)')} |",
        f"| declared dependencies | {deps} |",
        f"| model files | {files or '(none)'} |",
        f"| built | {meta.get('created', '(unknown)')} |",
        f"| size / sha256 | {size} bytes / `{digest[:16]}…` |",
        "",
    ]
    return "\n".join(lines)


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


def add_entry(entry: Path) -> None:
    """Add one KPAR to the index worktree; sysand derives and validates the
    project's identity from the KPAR metadata. Stage the result."""
    run("sysand", "index", "add", "--kpar-path", str(entry),
        "--index-root", str(WORKTREE))
    changed = git_out("status", "--porcelain", cwd=WORKTREE).splitlines()
    if not changed:
        raise Fail(f"{entry}: sysand index add changed nothing")
    git("add", "-A", cwd=WORKTREE, quiet=True)


def publish_batch(entries: list[Path]) -> None:
    """Apply all entries to a fresh checkout of the index branch; retry the
    whole batch on push races (rebase-retry, serialized writer)."""
    summary = " ".join(e.name for e in entries)
    for attempt in range(1, MAX_RETRIES + 1):
        git("fetch", REMOTE, INDEX_BRANCH, quiet=True)
        remove_worktree()
        git("worktree", "add", "--detach", str(WORKTREE), f"{REMOTE}/{INDEX_BRANCH}", quiet=True)
        try:
            for entry in entries:
                add_entry(entry)
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
    """Remove processed entries from the source branch. "[skip ci]" prevents writer
    recursion (belt); an empty inbox no-ops anyway (suspenders)."""
    for entry in entries:
        git("rm", "-q", str(entry))
    git("commit", "-m", f"inbox: processed {len(entries)} submission(s) [skip ci]", quiet=True)
    for attempt in range(1, MAX_RETRIES + 1):
        if git("push", REMOTE, f"HEAD:refs/heads/{SOURCE_BRANCH}", check=False).returncode == 0:
            return
        print(f"Push to {SOURCE_BRANCH} rejected - rebasing, retry {attempt}/{MAX_RETRIES}")
        git("pull", "--rebase", REMOTE, SOURCE_BRANCH)
    raise Fail(f"could not update {SOURCE_BRANCH}")


def cmd_process_inbox() -> int:
    run("sysand", "--version", quiet=True)  # fail fast if missing
    git("config", "user.name", GIT_USER)
    git("config", "user.email", GIT_EMAIL)
    if git("fetch", REMOTE, INDEX_BRANCH, check=False, quiet=True).returncode != 0:
        raise Fail(
            f"branch '{INDEX_BRANCH}' does not exist on {REMOTE} - it holds "
            "the generated index and must be created once (see ADMINISTRATION.md)"
        )
    git("fetch", REMOTE, SOURCE_BRANCH, quiet=True)

    entries = find_entries()
    if not entries:
        print("Inbox empty - nothing to do.")
        return 0
    print(f"Processing {len(entries)} submission(s):")
    for entry in entries:
        project, _ = kpar_metadata(entry)
        print(f"  {entry}: {project.get('publisher')}/{project.get('name')} {project.get('version')}")

    publish_batch(entries)
    clear_inbox(entries)
    return 0


def cmd_validate(base_ref: str) -> int:
    """Validate the diff BASE_REF...HEAD and write kpar-report.md
    describing each submission for reviewers."""
    changed = git_out(
        "diff", "--name-only", "--diff-filter=ACMR", f"{base_ref}...HEAD"
    ).splitlines()
    if not changed:
        print("No changes.")
        return 0

    failures = 0
    sections = ["## Index submission report", ""]
    for path in changed:
        if ENTRY_RE.match(path):
            try:
                sections.append(describe_kpar(Path(path)))
                print(f"ok:   {path}")
            except Fail as exc:
                sections.append(f"### `{Path(path).name}`\n\n**REJECTED**: {exc}\n")
                print(f"FAIL: {exc}")
                failures += 1
        elif Path(path) in INBOX_ALLOWED:
            print(f"ok:   {path}")
        elif path.startswith("inbox/"):
            sections.append(
                f"### `{path}`\n\n**REJECTED**: submissions must be .kpar "
                "files directly in inbox/\n"
            )
            print(f"FAIL: {path} - submissions must be .kpar files directly in inbox/")
            failures += 1
        # other files are ordinary code/docs changes, reviewed as such

    if len(sections) > 2:
        report = "\n".join(sections)
        REPORT.write_text(report)
        print(f"Report written to {REPORT}")
        step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if step_summary:
            with open(step_summary, "a") as fh:
                fh.write(report)
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("process-inbox", help="run the writer (inbox on the source branch -> index branch)")
    validate = sub.add_parser("validate", help="validate a submission diff")
    validate.add_argument("base_ref", help="merge base, e.g. origin/main")
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
