# NOC Manager

AI-powered Network Operations Center assistant. Ask natural-language questions about your infrastructure and get live answers drawn directly from SolarWinds Orion and VMware vCenter.

---

## What it does

- Chat with a GPT-4o-mini agent through a Streamlit web interface
- Agent calls SolarWinds **and** vCenter tools automatically based on context
- Comprehensive infrastructure observability with 20 integrated tools

### SolarWinds Orion (Network Layer)

| Tool | Description |
|---|---|
| Worst-performing devices | Top 20 nodes by packet loss / response time (last 4 hours) |
| BGP status | Cisco routers with at least one BGP peer down (last 30 minutes) |

### vCenter (Compute / Virtualisation Layer) — 18 tools

**Core Inventory & Health (9 tools)**

| Tool | Description |
|---|---|
| `list_vms_health` | Power state, CPU count, and memory for all VMs |
| `list_esxi_host_health` | Connection and power state for all hypervisor hosts |
| `list_datastore_capacity` | Capacity and free space per datastore |
| `get_vm_details` | Full config, NICs, disks, and guest IPs for a single VM — look up by name (exact or partial) or IP address ¹ |
| `get_cluster_resource_usage` | HA/DRS status and resource pool allocation per cluster |
| `list_vms_with_network_issues` | Powered-on VMs with disconnected or not-connected NICs |
| `check_vcenter_certificate_expiry` | Days remaining on the vCenter TLS cert with OK / WARNING / CRITICAL status |
| `list_powered_off_vms` | All powered-off VMs — identify decommission candidates |
| `get_vm_resource_usage` | CPU allocation, memory allocation, provisioned VMDK capacity, and guest disk usage % per VM — filter by thresholds ² |

**Appliance Health & System Metrics (1 tool)**

| Tool | Description |
|---|---|
| `get_vcenter_appliance_health` | VCSA memory and storage health, vCenter version, and uptime |

**Security & Access Control (1 tool)**

| Tool | Description |
|---|---|
| `list_roles_and_privileges` | All defined RBAC roles with resolved privilege names |

**Network Observability (1 tool)**

| Tool | Description |
|---|---|
| `list_virtual_networks` | All standard port groups, DVS port groups, and opaque networks |

**Capacity Planning & Forecasting (3 tools)**

| Tool | Description |
|---|---|
| `get_capacity_planning_report` | Per-cluster CPU/memory allocation; datastore fill thresholds |
| `list_vms_with_high_cpu_allocation` | VMs with high vCPU counts (overcommit risk analysis) |
| `get_vmtools_status_report` | VMware Tools status across the entire fleet |

**Storage Policy (1 tool)**

| Tool | Description |
|---|---|
| `list_storage_policies` | All VM Storage Policies (SPBM) |

**Inventory & Configuration (2 tools)**

| Tool | Description |
|---|---|
| `get_vcenter_inventory_summary` | Fleet-wide counts (DCs, clusters, hosts, VMs, datastores, networks) |
| `list_resource_pools` | All resource pools with allocation details |

> ¹ **IP-based VM lookup** requires VMware Tools to be running inside the VM so that vCenter can report guest IP addresses. Name-based lookup has no such requirement.
> ² **Guest disk usage %** requires VMware Tools. CPU and memory values are *allocated* (configured) resources — live utilisation % is not available via the vCenter REST API without the SOAP performance manager.

---

## Example queries

_Network & Infrastructure_
```
Show me the worst-performing network devices right now
Any BGP peers down?
List all powered-on VMs and their memory usage
What's the health of our ESXi hosts?
How full are our datastores?
```

_VM Operations & Details_
```
Give me full details for the VM at 10.179.100.64
Show me details for web-prod-01
What's the HA and DRS status across our clusters?
Are there any VMs with disconnected network adapters?
When does the vCenter certificate expire?
Which VMs have been powered off?
Which VMs have disk usage above 80%?
Show me VMs with more than 16 vCPUs allocated
Which VMs have the most memory allocated?
Give me a full resource inventory of all running VMs
```

_Observability & Compliance_
```
What is the vCenter appliance health status and version?
What RBAC roles are defined in our vCenter?
List all virtual networks and distributed switches
Show me the cluster capacity planning report
Which VMs have high CPU allocation (8+ vCPUs)?
What's the VMware Tools status across all VMs?
Show me VMs that need Tools updates
List all VM storage policies
What's our fleet inventory summary? (DCs, clusters, hosts, VMs, datastores)
Show me all resource pools and their allocation details
```

---

## Prerequisites

| Requirement | Notes |
|---|---|
| SolarWinds Orion | SWIS JSON API reachable on port 17774 |
| VMware vCenter | REST API reachable on port 443; vCenter 7.0+ required |
| OpenAI API key | `gpt-4o-mini` access |
| Python 3.11 | For local dev (3.11 matches the Docker image; avoids Pydantic v1 issues on 3.14) |
| Docker + Docker Compose | For containerised deployment |

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

### Docker DNS

`docker-compose.yml` uses Google public DNS (`8.8.8.8` / `8.8.4.4`) so the container can reach `api.openai.com`. Corporate DNS servers typically block or return `NXDOMAIN` for public domains, which prevents Docker from falling back to a public resolver.

```yaml
dns:
  - 8.8.8.8
  - 8.8.4.4
```

**For internal hostnames (SolarWinds, vCenter):** set `SW_HOSTNAME` and `VC_HOSTNAME` to IP addresses in `.env` rather than hostnames. This avoids any DNS dependency for your internal services entirely.

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
│           └── vcenter.py           # VMware vCenter MCP server (18 tools)
├── scripts/
│   └── diagnose_vcenter_api.py      # API endpoint diagnostic tool
├── pyproject.toml                   # uv / hatchling project config
├── Dockerfile
├── docker-compose.yml
├── .env.example                     # Secret template (safe to commit)
└── .gitignore
```

---

## Architecture

```
Browser (http://localhost:8501)
  │
  ▼
Streamlit (app.py)
  │  Python 3.11 + asyncio event loop
  │  LangChain 1.2+ agent (GPT-4o-mini)
  │
  ├── stdio subprocess ──→ MCP Server: solarwinds.py
  │                        FastMCP via stdio
  │                        2 tools
  │                        ↓
  │                    SolarWinds Orion API (:17774)
  │                    HTTPS + Basic Auth
  │
  └── stdio subprocess ──→ MCP Server: vcenter.py
                           FastMCP via stdio
                           18 tools
                           ↓
                       vCenter REST API (:443)
                       HTTPS + session-token auth
```

**Key architectural features:**

- **Zero external ports:** Both MCP servers run as stdio subprocesses — no additional listening ports required
- **Automatic tool selection:** LangChain agent intelligently selects the right tools based on the natural-language query
- **Version compatibility:** All power-state filtering performed client-side for maximum compatibility
- **No extra dependencies:** All tools use existing httpx HTTP client; no pyVmomi, vROps, or SOAP API wrappers required
- **Async/Streamlit compatible:** `nest_asyncio` patches the event loop to prevent conflicts between Streamlit's Tornado server and asyncio.run()
- **Error transparency:** Optional/version-specific endpoints return error dicts instead of raising exceptions; LLM agent handles gracefully
- **Read-only safety:** All tools are GET-only; no destructive operations (POST/DELETE/PATCH)

---

## Recent Changes (Feb 2026)

### vCenter 9 API Cleanup

Removed 9 tools whose backing REST API endpoints were confirmed broken (HTTP 404/400) on the production vCenter 9 environment. Tool count reduced from 27 to 18.

**Removed tools and reason:**

| Tool | Broken Endpoint | HTTP Status |
|---|---|---|
| `get_recent_alarms_and_events` | `/api/vcenter/event` | 404 |
| `query_vcenter_events` | `/api/vcenter/event`, `/api/vcenter/audit-records` | 404 |
| `get_recent_tasks` | `/api/cis/tasks` | 404 |
| `get_active_sessions` | `/api/cis/session/list`, `/api/vcenter/session` | 404 |
| `list_vm_snapshots` | `/api/vcenter/vm/{id}/snapshot` | 404 |
| `list_global_permissions` | `/api/vcenter/authorization/global-access` | 404 |
| `check_host_lockdown_mode` | `/api/vcenter/host/{id}/lockdown` | 404 |
| `get_distributed_switch_details` | `/api/vcenter/vds/switch/{id}` | 404 |
| `get_storage_policy_compliance` | `/api/vcenter/storage/policies/compliance/vm` | 400 |

**Modified tool:**

| Tool | Change |
|---|---|
| `get_vcenter_appliance_health` | Removed `/health/overall`, `/health/cpu`, `/health/network` (all 404); kept `/health/mem`, `/health/storage`, `/system/version`, `/system/uptime` |

**Updated diagnostic script** (`scripts/diagnose_vcenter_api.py`): now tests only confirmed-working endpoints and lists all known broken endpoints for reference.

### Confirmed Working Endpoints (vCenter 9)

| Endpoint | Used By |
|---|---|
| `GET /api/appliance/system/version` | `get_vcenter_appliance_health` |
| `GET /api/appliance/system/uptime` | `get_vcenter_appliance_health` |
| `GET /api/appliance/health/mem` | `get_vcenter_appliance_health` |
| `GET /api/appliance/health/storage` | `get_vcenter_appliance_health` |
| `GET /api/vcenter/vm` | multiple tools |
| `GET /api/vcenter/vm/{id}` | `get_vm_details`, `get_vm_resource_usage` |
| `GET /api/vcenter/vm/{id}/guest/identity` | `get_vmtools_status_report` |
| `GET /api/vcenter/vm/{id}/guest/local-filesystem` | `get_vm_resource_usage` |
| `GET /api/vcenter/vm/{id}/guest/networking/interfaces` | `get_vm_details` |
| `GET /api/vcenter/host` | `list_esxi_host_health`, `get_capacity_planning_report` |
| `GET /api/vcenter/cluster` | `get_cluster_resource_usage`, `get_capacity_planning_report` |
| `GET /api/vcenter/datacenter` | `get_vcenter_inventory_summary` |
| `GET /api/vcenter/datastore` | `list_datastore_capacity`, `get_capacity_planning_report` |
| `GET /api/vcenter/network` | `list_virtual_networks`, `get_vcenter_inventory_summary` |
| `GET /api/vcenter/resource-pool` | `list_resource_pools`, `get_vcenter_inventory_summary` |
| `GET /api/vcenter/certificate-management/vcenter/tls` | `check_vcenter_certificate_expiry` |
| `GET /api/vcenter/authorization/roles` | `list_roles_and_privileges` |
| `GET /api/vcenter/authorization/privileges` | `list_roles_and_privileges` |
| `GET /api/vcenter/storage/policies` | `list_storage_policies` |

---

## Troubleshooting & Known Limitations

### Common Issues

**Docker container fails to start**
```bash
# Check logs for authentication errors
docker compose logs noc-app

# Verify credentials are correct in .env
# Ensure VC_HOSTNAME and SW_HOSTNAME are reachable from container
```

**Agent doesn't respond / times out**
- Streamlit limits inference time; complex queries may timeout
- Check OpenAI API quota and rate limits
- Verify API key in `.env` is correct: `OPENAI_API_KEY=sk-...`

**Guest disk usage is empty for all VMs**
- VMware Tools must be running inside each VM for disk usage reporting
- Verify Tools are installed: `get_vmtools_status_report()`
- Powered-off VMs will not report guest data

### Version Compatibility

| Component | Requirement | Notes |
|---|---|---|
| vCenter | 7.0+ REST API | All power-state filters applied client-side |
| SolarWinds | SWIS JSON API | Port 17774 |
| Python | 3.11–3.13 | LangChain 1.2.x uses pydantic.v1 compat; 3.14+ requires LangChain 2.0 (future) |
| Docker | 20.10+ | Multi-stage build support |
| OpenAI | gpt-4o-mini available | GPT-4 supported; adjust SYSTEM_PROMPT if using different model |

### Performance Considerations

- **First query:** ~5–10 seconds (agent reasoning + API calls)
- **Subsequent queries:** ~2–5 seconds (LangChain caching)
- **Large inventory queries:** May take 10–15 seconds (e.g., `get_capacity_planning_report()` on 1000+ VMs)
- **Guest introspection:** Slower for large clusters; VMware Tools must respond on each VM

### Data Accuracy Notes

| Data Type | Accuracy | Notes |
|---|---|---|
| CPU allocation | High | Configured vCPU count; not live utilisation % |
| Memory allocation | High | Configured RAM in MiB; not live % |
| Guest disk usage | Requires Tools | Percentage used in guest OS |
| VM IPs | Current snapshot | Only updated when vCenter queries guest; requires Tools |

### API Limitations

The vCenter REST API has some limitations vs. SOAP:
- **Triggered alarms:** Not available via REST API (requires SOAP AlarmManager)
- **Real-time performance metrics:** Live CPU/memory % not exposed (vROps required)
- **Custom fields:** Not supported in REST API

### Running the Endpoint Diagnostic

Use the diagnostic script to verify endpoint availability against your vCenter:

```bash
uv run python scripts/diagnose_vcenter_api.py
```

The script tests all endpoints used by the 18 active tools and lists the known broken endpoints for reference.

---

## Support & Development

### Local Testing

```bash
# Run the Streamlit app in debug mode
streamlit run src/noc_managers/app.py --logger.level=debug

# Test MCP server directly (requires manual setup)
python -m noc_managers.mcp_servers.vcenter

# Verify dependencies
python -c "import langchain, langchain_core, langchain_mcp_adapters, nest_asyncio; print('✓ All deps OK')"
```

### Extending with New Tools

To add a new vCenter tool:

1. **Add to `src/noc_managers/mcp_servers/vcenter.py`:**
   ```python
   @mcp.tool()
   def my_new_tool(param: str) -> dict:
       """Tool description for the agent."""
       with _vcenter_session() as client:
           resp = client.get("/api/vcenter/some/endpoint")
           resp.raise_for_status()
           return resp.json()
   ```

2. **Add to SYSTEM_PROMPT in `src/noc_managers/app.py`** so the agent knows about it

3. **Verify the endpoint first** using `scripts/diagnose_vcenter_api.py` before building

### File Locations

- **vCenter tools:** `src/noc_managers/mcp_servers/vcenter.py` (18 tools)
- **SolarWinds tools:** `src/noc_managers/mcp_servers/solarwinds.py` (2 tools)
- **Agent & UI:** `src/noc_managers/app.py`
- **Endpoint diagnostic:** `scripts/diagnose_vcenter_api.py`
- **Dependency config:** `pyproject.toml` (hatchling build backend)
- **Container config:** `Dockerfile`, `docker-compose.yml`
