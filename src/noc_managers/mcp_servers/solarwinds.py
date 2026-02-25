import os

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("solarwinds-monitoring")

_SW_HOSTNAME = os.getenv("SW_HOSTNAME", "")
_SW_USERNAME = os.getenv("SW_USERNAME", "")
_SW_PASSWORD = os.getenv("SW_PASSWORD", "")


def _execute_via_solarwinds_api(swql_query: str) -> dict:
    url = (
        f"https://{_SW_HOSTNAME}:17774"
        "/SolarWinds/InformationService/v3/Json/Query"
    )
    with httpx.Client(verify=False, auth=(_SW_USERNAME, _SW_PASSWORD)) as client:
        response = client.post(url, json={"query": swql_query})
        response.raise_for_status()
        return response.json()


@mcp.tool()
def worst_performing_devices_based_packet_loss_response_time() -> dict:
    """
    Uses the SolarWinds API to get worst-performing active devices based on
    packet loss and response time (last 4 hours, top 20).

    Returns response in JSON.
    """
    swql_query = """SELECT TOP 20
        n.Caption AS Node_Name,
        n.IP_Address,
        n.MachineType,
        n.StatusIcon AS [_IconFor_Node_Name],
        n.DetailsUrl AS [_LinkFor_Node_Name],
        ROUND(AVG(rt.AvgResponseTime), 0) AS Avg_Response_Time_ms,
        ROUND(AVG(rt.PercentLoss), 2) AS Avg_Packet_Loss_Percent,
        n.StatusDescription AS Current_Status
    FROM Orion.Nodes n
    INNER JOIN Orion.ResponseTime rt ON rt.NodeID = n.NodeID
    WHERE rt.ObservationTimestamp > ADDHOUR(-4, GETUTCDATE())
    AND n.Status = 1
    GROUP BY n.NodeID, n.Caption, n.IP_Address, n.MachineType,
            n.StatusIcon, n.DetailsUrl, n.StatusDescription
    HAVING AVG(rt.PercentLoss) > 0.5 OR AVG(rt.AvgResponseTime) > 150
    ORDER BY Avg_Packet_Loss_Percent DESC, Avg_Response_Time_ms DESC
    """
    return _execute_via_solarwinds_api(swql_query)


@mcp.tool()
def bgp_status_down() -> dict:
    """
    Uses the SolarWinds API to get Cisco routers with at least one BGP peer
    in a Down state (last 30 minutes, top 15).

    Returns response in JSON.
    """
    swql_query = """
    SELECT TOP 15
    n.Caption AS Router_Name,
    n.IP_Address AS IPAddress,
    MAX(CASE
        WHEN rn.ProtocolStatusDescription = 'Established' THEN 'Up'
        ELSE 'Down'
    END) AS BGPStatus,
    ROUND(AVG(rt.AvgResponseTime), 0) AS Avg_Response_Time_ms,
    ROUND(AVG(rt.PercentLoss), 2) AS Avg_Packet_Loss_Percent,
    n.DetailsUrl AS [_LinkFor_Router_Name],
    '/Orion/images/StatusIcons/Small-' + n.StatusIcon AS [_IconFor_Router_Name]
FROM Orion.Nodes n
JOIN Orion.ResponseTime rt ON rt.NodeID = n.NodeID
LEFT JOIN Orion.Routing.Neighbors rn ON rn.NodeID = n.NodeID AND rn.ProtocolName = 'BGP'
WHERE n.Vendor LIKE '%Cisco%'
  AND n.MachineType LIKE '%Router%'
  AND rt.ObservationTimestamp > ADDMinute(-30, GETUTCDATE())
GROUP BY n.NodeID, n.Caption, n.IP_Address, n.DetailsUrl, n.StatusIcon
HAVING MAX(CASE
           WHEN rn.ProtocolStatusDescription = 'Established' THEN 'Up'
           ELSE 'Down'
       END) = 'Down'
ORDER BY Avg_Response_Time_ms DESC
    """
    return _execute_via_solarwinds_api(swql_query)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
