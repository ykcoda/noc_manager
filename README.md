# NOC Manager

AI-powered Network Operations Center assistant. Ask natural-language questions about your network and get live answers drawn directly from SolarWinds Orion.

---

## What it does

- Chat with a GPT-4o-mini agent through a Streamlit web interface
- Agent calls SolarWinds tools automatically to answer questions
- Built-in tools:
  - **Worst-performing devices** — top 20 nodes by packet loss / response time (last 4 hours)
  - **BGP status** — Cisco routers with at least one BGP peer down (last 30 minutes)

---

## Prerequisites

| Requirement | Notes |
|---|---|
| SolarWinds Orion | SWIS JSON API reachable on port 17774 |
| OpenAI API key | `gpt-4o-mini` access |
| Python 3.11+ | For local dev |
| Docker + Docker Compose | For containerised deployment |

---

## Local development (uv)

```bash
# 1. Create virtual environment and install dependencies
uv venv && source .venv/bin/activate
uv pip install -e .

# 2. Copy the example env file and fill in your credentials
cp .env.example .env

# 3. Run the Streamlit app
streamlit run src/noc_managers/app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

---

## Docker deployment

```bash
# 1. Copy and fill in your credentials
cp .env.example .env

# 2. Build and start
docker compose up --build -d

# 3. View logs
docker compose logs -f

# 4. Stop
docker compose down
```

The app is available at [http://localhost:8501](http://localhost:8501).

---

## Environment variables

Copy `.env.example` to `.env` and set the following:

| Variable | Description |
|---|---|
| `SW_HOSTNAME` | SolarWinds Orion hostname (e.g. `solarwinds.example.net`) |
| `SW_USERNAME` | SolarWinds admin username |
| `SW_PASSWORD` | SolarWinds admin password |
| `OPENAI_API_KEY` | Your OpenAI API key |

> **Never commit `.env` to version control.** It is gitignored by default.

---

## Project structure

```
noc_managers/
├── src/
│   └── noc_managers/
│       ├── app.py           # Streamlit chat UI + LangChain agent
│       └── mcp_server.py    # MCP server exposing SolarWinds tools
├── pyproject.toml           # uv / hatchling project config
├── Dockerfile
├── docker-compose.yml
├── .env.example             # Secret template (safe to commit)
└── .gitignore
```

---

## Architecture

```
Browser
  │
  ▼
Streamlit (app.py)
  │  asyncio + LangChain agent (GPT-4o-mini)
  │
  ▼ stdio subprocess
MCP Server (mcp_server.py)
  │  FastMCP tools
  │
  ▼ HTTPS / Basic Auth
SolarWinds Orion API (:17774)
```

The MCP server runs as a stdio subprocess inside the same container as the Streamlit app — no additional network ports required.
