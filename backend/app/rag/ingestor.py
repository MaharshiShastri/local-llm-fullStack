from sqlalchemy.orm import Session
from app.models.models import Document, DocumentChunk
from app.rag.chunker import rag_chunker
from app.rag.vector_store import rag_vector_store
from app.rag.embedder import rag_embedder

def ingest_text(db: Session, title: str, raw_text: str, user_id: int, source_type: str = "document", file_path: str = None):
    final_path = file_path if file_path else f"/{user_id}/internal/{source_type}"
    #Generalized ETL for any text content (Tasks, Conversations, or PDFs).
    new_doc = Document(
        filename=title, 
        user_id=user_id, 
        file_path=final_path
        )
    db.add(new_doc)
    db.commit()
    db.refresh(new_doc)
    text_chunks = rag_chunker.create_chunks(raw_text)#transform data from raw_text to chunks

    text_embedding = rag_embedder.generate_embeddings(text_chunks)#transform chunks to vector ID referenced through vector_index

    start_vector_id = rag_vector_store.add_to_index(text_embedding)#Load the answer refrenced from vector_bin

    chunk_objects = []
    for i, content in enumerate(text_chunks):
        chunk = DocumentChunk(
            document_id = new_doc.id,
            content = content,
            chunk_index = i,
            vector_id = start_vector_id + i #Increment with i value with reference to FAISS vector_id
        )
        chunk_objects.append(chunk)

    db.bulk_save_objects(chunk_objects) #Lesser expensive as compared to storing individiaual chunks, Load answer into DB
    db.commit()
    print(f"Ingested document '{title}' with {len(text_chunks)} chunks and vector IDs from {start_vector_id} to {start_vector_id + len(text_chunks) - 1} with contents: {chunk_objects}")
    return {"document_id": new_doc.id, "chunks_count": len(text_chunks)}


def get_grounded_context(query: str, db: Session, user_id: int):
    query_vector = rag_embedder.generate_embeddings([query])[0] #Get vector for query
    _, indices = rag_vector_store.search(query_vector, k=5) #Search for top 5 relevant chunks in vector store
    safe_indices = [int(i) for i in indices if i is not None]
    
    chunks = db.query(DocumentChunk).join(Document).filter(
        DocumentChunk.vector_id.in_(safe_indices),
        Document.user_id == user_id,
    ).all()
    context_text = "\n".join([c.content for c in chunks])

    return context_text