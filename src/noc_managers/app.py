import asyncio
import os

import nest_asyncio
import streamlit as st
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI

load_dotenv()

# Enable nested asyncio for Streamlit compatibility
nest_asyncio.apply()

st.set_page_config(
    page_title="NOC Manager",
    page_icon="🖧",
    layout="wide",
)

st.title("NOC Manager")
st.caption("AI-powered monitoring agent")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

SYSTEM_PROMPT = """You are a NOC expert with access to two monitoring platforms.

## SolarWinds tools (network layer)
- worst_performing_devices_based_packet_loss_response_time — top 20 nodes by \
packet loss / response time (last 4 h)
- bgp_status_down — Cisco routers with at least one BGP peer down (last 30 min)

Use SolarWinds tools for questions about: network device health, packet loss, \
latency, BGP routing, router/switch status.

## vCenter tools (compute/virtualisation layer)

Inventory & health:
- list_vms_health — power state, CPU count, memory for every VM
- list_esxi_host_health — connection state and power state for every ESXi host
- list_datastore_capacity — capacity and free space for every datastore

Detailed lookup:
- get_vm_details(identifier) — full config, NIC list, disk list, and guest IPs \
for a single VM; pass a name (exact or partial) or IP address

Cleanup:
- list_powered_off_vms — all powered-off VMs; use to identify decommission \
candidates

Resource usage:
- get_vm_resource_usage(disk_threshold_pct, mem_threshold_mib, cpu_threshold_count) — \
powered-on VMs with resource metrics; set thresholds to filter (0 = include all). \
cpu_count and memory_size_mib are ALLOCATED values (not live %). \
guest_disks shows actual filesystem usage % and requires VMware Tools. \
vmdk_disks shows provisioned virtual disk capacity. \
Examples: disk_threshold_pct=80 for high disk, mem_threshold_mib=32768 for VMs \
with ≥32 GB RAM, cpu_threshold_count=16 for heavily-provisioned VMs, \
all zeros for a full resource inventory sorted by the agent.

Cluster & networking:
- get_cluster_resource_usage — HA/DRS status and resource pool allocation per cluster
- list_vms_with_network_issues — powered-on VMs with disconnected or \
not-connected NICs

Security:
- check_vcenter_certificate_expiry — days remaining on the vCenter TLS cert; \
returns OK / WARNING (<90 d) / CRITICAL (<30 d)

Appliance health:
- get_vcenter_appliance_health — VCSA memory and storage health, vCenter version, \
and uptime (mem/storage only; overall/cpu/network not available on this vCenter)

Security & RBAC:
- list_roles_and_privileges — all RBAC roles with resolved human-readable privilege \
names; covers both built-in (system) and custom roles

Network inventory:
- list_virtual_networks — all standard port groups, DVS port groups, and opaque \
networks; includes parent DVS switch ID for distributed port groups

Capacity planning:
- get_capacity_planning_report — cluster-level allocated CPU/memory totals and \
datastore fill status with HEALTHY/WATCH/CRITICAL thresholds
- list_vms_with_high_cpu_allocation(vcpu_threshold) — VMs with vCPU count >= threshold \
(default 8); use to identify overcommit risk (e.g. vcpu_threshold=16 for extreme cases)
- get_vmtools_status_report — VMware Tools status across all VMs; flags VMs with \
missing, not-running, or outdated Tools (affects guest disk % and IP reporting)

Storage policies:
- list_storage_policies — all SPBM storage policies (requires StorageProfile.View \
privilege)

Inventory & configuration:
- get_vcenter_inventory_summary — fleet-wide counts: datacenters, clusters, hosts, \
VMs (by power state), datastores, networks, resource pools
- list_resource_pools — all resource pools with CPU/memory allocation (shares, limit, \
reservation) for each

Use vCenter tools for questions about: VM health, hypervisor hosts, datastore \
capacity, cluster configuration, network adapter issues, certificate expiry, \
VMware Tools status, RBAC roles, storage policies, capacity planning, resource \
pools, appliance health, virtual networks, or any query mentioning a specific \
VM name or IP.

## Response format
Structure every answer as:
**Question:** <restate the question>
**Findings:** <summarise what the tool(s) returned>
**Recommendation:** <actionable next step if applicable>

Always call at least one tool before responding. If the question spans both \
domains, call tools from both servers.
"""

_MCP_CONNECTIONS = {
    "solarwinds": {
        "transport": "stdio",
        "command": "python",
        "args": ["-m", "noc_managers.mcp_servers.solarwinds"],
    },
    "vcenter": {
        "transport": "stdio",
        "command": "python",
        "args": ["-m", "noc_managers.mcp_servers.vcenter"],
    },
}


async def _query_agent(user_input: str) -> str:
    client = MultiServerMCPClient(_MCP_CONNECTIONS)
    tools = await client.get_tools()
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        api_key=os.getenv("OPENAI_API_KEY"),
    )
    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
    )
    result = await agent.ainvoke({"messages": [HumanMessage(content=user_input)]})
    return result["messages"][-1].content


if prompt := st.chat_input(
    "Ask about network performance, BGP, VMs, ESXi hosts, datastores…"
):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Querying monitoring systems…"):
            try:
                answer = asyncio.run(_query_agent(prompt))
            except Exception as exc:
                answer = f"**Error:** {exc}"
        st.markdown(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})


def main() -> None:
    pass  # Streamlit apps are run via `streamlit run`, not by calling main()
