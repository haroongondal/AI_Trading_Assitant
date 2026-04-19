"""
Web search tool: live search for info not in RAG (DuckDuckGo via langchain-community).
"""
from langchain_core.tools import tool
from langchain_community.tools import DuckDuckGoSearchRun

_ddg = DuckDuckGoSearchRun()


@tool
def search_web(query: str) -> str:
    """Search the web for current information: crypto, US equities, PSX, forex, macro, and regional headlines (Pakistan, US, Middle East/oil) when those drive the user's holdings."""
    try:
        return _ddg.invoke(query)
    except Exception as e:
        return f"Search error: {e}"


web_search_tool = search_web
