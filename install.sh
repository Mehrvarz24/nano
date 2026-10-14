#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  ⚡ Nano-Hermes — نصب‌کنندهٔ یک‌خطی
#
#  استفاده:
#    curl -fsSL https://raw.githubusercontent.com/USER/nanohermes/main/install.sh | bash
#
#  یا با مخزن دلخواه:
#    NANO_REPO=https://github.com/USER/nanohermes.git bash install.sh
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

# ── رنگ‌ها ──
if [ -t 1 ]; then
  B=$'\033[1m'; DIM=$'\033[2m'; R=$'\033[0m'
  CY=$'\033[38;5;81m'; GR=$'\033[38;5;114m'; YE=$'\033[38;5;215m'; RE=$'\033[38;5;203m'
  PU=$'\033[38;5;177m'; PK=$'\033[38;5;211m'
else
  B=""; DIM=""; R=""; CY=""; GR=""; YE=""; RE=""; PU=""; PK=""
fi

say()  { printf "  %s\n" "$1"; }
ok()   { printf "  ${GR}✓${R} %s\n" "$1"; }
warn() { printf "  ${YE}!${R} %s\n" "$1"; }
die()  { printf "  ${RE}✗ %s${R}\n" "$1" >&2; exit 1; }
step() { printf "\n${CY}${B}▸ %s${R}\n" "$1"; }

APP="nanohermes"
DIR="${NANO_DIR:-$HOME/.nanohermes}"
REPO="${NANO_REPO:-https://github.com/amir/nanohermes.git}"
BRANCH="${NANO_BRANCH:-main}"
PORT="${NANO_PORT:-7580}"

# ── بنر ──
printf "\n"
printf "${CY}${B}"
cat <<'BANNER'
   ╭──────────────────────────────────╮
   │        ⚡  N a n o - H e r m e s   │
   │   ایجنت سبک سرور · وب · فایل      │
   ╰──────────────────────────────────╯
BANNER
printf "${R}\n"

# ── پیش‌نیازها ──
step "بررسی پیش‌نیازها"

PY=""
for c in python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1; then
    v=$("$c" -c 'import sys; print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo 0)
    maj=${v%%.*}; min=${v##*.}
    if [ "$maj" -ge 3 ] && [ "$min" -ge 10 ]; then PY="$c"; break; fi
  fi
done
[ -n "$PY" ] || die "Python 3.10+ لازم است. نصب کن: sudo apt install python3 python3-venv"
ok "Python: $($PY -V 2>&1) → $(command -v $PY)"

if command -v git >/dev/null 2>&1; then
  ok "git موجود"
  HAVE_GIT=1
else
  warn "git نیست — از حالت بدون‌git استفاده می‌کنم"
  HAVE_GIT=0
fi

# uv (سریع‌ترین راه ساخت venv) — اختیاری
UV=""
if command -v uv >/dev/null 2>&1; then UV="$(command -v uv)"; ok "uv موجود (نصب سریع)"; fi

# ── دریافت کد ──
step "دریافت کد"
HERE_EARLY="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
HAVE_LOCAL=0
{ [ -f "$HERE_EARLY/nano" ] || [ -f "$HERE_EARLY/nanohermes/nano" ]; } && HAVE_LOCAL=1

SRC=""
if [ "$HAVE_LOCAL" = "1" ] && [ "${NANO_FROM_GIT:-0}" != "1" ]; then
  ok "نصب از پوشهٔ محلی: $HERE_EARLY"
  if [ -f "$HERE_EARLY/nanohermes/nano" ]; then
    SRC_LOCAL="$HERE_EARLY/nanohermes"      # ساختار repo
  else
    SRC_LOCAL="$HERE_EARLY"                 # اجرا از داخل پوشهٔ کد
  fi
  mkdir -p "$DIR"
  cp -r "$SRC_LOCAL"/. "$DIR"/ 2>/dev/null || cp -r "$SRC_LOCAL"/* "$DIR"/ 2>/dev/null || true
  SRC="$DIR"
  rm -rf "$SRC/.git" 2>/dev/null || true
elif [ "$HAVE_GIT" = "1" ] && [[ "$REPO" == http* ]]; then
  if [ -d "$DIR/.git" ]; then
    ok "به‌روزرسانی مخزن موجود"
    git -C "$DIR" fetch --depth 1 origin "$BRANCH" -q && git -C "$DIR" reset --hard "origin/$BRANCH" -q \
      || warn "به‌روزرسانی ناموفق — از نسخهٔ موجود استفاده می‌کنم"
  else
    mkdir -p "$(dirname "$DIR")"
    if git clone --depth 1 -b "$BRANCH" "$REPO" "$DIR" -q 2>/dev/null; then
      ok "کلون شد → $DIR"
    else
      warn "کلون مخزن ناموفق (شبکه/دسترسی) — از پوشهٔ محلی استفاده می‌کنم"
      HAVE_LOCAL=1
      mkdir -p "$DIR"; cp -r "$HERE_EARLY"/. "$DIR"/ 2>/dev/null || true
      SRC="$DIR"
    fi
  fi
  [ -n "$SRC" ] || SRC="$DIR"
else
  # حالت محلی (نصب از پوشهٔ همین اسکریپت)
  HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
  if [ -f "$HERE/nano" ] || [ -f "$HERE/nanohermes/nano" ]; then
    ok "نصب از پوشهٔ محلی: $HERE"
    mkdir -p "$DIR"
    cp -r "$HERE"/* "$DIR"/ 2>/dev/null || true
    SRC="$DIR"
  else
    die "کد پیدا نشد. یا git بده یا از پوشهٔ پروژه اجرا کن."
  fi
fi

# اگر کد داخل زیرپوشه nanohermes/ بود
if [ -f "$SRC/nanohermes/nano" ]; then SRC="$SRC/nanohermes"; fi
[ -f "$SRC/nano" ] || die "فایل‌های پروژه پیدا نشد در $SRC"

# ── محیط مجازی ──
step "ساخت محیط مجازی"
cd "$SRC"
if [ ! -d ".venv" ]; then
  if [ -n "$UV" ]; then
    "$UV" venv --python "$PY" .venv >/dev/null 2>&1 || "$PY" -m venv .venv
  else
    "$PY" -m venv .venv 2>/dev/null || die "ساخت venv ناموفق — python3-venv را نصب کن"
  fi
  ok "venv ساخته شد"
else
  ok "venv موجود است"
fi
VPY="$SRC/.venv/bin/python"
[ -x "$VPY" ] || die "پایتون venv پیدا نشد"

step "نصب پکیج‌ها"
if [ -n "$UV" ]; then
  "$UV" pip install --python "$VPY" -q aiohttp pyyaml prompt_toolkit rich 2>&1 | tail -2 || true
else
  "$VPY" -m pip install -q --upgrade pip 2>/dev/null || true
  "$VPY" -m pip install -q aiohttp pyyaml prompt_toolkit rich 2>&1 | tail -2 || true
fi
for mod in aiohttp prompt_toolkit rich; do
  "$VPY" -c "import $mod" 2>/dev/null && ok "$mod" || die "نصب $mod ناموفق"
done

# ── لانچر nano ──
step "ساخت دستور nano"
LAUNCH="$SRC/.nano-launch"
cat > "$LAUNCH" <<EOF
#!/usr/bin/env bash
exec "$VPY" "$SRC/nano" "\$@"
EOF
chmod +x "$LAUNCH"

# محل نصب باینری
BINDIR=""
for d in /usr/local/bin "$HOME/.local/bin" "$HOME/bin"; do
  if [ -d "$d" ] && [ -w "$d" ]; then BINDIR="$d"; break; fi
done
if [ -z "$BINDIR" ]; then
  mkdir -p "$HOME/.local/bin"; BINDIR="$HOME/.local/bin"
fi

if ln -sf "$LAUNCH" "$BINDIR/nano" 2>/dev/null; then
  ok "دستور nano → $BINDIR/nano"
else
  warn "اجازهٔ نوشتن در $BINDIR نبود — با sudo تلاش می‌کنم"
  sudo ln -sf "$LAUNCH" /usr/local/bin/nano 2>/dev/null && ok "نصب شد در /usr/local/bin/nano" \
    || warn "نصب باینری نشد — از $LAUNCH استفاده کن"
fi

case ":$PATH:" in
  *":$BINDIR:"*) : ;;
  *) warn "$BINDIR در PATH نیست — به ~/.bashrc اضافه کن: export PATH=\"$BINDIR:\$PATH\"" ;;
esac

# ── پیکربندی ──
step "پیکربندی"
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
}, ensure_ascii=False, indent=1))
PYEOF
  chmod 600 "$CFG"
  ok "config.json ساخته شد (رمز تصادفی)"
else
  ok "config.json موجود است"
fi

# ── ساختار مهارت‌ها ──
mkdir -p "$SRC/skills"
[ -z "$(ls -A "$SRC/skills" 2>/dev/null)" ] && cat > "$SRC/skills/README.md" <<'EOF'
# مهارت‌ها

هر مهارت یک پوشه با `SKILL.md` است:

```
skills/
└── my-skill/
    └── SKILL.md
```

فرمت `SKILL.md`:

```markdown
---
name: my-skill
description: یک‌خطی چه‌کار می‌کند
keywords: [کلیدواژه۱, کلیدواژه۲]
version: 1
---

# عنوان

## مراحل
...
```

ایجنت خودش هنگام کار مهارت می‌سازد (`skill_manage`) و دفعهٔ بعد
مهارت مرتبط را خودکار در context می‌گیرد.
EOF
ok "پوشهٔ مهارت‌ها آماده"

# ── تست ──
step "تست نصب"
if "$VPY" -m py_compile "$SRC/nano" "$SRC/skills.py" "$SRC/webtools.py" 2>/dev/null; then
  ok "کد سالم (syntax)"
else
  warn "خطای سینتکس در کد"
fi

# آیا پروایدری هست؟
PROVS=0
if [ -f "$HOME/.hermes/config.yaml" ]; then
  PROVS=$("$VPY" - <<'PYEOF' 2>/dev/null || echo 0
try:
    import yaml, json
    from pathlib import Path
    c = yaml.safe_load(Path.home().joinpath(".hermes/config.yaml").read_text())
    print(len((c.get("providers") or {})))
except Exception:
    print(0)
PYEOF
)
fi
if [ "${PROVS:-0}" -gt 0 ] 2>/dev/null; then
  ok "$PROVS پروایدر از Hermes پیدا شد (خودکار)"
else
  warn "پروایدری از Hermes پیدا نشد — بعداً داخل خود nano با /provider اضافه کن"
fi

# ── سرویس وب (اختیاری) ──
step "سرویس وب"
PASS=$("$VPY" - <<PYEOF 2>/dev/null || echo change-me
import json
from pathlib import Path
try: print(json.loads(Path("$CFG").read_text()).get("admin_pass","change-me"))
except Exception: print("change-me")
PYEOF
)

INSTALL_SVC="${NANO_SERVICE:-ask}"
if [ "$INSTALL_SVC" = "ask" ]; then
  if [ -t 0 ]; then
    printf "  ${DIM}سرویس systemd برای پنل وب نصب شود؟ (سرور همیشه بالا بماند و از وب قابل دسترسی باشد) [y/N]: ${R}"
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
    sudo systemctl enable --now nanohermes 2>/dev/null && ok "سرویس nanohermes فعال شد" \
      || warn "فعال‌سازی سرویس ناموفق"
  else
    warn "نصب سرویس نیاز به sudo داشت — رد شد"
    echo "  ${DIM}برای نصب دستی: NANO_SERVICE=1 sudo -E bash install.sh${R}"
  fi
  rm -f "$TMP"
else
  ok "سرویس نصب نشد (فقط CLI)"
fi

# ── پایان ──
printf "\n${GR}${B}   ✓ نصب کامل شد${R}\n\n"
say "${B}اجرا:${R}"
say "  ${CY}nano${R}                        ${DIM}# منوی چت${R}"
say ""
say "${B}اگر nano در PATH نبود:${R}"
say "  ${CY}$LAUNCH${R}"
say ""
if [ "$INSTALL_SVC" = "1" ]; then
  say "${B}پنل وب:${R} ${CY}http://127.0.0.1:$PORT${R}"
  say "${B}رمز پنل:${R} ${YE}$PASS${R}"
  say "  ${DIM}systemctl status nanohermes${R}"
  say ""
fi
say "${DIM}راهنما داخل nano: /help${R}"
say "${DIM}پوشهٔ نصب: $SRC${R}"
printf "\n"
