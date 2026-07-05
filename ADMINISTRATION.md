# Administering this index

This page is for the person who runs the index — or wants to copy this
repository to run their own. For installing and publishing, see the
[README](README.md).

## How it works

| Branch  | Contents                                                                | Who writes it                  |
| ------- | ----------------------------------------------------------------------- | ------------------------------ |
| `main`  | `kpars/` (submitted artifacts), automation, docs — a normal branch      | contributors via pull request  |
| `index` | the **generated index** consumers read (index files at the branch root) | the index-writer workflow only |

Submissions are KPAR files placed directly in `kpars/` via pull requests
to `main`, where they remain; publisher, name, and version come from each
KPAR's own metadata. Every push to `main` runs the **index-writer**
(`.github/workflows/index-writer.yml`), which _reconciles_ the `index` branch
against `kpars/`: any file not yet published (by digest) is added with
`sysand index add`; everything else is a no-op. The index-writer is idempotent,
never removes anything, and **never writes to `main`** — no branch needs
to grant automation any special rights on `main`. Nobody edits the
`index` branch by hand. The index is served to `sysand` by
`raw.githubusercontent.com` from the `index` branch.

**Review is the publishing gate**: whatever reviewers approve on `main`
gets published. To make that review meaningful, the validation check
identifies every submitted KPAR (publisher, name, version, license) in
its log, dry-runs the publish, and rejects modifications to
already-submitted files (published versions are immutable). Make this
check **required** in branch protection so a failing submission cannot
be merged.

```
kpars/                      submitted artifacts (the index-writer publishes from here)
manage_index.py             the index automation: validate + reconcile (Python >= 3.11, stdlib only)
.github/workflows/          index-writer + pull-request validation
```

## Set up your own

1. Copy this repository into your organization as a **private** repo, with
   both the `main` and `index` branches.
2. Protect `main`: require pull requests with at least one approving
   review. Whoever can approve pull requests can publish — that review is
   the entire authorization model, so choose the approvers accordingly.
3. Fill in the README for your instance: replace `YOUR-ORG`/`YOUR-INDEX`
   in the install and publish sections with your real values, and say who
   to ask for a read token — consumers are sent to the README, not here.
4. Protect `index` with a ruleset: **Restrict updates**, with **GitHub
   Actions** as the only bypass — the index-writer is then the only thing that
   can touch the published index. (The GitHub Actions bypass actor is
   available in organization-owned repositories; on a personal repository,
   leave `index` unprotected while trying things out.)

If the `index` branch is ever missing (it holds only generated content),
recreate it: `git switch --orphan index`, run `sysand index init`, commit,
push — the next index-writer run republishes everything in `kpars/`.

## What to give consumers

- **Index URL**:
  `https://raw.githubusercontent.com/YOUR-ORG/YOUR-INDEX/refs/heads/index/`
- **Read token**: a **classic** personal access token with read access to
  this repository — typically from a shared machine account. (Fine-grained
  tokens are unreliable against `raw.githubusercontent.com`.)

Note that `raw.githubusercontent.com` content can lag pushes by a few
minutes and has unpublished rate limits; it works well at team scale.

## Maintenance

- The index-writer processes submissions as one batch; a bad file blocks the
  batch until removed (check the failed workflow run's log). Removing a
  file from `kpars/` does **not** unpublish it — the index-writer only adds.
- To retire a published version, run
  `sysand index yank <iri> --version <v> --index-root .` on a checkout of
  the `index` branch and push it through your ruleset's exception process
  (yanked versions stay available to existing lockfiles but are not
  picked for new ones). Never replace a published version's bytes —
  consumers verify digests recorded at publish time.
- Repository size grows with publish volume (KPARs live in `kpars/`).
  Keep KPARs modest; if this becomes a problem, ask about index formats
  that store archives outside git.
