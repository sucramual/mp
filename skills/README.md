# Skills

Agent skills for Claude Code, Codex, and Cursor. The main set is the **neo suite**: you give it a Linear ticket and answer one intake message. It comes back with merged PRs that pass the ticket's checks.

## Install

You need Python 3.11 or newer, [`uv`](https://docs.astral.sh/uv/), `gh` signed in, and Claude Code or Codex with the Linear MCP connected.

1. Clone the repository. Do not run its `./install.sh`: that installs Marcus's whole machine setup and replaces your `~/.zshrc`.

   ```bash
   git clone https://github.com/sucramual/mp.git ~/mp && cd ~/mp
   ```

2. Choose your skills in a checklist, and link them into `~/.claude/skills` and `~/.agents/skills`:

   ```bash
   python3 scripts/link_skills.py --pick
   ```

   To see each skill and its description first, run `python3 scripts/link_skills.py --list`.

   **For the neo suite**, skip the checklist and select its seven skills directly:

   ```bash
   mkdir -p ~/.config/dotfiles
   printf '%s\n' neo matrix perf open-pr review-pr verify retro > ~/.config/dotfiles/skills.txt
   python3 scripts/link_skills.py
   ```

3. Link the tools (`agent-trace`, `auth-helper`, and others) into `~/bin`, and put `~/bin` on your `PATH`:

   ```bash
   python3 scripts/link_tools.py
   ```

4. Add the hooks. They block unpinned merges and Spacelift writes, and record each run's trace:

   ```bash
   python3 config/agent-hooks/install_hooks.py ~/.claude/settings.json ~/.codex/hooks.json
   ```

5. Restart Claude Code or Codex.

To update, run `git pull` in `~/mp`. The links point at your clone, so the change is live at once.

## Use

| You have | Type | You get |
| --- | --- | --- |
| One ticket | `/neo ABC-123` | Merged PRs that pass each ticket check |
| A goal too large for one PR | `/matrix <goal>` | The goal split across several `neo` workers, with one decision queue for you |
| An idea to test, such as a speed-up | `/perf <idea>` | A decision record from experiments. It merges nothing. |
| Finished runs | `/retro last 5 runs` | Suggested fixes to skills and tools |

A run starts with one intake message. It gives a pass/fail check for each requirement and names each login that will expire before the run ends, with the command to fix it. Answer it, then leave. The run ends with one message that lists the merged PRs and each item it parked for you.

The skills name Marcus as the person who answers intake and merges parked PRs. Read that as you.

A run never does these things:

- Merge a guarded change: data, migrations, infra, auth, secrets, or CI workflows. It parks the PR for you with the merge command.
- Merge a commit other than the one it reviewed.
- Write to Spacelift.
- Call the work done before each ticket check passes on the merged result.

## More

- [How the neo suite works](neo-suite.md): the flow diagram and each part's job.
- [Neo suite vocabulary](neo-vocabulary.md): chain, PR brief, park, and other terms.
- [Maintaining the skills](MAINTAINING.md): how the links work, per-machine selection, third-party skills, versions, and evals.
