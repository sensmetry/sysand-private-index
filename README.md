# Private sysand index (GitHub)

This repository is your team's private package index for SysML v2 / KerML
projects, used with the [sysand](https://docs.sysand.com/client/) tool. If
someone pointed you here, this is where your team's shared models live: you
can **install** them into your own projects and **publish** new versions
for others to use. You don't need to know how the repository works inside.
Find the section below that matches what you want to do and follow it.

- [I want to use a project from this index](#install-a-project)
- [I want to publish a project to this index](#publish-a-project)
- I administer this index (or want to set up one like it):
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

Two notes on the first line. `TEAMIDX` is any label you like. The trailing
`**` is required: it tells `sysand` to send the token for everything under
the index URL, so don't remove it. To see what projects exist, browse this
repository's `index` branch, where folders are laid out as
`<publisher>/<project>/`.

That's all there is to it. `sysand` downloads the project and its
dependencies just like it would from any other index. To avoid retyping,
you can store the URL and credentials in `sysand.toml`; see the
[sysand documentation](https://docs.sysand.com/client/).

If you see `no resolver was able to resolve the IRI`, check three things:
(1) the token (GitHub reports bad auth as a 404, so a bad token looks like
a missing project); (2) that the `**` is still at the end of the
`SYSAND_CRED_*` URL; (3) the publisher/project spelling against the `index`
branch.

## Publish a project

You publish by adding your project's `.kpar` file (produced by
`sysand build`) to this repository through a pull request. The automation
handles the rest.

1. Clone this repository and create a branch for your submission:

   ```sh
   git clone git@github.com:YOUR-ORG/YOUR-INDEX.git && cd YOUR-INDEX
   git switch -c submit/my-project-1.0.0
   ```

2. Copy your `.kpar` file into the `kpars/` folder, exactly as
   `sysand build` produced it (no renaming):

   ```sh
   cp path/to/my_project-1.0.0.kpar kpars/
   ```

   Everything about your project (publisher, name, version) is read from
   the file itself.

3. Commit, push, and open a pull request:

   ```sh
   git add kpars && git commit -m "submit: my-team/my-project 1.0.0"
   git push -u origin HEAD
   ```

A validation check runs on your pull request. It identifies your submission
(publisher, name, version, license) and dry-runs the actual publish, so a
bad submission fails the check before it can be merged. The result shows in
the check's log. Once your pull request is approved and merged, the
automation publishes the project, and it is installable about a minute
later.

One thing to know: a published version is permanent. To change something,
publish a new version.

You can also automate publishing from your project's own repository, for
example on every release tag. The release job does the same steps, or opens
the pull request with `gh pr create`.
