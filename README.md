# NOC Manager

AI-powered Network Operations Center assistant. Ask natural-language questions about your infrastructure and get live answers drawn directly from SolarWinds Orion and VMware vCenter.

---

## What it does

- Chat with a GPT-4o-mini agent through a Streamlit web interface
- Agent calls SolarWinds **and** vCenter tools automatically based on context
- Comprehensive infrastructure observability with 29 integrated tools

### SolarWinds Orion (Network Layer)

| Tool | Description |
|---|---|
| Worst-performing devices | Top 20 nodes by packet loss / response time (last 4 hours) |
| BGP status | Cisco routers with at least one BGP peer down (last 30 minutes) |

### vCenter (Compute / Virtualisation Layer) — 27 tools across 8 observability domains

**Core Inventory & Health (11 tools)**

| Tool | Description |
|---|---|
| `list_vms_health` | Power state, CPU count, and memory for all VMs |
| `list_esxi_host_health` | Connection and power state for all hypervisor hosts |
| `list_datastore_capacity` | Capacity and free space per datastore |
| `get_vm_details` | Full config, NICs, disks, and guest IPs for a single VM — look up by name (exact or partial) or IP address ² |
| `list_vm_snapshots` | VMs that have snapshots; filter by age to surface stale ones |
| `get_cluster_resource_usage` | HA/DRS status and resource pool allocation per cluster |
| `list_vms_with_network_issues` | Powered-on VMs with disconnected or not-connected NICs |
| `check_vcenter_certificate_expiry` | Days remaining on the vCenter TLS cert with OK / WARNING / CRITICAL status |
| `list_powered_off_vms` | All powered-off VMs — identify decommission candidates |
| `get_vm_resource_usage` | CPU allocation, memory allocation, provisioned VMDK capacity, and guest disk usage % per VM — filter by thresholds ³ |
| `get_recent_alarms_and_events` | Recent event log entries (REST API); note that triggered alarms require SOAP API |

**Appliance Health & System Metrics (1 tool)**

| Tool | Description |
|---|---|
| `get_vcenter_appliance_health` | VCSA subsystem health (mem/cpu/storage/network), version, uptime |

**Audit & Event Logs (1 tool)**

| Tool | Description |
|---|---|
| `query_vcenter_events` | Filtered vCenter event stream with user/type/time filtering; audit records (vCenter 8.0+) |

**Active Sessions & Recent Tasks (2 tools)**

| Tool | Description |
|---|---|
| `get_recent_tasks` | Task history with status, progress, and error details |
| `get_active_sessions` | Currently authenticated sessions with idle time tracking (requires Global.Diagnostics privilege) |

**Security & Access Control (3 tools)**

| Tool | Description |
|---|---|
| `list_roles_and_privileges` | All defined RBAC roles with resolved privilege names |
| `list_global_permissions` | User/group global role assignments |
| `check_host_lockdown_mode` | ESXi lockdown status per host (NORMAL / LOCKDOWN / STRICT) |

**Network Observability (2 tools)**

| Tool | Description |
|---|---|
| `list_virtual_networks` | All standard port groups, DVS port groups, and opaque networks |
| `get_distributed_switch_details` | Detailed DVS configuration (ports, uplinks, MTU, host membership) |

**Capacity Planning & Forecasting (3 tools)**

| Tool | Description |
|---|---|
| `get_capacity_planning_report` | Per-cluster CPU/memory allocation; datastore fill thresholds |
| `list_vms_with_high_cpu_allocation` | VMs with high vCPU counts (overcommit risk analysis) |
| `get_vmtools_status_report` | VMware Tools status across the entire fleet |

**Storage Policy & Compliance (2 tools)**

| Tool | Description |
|---|---|
| `list_storage_policies` | All VM Storage Policies (SPBM) |
| `get_storage_policy_compliance` | VMs non-compliant with assigned policies |

**Inventory & Configuration (2 tools)**

| Tool | Description |
|---|---|
| `get_vcenter_inventory_summary` | Fleet-wide counts (DCs, clusters, hosts, VMs, datastores, networks) |
| `list_resource_pools` | All resource pools with allocation details |

> ² **IP-based VM lookup** requires VMware Tools to be running inside the VM so that vCenter can report guest IP addresses. Name-based lookup has no such requirement.
> ³ **Guest disk usage %** requires VMware Tools. CPU and memory values are *allocated* (configured) resources — live utilisation % is not available via the vCenter REST API without the SOAP performance manager.

---

## Example queries

_Network & Infrastructure_
```
Show me the worst-performing network devices right now
Any BGP peers down?
List all powered-on VMs and their memory usage
What's the health of our ESXi hosts?
How full are our datastores?
Any active vCenter alarms?
```

_VM Operations & Details_
```
Give me full details for the VM at 10.179.100.64
Show me details for web-prod-01
Which VMs have snapshots older than 30 days?
What's the HA and DRS status across our clusters?
Are there any VMs with disconnected network adapters?
When does the vCenter certificate expire?
Which VMs have been powered off?
Which VMs have disk usage above 80%?
Show me VMs with more than 16 vCPUs allocated
Which VMs have the most memory allocated?
Give me a full resource inventory of all running VMs
```

_Observability & Compliance (New)_
```
What is the vCenter appliance health status and version?
Show me vCenter events from the last 24 hours
Which vCenter users are currently logged in?
List recent administrative tasks in vCenter
What RBAC roles are defined in our vCenter?
Who has global permissions in vCenter?
Which ESXi hosts have lockdown mode enabled?
List all virtual networks and distributed switches
Show me the cluster capacity planning report
Which VMs have high CPU allocation (8+ vCPUs)?
What's the VMware Tools status across all VMs?
Show me VMs that need Tools updates
List all VM storage policies
Which VMs are non-compliant with their storage policies?
What's our fleet inventory summary? (DCs, clusters, hosts, VMs, datastores)
Show me all resource pools and their allocation details
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
│           └── vcenter.py           # VMware vCenter MCP server (27 tools)
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
                           27 tools across 8 domains
                           ↓
                       vCenter REST API (:443)
                       HTTPS + session-token auth
```

**Key architectural features:**

- **Zero external ports:** Both MCP servers run as stdio subprocesses — no additional listening ports required
- **Automatic tool selection:** LangChain agent intelligently selects the right tools based on the natural-language query
- **Version compatibility:** vCenter 7.0+ REST API; all power-state filtering performed client-side for maximum compatibility
- **No extra dependencies:** All tools use existing httpx HTTP client; no pyVmomi, vROps, or SOAP API wrappers required
- **Async/Streamlit compatible:** `nest_asyncio` patches the event loop to prevent conflicts between Streamlit's Tornado server and asyncio.run()
- **Error transparency:** Optional/version-specific endpoints return error dicts instead of raising exceptions; LLM agent handles gracefully
- **Read-only safety:** All tools are GET-only; no destructive operations (POST/DELETE/PATCH)

---

## Recent Enhancements (Feb 2026)

### Pydantic v2 Compatibility
Dependency bounds updated to support Pydantic v2 with pragmatic version constraints:
- ✅ **Pinned Pydantic:** `>=2.0.0,<3.0` (native Pydantic v2)
- ✅ **Explicit langchain-core:** `>=0.3.0` (Pydantic v2 support)
- ✅ **Python version constraint:** `>=3.11,<3.14` (avoids pydantic.v1 compat layer with 3.14+)
- ⚠️ **Known limitation:** Upstream dependencies (LangChain 1.2.x) still use pydantic.v1 compat shim; warning appears on Python 3.14+

**Upgrade path:** When LangChain 2.0 fully migrates to Pydantic v2 native APIs (Q2 2026+), this constraint will be removed and Python 3.15+ will be supported natively without warnings.

### Endpoint & Integration Fixes
All 27 vCenter tools verified operational with corrected API paths and response parsing:

- ✅ **Event log endpoint:** Fixed incorrect paths for recent events (now `/api/vcenter/event`)
- ✅ **Guest disk usage:** Fixed filesystem response parsing and endpoint path (`/api/vcenter/vm/{id}/guest/local-filesystem`)
- ✅ **Distributed virtual switches:** Corrected path (`/api/vcenter/vds/switch`); DVS parent names now properly augmented
- ✅ **Host lockdown mode:** Fixed endpoint path and string response handling
- ✅ **Session listing:** Enhanced to list all sessions via `/api/cis/session/list` with fallback
- ✅ **RBAC endpoints:** Try plural forms first (`roles`/`privileges`) with fallback to singular
- ✅ **Cluster capacity:** Fixed substring matching bug in host count calculation

### Dependency & Runtime Improvements
- ✅ **Streamlit async compatibility:** Added `nest_asyncio` to enable `asyncio.run()` within Streamlit's event loop
- ✅ **Tightened dependency bounds:** Pinned langchain (≥1.2.0) and langchain-mcp-adapters (≥0.1.0) to prevent version resolution errors
- ✅ **Input validation:** Added bounds checking and empty-string validation to 6 tools (identifiers, thresholds, timeouts)
- ✅ **Consistent error handling:** All optional/version-specific endpoints now use `_safe_get()` helper
- ✅ **Canonical imports:** Updated to use `langchain_core.messages` for maintainability

### Testing & Verification
- Docker image builds successfully
- All 27 tools registered and initialized in MCP server
- Syntax validation passed
- Dependency resolution successful (all versions available on PyPI)
- Module imports verified
- Example queries tested with agent

---

## VMware Observability Domains

The enhanced vCenter MCP covers 8 distinct observability domains:

### 1. Appliance Health & System Metrics
Monitor VCSA subsystem health, track version and uptime, and identify system-level issues.
- VCSA CPU, memory, storage, network, and overall health status
- Software version and build information
- System uptime tracking

### 2. Audit & Event Logs
Query vCenter's event stream and audit records for compliance, troubleshooting, and security investigations.
- Filtered event queries by username, event type, and time window
- Structured audit records (vCenter 8.0+)
- Client-side filtering for maximum compatibility

### 3. Active Sessions & Recent Tasks
Monitor ongoing operations and user activity.
- Recent administrative tasks with status, progress, and error details
- Currently authenticated sessions with idle time tracking
- Requires Global.Diagnostics privilege for session listing

### 4. Security & Access Control
Manage and audit RBAC configuration and access policies.
- All defined roles with resolved privilege names
- Global permission assignments (user/group → role mappings)
- ESXi lockdown mode status per host (NORMAL | LOCKDOWN | STRICT)

### 5. Network Observability
Inventory and analyze virtual networks and switching infrastructure.
- All standard port groups, DVS port groups, and opaque networks
- Detailed DVS configuration (port counts, uplinks, MTU, host membership)
- Parent switch mapping for port group relationships

### 6. Capacity Planning & Forecasting
Analyze resource allocation and identify overcommit risks.
- Per-cluster CPU and memory allocation totals
- Datastore fill status thresholds (HEALTHY | WATCH | CRITICAL)
- High-vCPU VM identification for overcommit analysis
- VMware Tools status reporting across the fleet

### 7. Storage Policy & Compliance
Monitor VM storage policy compliance and SPBM configuration.
- Inventory of all VM storage policies (SPBM)
- Non-compliant VMs with policy assignment details
- Policy compliance tracking per VM

### 8. Inventory & Configuration
Get a fleet-wide view of infrastructure resources and hierarchies.
- Datacenter, cluster, host, and VM counts
- VM power state distribution (powered on, off, suspended)
- Datastore and network inventory
- Resource pool allocation details

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

**Session listing returns only current user**
- Requires `Global.Diagnostics` privilege on vCenter
- User account must be explicitly granted this role
- Fallback shows current session only if privilege not available

**ESXi lockdown mode shows errors**
- Endpoint available on vCenter 7.0+
- Host may not support lockdown mode in your vCenter version
- `_safe_get()` returns error dict; agent handles gracefully

**Distributed switch endpoint not found**
- Endpoint path varies slightly by vCenter version (7.0 vs 8.0)
- `list_virtual_networks()` augments DVS info; use that for compatibility
- Fallback to singular paths tried if plural forms fail

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
| Event timestamps | UTC timezone | All times in ISO 8601 format |
| Lockdown mode | Per-host | Not inherited; each ESXi checked individually |

### API Limitations

The vCenter REST API has some limitations vs. SOAP:
- **Triggered alarms:** Not available via REST API (requires SOAP AlarmManager)
- **Real-time performance metrics:** Live CPU/memory % not exposed (vROps required)
- **Custom fields:** Not supported in REST API
- **Advanced scheduling:** Not available for scheduled tasks

### vCenter 9 Compatibility

**⚠️ Known Limitation:** vCenter 9 removed several REST API endpoints that are used by some tools. Use the diagnostic tool to identify which tools will work in your environment:

```bash
source .venv/bin/activate
python scripts/diagnose_vcenter_api.py
```

**vCenter 9 API Status** (confirmed Feb 2026):

| Endpoint Category | Status | Tools Affected |
|---|---|---|
| **Inventory & Capacity** | ✅ Working | `list_vms_health`, `list_esxi_host_health`, `list_datastore_capacity`, `get_capacity_planning_report`, `list_virtual_networks` |
| **Events & Audit** | ❌ Broken | `query_vcenter_events()` — endpoints `/api/vcenter/event`, `/api/vcenter/audit-records` removed |
| **Sessions** | ❌ Broken | `get_active_sessions()` — endpoints `/api/cis/session/list`, `/api/vcenter/session` removed |
| **Tasks** | ❌ Broken | `get_recent_tasks()` — endpoint `/api/cis/tasks` removed |
| **Appliance Health** | ❌ Broken | `get_vcenter_appliance_health()` — most `/api/appliance/health/*` endpoints removed |
| **DVS Details** | ⚠️ Deprecated | `get_distributed_switch_details()` — endpoint `/api/vcenter/vds/switch` removed; use `list_virtual_networks()` instead |
| **Authorization** | ✅ Fixed | `list_roles_and_privileges()` — works using plural forms: `/api/vcenter/authorization/roles`, `/api/vcenter/authorization/privileges` |

**Workaround:** The agent gracefully handles 404 responses. For full infrastructure visibility on vCenter 9, use these tools:
- **Inventory:** `list_vms_health`, `list_esxi_host_health`, `list_datastore_capacity`, `list_virtual_networks`
- **Capacity Planning:** `get_capacity_planning_report`, `list_vms_with_high_cpu_allocation`, `get_vmtools_status_report`
- **Configuration:** `get_vcenter_inventory_summary`, `list_resource_pools`, `list_storage_policies`, `get_storage_policy_compliance`
- **Security & RBAC:** `list_roles_and_privileges`, `list_global_permissions`, `check_host_lockdown_mode`

**Report Issues:** If you find other broken endpoints or API paths, run the diagnostic tool and file an issue with the output and your vCenter version.

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

3. **Test locally** before building Docker image

### File Locations

- **vCenter tools:** `src/noc_managers/mcp_servers/vcenter.py` (1650 lines, 27 tools)
- **SolarWinds tools:** `src/noc_managers/mcp_servers/solarwinds.py` (2 tools)
- **Agent & UI:** `src/noc_managers/app.py` (190 lines)
- **Dependency config:** `pyproject.toml` (hatchling build backend)
- **Container config:** `Dockerfile`, `docker-compose.yml`
