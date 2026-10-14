#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Nano-Hermes - lightweight agent with root access, web search and a provider panel

  - chat with Hermes providers (auto-loaded from config.yaml) plus manual ones
  - tools: run_bash, web_search, read_url, manage_file, skills
  - agent tool-calling loop
  - web panel + API + SQLite
"""
import asyncio, json, os, re, sqlite3, time, uuid
from pathlib import Path
from aiohttp import web, ClientSession

import skills as SK

# ====================== settings ======================
BASE       = Path(__file__).resolve().parent
DB_PATH    = BASE / "nano_hermes.db"

# -- config.json (written by install.sh) --
_CFG_JSON = BASE / "config.json"
CFG_DATA = {}
if _CFG_JSON.exists():
    try:
        CFG_DATA = json.loads(_CFG_JSON.read_text())
    except Exception:
        CFG_DATA = {}

PORT       = int(os.getenv("PORT") or CFG_DATA.get("port") or "7580")
HOST       = os.getenv("HOST") or CFG_DATA.get("host") or "127.0.0.1"
ADMIN_PASS = os.getenv("ADMIN_PASS") or CFG_DATA.get("admin_pass") or "change-me-nano"
HERMES_ENV = Path(CFG_DATA.get("hermes_env") or
                  os.environ.get("HERMES_ENV") or (Path.home() / ".hermes" / ".env"))
HERMES_CFG = Path(CFG_DATA.get("hermes_config") or
                  os.environ.get("HERMES_CONFIG") or (Path.home() / ".hermes" / "config.yaml"))

MAX_STEPS   = 12
MAX_OUTPUT  = 8000
CMD_TIMEOUT = 60

DANGER = re.compile(
    r"(rm\s+-rf\s+/[^t]|rm\s+-rf\s+/\s|mkfs|dd\s+if=|:\(\)\{|shutdown|reboot|poweroff|"
    r"init\s+0|>\s*/dev/sd|chmod\s+-R\s+777\s+/|systemctl\s+(stop|disable)\s+(ssh|networking|cloudflared)|"
    r"iptables\s+-F|ufw\s+disable)",
    re.I,
)

SYSTEM_PROMPT = """You are Nano-Hermes, an autonomous AI agent with full (root) access to a Linux server and live web access.

Your tools:
- run_bash: run shell commands. Use it for system checks, services, logs, Docker, networking, any system task.
- web_search: layered web search (deepseek-search with citations, then Jina, DDG, Wikipedia).
- read_url: read a web page as clean text.
- manage_file: read or write files on the server.
- skill_list / skill_view / skill_manage: self-growing memory - the skills you have learned.

Rules:
- Self-growing memory: to see skills, call the skill_list tool ONLY (never look for the skills folder with run_bash).
- Before repeating a task, read the relevant skill with skill_view.
- After solving a hard problem or discovering a trick, save it immediately with skill_manage.
- Reply in Persian unless the user writes in English.
- Be direct. Lead with the result, then a short explanation.
- Before a multi-step task, state in one line what you are about to do, then run it.
- Never print API keys or tokens in the output (mask them if needed).
"""

# ====================== database ======================
def init_db():
    c = sqlite3.connect(DB_PATH)
    c.executescript("""
        CREATE TABLE IF NOT EXISTS providers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE, base_url TEXT, key_env TEXT,
            api_key TEXT, models TEXT, source TEXT DEFAULT 'manual',
            created REAL
        );
        CREATE TABLE IF NOT EXISTS chats(
            id TEXT PRIMARY KEY, title TEXT, model TEXT,
            provider TEXT, created REAL
        );
        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT,
            role TEXT, content TEXT, created REAL
        );
    """)
    c.commit(); c.close()


def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def load_hermes_providers():
    """Read Hermes providers from config.yaml plus .env"""
    out = []
    try:
        import yaml
        cfg = yaml.safe_load(HERMES_CFG.read_text()) or {}
    except Exception as e:
        return out, f"could not read config.yaml: {e}"

    env = {}
    try:
        for line in HERMES_ENV.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    except Exception:
        pass

    for name, p in (cfg.get("providers") or {}).items():
        models = []
        for m in (p.get("models") or []):
            models.append(m["id"] if isinstance(m, dict) else m)
        if p.get("model") and not models:
            models = [p["model"]]
        key_env = p.get("key_env") or ""
        out.append({
            "name": name, "base_url": p.get("base_url", ""), "key_env": key_env,
            "api_key": env.get(key_env, ""), "models": models, "source": "hermes",
        })
    return out, None


def sync_providers():
    provs, err = load_hermes_providers()
    c = db()
    for p in provs:
        c.execute("""INSERT INTO providers(name,base_url,key_env,api_key,models,source,created)
                     VALUES(?,?,?,?,?,?,?)
                     ON CONFLICT(name) DO UPDATE SET
                       base_url=excluded.base_url, key_env=excluded.key_env,
                       api_key=excluded.api_key, models=excluded.models""",
                  (p["name"], p["base_url"], p["key_env"], p["api_key"],
                   json.dumps(p["models"], ensure_ascii=False), "hermes", time.time()))
    c.commit()
    rows = [dict(r) for r in c.execute("SELECT * FROM providers ORDER BY name")]
    c.close()
    return rows, err


def get_provider(name):
    c = db()
    r = c.execute("SELECT * FROM providers WHERE name=?", (name,)).fetchone()
    c.close()
    return dict(r) if r else None


def get_key(prov):
    if prov.get("api_key"):
        return prov["api_key"]
    if prov.get("key_env"):
        if prov["key_env"] in os.environ:
            return os.environ[prov["key_env"]]
        try:
            for line in HERMES_ENV.read_text().splitlines():
                if line.startswith(prov["key_env"] + "="):
                    return line.split("=", 1)[1].strip()
        except Exception:
            pass
    return ""


# ====================== tools ======================
async def tool_run_bash(command: str = "", **kw) -> str:
    if DANGER.search(command):
        return "blocked: destructive command refused."
    try:
        proc = await asyncio.create_subprocess_shell(
            command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=CMD_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            return f"timed out after {CMD_TIMEOUT}s"
        text = out.decode("utf-8", "replace")
        if len(text) > MAX_OUTPUT:
            text = text[:MAX_OUTPUT] + f"\n... [truncated - {len(text)} bytes total]"
        return text or "(no output)"
    except Exception as e:
        return f"error: {e}"


async def tool_web_search(query: str = "", max_results: int = 5, **kw) -> str:
    import webtools
    return await webtools.web_search(query, max_results)


async def tool_read_url(url: str = "", use_reader: bool = True, **kw) -> str:
    import webtools
    return await webtools.read_url(url)


async def tool_manage_file(action: str = "read", path: str = "", content: str = "", **kw) -> str:
    p = Path(path).expanduser()
    try:
        if action == "read":
            if not p.exists():
                return "file not found."
            data = p.read_text(errors="replace")
            return data[:MAX_OUTPUT] + ("…" if len(data) > MAX_OUTPUT else "")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content or "")
        return f"written: {p} ({len(content or '')} chars)"
    except Exception as e:
        return f"file error: {e}"


TOOLS = [
    {"type": "function", "function": {
        "name": "run_bash",
        "description": "Execute a bash command on the Linux server and return stdout/stderr.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "shell command to run"}}, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Search the web (DuckDuckGo) for up-to-date information.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "max_results": {"type": "integer", "default": 5}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "read_url",
        "description": "Fetch and read the clean text of any webpage URL (uses Jina Reader for better extraction).",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"},
            "use_reader": {"type": "boolean", "description": "use Jina Reader (default: yes)"}},
            "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "manage_file",
        "description": "Read or write a file directly on the server.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["read", "write"]},
            "path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["action", "path"]}}},
]

async def tool_skill_list(**kw):
    st = SK.stats()
    if not st["skills"]:
        return "no skills learned yet."
    return "\n".join([f"skills: {st['total']} - total uses: {st['uses_total']}"] +
                      [f"• {x['name']} ({x['uses']}×) — {x['description']}" for x in st["skills"]])


async def tool_skill_view(name="", file_path=None, **kw):
    r = SK.read_skill(name, file_path)
    return r.get("error") or f"# {name}\n{r['content'][:6000]}"


async def tool_skill_manage(action="", name="", description="", keywords="",
                            body="", append="", file_path="", content="", **kw):
    kws = [x.strip() for x in (keywords or "").split(",") if x.strip()]
    if action == "create":
        return str(SK.create_skill(name, description, body, kws))
    if action == "update":
        return str(SK.update_skill(name, body=body or None,
                                   description=description or None, keywords=kws or None))
    if action == "append":
        return str(SK.update_skill(name, append=append or body))
    if action == "delete":
        return str(SK.delete_skill(name))
    if action == "add_file":
        return str(SK.add_file(name, file_path, content))
    return f"invalid action: {action}"


TOOL_FN = {"run_bash": tool_run_bash, "web_search": tool_web_search,
           "read_url": tool_read_url, "manage_file": tool_manage_file,
    "skill_list": tool_skill_list,
    "skill_view": tool_skill_view,
    "skill_manage": tool_skill_manage,
}


async def call_tool(name, args):
    fn = TOOL_FN.get(name)
    if not fn:
        return f"unknown tool: {name}"
    try:
        return await fn(**(args if isinstance(args, dict) else {}))
    except Exception as e:
        return f"tool error: {e}"


# ══════════════════════ LLM ══════════════════════
async def llm_chat(prov, model, messages, use_tools=True, temperature=0.4):
    key = get_key(prov)
    if not key:
        return {"error": f"no API key found for provider '{prov['name']}'"}
    url = prov["base_url"].rstrip("/") + "/chat/completions"
    body = {"model": model, "messages": messages, "temperature": temperature, "stream": False}
    if use_tools:
        body["tools"] = TOOLS
        body["tool_choice"] = "auto"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        async with ClientSession() as s:
            async with s.post(url, json=body, headers=headers, timeout=180) as r:
                data = await r.json(content_type=None)
        if not isinstance(data, dict):
            return {"error": "invalid response"}
        if data.get("error"):
            return {"error": str(data["error"])[:500]}
        ch = (data.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        return {"message": msg, "usage": data.get("usage")}
    except Exception as e:
        return {"error": f"provider error: {e}"}


async def agent_run(prov_name, model, history):
    prov = get_provider(prov_name)
    if not prov:
        return {"error": f"provider not found: {prov_name}"}
    if not model:
        ms = json.loads(prov.get("models") or "[]")
        model = ms[0] if ms else "auto"

    msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    steps = []

    for _ in range(MAX_STEPS):
        res = await llm_chat(prov, model, msgs)
        if "error" in res:
            return {"error": res["error"], "steps": steps}

        msg = res["message"] or {}
        tcs = msg.get("tool_calls") or []
        content = msg.get("content") or ""

        if not tcs:
            return {"reply": content or "(no response)", "steps": steps, "usage": res.get("usage"),
                    "steps_count": len(steps)}

        msgs.append({"role": "assistant", "content": content, "tool_calls": tcs})
        for tc in tcs:
            fn = tc.get("function") or {}
            name = fn.get("name")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            t0 = time.time()
            out = await call_tool(name, args)
            ms = int((time.time() - t0) * 1000)
            steps.append({
                "tool": name, "args": args, "out": out[:1200],
                "ms": ms, "chars": len(out),
                "ok": not out.startswith(("error", "blocked", "timed out")),
            })
            msgs.append({
                "role": "tool", "tool_call_id": tc.get("id"),
                "name": name,                      # compatibility with providers that require name
                "content": out,
            })

    return {"reply": "reached the maximum number of tool steps.", "steps": steps}


# ══════════════════════ API ══════════════════════
routes = web.RouteTableDef()


def auth(req):
    return (req.headers.get("X-Admin-Pass") or req.query.get("pass", "")) == ADMIN_PASS


@routes.get("/")
async def index(req):
    return web.FileResponse(BASE / "index.html")


@routes.get("/api/health")
async def health(req):
    return web.json_response({"ok": True, "service": "nano-hermes", "t": time.time()})


@routes.post("/api/login")
async def login(req):
    d = await req.json()
    return web.json_response({"ok": d.get("password") == ADMIN_PASS})


@routes.get("/api/providers")
async def list_providers(req):
    if not auth(req):
        return web.json_response({"error": "unauthorized"}, status=401)
    rows = []
    for r in db().execute("SELECT * FROM providers ORDER BY name"):
        d = dict(r)
        d["has_key"] = bool(get_key(d))
        d["models"] = json.loads(d.get("models") or "[]")
        d["api_key"] = "***" if d.get("api_key") else ""
        rows.append(d)
    return web.json_response({"providers": rows})


@routes.post("/api/providers/sync")
async def api_sync(req):
    if not auth(req):
        return web.json_response({"error": "unauthorized"}, status=401)
    rows, err = sync_providers()
    return web.json_response({"ok": not err, "count": len(rows), "error": err})


@routes.post("/api/providers")
async def add_provider(req):
    if not auth(req):
        return web.json_response({"error": "unauthorized"}, status=401)
    d = await req.json()
    if not d.get("name") or not d.get("base_url"):
        return web.json_response({"error": "name and base_url are required"}, status=400)
    models = d.get("models") or []
    if isinstance(models, str):
        models = [m.strip() for m in models.split(",") if m.strip()]
    c = db()
    c.execute("""INSERT INTO providers(name,base_url,key_env,api_key,models,source,created)
                 VALUES(?,?,?,?,?,?,?)
                 ON CONFLICT(name) DO UPDATE SET base_url=excluded.base_url,
                 api_key=excluded.api_key, models=excluded.models""",
              (d["name"], d["base_url"], d.get("key_env", ""), d.get("api_key", ""),
               json.dumps(models, ensure_ascii=False), "manual", time.time()))
    c.commit(); c.close()
    return web.json_response({"ok": True})


@routes.delete("/api/providers/{pid}")
async def del_provider(req):
    if not auth(req):
        return web.json_response({"error": "unauthorized"}, status=401)
    c = db()
    c.execute("DELETE FROM providers WHERE id=?", (req.match_info["pid"],))
    c.commit(); c.close()
    return web.json_response({"ok": True})


@routes.get("/api/chats")
async def list_chats(req):
    if not auth(req):
        return web.json_response({"error": "unauthorized"}, status=401)
    rows = [dict(r) for r in db().execute("SELECT * FROM chats ORDER BY created DESC LIMIT 60")]
    return web.json_response({"chats": rows})


@routes.get("/api/chats/{cid}")
async def get_chat(req):
    if not auth(req):
        return web.json_response({"error": "unauthorized"}, status=401)
    c = db()
    msgs = [dict(r) for r in c.execute(
        "SELECT role,content,created FROM messages WHERE chat_id=? ORDER BY id",
        (req.match_info["cid"],))]
    c.close()
    return web.json_response({"messages": msgs})


@routes.get("/api/skills")
async def api_skills(req):
    if not auth(req):
        return web.json_response({"error": "Unauthorized"}, status=401)
    return web.json_response({"skills": SK.list_skills(), "stats": {"total": len(SK.list_skills()),
                             "uses": SK.stats()["uses_total"]}})


@routes.get("/api/skills/{name}")
async def api_skill_get(req):
    if not auth(req):
        return web.json_response({"error": "Unauthorized"}, status=401)
    return web.json_response(SK.read_skill(req.match_info["name"]))


@routes.delete("/api/skills/{name}")
async def api_skill_del(req):
    if not auth(req):
        return web.json_response({"error": "Unauthorized"}, status=401)
    return web.json_response(SK.delete_skill(req.match_info["name"]))


@routes.post("/api/chat")
async def api_chat(req):
    if not auth(req):
        return web.json_response({"error": "unauthorized"}, status=401)
    d = await req.json()
    prov, model = d.get("provider"), d.get("model")
    text = (d.get("message") or "").strip()
    chat_id = d.get("chat_id") or uuid.uuid4().hex[:12]
    if not text:
        return web.json_response({"error": "empty message"}, status=400)

    c = db()
    if not c.execute("SELECT 1 FROM chats WHERE id=?", (chat_id,)).fetchone():
        c.execute("INSERT INTO chats(id,title,model,provider,created) VALUES(?,?,?,?,?)",
                  (chat_id, text[:40], model, prov, time.time()))
    c.execute("INSERT INTO messages(chat_id,role,content,created) VALUES(?,?,?,?)",
              (chat_id, "user", text, time.time()))
    hist = [{"role": r["role"], "content": r["content"]}
            for r in c.execute("SELECT role,content FROM messages WHERE chat_id=? ORDER BY id",
                               (chat_id,))]
    c.commit(); c.close()

    res = await agent_run(prov, model, hist)

    c = db()
    c.execute("INSERT INTO messages(chat_id,role,content,created) VALUES(?,?,?,?)",
              (chat_id, "assistant", res.get("reply") or res.get("error", ""), time.time()))
    c.commit(); c.close()
    return web.json_response({"chat_id": chat_id, **res})


def make_app():
    init_db()
    sync_providers()
    app = web.Application(client_max_size=16 * 1024**2)
    app.add_routes(routes)
    return app


if __name__ == "__main__":
    print(f"Nano-Hermes → http://{HOST}:{PORT}", flush=True)
    web.run_app(make_app(), host=HOST, port=PORT, print=None)
