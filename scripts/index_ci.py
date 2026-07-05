#!/usr/bin/env python3
"""CI logic for this private sysand index.

Subcommands:
  reconcile         The writer: publish every kpars/ file not yet in the
                    generated index branch. Idempotent - already-published
                    files (by digest) are skipped; nothing is ever removed.
  validate BASEREF  Pre-merge validation for MRs/PRs.
                    Writes kpar-report.md describing every submission so
                    reviewers see exactly what is being added (CI posts it
                    on the PR/MR).

A submission is a KPAR file exactly as `sysand build` produced it, placed
directly in kpars/ on the default branch, where it remains: the folder is
the declarative set of submitted artifacts, and the writer reconciles the
index branch against it. The project's identity - publisher, name,
version - comes from the KPAR's own metadata. Review of the pull/merge
request is the publishing gate: what reviewers approve gets published.

Invariants:
- The writer runs serialized (GitHub `concurrency:` / GitLab `resource_group`).
- Prior index state is read from git, never from a deployed/served copy.
- Only the writer's CI identity may push to the index branch (protected);
  the writer never writes to the default branch.
- Published versions are immutable: the writer only ever adds, and a
  changed KPAR under an already-published version is an error.

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
GIT_USER = os.environ.get("GIT_USER", "index-writer")
GIT_EMAIL = os.environ.get("GIT_EMAIL", "index-writer@example.invalid")
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "5"))

KPARS = Path("kpars")
WORKTREE = Path(".index-work")
REPORT = Path("kpar-report.md")
ENTRY_RE = re.compile(r"^kpars/[^/]+\.kpar$")
# Files under kpars/ that are not submissions but are allowed to exist.
KPARS_ALLOWED = {Path("kpars/README.md")}


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
    for path in sorted(KPARS.rglob("*")):
        if path.is_dir() or path in KPARS_ALLOWED:
            continue
        if not ENTRY_RE.match(path.as_posix()):
            raise Fail(f"{path}: submissions must be .kpar files directly in kpars/")
        entries.append(path)
    return entries


def published_digests() -> set[str]:
    """sha256 of every KPAR already on the index branch (in the worktree)."""
    return {
        hashlib.sha256(p.read_bytes()).hexdigest()
        for p in WORKTREE.glob("*/*/*/project.kpar")
    }


def remove_worktree() -> None:
    git("worktree", "remove", "--force", str(WORKTREE), check=False, quiet=True)
    git("worktree", "prune", quiet=True)


def add_entry(entry: Path) -> None:
    """Add one KPAR to the index worktree; sysand derives and validates the
    project's identity from the KPAR metadata. Stage the result."""
    result = run("sysand", "index", "add", "--kpar-path", str(entry),
                 "--index-root", str(WORKTREE), check=False, quiet=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.returncode != 0:
        if "already exists" in (result.stdout or ""):
            raise Fail(
                f"{entry}: this version is already published with different "
                "content - published versions are immutable; bump the version"
            )
        raise Fail(f"{entry}: sysand index add failed")
    changed = git_out("status", "--porcelain", cwd=WORKTREE).splitlines()
    if not changed:
        raise Fail(f"{entry}: sysand index add changed nothing")
    git("add", "-A", cwd=WORKTREE, quiet=True)


def publish_batch(entries: list[Path]) -> None:
    """Apply all entries to a fresh checkout of the index branch; retry the
    whole batch on push races (rebase-retry, serialized writer)."""
    summary = ""  # set after filtering; commit message built below
    for attempt in range(1, MAX_RETRIES + 1):
        git("fetch", REMOTE, INDEX_BRANCH, quiet=True)
        remove_worktree()
        git("worktree", "add", "--detach", str(WORKTREE), f"{REMOTE}/{INDEX_BRANCH}", quiet=True)
        try:
            published = published_digests()
            new = [
                e for e in entries
                if hashlib.sha256(e.read_bytes()).hexdigest() not in published
            ]
            if not new:
                print("Everything in kpars/ is already published - nothing to do.")
                return
            print(f"Publishing {len(new)} artifact(s):")
            for entry in new:
                print(f"  {entry}")
                add_entry(entry)
            git(
                "-c", f"user.name={GIT_USER}", "-c", f"user.email={GIT_EMAIL}",
                "commit", "-m", "index: publish " + " ".join(e.name for e in new),
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


def cmd_reconcile() -> int:
    run("sysand", "--version", quiet=True)  # fail fast if missing
    if git("fetch", REMOTE, INDEX_BRANCH, check=False, quiet=True).returncode != 0:
        raise Fail(
            f"branch '{INDEX_BRANCH}' does not exist on {REMOTE} - it holds "
            "the generated index and must be created once (see ADMINISTRATION.md)"
        )

    entries = find_entries()
    if not entries:
        print("kpars/ is empty - nothing to do.")
        return 0
    publish_batch(entries)
    return 0


def cmd_validate(base_ref: str) -> int:
    """Validate the diff BASE_REF...HEAD and write kpar-report.md
    describing each submission for reviewers."""
    changed = []
    for line in git_out(
        "diff", "--name-status", "--diff-filter=ACMR", f"{base_ref}...HEAD"
    ).splitlines():
        status, _, rest = line.partition("\t")
        path = rest.split("\t")[-1]  # renames/copies: take the new path
        changed.append((status[0], path))
    if not changed:
        print("No changes.")
        return 0

    failures = 0
    sections = ["## Index submission report", ""]
    for status, path in changed:
        if ENTRY_RE.match(path) and status == "M":
            sections.append(
                f"### `{path}`\n\n**REJECTED**: published artifacts are "
                "immutable - do not modify an existing KPAR, publish a new "
                "version instead\n"
            )
            print(f"FAIL: {path} - published artifacts are immutable")
            failures += 1
        elif ENTRY_RE.match(path):
            try:
                sections.append(describe_kpar(Path(path)))
                print(f"ok:   {path}")
            except Fail as exc:
                sections.append(f"### `{Path(path).name}`\n\n**REJECTED**: {exc}\n")
                print(f"FAIL: {exc}")
                failures += 1
        elif Path(path) in KPARS_ALLOWED:
            print(f"ok:   {path}")
        elif path.startswith("kpars/"):
            sections.append(
                f"### `{path}`\n\n**REJECTED**: submissions must be .kpar "
                "files directly in kpars/\n"
            )
            print(f"FAIL: {path} - submissions must be .kpar files directly in kpars/")
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
    sub.add_parser("reconcile", help="run the writer (kpars/ -> index branch)")
    validate = sub.add_parser("validate", help="validate a submission diff")
    validate.add_argument("base_ref", help="merge base, e.g. origin/main")
    args = parser.parse_args()
    try:
        if args.command == "reconcile":
            return cmd_reconcile()
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
