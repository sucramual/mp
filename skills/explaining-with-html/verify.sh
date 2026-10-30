#!/usr/bin/env bash
# Verify an explainer HTML page before shipping:
#   1. every <pre class="mermaid"> block renders to an SVG in a real headless browser
#   2. no mermaid syntax-error output in the rendered DOM
#   3. TOC anchors resolve to section ids
#   4. required contract sections are present (canonical ids from template.html)
# Usage: ./verify.sh page.html
set -euo pipefail

f="${1:?usage: verify.sh page.html}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

blocks=$(python3 - "$f" <<'EOF'
import html, re, sys, pathlib
src = pathlib.Path(sys.argv[1]).read_text()
blocks = re.findall(r'<pre class="mermaid">\s*(.*?)\s*</pre>', src, re.S)
print(len(blocks))
EOF
)

chrome=""
for c in "google-chrome" "chromium" "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; do
  if command -v "$c" >/dev/null 2>&1 || [ -x "$c" ]; then chrome="$c"; break; fi
done
if [ -z "$chrome" ]; then
  echo "FAIL: no Chrome/Chromium found for headless render check" >&2; exit 1
fi

# Root-run containers (Docker/CI) have no usable Chrome sandbox — launch aborts without --no-sandbox.
# (Scalar + ${var:+...}: empty arrays trip `set -u` under macOS bash 3.2.)
sandbox_flag=""
if [ "$(id -u)" -eq 0 ]; then sandbox_flag="--no-sandbox"; fi

# Percent-encode the path ('#'/spaces in names like "PR #123.html" would otherwise
# be parsed as a URL fragment and Chrome loads the wrong file).
url="$(python3 -c 'import sys, pathlib; print(pathlib.Path(sys.argv[1]).resolve().as_uri())' "$f")"
"$chrome" --headless --disable-gpu --virtual-time-budget=15000 --dump-dom ${sandbox_flag:+"$sandbox_flag"} \
  "$url" 2>/dev/null > "$tmp/rendered.html"

# Mermaid stamps every diagram SVG with aria-roledescription; hand-authored SVGs don't count.
# `|| true`: zero rendered diagrams (e.g. CDN unreachable) makes grep exit 1, which under
# set -e/pipefail would kill the script BEFORE the FAIL diagnostics below can print.
svgs=$(grep -o 'aria-roledescription="[^"]*"' "$tmp/rendered.html" | wc -l | tr -d ' ' || true)

# NOTE: 'error-icon' appears in mermaid's boilerplate CSS on every SUCCESSFUL render —
# it is NOT an error signal. Real failures render literal "Syntax error" text.
errors=$(grep -ci "syntax error in text\|Syntax error in graph" "$tmp/rendered.html" || true)

anchors_missing=$(python3 - "$f" <<'EOF'
import re, sys, pathlib
src = pathlib.Path(sys.argv[1]).read_text()
hrefs = set(re.findall(r'href="#([^"]+)"', src))
ids = set(re.findall(r'id="([^"]+)"', src))
missing = sorted(hrefs - ids)
print('\n'.join(missing))
EOF
)

# Required contract sections (canonical ids from template.html). #design-space is
# conditional (only when the subject contains a design choice), so it is not enforced.
# Each required section must also be LINKED from the TOC — `hrefs - ids` alone only
# catches dangling links, so a deleted TOC (or missing entries) would still pass.
slots_missing=$(python3 - "$f" <<'EOF'
import re, sys, pathlib
src = pathlib.Path(sys.argv[1]).read_text()
ids = set(re.findall(r'id="([^"]+)"', src))
required = ['core-idea', 'architecture', 'anatomy', 'sequence', 'decisions', 'open-tensions', 'glossary']
print('\n'.join(r for r in required if r not in ids))
EOF
)

toc_missing=$(python3 - "$f" <<'EOF'
import re, sys, pathlib
src = pathlib.Path(sys.argv[1]).read_text()
if not re.search(r'<nav[^>]*class="[^"]*\btoc\b', src):
    print('(no <nav class="toc"> found)')
else:
    hrefs = set(re.findall(r'href="#([^"]+)"', src))
    required = ['core-idea', 'architecture', 'anatomy', 'sequence', 'decisions', 'open-tensions', 'glossary']
    print('\n'.join(r for r in required if r not in hrefs))
EOF
)

status=0
echo "mermaid blocks: $blocks · rendered diagram SVGs: $svgs · syntax errors: $errors"
if [ "$svgs" -lt "$blocks" ]; then echo "FAIL: $((blocks - svgs)) mermaid block(s) did not render"; status=1; fi
if [ "$errors" -gt 0 ]; then echo "FAIL: mermaid syntax errors in rendered output"; status=1; fi
if [ -n "$anchors_missing" ]; then echo "FAIL: TOC anchors with no matching id:"; echo "$anchors_missing"; status=1; fi
if [ -n "$slots_missing" ]; then echo "FAIL: required contract sections missing (see SKILL.md):"; echo "$slots_missing"; status=1; fi
if [ -n "$toc_missing" ]; then echo "FAIL: required sections not linked from the TOC:"; echo "$toc_missing"; status=1; fi
[ "$status" -eq 0 ] && echo "OK"
exit "$status"
