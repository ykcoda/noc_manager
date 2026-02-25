# NOC Manager

AI-powered Network Operations Center assistant. Ask natural-language questions about your infrastructure and get live answers drawn directly from SolarWinds Orion and VMware vCenter.

---

## What it does

- Chat with a GPT-4o-mini agent through a Streamlit web interface
- Agent calls SolarWinds **and** vCenter tools automatically based on context

**SolarWinds (network layer)**

| Tool | Description |
|---|---|
| Worst-performing devices | Top 20 nodes by packet loss / response time (last 4 hours) |
| BGP status | Cisco routers with at least one BGP peer down (last 30 minutes) |

**vCenter (compute / virtualisation layer)**

| Tool | Description |
|---|---|
| VM health | Power state, CPU count, and memory for all VMs |
| ESXi host health | Connection and power state for all hypervisor hosts |
| Datastore capacity | Capacity and free space per datastore |
| Alarms & events | Active triggered alarms and recent event log entries |
| VM details | Full config, NICs, disks, and guest IPs for a single VM — look up by name (exact or partial) or IP address ²  |
| Snapshot inventory | VMs that have snapshots; filter by age to surface stale ones |
| Cluster resource usage | HA/DRS status and resource pool allocation per cluster |
| VMs with network issues | Powered-on VMs with disconnected or not-connected NICs |
| Certificate expiry | Days remaining on the vCenter TLS cert with OK / WARNING / CRITICAL status |
| Powered-off VMs | All powered-off VMs — identify decommission candidates |

> ² **IP-based VM lookup** requires VMware Tools to be running inside the VM so that vCenter can report guest IP addresses. Name-based lookup has no such requirement.

---

## Example queries

```
Show me the worst-performing network devices right now
Any BGP peers down?
List all powered-on VMs and their memory usage
What's the health of our ESXi hosts?
How full are our datastores?
Any active vCenter alarms?
Give me full details for the VM at 10.179.100.64
Show me details for web-prod-01
Which VMs have snapshots older than 30 days?
What's the HA and DRS status across our clusters?
Are there any VMs with disconnected network adapters?
When does the vCenter certificate expire?
Which VMs have been powered off?
```

---

## Prerequisites

| Requirement | Notes |
|---|---|
| SolarWinds Orion | SWIS JSON API reachable on port 17774 |
| VMware vCenter | REST API reachable on port 443; vCenter 7.0+ required ¹ |
| OpenAI API key | `gpt-4o-mini` access |
| Python 3.11 | For local dev (3.11 matches the Docker image; avoids Pydantic v1 issues on 3.14) |
| Docker + Docker Compose | For containerised deployment |

> ¹ All power-state filtering is performed client-side for maximum compatibility. Server-side `filter.power_states` is not used as its behaviour varies across vCenter versions.

---

## Local development (uv)

```bash
# 1. Create virtual environment pinned to Python 3.11
uv venv --python 3.11 && source .venv/bin/activate
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
| `VC_HOSTNAME` | vCenter hostname (e.g. `vcenter.example.net`) |
| `VC_USERNAME` | vCenter user (e.g. `administrator@vsphere.local`) |
| `VC_PASSWORD` | vCenter password |
| `OPENAI_API_KEY` | Your OpenAI API key |

> **Never commit `.env` to version control.** It is gitignored by default.

---

## Project structure

```
noc_managers/
├── src/
│   └── noc_managers/
│       ├── app.py                   # Streamlit chat UI + LangChain agent
│       └── mcp_servers/
│           ├── __init__.py
│           ├── solarwinds.py        # SolarWinds Orion MCP server (2 tools)
│           └── vcenter.py           # VMware vCenter MCP server (10 tools)
├── pyproject.toml                   # uv / hatchling project config
├── Dockerfile
├── docker-compose.yml
├── .env.example                     # Secret template (safe to commit)
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
  ├── stdio subprocess
  │   MCP Server: mcp_servers/solarwinds.py  (2 tools)
  │     │  FastMCP · HTTPS / Basic Auth
  │     ▼
  │   SolarWinds Orion API (:17774)
  │
  └── stdio subprocess
      MCP Server: mcp_servers/vcenter.py  (10 tools)
        │  FastMCP · HTTPS / session-token REST API
        ▼
      vCenter API (:443)
```

Both MCP servers run as stdio subprocesses inside the same container — no additional network ports required. The agent automatically selects the appropriate tools based on the question asked.
