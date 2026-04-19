"""
Web search tool: live search for info not in RAG (DuckDuckGo via langchain-community).
"""
from langchain_core.tools import tool
from langchain_community.tools import DuckDuckGoSearchRun

_ddg = DuckDuckGoSearchRun()


@tool
def search_web(query: str) -> str:
    """Search the web for current information: crypto, equities (NASDAQ/NYSE), PSX, forex, macro. Use when the user needs up-to-date prices or news not in the knowledge base."""
    try:
        return _ddg.invoke(query)
    except Exception as e:
        return f"Search error: {e}"


web_search_tool = search_web
