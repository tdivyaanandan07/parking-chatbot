import os
import sys
import asyncio
from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()


async def _save(name: str, car_number: str, period: str) -> str:
    client = MultiServerMCPClient({
        "writer": {
            "command": sys.executable,
            "args": ["mcp_server/server.py"],
            "transport": "stdio",
            "env": {**os.environ, "MCP_SECRET": os.environ["MCP_SECRET"]},
        }
    })
    tools = await client.get_tools()
    tool = next(t for t in tools if t.name == "save_reservation")
    result = await tool.ainvoke({
        "name": name, "car_number": car_number, "period": period,
        "token": os.environ["MCP_SECRET"],
    })
    return str(result)


def save_via_mcp(name: str, car_number: str, period: str) -> str:
    return asyncio.run(_save(name, car_number, period))