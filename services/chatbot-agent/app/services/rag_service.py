import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings
from app.models import DocumentEmbedding

async def get_embedding(text: str) -> list[float]:
    """Fetch embeddings from the external Ollama server."""
    url = f"{settings.llm_api_base_url}/api/embeddings"
    payload = {
        "model": "nomic-embed-text", # Ensure you pull this on your external host!
        "prompt": text
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json().get("embedding", [])

async def search_knowledge_base(query: str, db: AsyncSession, limit: int = 3) -> str:
    """Perform Vector Search (RAG) on procurement documents."""
    try:
        # 1. Convert the user's search query into an embedding vector
        query_embedding = await get_embedding(query)
        if not query_embedding:
            return "Failed to generate search vector."

        # 2. Search Postgres using Cosine Distance (<=>)
        stmt = (
            select(DocumentEmbedding)
            .order_by(DocumentEmbedding.embedding.cosine_distance(query_embedding))
            .limit(limit)
        )
        
        results = await db.execute(stmt)
        chunks = results.scalars().all()

        if not chunks:
            return "No relevant documents found in the knowledge base."

        # 3. Format context for the LLM
        context = "Relevant Document Excerpts:\n\n"
        for chunk in chunks:
            context += f"[Doc ID: {chunk.document_id}]\n{chunk.chunk_text}\n---\n"
            
        return context

    except Exception as e:
        return f"Error searching knowledge base: {str(e)}"