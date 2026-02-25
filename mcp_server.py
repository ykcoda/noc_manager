import httpx
from dataclasses import dataclass
from typing import Optional
from datetime import datetime
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("monitoring")


def execute_via_solarwinds_api(swql_query: str):
    hostname = "solarwinds.myfidelitybank.net"

    username = "admin"
    password = "F1d3l1t7@2022"

    # Step 2: Build the SWIS JSON API URL
    url = f"https://{hostname}:17774/SolarWinds/InformationService/v3/Json/Query"

    # Step 4: Make POST request to SWIS API
    with httpx.Client(verify=False, auth=(username, password)) as client:
        response = client.post(url, json={"query": swql_query})
        response.raise_for_status()
        return response.json()


@mcp.tool()
def worst_performing_devices_based_packet_loss_response_time():
    """
    Uses the solarwinds api to get worst-performing active devices based on packet loss and response time.

    returns response in json
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

    return execute_via_solarwinds_api(swql_query)


@mcp.tool()
def bgp_status_down():
    """
    Uses the solarwinds api to get network routers with their bgp status as down.

    returns
    response in a tabular format displaying ONLY Router Name, Address and BGP Status
    """
    # Step 3: SWQL query to check if Orion server exists
    swql_query = """
    SELECT TOP 15
    n.Caption AS Router_Name,
    n.IP_Address AS IPAddress,
    MAX(CASE 
        WHEN rn.ProtocolStatusDescription = 'Established' THEN 'Up' 
        ELSE 'Down' 
    END) AS BGPStatus,  -- 'Down' if any BGP peer isn't Established
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
       END) = 'Down'   -- Only include routers where BGP is Down (at least one peer affected)
ORDER BY Avg_Response_Time_ms DESC
        """
    return execute_via_solarwinds_api(swql_query)


if __name__ == "__main__":
    print("MCP Server is running....")
    mcp.run(transport="stdio")
