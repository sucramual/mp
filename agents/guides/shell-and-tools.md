# Shell and tools

These instructions supplement the global AGENTS.md.

- For terminal-bound output, render mermaid via `mmd-ascii` (stdin or file arg; `--ascii` for pure ASCII) — wraps `beautiful-mermaid`, lives at `~/dotfiles/tools/mmd-ascii/`. Sequence diagrams render best; cyclic flowcharts get tangled; only 6 diagram types supported (flowchart, state, sequence, class, ER, XY).
- Checks: prefer a command that returns pass or fail. Start a server only when the result needs browser layout or a running app.
  - If you need one, bind it to `127.0.0.1`, stop it in the same turn, and delete any config you made for it (for example `.claude/launch.json`).
  - During a check, load no unpinned script from a CDN.
- Terminal: **Ghostty** on macOS.
- macOS has **no `timeout`**, `flock`, or `gitleaks` (verified 2026-10-15) — don't use them in scripts for this machine. For `timeout`, use `perl -e 'alarm N; exec @ARGV'` or background+wait+kill.
- Shell is **zsh**: unquoted `$VAR` does **not** word-split (no `SH_WORD_SPLIT`) — a variable holding multiple CLI flags (`FLAGS="--a --b"; cmd $FLAGS`) passes as ONE argument and the command errors. Use arrays (`flags=(--a --b); cmd "${flags[@]}"`) or inline the flags; test loop bodies with the variable, not just the inlined command (2026-07-18: two silent watcher failures, errors hidden by `2>/dev/null`).
- In zsh, quote any separator that starts with `=`, for example `echo '===='`, because zsh expands `=word` to a command path (`==== not found`).
- In zsh, write `${VAR}:path`, never `$VAR:path`: zsh reads `:l`, `:s`, `:h` and `:t` after a bare `$VAR` as modifiers, so `git show $M:libs/x` reads the wrong path. Or put the commands in a bash script (2026-11-17: 43 minutes lost).
- To add notes to a file, use the Edit or Write tool, not `cat >> file <<'EOF'`. The guard_irreversible hook checks a heredoc body that names `gh`, `spacectl` or `graphql` as commands, so a note that mentions them is blocked (2026-11-18 and 2026-11-19: a worker and a router were blocked this way).
