import asyncio
import os

import streamlit as st
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.messages import HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI

load_dotenv()

st.set_page_config(
    page_title="NOC Manager",
    page_icon="🖧",
    layout="wide",
)

st.title("NOC Manager")
st.caption("AI-powered network monitoring via SolarWinds")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

SYSTEM_PROMPT = """You are a NOC expert. You MUST use the available SolarWinds tools \
to answer every user query about network performance or device status.

Structure your response as:
**Question:** <restate the question>
**Findings:** <summarise what the tool returned>
**Recommendation:** <actionable next step if applicable>
"""


async def _query_agent(user_input: str) -> str:
    async with MultiServerMCPClient(
        {
            "monitoring": {
                "transport": "stdio",
                "command": "python",
                "args": ["-m", "noc_managers.mcp_server"],
            }
        }
    ) as client:
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


if prompt := st.chat_input("Ask about network performance, BGP status, packet loss…"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Querying SolarWinds…"):
            try:
                answer = asyncio.run(_query_agent(prompt))
            except Exception as exc:
                answer = f"**Error:** {exc}"
        st.markdown(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})
