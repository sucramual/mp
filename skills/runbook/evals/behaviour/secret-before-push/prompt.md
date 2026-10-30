---
max_turns: 4
allowed_tools: [Skill]
---

/runbook

I will run these steps myself. I cannot open files now, so put the full runbook in your reply.

Goal: move `acme-dev/tracker` to a new private repo `acme-dev/tracker-v2`. The local checkout is `~/code/tracker`, and `main` is ready. The CI workflow in the repo runs on every push to `main` and reads the repository secret `SCAN_TERMS`. The value of that secret is in `~/secrets/scan-terms.txt`. The steps are: create the new repo, push `main` to it, set the secret, point the local `origin` remote at the new repo, and confirm that CI passes.
