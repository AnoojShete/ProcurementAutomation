import asyncio
import json
from sqlalchemy import text
from app.database import async_session_factory
from app.services.rag_service import get_embedding

async def auto_embed_loop():
    print("Starting automatic RAG embedding watcher...")
    while True:
        try:
            async with async_session_factory() as db:
                # Find documents that have extracted data BUT are not yet in the embeddings table
                query = text("""
                    SELECT id, extracted_fields 
                    FROM documents 
                    WHERE extracted_fields IS NOT NULL 
                    AND id NOT IN (SELECT DISTINCT document_id FROM document_embeddings)
                """)
                result = await db.execute(query)
                new_docs = result.fetchall()
                
                for doc_id, extracted_json in new_docs:
                    print(f"New document detected ({doc_id}). Embedding automatically...")
                    
                    extracted = json.loads(extracted_json) if isinstance(extracted_json, str) else extracted_json
                    full_text = json.dumps(extracted, indent=2)
                    chunks = [full_text[i:i+1000] for i in range(0, len(full_text), 1000)]
                    
                    for chunk in chunks:
                        embedding = await get_embedding(chunk)
                        await db.execute(
                            text("""
                            INSERT INTO document_embeddings (document_id, chunk_text, embedding) 
                            VALUES (:doc_id, :chunk, :embed)
                            """),
                            {"doc_id": str(doc_id), "chunk": chunk, "embed": str(embedding)}
                        )
                    await db.commit()
                    print(f"Document {doc_id} successfully embedded into RAG.")
                    
        except Exception as e:
            print(f"Auto-embedder error: {e}")
        
        # Sleep for 10 seconds before checking again
        await asyncio.sleep(10)
