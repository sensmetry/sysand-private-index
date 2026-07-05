#!/usr/bin/env python3
"""CI logic for this private sysand index.

Subcommands:
  reconcile         The writer: publish every kpars/ file not yet in the
                    generated index branch. Idempotent - already-published
                    files (by digest) are skipped; nothing is ever removed.
  validate BASEREF  Pre-merge validation for MRs/PRs: describes every
                    submission and dry-runs the actual publish against a
                    throwaway checkout of the index branch (nothing is
                    pushed). Writes kpar-report.md so CI can post it on
                    the PR/MR.

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


def add_entry(entry: Path) -> list[str]:
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
        reason = next(
            (l for l in (result.stdout or "").splitlines() if l.startswith("error")),
            (result.stdout or "").strip().splitlines()[-1] if (result.stdout or "").strip() else "unknown error",
        )
        raise Fail(f"{entry}: sysand index add failed: {reason}")
    # Only worktree-side (unstaged/untracked) changes: earlier entries in
    # this batch are already staged and must not leak into this entry's set.
    changed = [
        line[3:] for line in
        git_out("status", "--porcelain", "--untracked-files=all", cwd=WORKTREE).splitlines()
        if line[1] != " "
    ]
    if not changed:
        raise Fail(f"{entry}: sysand index add changed nothing")
    git("add", "-A", cwd=WORKTREE, quiet=True)
    return changed


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


def publish_context(touched: list[str]) -> str:
    """One line of reviewer context: is this a known publisher/project on
    the index branch (list prior versions), or a first appearance?"""
    dirs = {p.split("/")[0] + "/" + p.split("/")[1] for p in touched if p.count("/") >= 2}
    if not dirs:
        return "\n"
    publisher_name = sorted(dirs)[0]
    publisher = publisher_name.split("/")[0]
    known_publisher = bool(
        git_out("ls-tree", "HEAD", "--", publisher, cwd=WORKTREE).strip()
    )
    if not known_publisher:
        return (
            f"\n\n:warning: **First submission under publisher `{publisher}` "
            "on this index** - verify the submitter is entitled to publish "
            "under this name.\n"
        )
    prior = run(
        "git", "show", f"HEAD:{publisher_name}/versions.json",
        cwd=WORKTREE, check=False, quiet=True,
    )
    if prior.returncode == 0:
        versions = [v.get("version") for v in json.loads(prior.stdout).get("versions", [])]
        return f"\nPreviously published versions of `{publisher_name}`: {', '.join(versions)}.\n"
    return (
        f"\n\n:warning: **New project `{publisher_name}` under existing "
        f"publisher `{publisher}`** - verify the submitter is entitled to "
        "publish under this name.\n"
    )


def cmd_validate(base_ref: str) -> int:
    """Validate the diff BASE_REF...HEAD and write kpar-report.md
    describing each submission for reviewers, including a dry-run of the
    actual publish against a throwaway index-branch worktree."""
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

    # Dry-run target: the real index branch in a throwaway worktree.
    dry_run = False
    published: set[str] = set()
    if any(ENTRY_RE.match(p) and s != "M" for s, p in changed):
        if git("fetch", REMOTE, INDEX_BRANCH, check=False, quiet=True).returncode == 0:
            remove_worktree()
            git("worktree", "add", "--detach", str(WORKTREE),
                f"{REMOTE}/{INDEX_BRANCH}", quiet=True)
            published = published_digests()
            dry_run = True
        else:
            print(f"note: no '{INDEX_BRANCH}' branch on {REMOTE} - skipping publish dry-run")

    failures = 0
    sections = [
        "## Index submission report",
        "",
        "> **Approving this change publishes the artifacts below to every "
        "consumer of this index.** Approval is the only gate: confirm each "
        "submission's publisher and project name are ones this submitter is "
        "entitled to publish.",
        "",
    ]
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
                section = describe_kpar(Path(path))
            except Fail as exc:
                sections.append(f"### `{Path(path).name}`\n\n**REJECTED**: {exc}\n")
                print(f"FAIL: {exc}")
                failures += 1
                continue
            if dry_run:
                digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
                if digest in published:
                    section += "\n**Publish check**: already published - the writer will skip it.\n"
                    print(f"ok:   {path} (already published)")
                else:
                    try:
                        touched = add_entry(Path(path))
                        section += "\n**Publish check**: dry-run against the index branch succeeded - will be published on merge."
                        section += publish_context(touched)
                        print(f"ok:   {path} (publish dry-run ok)")
                    except Fail as exc:
                        section += f"\n**REJECTED (publish check)**: {exc}\n"
                        print(f"FAIL: {exc}")
                        failures += 1
            else:
                print(f"ok:   {path}")
            sections.append(section)
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

    if dry_run:
        remove_worktree()
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
