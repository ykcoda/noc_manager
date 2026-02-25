"""
Backward-compatibility shim.
Delegates to the canonical location: noc_managers.mcp_servers.solarwinds
"""
from noc_managers.mcp_servers.solarwinds import main, mcp  # noqa: F401

if __name__ == "__main__":
    main()
