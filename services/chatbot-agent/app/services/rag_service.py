import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.config import settings
from shared.auth.middleware import CurrentUser

async def get_embedding(text_content: str) -> list[float]:
    url = f"{settings.llm_api_base_url}/api/embeddings"
    payload = {"model": "nomic-embed-text", "prompt": text_content}
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json().get("embedding", [])

async def search_knowledge_base(query: str, db: AsyncSession, user: CurrentUser, limit: int = 5) -> str:
    try:
        query_embedding = await get_embedding(query)
        if not query_embedding:
            return "Failed to generate search vector."

        stmt = text("""
            SELECT e.chunk_text, e.document_id
            FROM document_embeddings e
            -- FIXED: Cast documents.id to TEXT so it ignores the junk data
            JOIN documents d ON e.document_id = CAST(d.id AS TEXT)
            WHERE 
                (:role IN ('admin', 'finance')) 
                OR (d.uploaded_by = :email)
            ORDER BY e.embedding <=> cast(:vector as vector)
            LIMIT :limit
        """)
        
        results = await db.execute(stmt, {
            "vector": str(query_embedding),
            "role": user.role,
            "email": user.email,
            "limit": limit
        })
        
        chunks = results.fetchall()
        if not chunks:
            return "No relevant documents found in the knowledge base."

        context = "Relevant Document Excerpts:\n\n"
        for chunk in chunks:
            context += f"[Doc ID: {chunk.document_id}]\n{chunk.chunk_text}\n---\n"
            
        return context
    except Exception as e:
        return f"Error searching knowledge base: {str(e)}"
