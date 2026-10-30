# Agent completion sound

One Python runtime plays macOS's Glass sound when an agent turn completes.
The Codex and Claude Code adapters only select their event input and preserve each harness's callback contract.
The tool uses no resident service or model call.

After merging and running `dotfiles-pr sync`, run `./install.sh` from the dotfiles checkout.
Sync updates the checkout; the installer creates the tool link and adds both config entries.
The installer and the shared runtime need Python 3.11 or later.
On other operating systems, the installer skips audio config.

The installer creates `~/bin/acs` and `~/bin/agent-completion-sound.py` through the standard tool link loop.
It invokes the executable helper by its absolute path.
The helper's `python3` shebang uses the Python available on `PATH`, so hooks do not depend on the installer-time interpreter.
It adds one asynchronous Claude `Stop` command to the real `~/.claude/settings.json` file.
It wraps the current Codex `notify` argument list in the real `~/.codex/config.toml` file.
Without an existing callback, Codex uses sound-only mode.

The shared runtime reads Claude's event from standard input and Codex's appended JSON argument.
It plays sound only for Claude `Stop` and Codex `agent-turn-complete` events.
It forwards every Codex callback argument unchanged, without a shell.
It inherits callback output and returns the callback's status.
Sound playback starts before the callback and fails independently.
The runtime waits up to ten seconds for playback, then stops a stuck audio process.

Use one command to control completion sounds for both harnesses:

```sh
acs off
acs on
acs status
```

Sounds are on by default. `off` creates `~/.config/agent-completion-sound/disabled`; `on` removes it.
The preference persists across sessions. The fixed home path works independently of `XDG_CONFIG_HOME`.
Both adapters read it before each playback, so changes affect subsequent completions without a helper restart.
The controls leave harness configs intact. The `.py` command accepts the same controls.
Use `acs --help` for usage. Control errors report a failure; hook preference errors stay quiet and allow playback.
Codex callbacks still run when sound is off.
After this change merges, run `dotfiles-pr sync` and `./install.sh` to install the new command link.

Repeated installation leaves current config files unchanged.
Migration recognises only the exact old `~/.local/bin/agent-completion-sound.py` and new `~/bin/agent-completion-sound.py` paths.
It migrates both direct helper commands and legacy Python-prefixed commands.
It updates the owned Claude command, sets its `async` field to `true`, and removes duplicate owned hooks.
It unwraps nested known Codex wrappers.
Other fields of the retained owned hook remain intact.
Other callbacks, hooks, and settings remain intact.
The installer preserves unrelated TOML text and verifies the parsed result before writing.
Claude JSON formatting can change when the owned hook changes.
Unsupported TOML layouts fail without a config rewrite.

Each changed config receives a content backup at `<path>.bak` or `<path>.bak.N`.
The installer preserves file modes, replaces symlinks instead of their source files, and checks for concurrent edits before replacement.
The final check and replacement are separate operations; close config editors during installation.
For rollback, restore the required backup contents to the original config file.
The legacy helper stays installed so its previous config still works after rollback.

Tests use temporary home directories and fake audio and callback commands.
They verify installation, migration, event filtering, callback arguments, output, exit status, and independent failures.
