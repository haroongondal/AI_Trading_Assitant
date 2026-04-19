"""
RAG tool: vector search over stored news/documents. JS parallel: like a "search knowledge base" API the agent calls.
"""
import os

# Belt-and-suspenders (main.py also sets this before other imports).
os.environ.setdefault("ANONYMIZED_TELEMETRY", "0")
os.environ.setdefault("CHROMA_TELEMETRY_ENABLED", "false")
os.environ.setdefault("CHROMA_ANONYMIZED_TELEMETRY", "false")

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
    """Search the knowledge base for market news and analysis (content may skew crypto/forex depending on ingest). Use for background context; combine with search_web for fresh tickers."""
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


def clear_vectorstore():
    """Remove all documents from the collection so the next ingest is fresh (no duplicate articles)."""
    global _vectorstore
    if _vectorstore is not None:
        try:
            _vectorstore.delete_collection()
        except Exception:
            pass
        _vectorstore = None
