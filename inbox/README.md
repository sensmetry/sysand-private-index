# Submission inbox

This is where new project versions are dropped off for publishing — see
**"Publish a project"** in the repository README for the full step-by-step
guide.

In short, a submission is one `.kpar` file (exactly as `sysand build`
produced it) added directly to this folder via a pull request:

```
inbox/my_project-1.0.0.kpar
```

Validation posts a comment on your pull request describing what the file
contains. After your submission is approved and merged, automation
publishes it to the index and removes it from this folder — an empty
inbox means everything has been processed.
