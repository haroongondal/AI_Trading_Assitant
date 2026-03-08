"""
RAG tool: vector search over stored news/documents. JS parallel: like a "search knowledge base" API the agent calls.
"""
import os
from langchain_community.vectorstores import Chroma
from langchain_ollama import OllamaEmbeddings
from langchain_core.tools import tool

from app.core.config import settings

_embeddings = None
_vectorstore = None


def _get_embeddings():
    global _embeddings
    if _embeddings is None:
        _embeddings = OllamaEmbeddings(
            base_url=settings.OLLAMA_BASE_URL,
            model=settings.OLLAMA_EMBEDDING_MODEL,
        )
    return _embeddings


def get_rag_retriever():
    """Return a retriever over the persisted Chroma collection. Creates collection if missing."""
    global _vectorstore
    os.makedirs(settings.CHROMA_PERSIST_DIR, exist_ok=True)
    if _vectorstore is None:
        _vectorstore = Chroma(
            collection_name="trading_news",
            embedding_function=_get_embeddings(),
            persist_directory=settings.CHROMA_PERSIST_DIR,
        )
    return _vectorstore.as_retriever(search_kwargs={"k": settings.RAG_TOP_K})


@tool
def query_rag(query: str) -> str:
    """Search the knowledge base for relevant crypto and forex news and analysis. Use this when the user asks about market news, recent events, or context from ingested documents."""
    retriever = get_rag_retriever()
    try:
        docs = retriever.invoke(query)
        if not docs:
            return "No relevant documents found in the knowledge base."
        return "\n\n---\n\n".join(doc.page_content for doc in docs)
    except Exception as e:
        return f"RAG search error: {e}"


# Expose for jobs that need to add documents
def get_vectorstore():
    get_rag_retriever()
    return _vectorstore
