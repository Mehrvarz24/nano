# ⚡ Nano-Hermes

**A lightweight terminal assistant with full server access, live web search, and a self-growing skill system.**

A small, fast agent that runs on any Linux server, executes shell commands, reads the web,
and learns from everything it does — no Docker, no Node, no heavy dependencies.

```
+------------------ ⚡ Nano-Hermes ------------------+
|       model  river/deepseek-ai/DeepSeek-V4.1-Flash |
|       tools  * on                                  |
|   reasoning  o normal                              |
|      skills  12 learned                            |
+-------- server / web / files / self-growing -------+

nano > why won't nginx start?

  +- > run_bash {"command": "systemctl status nginx --no-pager | head -20"}
  +- ok 42ms - nginx.service - A high performance web server
  +- > run_bash {"command": "journalctl -u nginx -n 20 --no-pager | tail -5"}
  +- ok 38ms - Address already in use: 0.0.0.0:80

+------------------------------- reply ----------------+
| Port 80 is already taken. Another service (likely     |
| x-ui) is bound to it.                                 |
| Fix: systemctl stop x-ui  - or -  move nginx to a     |
| different port.                                       |
+-------------------------------------------------------+
  2 tools  -  1840 tokens
```

---

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/Mehrvarz24/nano/main/install.sh | bash
```

The installer: checks Python → creates a virtual environment → installs dependencies →
puts the `nano` command on your PATH → writes a config → verifies the installation.

**Optional environment variables:**

| Variable | Default | Purpose |
|---|---|---|
| `NANO_DIR` | `~/.nanohermes` | install directory |
| `NANO_PORT` | `7580` | web panel port |
| `NANO_PASS` | random | web panel password |
| `NANO_SERVICE` | `ask` | install a systemd service (`1` / `0` / `ask`) |
| `NANO_REPO` | repo URL | custom git repository |
| `NANO_BRANCH` | `main` | git branch |

### Install from source

```bash
git clone https://github.com/Mehrvarz24/nano.git
cd nano
bash install.sh
```

### Manual install (no installer)

```bash
git clone https://github.com/Mehrvarz24/nano.git
cd nano/nanohermes
python3 -m venv .venv
.venv/bin/pip install aiohttp pyyaml prompt_toolkit rich
.venv/bin/python nano          # start the CLI
```

---

## Usage

```bash
nano
```

### Slash commands

| Command | Description |
|---|---|
| `/model [provider/model]` | switch model — with no argument, opens an interactive picker |
| `/models` | list all providers and models |
| `/provider` | **add a provider** (name, base URL, key, models) |
| `/new` | start a new conversation |
| `/reasoning` | toggle deep reasoning |
| `/tools` | toggle tools on/off |
| `/stop` | stop the current run (or press `Ctrl+C`) |
| `/status` | server status (RAM, disk, load average) |
| `/sys <text>` | change the agent persona |
| `/skills` | list learned skills |
| `/skill <name>` | show a full skill |
| `/learn [name]` | save the last solution as a skill |
| `/forget <name>` | delete a skill |
| `/history` | show this conversation |
| `/save` `/load` | save / load a session |
| `/exit` | quit |

**Keys:** `Tab` autocomplete · `Up/Down` history · `Ctrl+C` interrupt

---

## Tools

| Tool | Description |
|---|---|
| `run_bash` | execute shell commands (destructive commands are guarded) |
| `web_search` | layered search: **deepseek-search** (cited) → Jina → DDG → Wikipedia |
| `read_url` | read the clean text of a page (Jina Reader) |
| `manage_file` | read / write files on the server |
| `skill_list` | list learned skills |
| `skill_view` | read one skill |
| `skill_manage` | create / update skills |

---

## 🧠 Self-growing skills

The pattern comes from [Hermes Agent](https://github.com/NousResearch/hermes-agent),
but lighter (keyword matching instead of embeddings):

1. **Auto-inject** — before each message, the most relevant skill is matched by keyword and added to context.
2. **Use** — the agent reads it with `skill_view` and follows its steps.
3. **Learn** — after solving something, it creates or updates a skill with `skill_manage`.
4. **Stats** — usage counts are tracked so more useful skills rank higher.

### Skill layout

```
skills/
+-- server-health-check/
    +-- SKILL.md
    +-- references/          # optional
```

```markdown
---
name: server-health-check
description: Check server health: running services and their memory use
keywords: [ram, service, health, server]
version: 1
---

# Server health check

## Steps
### 1) Overview
```bash
uptime && free -h
```

## Notes
- `user@1002.service` is misleading...
```

**The agent writes this itself** when you ask it to:

```
nano > learn this approach
  +- skill_manage {"action":"create","name":"port-conflict-check",...}
  +- ok 3ms - {"ok": true, "name": "port-conflict-check"}
```

---

## Web panel

If you install the service, you also get a lightweight web panel:

```
http://127.0.0.1:7580
```

- chat with the same agent and tools
- manage providers
- browse skills
- conversation history

```bash
systemctl status nanohermes
```

---

## Providers

**Automatic from Hermes:** if `~/.hermes/config.yaml` exists, all of its providers
(with their models) are picked up automatically. Keys are read from `~/.hermes/.env`.

**Manual:** run `/provider` inside the app and add any OpenAI-compatible endpoint
(OpenRouter, Groq, Together, DeepSeek, a local Ollama, …).

---

## Resource usage

Measured on a 2-core / 7.4 GB VM:

| | Nano-Hermes | Hermes Agent |
|---|---|---|
| RAM (idle) | **~40 MB** | ~444 MB |
| RAM (with all plugins) | — | ~679 MB |
| Peak RAM while running a tool | ~42 MB | — |
| Dependencies | 4 Python packages | Python + Node + plugins |
| Startup | ~0.3 s | daemon |

No Docker, no Node, no heavy database (SQLite only).

---

## Security

- **Destructive command guard:** `rm -rf /`, `mkfs`, `dd if=`, `shutdown` and similar are refused.
- **Auto-execution:** the agent runs commands without confirmation (like Hermes).
  On sensitive machines, turn tools off with `/tools`.
- **Secrets:** never printed to output (enforced in the system prompt).
- **Web panel:** listens on `127.0.0.1`. For remote access use a tunnel
  (Cloudflare Tunnel / SSH) instead of exposing the port.

---

## License

MIT
