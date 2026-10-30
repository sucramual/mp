"""Black-box tests for tools/auth-helper, and for rogue-auth, its old name, which stays as an alias.

Each test runs the real tool as a subprocess. Fake gh, gcloud, spacectl, signadot, and open
executables sit on a PATH that holds no real provider CLI, so a test can never reach a real login.
A local HTTP server stands in for the Cloud Monitoring API. HOME is a temporary directory, so the
tool reads a fake Spacelift config and writes its login history there, never in the real HOME.
The tool runs with `python -S`, so the interpreter sees no site-packages: it must need only the standard library.

Set AUTH_HELPER_PYTHON (for example /opt/homebrew/bin/python3.13) to pick the interpreter. The default is the
interpreter that runs pytest.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from conftest import REPO_ROOT, IsolatedEnv

TOOL = REPO_ROOT / "tools" / "auth-helper" / "bin" / "auth-helper"
ALIAS = REPO_ROOT / "tools" / "auth-helper" / "bin" / "rogue-auth"
PYTHON = os.environ.get("AUTH_HELPER_PYTHON") or sys.executable
RunTool = Callable[..., subprocess.CompletedProcess[str]]

# Every fake CLI that can mint or show a token prints this value. No test output may contain it.
TOKEN = "ya29.SENTINEL-token-that-must-never-be-printed"
ACCOUNT = "marcus@example.com"
PROVIDERS = {"gh", "gcloud", "gcloud-adc", "spacelift", "signadot", "okta"}
STATUSES = {"ok", "expired", "expiring", "missing", "manual", "error"}
EXPIRES_SOURCES = {"provider", "token", "observed", "unknown"}
UNKNOWN_LIFETIME = "lifetime unknown; it may expire during the run"
RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")

# The fix strings are part of the output contract: they are the team's exact login commands.
GH_FIX = "gh auth login --hostname github.com --web"
GCLOUD_FIX = "gcloud auth login --force --update-adc --quiet"
SPACELIFT_FIX = (
    "spacectl profile login --method browser --endpoint https://acmeholdings.app.us.spacelift.io acmeholdings"
)
SIGNADOT_FIX = "signadot auth login"

TEAM_PROBES = {
    "gh-auth",
    "spacelift-stacks",
    "signadot-sandboxes",
    "gcloud-adc-token",
    "cloud-build:acme-internal",
    "cloud-deploy:acme-internal",
    "cloud-run:acme-platform-staging",
    "logging:acme-platform-staging",
    "monitoring:acme-platform-staging",
    "cloud-run:acme-platform",
    "logging:acme-platform",
    "monitoring:acme-platform",
}

# The team config that every test passes through AUTH_HELPER_CONFIG. The work overlay ships the real one.
# The "team" set lists the same reads, in the same order, as the probe set that was built into the tool.
TEAM_CONFIG = {
    "spacelift": {"profile": "acmeholdings", "endpoint": "https://acmeholdings.app.us.spacelift.io"},
    "okta": {"url": "https://login.acme.example"},
    "probe_sets": {
        "team": [
            {"name": "gh-auth", "argv": ["gh", "api", "--hostname", "github.com", "user"]},
            {"name": "spacelift-stacks", "argv": ["spacectl", "stack", "list", "-o", "json"]},
            {"name": "signadot-sandboxes", "argv": ["signadot", "sandbox", "list"]},
            {"name": "gcloud-adc-token", "argv": ["gcloud", "auth", "application-default", "print-access-token"]},
            {
                "name": "cloud-build:acme-internal",
                "argv": [
                    "gcloud",
                    "builds",
                    "list",
                    "--project",
                    "acme-internal",
                    "--region",
                    "us-east1",
                    "--limit",
                    "1",
                ],
            },
            {
                "name": "cloud-deploy:acme-internal",
                "argv": [
                    *("gcloud", "deploy", "delivery-pipelines", "list", "--project", "acme-internal"),
                    *("--region", "us-east1", "--limit", "1"),
                ],
            },
            {"gcp_project": "acme-platform-staging"},
            {"gcp_project": "acme-platform"},
        ]
    },
}

# Shared start of every fake. It logs the call, reads the fake's mode (default ok), and fails the
# call when a file fail/<name>-<word1>-<word2>[@<project>] exists, with that file's text on stderr.
# A file slow/<selector> makes the call sleep for the seconds it holds first. When the file
# stdin-check exists, the fake records two prompt variables and fails when it can read a line on stdin.
FAKE_PRELUDE = r"""state="@STATE@"
printf '%s\n' "$*" >>"$state/calls-@NAME@.log"
if [[ -e "$state/stdin-check" ]]; then
  printf '%s %s\n' "${CLOUDSDK_CORE_DISABLE_PROMPTS:-unset}" "${GH_PROMPT_DISABLED:-unset}" >>"$state/prompt-env.log"
  if read -r line; then
    echo "stdin was open: $line" >&2
    exit 1
  fi
fi
mode=$(cat "$state/@NAME@.mode" 2>/dev/null || echo ok)
project=""
prev=""
for arg in "$@"; do
  [[ $prev == --project ]] && project=$arg
  prev=$arg
done
selector="@NAME@-$1-$2${project:+@$project}"
if [[ -e "$state/slow/$selector" ]]; then
  sleep "$(cat "$state/slow/$selector")"
fi
if [[ -e "$state/fail/$selector" ]]; then
  cat "$state/fail/$selector" >&2
  exit 1
fi
"""

# gh: `auth status --json hosts` has the shape gh 2.102 prints. In ok mode the entry also carries
# a token field, which real gh adds only with --show-token, to catch a tool that echoes gh's JSON.
# graphql-blocked is the Claude Code cloud case: the egress proxy refuses GraphQL, which `auth status` uses,
# so gh prints state "error" with an empty login, but the REST API (`gh api user`) works.
# graphql-blocked-no-rest is the same, with REST refused too.
# Like gh 2.102, `auth status` without --json exits 1 for a stale login on another host, unless
# --hostname github.com limits it, and for a stale inactive account, unless --active limits it.
FAKE_GH = r"""case "$1 $2" in
  "auth status")
    if [[ " $* " != *" --json "* ]]; then
      if [[ -e "$state/gh.stale-other-host" && " $* " != *" --hostname github.com "* ]]; then
        echo 'ghe.example.com: X Failed to log in to ghe.example.com account octo-old (keyring)' >&2
        exit 1
      fi
      if [[ -e "$state/gh.stale-inactive-account" && " $* " != *" --active "* ]]; then
        echo 'github.com: X Failed to log in to github.com account octo-old (keyring)' >&2
        exit 1
      fi
    fi
    if [[ " $* " == *" --json "* ]]; then
      case "$mode" in
        ok)
          printf '%s' '{"hosts":{"github.com":[{"state":"success","active":true,"host":"github.com",' \
            '"login":"octo-fake","tokenSource":"keyring","token":"@TOKEN@"}]}}'
          echo ;;
        expired)
          printf '%s' '{"hosts":{"github.com":[{"state":"error","active":true,"host":"github.com",' \
            '"login":"octo-fake","tokenSource":"keyring","error":"The token in keyring is invalid."}]}}'
          echo ;;
        graphql-blocked | graphql-blocked-no-rest)
          printf '%s' '{"hosts":{"github.com":[{"state":"error","active":true,"host":"github.com",' \
            '"login":"","tokenSource":"GH_TOKEN",' \
            '"error":"non-200 OK status code: 403 Forbidden body: \"{\\\"message\\\":\\\"' \
            'GitHub GraphQL is not available from Claude Code sessions; use the REST API instead' \
            '\\\"}\""}]}}'
          echo ;;
        missing)
          echo 'You are not logged into any GitHub hosts. To log in, run: gh auth login' >&2
          printf '{"hosts":{}}\n' ;;
      esac
      exit 0
    fi
    if [[ $mode == ok ]]; then
      echo 'github.com: Logged in to github.com account octo-fake (keyring)'
      exit 0
    fi
    echo 'github.com: X Failed to log in to github.com account octo-fake (keyring)' >&2
    exit 1 ;;
  "api --hostname")
    case "$mode" in
      ok) echo octo-fake; exit 0 ;;
      graphql-blocked) echo sucramual; exit 0 ;;
    esac
    echo 'gh: Bad credentials (HTTP 401)' >&2
    exit 1 ;;
  "auth login")
    echo ok >"$state/gh.mode"
    exit 0 ;;
esac
echo "fake gh: unexpected command: $*" >&2
exit 2
"""

# gcloud: the reauthentication error is the text gcloud 560 prints on this machine.
FAKE_GCLOUD = r"""reauth() {
  local reason='There was a problem refreshing your current auth tokens: '
  reason+='Reauthentication failed. cannot prompt during non-interactive execution.'
  printf '%s\n' "ERROR: (gcloud.$1) $reason" \
    'Please run:' '' '  $ gcloud auth login' '' 'to obtain new credentials.' >&2
  exit 1
}
case "$1 $2" in
  "config get-value")
    [[ $mode == missing ]] || echo "@ACCOUNT@"
    exit 0 ;;
  "auth print-access-token")
    [[ $mode == ok ]] || reauth auth.print-access-token
    echo "@TOKEN@"
    exit 0 ;;
  "auth application-default")
    adc=$(cat "$state/gcloud-adc.mode" 2>/dev/null || echo "$mode")
    if [[ $adc == missing ]]; then
      echo 'ERROR: (gcloud.auth.application-default.print-access-token) Your default credentials were not found.' >&2
      exit 1
    fi
    [[ $adc == ok ]] || reauth auth.application-default.print-access-token
    echo "@TOKEN@"
    exit 0 ;;
  "auth login")
    echo ok >"$state/gcloud.mode"
    echo ok >"$state/gcloud-adc.mode"
    exit 0 ;;
  "run services" | "logging read" | "builds list" | "deploy delivery-pipelines")
    [[ $mode == ok ]] || reauth "$1"
    echo 'LISTED-ROW that the tool must not echo'
    exit 0 ;;
esac
echo "fake gcloud: unexpected command: $*" >&2
exit 2
"""

# spacectl: the whoami failure is the text spacectl 1.26.0 prints on this machine. Like spacectl
# 1.26.0, `profile login <alias>` creates the profile and makes it the current one.
FAKE_SPACECTL = r"""unauthorized() {
  echo '2026/10/18 10:19:37 failed to query user information: unauthorized' >&2
  exit 1
}
case "$1 $2" in
  "profile current")
    cat "$state/spacectl.profile" 2>/dev/null || echo acmeholdings
    exit 0 ;;
  "whoami "*)
    [[ $mode == ok ]] || unauthorized
    echo '{"id":"fake-user","name":"Fake User"}'
    exit 0 ;;
  "stack list")
    [[ $mode == ok ]] || unauthorized
    echo '[]'
    exit 0 ;;
  "profile login")
    echo ok >"$state/spacectl.mode"
    echo "${@: -1}" >"$state/spacectl.profile"
    exit 0 ;;
esac
echo "fake spacectl: unexpected command: $*" >&2
exit 2
"""

# signadot: `auth status -o json` has the shape signadot 1.9.0 prints, including its bearerToken.
# A login renews the expiry: to signadot.expires-after-login when that file exists, else far ahead.
FAKE_SIGNADOT = r"""case "$1 $2" in
  "sandbox list")
    if [[ $mode != ok ]]; then
      echo "Error: Authentication expired. Please log in using 'signadot auth login'" >&2
      exit 1
    fi
    echo 'NAME   CLUSTER   STATUS'
    exit 0 ;;
  "auth status")
    expires=$(cat "$state/signadot.expires" 2>/dev/null || echo 2099-01-01T00:00:00.000000-07:00)
    printf '{"bearerToken":"@TOKEN@","orgName":"fake-org","expiresAt":"%s","source":"keyring"}\n' "$expires"
    exit 0 ;;
  "auth login")
    echo ok >"$state/signadot.mode"
    renewed=$(cat "$state/signadot.expires-after-login" 2>/dev/null || echo 2099-01-01T00:00:00.000000-07:00)
    echo "$renewed" >"$state/signadot.expires"
    exit 0 ;;
esac
echo "fake signadot: unexpected command: $*" >&2
exit 2
"""

FAKE_OPEN = "exit 0\n"

# verify-browser: `status --json` prints state/verify-browser.json, else a signed-in report with the shape that
# config/devbox/verify-browser/verify-browser prints. It exits 0 only for an ACTIVE session, like the real one.
VERIFY_BROWSER_ACTIVE = {
    "chrome": {"answers": True, "browser": "Chrome/156.0.8078.80"},
    "okta": {
        "checked_at": "2026-10-30T09:00:00Z",
        "http_status": 200,
        "status": "ACTIVE",
        "createdAt": "2026-10-30T08:00:00.000Z",
        "lastPasswordVerification": "2026-10-30T08:00:00.000Z",
        "lastFactorVerification": "2026-10-30T08:00:05.000Z",
        "expiresAt": "2026-10-30T11:00:00.000Z",
        "error": None,
    },
}
FAKE_VERIFY_BROWSER = r"""case "$1 $2" in
  "status --json")
    printf '%s\n' "${VERIFY_BROWSER_OKTA_URL:-unset}" >>"$state/verify-browser-okta-url.log"
    if [[ -e "$state/verify-browser.json" ]]; then
      cat "$state/verify-browser.json"
      grep -q '"ACTIVE"' "$state/verify-browser.json" || exit 1
    else
      cat <<'JSON'
@ACTIVE@
JSON
    fi
    exit 0 ;;
esac
echo "fake verify-browser: unexpected command: $*" >&2
exit 2
""".replace("@ACTIVE@", json.dumps(VERIFY_BROWSER_ACTIVE))

FAKES = {
    "gh": FAKE_GH,
    "gcloud": FAKE_GCLOUD,
    "spacectl": FAKE_SPACECTL,
    "signadot": FAKE_SIGNADOT,
    "open": FAKE_OPEN,
    "verify-browser": FAKE_VERIFY_BROWSER,
}


@dataclass
class Fakes:
    """The fake CLIs and their shared state directory."""

    bin: Path
    state: Path
    write: Callable[..., Path]

    def mode(self, name: str, mode: str) -> None:
        """Set a fake's mode: ok, expired, or missing."""
        (self.state / f"{name}.mode").write_text(f"{mode}\n")

    def fail(self, selector: str, stderr: str) -> None:
        """Make the calls that match the selector exit 1 with this stderr."""
        (self.state / "fail").mkdir(exist_ok=True)
        (self.state / "fail" / selector).write_text(stderr)

    def slow(self, selector: str, seconds: int) -> None:
        """Make the calls that match the selector sleep this many seconds first."""
        (self.state / "slow").mkdir(exist_ok=True)
        (self.state / "slow" / selector).write_text(f"{seconds}\n")

    def remove(self, name: str) -> None:
        """Take a CLI off PATH, as if it were not installed."""
        (self.bin / name).unlink()

    def verify_browser(self, report: dict[str, object]) -> None:
        """Set the report that the fake `verify-browser status --json` prints."""
        (self.state / "verify-browser.json").write_text(json.dumps(report))

    def calls(self, name: str) -> list[str]:
        """The argument lines a fake received, one per call."""
        log = self.state / f"calls-{name}.log"
        return log.read_text().splitlines() if log.exists() else []


@dataclass
class Monitoring:
    """A local stand-in for the Cloud Monitoring API.

    For a project in redirect_by_project it answers 302 to that URL. For a project in
    truncate_by_project it declares a longer body than it sends, then closes the connection.
    """

    url: str
    status_by_project: dict[str, int] = field(default_factory=dict)
    redirect_by_project: dict[str, str] = field(default_factory=dict)
    truncate_by_project: set[str] = field(default_factory=set)
    requests: list[dict[str, object]] = field(default_factory=list)


@pytest.fixture
def fakes(isolated_env: IsolatedEnv, fake_exe: Callable[..., Path]) -> Fakes:
    state = isolated_env.root / "state"
    state.mkdir()
    for name, body in FAKES.items():
        script = FAKE_PRELUDE + body
        for placeholder, value in (
            ("@STATE@", str(state)),
            ("@NAME@", name),
            ("@TOKEN@", TOKEN),
            ("@ACCOUNT@", ACCOUNT),
        ):
            script = script.replace(placeholder, value)
        fake_exe(name, script)
    return Fakes(bin=isolated_env.bin, state=state, write=fake_exe)


@contextmanager
def serve_monitoring() -> Iterator[Monitoring]:
    server_state = Monitoring(url="")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parts = urlsplit(self.path)
            match = re.fullmatch(r"/v3/projects/([^/]+)/timeSeries", parts.path)
            project = match.group(1) if match else ""
            server_state.requests.append(
                {
                    "project": project,
                    "query": parse_qs(parts.query),
                    "authorization": self.headers.get("Authorization"),
                }
            )
            if project in server_state.redirect_by_project:
                self.send_response(302)
                self.send_header("Location", server_state.redirect_by_project[project])
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if project in server_state.truncate_by_project:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "100")
                self.end_headers()
                self.wfile.write(b"{}")
                self.close_connection = True
                return
            status = server_state.status_by_project.get(project, 200) if match else 404
            if status == 200:
                body = b"{}"
            else:
                body = json.dumps(
                    {"error": {"code": status, "message": "Permission monitoring.timeSeries.list denied"}}
                ).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - BaseHTTPRequestHandler's name
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_state.url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server_state
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def monitoring() -> Iterator[Monitoring]:
    with serve_monitoring() as server_state:
        yield server_state


@pytest.fixture
def elsewhere() -> Iterator[Monitoring]:
    """Another host. A token-bearing request must never reach it."""
    with serve_monitoring() as server_state:
        yield server_state


def team_config_path(isolated_env: IsolatedEnv) -> Path:
    """Where the run fixture writes TEAM_CONFIG: outside HOME, so the default config path stays empty."""
    return isolated_env.root / "team.json"


@pytest.fixture
def run(isolated_env: IsolatedEnv, fakes: Fakes, monitoring: Monitoring, run_tool: RunTool) -> RunTool:
    """Run auth-helper with `python -S`, and with only the fakes, bash, cat, grep, and sleep on PATH.

    The host is not a devbox: the devbox marker does not exist. A test sets DOTFILES_DEVBOX=1 to make it one.
    auth-helper reaches the fake verify-browser through AUTH_HELPER_VERIFY_BROWSER, never a real browser.
    It reads the team config TEAM_CONFIG from team_config_path(). A test passes AUTH_HELPER_CONFIG to use another.
    """
    team_config = team_config_path(isolated_env)
    team_config.write_text(json.dumps(TEAM_CONFIG))
    system_bin = isolated_env.root / "system-bin"
    system_bin.mkdir()
    for name in ("bash", "cat", "grep", "sleep"):
        found = next((Path(d) / name for d in ("/bin", "/usr/bin") if (Path(d) / name).exists()), None)
        assert found, f"{name} must exist in /bin or /usr/bin to run these tests"
        (system_bin / name).symlink_to(found)

    def go(*args: str, stdin: str | None = None, **extra_env: str) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": f"{fakes.bin}{os.pathsep}{system_bin}",
            "AUTH_HELPER_CONFIG": str(team_config),
            "AUTH_HELPER_MONITORING_URL": monitoring.url,
            "AUTH_HELPER_VERIFY_BROWSER": str(fakes.bin / "verify-browser"),
            "DOTFILES_DEVBOX_MARKER": str(isolated_env.root / "no-devbox"),
            **extra_env,
        }
        return run_tool([PYTHON, "-S", TOOL, *args], cwd=isolated_env.root, input=stdin, **env)

    return go


def report(result: subprocess.CompletedProcess[str]) -> dict:
    """Parse the --json report. Fails the test with the tool's output when stdout is not JSON."""
    try:
        return json.loads(result.stdout)
    except ValueError:
        pytest.fail(
            f"stdout is not JSON (exit {result.returncode})\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def provider(data: dict, name: str) -> dict:
    entries = [entry for entry in data["providers"] if entry["name"] == name]
    assert len(entries) == 1, f"expected one {name} entry: {data['providers']}"
    return entries[0]


def probe(data: dict, name: str) -> dict:
    entries = [entry for entry in data["probes"] if entry["name"] == name]
    assert len(entries) == 1, f"expected one {name} probe: {data['probes']}"
    return entries[0]


def rfc3339(moment: datetime) -> str:
    """Format like signadot does: microseconds and a -07:00 offset."""
    return moment.astimezone(timezone(timedelta(hours=-7))).isoformat(timespec="microseconds")


def zulu(moment: datetime) -> str:
    """Format like auth-helper does: whole seconds in UTC, with a Z."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_zulu(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def now_seconds() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def history_file(isolated_env: IsolatedEnv) -> Path:
    """The history file that rogue-auth kept. auth-helper keeps using it, so no history resets."""
    return isolated_env.home / ".local" / "state" / "rogue-auth" / "history.jsonl"


def history(isolated_env: IsolatedEnv) -> list[dict]:
    """Every record of the history file, parsed. An absent file has no records."""
    path = history_file(isolated_env)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def events(isolated_env: IsolatedEnv, name: str) -> list[tuple[str, datetime]]:
    """The (event, time) records of one provider, in file order."""
    return [(entry["event"], parse_zulu(entry["at"])) for entry in history(isolated_env) if entry["provider"] == name]


def seed_history(isolated_env: IsolatedEnv, *entries: tuple[str, str, datetime]) -> None:
    """Append (provider, event, time) records to the history file, in its documented JSON Lines format."""
    path = history_file(isolated_env)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        for name, event, moment in entries:
            handle.write(json.dumps({"at": zulu(moment), "provider": name, "event": event}) + "\n")


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def jwt(payload: dict, *, header: dict | None = None, signature: str = "c2lnbmF0dXJl") -> str:
    head = header or {"alg": "HS256", "typ": "JWT"}
    return ".".join([b64url(json.dumps(head).encode()), b64url(json.dumps(payload).encode()), signature])


def write_spacelift_config(directory: Path, profiles: dict[str, object], current: str = "acmeholdings") -> None:
    """Write a spacectl 1.26.0 config.json. A str profile value is the token; any other value is the credentials."""
    directory.mkdir(parents=True, exist_ok=True)
    entries = {
        alias: {
            "alias": alias,
            "credentials": (
                {"type": 3, "endpoint": f"https://{alias}.app.us.spacelift.io", "access_token": value}
                if isinstance(value, str)
                else value
            ),
        }
        for alias, value in profiles.items()
    }
    (directory / "config.json").write_text(json.dumps({"currentProfileAlias": current, "profiles": entries}))


ALL_LOGINS = "gh,gcloud,gcloud-adc,spacelift,signadot"


# Protects: every working login reads as ok, with its account, and the run exits 0.
# Bug caught: a check that treats any stderr text, or gcloud's (unset) noise, as failure.
def test_all_ok_reports_each_login_and_exits_zero(run: RunTool):
    result = run("check", "--json", "--require", ALL_LOGINS)

    data = report(result)
    assert result.returncode == 0, result.stderr
    assert data["ok"] is True
    assert {entry["name"]: entry["status"] for entry in data["providers"]} == {
        "gh": "ok",
        "gcloud": "ok",
        "gcloud-adc": "ok",
        "spacelift": "ok",
        "signadot": "ok",
        "okta": "manual",
    }
    assert provider(data, "gh")["account"] == "octo-fake"
    assert provider(data, "gcloud")["account"] == ACCOUNT
    assert provider(data, "spacelift")["account"] == "acmeholdings"
    assert provider(data, "signadot")["account"] == "fake-org"
    assert all(provider(data, name)["fix"] is None for name in ("gh", "gcloud", "spacelift", "signadot"))


# Protects: a required login that the provider rejects fails the run and names the exact fix.
# Bug caught: ok computed from the wrong set, or an expired login reported without its fix.
def test_required_provider_that_is_expired_fails_with_its_fix(run: RunTool, fakes: Fakes):
    fakes.mode("spacectl", "expired")

    result = run("check", "--json", "--require", "gh,spacelift")

    data = report(result)
    assert result.returncode == 1, result.stderr
    assert data["ok"] is False
    spacelift = provider(data, "spacelift")
    assert spacelift["status"] == "expired"
    assert spacelift["fix"] == SPACELIFT_FIX
    assert provider(data, "gh")["status"] == "ok"


# Protects: without --require, only gh decides ok, but every provider is still reported.
# Bug caught: the default run fails on an unrelated provider, or ignores a broken gh.
def test_default_check_requires_only_gh(run: RunTool, fakes: Fakes):
    fakes.mode("gcloud", "expired")

    passing = run("check", "--json")

    data = report(passing)
    assert passing.returncode == 0, passing.stderr
    assert data["ok"] is True
    assert {entry["name"] for entry in data["providers"]} == PROVIDERS
    gcloud = provider(data, "gcloud")
    assert gcloud["status"] == "expired"
    assert gcloud["fix"] == GCLOUD_FIX

    fakes.mode("gh", "expired")
    failing = run("check", "--json")

    data = report(failing)
    assert failing.returncode == 1, failing.stderr
    assert data["ok"] is False
    gh = provider(data, "gh")
    assert gh["status"] == "expired"
    assert gh["fix"] == GH_FIX


# Protects: a CLI that is not installed reads as missing, with an install hint, instead of a crash.
# Bug caught: FileNotFoundError escapes as a traceback, so the /rogue skill gets no JSON at all.
def test_missing_clis_are_reported_missing(run: RunTool, fakes: Fakes):
    for name in ("gcloud", "spacectl", "signadot"):
        fakes.remove(name)

    result = run("check", "--json")

    data = report(result)
    assert result.returncode == 0, result.stderr
    for name, login in (("gcloud", GCLOUD_FIX), ("gcloud-adc", GCLOUD_FIX), ("spacelift", SPACELIFT_FIX)):
        entry = provider(data, name)
        assert entry["status"] == "missing", entry
        assert entry["fix"] is not None and login in entry["fix"], entry
    assert provider(data, "signadot")["status"] == "missing"


# Protects: Okta is never reported ok, because the shell cannot see Chrome's session.
# Bug caught: okta reported ok, or manual counted as ok when the run requires okta.
def test_okta_is_manual_even_when_required(run: RunTool):
    result = run("check", "--json", "--require", f"{ALL_LOGINS},okta")

    data = report(result)
    okta = provider(data, "okta")
    assert okta["status"] == "manual"
    assert okta["fix"] is not None and "Chrome" in okta["fix"]
    assert data["ok"] is False
    assert result.returncode == 1


# Protects: off a devbox, Okta stays manual and auth-helper does not ask verify-browser, even when it would say ok.
# Bug caught: the devbox check runs on the laptop, where no verify-browser Chrome holds the Okta session.
def test_okta_off_a_devbox_stays_manual_and_skips_verify_browser(run: RunTool, fakes: Fakes):
    result = run("check", "--json", "--require", f"{ALL_LOGINS},okta")

    okta = provider(report(result), "okta")
    assert okta["status"] == "manual"
    assert fakes.calls("verify-browser") == []
    assert result.returncode == 1


# Protects: on a devbox, an ACTIVE Okta session in the verify-browser Chrome makes okta ok, so a run that
# requires okta can start. Okta's expiresAt is only the 2-hour idle expiry, so it is not the session's expiry:
# the unknown-lifetime warning stays.
# Bug caught: okta stays manual on the devbox; or expiresAt is taken as the expiry, so --horizon 8h marks a
# kept-alive session expiring.
def test_okta_on_a_devbox_is_ok_when_verify_browser_sees_an_active_session(run: RunTool, fakes: Fakes):
    result = run("check", "--json", "--require", f"{ALL_LOGINS},okta", "--horizon", "8h", DOTFILES_DEVBOX="1")

    data = report(result)
    okta = provider(data, "okta")
    assert okta["status"] == "ok", okta
    assert okta["fix"] is None
    assert okta["expires_at"] is None, "Okta's expiresAt is the idle expiry, not the session's absolute limit"
    assert okta["warning"] == UNKNOWN_LIFETIME
    assert fakes.calls("verify-browser") == ["status --json"]
    assert data["ok"] is True
    assert result.returncode == 0, result.stdout + result.stderr


# Protects: on a devbox, a signed-out Okta session reads expired, fails a run that requires it, and names the
# noVNC sign-in step as its fix.
# Bug caught: a non-ACTIVE session counts as ok, or the fix still says to open Chrome on the laptop.
@pytest.mark.parametrize(
    "okta_report",
    [
        {"http_status": 404, "status": None, "error": "Okta answered HTTP 404"},
        {"http_status": 200, "status": "MFA_REQUIRED", "error": None},
    ],
)
def test_okta_on_a_devbox_is_expired_with_the_novnc_fix(run: RunTool, fakes: Fakes, okta_report: dict):
    fakes.verify_browser({"chrome": {"answers": True, "browser": "Chrome/156"}, "okta": okta_report})

    result = run("check", "--json", "--require", f"{ALL_LOGINS},okta", DOTFILES_DEVBOX="1")

    data = report(result)
    okta = provider(data, "okta")
    assert okta["status"] == "expired", okta
    assert okta["fix"] is not None and "vnc.html" in okta["fix"], okta
    assert data["ok"] is False
    assert result.returncode == 1


# Protects: on a devbox where the verify-browser Chrome does not answer, or the Okta read itself fails, okta is an
# error whose fix restarts verify-browser.
# Bug caught: a stopped Chrome or a timed-out read counts as a signed-out session, so Marcus signs in to a browser
# that is not running, or a run starts on a session that nobody checked.
@pytest.mark.parametrize(
    "status_report",
    [
        {"chrome": {"answers": False, "error": "connect ECONNREFUSED 127.0.0.1:9222"}, "okta": None},
        {"chrome": {"answers": True, "browser": "Chrome/156"}, "okta": None, "error": "timed out after 45s"},
        {
            "chrome": {"answers": True, "browser": "Chrome/156"},
            "okta": {"http_status": None, "status": None, "error": "no Okta URL: set VERIFY_BROWSER_OKTA_URL"},
        },
    ],
)
def test_okta_on_a_devbox_without_a_working_check_is_an_error(run: RunTool, fakes: Fakes, status_report: dict):
    fakes.verify_browser(status_report)

    result = run("check", "--json", "--require", f"{ALL_LOGINS},okta", DOTFILES_DEVBOX="1")

    okta = provider(report(result), "okta")
    assert okta["status"] == "error", okta
    assert okta["fix"] is not None and "verify-browser start" in okta["fix"], okta
    assert result.returncode == 1


# Protects: auth-helper gives verify-browser its own Okta URL, so the devbox check needs no okta-url config file.
# Bug caught: the URL is not passed, so every devbox check reports a missing Okta URL.
def test_okta_on_a_devbox_passes_the_team_okta_url_to_verify_browser(run: RunTool, fakes: Fakes):
    run("check", "--json", DOTFILES_DEVBOX="1")

    log = fakes.state / "verify-browser-okta-url.log"
    assert log.read_text().splitlines() == ["https://login.acme.example"]


# Protects: on a devbox, `refresh okta` opens no laptop browser; it prints the noVNC sign-in step and checks again.
# Bug caught: refresh runs macOS `open -a "Google Chrome"` on Linux and reports a failed login command.
def test_refresh_okta_on_a_devbox_names_the_novnc_step(run: RunTool, fakes: Fakes):
    fakes.verify_browser({"chrome": {"answers": True, "browser": "Chrome/156"}, "okta": {"http_status": 401}})

    result = run("refresh", "okta", DOTFILES_DEVBOX="1")

    assert fakes.calls("open") == []
    assert re.search(r"^okta: expired\b.*vnc\.html", result.stdout, re.MULTILINE), result.stdout
    assert result.returncode == 1


# Protects: spacelift is ok only for the team's profile, and its fix logs in to and selects that profile.
# Bug caught: another selected profile, such as the near-duplicate "acmeholding" on this machine,
# reads as ok because spacectl whoami works for it.
def test_spacelift_requires_the_team_profile(run: RunTool, fakes: Fakes):
    (fakes.state / "spacectl.profile").write_text("acmeholding\n")

    result = run("check", "--json", "--require", "gh,spacelift")

    data = report(result)
    assert result.returncode == 1, result.stderr
    assert data["ok"] is False
    spacelift = provider(data, "spacelift")
    assert spacelift["status"] == "error"
    assert spacelift["account"] == "acmeholding"
    assert spacelift["fix"] == SPACELIFT_FIX

    refreshed = run("refresh", "spacelift")

    assert refreshed.returncode == 0, refreshed.stdout + refreshed.stderr
    assert re.search(r"^spacelift: ok \(acmeholdings\)", refreshed.stdout, re.MULTILINE), refreshed.stdout


# Protects: a SPACELIFT_API_* variable makes spacelift an error whose fix unsets it, and its value is never printed.
# Bug caught: spacectl uses the environment credential before the selected profile (verified with spacectl
# 1.26.0), so profile current names the team profile while whoami succeeds for another identity.
@pytest.mark.parametrize("variable", ["SPACELIFT_API_TOKEN", "SPACELIFT_API_KEY_SECRET"])
def test_spacelift_api_variables_make_spacelift_an_error(run: RunTool, variable: str):
    secret = "spacelift-env-secret-that-must-never-be-printed"

    as_json = run("check", "--json", "--require", "gh,spacelift", **{variable: secret})
    as_table = run("check", "--require", "gh,spacelift", **{variable: secret})

    data = report(as_json)
    assert as_json.returncode == 1, as_json.stderr
    assert data["ok"] is False
    spacelift = provider(data, "spacelift")
    assert spacelift["status"] == "error"
    assert spacelift["fix"] == f"unset {variable}"
    assert provider(data, "gh")["status"] == "ok"
    assert as_table.returncode == 1
    assert re.search(rf"^\s+spacelift: unset {variable}$", as_table.stdout, re.MULTILINE), as_table.stdout
    for result in (as_json, as_table):
        assert secret not in result.stdout + result.stderr


# Protects: a known expiry inside --horizon marks the login expiring, which fails a required check.
# Bug caught: --horizon ignored, or the comparison runs the wrong way.
def test_horizon_marks_known_expiry_as_expiring(run: RunTool, fakes: Fakes):
    expires = datetime.now(UTC) + timedelta(hours=2)
    (fakes.state / "signadot.expires").write_text(rfc3339(expires))

    long_run = run("check", "--json", "--require", "signadot", "--horizon", "8h")

    data = report(long_run)
    signadot = provider(data, "signadot")
    assert signadot["status"] == "expiring"
    assert signadot["fix"] == SIGNADOT_FIX
    parsed = datetime.fromisoformat(signadot["expires_at"].replace("Z", "+00:00"))
    assert abs((parsed - expires).total_seconds()) < 1
    assert data["ok"] is False
    assert long_run.returncode == 1

    short_run = run("check", "--json", "--require", "signadot", "--horizon", "1h")

    data = report(short_run)
    assert provider(data, "signadot")["status"] == "ok"
    assert data["ok"] is True
    assert short_run.returncode == 0


FAR_FUTURE = "2099-01-01T00:00:00Z"


# Protects: the provider expiry accepts an RFC3339 time with Z or an offset and any fraction length,
# and reports it as whole seconds in UTC. A fraction past 6 digits is cut off, never rounded up.
# Bug caught: a "Z" suffix or a fraction length of 1 or 7+ digits is rejected, so the expiry shows as
# unknown; or a long fraction is rounded, so .9999999 moves the reported time one second later.
@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("2099-01-01T00:00:00Z", id="z-no-fraction"),
        pytest.param("2099-01-01T00:00:00.5Z", id="z-1-digit"),
        pytest.param("2099-01-01T00:00:00.123Z", id="z-3-digits"),
        pytest.param("2099-01-01T00:00:00.9999999Z", id="z-7-digits-truncated"),
        pytest.param("2099-01-01T00:00:00.999999999+00:00", id="utc-offset-9-digits"),
        pytest.param("2098-12-31T17:00:00.000000-07:00", id="signadot-offset-6-digits"),
        pytest.param("2099-01-01T05:30:00.1234567+05:30", id="east-offset-7-digits"),
        pytest.param(" 2099-01-01T00:00:00Z ", id="surrounding-spaces"),
    ],
)
def test_provider_expiry_reads_rfc3339_with_any_fraction_length(run: RunTool, fakes: Fakes, raw: str):
    (fakes.state / "signadot.expires").write_text(raw)

    result = run("check", "--json", "--require", "signadot", "--horizon", "8h")

    signadot = provider(report(result), "signadot")
    assert result.returncode == 0, result.stderr
    assert signadot["status"] == "ok"
    assert signadot["expires_at"] == FAR_FUTURE
    assert signadot["expires_source"] == "provider"
    assert signadot["warning"] is None


# Protects: a provider expiry that is not a full RFC3339 time with a Z or an offset is unknown, not a guess.
# Bug caught: a time with no offset is read as the local time zone, so the expiry moves by the local offset;
# or a time in another ISO 8601 form, or an impossible date, is accepted or crashes the check.
@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("2099-01-01T00:00:00", id="no-offset"),
        pytest.param("2099-01-01T00:00:00.123456", id="no-offset-fraction"),
        pytest.param("2099-01-01 00:00:00Z", id="space-separator"),
        pytest.param("20990101T000000Z", id="basic-format"),
        pytest.param("2099-01-01T00:00:00+0000", id="offset-without-colon"),
        pytest.param("2099-01-01", id="date-only"),
        pytest.param("2099-13-01T00:00:00Z", id="impossible-month"),
    ],
)
def test_provider_expiry_that_is_not_full_rfc3339_is_unknown(run: RunTool, fakes: Fakes, raw: str):
    (fakes.state / "signadot.expires").write_text(raw)

    result = run("check", "--json", "--require", "signadot", "--horizon", "8h")

    signadot = provider(report(result), "signadot")
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert signadot["status"] == "ok"
    assert signadot["expires_at"] is None
    assert signadot["expires_source"] == "unknown"
    assert signadot["warning"] == UNKNOWN_LIFETIME


# Protects: the JSON shape that the /rogue skill parses.
# Bug caught: a renamed, dropped, or retyped field, or a non-RFC3339 time.
def test_json_output_matches_the_contract(run: RunTool, fakes: Fakes):
    fakes.mode("spacectl", "expired")
    (fakes.state / "signadot.expires").write_text(rfc3339(datetime.now(UTC) + timedelta(days=3)))

    result = run("check", "--json", "--probes", "team")

    data = report(result)
    assert set(data) == {"checked_at", "providers", "ok", "probes"}
    assert RFC3339.match(data["checked_at"]), data["checked_at"]
    assert isinstance(data["ok"], bool)
    assert [entry["name"] for entry in data["providers"]].count("gh") == 1
    assert {entry["name"] for entry in data["providers"]} == PROVIDERS
    for entry in data["providers"]:
        assert set(entry) == {
            "name",
            "status",
            "account",
            "expires_at",
            "fix",
            "expires_source",
            "observed_lifetimes",
            "warning",
        }, entry
        assert entry["status"] in STATUSES, entry
        assert entry["account"] is None or isinstance(entry["account"], str), entry
        assert entry["expires_at"] is None or RFC3339.match(entry["expires_at"]), entry
        assert entry["fix"] is None or isinstance(entry["fix"], str), entry
        assert entry["expires_source"] in EXPIRES_SOURCES, entry
        assert (entry["expires_source"] == "unknown") == (entry["expires_at"] is None), entry
        lifetimes = entry["observed_lifetimes"]
        assert set(lifetimes) == {"count", "shortest_seconds"}, entry
        assert isinstance(lifetimes["count"], int), entry
        assert (lifetimes["shortest_seconds"] is None) == (lifetimes["count"] == 0), entry
        assert entry["warning"] is None or isinstance(entry["warning"], str), entry
    signadot = provider(data, "signadot")
    assert signadot["expires_at"] is not None
    assert signadot["expires_source"] == "provider"
    assert {entry["name"] for entry in data["probes"]} == TEAM_PROBES
    for entry in data["probes"]:
        assert set(entry) == {"name", "status", "detail"}, entry
        assert entry["status"] in {"ok", "fail"}, entry
        assert entry["detail"] is None or isinstance(entry["detail"], str), entry


# Protects: a mistyped provider, probe set, or horizon stops the run before any check runs.
# Bug caught: `--require spacelfit` is ignored, so a broken Spacelift login passes preflight.
@pytest.mark.parametrize(
    ("args", "named"),
    [
        (("--require", "gh,spacelfit"), "spacelfit"),
        (("--probes", "multiplyer"), "multiplyer"),
        (("--horizon", "8 hours"), "8 hours"),
    ],
)
def test_unknown_names_are_refused_before_any_check(run: RunTool, fakes: Fakes, args: tuple[str, ...], named: str):
    result = run("check", "--json", *args)

    assert result.returncode == 2, result.stdout
    assert named in result.stderr
    assert result.stdout == ""
    assert all(fakes.calls(name) == [] for name in ("gh", "gcloud", "spacectl", "signadot"))


# Protects: with every login and permission in place, every probe of the set passes and the run is ok.
# Bug caught: a probe that reads a CLI's normal output as failure, or a malformed Monitoring request.
def test_probes_all_pass(run: RunTool, monitoring: Monitoring):
    result = run("check", "--json", "--probes", "team")

    data = report(result)
    assert result.returncode == 0, result.stderr
    assert data["ok"] is True
    assert {entry["name"]: entry["status"] for entry in data["probes"]} == dict.fromkeys(TEAM_PROBES, "ok")
    assert sorted(str(request["project"]) for request in monitoring.requests) == [
        "acme-platform",
        "acme-platform-staging",
    ]
    for request in monitoring.requests:
        query = request["query"]
        assert isinstance(query, dict)
        assert query["filter"] == ['metric.type="run.googleapis.com/request_count"']
        assert query["view"] == ["HEADERS"]
        assert query["pageSize"] == ["1"]
        start = datetime.fromisoformat(query["interval.startTime"][0].replace("Z", "+00:00"))
        end = datetime.fromisoformat(query["interval.endTime"][0].replace("Z", "+00:00"))
        assert end - start == timedelta(minutes=10)


# Protects: a failed probe fails the run, even when no login is required, and says why in one line.
# Bug caught: probe failures left out of ok, or a detail that is gcloud's last, unhelpful line.
def test_failed_probes_fail_the_check_with_their_last_error_line(run: RunTool, fakes: Fakes, monitoring: Monitoring):
    denied = (
        "ERROR: (gcloud.run.services.list) PERMISSION_DENIED: Permission 'run.services.list' denied on resource "
        "'projects/acme-platform/locations/-/services' (or it may not exist). This command is authenticated "
        "as marcus@example.com."
    )
    fakes.fail("gcloud-run-services@acme-platform", f"WARNING: retrying\n{denied}\nTo fix, ask for roles/run.viewer\n")
    monitoring.status_by_project["acme-platform-staging"] = 403

    result = run("check", "--json", "--probes", "team")

    data = report(result)
    assert result.returncode == 1, result.stderr
    assert data["ok"] is False
    assert provider(data, "gh")["status"] == "ok"
    cloud_run = probe(data, "cloud-run:acme-platform")
    assert cloud_run["status"] == "fail"
    assert cloud_run["detail"].startswith("ERROR: (gcloud.run.services.list) PERMISSION_DENIED")
    assert len(cloud_run["detail"]) <= 120
    staging = probe(data, "monitoring:acme-platform-staging")
    assert staging["status"] == "fail"
    assert "403" in staging["detail"]
    assert "Permission monitoring.timeSeries.list denied" in staging["detail"]
    passing = {entry["name"] for entry in data["probes"] if entry["status"] == "ok"}
    assert passing == TEAM_PROBES - {"cloud-run:acme-platform", "monitoring:acme-platform-staging"}


# Protects: an expired gcloud login fails the Monitoring probes with gcloud's reason, before any request.
# Bug caught: an empty or failed token mint sent as "Bearer " and reported as an HTTP error.
def test_monitoring_probe_reports_a_failed_token_mint(run: RunTool, fakes: Fakes, monitoring: Monitoring):
    fakes.mode("gcloud", "expired")

    result = run("check", "--json", "--probes", "team")

    data = report(result)
    assert result.returncode == 1
    for project in ("acme-platform-staging", "acme-platform"):
        entry = probe(data, f"monitoring:{project}")
        assert entry["status"] == "fail"
        assert entry["detail"].startswith("ERROR: (gcloud.auth.print-access-token) There was a problem refreshing")
        assert len(entry["detail"]) <= 120
    assert monitoring.requests == []


# Protects: no token reaches stdout or stderr, in JSON or table output, including the Monitoring probe.
# Bug caught: a tool that echoes a CLI's stdout, gh's or signadot's JSON, or the Authorization header.
@pytest.mark.parametrize("output", ["json", "table"])
def test_tokens_never_appear_in_output(run: RunTool, monitoring: Monitoring, output: str):
    monitoring.status_by_project["acme-platform"] = 401
    args = ["check", "--probes", "team", "--require", ALL_LOGINS]
    if output == "json":
        args.append("--json")

    result = run(*args)

    combined = result.stdout + result.stderr
    # The Monitoring server received the minted token, so the token really passed through the tool.
    assert {request["authorization"] for request in monitoring.requests} == {f"Bearer {TOKEN}"}
    if output == "json":
        data = report(result)
        assert provider(data, "gcloud")["status"] == "ok"
        assert provider(data, "signadot")["account"] == "fake-org"
        assert probe(data, "monitoring:acme-platform")["status"] == "fail"
        assert probe(data, "gcloud-adc-token")["status"] == "ok"
    else:
        assert re.search(r"^gcloud\b.*\bok\b", result.stdout, re.MULTILINE), result.stdout
        assert re.search(r"monitoring:acme-platform\b.*401", result.stdout), result.stdout
    assert TOKEN not in combined
    assert TOKEN[:16] not in combined
    assert "LISTED-ROW" not in combined


# Protects: the test-only Monitoring URL override never sends a token to a non-loopback host.
# Bug caught: the guard removed, so AUTH_HELPER_MONITORING_URL can send the token anywhere.
def test_monitoring_override_must_be_loopback(run: RunTool):
    result = run("check", "--json", "--probes", "team", AUTH_HELPER_MONITORING_URL="http://example.invalid")

    data = report(result)
    assert result.returncode == 1
    for project in ("acme-platform-staging", "acme-platform"):
        entry = probe(data, f"monitoring:{project}")
        assert entry["status"] == "fail"
        assert "loopback" in entry["detail"]


# Protects: the gh-auth probe checks the active github.com account only, like the gh provider check.
# Bug caught: unscoped gh auth status exits 1 for a stale login on another host or an inactive account,
# so a working github.com login fails the team preflight.
def test_gh_probe_checks_only_the_active_github_account(run: RunTool, fakes: Fakes):
    (fakes.state / "gh.stale-other-host").touch()
    (fakes.state / "gh.stale-inactive-account").touch()

    passing = run("check", "--json", "--probes", "team")

    data = report(passing)
    assert probe(data, "gh-auth")["status"] == "ok", probe(data, "gh-auth")
    assert data["ok"] is True
    assert passing.returncode == 0, passing.stderr

    fakes.mode("gh", "expired")
    failing = run("check", "--json", "--probes", "team")

    data = report(failing)
    assert probe(data, "gh-auth")["status"] == "fail"
    assert failing.returncode == 1


# Protects: the Monitoring token goes only to the Monitoring host; a redirect fails the probe instead.
# Bug caught: urllib follows the redirect and copies the Authorization header to the new host.
def test_monitoring_probe_refuses_a_redirect(run: RunTool, monitoring: Monitoring, elsewhere: Monitoring):
    monitoring.redirect_by_project["acme-platform"] = (
        f"{elsewhere.url}/v3/projects/acme-platform/timeSeries?view=HEADERS"
    )

    result = run("check", "--json", "--probes", "team")

    data = report(result)
    redirected = probe(data, "monitoring:acme-platform")
    assert redirected["status"] == "fail", redirected
    assert "redirect" in redirected["detail"]
    assert result.returncode == 1
    assert "acme-platform" in [request["project"] for request in monitoring.requests]
    assert elsewhere.requests == []
    assert probe(data, "monitoring:acme-platform-staging")["status"] == "ok"
    assert TOKEN not in result.stdout + result.stderr


# Protects: a broken Monitoring response fails its probe, and check still prints the whole JSON report.
# Bug caught: http.client.IncompleteRead escapes the probe, so check prints a traceback instead of JSON.
def test_monitoring_probe_reports_a_truncated_response(run: RunTool, monitoring: Monitoring):
    monitoring.truncate_by_project.add("acme-platform")

    result = run("check", "--json", "--probes", "team")

    data = report(result)
    truncated = probe(data, "monitoring:acme-platform")
    assert truncated["status"] == "fail", truncated
    assert truncated["detail"]
    assert result.returncode == 1
    assert probe(data, "monitoring:acme-platform-staging")["status"] == "ok"
    assert {entry["name"] for entry in data["probes"]} == TEAM_PROBES


def login_calls(fakes: Fakes, name: str) -> list[str]:
    return [line for line in fakes.calls(name) if " login" in f" {line}"]


# Protects: refresh runs the gh web login only when gh auth status fails, then checks gh again.
# Bug caught: a browser login forced on every refresh, or a refresh that skips a broken gh.
def test_refresh_runs_gh_login_only_when_gh_fails(run: RunTool, fakes: Fakes):
    skipped = run("refresh", "gh")

    assert skipped.returncode == 0, skipped.stdout + skipped.stderr
    assert login_calls(fakes, "gh") == []
    assert re.search(r"^gh: ok\b", skipped.stdout, re.MULTILINE), skipped.stdout

    fakes.mode("gh", "expired")
    refreshed = run("refresh", "gh")

    assert refreshed.returncode == 0, refreshed.stdout + refreshed.stderr
    [login] = login_calls(fakes, "gh")
    assert "--web" in login.split() and "github.com" in login.split()
    assert re.search(r"^gh: ok\b", refreshed.stdout, re.MULTILINE), refreshed.stdout


# Protects: refresh logs in to the team's Spacelift profile and reports the login state afterwards.
# Bug caught: login to the wrong profile or endpoint, or no re-check after the login.
def test_refresh_spacelift_logs_in_to_the_team_profile_and_rechecks(run: RunTool, fakes: Fakes):
    fakes.mode("spacectl", "expired")

    result = run("refresh", "spacelift")

    assert result.returncode == 0, result.stdout + result.stderr
    [login] = login_calls(fakes, "spacectl")
    words = login.split()
    assert words[-1] == "acmeholdings"
    assert "https://acmeholdings.app.us.spacelift.io" in words
    assert re.search(r"^spacelift: ok\b", result.stdout, re.MULTILINE), result.stdout


# Protects: a login that still fails after refresh is reported and fails the command.
# Bug caught: refresh reports success because the login command ran, without checking again.
def test_refresh_reports_a_login_that_still_fails(run: RunTool, fakes: Fakes):
    fakes.mode("signadot", "expired")
    fakes.fail("signadot-auth-login", "Error: login cancelled\n")

    result = run("refresh", "signadot")

    assert result.returncode == 1, result.stdout + result.stderr
    assert len(login_calls(fakes, "signadot")) == 1
    assert re.search(r"^signadot: expired\b", result.stdout, re.MULTILINE), result.stdout


# Protects: the refresh command that check prints renews a login that --horizon marks expiring, and
# refresh fails when the new login still expires inside the horizon.
# Bug caught: refresh checks again without the horizon, sees ok, and skips the signadot login.
def test_refresh_renews_a_login_that_check_marks_expiring(run: RunTool, fakes: Fakes):
    soon = rfc3339(datetime.now(UTC) + timedelta(hours=2))
    (fakes.state / "signadot.expires").write_text(soon)

    checked = run("check", "--require", "signadot", "--horizon", "8h")

    assert checked.returncode == 1, checked.stdout + checked.stderr
    hint = re.search(r"^\s+Or run them all: auth-helper (refresh\b.*)$", checked.stdout, re.MULTILINE)
    assert hint, checked.stdout
    refreshed = run(*shlex.split(hint.group(1)))

    assert refreshed.returncode == 0, refreshed.stdout + refreshed.stderr
    assert len(login_calls(fakes, "signadot")) == 1
    assert re.search(r"^signadot: ok\b", refreshed.stdout, re.MULTILINE), refreshed.stdout

    (fakes.state / "signadot.expires").write_text(soon)
    (fakes.state / "signadot.expires-after-login").write_text(rfc3339(datetime.now(UTC) + timedelta(hours=3)))
    still_short = run(*shlex.split(hint.group(1)))

    assert still_short.returncode == 1, still_short.stdout + still_short.stderr
    assert len(login_calls(fakes, "signadot")) == 2
    assert re.search(r"^signadot: expiring\b", still_short.stdout, re.MULTILINE), still_short.stdout


# Protects: refresh fails when a login command fails, even when the old credential still works.
# Bug caught: refresh ignores the login exit code, so a cancelled login exits 0 on the old credential.
@pytest.mark.parametrize(
    ("name", "selector"),
    [
        ("gcloud", "gcloud-auth-login"),
        ("spacelift", "spacectl-profile-login"),
        ("okta", "open--a-Google Chrome"),
    ],
)
def test_refresh_fails_when_a_login_command_fails(
    run: RunTool, fakes: Fakes, isolated_env: IsolatedEnv, name: str, selector: str
):
    fakes.fail(selector, "login cancelled\n")

    result = run("refresh", name)

    assert result.returncode == 1, result.stdout + result.stderr
    assert re.search(rf"^{name}: .*login command failed \(exit 1\)", result.stdout, re.MULTILINE), result.stdout
    # The old credential still works, but no login happened, so no refresh is recorded.
    assert [entry for entry in history(isolated_env) if entry["event"] == "refreshed"] == []


# Protects: refresh okta opens the team's Okta dashboard in Google Chrome and stays manual.
# Bug caught: the default browser opens instead of Chrome, where the Okta session lives.
def test_refresh_okta_opens_the_dashboard_in_chrome(run: RunTool, fakes: Fakes, isolated_env: IsolatedEnv):
    result = run("refresh", "okta")

    assert result.returncode == 0, result.stdout + result.stderr
    assert fakes.calls("open") == ["-a Google Chrome https://login.acme.example"]
    assert re.search(r"^okta: manual\b", result.stdout, re.MULTILINE), result.stdout
    # Opening Chrome proves no login, so refresh records no Okta event.
    assert history(isolated_env) == []


# Protects: a mistyped provider stops refresh before any login runs.
# Bug caught: `refresh spacelfit` silently does nothing and looks like success.
def test_refresh_refuses_an_unknown_provider(run: RunTool, fakes: Fakes):
    result = run("refresh", "gh", "spacelfit")

    assert result.returncode == 2
    assert "spacelfit" in result.stderr
    assert all(fakes.calls(name) == [] for name in ("gh", "gcloud", "spacectl", "signadot", "open"))


# ---- expiry: the Spacelift token, observed lifetimes, and warnings ---------------------------------

# The header, the claims other than exp, and the signature of a test token hold these values.
TOKEN_SENTINELS = ("SENTINEL-HEADER-kid", "SENTINEL-CLAIM-sub", "SENTINEL-CLAIM-aud", "SENTINEL-SIGNATURE")
FAR_EXP = 4_102_444_800  # 2100-01-01T00:00:00Z


def team_token(exp: object) -> str:
    """A Spacelift-like session JWT with this exp claim. Every other part holds a sentinel."""
    return jwt(
        {"exp": exp, "iat": 1_700_000_000, "sub": "SENTINEL-CLAIM-sub", "aud": ["SENTINEL-CLAIM-aud"]},
        header={"alg": "RS256", "typ": "JWT", "kid": "SENTINEL-HEADER-kid"},
        signature=b64url(b"signature-bytes") + "SENTINEL-SIGNATURE",
    )


def leaked_parts(token: str, *results: subprocess.CompletedProcess[str], also: str = "") -> list[str]:
    """The token parts and sentinels that appear in any output, or in the extra text."""
    combined = "".join(result.stdout + result.stderr for result in results) + also
    return [part for part in (token, *token.split("."), *TOKEN_SENTINELS) if part in combined]


def history_text(isolated_env: IsolatedEnv) -> str:
    path = history_file(isolated_env)
    return path.read_text() if path.exists() else ""


# Protects: spacelift reports its real session expiry, the exp claim of the team profile's token, as a
# token expiry that --horizon applies to. No other part of the token reaches any output or file.
# Bug caught: the first profile's token is read (this machine also holds "acmeholding"), or the
# token, its header, another claim, or its signature is echoed in the report or the history file.
def test_spacelift_expiry_comes_from_the_team_profile_token(run: RunTool, isolated_env: IsolatedEnv):
    exp = int((now_seconds() + timedelta(days=3)).timestamp())
    token = team_token(exp)
    write_spacelift_config(
        isolated_env.home / ".spacelift",
        {"acmeholding": team_token(exp + 50 * 86400), "acmeholdings": token},
    )
    expected = zulu(datetime.fromtimestamp(exp, UTC))

    as_json = run("check", "--json", "--require", "gh,spacelift")
    with_horizon = run("check", "--json", "--require", "gh,spacelift", "--horizon", "8h")
    table = run("check", "--require", "gh,spacelift", "--horizon", "8h")
    inside = run("check", "--json", "--require", "gh,spacelift", "--horizon", "4d")

    for result in (as_json, with_horizon):
        data = report(result)
        assert result.returncode == 0, result.stderr
        spacelift = provider(data, "spacelift")
        assert spacelift["status"] == "ok", spacelift
        assert spacelift["expires_at"] == expected
        assert spacelift["expires_source"] == "token"
        assert spacelift["warning"] is None
    assert re.search(rf"^spacelift \*\s.*{re.escape(expected)}", table.stdout, re.MULTILINE), table.stdout
    data = report(inside)
    spacelift = provider(data, "spacelift")
    assert spacelift["status"] == "expiring"
    assert spacelift["fix"] == SPACELIFT_FIX
    assert data["ok"] is False
    assert inside.returncode == 1
    assert leaked_parts(token, as_json, with_horizon, table, inside, also=history_text(isolated_env)) == []


# Protects: the token comes from the directory that spacectl reads, which SPACELIFT_CONFIG_DIR can move.
# Bug caught: the tool always reads ~/.spacelift, so it reports the expiry of a login spacectl does not use.
def test_spacelift_expiry_follows_spacelift_config_dir(run: RunTool, isolated_env: IsolatedEnv):
    write_spacelift_config(isolated_env.home / ".spacelift", {"acmeholdings": team_token(FAR_EXP)})
    moved = isolated_env.root / "spacelift-config"
    exp = int((now_seconds() + timedelta(days=5)).timestamp())
    write_spacelift_config(moved, {"acmeholdings": team_token(exp)})

    result = run("check", "--json", "--require", "gh,spacelift", SPACELIFT_CONFIG_DIR=str(moved))

    spacelift = provider(report(result), "spacelift")
    assert spacelift["expires_at"] == zulu(datetime.fromtimestamp(exp, UTC))
    assert spacelift["expires_source"] == "token"


# Protects: a missing or malformed Spacelift config or token gives an unknown expiry and a full report.
# Bug caught: a KeyError, a base64 or JSON error, or an out-of-range exp escapes as a traceback, so the
# /rogue skill gets no JSON; or a boolean exp reads as 1970, so a working login fails preflight.
@pytest.mark.parametrize(
    "config",
    [
        pytest.param(None, id="no-config-file"),
        pytest.param("{not json", id="config-not-json"),
        pytest.param({"acmeholding": team_token(FAR_EXP)}, id="no-team-profile"),
        pytest.param({"acmeholdings": {"type": 3, "endpoint": "https://x.example"}}, id="no-access-token"),
        pytest.param({"acmeholdings": "SENTINEL-SIGNATURE.only-two"}, id="token-not-a-jwt"),
        pytest.param({"acmeholdings": "e30.%%%-not-base64-%%%.SENTINEL-SIGNATURE"}, id="payload-not-base64"),
        pytest.param({"acmeholdings": f"e30.{b64url(b'not json')}.SENTINEL-SIGNATURE"}, id="payload-not-json"),
        pytest.param({"acmeholdings": f"e30.{b64url(b'[1]')}.SENTINEL-SIGNATURE"}, id="payload-not-object"),
        pytest.param({"acmeholdings": jwt({"sub": "SENTINEL-CLAIM-sub"})}, id="no-exp"),
        pytest.param({"acmeholdings": team_token("2100-01-01")}, id="exp-a-string"),
        pytest.param({"acmeholdings": team_token(True)}, id="exp-a-boolean"),
        pytest.param({"acmeholdings": team_token(10**20)}, id="exp-out-of-range"),
    ],
)
def test_spacelift_token_that_cannot_be_read_gives_unknown(run: RunTool, isolated_env: IsolatedEnv, config: object):
    directory = isolated_env.home / ".spacelift"
    if isinstance(config, str):
        directory.mkdir()
        (directory / "config.json").write_text(config)
    elif isinstance(config, dict):
        write_spacelift_config(directory, config)

    result = run("check", "--json", "--require", "gh,spacelift", "--horizon", "8h")

    data = report(result)
    assert result.returncode == 0, result.stderr
    assert data["ok"] is True
    spacelift = provider(data, "spacelift")
    assert spacelift["status"] == "ok", spacelift
    assert spacelift["expires_at"] is None
    assert spacelift["expires_source"] == "unknown"
    assert spacelift["warning"] == UNKNOWN_LIFETIME
    assert "Traceback" not in result.stderr
    assert [part for part in TOKEN_SENTINELS if part in result.stdout + result.stderr] == []


# Protects: with no real expiry and no observed lifetime, --horizon adds a warning and keeps the status.
# Bug caught: an unknown expiry counts as expiring, so every long run fails preflight; or no warning shows.
def test_horizon_with_no_lifetime_data_warns_without_failing(run: RunTool):
    required = "gh,gcloud,gcloud-adc,spacelift"

    result = run("check", "--json", "--require", required, "--horizon", "8h")
    table = run("check", "--require", required, "--horizon", "8h")

    data = report(result)
    assert result.returncode == 0, result.stderr
    assert data["ok"] is True
    for name in required.split(","):
        entry = provider(data, name)
        assert entry["status"] == "ok", entry
        assert entry["expires_at"] is None
        assert entry["expires_source"] == "unknown"
        assert entry["observed_lifetimes"] == {"count": 0, "shortest_seconds": None}
        assert entry["warning"] == UNKNOWN_LIFETIME
    signadot = provider(data, "signadot")
    assert signadot["expires_source"] == "provider"
    assert signadot["warning"] is None
    assert table.returncode == 0, table.stdout
    assert re.search(rf"^\s+gcloud: {re.escape(UNKNOWN_LIFETIME)}$", table.stdout, re.MULTILINE), table.stdout


# Protects: check estimates expiry as the last refresh plus the shortest observed lifetime; inside
# --horizon that marks the login expiring, and its fix is the auth-helper refresh command, which records
# the new refresh time.
# Bug caught: the first, last, longest, or mean lifetime used; or the fix is the bare login command,
# which records no refresh, so the estimate never moves and preflight fails on every later run.
def test_check_estimates_expiry_from_the_shortest_observed_lifetime(run: RunTool, isolated_env: IsolatedEnv):
    start = now_seconds() - timedelta(days=3)
    seeded: list[tuple[str, str, datetime]] = []
    for offset_hours, lifetime_hours in ((0, 10), (20, 3), (40, 6)):
        refreshed = start + timedelta(hours=offset_hours)
        seeded += [
            ("gcloud", "refreshed", refreshed),
            ("gcloud", "expired_seen", refreshed + timedelta(hours=lifetime_hours)),
        ]
    last_refresh = now_seconds() - timedelta(hours=1)
    seed_history(isolated_env, *seeded, ("gcloud", "refreshed", last_refresh))

    short = run("check", "--json", "--require", "gh,gcloud", "--horizon", "1h")

    data = report(short)
    assert short.returncode == 0, short.stderr
    gcloud = provider(data, "gcloud")
    assert gcloud["status"] == "ok", gcloud
    assert gcloud["expires_source"] == "observed"
    assert gcloud["expires_at"] == zulu(last_refresh + timedelta(hours=3))
    assert gcloud["observed_lifetimes"] == {"count": 3, "shortest_seconds": 3 * 3600}
    assert gcloud["warning"] is None

    long = run("check", "--json", "--require", "gh,gcloud", "--horizon", "8h")

    data = report(long)
    assert long.returncode == 1
    assert data["ok"] is False
    gcloud = provider(data, "gcloud")
    assert gcloud["status"] == "expiring"
    assert gcloud["fix"] == "auth-helper refresh --horizon 8h gcloud"

    renewed_from = now_seconds()
    refreshed = run(*shlex.split(gcloud["fix"])[1:])
    renewed_until = now_seconds()

    # A 3-hour login cannot last 8 hours, so refresh still reports expiring.
    assert refreshed.returncode == 1, refreshed.stdout + refreshed.stderr
    assert re.search(r"^gcloud: expiring\b", refreshed.stdout, re.MULTILINE), refreshed.stdout
    latest_event, latest_at = events(isolated_env, "gcloud")[-1]
    assert latest_event == "refreshed"
    assert renewed_from <= latest_at <= renewed_until
    after = run("check", "--json", "--require", "gh,gcloud", "--horizon", "2h")

    gcloud = provider(report(after), "gcloud")
    assert after.returncode == 0, after.stderr
    assert gcloud["status"] == "ok"
    assert gcloud["expires_at"] == zulu(latest_at + timedelta(hours=3))


# Protects: the first check that sees a login expired after its refresh records one expired_seen, which
# becomes an observed lifetime. Later checks record nothing.
# Bug caught: no expired_seen recorded, so no lifetime is ever learned; or one per check, so a login
# that stays expired adds a record on every preflight.
def test_first_expired_check_after_a_refresh_records_one_expired_seen(
    run: RunTool, fakes: Fakes, isolated_env: IsolatedEnv
):
    refreshed = now_seconds() - timedelta(hours=2)
    seed_history(isolated_env, ("gcloud", "refreshed", refreshed))
    fakes.mode("gcloud", "expired")
    fakes.mode("gcloud-adc", "ok")

    started = now_seconds()
    results = [run("check", "--json") for _ in range(3)]
    ended = now_seconds()

    for result in results:
        assert provider(report(result), "gcloud")["status"] == "expired"
    recorded = events(isolated_env, "gcloud")
    assert [event for event, _ in recorded] == ["refreshed", "expired_seen"]
    seen = recorded[1][1]
    assert started <= seen <= ended
    assert {entry["provider"] for entry in history(isolated_env)} == {"gcloud"}
    lifetime = int((seen - refreshed).total_seconds())
    assert provider(report(results[-1]), "gcloud")["observed_lifetimes"] == {"count": 1, "shortest_seconds": lifetime}


# Protects: a successful refresh records a refresh for each login that its command renews.
# Bug caught: `gcloud auth login --update-adc` also renews the user login, but only gcloud-adc's refresh
# is recorded, so gcloud's next lifetime counts from an older refresh and is too long.
def test_refresh_records_each_login_that_its_command_renews(run: RunTool, fakes: Fakes, isolated_env: IsolatedEnv):
    fakes.mode("gcloud-adc", "expired")

    started = now_seconds()
    result = run("refresh", "gcloud-adc")
    ended = now_seconds()

    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"^gcloud-adc: ok\b", result.stdout, re.MULTILINE), result.stdout
    for name in ("gcloud-adc", "gcloud"):
        recorded = events(isolated_env, name)
        assert [event for event, _ in recorded] == ["refreshed"], (name, recorded)
        assert started <= recorded[0][1] <= ended


# Protects: the history file is in the user's state directory, readable by the user only.
# Bug caught: history written next to the script or in the working directory, which can be inside the
# dotfiles repository, or created with the default umask, so other users can read it.
def test_history_file_is_user_only_and_outside_the_repo(run: RunTool, isolated_env: IsolatedEnv):
    old_umask = os.umask(0o022)
    try:
        result = run("refresh", "spacelift")
    finally:
        os.umask(old_umask)

    assert result.returncode == 0, result.stdout + result.stderr
    path = history_file(isolated_env)
    assert [event for event, _ in events(isolated_env, "spacelift")] == ["refreshed"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert not path.resolve().is_relative_to(REPO_ROOT)
    found = {*isolated_env.root.rglob("history.jsonl"), *TOOL.parent.parent.rglob("history.jsonl")}
    assert found == {path}


# Protects: the hook that the /rogue skill calls after a Chrome check. `record okta expired` records one
# expired_seen, the first `record okta ok` after it records the refresh, and check then estimates Okta's
# expiry from those records while Okta stays manual.
# Bug caught: `record okta ok` on a session of unknown age records a refresh, which gives a too-short
# lifetime; a repeated record appends duplicates; or record accepts a provider that the shell checks.
def test_record_okta_turns_chrome_checks_into_lifetimes(run: RunTool, isolated_env: IsolatedEnv):
    unseen = run("record", "okta", "ok")

    assert unseen.returncode == 0, unseen.stderr
    assert history(isolated_env) == []

    refreshed = now_seconds() - timedelta(hours=5)
    seed_history(isolated_env, ("okta", "refreshed", refreshed))
    for value in ("expired", "expired", "ok", "ok"):
        recorded = run("record", "okta", value)
        assert recorded.returncode == 0, recorded.stderr

    recorded_events = events(isolated_env, "okta")
    assert [event for event, _ in recorded_events] == ["refreshed", "expired_seen", "refreshed"]
    lifetime = recorded_events[1][1] - refreshed
    checked = run("check", "--json", "--horizon", "8h")

    okta = provider(report(checked), "okta")
    assert okta["status"] == "manual"
    assert okta["expires_source"] == "observed"
    assert okta["expires_at"] == zulu(recorded_events[2][1] + lifetime)
    assert okta["observed_lifetimes"] == {"count": 1, "shortest_seconds": int(lifetime.total_seconds())}
    assert okta["warning"] is not None and okta["expires_at"] in okta["warning"]

    for args, named in ((("gh", "ok"), "'gh'"), (("okta", "maybe"), "'maybe'")):
        refused = run("record", *args)
        assert refused.returncode == 2, refused.stdout
        assert "invalid choice" in refused.stderr and named in refused.stderr, refused.stderr
    assert len(history(isolated_env)) == 3


# Protects: in a Claude Code cloud session GraphQL is blocked but REST works, so gh is usable.
# Bug caught: check trusts only `gh auth status`, reports gh expired, and the preflight asks for a browser login.
def test_gh_is_ok_when_graphql_is_blocked_but_rest_works(run: RunTool, fakes: Fakes):
    fakes.mode("gh", "graphql-blocked")

    result = run("check", "--json")

    data = report(result)
    assert provider(data, "gh")["status"] == "ok", provider(data, "gh")
    assert provider(data, "gh")["account"] == "sucramual"
    assert provider(data, "gh")["fix"] is None
    assert data["ok"] is True
    assert result.returncode == 0, result.stderr


# Protects: the REST fallback does not hide a broken token.
# Bug caught: the fallback reports ok for any non-success state, or drops the reason from `gh auth status`.
def test_gh_stays_expired_when_graphql_is_blocked_and_rest_fails(run: RunTool, fakes: Fakes):
    fakes.mode("gh", "graphql-blocked-no-rest")

    result = run("check", "--json")

    data = report(result)
    gh = provider(data, "gh")
    assert gh["status"] == "expired"
    assert gh["fix"] == GH_FIX
    assert data["ok"] is False
    assert result.returncode == 1
    # The JSON report has no reason field. The table keeps the text from `gh auth status`.
    table = run("check")
    assert "GraphQL is not available" in table.stdout, table.stdout


# Protects: the gh-auth probe passes on REST access when GraphQL is blocked.
# Bug caught: the probe runs `gh auth status`, which fails in a cloud session, so the team preflight fails.
def test_gh_probe_passes_when_graphql_is_blocked_but_rest_works(run: RunTool, fakes: Fakes):
    fakes.mode("gh", "graphql-blocked")

    passing = run("check", "--json", "--probes", "team")

    assert probe(report(passing), "gh-auth")["status"] == "ok", probe(report(passing), "gh-auth")

    fakes.mode("gh", "graphql-blocked-no-rest")
    failing = run("check", "--json", "--probes", "team")

    assert probe(report(failing), "gh-auth")["status"] == "fail"


# Protects: refresh does not open a browser login for a gh that works through REST.
# Bug caught: refresh sees the GraphQL error, runs `gh auth login --web`, and blocks an unattended run.
def test_refresh_skips_gh_login_when_rest_works(run: RunTool, fakes: Fakes):
    fakes.mode("gh", "graphql-blocked")

    result = run("refresh", "gh")

    assert result.returncode == 0, result.stdout + result.stderr
    assert login_calls(fakes, "gh") == []
    assert re.search(r"^gh: ok\b", result.stdout, re.MULTILINE), result.stdout


# ---- behaviour from ro auth's own tests -------------------------------------------------------------
# rogue-auth ran ro auth (sucramual/ro) before auth-helper took its code. These cases come from ro's
# tests/test_auth.py at the commit that rogue-auth pinned, for the behaviour that auth-helper keeps.


# Protects: a required credential that expires while a slow probe runs does not pass the preflight.
# Bug caught: check assesses expiry against the time taken before the checks ran, so a credential
# that is already expired when the report is made still reports ok.
def test_check_assesses_expiry_when_the_checks_finish(run: RunTool, fakes: Fakes):
    (fakes.state / "signadot.expires").write_text(rfc3339(datetime.now(UTC) + timedelta(seconds=3)))
    fakes.slow("spacectl-stack-list", 5)

    result = run("check", "--json", "--require", "signadot", "--probes", "team")

    data = report(result)
    signadot = provider(data, "signadot")
    assert probe(data, "spacelift-stacks")["status"] == "ok"
    assert signadot["expires_at"] is not None
    assert signadot["status"] != "ok", signadot
    assert data["ok"] is False
    assert result.returncode == 1


# Protects: a probe runs with no terminal input and with the prompt variables set, its stdout never
# reaches the output, and a missing program fails only its own probe.
# Bug caught: a probe that inherits stdin and waits for input, echoes listed data, or crashes the
# check when its program is not installed.
def test_probe_is_non_interactive_and_keeps_only_stderr(run: RunTool, fakes: Fakes):
    (fakes.state / "stdin-check").touch()
    fakes.remove("spacectl")

    # auth-helper has input waiting on stdin, but no command that it runs may get any of it.
    as_json = run("check", "--json", "--probes", "team", stdin="typed-answer\n")
    as_table = run("check", "--probes", "team", stdin="typed-answer\n")

    data = report(as_json)
    assert probe(data, "cloud-run:acme-platform") == {
        "name": "cloud-run:acme-platform",
        "status": "ok",
        "detail": None,
    }
    prompt_env = (fakes.state / "prompt-env.log").read_text().splitlines()
    assert prompt_env and set(prompt_env) == {"1 1"}, prompt_env
    absent = probe(data, "spacelift-stacks")
    assert absent == {"name": "spacelift-stacks", "status": "fail", "detail": "spacectl is not installed"}
    assert {entry["name"] for entry in data["probes"] if entry["status"] == "fail"} == {"spacelift-stacks"}
    assert as_json.returncode == 1
    absent_row = r"^\s+fail\s+spacelift-stacks\s+spacectl is not installed$"
    assert re.search(absent_row, as_table.stdout, re.MULTILINE), as_table.stdout
    for result in (as_json, as_table):
        combined = result.stdout + result.stderr
        assert "stdin was open" not in combined
        assert TOKEN not in combined
        assert "LISTED-ROW" not in combined


# Protects: malformed history lines are skipped, the check goes on, and one stderr warning names
# each skipped line.
# Bug caught: a corrupt line is dropped without a word, so a lost observation goes unnoticed; or it
# stops the check.
def test_malformed_history_lines_are_named_in_one_warning(run: RunTool, isolated_env: IsolatedEnv):
    path = history_file(isolated_env)
    seed_history(isolated_env, ("gcloud", "refreshed", now_seconds() - timedelta(hours=1)))
    with path.open("a") as handle:
        handle.write("{not json\n")
        handle.write(json.dumps({"at": "yesterday", "provider": "gcloud", "event": "x"}) + "\n")
        handle.write("\n")
    seed_history(isolated_env, ("gh", "refreshed", now_seconds() - timedelta(hours=1)))

    result = run("check", "--json")

    assert result.returncode == 0, result.stderr
    assert report(result)["ok"] is True
    warnings = [line for line in result.stderr.splitlines() if "login history" in line]
    assert warnings == [f"auth-helper: login history: skipped malformed lines 2, 3 in {path}"]


# Protects: a --horizon past 3650d is refused like any bad duration, before any check.
# Bug caught: a huge horizon overflows timedelta and prints a traceback instead of the usage error.
@pytest.mark.parametrize("horizon", ["3651d", "99999999999999999999d"])
def test_horizon_above_the_maximum_is_refused(run: RunTool, fakes: Fakes, horizon: str):
    result = run("check", "--json", "--horizon", horizon)

    assert result.returncode == 2, result.stdout + result.stderr
    assert result.stderr.strip() == f"auth-helper: bad --horizon {horizon!r}: use at most 3650d"
    assert result.stdout == ""
    assert all(fakes.calls(name) == [] for name in ("gh", "gcloud", "spacectl", "signadot"))


# ---- the tool before auth-helper ------------------------------------------------------------------
# The golden files in tests/fixtures/rogue_auth/ hold the output of rogue-auth before it ran ro
# (dotfiles 7e56c35), recorded on the same fakes. auth-helper keeps that output, apart from the
# differences listed below.

GOLDEN_DIR = REPO_ROOT / "tests" / "fixtures" / "rogue_auth"
ZULU_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def without_times(value: object) -> object:
    """Replace each RFC 3339 UTC time with <time>, so a report from another moment compares equal."""
    if isinstance(value, str):
        return ZULU_TIME.sub("<time>", value)
    if isinstance(value, list):
        return [without_times(item) for item in value]
    if isinstance(value, dict):
        return {key: without_times(item) for key, item in value.items()}
    return value


def replaced(value: object, before: str, after: str) -> object:
    """Replace text in every string of a parsed report."""
    if isinstance(value, str):
        return value.replace(before, after)
    if isinstance(value, list):
        return [replaced(item, before, after) for item in value]
    if isinstance(value, dict):
        return {key: replaced(item, before, after) for key, item in value.items()}
    return value


def golden_result(result: subprocess.CompletedProcess[str], *, json_output: bool) -> dict:
    """The parts of a run that callers read: the exit code, stdout (parsed when it is JSON), and stderr."""
    stdout: object = report(result) if json_output else result.stdout
    return {"exit": result.returncode, "stdout": without_times(stdout), "stderr": without_times(result.stderr)}


def golden_case(case: str, run: RunTool, fakes: Fakes, monitoring: Monitoring, isolated_env: IsolatedEnv) -> dict:
    """Set up one golden case on the fakes, run it, and return its golden_result."""
    if case == "gh-only":
        return golden_result(run("check", "--require", "gh", "--json"), json_output=True)
    if case == "missing-provider":
        fakes.remove("signadot")
        fakes.mode("gcloud", "missing")
        return golden_result(run("check", "--require", "gh,gcloud,signadot", "--json"), json_output=True)
    if case == "probes-team":
        fakes.fail("gcloud-run-services@acme-platform-staging", "ERROR: (gcloud.run.services.list) denied\n")
        monitoring.status_by_project["acme-platform"] = 403
        return golden_result(run("check", "--require", "gh", "--probes", "team", "--json"), json_output=True)
    if case in ("horizon", "horizon-table"):
        last_refresh = now_seconds() - timedelta(hours=1)
        seed_history(
            isolated_env,
            ("gcloud", "refreshed", last_refresh - timedelta(hours=10)),
            ("gcloud", "expired_seen", last_refresh - timedelta(hours=7)),
            ("gcloud", "refreshed", last_refresh),
        )
        (fakes.state / "signadot.expires").write_text(rfc3339(datetime.now(UTC) + timedelta(hours=2)))
        json_output = case == "horizon"
        args = ("check", "--require", "gh,gcloud", "--horizon", "8h", *(("--json",) if json_output else ()))
        return golden_result(run(*args), json_output=json_output)
    if case == "usage-error":
        return golden_result(run("check", "--require", "gh,nope", "--json"), json_output=False)
    raise AssertionError(f"unknown golden case {case}")


# Where the output differs from the golden files on purpose. Each pair is (old text, new text).
ACCEPTED_DIFFERENCES = (
    # The tool's new name, in the printed refresh commands and the error prefix. rogue-auth stays as an alias,
    # so an old command still works.
    ("rogue-auth", "auth-helper"),
    # The Okta reason line in the table, as ro auth worded it. The Okta fix still names Google Chrome.
    ("the shell cannot see Chrome's Okta session", "the shell cannot see the browser's Okta session"),
)
GOLDEN_CASES = ("gh-only", "missing-provider", "probes-team", "horizon", "horizon-table", "usage-error")


# Protects: the /rogue preflight reads the same report, fixes, and exit codes as before.
# Bug caught: a field, fix, status, or probe that changes in the port, such as a probe set that loses a
# probe or changes its order, or a fix that names ro.
@pytest.mark.parametrize("case", GOLDEN_CASES)
def test_output_matches_the_golden_file_of_the_old_tool(
    case: str, run: RunTool, fakes: Fakes, monitoring: Monitoring, isolated_env: IsolatedEnv
):
    expected: object = json.loads((GOLDEN_DIR / f"{case}.json").read_text(encoding="utf-8"))
    for before, after in ACCEPTED_DIFFERENCES:
        expected = replaced(expected, before, after)

    actual = golden_case(case, run, fakes, monitoring, isolated_env)

    assert actual == expected


# Protects: `auth-helper check --help` shows the forms that the /rogue intake tells an agent to read.
# Bug caught: help that names another program, or --probes help that does not name the configured set.
def test_check_help_names_the_tool_the_providers_and_the_probe_set(run: RunTool, fakes: Fakes):
    result = run("check", "--help")

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("usage: auth-helper check "), result.stdout
    assert "team" in result.stdout
    assert all(name in result.stdout for name in PROVIDERS), result.stdout
    assert all(fakes.calls(name) == [] for name in ("gh", "gcloud", "spacectl", "signadot"))


# Protects: auth-helper needs neither ro nor uv. The run fixture already starts it with `python -S`, so
# an import of anything outside the standard library fails every test.
# Bug caught: a leftover ro import, or a uv re-exec that installs ro, on a host without network access.
def test_check_and_refresh_run_without_ro_or_uv(run: RunTool, isolated_env: IsolatedEnv):
    checked = run("check", "--json", "--require", ALL_LOGINS, "--probes", "team")
    refreshed = run("refresh", "spacelift")

    assert checked.returncode == 0, checked.stderr
    assert report(checked)["ok"] is True
    assert refreshed.returncode == 0, refreshed.stdout + refreshed.stderr
    assert not (isolated_env.home / "uv.log").exists(), "auth-helper should not call uv"
    assert not (isolated_env.home / "ro.log").exists(), "auth-helper should not call ro"


# Protects: the old name rogue-auth still works, from PATH, with the same report and history.
# Bug caught: the alias is deleted or points at the removed ro wrapper, so muscle memory and old docs break.
def test_rogue_auth_alias_runs_auth_helper(run: RunTool, fakes: Fakes, isolated_env: IsolatedEnv, run_tool: RunTool):
    python_bin = isolated_env.root / "python-bin"
    python_bin.mkdir()
    (python_bin / "python3").symlink_to(PYTHON)
    linked = isolated_env.root / "home-bin"
    linked.mkdir()
    # Like ~/bin/rogue-auth, which scripts/link_tools.py links to the entry point.
    (linked / "rogue-auth").symlink_to(ALIAS)

    direct = run("check", "--json", "--require", "gh,gcloud")
    alias = run_tool(
        ["rogue-auth", "check", "--json", "--require", "gh,gcloud"],
        cwd=isolated_env.root,
        PATH=os.pathsep.join([str(linked), str(fakes.bin), str(python_bin), "/usr/bin", "/bin"]),
        AUTH_HELPER_CONFIG=str(team_config_path(isolated_env)),
        AUTH_HELPER_MONITORING_URL="http://127.0.0.1:9",
    )

    assert alias.returncode == direct.returncode == 0, alias.stderr
    assert without_times(report(alias)) == without_times(report(direct))


# ---- the team config ------------------------------------------------------------------------------
# The team's settings come from a JSON file that the private work overlay installs. Without it, a check
# that needs a setting must fail, never pass on evidence that it did not collect.

FAKE_CLIS = ("gh", "gcloud", "spacectl", "signadot", "open", "verify-browser")


def assert_not_configured(entry: dict, path: Path) -> None:
    assert entry["status"] == "error", entry
    assert entry["fix"].startswith("Not configured: "), entry
    assert str(path) in entry["fix"], entry


# Protects: a run that asks for a probe set fails when no team config exists, and says why.
# Bug caught: an empty probe list passes `all(...)`, so `--probes team` reports ok without one read.
def test_probe_set_without_a_team_config_fails_as_not_configured(
    run: RunTool, fakes: Fakes, monitoring: Monitoring, isolated_env: IsolatedEnv
):
    absent = isolated_env.root / "absent" / "team.json"

    result = run("check", "--json", "--probes", "team", AUTH_HELPER_CONFIG=str(absent))

    assert result.returncode == 1, result.stdout + result.stderr
    data = report(result)
    assert data["ok"] is False
    assert data["probes"] == [{"name": "team", "status": "fail", "detail": f"not configured: {absent} does not exist"}]
    assert all("--project" not in call for call in fakes.calls("gcloud")), "no project probe may run"
    assert all("stack list" not in call for call in fakes.calls("spacectl")), "no Spacelift probe may run"
    assert monitoring.requests == []


# Protects: a config file without probe sets fails a requested set the same way.
# Bug caught: a config that sets only Spacelift makes `--probes team` a usage error or an empty pass.
def test_probe_set_missing_from_the_team_config_fails_as_not_configured(run: RunTool, isolated_env: IsolatedEnv):
    partial = isolated_env.root / "partial.json"
    partial.write_text(json.dumps({"spacelift": TEAM_CONFIG["spacelift"]}))

    result = run("check", "--json", "--probes", "team", AUTH_HELPER_CONFIG=str(partial))

    assert result.returncode == 1, result.stdout + result.stderr
    data = report(result)
    assert data["ok"] is False
    assert data["probes"] == [
        {"name": "team", "status": "fail", "detail": f"not configured: {partial} does not set probe_sets"}
    ]
    assert provider(data, "spacelift")["status"] == "ok"


# Protects: Spacelift and Okta need team settings. Without them, a required login fails as not configured,
# and no spacectl call runs against an unknown profile.
# Bug caught: a missing profile compares equal to a missing current profile, or an Okta fix opens "None".
def test_providers_without_team_settings_are_not_configured(run: RunTool, fakes: Fakes, isolated_env: IsolatedEnv):
    absent = isolated_env.root / "absent.json"

    result = run("check", "--json", "--require", "gh,spacelift,okta", AUTH_HELPER_CONFIG=str(absent))

    assert result.returncode == 1, result.stdout + result.stderr
    data = report(result)
    assert data["ok"] is False
    assert provider(data, "gh")["status"] == "ok"
    assert_not_configured(provider(data, "spacelift"), absent)
    assert_not_configured(provider(data, "okta"), absent)
    assert "None" not in provider(data, "okta")["fix"]
    assert fakes.calls("spacectl") == []


# Protects: refresh runs no login for a provider without team settings, and fails.
# Bug caught: refresh runs `spacectl profile login --endpoint None None`, or opens Chrome on "None".
def test_refresh_without_team_settings_runs_no_login(run: RunTool, fakes: Fakes, isolated_env: IsolatedEnv):
    absent = isolated_env.root / "absent.json"

    result = run("refresh", "spacelift", "okta", AUTH_HELPER_CONFIG=str(absent))

    assert result.returncode == 1, result.stdout + result.stderr
    assert re.search(r"^spacelift: error - Not configured: ", result.stdout, re.MULTILINE), result.stdout
    assert re.search(r"^okta: error - Not configured: ", result.stdout, re.MULTILINE), result.stdout
    assert fakes.calls("spacectl") == []
    assert fakes.calls("open") == []


# Protects: a team config that exists but is broken stops every check with one clear line.
# Bug caught: a typo in the JSON reads as "no config", so the run goes on with every team check not configured.
@pytest.mark.parametrize(
    ("content", "named"),
    [
        pytest.param("{not json", "is not valid JSON", id="not-json"),
        pytest.param(json.dumps({"okta": {"url": "http://login.acme.example"}}), "okta.url", id="okta-not-https"),
        pytest.param(json.dumps({"probe_sets": {"team": [{"name": "x"}]}}), "probe_sets.team[0]", id="bad-probe"),
        pytest.param(json.dumps({"probe_sets": {"team": []}}), "probe_sets.team", id="empty-set"),
    ],
)
def test_bad_team_config_is_refused_before_any_check(
    run: RunTool, fakes: Fakes, isolated_env: IsolatedEnv, content: str, named: str
):
    broken = isolated_env.root / "broken.json"
    broken.write_text(content)

    result = run("check", "--json", "--require", "gh", AUTH_HELPER_CONFIG=str(broken))

    assert result.returncode == 2, result.stdout + result.stderr
    assert result.stdout == ""
    lines = result.stderr.splitlines()
    assert len(lines) == 1, result.stderr
    assert lines[0].startswith(f"auth-helper: bad team config: {broken}"), result.stderr
    assert named in lines[0], result.stderr
    assert all(fakes.calls(name) == [] for name in FAKE_CLIS)


# Protects: the default config path is the one that the work overlay installer links:
# $XDG_CONFIG_HOME/auth-helper/team.json, else ~/.config/auth-helper/team.json.
# Bug caught: the tool reads another path, so an installed overlay config is never used.
@pytest.mark.parametrize("use_xdg", [True, False], ids=["xdg-config-home", "home-config"])
def test_default_team_config_path(run: RunTool, isolated_env: IsolatedEnv, use_xdg: bool):
    base = isolated_env.root / "xdg" if use_xdg else isolated_env.home / ".config"
    (base / "auth-helper").mkdir(parents=True)
    (base / "auth-helper" / "team.json").write_text(json.dumps(TEAM_CONFIG))
    env = {"AUTH_HELPER_CONFIG": ""}
    if use_xdg:
        env["XDG_CONFIG_HOME"] = str(base)

    result = run("check", "--json", "--require", "gh,spacelift", "--probes", "team", **env)

    assert result.returncode == 0, result.stdout + result.stderr
    data = report(result)
    assert data["ok"] is True
    assert provider(data, "spacelift")["account"] == "acmeholdings"
    assert {entry["name"] for entry in data["probes"]} == TEAM_PROBES
