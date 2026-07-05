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
- I administer this index (or want to set up one like it) →
  [ADMINISTRATION.md](ADMINISTRATION.md)

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
