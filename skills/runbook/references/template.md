# Runbook: GOAL

The agent runs the steps in order. It runs each `agent, after yes` step only after Marcus says yes. A `Marcus` step goes to Marcus. Stop if a step fails.
State before step 1: ONE OR TWO SENTENCES ABOUT WHAT IS READY AND CHECKED.

## 1. Pause the background jobs

Runs: agent, after yes.

They could act on a half-done state.

```bash
COMMAND THAT PAUSES JOB A
```

## 2. PRIVATE, REVERSIBLE STEP

Runs: agent, after yes.

PURPOSE LINE.

```bash
COMMAND
```

## 3. Set the inputs that later steps read

Runs: agent, after yes.

Step 4 starts CI, and CI reads `SECRET_NAME`. Set it first.

```bash
gh secret set SECRET_NAME --repo OWNER/REPO < PATH/TO/VALUE/FILE
```

## 4. STEP THAT STARTS AN ACTION

Runs: agent, after yes.

PURPOSE LINE. KNOWN PITFALL, AND HOW THIS STEP AVOIDS IT.

```bash
COMMAND
```

## 5. Check gate

Runs: agent.

```bash
GH_PAGER=cat gh run list --repo OWNER/REPO --limit 3
```

JOB NAMES must pass before step 6.

## 6. IRREVERSIBLE OR PUBLIC STEP

Runs: agent, after yes.

PURPOSE LINE. The payload is ready at `ABSOLUTE/PATH.json`.

```bash
gh api -X PUT repos/OWNER/REPO/ENDPOINT --input ABSOLUTE/PATH.json
```

## 7. Restart the background jobs

Runs: agent, after yes.

```bash
COMMAND THAT RESTARTS JOB A
```

## 8. Smoke test

Runs: agent.

ONE ACTION THAT RUNS THE WHOLE PATH END TO END, AND THE RESULT THAT PROVES IT.
