#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  Nano-Hermes — one-line installer
#
#  Usage:
#    curl -fsSL https://raw.githubusercontent.com/Mehrvarz24/nano/main/install.sh | bash
#
#  Custom repo / branch:
#    NANO_REPO=https://github.com/USER/nano.git bash install.sh
#    NANO_BRANCH=dev bash install.sh
#
#  Options (environment variables):
#    NANO_DIR      install directory            (default: ~/.nanohermes)
#    NANO_PORT     web panel port               (default: 7580)
#    NANO_PASS     web panel password           (default: random)
#    NANO_SERVICE  1 = install systemd service, 0 = skip, ask = prompt (default: ask)
#    NANO_BRANCH   git branch                   (default: main)
#    NANO_REPO     git repository URL
#    NANO_FROM_GIT 1 = force clone from git even when run from a local checkout
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

# ── Colors ──
if [ -t 1 ]; then
  B=$'\033[1m'; DIM=$'\033[2m'; R=$'\033[0m'
  CY=$'\033[38;5;81m'; GR=$'\033[38;5;114m'; YE=$'\033[38;5;215m'; RE=$'\033[38;5;203m'
else
  B=""; DIM=""; R=""; CY=""; GR=""; YE=""; RE=""
fi

say()  { printf "  %s\n" "$1"; }
ok()   { printf "  ${GR}✓${R} %s\n" "$1"; }
warn() { printf "  ${YE}!${R} %s\n" "$1"; }
die()  { printf "  ${RE}✗ %s${R}\n" "$1" >&2; exit 1; }
step() { printf "\n${CY}${B}▸ %s${R}\n" "$1"; }

DIR="${NANO_DIR:-$HOME/.nanohermes}"
REPO="${NANO_REPO:-https://github.com/Mehrvarz24/nano.git}"
BRANCH="${NANO_BRANCH:-main}"
PORT="${NANO_PORT:-7580}"

# ── Banner ──
printf "\n"
printf "${CY}${B}"
cat <<'BANNER'
   +--------------------------------------+
   |        N a n o - H e r m e s         |
   |  lightweight server / web / file     |
   |  agent with self-growing skills      |
   +--------------------------------------+
BANNER
printf "${R}\n"

# ── Prerequisites ──
step "Checking prerequisites"

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1; then
    v=$("$c" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "0.0")
    maj=${v%%.*}; min=${v##*.}
    if [ "${maj:-0}" -ge 3 ] && [ "${min:-0}" -ge 10 ]; then PY="$c"; break; fi
  fi
done
[ -n "$PY" ] || die "Python 3.10+ is required. Install it with: sudo apt install python3 python3-venv"
ok "Python: $("$PY" -V 2>&1) -> $(command -v "$PY")"

if command -v git >/dev/null 2>&1; then
  ok "git found"
  HAVE_GIT=1
else
  warn "git not found - will install from a local folder instead"
  HAVE_GIT=0
fi

# uv (fastest way to create the venv) - optional
UV=""
if command -v uv >/dev/null 2>&1; then UV="$(command -v uv)"; ok "uv found (faster install)"; fi

# ── Fetch source ──
step "Fetching source code"
HERE_EARLY="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
HAVE_LOCAL=0
{ [ -f "$HERE_EARLY/nano" ] || [ -f "$HERE_EARLY/nanohermes/nano" ]; } && HAVE_LOCAL=1

SRC=""
if [ "$HAVE_LOCAL" = "1" ] && [ "${NANO_FROM_GIT:-0}" != "1" ]; then
  ok "Installing from local folder: $HERE_EARLY"
  if [ -f "$HERE_EARLY/nanohermes/nano" ]; then
    SRC_LOCAL="$HERE_EARLY/nanohermes"      # repo layout
  else
    SRC_LOCAL="$HERE_EARLY"                 # running from inside the code folder
  fi
  mkdir -p "$DIR"
  cp -r "$SRC_LOCAL"/. "$DIR"/ 2>/dev/null || cp -r "$SRC_LOCAL"/* "$DIR"/ 2>/dev/null || true
  SRC="$DIR"
  rm -rf "$SRC/.git" 2>/dev/null || true
elif [ "$HAVE_GIT" = "1" ] && [[ "$REPO" == http* ]]; then
  if [ -d "$DIR/.git" ]; then
    ok "Updating existing checkout"
    git -C "$DIR" fetch --depth 1 origin "$BRANCH" -q && git -C "$DIR" reset --hard "origin/$BRANCH" -q \
      || warn "Update failed - keeping the current version"
  else
    mkdir -p "$(dirname "$DIR")"
    if git clone --depth 1 -b "$BRANCH" "$REPO" "$DIR" -q 2>/dev/null; then
      ok "Cloned -> $DIR"
    else
      warn "Clone failed (network/permissions) - falling back to the local folder"
      mkdir -p "$DIR"; cp -r "$HERE_EARLY"/. "$DIR"/ 2>/dev/null || true
      SRC="$DIR"
    fi
  fi
  [ -n "$SRC" ] || SRC="$DIR"
else
  # Local mode (install from the folder containing this script)
  HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
  if [ -f "$HERE/nano" ] || [ -f "$HERE/nanohermes/nano" ]; then
    ok "Installing from local folder: $HERE"
    mkdir -p "$DIR"
    cp -r "$HERE"/* "$DIR"/ 2>/dev/null || true
    SRC="$DIR"
  else
    die "Source not found. Provide a git repo or run this from the project folder."
  fi
fi

# If the code lives in a nested nanohermes/ folder, descend into it
if [ -f "$SRC/nanohermes/nano" ]; then SRC="$SRC/nanohermes"; fi
[ -f "$SRC/nano" ] || die "Project files not found in $SRC"

# ── Virtual environment ──
step "Creating the virtual environment"
cd "$SRC"
if [ ! -d ".venv" ]; then
  if [ -n "$UV" ]; then
    "$UV" venv --python "$PY" .venv >/dev/null 2>&1 || "$PY" -m venv .venv
  else
    "$PY" -m venv .venv 2>/dev/null || die "Could not create the venv - install python3-venv"
  fi
  ok "venv created"
else
  ok "venv already present"
fi
VPY="$SRC/.venv/bin/python"
[ -x "$VPY" ] || die "venv python not found at $VPY"

step "Installing dependencies"
if [ -n "$UV" ]; then
  "$UV" pip install --python "$VPY" -q aiohttp pyyaml prompt_toolkit rich 2>&1 | tail -2 || true
else
  "$VPY" -m pip install -q --upgrade pip 2>/dev/null || true
  "$VPY" -m pip install -q aiohttp pyyaml prompt_toolkit rich 2>&1 | tail -2 || true
fi
for mod in aiohttp prompt_toolkit rich; do
  "$VPY" -c "import $mod" 2>/dev/null && ok "$mod" || die "Failed to install $mod"
done

# ── Launcher ──
step "Installing the 'nano' command"
LAUNCH="$SRC/.nano-launch"
cat > "$LAUNCH" <<EOF
#!/usr/bin/env bash
exec "$VPY" "$SRC/nano" "\$@"
EOF
chmod +x "$LAUNCH"

BINDIR=""
for d in /usr/local/bin "$HOME/.local/bin" "$HOME/bin"; do
  if [ -d "$d" ] && [ -w "$d" ]; then BINDIR="$d"; break; fi
done
if [ -z "$BINDIR" ]; then
  mkdir -p "$HOME/.local/bin"; BINDIR="$HOME/.local/bin"
fi

if ln -sf "$LAUNCH" "$BINDIR/nano" 2>/dev/null; then
  ok "nano command -> $BINDIR/nano"
else
  warn "Cannot write to $BINDIR - trying with sudo"
  sudo ln -sf "$LAUNCH" /usr/local/bin/nano 2>/dev/null && ok "Installed to /usr/local/bin/nano" \
    || warn "Could not install the binary - use $LAUNCH directly"
fi

case ":$PATH:" in
  *":$BINDIR:"*) : ;;
  *) warn "$BINDIR is not in PATH - add it to ~/.bashrc: export PATH=\"$BINDIR:\$PATH\"" ;;
esac

# ── Configuration ──
step "Writing configuration"
SRC="$(cd "$SRC" && pwd)"
export SRC
CFG="$SRC/config.json"
if [ ! -f "$CFG" ]; then
  "$VPY" - <<'PYEOF'
import json, os, secrets
from pathlib import Path
p = Path(os.environ["SRC"]) / "config.json"
p.write_text(json.dumps({
    "admin_pass": os.environ.get("NANO_PASS") or secrets.token_urlsafe(12),
    "port": int(os.environ.get("NANO_PORT", "7580")),
    "host": os.environ.get("NANO_HOST", "127.0.0.1"),
    "hermes_env": str(Path.home() / ".hermes" / ".env"),
    "hermes_config": str(Path.home() / ".hermes" / "config.yaml"),
}, indent=1))
PYEOF
  chmod 600 "$CFG"
  ok "config.json created (random password)"
else
  ok "config.json already present"
fi

# ── Skills folder ──
step "Preparing the skills folder"
mkdir -p "$SRC/skills"
[ -z "$(ls -A "$SRC/skills" 2>/dev/null)" ] && cat > "$SRC/skills/README.md" <<'EOF'
# Skills

Every skill is a folder containing a `SKILL.md` file:

```
skills/
+-- my-skill/
    +-- SKILL.md
```

`SKILL.md` format:

```markdown
---
name: my-skill
description: One-line summary of what it does
keywords: [keyword1, keyword2]
version: 1
---

# Title

## Steps
...
```

The agent creates skills on its own while working (via `skill_manage`)
and automatically loads the relevant skill into context next time.
EOF
ok "Skills folder ready"

# ── Verify ──
step "Verifying the installation"
if "$VPY" -m py_compile "$SRC/nano" "$SRC/skills.py" "$SRC/webtools.py" 2>/dev/null; then
  ok "Code is valid (syntax check passed)"
else
  warn "Syntax error detected in the code"
fi

PROVS=0
if [ -f "$HOME/.hermes/config.yaml" ]; then
  PROVS=$("$VPY" - <<'PYEOF' 2>/dev/null || echo 0
try:
    import yaml
    from pathlib import Path
    c = yaml.safe_load(Path.home().joinpath(".hermes/config.yaml").read_text())
    print(len((c.get("providers") or {})))
except Exception:
    print(0)
PYEOF
)
fi
if [ "${PROVS:-0}" -gt 0 ] 2>/dev/null; then
  ok "Found $PROVS provider(s) in the Hermes config (loaded automatically)"
else
  warn "No providers found in the Hermes config - add one later with /provider inside nano"
fi

# ── Web service (optional) ──
step "Web service"
PASS=$("$VPY" - <<PYEOF 2>/dev/null || echo change-me
import json
from pathlib import Path
try: print(json.loads(Path("$CFG").read_text()).get("admin_pass", "change-me"))
except Exception: print("change-me")
PYEOF
)

INSTALL_SVC="${NANO_SERVICE:-ask}"
if [ "$INSTALL_SVC" = "ask" ]; then
  if [ -t 0 ]; then
    printf "  ${DIM}Install a systemd service for the web panel? (keeps it always up and reachable over HTTP) [y/N]: ${R}"
    read -r ans || ans="n"
    case "$ans" in y|Y|yes|YES) INSTALL_SVC=1 ;; *) INSTALL_SVC=0 ;; esac
  else
    INSTALL_SVC=0
  fi
fi

if [ "$INSTALL_SVC" = "1" ]; then
  SVC=/etc/systemd/system/nanohermes.service
  TMP=$(mktemp)
  cat > "$TMP" <<EOF
[Unit]
Description=Nano-Hermes web panel & API
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$SRC
Environment=PORT=$PORT
Environment=HOST=127.0.0.1
Environment=ADMIN_PASS=$PASS
ExecStart=$VPY $SRC/nano_hermes.py
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
  if sudo -n cp "$TMP" "$SVC" 2>/dev/null || sudo cp "$TMP" "$SVC" 2>/dev/null; then
    sudo systemctl daemon-reload
    sudo systemctl enable --now nanohermes 2>/dev/null && ok "nanohermes service enabled" \
      || warn "Failed to enable the service"
  else
    warn "Installing the service needs sudo - skipped"
    echo "  ${DIM}To install manually: NANO_SERVICE=1 sudo -E bash install.sh${R}"
  fi
  rm -f "$TMP"
else
  ok "Service not installed (CLI only)"
fi

# ── Done ──
printf "\n${GR}${B}   ✓ Installation complete${R}\n\n"
say "${B}Run:${R}"
say "  ${CY}nano${R}                        ${DIM}# interactive chat${R}"
say ""
say "${B}If 'nano' is not in PATH:${R}"
say "  ${CY}$LAUNCH${R}"
say ""
if [ "$INSTALL_SVC" = "1" ]; then
  say "${B}Web panel:${R} ${CY}http://127.0.0.1:$PORT${R}"
  say "${B}Panel password:${R} ${YE}$PASS${R}"
  say "  ${DIM}systemctl status nanohermes${R}"
  say ""
fi
say "${DIM}Help inside nano: /help${R}"
say "${DIM}Install directory: $SRC${R}"
printf "\n"
