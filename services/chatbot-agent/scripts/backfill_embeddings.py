import asyncio
import json
import httpx
from sqlalchemy import text
from app.database import async_session_factory
from app.config import settings

# Define the function directly in the script to avoid import errors!
async def get_embedding(text_content: str) -> list[float]:
    url = f"{settings.llm_api_base_url}/api/embeddings"
    payload = {"model": "nomic-embed-text", "prompt": text_content}
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json().get("embedding", [])

async def backfill():
    async with async_session_factory() as db:
        print("Fetching extracted documents from Postgres...")
        result = await db.execute(text("SELECT id, extracted FROM documents WHERE extracted IS NOT NULL"))
        docs = result.fetchall()
        
        print(f"Found {len(docs)} documents. Embedding data...")
        await db.execute(text("TRUNCATE TABLE document_embeddings"))
        
        for doc_id, extracted_json in docs:
            if not extracted_json:
                continue
            extracted = json.loads(extracted_json) if isinstance(extracted_json, str) else extracted_json
            full_text = json.dumps(extracted, indent=2)
            chunks = [full_text[i:i+1000] for i in range(0, len(full_text), 1000)]
            
            for chunk in chunks:
                try:
                    embedding = await get_embedding(chunk)
                    await db.execute(
                        text("""
                        INSERT INTO document_embeddings (document_id, chunk_text, embedding) 
                        VALUES (:doc_id, :chunk, :embed)
                        """),
                        {"doc_id": str(doc_id), "chunk": chunk, "embed": str(embedding)}
                    )
                except Exception as e:
                    print(f"Error embedding chunk: {e}")
                    
        await db.commit()
        count = (await db.execute(text("SELECT count(*) FROM document_embeddings"))).scalar()
        print(f"Backfill complete! Vector database now contains {count} embedded chunks.")

if __name__ == "__main__":
    asyncio.run(backfill())
