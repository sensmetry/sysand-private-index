<!-- Structure and wording kept in sync with the GitLab example
     repository's ADMINISTRATION.md; only platform details differ. -->

# Administering this index

This page is for the person setting up an index from this repository (and
running it afterwards). For installing and publishing, see the
[README](README.md).

## How it works

This repository implements the [reviewed team index
model](https://docs.sysand.com/client/explanation/reviewed-team-index/):
contributors add KPAR files to `kpars/` through reviewed pull requests,
and automation publishes whatever lands on `main`.

| Branch  | Contents                                                                | Who writes it                  |
| ------- | ----------------------------------------------------------------------- | ------------------------------ |
| `main`  | `kpars/` (submitted artifacts), automation, docs; a normal branch       | contributors via pull request  |
| `index` | the **generated index** consumers read (index files at the branch root) | the index-writer workflow only |

Every push to `main` runs the **index-writer**
(`.github/workflows/index-writer.yml`), which _reconciles_ the `index`
branch against `kpars/`: any file not yet published (matched by digest) is
added with `sysand index add`, and everything else is a no-op. The
index-writer is idempotent, never removes anything, and **never writes to
`main`**. The index is served to `sysand` by `raw.githubusercontent.com`
from the `index` branch.

The validation check identifies every submitted KPAR (publisher, name,
version, license) in its log, dry-runs the publish, and rejects
modifications to already-submitted files (published versions are
immutable). Review is the publishing gate, so make this check
**required** in branch protection: a failing submission then cannot be
merged.

```
kpars/                      submitted artifacts (the index-writer publishes from here)
manage_index.py             the index automation: validate + reconcile (Python >= 3.12, stdlib only)
.github/workflows/          index-writer + pull-request validation
```

## Set up your own

1. Make your own **private** copy that includes **both** the `main` and
   `index` branches. A normal GitHub fork will not do this: a fork of a
   public repository stays public. Use one of these instead.

   - **GitHub's importer** (easiest): open
     [github.com/new/import](https://github.com/new/import), paste this
     repository's URL as the source, choose your organization and a name,
     and set the new repository to **Private**. This copies every branch.
   - **From a terminal**: create a new empty private repository on
     GitHub, then mirror this one into it.

     ```sh
     git clone --bare <this repository's clone URL> index-copy.git
     cd index-copy.git
     git push --mirror <your new repository's URL>
     cd .. && rm -rf index-copy.git
     ```

   Clone your copy and check both branches arrived (`git branch -a`).

2. Fill in the README for your instance: search-and-replace every
   `YOUR-ORG` and `YOUR-INDEX` in `README.md` (including the token link at
   the bottom).
3. Allow fine-grained personal access tokens in your organization
   (**Organization settings → Personal access tokens**), and decide there
   whether tokens need admin approval. Consumers create their own read
   tokens this way; see
   [How consumers access the index](#how-consumers-access-the-index).
4. Protect `main`: require pull requests with at least one approving
   review, and make the validation check, named `validate`, **required**
   so a failing submission cannot be merged. (The check appears in the
   picker only after it has run once, e.g. on the
   [Verify your setup](#verify-your-setup-optional) pull request, or you
   can type the name into a ruleset.)
5. Protect `index` with a ruleset: **Restrict updates**, with **GitHub
   Actions** as the only bypass, so the index-writer is the only thing that
   can touch the published index. (The GitHub Actions bypass actor is
   available in organization-owned repositories. On a personal repository,
   leave `index` unprotected while you try things out.)

## GitHub Enterprise

This guide assumes github.com. On GitHub Enterprise Cloud with data
residency, replace `raw.githubusercontent.com` with
`raw.SUBDOMAIN.ghe.com`. On GitHub Enterprise Server, the raw URL is
`https://HOSTNAME/raw/...` (or `raw.HOSTNAME` with subdomain isolation),
GitHub Actions must be enabled by your site admin, and you should verify a
bearer-token fetch of a raw file works on your instance before onboarding.
On both, also update the `github.com` hosts in the README's links when
filling it in.

## How consumers access the index

Consumers self-serve per the [README](README.md#install-a-project). Two
admin-side facts: GitHub does not support fine-grained tokens for outside
collaborators, so consumers must be organization members; and
`raw.githubusercontent.com` can lag pushes by a few minutes and has
unpublished rate limits, which is fine at team scale.

## Verify your setup (optional)

This repository ships with an empty index. Before you onboard your team,
you can prove the whole pipeline works end to end with a throwaway package:

1. Build a small package with `sysand build`, using a throwaway
   publisher/name you will not reuse.
2. Open a pull request adding its `.kpar` to `kpars/` (see
   [Publish a project](README.md#publish-a-project)) and confirm the
   validation check passes.
3. Merge it, confirm the index-writer run is green, and check the package
   appears on the `index` branch under `<publisher>/<project>/`.
4. Install it with the read token, exactly as a consumer would.
5. Retire the throwaway with the yank procedure under
   [Maintenance](#maintenance) (and remove its `.kpar` from `kpars/`).

## Maintenance

- The index-writer publishes each submission independently. If one cannot
  be published (for example, an older KPAR that a newer `sysand` rejects),
  it is skipped, the rest are still published, and the run fails; the log
  names the offender. Remove or rebuild the offending file to clear it.
  Removing a file from `kpars/` does **not** unpublish it; the
  index-writer only adds.
- To retire a published version, yank it on the `index` branch. Only the
  index-writer can normally push there, so grant yourself push access for
  the moment: in **Settings → Rules → Rulesets**, add yourself (or "Repository
  admin") to the `index` ruleset's bypass list. Then:

  ```sh
  git switch index && git pull
  sysand index yank <iri> --version <v> --index-root .
  git commit -am "yank <iri> <v>" && git push
  ```

  Remove yourself from the bypass list again afterwards. Yanked versions
  stay available to existing lockfiles but are not picked for new ones.
  Never replace a published version's bytes, because consumers verify the
  digest recorded at publish time.

- When upgrading sysand, update the pinned version in both workflow files
  (`index-writer.yml` and `validate-pr.yml`) together.
- If the `index` branch is ever missing, recreate it: `git switch --orphan
  index`, run `sysand index init`, commit, and push. The next index-writer
  run republishes everything in `kpars/`.
