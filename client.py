import asyncio
from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_agent
from langchain.messages import HumanMessage

load_dotenv()
client = MultiServerMCPClient(
    {
        "monitoring": {
            "transport": "stdio",
            "command": "python",
            "args": ["./test/mcp_server.py"],
        }
    }
)


async def main():

    tools = await client.get_tools()
    agent = create_agent(
        model="gpt-5-mini",
        tools=tools,
        system_prompt="""You are NOC expect. You MUST use the available tools(solarwinds) to respond to user queries
        
        respond by saying:
        Question: {question}
        Answer: display it based on the output or what the tool presents
        \n
        """,
    )
    while True:
        print("Ask the agent a question or type 'quit' to exit.")
        query = input("Ask agent for monitoring info: ")

        if query.lower() == "quit":
            print("Quitting.... Bye, Bye...")
            break

        response = await agent.ainvoke({"messages": [HumanMessage(content=query)]})

        print(response["messages"][-1].content)


if __name__ == "__main__":
    asyncio.run(main())
