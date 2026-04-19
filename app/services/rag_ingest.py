"""
Ingest documents (e.g. news) into the RAG vector store. JS parallel: like a pipeline that chunks text, embeds, and writes to DB.
"""
import logging
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings
from app.tools.rag import clear_vectorstore, get_vectorstore, ollama_service_reachable

logger = logging.getLogger(__name__)

TEXT_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=80,
    length_function=len,
)


def ingest_documents(docs: list[dict]) -> int:
    """
    docs: list of {title, summary, link, published}. Creates Document objects, chunks, adds to Chroma.
    Returns number of chunks added.
    """
    if not docs:
        return 0
    documents: list[Document] = []
    for d in docs:
        text = f"Title: {d.get('title', '')}\nSummary: {d.get('summary', '')}\nSource: {d.get('link', '')}\nPublished: {d.get('published', '')}"
        documents.append(Document(page_content=text, metadata={"source": d.get("link", ""), "title": d.get("title", "")}))
    chunks = TEXT_SPLITTER.split_documents(documents)
    if not chunks:
        return 0
    if not ollama_service_reachable():
        logger.warning(
            "RAG ingest skipped: Ollama not reachable at %s (start Ollama for embeddings, or news ingest will stay a no-op). "
            "Scheduled analysis still runs; chat without RAG still works via Groq.",
            settings.OLLAMA_BASE_URL,
        )
        return 0
    try:
        vs = get_vectorstore()
        # Prove embeddings work before wiping the collection (avoid long hangs + empty store on failure).
        if vs.embeddings is None:
            logger.warning("RAG ingest skipped: vector store has no embedding function")
            return 0
        vs.embeddings.embed_query(chunks[0].page_content[:1200])
    except Exception as e:
        logger.warning("RAG ingest skipped: embedding trial failed: %s", e)
        return 0
    try:
        clear_vectorstore()
        vs = get_vectorstore()
        vs.add_documents(chunks)
        logger.info("Ingested %s chunks into RAG", len(chunks))
        return len(chunks)
    except Exception as e:
        logger.exception("RAG ingest error: %s", e)
        return 0
