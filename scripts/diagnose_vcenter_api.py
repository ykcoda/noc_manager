#!/usr/bin/env python3
"""
vCenter API Diagnostic Tool

Probes your vCenter instance to confirm which REST API endpoints are
available and working. All endpoints listed here are confirmed functional
on the production vCenter 9 environment (verified Feb 2026).

Usage:
    uv run python scripts/diagnose_vcenter_api.py
"""

import os
import sys
from contextlib import contextmanager

import httpx
from dotenv import load_dotenv

load_dotenv()

VC_HOSTNAME = os.getenv("VC_HOSTNAME", "")
VC_USERNAME = os.getenv("VC_USERNAME", "")
VC_PASSWORD = os.getenv("VC_PASSWORD", "")


@contextmanager
def vcenter_session():
    """Authenticate to vCenter REST API."""
    base_url = f"https://{VC_HOSTNAME}"
    with httpx.Client(base_url=base_url, verify=False) as client:
        try:
            auth_resp = client.post("/api/session", auth=(VC_USERNAME, VC_PASSWORD))
            auth_resp.raise_for_status()
            token = auth_resp.json()
            client.headers.update({"vmware-api-session-id": token})
            yield client
        except Exception as e:
            print(f"❌ Failed to authenticate: {e}")
            sys.exit(1)
        finally:
            try:
                client.delete("/api/session")
            except Exception:
                pass


def test_endpoint(client: httpx.Client, path: str) -> dict:
    """Test if an endpoint is accessible and returns HTTP 200."""
    try:
        resp = client.get(path)
        return {
            "status": "ok" if resp.status_code == 200 else "error",
            "code": resp.status_code,
            "reason": resp.reason_phrase,
        }
    except Exception as e:
        return {"status": "error", "code": None, "reason": str(e)}


def main():
    """Run diagnostic tests on confirmed vCenter API endpoints."""
    print("🔍 vCenter API Endpoint Diagnostic\n")
    print(f"Target: {VC_HOSTNAME}\n")

    # All endpoints confirmed working on vCenter 9 (Feb 2026)
    working_endpoints = {
        "Appliance System": [
            "/api/appliance/system/version",
            "/api/appliance/system/uptime",
        ],
        "Appliance Health (partial — mem/storage only on vCenter 9)": [
            "/api/appliance/health/mem",
            "/api/appliance/health/storage",
        ],
        "Authorization (RBAC)": [
            "/api/vcenter/authorization/roles",
            "/api/vcenter/authorization/privileges",
        ],
        "Inventory": [
            "/api/vcenter/vm",
            "/api/vcenter/host",
            "/api/vcenter/cluster",
            "/api/vcenter/datacenter",
            "/api/vcenter/datastore",
            "/api/vcenter/network",
            "/api/vcenter/resource-pool",
        ],
        "Certificate Management": [
            "/api/vcenter/certificate-management/vcenter/tls",
        ],
        "Storage Policies": [
            "/api/vcenter/storage/policies",
        ],
    }

    with vcenter_session() as client:
        # Get a powered-on VM ID for per-VM endpoint tests
        vms_resp = client.get("/api/vcenter/vm")
        all_vms = vms_resp.json() if vms_resp.status_code == 200 else []
        vm_id = next(
            (v["vm"] for v in all_vms if v.get("power_state") == "POWERED_ON"), None
        )

        for category, endpoints in working_endpoints.items():
            print(f"\n📋 {category}")
            print("─" * 60)
            for path in endpoints:
                result = test_endpoint(client, path)
                icon = "✅" if result["status"] == "ok" else "❌"
                code_str = f"HTTP {result['code']}" if result["code"] else "N/A"
                print(f"{icon} {path:55s} {code_str:12s} {result['reason']}")

        # Per-VM guest endpoints (requires VMware Tools on target VM)
        print(f"\n📋 Per-VM Guest Endpoints (requires VMware Tools)")
        print("─" * 60)
        if vm_id:
            per_vm_paths = [
                f"/api/vcenter/vm/{vm_id}/guest/identity",
                f"/api/vcenter/vm/{vm_id}/guest/local-filesystem",
                f"/api/vcenter/vm/{vm_id}/guest/networking/interfaces",
            ]
            for path in per_vm_paths:
                result = test_endpoint(client, path)
                icon = "✅" if result["status"] == "ok" else "❌"
                code_str = f"HTTP {result['code']}" if result["code"] else "N/A"
                # Display with placeholder for readability
                display_path = path.replace(vm_id, "<vm-id>")
                print(f"{icon} {display_path:55s} {code_str:12s} {result['reason']}")
        else:
            print("  ⚠️  No powered-on VMs found — skipping per-VM tests")

    print("\n" + "=" * 60)
    print("🔑 Legend:")
    print("  ✅ HTTP 200 — Endpoint working")
    print("  ❌ Non-200 or error — Endpoint unavailable")
    print("\n📌 Known broken endpoints on vCenter 9 (do not use):")
    broken = [
        "/api/vcenter/event",
        "/api/vcenter/audit-records",
        "/api/cis/tasks",
        "/api/cis/session/list",
        "/api/vcenter/session",
        "/api/vcenter/vds/switch",
        "/api/vcenter/authorization/global-access",
        "/api/vcenter/host/<id>/lockdown",
        "/api/vcenter/vm/<id>/snapshot",
        "/api/vcenter/storage/policies/compliance/vm",
        "/api/appliance/health/overall",
        "/api/appliance/health/cpu",
        "/api/appliance/health/network",
    ]
    for path in broken:
        print(f"  ❌ {path}")


if __name__ == "__main__":
    main()
