"""
Web search tool: live search for info not in RAG. JS parallel: agent calls this like an external API.
"""
from langchain_core.tools import tool
from langchain_community.tools import DuckDuckGoSearchRun

_search = DuckDuckGoSearchRun()


@tool
def search_web(query: str) -> str:
    """Search the web for current information about crypto, forex, or markets. Use when the user needs up-to-date info that might not be in the knowledge base."""
    try:
        return _search.invoke(query)
    except Exception as e:
        return f"Search error: {e}"


web_search_tool = search_web
