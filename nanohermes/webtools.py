#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ابزارهای وب مشترک — سرچ چندلایه + خواندن صفحه."""
import os, re, html as _h
from pathlib import Path
from aiohttp import ClientSession

MAX_OUTPUT = 8000
HERMES_ENV = Path("/home/agentuser/.hermes/.env")


def _env(key: str) -> str:
    v = os.environ.get(key)
    if v:
        return v
    try:
        for line in HERMES_ENV.read_text().splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


async def search_deepseek(query: str, n: int = 5) -> str:
    """🔍 سرچ واقعی با استناد (deepseek-search روی dsatlas)."""
    key = _env("DS_API_KEY")
    if not key:
        return ""
    try:
        async with ClientSession() as s:
            async with s.post("https://ds.miors.art/v1/chat/completions",
                              json={"model": "deepseek-search", "stream": False,
                                    "messages": [{"role": "user", "content":
                                    f"{query}\n\n(حداکثر {n} نتیجهٔ کلیدی با لینک بده)"}]},
                              headers={"Authorization": f"Bearer {key}"},
                              timeout=75) as r:
                if r.status != 200:
                    return ""
                d = await r.json(content_type=None)
                return d.get("choices", [{}])[0].get("message", {}).get("content") or ""
    except Exception:
        return ""


async def search_jina(query: str) -> str:
    key = _env("JINA_API_KEY")
    try:
        hdrs = {"Accept": "text/plain"}
        if key:
            hdrs["Authorization"] = f"Bearer {key}"
        async with ClientSession() as s:
            async with s.get("https://s.jina.ai/" + query, headers=hdrs, timeout=40) as r:
                if r.status == 200:
                    t = await r.text()
                    if len(t.strip()) > 120:
                        return t.strip()[:MAX_OUTPUT]
    except Exception:
        pass
    return ""


async def search_ddg(query: str, n: int = 5) -> str:
    import urllib.parse
    for base in ("https://lite.duckduckgo.com/lite/", "https://html.duckduckgo.com/html/"):
        try:
            hdrs = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                  "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml"}
            async with ClientSession() as s:
                async with s.post(base, data={"q": query}, headers=hdrs, timeout=25) as r:
                    txt = await r.text()
            out = []
            for m in re.finditer(r'href="(https?://[^"]+)"[^>]*>(.*?)</a>', txt, re.S):
                u, t = m.group(1), _h.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
                if "duckduckgo.com" in u or not t or len(t) < 8:
                    continue
                out.append(f"• {t}\n  {u}")
                if len(out) >= n:
                    break
            if out:
                return "\n".join(out)
        except Exception:
            continue
    return ""


async def search_wikipedia(query: str, n: int = 5) -> str:
    import urllib.parse
    try:
        async with ClientSession() as s:
            async with s.get("https://en.wikipedia.org/w/api.php?action=query&list=search"
                             "&format=json&srlimit=" + str(n) + "&srsearch=" +
                             urllib.parse.quote(query), timeout=20) as r:
                d = await r.json(content_type=None)
        hits = d.get("query", {}).get("search", [])
        if hits:
            return "\n".join(
                f"• {h['title']} — {re.sub('<[^>]+>', '', h.get('snippet', ''))}\n"
                f"  https://en.wikipedia.org/wiki/" +
                urllib.parse.quote(h["title"].replace(" ", "_")) for h in hits)
    except Exception:
        pass
    return ""


async def web_search(query: str, max_results: int = 5) -> str:
    """سرچ چندلایه با fallback خودکار."""
    q = (query or "").strip()
    if not q:
        return "کوئری خالی است."
    n = int(max_results or 5)
    for fn, label in ((search_deepseek, "DeepSeek-Search"),
                      (search_jina, "Jina"),
                      (search_ddg, "DuckDuckGo"),
                      (search_wikipedia, "Wikipedia")):
        try:
            out = await (fn(q, n) if fn is not search_jina else fn(q))
        except Exception:
            continue
        if out:
            return f"🔍 **{q}**\n\n{out}\n\n«منبع: {label}»"
    return "❌ هیچ موتور جست‌وجویی نتیجه نداد."


async def read_url(url: str) -> str:
    """خواندن متن تمیز صفحه (Jina → fallback)."""
    if not url.startswith(("http://", "https://")):
        return "URL نامعتبر."
    key = _env("JINA_API_KEY")
    try:
        hdrs = {"User-Agent": "Nano-Hermes/1.0"}
        if key:
            hdrs["Authorization"] = f"Bearer {key}"
        async with ClientSession() as s:
            async with s.get("https://r.jina.ai/" + url, headers=hdrs, timeout=30) as r:
                if r.status == 200:
                    t = await r.text()
                    if len(t.strip()) > 80:
                        return t.strip()[:MAX_OUTPUT]
    except Exception:
        pass
    try:
        async with ClientSession() as s:
            async with s.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=25) as r:
                h = await r.text()
            h = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", h, flags=re.S | re.I)
            t = _h.unescape(re.sub(r"<[^>]+>", " ", h))
            return re.sub(r"\s+\n", "\n", re.sub(r"[ \t]+", " ", t)).strip()[:MAX_OUTPUT]
    except Exception as e:
        return f"خطای خواندن: {e}"
