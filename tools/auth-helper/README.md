# auth-helper

`auth-helper` checks the logins that an unattended agent run needs, and refreshes them. The `/rogue` and `/neo` skills run `auth-helper check` at intake. Run `auth-helper refresh` yourself before you leave an agent to run alone.

`rogue-auth`, the old name, is an alias: `bin/rogue-auth` is a link to `bin/auth-helper`, so old commands and docs keep working.

`bin/auth-helper` is one Python script that needs only the standard library. The team's settings come from the [team config](#configuration), a JSON file: the Spacelift profile and endpoint, the Okta URL, and the probe sets. The private work overlay installs it. See [History](#history).

The login commands and the access probes are adapted from the team's infra login helpers.

## Quick Start

```bash
auth-helper check                                    # table: is each login ok now?
auth-helper check --require gh,gcloud,spacelift --horizon 8h --probes team --json
auth-helper refresh --horizon 8h                     # log in again, interactively
auth-helper refresh spacelift                        # one provider only
auth-helper record okta expired                      # after a Chrome check shows the Okta sign-in page
```

If your shell cannot find `auth-helper`, run `dotfiles-pr sync`. It links every `tools/*/bin/*` into `~/bin`. On a new machine, run `./install.sh` from your dotfiles checkout first.

## Commands

| Command | What it does |
| --- | --- |
| `auth-helper check` | Non-interactive. Checks each provider and prints a table and the fix for each login that is not ok. Exits 0 when every required login is ok and every probe passes. Otherwise it exits 1. |
| `check --require P[,P...]` | Sets the providers that must be ok. The default is `gh` only. All providers are always reported. |
| `check --horizon DURATION` | Marks a login `expiring` when its known or estimated expiry falls inside the duration, for example `8h`, `90m`, or `1h30m`. A login with an unknown expiry keeps its status and gets a warning. See [Expiry](#expiry). |
| `check --probes SET[,SET...]` | Also runs the read-only access probes of a set from the [team config](#configuration). Each failed probe makes the check fail. Without probe sets in the team config, each requested set fails as `not configured`. |
| `check --json` | Prints the JSON report below instead of the table. |
| `auth-helper refresh [PROVIDER...]` | Interactive. Runs the login flow of each named provider (all providers when you name none), then checks that provider again and prints the result. Exits 1 when a login command fails or a login is still not ok. A failed login command fails refresh even when the old credential still works, because the credential was not renewed. |
| `refresh --horizon DURATION` | Applies the same horizon rule as `check`. It runs a conditional login (gh, signadot) when its known or estimated expiry falls inside the duration, and it fails when the new login still expires inside it. The table that `check --horizon` prints suggests a `refresh` command with the same horizon. |
| `auth-helper record okta ok\|expired` | Records the result of a check that the shell cannot run: the `/rogue` skill's Chrome check of Okta. See [Login history](#login-history). |

A mistyped provider, probe set, duration, or `record` value exits 2 before any check, login, or record runs. So does a horizon longer than `3650d`, and a team config that exists but is not valid.

One rule decides `ok` for `check` and `refresh`: the team's identity works now and stays valid through `--horizon`.

## Providers

| Provider | Check | Fix and `refresh` command | Expiry |
| --- | --- | --- | --- |
| `gh` | `gh auth status --json hosts` for the active github.com account. If it does not report success, `gh api user` decides (see below) | `gh auth login --hostname github.com --web`, only when the check fails | observed |
| `gcloud` | the active account, then `gcloud auth print-access-token` | `gcloud auth login --force --update-adc --quiet` | observed |
| `gcloud-adc` | `gcloud auth application-default print-access-token` | the same `gcloud auth login` command, run once for both entries | observed |
| `spacelift` | no `SPACELIFT_API_*` variable, the current profile is the team profile (`spacelift.profile`), then `spacectl whoami` | `spacectl profile login --method browser --endpoint <spacelift.endpoint> <spacelift.profile>`, which also selects the profile | `exp` of the session token, else observed |
| `signadot` | `signadot sandbox list` | `signadot auth login`, only when the check fails | `expiresAt` from `signadot auth status -o json` |
| `okta` | none: the shell cannot see Chrome's session | opens the team Okta URL (`okta.url`) in Google Chrome | observed, from `auth-helper record` |

On the laptop, Okta is always `manual`, never `ok`. When a run requires `okta`, the agent must confirm the Okta session in Chrome.

A provider that needs a team setting is `error` when the team config does not set it: `spacelift` without `spacelift.profile` and `spacelift.endpoint`, and `okta` on the laptop without `okta.url`. Its `fix` starts with `Not configured:` and names the config path. `refresh` runs no login for it and exits 1.

On a devbox, the `okta` check and `refresh` differ from this row: `auth-helper` asks the verify-browser Chrome (see [config/devbox/README.md](../../config/devbox/README.md)). It uses the same devbox rule as `scripts/install_devbox.sh`: `DOTFILES_DEVBOX=1` or `0` forces it, else `/opt/devbox` (or `$DOTFILES_DEVBOX_MARKER`) exists on Linux.

- `ok`: the Okta session is `ACTIVE`.
- `expired`: Chrome answers, but the session is not `ACTIVE`. The fix is the noVNC sign-in step.
- `error`: Chrome does not answer, or the check never reached Okta, for example because no Okta URL is set. The fix restarts `verify-browser`.
- `manual`: `verify-browser` is not installed.

`auth-helper` passes the team Okta URL to `verify-browser` as `VERIFY_BROWSER_OKTA_URL`. Without it, `verify-browser` uses its own setting. When that is missing too, the check reaches no Okta page and reports `error`.

Okta's `expiresAt` is only the 2-hour idle expiry, which each page load renews. So `auth-helper` does not use it as the expiry: `expires_at` stays `null`, and `--horizon` keeps the unknown-lifetime warning until the absolute session limit is known.

The Claude Code cloud egress proxy blocks GraphQL. There, `gh auth status` reports an error for a working token.
So when `gh auth status` does not report success, `auth-helper` calls `gh api user` (REST). If that works, the gh login is `ok`, and `refresh` does not open a browser login.

Spacelift is `error` when another profile is current, with the login command as its fix. It is also `error` while any `SPACELIFT_API_*` variable is set, because spacectl uses those credentials before the selected profile. Its fix is then `unset` with the variable names. The tool never prints their values.

### Status values

| Status | Meaning |
| --- | --- |
| `ok` | The team's identity works now, and its known or estimated expiry is outside the horizon. |
| `expiring` | The login works now, but its known or estimated expiry falls inside `--horizon`. |
| `expired` | A login exists, but the provider rejected it. |
| `missing` | The CLI is not installed, or no login exists. |
| `manual` | The shell cannot check this login (Okta, except on a devbox with `verify-browser`). |
| `error` | The check failed for another reason, such as a timeout, unexpected output, a Spacelift identity that is not the team's, or a team setting that is not configured. |

## Expiry

`check` takes the expiry of each login from the first source that has one. `expires_source` names it.

| `expires_source` | Source | Providers |
| --- | --- | --- |
| `provider` | The CLI shows the expiry without a token. | signadot |
| `token` | The `exp` claim of the session token, decoded on this machine. | spacelift |
| `observed` | The last refresh plus the shortest observed lifetime, from the [login history](#login-history). | any provider with observations |
| `unknown` | No source has an expiry. | |

For Spacelift, the tool reads `profiles.<team profile>.credentials.access_token` from `config.json` in `$SPACELIFT_CONFIG_DIR`, else in `~/.spacelift`, where spacectl 1.26.0 keeps it. The token is a JWT. The tool base64url-decodes only its middle segment, the payload, and keeps only `exp`. When the file, the profile, the JWT format, or `exp` is missing, the expiry is `unknown`, and the check does not fail.

The other logins have no readable expiry: their lifetime comes from org policy. The gcloud access token renews itself, so its one-hour expiry says nothing about the login. For these logins, the tool learns lifetimes by observation.

### Horizon rule

| Expiry | Inside `--horizon` | Outside `--horizon` |
| --- | --- | --- |
| `provider` or `token` | `expiring`. The fix is the login command. | `ok` |
| `observed` | `expiring`. The fix is `auth-helper refresh --horizon <duration> <provider>`, because only `refresh` records the new refresh time. | `ok` |
| `unknown` | The status does not change. With `--horizon`, the warning is `lifetime unknown; it may expire during the run`. When lifetimes were observed but no refresh was recorded after the last expiry, it is `last refresh unknown; it may expire during the run`. | |

The rule changes only an `ok` login. On the laptop, Okta stays `manual`: when its observed expiry falls inside the horizon, its warning names the estimated time.

An estimate in the past, for a login that still works, also falls inside the horizon. The login has outlived every observed lifetime, so it can stop at any time.

### Login history

The history file is `~/.local/state/rogue-auth/history.jsonl`, outside every repository. A new directory gets mode `0700`, and a new file gets mode `0600`. Each line is one JSON record:

```json
{"at": "2026-10-19T08:00:00Z", "provider": "gcloud", "event": "refreshed"}
```

- `refreshed`: a `refresh` login command exited 0, and the login works afterwards. A login command records a refresh for each provider that it renews, so a gcloud login records one for `gcloud` and one for `gcloud-adc`.
- `expired_seen`: a check sees the login `expired`, and the last record of that provider is not already `expired_seen`. Later checks record nothing until the next refresh. Only `expired` counts: `missing` and `error` (for example a timeout or the wrong profile) say nothing about the lifetime.
- An observed lifetime runs from a `refreshed` record to the next `expired_seen` record. The file keeps every observation, each with its dates. A check sees an expiry only after it happens, so each observed lifetime can be longer than the real one.
- The estimate exists only while the last record of the provider is `refreshed`. It is that refresh time plus the shortest observed lifetime.

Log in with `auth-helper refresh`. A login made outside it records no refresh time, so the estimate is out of date or missing.

auth-helper only reads the file and appends to it. To remove a wrong observation, for example a revoked token that looked like an expiry, delete its two lines. A malformed line is skipped, and the check goes on; one stderr warning names the number of each skipped line.

Okta has no shell check, so the `/rogue` skill records its Chrome check:

- `auth-helper record okta expired`: the check saw the Okta sign-in page. It records `expired_seen` with the same rule as `check`.
- `auth-helper record okta ok`: the check saw the dashboard. It records `refreshed` only when the last Okta record is `expired_seen`, because only then does it prove a new login. Otherwise it records nothing.
- `auth-helper refresh okta` records nothing, because opening Chrome proves no login.

## Probes

A probe checks real access, not only a login. Probes are non-interactive and open no browser. They send stdout to `/dev/null` and keep only the last error line of stderr, trimmed to 120 characters.

A probe set is a list in the [team config](#configuration). Each entry is one of these:

- `{"name": "<probe name>", "argv": ["<program>", "<argument>", ...]}`: one command. The tool runs the `argv` as a list, without a shell.
- `{"gcp_project": "<project ID>"}`: three reads in that Google Cloud project. They are `gcloud run services list`, `gcloud logging read 'severity>=ERROR'` over the last 10 minutes, and a Cloud Monitoring read of the `run.googleapis.com/request_count` time-series headers over the last 10 minutes. Their names are `cloud-run:<project>`, `logging:<project>`, and `monitoring:<project>`.

Use a read-only, non-interactive command for each probe. A command that opens a browser or prompts blocks the check until its 60-second limit.

The Monitoring read is an HTTP request, so `libexec/monitoring-probe` runs it as one probe command. It uses a token from `gcloud auth print-access-token`. The token stays in the memory of that process and goes only to the Monitoring API. The request refuses redirects, so the token cannot follow one to another host. The token mint has 25 seconds and the read has 30, inside the 60-second limit of each probe.

To add a probe, add an entry to its set in the team config.

## JSON contract

The `/rogue` skill parses this output. Keep it stable.

```json
{
  "checked_at": "2026-10-18T17:30:00Z",
  "providers": [
    {
      "name": "spacelift",
      "status": "expired",
      "account": "acmeholdings",
      "expires_at": "2026-10-18T16:45:00Z",
      "fix": "spacectl profile login --method browser --endpoint https://acmeholdings.app.us.spacelift.io acmeholdings",
      "expires_source": "token",
      "observed_lifetimes": {"count": 0, "shortest_seconds": null},
      "warning": null
    },
    {
      "name": "gcloud",
      "status": "ok",
      "account": "marcus@example.com",
      "expires_at": null,
      "fix": null,
      "expires_source": "unknown",
      "observed_lifetimes": {"count": 0, "shortest_seconds": null},
      "warning": "lifetime unknown; it may expire during the run"
    }
  ],
  "ok": false,
  "probes": [{"name": "cloud-run:acme-platform", "status": "fail", "detail": "ERROR: (gcloud.run.services.list) ..."}]
}
```

- `status` is one of `ok`, `expired`, `expiring`, `missing`, `manual`, or `error`. `account`, `expires_at`, `fix`, and `warning` can be `null`.
- `expires_source` is one of `provider`, `token`, `observed`, or `unknown`. It is `unknown` exactly when `expires_at` is `null`.
- `observed_lifetimes` has `count`, the number of observed lifetimes, and `shortest_seconds`, the shortest one in seconds. `shortest_seconds` is `null` when `count` is 0.
- `warning` is text for a person. No rule depends on its words. It is `null` without `--horizon`.
- Times are RFC 3339 in UTC.
- `fix` is the exact command to run, or the action to take. It is `null` for an `ok` login.
- `probes` is empty without `--probes`. A probe `status` is `ok` or `fail`. `detail` is `null` for `ok`.
- `ok` is false when a required provider is not `ok`, or when any requested probe fails.

## Safety Model

- `auth-helper` never prints, logs, or stores a token. Commands that print a token send stdout to `/dev/null`. The Monitoring token stays in memory, and its request refuses redirects.
- From the Spacelift session token, the tool decodes only the payload, on this machine, and keeps only `exp`. It never sends the token, and it keeps no error text from the decoding.
- The login history holds provider names, event names, and times only.
- On a devbox, the Okta check reads only the session status and times. It never reads a session ID, a token, or a cookie value.
- `check` runs with no terminal input and sets `CLOUDSDK_CORE_DISABLE_PROMPTS=1`, so no command can prompt or open a login page. Each command has a 60-second limit.
- Each CLI runs one process at a time, so parallel gcloud calls do not contend for its credential cache.
- `refresh` is the only command that starts a login. Run it yourself, at the keyboard.

## Configuration

The team's settings are in the team config, a JSON file. The tool reads `$AUTH_HELPER_CONFIG` when it is set, else `$XDG_CONFIG_HOME/auth-helper/team.json`, else `~/.config/auth-helper/team.json`. The private work overlay ships the real file and links it to that path. This repository holds no team values.

```json
{
  "spacelift": {"profile": "acmeholdings", "endpoint": "https://acmeholdings.app.us.spacelift.io"},
  "okta": {"url": "https://login.acme.example"},
  "probe_sets": {
    "team": [
      {"name": "gh-auth", "argv": ["gh", "api", "--hostname", "github.com", "user"]},
      {"gcp_project": "acme-platform-staging"}
    ]
  }
}
```

- Each section is optional. A provider or probe set that needs a missing setting is `not configured`, as [Providers](#providers) and [Probes](#probes) describe. It never passes.
- `spacelift` needs both `profile` and `endpoint`. `endpoint` and `okta.url` must start with `https://`.
- A probe set name holds only letters, digits, `-`, and `_`. A set is a non-empty list.
- Use the REST call `gh api --hostname github.com user` for a GitHub probe, not `gh auth status`. Claude Code cloud sessions block GraphQL, which `auth status` uses, and `--hostname` keeps a stale login on another host from deciding the result.
- A file that exists but is not valid JSON, or a value of the wrong type, stops `check` and `refresh` with exit 2 and one line on stderr. `record` does not read the team config.

`SPACELIFT_CONFIG_DIR` moves the spacectl config directory, as it does for spacectl.

`AUTH_HELPER_VERIFY_BROWSER` replaces the `verify-browser` command, for tests. The default is `config/devbox/verify-browser/verify-browser` in this repository.

`AUTH_HELPER_MONITORING_URL` replaces the Monitoring API base URL, for tests. Only a loopback host is accepted (`127.0.0.1`, `localhost`, or `::1`), so a token never goes to another host.

The history file has a fixed path: `~/.local/state/rogue-auth/history.jsonl`. It keeps the old tool name, so the history did not reset with the rename.

## History

`rogue-auth` first ran its own checks. It then became a thin wrapper over `ro auth` of the ro project (`sucramual/ro`), which it loaded at the commit that `pyproject.toml` pinned, through uv when needed, with the team's settings in a generated `auth.toml`.
`auth-helper` holds ro auth's code at that commit, with the ro loading, the uv re-exec, and the `auth.toml` step removed. Its behaviour, report, exit codes, and login history are the same as the wrapper's, apart from the tool name in printed commands and errors.

The tests in `tests/test_auth_helper.py` compare the output with golden files that the tool recorded before it ran ro (`tests/fixtures/rogue_auth/`).

### Differences from the tool before ro

| Area | Before | Now |
| --- | --- | --- |
| Tool name in printed `refresh` commands and errors | `rogue-auth` | `auth-helper`. `rogue-auth` still runs the same tool. |
| Okta reason line in the table | `the shell cannot see Chrome's Okta session` | `the shell cannot see the browser's Okta session`. The Okta fix still names Google Chrome. |
| Malformed history lines | skipped without a word | skipped, with one stderr warning |
| `--horizon` limit | none | at most `3650d`; a longer one exits 2 |
| Time of the horizon rule | taken before the checks ran | taken after them, so a slow check cannot let an expired login pass |
| Monitoring token | one mint per run, shared by both Monitoring probes, one gcloud call at a time | one mint per Monitoring probe, in its own process, which can run beside other gcloud calls |
| Monitoring time limits | 60 seconds for the mint and 60 for the read | 25 and 30, inside the 60-second probe limit |
| A probe program that cannot run | an uncaught error | the probe fails with `<program> cannot run: <reason>` |
| Team settings | constants in the tool | the [team config](#configuration). Without it, the team's checks are `not configured` and fail. |
