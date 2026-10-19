import asyncio
import json
from sqlalchemy import text
from app.database import async_session_factory
from app.services.rag_service import get_embedding

async def backfill():
    async with async_session_factory() as db:
        print("Fetching extracted documents from Postgres...")
        # Grab documents that have extracted text
        result = await db.execute(text("SELECT id, extracted FROM documents WHERE extracted IS NOT NULL"))
        docs = result.fetchall()
        
        print(f"Found {len(docs)} documents. Chunking and embedding...")
        for doc_id, extracted_json in docs:
            extracted = json.loads(extracted_json) if isinstance(extracted_json, str) else extracted_json
            
            # Simple chunking: Just grab the raw text and split it (if it exists)
            full_text = extracted.get("text", "")
            if not full_text:
                continue
                
            # Chunk by roughly 1000 characters
            chunks = [full_text[i:i+1000] for i in range(0, len(full_text), 1000)]
            
            for chunk in chunks:
                embedding = await get_embedding(chunk)
                await db.execute(
                    text("""
                    INSERT INTO document_embeddings (document_id, chunk_text, embedding) 
                    VALUES (:doc_id, :chunk, :embed)
                    """),
                    {"doc_id": doc_id, "chunk": chunk, "embed": str(embedding)}
                )
        await db.commit()
        print("Backfill complete! RAG is ready.")

if __name__ == "__main__":
    asyncio.run(backfill())