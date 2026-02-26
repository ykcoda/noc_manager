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


def _safe_get(client: httpx.Client, path: str, params: dict | None = None) -> dict:
    """
    Issue a GET request and return the parsed JSON body.
    Returns a structured error dict instead of raising on 4xx/5xx or
    network failures. Used for endpoints that are optional or may not
    exist in all vCenter versions.

    Args:
      client: authenticated httpx.Client from _vcenter_session()
      path:   API path, e.g. '/api/appliance/health/mem'
      params: optional query parameters dict

    Returns:
      Parsed JSON (dict or list wrapped in {"value": ...}) on success,
      or {"error": <message>, "status_code": <int>} on HTTP errors,
      or {"error": <message>, "status_code": None} on connection errors.
    """
    try:
        resp = client.get(path, params=params or {})
        if resp.status_code in (404, 403, 501):
            return {
                "error": f"Endpoint not available: {path}",
                "status_code": resp.status_code,
            }
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        return {"error": str(exc), "status_code": exc.response.status_code}
    except Exception as exc:
        return {"error": str(exc), "status_code": None}


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
def get_recent_alarms_and_events(max_events: int = 50) -> dict:
    """
    Fetches recent events from vCenter via the REST API.

    NOTE: Triggered alarms (active conditions) are not available via the vCenter REST API;
    they require the SOAP AlarmManager API. This tool returns events only.
    Use query_vcenter_events() for filtered event queries and get_recent_tasks() for
    administrative task history.

    Endpoint used:
      - GET /api/vcenter/event  -> recent system event log entries (vCenter 7.0+)

    Args:
      max_events: maximum event log entries to return (default 50)

    Returns a dict with:
      - 'events': list of recent event objects
      - 'note': explanation that alarms require SOAP API
    """
    with _vcenter_session() as client:
        events_raw: list = []
        try:
            events_resp = client.get(
                "/api/vcenter/event",
                params={"size": max_events},
            )
            events_resp.raise_for_status()
            payload = events_resp.json()
            events_raw = payload if isinstance(payload, list) else payload.get("value", [])
        except httpx.HTTPStatusError as exc:
            events_raw = [{"error": f"Failed to fetch events: {exc}"}]

    return {
        "events": events_raw[:max_events],
        "note": "Triggered alarms are not available via REST API (SOAP AlarmManager required). Use query_vcenter_events() for filtered queries.",
    }


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
    if not identifier or not identifier.strip():
        return {"error": "identifier parameter is required and cannot be empty"}

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
    # Validate max_age_days
    if max_age_days < 0:
        max_age_days = 0

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


@mcp.tool()
def get_vm_resource_usage(
    disk_threshold_pct: int = 0,
    mem_threshold_mib: int = 0,
    cpu_threshold_count: int = 0,
) -> list:
    """
    Returns powered-on VMs with their resource allocation and guest disk usage.

    CPU and memory values reflect ALLOCATED (configured) resources, not live
    utilisation percentages — the vCenter REST API does not expose real-time
    CPU/memory consumption directly.

    Guest disk usage (used_pct per filesystem) is the actual in-guest view and
    requires VMware Tools to be running inside the VM. VMs without Tools will
    show an empty 'guest_disks' list.

    VMDK disks show the provisioned virtual disk capacity (not guest usage).

    Args:
      disk_threshold_pct : include VMs with at least one filesystem >= this %
                           used (0 = include all, regardless of disk usage)
      mem_threshold_mib  : include VMs with allocated RAM >= this value in MiB
                           (0 = include all)
      cpu_threshold_count: include VMs with vCPU count >= this value
                           (0 = include all)

    When multiple thresholds are set, a VM is included if it matches ANY of them.
    Set all to 0 to return all powered-on VMs with full resource details.

    Each record contains:
      - name, vm_id
      - cpu_count       : allocated vCPUs
      - memory_size_mib : allocated RAM in MiB
      - vmdk_disks      : list of virtual disks with provisioned capacity in GB
      - guest_disks     : list of guest filesystems with used_pct (requires VMware Tools)
    """
    # Validate thresholds
    disk_threshold_pct = max(0, disk_threshold_pct)
    mem_threshold_mib = max(0, mem_threshold_mib)
    cpu_threshold_count = max(0, cpu_threshold_count)

    with _vcenter_session() as client:
        vms_resp = client.get("/api/vcenter/vm")
        vms_resp.raise_for_status()
        powered_on = [v for v in vms_resp.json() if v.get("power_state") == "POWERED_ON"]

        results = []
        for vm in powered_on:
            vm_id = vm["vm"]
            cpu_count = vm.get("cpu_count") or 0
            mem_mib = vm.get("memory_size_MiB") or 0

            entry: dict = {
                "name": vm.get("name"),
                "vm_id": vm_id,
                "cpu_count": cpu_count,
                "memory_size_mib": mem_mib,
                "vmdk_disks": [],
                "guest_disks": [],
            }

            # VMDK provisioned capacity from detailed VM config
            try:
                detail_resp = client.get(f"/api/vcenter/vm/{vm_id}")
                if detail_resp.status_code == 200:
                    disks = detail_resp.json().get("disks", {})
                    disk_list = list(disks.values()) if isinstance(disks, dict) else disks
                    entry["vmdk_disks"] = [
                        {
                            "label": d.get("label"),
                            "capacity_gb": round((d.get("capacity") or 0) / (1024**3), 2),
                        }
                        for d in disk_list
                    ]
            except Exception:
                pass

            # Guest filesystem usage — requires VMware Tools
            try:
                fs_resp = client.get(f"/api/vcenter/vm/{vm_id}/guest/local-filesystem")
                if fs_resp.status_code == 200:
                    filesystems = fs_resp.json()
                    # Endpoint returns a list of filesystem objects
                    guest_disks = []
                    fs_list = filesystems if isinstance(filesystems, list) else filesystems.get("value", [])
                    for fs in fs_list:
                        cap = fs.get("capacity") or 0
                        free = fs.get("free_space") or 0
                        used_pct = round((cap - free) / cap * 100, 1) if cap > 0 else 0.0
                        guest_disks.append(
                            {
                                "mount_point": fs.get("mount_point"),
                                "capacity_gb": round(cap / (1024**3), 2),
                                "free_gb": round(free / (1024**3), 2),
                                "used_pct": used_pct,
                            }
                        )
                    entry["guest_disks"] = guest_disks
            except Exception:
                pass

            # Threshold filtering: include if any threshold is exceeded or all are 0
            if disk_threshold_pct == 0 and mem_threshold_mib == 0 and cpu_threshold_count == 0:
                results.append(entry)
                continue

            include = False
            if cpu_threshold_count > 0 and cpu_count >= cpu_threshold_count:
                include = True
            if mem_threshold_mib > 0 and mem_mib >= mem_threshold_mib:
                include = True
            if disk_threshold_pct > 0 and any(
                d["used_pct"] >= disk_threshold_pct for d in entry["guest_disks"]
            ):
                include = True

            if include:
                results.append(entry)

    return results


# ── Domain 1: vCenter Appliance Health & System Metrics ──────────────────────────


@mcp.tool()
def get_vcenter_appliance_health() -> dict:
    """
    Returns health status for all VCSA appliance subsystems, software version,
    and uptime.

    Endpoints used (all under /api/appliance — available on vCenter 7.0+ VCSA only):
      GET /api/appliance/health/mem     — memory subsystem health
      GET /api/appliance/health/cpu     — CPU subsystem health
      GET /api/appliance/health/storage — storage subsystem health
      GET /api/appliance/health/network — network subsystem health
      GET /api/appliance/health/overall — aggregate health status
      GET /api/appliance/system/version — build, product, type, release date
      GET /api/appliance/system/uptime  — uptime in seconds (integer)

    Each health endpoint returns one of: green | yellow | orange | red | unknown | gray

    Returns a dict with keys: mem, cpu, storage, network, overall
    (each with a 'health' string), plus 'version' (dict) and
    'uptime_seconds' (int or None).

    Returns {"error": ..., "status_code": ...} for individual endpoints
    that are unavailable; other subsystems are still populated.
    """
    with _vcenter_session() as client:
        return {
            "health": {
                "mem": _safe_get(client, "/api/appliance/health/mem"),
                "cpu": _safe_get(client, "/api/appliance/health/cpu"),
                "storage": _safe_get(client, "/api/appliance/health/storage"),
                "network": _safe_get(client, "/api/appliance/health/network"),
                "overall": _safe_get(client, "/api/appliance/health/overall"),
            },
            "version": _safe_get(client, "/api/appliance/system/version"),
            "uptime_seconds": _safe_get(client, "/api/appliance/system/uptime"),
        }


# ── Domain 2: Audit & Event Logs ─────────────────────────────────────────────────


@mcp.tool()
def query_vcenter_events(
    user_filter: str = "",
    event_type_filter: str = "",
    hours_back: int = 24,
    max_results: int = 100,
) -> dict:
    """
    Filtered query of the vCenter event stream and (on vCenter 8.0+)
    structured audit records.

    Endpoints used:
      GET /api/vcenter/event
          Query params: filter.user_name, filter.types, filter.time.start,
                        filter.time.end (ISO 8601 UTC)
      GET /api/vcenter/audit-records   (vCenter 8.0+ only; 404 on 7.x)

    Args:
      user_filter:       Filter events by username substring (case-insensitive
                         match applied client-side after fetch; server accepts
                         exact principal names only).
      event_type_filter: Filter events where the type field contains this
                         string (e.g. 'VmPoweredOnEvent', 'UserLoginSessionEvent').
                         Applied client-side.
      hours_back:        Return events from this many hours ago until now
                         (default 24, max recommended 168 to avoid timeouts).
      max_results:       Maximum total events to return (default 100).

    Returns a dict with:
      - 'events': list of event dicts (type, created_time, user_name, message)
      - 'audit_records': list from /api/vcenter/audit-records, or
                         {"error": ..., "status_code": 404} on vCenter 7.x
      - 'filter_applied': dict summarising the filters used
    """
    # Validate hours_back
    hours_back = max(1, min(hours_back, 168))  # Clamp to 1-168 hours

    start_time = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    start_time_str = start_time.isoformat().replace("+00:00", "Z")

    params = {"filter.time.start": start_time_str}
    if user_filter:
        params["filter.user_name"] = user_filter

    with _vcenter_session() as client:
        # Fetch events
        events_resp = _safe_get(client, "/api/vcenter/event", params=params)
        if isinstance(events_resp, dict) and "error" in events_resp:
            events = []
        else:
            events = (
                events_resp
                if isinstance(events_resp, list)
                else events_resp.get("value", [])
            )

        # Apply client-side filters
        filtered_events = []
        for event in events:
            if event_type_filter and event_type_filter.lower() not in event.get(
                "type", ""
            ).lower():
                continue
            if user_filter and user_filter.lower() not in event.get("user_name", "").lower():
                continue
            filtered_events.append(event)

        filtered_events = filtered_events[:max_results]

        # Fetch audit records (vCenter 8.0+)
        audit_records_resp = _safe_get(client, "/api/vcenter/audit-records")
        if isinstance(audit_records_resp, dict) and "error" in audit_records_resp:
            audit_records = audit_records_resp
        else:
            audit_records = (
                audit_records_resp
                if isinstance(audit_records_resp, list)
                else audit_records_resp.get("value", [])
            )

    return {
        "events": filtered_events,
        "audit_records": audit_records,
        "filter_applied": {
            "user_filter": user_filter,
            "event_type_filter": event_type_filter,
            "hours_back": hours_back,
            "max_results": max_results,
            "start_time": start_time_str,
        },
    }


# ── Domain 3: Active Sessions & Recent Tasks ─────────────────────────────────────


@mcp.tool()
def get_recent_tasks(
    max_tasks: int = 50,
    include_completed: bool = True,
) -> list:
    """
    Returns recent administrative tasks from the vCenter task manager.

    Endpoint used:
      GET /api/cis/tasks
          Query params: filter.tasks.status (RUNNING | SUCCEEDED | FAILED | BLOCKED)

    Args:
      max_tasks:          Maximum number of tasks to return (default 50).
      include_completed:  When True, include SUCCEEDED and FAILED tasks.
                          When False, return only RUNNING and BLOCKED tasks.

    Each record contains:
      - task_id, status, description, progress (0–100),
        start_time, end_time, error (if failed), target (object the task acted on)

    Returns an empty list if the endpoint is unavailable (404/403).
    """
    with _vcenter_session() as client:
        tasks_resp = _safe_get(client, "/api/cis/tasks")

        if isinstance(tasks_resp, dict) and "error" in tasks_resp:
            return []

        # /api/cis/tasks returns dict keyed by task ID
        if isinstance(tasks_resp, dict):
            result = [{"task_id": k, **v} for k, v in tasks_resp.items()]
        else:
            result = tasks_resp if isinstance(tasks_resp, list) else []

        # Filter by completion status
        if not include_completed:
            result = [t for t in result if t.get("status") in ("RUNNING", "BLOCKED")]

        return result[:max_tasks]


@mcp.tool()
def get_active_sessions() -> list:
    """
    Returns currently authenticated sessions in vCenter.

    Requires the Global.Diagnostics privilege to list all sessions.

    Endpoint used:
      GET /api/cis/session/list (vCenter 7.0+) or
      GET /api/vcenter/session (fallback for current session info)

    Each record contains:
      - user, created_time, last_accessed_time, idle_time_seconds,
        client_address, user_agent

    Returns [{"error": ..., "status_code": 403}] if the authenticated
    user lacks the required Global.Diagnostics privilege.
    """
    with _vcenter_session() as client:
        # Try to list all sessions
        sessions_resp = _safe_get(client, "/api/cis/session/list")

        # Fallback to current session info if listing fails
        if isinstance(sessions_resp, dict) and "error" in sessions_resp:
            sessions_resp = _safe_get(client, "/api/vcenter/session")

        if isinstance(sessions_resp, dict) and "error" in sessions_resp:
            return [sessions_resp]

        sessions = (
            sessions_resp
            if isinstance(sessions_resp, list)
            else sessions_resp.get("value", [])
        )

        return sessions


# ── Domain 4: Security & Access Control (RBAC) ───────────────────────────────────


@mcp.tool()
def list_roles_and_privileges() -> list:
    """
    Returns all RBAC roles defined in vCenter, each annotated with its
    assigned privileges.

    Endpoints used:
      GET /api/vcenter/authorization/role      — all roles (id, name, system)
      GET /api/vcenter/authorization/privilege — all privileges (id, name, group)

    The roles endpoint returns a list of role objects. Each role contains a
    'privileges' list of privilege IDs. The privileges endpoint provides
    human-readable names for those IDs.

    Returns a list of dicts, each with:
      - role_id, name, system (bool — True for built-in VMware roles),
        privilege_count, privilege_names (list of human-readable names)

    Returns [{"error": ..., "status_code": ...}] if endpoint unavailable.
    """
    with _vcenter_session() as client:
        # Fetch privileges and build lookup map — try plural first, fallback to singular
        privs_resp = _safe_get(client, "/api/vcenter/authorization/privileges")
        if isinstance(privs_resp, dict) and "error" in privs_resp:
            privs_resp = _safe_get(client, "/api/vcenter/authorization/privilege")

        priv_map = {}
        if not (isinstance(privs_resp, dict) and "error" in privs_resp):
            privs_list = (
                privs_resp
                if isinstance(privs_resp, list)
                else privs_resp.get("value", [])
            )
            priv_map = {p.get("privilege"): p.get("name", "") for p in privs_list}

        # Fetch roles — try plural first, fallback to singular
        roles_resp = _safe_get(client, "/api/vcenter/authorization/roles")
        if isinstance(roles_resp, dict) and "error" in roles_resp:
            roles_resp = _safe_get(client, "/api/vcenter/authorization/role")

        if isinstance(roles_resp, dict) and "error" in roles_resp:
            return [roles_resp]

        roles_list = (
            roles_resp if isinstance(roles_resp, list) else roles_resp.get("value", [])
        )

        result = []
        for role in roles_list:
            privilege_ids = role.get("privileges", [])
            privilege_names = [
                priv_map.get(pid, pid) for pid in privilege_ids
            ]
            result.append(
                {
                    "role_id": role.get("role"),
                    "name": role.get("name"),
                    "system": role.get("system", False),
                    "privilege_count": len(privilege_ids),
                    "privilege_names": privilege_names,
                }
            )

        return result


@mcp.tool()
def list_global_permissions() -> list:
    """
    Returns global permission assignments in vCenter (user or group → role
    assignments at the root level of the inventory hierarchy).

    Endpoints used:
      GET /api/vcenter/authorization/global-access
          or
      GET /api/vcenter/authorization/global-role-assignments
          (endpoint path varies by vCenter version; both are tried)

    Each record contains:
      - principal (user or group name), role_id, propagate (bool),
        principal_type (USER | GROUP)

    Returns [{"error": ..., "status_code": ...}] if both endpoints return
    4xx (e.g. insufficient privileges or older vCenter API).
    """
    with _vcenter_session() as client:
        # Try first endpoint
        perms_resp = _safe_get(client, "/api/vcenter/authorization/global-access")

        # Fallback to second endpoint if first failed
        if isinstance(perms_resp, dict) and "error" in perms_resp:
            perms_resp = _safe_get(
                client, "/api/vcenter/authorization/global-role-assignments"
            )

        if isinstance(perms_resp, dict) and "error" in perms_resp:
            return [perms_resp]

        perms_list = (
            perms_resp
            if isinstance(perms_resp, list)
            else perms_resp.get("value", [])
        )

        return perms_list


@mcp.tool()
def check_host_lockdown_mode() -> list:
    """
    Returns the lockdown mode status for every ESXi host in vCenter.

    Endpoint used:
      GET /api/vcenter/host/{host_id}/lockdown-mode
          (one call per host; vCenter 7.0+)

    Each record contains:
      - host_name, host_id,
        lockdown_mode: NORMAL | STRICT | LOCKDOWN
        (NORMAL means lockdown is disabled; LOCKDOWN and STRICT mean it is enabled)

    Hosts where the endpoint returns 404 (older API) or 403 (no privilege)
    are included with lockdown_mode set to the error string for transparency.
    """
    with _vcenter_session() as client:
        # Get all hosts
        hosts_resp = client.get("/api/vcenter/host")
        hosts_resp.raise_for_status()
        hosts = hosts_resp.json()

        result = []
        for host in hosts:
            host_id = host.get("host")
            host_name = host.get("name")
            lockdown_mode_resp = _safe_get(
                client, f"/api/vcenter/host/{host_id}/lockdown"
            )

            # The endpoint returns a plain string, not a dict
            if isinstance(lockdown_mode_resp, dict) and "error" in lockdown_mode_resp:
                lockdown_mode = lockdown_mode_resp.get("error", "UNKNOWN")
            elif isinstance(lockdown_mode_resp, str):
                lockdown_mode = lockdown_mode_resp
            else:
                lockdown_mode = "UNKNOWN"

            result.append(
                {
                    "host_name": host_name,
                    "host_id": host_id,
                    "lockdown_mode": lockdown_mode,
                }
            )

        return result


# ── Domain 5: Network Observability ──────────────────────────────────────────────


@mcp.tool()
def list_virtual_networks() -> list:
    """
    Returns all virtual networks visible in vCenter, covering both standard
    port groups and Distributed Virtual Switch port groups.

    Endpoint used:
      GET /api/vcenter/network
          Returns standard portgroups, DVS portgroups, and opaque networks.

    Each record contains:
      - name, network_id, type
        (STANDARD_PORTGROUP | DISTRIBUTED_PORTGROUP | OPAQUE_NETWORK)

    The vds/switch endpoint (GET /api/vcenter/vds/switch) is also called to
    augment DVS port groups with their parent switch name when available.
    """
    with _vcenter_session() as client:
        # Fetch networks
        networks_resp = client.get("/api/vcenter/network")
        networks_resp.raise_for_status()
        networks = networks_resp.json()

        # Fetch DVS list to build name map
        dvs_resp = _safe_get(client, "/api/vcenter/vds/switch")
        dvs_map = {}
        if not (isinstance(dvs_resp, dict) and "error" in dvs_resp):
            dvs_list = (
                dvs_resp if isinstance(dvs_resp, list) else dvs_resp.get("value", [])
            )
            dvs_map = {dvs.get("switch"): dvs.get("name", "") for dvs in dvs_list}

        result = []
        for network in networks:
            entry = {
                "name": network.get("name"),
                "network_id": network.get("network"),
                "type": network.get("type"),
            }
            # Add DVS parent name for distributed port groups
            if network.get("type") == "DISTRIBUTED_PORTGROUP":
                dvs_id = network.get("backing", {}).get("switch")
                if dvs_id and dvs_id in dvs_map:
                    entry["dvs_name"] = dvs_map[dvs_id]
            result.append(entry)

        return result


@mcp.tool()
def get_distributed_switch_details(dvs_id: str) -> dict:
    """
    Returns detailed configuration for a single Distributed Virtual Switch.

    Endpoints used:
      GET /api/vcenter/vds/switch/{dvs_id} — detailed config

    Args:
      dvs_id: DVS managed object reference (e.g. 'dvs-15'), obtained from
              the 'network_id' field of list_virtual_networks() for
              DISTRIBUTED_PORTGROUP entries, or from vCenter inventory.

    Returns dict with: dvs_id, name, num_ports, uplink_names, mtu,
    discovery_protocol, num_hosts.

    Returns {"error": ..., "status_code": 404} if dvs_id is not found.
    """
    if not dvs_id or not dvs_id.strip():
        return {"error": "dvs_id parameter is required and cannot be empty", "status_code": None}

    with _vcenter_session() as client:
        dvs_resp = _safe_get(client, f"/api/vcenter/vds/switch/{dvs_id}")

        if isinstance(dvs_resp, dict) and "error" in dvs_resp:
            return dvs_resp

        return {
            "dvs_id": dvs_resp.get("switch"),
            "name": dvs_resp.get("name"),
            "num_ports": dvs_resp.get("num_ports"),
            "uplink_names": dvs_resp.get("uplinks", []),
            "mtu": dvs_resp.get("mtu"),
            "discovery_protocol": dvs_resp.get("discovery_protocol"),
            "num_hosts": len(dvs_resp.get("hosts", [])),
        }


# ── Domain 6: Capacity Planning ──────────────────────────────────────────────────


@mcp.tool()
def get_capacity_planning_report() -> dict:
    """
    Produces a cluster-level capacity planning report using vCenter REST
    inventory data. No vROps or SOAP performance manager is required.

    Data sources (all already used by existing tools — no new session costs):
      GET /api/vcenter/cluster    — cluster list with HA/DRS flags
      GET /api/vcenter/host       — host list for per-cluster host count
      GET /api/vcenter/vm         — VM list for per-cluster vCPU/memory totals
      GET /api/vcenter/datastore  — datastore capacity and free space

    Returns a dict with keys:
      - 'clusters': list of per-cluster dicts containing:
          cluster_id, name, host_count, total_vcpus_allocated,
          total_memory_allocated_mib, memory_overcommit_ratio
      - 'datastores': list with name, capacity_gb, free_space_gb,
          used_pct, fill_rate_note (qualitative: HEALTHY | WATCH | CRITICAL
          based on >80% or >90% used thresholds)
      - 'summary': dict with fleet-wide totals and counts

    NOTE: CPU and memory values represent ALLOCATED (configured) resources.
    Live utilisation is not available via the vCenter REST API without the
    SOAP performance manager or vROps.
    """
    with _vcenter_session() as client:
        # Fetch clusters
        clusters_resp = client.get("/api/vcenter/cluster")
        clusters_resp.raise_for_status()
        clusters = clusters_resp.json()

        # Fetch hosts
        hosts_resp = client.get("/api/vcenter/host")
        hosts_resp.raise_for_status()
        all_hosts = hosts_resp.json()

        # Fetch VMs
        vms_resp = client.get("/api/vcenter/vm")
        vms_resp.raise_for_status()
        all_vms = vms_resp.json()

        # Fetch datastores
        ds_resp = client.get("/api/vcenter/datastore")
        ds_resp.raise_for_status()
        datastores = ds_resp.json()

        # Build cluster report
        cluster_report = []
        for cluster in clusters:
            cluster_id = cluster.get("cluster")

            # Get hosts in this cluster — use equality check, not substring match
            cluster_hosts = [h for h in all_hosts if h.get("cluster") == cluster_id]
            host_count = len(cluster_hosts)

            # Get VMs in this cluster by filtering via cluster ID
            cluster_vms_resp = client.get(
                "/api/vcenter/vm", params={"filter.clusters": cluster_id}
            )
            if cluster_vms_resp.status_code == 200:
                cluster_vms = cluster_vms_resp.json()
            else:
                cluster_vms = []

            total_vcpus = sum(vm.get("cpu_count", 0) for vm in cluster_vms)
            total_memory = sum(vm.get("memory_size_MiB", 0) for vm in cluster_vms)

            cluster_report.append(
                {
                    "cluster_id": cluster_id,
                    "name": cluster.get("name"),
                    "host_count": host_count,
                    "total_vcpus_allocated": total_vcpus,
                    "total_memory_allocated_mib": total_memory,
                    "ha_enabled": cluster.get("ha_enabled"),
                    "drs_enabled": cluster.get("drs_enabled"),
                }
            )

        # Build datastore report
        datastore_report = []
        for ds in datastores:
            capacity = ds.get("capacity", 0) or 0
            free_space = ds.get("free_space", 0) or 0
            used_pct = (
                round((capacity - free_space) / capacity * 100, 1) if capacity > 0 else 0.0
            )

            if used_pct >= 90:
                fill_rate_note = "CRITICAL"
            elif used_pct >= 80:
                fill_rate_note = "WATCH"
            else:
                fill_rate_note = "HEALTHY"

            datastore_report.append(
                {
                    "name": ds.get("name"),
                    "capacity_gb": round(capacity / (1024**3), 2),
                    "free_space_gb": round(free_space / (1024**3), 2),
                    "used_pct": used_pct,
                    "fill_rate_note": fill_rate_note,
                }
            )

        # Build summary
        summary = {
            "cluster_count": len(clusters),
            "host_count": len(all_hosts),
            "vm_count": len(all_vms),
            "datastore_count": len(datastores),
            "total_vcpus_allocated": sum(c["total_vcpus_allocated"] for c in cluster_report),
            "total_memory_allocated_mib": sum(c["total_memory_allocated_mib"] for c in cluster_report),
        }

        return {
            "clusters": cluster_report,
            "datastores": datastore_report,
            "summary": summary,
        }


@mcp.tool()
def list_vms_with_high_cpu_allocation(vcpu_threshold: int = 8) -> list:
    """
    Returns VMs whose vCPU allocation meets or exceeds the given threshold.
    High vCPU counts increase vCPU-to-pCPU overcommit ratios and can
    cause CPU ready contention.

    Data source:
      GET /api/vcenter/vm  — already used by list_vms_health

    Args:
      vcpu_threshold: minimum vCPU count to include (default 8).
                      Common thresholds: 4 (moderate), 8 (high), 16 (extreme).

    Each record contains:
      - name, vm_id, cpu_count, memory_size_mib, power_state
    """
    # Validate vcpu_threshold
    if vcpu_threshold < 0:
        vcpu_threshold = 1

    with _vcenter_session() as client:
        resp = client.get("/api/vcenter/vm")
        resp.raise_for_status()
        vms = resp.json()

        filtered = [vm for vm in vms if vm.get("cpu_count", 0) >= vcpu_threshold]
        filtered.sort(key=lambda v: v.get("cpu_count", 0), reverse=True)

        return [
            {
                "name": vm.get("name"),
                "vm_id": vm.get("vm"),
                "cpu_count": vm.get("cpu_count"),
                "memory_size_mib": vm.get("memory_size_MiB"),
                "power_state": vm.get("power_state"),
            }
            for vm in filtered
        ]


@mcp.tool()
def get_vmtools_status_report() -> dict:
    """
    Returns VMware Tools installation and version status for all VMs.
    VMware Tools must be current for guest introspection features (guest
    disk usage, IP reporting, quiesced snapshots) to work correctly.
    Outdated or missing Tools is also a security concern.

    Endpoint used:
      GET /api/vcenter/vm/{vm_id}/guest/identity
          Returns guest OS info including tools_status and tools_version_status.

    Returns a dict with:
      - 'summary': counts by tools_status (TOOLSOK | TOOLSOLD | TOOLSNOTRUNNING
                   | TOOLSNOTINSTALLED | UNMANAGED)
      - 'vms_needing_attention': list of VMs where tools_status is not TOOLSOK,
          each with: name, vm_id, power_state, tools_status, tools_version_status

    VMs where the /guest/identity endpoint returns 404 or 503 (Tools not running
    or not installed) are included in the 'vms_needing_attention' list.
    """
    with _vcenter_session() as client:
        # Get all VMs
        vms_resp = client.get("/api/vcenter/vm")
        vms_resp.raise_for_status()
        all_vms = vms_resp.json()

        summary = {
            "TOOLSOK": 0,
            "TOOLSOLD": 0,
            "TOOLSNOTRUNNING": 0,
            "TOOLSNOTINSTALLED": 0,
            "UNMANAGED": 0,
        }
        vms_needing_attention = []

        for vm in all_vms:
            vm_id = vm.get("vm")
            identity_resp = _safe_get(client, f"/api/vcenter/vm/{vm_id}/guest/identity")

            if isinstance(identity_resp, dict) and "error" in identity_resp:
                tools_status = "TOOLSNOTRUNNING"
                tools_version_status = "UNKNOWN"
            else:
                tools_status = identity_resp.get("tools_status", "UNMANAGED")
                tools_version_status = identity_resp.get("tools_version_status", "UNKNOWN")

            # Track in summary
            if tools_status in summary:
                summary[tools_status] += 1
            else:
                summary[tools_status] = 1

            # Add to attention list if not OK
            if tools_status != "TOOLSOK":
                vms_needing_attention.append(
                    {
                        "name": vm.get("name"),
                        "vm_id": vm_id,
                        "power_state": vm.get("power_state"),
                        "tools_status": tools_status,
                        "tools_version_status": tools_version_status,
                    }
                )

        return {
            "summary": summary,
            "vms_needing_attention": vms_needing_attention,
        }


# ── Domain 7: Storage Policy & Compliance ────────────────────────────────────────


@mcp.tool()
def list_storage_policies() -> list:
    """
    Returns all VM Storage Policies defined in vCenter (SPBM — Storage
    Policy-Based Management).

    Endpoint used:
      GET /api/vcenter/storage/policies

    Each record contains:
      - policy_id, name, description, resource_type

    Returns [{"error": ..., "status_code": ...}] if the endpoint returns 4xx
    (requires the StorageProfile.View privilege).
    """
    with _vcenter_session() as client:
        policies_resp = _safe_get(client, "/api/vcenter/storage/policies")

        if isinstance(policies_resp, dict) and "error" in policies_resp:
            return [policies_resp]

        policies = (
            policies_resp
            if isinstance(policies_resp, list)
            else policies_resp.get("value", [])
        )

        return policies


@mcp.tool()
def get_storage_policy_compliance() -> dict:
    """
    Returns VMs that are non-compliant with their assigned VM Storage Policy.
    Non-compliant VMs may be at risk of missing storage SLAs (replication,
    encryption, performance tiers).

    Endpoint used:
      GET /api/vcenter/storage/policies/compliance/vm
          Returns compliance status per VM.

    Returns a dict with:
      - 'non_compliant': list of VMs with compliance_status != COMPLIANT,
          each with: vm_id, vm_name (if resolvable), compliance_status,
          policy_id
      - 'compliant_count': int
      - 'non_compliant_count': int
      - 'unknown_count': int (VMs where compliance could not be determined)

    Returns {"error": ..., "status_code": ...} if the endpoint is unavailable.
    """
    with _vcenter_session() as client:
        # Fetch compliance data
        compliance_resp = _safe_get(client, "/api/vcenter/storage/policies/compliance/vm")

        if isinstance(compliance_resp, dict) and "error" in compliance_resp:
            return compliance_resp

        compliance_list = (
            compliance_resp
            if isinstance(compliance_resp, list)
            else compliance_resp.get("value", [])
        )

        # Fetch VM list for name lookup
        vms_resp = client.get("/api/vcenter/vm")
        vms_resp.raise_for_status()
        all_vms = vms_resp.json()
        vm_map = {vm.get("vm"): vm.get("name") for vm in all_vms}

        # Categorize by compliance status
        compliant_count = 0
        non_compliant_count = 0
        unknown_count = 0
        non_compliant_list = []

        for item in compliance_list:
            status = item.get("compliance_status", "UNKNOWN")

            if status == "COMPLIANT":
                compliant_count += 1
            elif status == "NON_COMPLIANT":
                non_compliant_count += 1
                vm_id = item.get("vm")
                non_compliant_list.append(
                    {
                        "vm_id": vm_id,
                        "vm_name": vm_map.get(vm_id, "UNKNOWN"),
                        "compliance_status": status,
                        "policy_id": item.get("policy"),
                    }
                )
            else:
                unknown_count += 1

        return {
            "non_compliant": non_compliant_list,
            "compliant_count": compliant_count,
            "non_compliant_count": non_compliant_count,
            "unknown_count": unknown_count,
        }


# ── Domain 8: Inventory & Configuration ───────────────────────────────────────────


@mcp.tool()
def get_vcenter_inventory_summary() -> dict:
    """
    Returns high-level inventory counts across the vCenter hierarchy.
    Useful for capacity planning and situational awareness.

    Endpoints used:
      GET /api/vcenter/datacenter   — datacenters
      GET /api/vcenter/cluster      — clusters
      GET /api/vcenter/host         — ESXi hosts
      GET /api/vcenter/vm           — VMs (total and by power state)
      GET /api/vcenter/datastore    — datastores
      GET /api/vcenter/network      — port groups and networks
      GET /api/vcenter/resource-pool — resource pools (excluding root pools)

    Returns a dict with:
      - datacenter_count, cluster_count, host_count
      - vm_count_total, vm_count_powered_on, vm_count_powered_off,
        vm_count_suspended
      - datastore_count, network_count, resource_pool_count
    """
    with _vcenter_session() as client:
        # Fetch all inventory endpoints
        dc_resp = client.get("/api/vcenter/datacenter")
        dc_resp.raise_for_status()
        datacenters = dc_resp.json()

        cluster_resp = client.get("/api/vcenter/cluster")
        cluster_resp.raise_for_status()
        clusters = cluster_resp.json()

        host_resp = client.get("/api/vcenter/host")
        host_resp.raise_for_status()
        hosts = host_resp.json()

        vm_resp = client.get("/api/vcenter/vm")
        vm_resp.raise_for_status()
        vms = vm_resp.json()

        ds_resp = client.get("/api/vcenter/datastore")
        ds_resp.raise_for_status()
        datastores = ds_resp.json()

        net_resp = _safe_get(client, "/api/vcenter/network")
        if isinstance(net_resp, dict) and "error" in net_resp:
            networks = []
        else:
            networks = net_resp if isinstance(net_resp, list) else net_resp.get("value", [])

        rp_resp = _safe_get(client, "/api/vcenter/resource-pool")
        if isinstance(rp_resp, dict) and "error" in rp_resp:
            resource_pools = []
        else:
            resource_pools = (
                rp_resp if isinstance(rp_resp, list) else rp_resp.get("value", [])
            )

        # Compute VM power state counts
        vm_powered_on = sum(1 for vm in vms if vm.get("power_state") == "POWERED_ON")
        vm_powered_off = sum(1 for vm in vms if vm.get("power_state") == "POWERED_OFF")
        vm_suspended = sum(1 for vm in vms if vm.get("power_state") == "SUSPENDED")

        return {
            "datacenter_count": len(datacenters),
            "cluster_count": len(clusters),
            "host_count": len(hosts),
            "vm_count_total": len(vms),
            "vm_count_powered_on": vm_powered_on,
            "vm_count_powered_off": vm_powered_off,
            "vm_count_suspended": vm_suspended,
            "datastore_count": len(datastores),
            "network_count": len(networks),
            "resource_pool_count": len(resource_pools),
        }


@mcp.tool()
def list_resource_pools() -> list:
    """
    Returns all resource pools with CPU and memory allocation details.
    Useful for identifying pools that are over- or under-provisioned relative
    to the VMs running within them.

    Endpoints used:
      GET /api/vcenter/resource-pool                  — list all pools
      GET /api/vcenter/resource-pool/{pool_id}        — detail per pool

    Each record contains:
      - resource_pool_id, name, cpu_allocation (shares, limit, reservation),
        memory_allocation (shares, limit, reservation)

    Root resource pools (created automatically per cluster) are included.
    The 'name' field typically distinguishes them ('Resources' for root pools).

    Returns [{"error": ..., "status_code": ...}] if the endpoint returns 4xx.
    """
    with _vcenter_session() as client:
        # Fetch resource pool list
        pools_resp = _safe_get(client, "/api/vcenter/resource-pool")

        if isinstance(pools_resp, dict) and "error" in pools_resp:
            return [pools_resp]

        pools_list = (
            pools_resp if isinstance(pools_resp, list) else pools_resp.get("value", [])
        )

        result = []
        for pool in pools_list:
            pool_id = pool.get("resource_pool")

            # Fetch detailed allocation info
            detail_resp = _safe_get(client, f"/api/vcenter/resource-pool/{pool_id}")

            if isinstance(detail_resp, dict) and "error" in detail_resp:
                cpu_alloc = {}
                mem_alloc = {}
            else:
                cpu_alloc = detail_resp.get("cpu", {})
                mem_alloc = detail_resp.get("memory", {})

            result.append(
                {
                    "resource_pool_id": pool_id,
                    "name": pool.get("name"),
                    "cpu_allocation": cpu_alloc,
                    "memory_allocation": mem_alloc,
                }
            )

        return result


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
