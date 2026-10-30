# Devbox hooks

These files make the dotfiles work on the work devbox. The devbox is a headless Google Cloud Workstation with a persistent `/home`. The hooks give it the `/rogue` skill, the tools in `~/bin`, the automatic sync, and the verify-browser: a Chrome, signed in to Okta once, that agents drive for `/verify`.

## First install

1. On the devbox, run `gh auth login`. The devbox has its own login. Never copy laptop credentials to it.
2. On the laptop, run:

   ```bash
   scripts/devbox.sh run 'gh repo clone sucramual/mp ~/dotfiles && ~/dotfiles/install.sh'
   ```

3. Run `scripts/devbox.sh bootstrap` after a rebuild. Step `20-dotfiles` clones the repository and runs `install.sh` again. It prints the `gh auth login` command and stops when the devbox has no login. Step `30-verify-browser` installs the verify-browser Chrome. Neither step prompts.
4. After the first install, step `30-verify-browser` is not linked yet when the bootstrap starts. Run `verify-browser install` once, or run the bootstrap again. Then [sign in to Okta](#sign-in-to-okta-once).

## What `install.sh` links

`scripts/install_devbox.sh` runs only on a devbox. It sees `/opt/devbox` and Linux, or `DOTFILES_DEVBOX=1`.

| Link | Target | Purpose |
| --- | --- | --- |
| `~/.config/devbox/bootstrap.d/20-dotfiles` | `config/devbox/bootstrap.d/20-dotfiles` | Bootstrap step that clones and installs |
| `~/.config/devbox/bootstrap.d/30-verify-browser` | `config/devbox/bootstrap.d/30-verify-browser` | Bootstrap step that runs `verify-browser install` |
| `~/.config/devbox/on-start` | `config/devbox/on-start` | Starts the `dotfiles-sync` tmux session, and `verify-browser` when its Chrome is installed, on each devbox start |
| `~/bin/verify-browser` | `config/devbox/verify-browser/verify-browser` | The verify-browser command |

The installer also registers the Chrome DevTools MCP server `chrome-devtools` for Claude Code (user scope) and Codex, through `claude mcp add` and `codex mcp add`. The server runs `npx -y chrome-devtools-mcp@latest --browserUrl http://127.0.0.1:9222`, so it drives the verify-browser Chrome and never launches its own. An existing `chrome-devtools` entry stays unchanged. The Mac never gets this server.

A re-run changes nothing. A regular file at a target moves to `<target>.bak`. An existing `on-start` that you own stays in place. The installer prints a WARNING with the line to add to it.

## Sync and logs

The `dotfiles-sync` tmux session runs `tools/dotfiles-pr/sync-loop`. The loop runs `dotfiles-pr sync --no-prune` every 900 seconds. A failed run does not stop the loop.

- `~/.local/state/dotfiles-pr/sync.log`: one line when the outcome changes.
- `~/.local/state/dotfiles-pr/sync-last-run.log`: the full output of the last run.
- `tmux attach -t dotfiles-sync`: shows the loop.

## verify-browser

The unattended `/neo` and `/rogue` runs end with `/verify`, which clicks through staging. Staging needs Okta. So the devbox keeps one Chrome that Marcus signs in to once, and agents drive it through the Chrome DevTools MCP server.

The tmux session `verify-browser` has five windows:

| Window | Runs |
| --- | --- |
| `xvfb` | `Xvfb :99`, a virtual display of 1440x900 |
| `chrome` | Chrome for Testing on display `:99`, with the DevTools port `127.0.0.1:9222` and the profile `~/.local/state/verify-browser/profile` |
| `vnc` | `x11vnc` on `127.0.0.1:5900`, which shows the display |
| `novnc` | `websockify` on `127.0.0.1:6080`, which serves noVNC, the VNC client in a web page |
| `keepalive` | an Okta session check every 3600 seconds |

Each window restarts its process 5 seconds after it exits, and appends one line per restart to `~/.local/state/verify-browser/<window>.log`. So a crashed Chrome or Xvfb comes back without `start`.

| Command | Does |
| --- | --- |
| `verify-browser install` | Installs `xvfb x11vnc novnc websockify` with `sudo -n apt-get`, and Chrome for Testing under `~/.local/share/verify-browser`. `current/chrome` is the stable path. A re-run installs only what is missing. To update Chrome, delete the `current` link and run it again. |
| `verify-browser start` | Starts the session. It does nothing when the session exists. |
| `verify-browser stop` | Ends the session and its window loops first, so nothing restarts Chrome. Then it stops the Chrome whose `--user-data-dir` is the profile. |
| `verify-browser status --json` | Says whether Chrome answers, and the Okta session's `status`, `createdAt`, `lastPasswordVerification`, `lastFactorVerification`, and `expiresAt`. Exit 0 only when the session is `ACTIVE`. |

`auth-helper check --require okta` reads `verify-browser status --json` on the devbox. See [auth-helper](../../tools/auth-helper/README.md).

### Set the Okta URL

The Okta check needs your Okta URL, such as `https://<your-org>.okta.com`. It reads `VERIFY_BROWSER_OKTA_URL`, else the first line of `~/.config/verify-browser/okta-url`. Write the file once:

```bash
mkdir -p ~/.config/verify-browser
echo 'https://<your-org>.okta.com' >~/.config/verify-browser/okta-url
```

Without a URL, `status --json` reports an `okta.error` that names both settings, and exits 1. `auth-helper` passes its own Okta URL, so its check works without the file.

### Sign in to Okta once

1. Find your workstation's URL for port 6080.
2. Open `<that URL>/vnc.html?autoconnect=1&resize=scale`. The workstation gateway asks for a Google sign-in first.
3. In the Chrome on the page, open your Okta URL and sign in. Tick "Keep me signed in".
4. On the devbox, run `verify-browser status --json`. Okta `status` must be `ACTIVE`.

Do the same when `auth-helper` reports `okta` as `expired`.

### Session lifetime and keep-alive

Okta ends a session after 2 hours without a page load. Each page load renews this idle timeout, so `expiresAt` is always about 2 hours ahead. The absolute session limit is not known yet.

The `keepalive` window opens the Okta dashboard at your Okta URL every 3600 seconds, which renews the idle timeout. It appends one JSON line per check to `~/.local/state/verify-browser/okta-session.log`. The line holds the check time, whether Chrome answered, and the session status and times.

After a Chrome crash or a `SIGKILL`, the profile keeps the session, but Chrome refuses to start while its `Singleton*` lock files remain. The `chrome` window removes them, but only when no process uses the profile.

### Security

- The profile holds a live Okta session. The profile and its parent folder are mode 700.
- The DevTools port, VNC, and noVNC listen on `127.0.0.1` only. VNC has no password, so do not expose port 5900. The workstation gateway, behind a Google sign-in, is the only way in from outside.
- Any process on the devbox can drive the signed-in Chrome through port 9222. Run only trusted code on the devbox.
- The Okta check reads only status and times, never a session ID, token, or cookie value.

## Stop or remove

- Stop the loop: `tmux kill-session -t dotfiles-sync`. It starts again at the next devbox start.
- Stop the verify-browser: `verify-browser stop`. It starts again at the next devbox start.
- Remove the hooks: delete the links in `~/.config/devbox/` and `~/bin/verify-browser`. Then stop the sessions. Remove the MCP server with `claude mcp remove --scope user chrome-devtools` and `codex mcp remove chrome-devtools`.
