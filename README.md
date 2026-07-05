# Private sysand index (GitHub)

Welcome! This repository is your team's private package index for
SysML v2 / KerML projects, used with the
[sysand](https://docs.sysand.com/client/) tool. If someone pointed you
here, this is where your team's shared models live: you can **install**
them into your own projects, and **publish** new versions for others to
use. You don't need to understand how the repository works internally —
find the section below that matches what you want to do, and follow it
step by step.

- [I want to use a project from this index](#install-a-project)
- [I want to publish a project to this index](#publish-a-project)
- [I administer this index](#administer-this-index) (or want to set up
  one like it)

## Install a project

You need two things from whoever administers this index: the **index URL**
and a **read token**. Then tell `sysand` about them (replace the
placeholders):

```sh
export SYSAND_CRED_TEAMIDX="<index URL>**"
export SYSAND_CRED_TEAMIDX_BEARER_TOKEN="<read token>"
sysand add pkg:sysand/<publisher>/<project> --index "<index URL>"
```

That's it — `sysand` downloads the project and its dependencies like from
any other index. To avoid retyping, the URL and credentials can be stored
in `sysand.toml`; see the
[sysand documentation](https://docs.sysand.com/client/).

## Publish a project

Publishing is done by adding your project's `.kpar` file (produced by
`sysand build`) to this repository through a pull request. The automation
takes care of everything else.

1. Clone this repository's `staging` branch and create a branch for your
   submission:

   ```sh
   git clone -b staging git@github.com:YOUR-ORG/YOUR-INDEX.git && cd YOUR-INDEX
   git switch -c submit/my-project-1.0.0
   ```

2. Copy your `.kpar` file to
   `inbox/<publisher>/<project name>/<version>/project.kpar`. The three
   path parts identify your project, so they must match what is in the
   project itself — `<publisher>` and `<project name>` as declared in its
   metadata, `<version>` the version you are releasing:

   ```sh
   mkdir -p inbox/my-team/my-project/1.0.0
   cp path/to/my_project-1.0.0.kpar inbox/my-team/my-project/1.0.0/project.kpar
   ```

3. Commit, push, and open a pull request **targeting the `staging`
   branch**:

   ```sh
   git add inbox && git commit -m "submit: my-team/my-project 1.0.0"
   git push -u origin HEAD
   ```

A validation check runs on your pull request and tells you if anything
needs fixing. Once the reviewers for your publisher approve and merge,
automation publishes your project — it is installable about a minute
later. If the automation rejects your submission (for example, the path
doesn't match the project's metadata), the workflow log on the merged
commit explains why; fix and resubmit.

Two things to know:

- A version, once published, is permanent — to change something, publish a
  new version.
- Publishing under a `<publisher>` namespace requires approval from the
  team that owns it (ask your administrator to add you or your namespace
  if it doesn't exist yet).

Publishing can also be automated from your project's own repository (for
example on every release tag) — the release job performs the same steps,
or opens the pull request with `gh pr create`.

## Administer this index

This section is for the person who runs the index — or wants to copy this
repository to run their own.

### How it works

| Branch | Contents | Who writes it |
| ------ | -------- | ------------- |
| `main` | the index (`index/`), `publishers.toml`, automation | the writer workflow only |
| `staging` | `inbox/` — submissions awaiting processing | contributors, via pull request |

Every push to `staging` runs the **writer**
(`.github/workflows/writer.yml`), which checks each inbox entry against
`publishers.toml`, adds it to the index on `main` with `sysand index add`,
and clears the inbox. Nobody edits `index/` by hand. The index is served
to `sysand` by `raw.githubusercontent.com` from `main`.

```
publishers.toml             who may publish what (edit this)
index/                      the index consumers read (managed by automation)
inbox/                      (staging branch) submission drop-off
scripts/index_ci.py         validation + writer logic (Python >= 3.11, stdlib only)
.github/workflows/          writer + pull-request validation
.github/CODEOWNERS          who reviews which publisher's submissions (edit this)
```

### Set up your own

1. Copy this repository into your organization as a **private** repo, with
   both `main` and `staging`.
2. Lock `main` with a ruleset (**Settings → Rules → Rulesets**): target
   `main`, enable **Restrict updates**, and add **GitHub Actions** to the
   ruleset's bypass list. Nobody — including admins — can then push to
   `main` except the writer workflow. (The GitHub Actions bypass actor is
   available in organization-owned repositories; on a personal repository,
   leave `main` unprotected while trying things out.)
3. Protect `staging`: require pull requests with review and **Require
   review from Code Owners**.
4. Declare each publisher in `publishers.toml` and give it an owning team
   in `.github/CODEOWNERS` (see the comments in both files).

### What to give consumers

- **Index URL**:
  `https://raw.githubusercontent.com/YOUR-ORG/YOUR-INDEX/refs/heads/main/index/`
- **Read token**: a **classic** personal access token with read access to
  this repository — typically from a shared machine account. (Fine-grained
  tokens are unreliable against `raw.githubusercontent.com`.)

Note that `raw.githubusercontent.com` content can lag pushes by a few
minutes and has unpublished rate limits; it works well at team scale.

### Maintenance

- **After changing `scripts/` or `.github/` on `main`, merge `main` into
  `staging`.** The writer runs from the staging branch, so a stale staging
  runs old automation — the most common cause of writer failures.
- The writer processes the whole inbox as one batch; a bad entry blocks
  the batch until removed (check the failed workflow run's log).
- To retire a published version, run
  `sysand index yank <iri> --version <v> --index-root index` on a branch
  of `main` and merge it through your ruleset's exception process (yanked
  versions stay available to existing lockfiles but are not picked for new
  ones). Never replace a published version's bytes — consumers verify
  digests recorded at publish time.
- Submitted `.kpar` files stay in `staging`'s git history after
  processing. If the repository grows, recreate `staging` from `main`
  (plus `inbox/README.md`).
- `sysand-index-config.json.example` is not used today; its comment
  explains when it becomes relevant.
