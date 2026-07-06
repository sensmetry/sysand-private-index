# Administering this index

This page is for the person who runs the index, or who wants to copy this
repository to run their own. For installing and publishing, see the
[README](README.md).

## How it works

| Branch  | Contents                                                                | Who writes it                  |
| ------- | ----------------------------------------------------------------------- | ------------------------------ |
| `main`  | `kpars/` (submitted artifacts), automation, docs; a normal branch       | contributors via pull request  |
| `index` | the **generated index** consumers read (index files at the branch root) | the index-writer workflow only |

Submissions are KPAR files placed directly in `kpars/` via pull requests to
`main`, where they stay. Publisher, name, and version come from each KPAR's
own metadata. Every push to `main` runs the **index-writer**
(`.github/workflows/index-writer.yml`), which _reconciles_ the `index`
branch against `kpars/`: any file not yet published (matched by digest) is
added with `sysand index add`, and everything else is a no-op. The
index-writer is idempotent, never removes anything, and **never writes to
`main`**, so no branch has to grant the automation any special rights
there. Nobody edits the `index` branch by hand. The index is served to
`sysand` by `raw.githubusercontent.com` from the `index` branch.

**Review is the publishing gate**: whatever reviewers approve on `main`
gets published. To make that review meaningful, the validation check
identifies every submitted KPAR (publisher, name, version, license) in its
log, dry-runs the publish, and rejects modifications to already-submitted
files (published versions are immutable). Make this check **required** in
branch protection so a failing submission cannot be merged.

```
kpars/                      submitted artifacts (the index-writer publishes from here)
manage_index.py             the index automation: validate + reconcile (Python >= 3.12, stdlib only)
.github/workflows/          index-writer + pull-request validation
```

## Set up your own

1. Make your own **private** copy that includes **both** the `main` and
   `index` branches. A normal GitHub fork will not do this: forks are
   public and only track the default branch. Use one of these instead.

   - **GitHub's importer** (easiest): open
     [github.com/new/import](https://github.com/new/import), paste this
     repository's URL as the source, choose your organization and a name,
     and set the new repository to **Private**. This copies every branch.
   - **From a terminal**, if you prefer: create a new empty private
     repository on GitHub, then mirror this one into it.

     ```sh
     git clone --bare <this repository's clone URL> index-copy.git
     cd index-copy.git
     git push --mirror <your new repository's URL>
     cd .. && rm -rf index-copy.git
     ```

   Then clone your copy and confirm both branches are there with
   `git branch -a`.

2. Protect `main`: require pull requests with at least one approving
   review. Anyone who can approve a pull request can publish, so that
   review is the whole authorization model. Choose the approvers
   accordingly.
3. Fill in the README for your instance: replace `YOUR-ORG` and
   `YOUR-INDEX` in the install and publish sections with your real values,
   and say who to ask for a read token. Consumers are sent to the README,
   not here.
4. Protect `index` with a ruleset: **Restrict updates**, with **GitHub
   Actions** as the only bypass, so the index-writer is the only thing that
   can touch the published index. (The GitHub Actions bypass actor is
   available in organization-owned repositories. On a personal repository,
   leave `index` unprotected while you try things out.)

If the `index` branch is ever missing (it holds only generated content),
recreate it: `git switch --orphan index`, run `sysand index init`, commit,
and push. The next index-writer run republishes everything in `kpars/`.

## What to give consumers

- **Index URL**:
  `https://raw.githubusercontent.com/YOUR-ORG/YOUR-INDEX/refs/heads/index/`
- **Read token**: a **classic** personal access token with read access to
  this repository, typically from a shared machine account. (Fine-grained
  tokens are unreliable against `raw.githubusercontent.com`.)

Note that `raw.githubusercontent.com` content can lag pushes by a few
minutes and has unpublished rate limits. It works well at team scale.

## Verify your setup (optional)

This repository ships with an empty index. Before you onboard your team,
you can prove the whole pipeline works end to end with a throwaway package:

1. Build a small package with `sysand build`, using a throwaway
   publisher/name you will not reuse.
2. Open a pull request adding its `.kpar` to `kpars/` (see
   [Publish a project](README.md#publish-a-project)) and confirm the
   validation check passes.
3. Merge it, confirm the index-writer run is green, and check the package
   appears under your index URL.
4. Install it with the read token, exactly as a consumer would.
5. Retire the throwaway when you are done. Yank it with
   `sysand index yank <iri> --version <v> --index-root .` on the `index`
   branch, or reset the index to empty by removing its publisher directory
   and setting `index.json` to `{"projects": []}`.

## Maintenance

- The index-writer publishes each submission independently. If one cannot
  be published (for example, an older KPAR that a newer `sysand` rejects),
  it is skipped and reported, the rest are still published, and the run
  fails so you notice (check the workflow run's log). Remove or rebuild the
  offending file to clear it. Removing a file from `kpars/` does **not**
  unpublish it; the index-writer only adds.
- To retire a published version, run
  `sysand index yank <iri> --version <v> --index-root .` on a checkout of
  the `index` branch and push it through your ruleset's exception process
  (yanked versions stay available to existing lockfiles but are not picked
  for new ones). Never replace a published version's bytes, because
  consumers verify the digest recorded at publish time.
- Repository size grows with publish volume (KPARs live in `kpars/`). Keep
  KPARs modest; if this becomes a problem, ask about index formats that
  store archives outside git.
