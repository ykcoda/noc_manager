import os
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("vcenter-monitoring")
_IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

_VC_HOSTNAME = os.getenv("VC_HOSTNAME", "")
_VC_USERNAME = os.getenv("VC_USERNAME", "")
_VC_PASSWORD = os.getenv("VC_PASSWORD", "")


@contextmanager
def _vcenter_session():
    """
    Context manager that authenticates to the vCenter REST API and yields an
    httpx.Client pre-configured with the vmware-api-session-id header.

    Uses POST /api/session (Basic Auth) to obtain a session token, then
    deletes the session on exit to avoid leaking server-side sessions.
    """
    base_url = f"https://{_VC_HOSTNAME}"
    with httpx.Client(base_url=base_url, verify=False) as client:
        auth_resp = client.post("/api/session", auth=(_VC_USERNAME, _VC_PASSWORD))
        auth_resp.raise_for_status()
        token: str = auth_resp.json()
        client.headers.update({"vmware-api-session-id": token})
        try:
            yield client
        finally:
            client.delete("/api/session")


# ── Existing tools ─────────────────────────────────────────────────────────────

@mcp.tool()
def list_vms_health() -> list:
    """
    Returns health summary for all VMs visible to the authenticated vCenter user
    via the vCenter REST API (GET /api/vcenter/vm).

    Each record contains:
      - name: VM display name
      - power_state: POWERED_ON | POWERED_OFF | SUSPENDED
      - cpu_count: number of vCPUs
      - memory_size_mib: allocated RAM in MiB
      - vm_id: vSphere managed object reference (e.g. 'vm-42')
    """
    with _vcenter_session() as client:
        resp = client.get("/api/vcenter/vm")
        resp.raise_for_status()
        vms = resp.json()

    return [
        {
            "name": vm.get("name"),
            "power_state": vm.get("power_state"),
            "cpu_count": vm.get("cpu_count"),
            "memory_size_mib": vm.get("memory_size_MiB"),
            "vm_id": vm.get("vm"),
        }
        for vm in vms
    ]


@mcp.tool()
def list_esxi_host_health() -> list:
    """
    Returns health summary for all ESXi hosts visible in vCenter
    via the vCenter REST API (GET /api/vcenter/host).

    Each record contains:
      - name: Host display name
      - connection_state: CONNECTED | DISCONNECTED | NOT_RESPONDING
      - power_state: POWERED_ON | POWERED_OFF | STANDBY
      - host_id: vSphere managed object reference (e.g. 'host-23')
    """
    with _vcenter_session() as client:
        resp = client.get("/api/vcenter/host")
        resp.raise_for_status()
        hosts = resp.json()

    return [
        {
            "name": host.get("name"),
            "connection_state": host.get("connection_state"),
            "power_state": host.get("power_state"),
            "host_id": host.get("host"),
        }
        for host in hosts
    ]


@mcp.tool()
def list_datastore_capacity() -> list:
    """
    Returns capacity and free-space information for all datastores in vCenter
    via the vCenter REST API (GET /api/vcenter/datastore).

    Each record contains:
      - name: Datastore display name
      - type: VMFS | NFS | NFS41 | VSAN | VMFS_DISTRIBUTED
      - capacity_gb: total capacity in GB (rounded to 2 decimal places)
      - free_space_gb: available free space in GB (rounded to 2 decimal places)
      - datastore_id: vSphere managed object reference (e.g. 'datastore-18')
    """
    with _vcenter_session() as client:
        resp = client.get("/api/vcenter/datastore")
        resp.raise_for_status()
        datastores = resp.json()

    result = []
    for ds in datastores:
        capacity = ds.get("capacity", 0) or 0
        free_space = ds.get("free_space", 0) or 0
        result.append(
            {
                "name": ds.get("name"),
                "type": ds.get("type"),
                "capacity_gb": round(capacity / (1024**3), 2),
                "free_space_gb": round(free_space / (1024**3), 2),
                "datastore_id": ds.get("datastore"),
            }
        )
    return result


@mcp.tool()
def get_recent_alarms_and_events(max_alarms: int = 50, max_events: int = 50) -> dict:
    """
    Fetches recently triggered alarms and system events from vCenter
    via the vCenter REST API.

    Endpoints used:
      - GET /api/vcenter/alarm          -> active triggered alarms
      - GET /api/vcenter/event-log      -> recent system event log entries

    Args:
      max_alarms: maximum alarm records to return (default 50)
      max_events: maximum event log entries to return (default 50)

    Returns a dict with keys 'alarms' and 'events', each a list of dicts.
    """
    with _vcenter_session() as client:
        alarms_raw: list = []
        try:
            alarms_resp = client.get(
                "/api/vcenter/alarm",
                params={"page_size": max_alarms},
            )
            alarms_resp.raise_for_status()
            payload = alarms_resp.json()
            alarms_raw = payload if isinstance(payload, list) else payload.get("value", [])
        except httpx.HTTPStatusError as exc:
            alarms_raw = [{"error": str(exc)}]

        events_raw: list = []
        try:
            events_resp = client.get(
                "/api/vcenter/event-log",
                params={"size": max_events},
            )
            events_resp.raise_for_status()
            payload = events_resp.json()
            events_raw = payload if isinstance(payload, list) else payload.get("value", [])
        except httpx.HTTPStatusError as exc:
            events_raw = [{"error": str(exc)}]

    return {"alarms": alarms_raw, "events": events_raw}


# ── New tools ──────────────────────────────────────────────────────────────────

@mcp.tool()
def get_vm_details(identifier: str) -> dict:
    """
    Returns detailed configuration and guest information for a single VM,
    looked up by display name (exact or partial match) or guest IP address.

    Searches by exact name first, then falls back to a case-insensitive
    partial name match. If the identifier looks like an IP address, it is
    matched against guest-reported IPs (requires VMware Tools to be running).

    Args:
      identifier: VM display name (exact or partial) or guest IP address

    Returns hardware config, NIC list, disk list, and guest OS details.
    """
    is_ip = bool(_IP_RE.match(identifier.strip()))

    with _vcenter_session() as client:
        matches: list = []

        if is_ip:
            # IP lookup: scan all VMs and match against guest-reported IPs.
            # Requires VMware Tools to be running inside the VM.
            all_resp = client.get("/api/vcenter/vm")
            all_resp.raise_for_status()
            for vm in all_resp.json():
                vm_id = vm.get("vm")
                try:
                    gi_resp = client.get(
                        f"/api/vcenter/vm/{vm_id}/guest/networking/interfaces"
                    )
                    if gi_resp.status_code != 200:
                        continue
                    for iface in gi_resp.json():
                        ips = [
                            ip.get("ip_address")
                            for ip in iface.get("ip", {}).get("ip_addresses", [])
                        ]
                        if identifier in ips:
                            matches = [vm]
                            break
                except Exception:
                    continue
                if matches:
                    break
        else:
            # Name lookup: exact match via API filter first
            name_resp = client.get("/api/vcenter/vm", params={"filter.names": identifier})
            if name_resp.status_code == 200:
                matches = name_resp.json()

            if not matches:
                # Partial name fallback
                all_resp = client.get("/api/vcenter/vm")
                all_resp.raise_for_status()
                matches = [
                    v for v in all_resp.json()
                    if identifier.lower() in v.get("name", "").lower()
                ]

        if not matches:
            return {"error": f"No VM found matching '{identifier}'"}

        vm_id = matches[0].get("vm")
        detail_resp = client.get(f"/api/vcenter/vm/{vm_id}")
        detail_resp.raise_for_status()
        detail = detail_resp.json()

        # Guest network interfaces (IP addresses) — requires VMware Tools
        guest_interfaces: list = []
        try:
            gi_resp = client.get(f"/api/vcenter/vm/{vm_id}/guest/networking/interfaces")
            if gi_resp.status_code == 200:
                for iface in gi_resp.json():
                    guest_interfaces.append({
                        "mac": iface.get("mac_address"),
                        "ip_addresses": [
                            ip.get("ip_address")
                            for ip in iface.get("ip", {}).get("ip_addresses", [])
                        ],
                    })
        except Exception:
            pass

        nics = detail.get("nics", {})
        disks = detail.get("disks", {})

        return {
            "vm_id": vm_id,
            "name": detail.get("name"),
            "power_state": detail.get("power_state"),
            "guest_os": detail.get("guest_OS"),
            "cpu_count": detail.get("cpu", {}).get("count"),
            "memory_size_mib": detail.get("memory", {}).get("size_MiB"),
            "hardware_version": detail.get("hardware", {}).get("version"),
            "nics": [
                {
                    "label": nic.get("label"),
                    "mac_address": nic.get("mac_address"),
                    "state": nic.get("state"),
                    "type": nic.get("type"),
                }
                for nic in (nics.values() if isinstance(nics, dict) else nics)
            ],
            "disks": [
                {
                    "label": disk.get("label"),
                    "capacity_gb": round(disk.get("capacity", 0) / (1024**3), 2),
                    "type": disk.get("backing", {}).get("type"),
                }
                for disk in (disks.values() if isinstance(disks, dict) else disks)
            ],
            "guest_ip_addresses": guest_interfaces,
        }


@mcp.tool()
def list_vm_snapshots(max_age_days: int = 0) -> list:
    """
    Lists VMs that currently have one or more snapshots.

    Iterates all VMs and queries the snapshot tree for each. VMs without
    snapshots are omitted from the result.

    Args:
      max_age_days: when > 0, only include snapshots older than this many days
                    (useful to surface forgotten or stale snapshots)

    Each record contains: vm_name, vm_id, snapshot_count, snapshots list
    (name, description, create_time, state per snapshot).
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=max_age_days)
        if max_age_days > 0
        else None
    )

    with _vcenter_session() as client:
        vms_resp = client.get("/api/vcenter/vm")
        vms_resp.raise_for_status()
        vms = vms_resp.json()

        result = []
        for vm in vms:
            vm_id = vm.get("vm")
            try:
                snap_resp = client.get(f"/api/vcenter/vm/{vm_id}/snapshot")
                if snap_resp.status_code != 200:
                    continue

                payload = snap_resp.json()
                snapshots = payload if isinstance(payload, list) else payload.get("snapshots", [])

                if cutoff:
                    def _parse(ts: str) -> datetime:
                        return datetime.fromisoformat(ts.replace("Z", "+00:00"))

                    snapshots = [
                        s for s in snapshots
                        if s.get("create_time") and _parse(s["create_time"]) < cutoff
                    ]

                if not snapshots:
                    continue

                result.append({
                    "vm_name": vm.get("name"),
                    "vm_id": vm_id,
                    "snapshot_count": len(snapshots),
                    "snapshots": [
                        {
                            "name": s.get("name"),
                            "description": s.get("description", ""),
                            "create_time": s.get("create_time"),
                            "state": s.get("state"),
                        }
                        for s in snapshots
                    ],
                })
            except Exception:
                continue

    return result


@mcp.tool()
def get_cluster_resource_usage() -> list:
    """
    Returns HA/DRS configuration and resource pool allocation for all clusters
    in vCenter.

    Each record contains: name, cluster_id, ha_enabled, drs_enabled, and
    optional cpu/memory allocation stats from the cluster's root resource pool.
    """
    with _vcenter_session() as client:
        clusters_resp = client.get("/api/vcenter/cluster")
        clusters_resp.raise_for_status()
        clusters = clusters_resp.json()

        result = []
        for cluster in clusters:
            cluster_id = cluster.get("cluster")
            entry: dict = {
                "name": cluster.get("name"),
                "cluster_id": cluster_id,
                "ha_enabled": cluster.get("ha_enabled"),
                "drs_enabled": cluster.get("drs_enabled"),
            }

            # Fetch root resource pool for CPU/memory allocation stats
            try:
                rp_resp = client.get(
                    "/api/vcenter/resource-pool",
                    params={"filter.clusters": cluster_id},
                )
                if rp_resp.status_code == 200:
                    rps = rp_resp.json()
                    if rps:
                        rp_id = rps[0].get("resource_pool")
                        rp_detail_resp = client.get(f"/api/vcenter/resource-pool/{rp_id}")
                        if rp_detail_resp.status_code == 200:
                            rp = rp_detail_resp.json()
                            entry["cpu_allocation"] = rp.get("cpu", {})
                            entry["memory_allocation"] = rp.get("memory", {})
            except Exception:
                pass

            result.append(entry)

    return result


@mcp.tool()
def list_vms_with_network_issues() -> list:
    """
    Returns powered-on VMs that have one or more NICs in a non-CONNECTED state
    (e.g. NOT_CONNECTED or DISCONNECTED).

    Useful for detecting VMs that have lost network connectivity or were
    provisioned with a disconnected adapter.

    Each record contains: vm_name, vm_id, and a list of problematic NIC details.
    """
    with _vcenter_session() as client:
        vms_resp = client.get("/api/vcenter/vm")
        vms_resp.raise_for_status()
        all_vms = vms_resp.json()
        # Filter client-side — server-side filter.power_states varies by vCenter version
        vms = [v for v in all_vms if v.get("power_state") == "POWERED_ON"]

        result = []
        for vm in vms:
            vm_id = vm.get("vm")
            try:
                detail_resp = client.get(f"/api/vcenter/vm/{vm_id}")
                if detail_resp.status_code != 200:
                    continue
                detail = detail_resp.json()

                nics = detail.get("nics", {})
                nic_list = list(nics.values()) if isinstance(nics, dict) else nics
                problematic = [
                    {
                        "label": nic.get("label"),
                        "state": nic.get("state"),
                        "mac_address": nic.get("mac_address"),
                        "backing_type": nic.get("backing", {}).get("type"),
                    }
                    for nic in nic_list
                    if nic.get("state") != "CONNECTED"
                ]

                if problematic:
                    result.append({
                        "vm_name": vm.get("name"),
                        "vm_id": vm_id,
                        "problematic_nics": problematic,
                    })
            except Exception:
                continue

    return result


@mcp.tool()
def check_vcenter_certificate_expiry() -> dict:
    """
    Returns the expiry date and health status of the vCenter TLS certificate.

    Uses GET /api/vcenter/certificate-management/vcenter/tls (vCenter 7.0+).

    Status field:
      - OK       : more than 90 days remaining
      - WARNING  : 30–90 days remaining
      - CRITICAL : fewer than 30 days remaining
    """
    with _vcenter_session() as client:
        cert_resp = client.get("/api/vcenter/certificate-management/vcenter/tls")
        cert_resp.raise_for_status()
        cert = cert_resp.json()

    valid_to = cert.get("valid_to")
    days_remaining: int | None = None

    if valid_to:
        expiry = datetime.fromisoformat(valid_to.replace("Z", "+00:00"))
        days_remaining = (expiry - datetime.now(timezone.utc)).days

    if days_remaining is None:
        status = "UNKNOWN"
    elif days_remaining < 30:
        status = "CRITICAL"
    elif days_remaining < 90:
        status = "WARNING"
    else:
        status = "OK"

    return {
        "subject_dn": cert.get("subject_dn"),
        "issuer_dn": cert.get("issuer_dn"),
        "valid_from": cert.get("valid_from"),
        "valid_to": valid_to,
        "days_remaining": days_remaining,
        "thumbprint": cert.get("thumbprint"),
        "status": status,
    }


@mcp.tool()
def list_powered_off_vms() -> list:
    """
    Returns all VMs currently in POWERED_OFF state.

    Review this list to identify candidates for decommission or cleanup.

    Each record contains: name, vm_id, cpu_count, memory_size_mib, guest_os.
    """
    with _vcenter_session() as client:
        resp = client.get("/api/vcenter/vm")
        resp.raise_for_status()
        # Filter client-side — server-side filter.power_states varies by vCenter version
        vms = [v for v in resp.json() if v.get("power_state") == "POWERED_OFF"]

    return [
        {
            "name": vm.get("name"),
            "vm_id": vm.get("vm"),
            "cpu_count": vm.get("cpu_count"),
            "memory_size_mib": vm.get("memory_size_MiB"),
            "guest_os": vm.get("guest_OS"),
        }
        for vm in vms
    ]


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
