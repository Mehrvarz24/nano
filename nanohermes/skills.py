#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Nano-Hermes Skills - the self-growing skill system

Hermes pattern:
  - a skill = a folder with SKILL.md (YAML frontmatter + markdown)
  - the agent itself can create/edit skills (skill_manage)
  - the relevant skill is loaded into context automatically

Nano differences (lighter):
  - no embeddings - keyword matching (keywords in frontmatter)
  - no curator/judge - the agent decides on its own
  - SQLite for usage stats; files only for content
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
    """Lightweight dependency-free YAML (key: value plus [a, b] lists)."""
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


# ==================== main API ====================
def list_skills() -> list[dict]:
    """All skills plus usage stats."""
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
    """Read a skill (whole SKILL.md or an attachment)."""
    if not NAME_RE.match(name or ""):
        return {"error": f"invalid name: {name}"}
    base = (SKILLS_DIR / name).resolve()
    if not str(base).startswith(str(SKILLS_DIR.resolve())) or not base.is_dir():
        return {"error": f"skill not found: {name}"}

    target = base / "SKILL.md"
    if file_path:
        # only inside the skill folder
        t = (base / file_path).resolve()
        if not str(t).startswith(str(base)):
            return {"error": "path escapes the skill folder."}
        target = t
    if not target.exists():
        return {"error": f"file not found: {file_path or 'SKILL.md'}"}

    text = target.read_text(errors="replace")
    _touch(name)
    meta, body = _parse_fm(text)
    return {"name": name, "file": file_path or "SKILL.md",
            "meta": meta, "content": body if not file_path else text,
            "raw": text}


def create_skill(name: str, description: str, body: str,
                 keywords: list | None = None) -> dict:
    """Create a new skill."""
    name = (name or "").strip().lower().replace(" ", "-")
    if not NAME_RE.match(name):
        return {"error": "name must be lowercase letters/digits/hyphens (2-64 chars)."}
    d = SKILLS_DIR / name
    if (d / "SKILL.md").exists():
        return {"error": f"skill already exists: {name} - use skill_update instead."}
    if not description or not body:
        return {"error": "description and body are required."}
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(_dump_frontmatter(name, description, keywords or [], body))
    _register(name, created=True)
    return {"ok": True, "name": name, "path": str(d / "SKILL.md")}


def update_skill(name: str, body: str | None = None, description: str | None = None,
                 keywords: list | None = None, append: str | None = None) -> dict:
    """Update an existing skill."""
    if not NAME_RE.match(name or ""):
        return {"error": "invalid name."}
    f = SKILLS_DIR / name / "SKILL.md"
    if not f.exists():
        return {"error": f"skill not found: {name}"}
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
        return {"error": "invalid name."}
    d = SKILLS_DIR / name
    if not (d / "SKILL.md").exists():
        return {"error": f"skill not found: {name}"}
    shutil.rmtree(d)
    c = _db(); c.execute("DELETE FROM skill_stats WHERE name=?", (name,)); c.commit(); c.close()
    return {"ok": True, "deleted": name}


def add_file(name: str, file_path: str, content: str) -> dict:
    """Add an attachment file (references/, scripts/, ...)."""
    if not NAME_RE.match(name or ""):
        return {"error": "invalid name."}
    base = SKILLS_DIR / name
    if not (base / "SKILL.md").exists():
        return {"error": f"skill not found: {name}"}
    rel = (file_path or "").lstrip("/")
    if not rel.startswith(("references/", "scripts/", "templates/", "assets/")):
        return {"error": "path must start with references/, scripts/, templates/ or assets/."}
    t = (base / rel).resolve()
    if not str(t).startswith(str(base)):
        return {"error": "invalid path."}
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text(content or "")
    return {"ok": True, "path": str(t.relative_to(base))}


def search_skills(query: str, limit: int = 4, min_score: int = 1) -> list[dict]:
    """Simple keyword matching over description/body text (no embeddings)."""
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
    """Text of relevant skills, to inject into the system prompt."""
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
    return ("\n\n## Relevant skills (previously learned)\n"
            "Use these as guidance for your task; if you learn something new, "
            "update them with skill_manage.\n\n" + "\n\n".join(parts))


def learn_from_task(task: str, solution: str, name: str,
                    description: str, keywords: list | None = None,
                    append_to: str | None = None) -> dict:
    """Automatic learning: create a skill or append to an existing one."""
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
