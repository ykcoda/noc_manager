#!/usr/bin/env python3
"""
vCenter API Diagnostic Tool for vCenter 9 Compatibility

This script probes your vCenter 9 instance to identify which API endpoints
are available and working, helping diagnose API compatibility issues.

Usage:
    python scripts/diagnose_vcenter_api.py
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
            except:
                pass


def test_endpoint(client: httpx.Client, path: str, method: str = "GET", **kwargs) -> dict:
    """Test if an endpoint exists and is accessible."""
    try:
        if method == "GET":
            resp = client.get(path, **kwargs)
        elif method == "POST":
            resp = client.post(path, json={}, **kwargs)
        else:
            return {"status": "unknown", "code": None, "reason": "unsupported method"}

        return {
            "status": "ok" if resp.status_code == 200 else "exists",
            "code": resp.status_code,
            "reason": resp.reason_phrase,
        }
    except Exception as e:
        return {"status": "error", "code": None, "reason": str(e)}


def main():
    """Run diagnostic tests on vCenter API endpoints."""
    print("🔍 vCenter 9 API Compatibility Diagnostic\n")
    print(f"Target: {VC_HOSTNAME}\n")

    endpoints_to_test = {
        "Appliance Health": [
            ("/api/appliance/health/overall", "GET"),
            ("/api/appliance/system/version", "GET"),
        ],
        "Event & Audit": [
            ("/api/vcenter/event", "GET"),
            ("/api/vcenter/audit-records", "GET"),
            ("/api/vcenter/audit", "GET"),  # Alternative path
        ],
        "Sessions": [
            ("/api/cis/session/list", "POST"),
            ("/api/vcenter/session", "GET"),
        ],
        "Tasks": [
            ("/api/cis/tasks", "GET"),
        ],
        "Authorization": [
            ("/api/vcenter/authorization/role", "GET"),
            ("/api/vcenter/authorization/roles", "GET"),
            ("/api/vcenter/authorization/privilege", "GET"),
            ("/api/vcenter/authorization/privileges", "GET"),
        ],
        "VMs": [
            ("/api/vcenter/vm", "GET"),
        ],
        "Hosts": [
            ("/api/vcenter/host", "GET"),
        ],
        "Networks": [
            ("/api/vcenter/vds/switch", "GET"),
            ("/api/vcenter/distributed-switch", "GET"),
        ],
        "Clusters": [
            ("/api/vcenter/cluster", "GET"),
        ],
    }

    with vcenter_session() as client:
        for category, endpoints in endpoints_to_test.items():
            print(f"\n📋 {category}")
            print("─" * 60)

            for path, method in endpoints:
                result = test_endpoint(client, path, method=method)
                status_icon = {
                    "ok": "✅",
                    "exists": "⚠️",
                    "error": "❌",
                    "unknown": "❓",
                }.get(result["status"], "❓")

                if method == "POST":
                    path_display = f"{path} (POST)"
                else:
                    path_display = path

                code_str = f"HTTP {result['code']}" if result["code"] else "N/A"
                reason = result["reason"]

                print(
                    f"{status_icon} {path_display:50s} {code_str:15s} {reason}"
                )

    print("\n" + "=" * 60)
    print("🔑 Legend:")
    print("  ✅ HTTP 200 — Endpoint working normally")
    print("  ⚠️  HTTP 4xx/5xx — Endpoint exists but has an error")
    print("  ❌ Connection error — Endpoint unreachable")
    print("\n💡 Tips:")
    print("  • Use ✅ endpoints in your queries")
    print("  • ⚠️  endpoints may require special privileges or data")
    print("  • Check vCenter version in Appliance Health section")


if __name__ == "__main__":
    main()
