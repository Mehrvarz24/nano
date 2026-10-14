#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Nano-Hermes Skills — سیستم مهارت خودرشد

الگوی هرمس:
  • مهارت = یک پوشه با SKILL.md (frontmatter YAML + markdown)
  • خودِ ایجنت می‌تواند مهارت بسازد/ویرایش کند (skill_manage)
  • مهارت مرتبط به‌صورت خودکار در context بارگذاری می‌شود

تفاوت‌های nano (سبک‌سازی):
  • بدون embedding — تطبیق با کلیدواژه (keywords در frontmatter)
  • بدون curator/judge — خود ایجنت تصمیم می‌گیرد
  • SQLite برای آمار استفاده؛ فایل فقط برای محتوا
"""
from __future__ import annotations
import json, os, re, sqlite3, time
from pathlib import Path
from typing import Optional

SKILLS_DIR = Path(os.getenv("NANO_SKILLS", Path(__file__).resolve().parent / "skills"))
SKILLS_DIR.mkdir(exist_ok=True)
DB = Path(__file__).resolve().parent / "nano_hermes.db"

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)


# ═══════════════ frontmatter ═══════════════
def _parse_fm(text: str):
    """YAML سبک بدون وابستگی (کلید: مقدار + لیست‌های [a, b])."""
    m = FM_RE.match(text or "")
    if not m:
        return {}, (text or "")
    raw, body = m.group(1), m.group(2)
    meta = {}
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if v.startswith("[") and v.endswith("]"):
            meta[k] = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
        elif v.startswith(("'", '"')) and v.endswith(("'", '"')) and len(v) > 1:
            meta[k] = v[1:-1]
        elif v.lower() in ("true", "false"):
            meta[k] = v.lower() == "true"
        else:
            meta[k] = v
    return meta, body


def _dump_frontmatter(name: str, description: str, keywords: list, body: str,
                      version: int = 1, author: str = "nano", created: float = None) -> str:
    kw = ", ".join(keywords or [])
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"keywords: [{kw}]\n"
        f"version: {version}\n"
        f"author: {author}\n"
        f"created: {time.strftime('%Y-%m-%d', time.localtime(created or time.time()))}\n"
        "---\n\n"
        + (body or "").strip() + "\n"
    )


def _db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_skill_db():
    c = _db()
    c.execute("""
        CREATE TABLE IF NOT EXISTS skill_stats (
            name TEXT PRIMARY KEY,
            uses INTEGER DEFAULT 0,
            created REAL,
            updated REAL,
            last_use REAL
        )""")
    c.execute("CREATE TABLE IF NOT EXISTS lessons ("
              "id INTEGER PRIMARY KEY AUTOINCREMENT,"
              "skill TEXT, text TEXT, created REAL)")
    c.commit(); c.close()


# ═══════════════ API اصلی ═══════════════
def list_skills() -> list[dict]:
    """همهٔ مهارت‌ها + آمار استفاده."""
    stats = {}
    try:
        c = _db()
        for r in c.execute("SELECT * FROM skill_stats"):
            stats[r["name"]] = dict(r)
        c.close()
    except Exception:
        pass

    out = []
    for d in sorted(SKILLS_DIR.iterdir()):
        if not d.is_dir():
            continue
        f = d / "SKILL.md"
        if not f.exists():
            continue
        try:
            meta, body = _parse_fm(f.read_text(errors="replace"))
        except Exception:
            continue
        s = stats.get(d.name, {})
        out.append({
            "name": d.name,
            "description": meta.get("description", ""),
            "keywords": meta.get("keywords", []) if isinstance(meta.get("keywords"), list) else [],
            "version": int(meta.get("version", 1) or 1),
            "uses": s.get("uses", 0),
            "chars": len(body or ""),
            "files": [p.name for p in d.rglob("*") if p.is_file() and p.name != "SKILL.md"][:12],
        })
    return sorted(out, key=lambda x: -x["uses"])


def read_skill(name: str, file_path: str | None = None) -> dict:
    """خواندن یک مهارت (کل SKILL.md یا فایل پیوست)."""
    if not NAME_RE.match(name or ""):
        return {"error": f"نام نامعتبر: {name}"}
    base = (SKILLS_DIR / name).resolve()
    if not str(base).startswith(str(SKILLS_DIR.resolve())) or not base.is_dir():
        return {"error": f"مهارت «{name}» نیست."}

    target = base / "SKILL.md"
    if file_path:
        # فقط داخل پوشهٔ مهارت
        t = (base / file_path).resolve()
        if not str(t).startswith(str(base)):
            return {"error": "مسیر خارج از مهارت."}
        target = t
    if not target.exists():
        return {"error": f"فایل نیست: {file_path or 'SKILL.md'}"}

    text = target.read_text(errors="replace")
    _touch(name)
    meta, body = _parse_fm(text)
    return {"name": name, "file": file_path or "SKILL.md",
            "meta": meta, "content": body if not file_path else text,
            "raw": text}


def create_skill(name: str, description: str, body: str,
                 keywords: list | None = None) -> dict:
    """ساخت مهارت جدید."""
    name = (name or "").strip().lower().replace(" ", "-")
    if not NAME_RE.match(name):
        return {"error": "نام باید حروف کوچک/عدد/خط‌تیره باشد (۲–۶۴)."}
    d = SKILLS_DIR / name
    if (d / "SKILL.md").exists():
        return {"error": f"مهارت «{name}» از قبل هست — از skill_update استفاده کن."}
    if not description or not body:
        return {"error": "توضیح و بدنه لازم است."}
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(_dump_frontmatter(name, description, keywords or [], body))
    _register(name, created=True)
    return {"ok": True, "name": name, "path": str(d / "SKILL.md")}


def update_skill(name: str, body: str | None = None, description: str | None = None,
                 keywords: list | None = None, append: str | None = None) -> dict:
    """به‌روزرسانی مهارت موجود."""
    if not NAME_RE.match(name or ""):
        return {"error": "نام نامعتبر."}
    f = SKILLS_DIR / name / "SKILL.md"
    if not f.exists():
        return {"error": f"مهارت «{name}» نیست."}
    meta, old = _parse_fm(f.read_text(errors="replace"))
    new_body = body if body is not None else old
    if append:
        new_body = (new_body or "").rstrip() + "\n\n" + append.strip() + "\n"
    ver = int(meta.get("version", 1) or 1) + 1
    f.write_text(_dump_frontmatter(
        name, description or meta.get("description", ""),
        keywords if keywords is not None else (meta.get("keywords") or []),
        new_body, version=ver, created=time.time()))
    _register(name, created=False)
    return {"ok": True, "name": name, "version": ver}


def delete_skill(name: str) -> dict:
    import shutil
    if not NAME_RE.match(name or ""):
        return {"error": "نام نامعتبر."}
    d = SKILLS_DIR / name
    if not (d / "SKILL.md").exists():
        return {"error": f"مهارت «{name}» نیست."}
    shutil.rmtree(d)
    c = _db(); c.execute("DELETE FROM skill_stats WHERE name=?", (name,)); c.commit(); c.close()
    return {"ok": True, "deleted": name}


def add_file(name: str, file_path: str, content: str) -> dict:
    """افزودن فایل پیوست (references/, scripts/, …)."""
    if not NAME_RE.match(name or ""):
        return {"error": "نام نامعتبر."}
    base = SKILLS_DIR / name
    if not (base / "SKILL.md").exists():
        return {"error": f"مهارت «{name}» نیست."}
    rel = (file_path or "").lstrip("/")
    if not rel.startswith(("references/", "scripts/", "templates/", "assets/")):
        return {"error": "مسیر باید با references/ یا scripts/ یا templates/ یا assets/ شروع شود."}
    t = (base / rel).resolve()
    if not str(t).startswith(str(base)):
        return {"error": "مسیر نامعتبر."}
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text(content or "")
    return {"ok": True, "path": str(t.relative_to(base))}


def search_skills(query: str, limit: int = 4, min_score: int = 1) -> list[dict]:
    """تطبیق ساده با کلیدواژه + متن توضیح/بدنه (بدون embedding)."""
    q = (query or "").lower()
    words = [w for w in re.findall(r"[\w\u0600-\u06FF]{3,}", q)]
    if not words:
        return []
    results = []
    for d in SKILLS_DIR.iterdir():
        if not d.is_dir() or not (d / "SKILL.md").exists():
            continue
        try:
            text = (d / "SKILL.md").read_text(errors="replace")
        except Exception:
            continue
        meta, body = _parse_fm(text)
        kws = [str(k).lower() for k in (meta.get("keywords") or [])]
        desc = str(meta.get("description", "")).lower()
        low = text.lower()
        score = 0
        for w in words:
            if w in kws:
                score += 4
            if w in desc:
                score += 2
            score += min(low.count(w), 3)
        if score >= min_score:
            results.append({"name": d.name, "description": meta.get("description", ""),
                            "keywords": meta.get("keywords", []), "score": score})
    return sorted(results, key=lambda x: -x["score"])[:limit]


def build_context(query: str, max_chars: int = 3000, top: int = 2) -> str:
    """متن مهارت‌های مرتبط برای تزریق در system prompt."""
    hits = search_skills(query, limit=top)
    if not hits:
        return ""
    parts, used = [], 0
    for h in hits:
        r = read_skill(h["name"])
        if r.get("error"):
            continue
        chunk = f"### {h['name']}\n{r['content'].strip()[:1400]}"
        if used + len(chunk) > max_chars:
            break
        parts.append(chunk)
        used += len(chunk)
        _mark_used(h["name"])
    if not parts:
        return ""
    return ("\n\n## مهارت‌های مرتبط (آموخته‌های قبلی)\n"
            "این‌ها را به‌عنوان راهنمای کارت استفاده کن و اگر چیز جدیدی یاد گرفتی، "
            "با skill_manage به‌روزرسانی کن.\n\n" + "\n\n".join(parts))


def learn_from_task(task: str, solution: str, name: str,
                    description: str, keywords: list | None = None,
                    append_to: str | None = None) -> dict:
    """یادگیری خودکار: مهارت بساز یا به موجود اضافه کن."""
    if append_to:
        r = update_skill(append_to, append=f"## {task[:80]}\n{solution}")
        if r.get("ok"):
            return {"ok": True, "mode": "appended", "skill": append_to}
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "skill").lower()).strip("-")[:50]
    if (SKILLS_DIR / slug / "SKILL.md").exists():
        return update_skill(slug, append=f"## {task[:80]}\n{solution}")
    return create_skill(slug, description, f"## {task[:80]}\n{solution}",
                        keywords or (keywords or []))


# ═══════════════ internal ═══════════════
def _register(name: str, created: bool):
    try:
        c = _db()
        now = time.time()
        c.execute("""INSERT INTO skill_stats(name,uses,created,updated,last_use)
                     VALUES(?,0,?,?,NULL)
                     ON CONFLICT(name) DO UPDATE SET updated=excluded.updated""",
                  (name, now, now))
        c.commit(); c.close()
    except Exception:
        pass


def _touch(name: str):
    try:
        c = _db()
        c.execute("UPDATE skill_stats SET last_use=? WHERE name=?", (time.time(), name))
        c.commit(); c.close()
    except Exception:
        pass


def _mark_used(name: str):
    try:
        c = _db()
        c.execute("""INSERT INTO skill_stats(name,uses,last_use) VALUES(?,1,?)
                     ON CONFLICT(name) DO UPDATE SET uses=uses+1, last_use=excluded.last_use""",
                  (name, time.time()))
        c.commit(); c.close()
    except Exception:
        pass


def stats() -> dict:
    s = list_skills()
    return {"total": len(s), "uses_total": sum(x["uses"] for x in s),
            "chars_total": sum(x["chars"] for x in s), "skills": s[:10]}


init_skill_db()

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print(json.dumps(stats(), ensure_ascii=False, indent=1)); sys.exit()
    cmd = sys.argv[1]
    if cmd == "list":
        print(json.dumps(list_skills(), ensure_ascii=False, indent=1))
    elif cmd == "read" and len(sys.argv) > 2:
        print(json.dumps(read_skill(sys.argv[2]), ensure_ascii=False, indent=1))
    elif cmd == "search" and len(sys.argv) > 2:
        print(json.dumps(search_skills(sys.argv[2]), ensure_ascii=False, indent=1))
