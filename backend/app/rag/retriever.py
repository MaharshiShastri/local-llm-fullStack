import time
import numpy as np
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sentence_transformers import CrossEncoder
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import torch

from app.rag.embedder import rag_embedder
from app.rag.vector_store import rag_vector_store
from app.models.models import DocumentChunk, Document

class Retriever:
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Retriever, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, k=15, final_k=3, time_threshold_ms=300):
        if self._initialized:
            return
        self._initialized = True
        self.k = k
        self.final_k = final_k
        self.time_threshold_ms = time_threshold_ms  # SLA for retrieval
        self._rerank_model = None 
        self._summarizer_model = None
        self._summarizer_tokenizer = None
        print(f"--- RAG: Retriever initialized in Lean-Mode (Cloud Summary) ---")
    
    @property
    def reranker(self):
        """Loads reranker to CPU only when a specific query triggers it."""
        if self._rerank_model is None:
            from sentence_transformers import CrossEncoder
            # Forced to CPU to ensure no conflict with Ollama/Ollama doesn't fight for VRAM
            self._rerank_model = CrossEncoder("./models/ms-marco-MiniLM-L-6-v2", device="cpu")
        return self._rerank_model
    
    @property
    def summarizer_model(self):
        if self._summarizer_model is None:
            print(f"--- RAG: Loading T5 Model to {self.device} ---")
            from transformers import AutoModelForSeq2SeqLM
            self._summarizer_model = AutoModelForSeq2SeqLM.from_pretrained("./models/t5-small").to(self.device)
        return self._summarizer_model

    @property
    def summarizer_tokenizer(self):
        if self._summarizer_tokenizer is None:
            from transformers import AutoTokenizer
            self._summarizer_tokenizer = AutoTokenizer.from_pretrained("./models/t5-small")
        return self._summarizer_tokenizer
    
    def _normalize_distances(self, distances):
        """
        Converts L2 distances to a 0-1 similarity score.
        Grounded Logic: Similarity = 1 / (1 + distance)
        """
        return 1 / (1 + np.array(distances))

    def retrieve_context(self, query: str, db: Session, bypass_summarization=False, load: float = 76.0, total_time: int = 500):
        STRICT_THRESHOLD = 0.5
        gpu_util = torch.cuda.utilization()
        vram_used = torch.cuda.memory_allocated() / torch.cuda.get_device_properties(0).total_memory
        print("CPU load: ", load, "GPU load: ", gpu_util, "VRAM used: ", round(vram_used *100), "%")
        
        if total_time < 300:
            print(total_time)
            self.final_k = 1
            bypass_summarization = True
        else:
            self.final_k = 3
            bypass_summarization = gpu_util > 90.0 or vram_used > 0.9 or load > 75.0

        start_time = time.perf_counter()
        
        # 1. FAISS Search
        query_embeddings = rag_embedder.generate_embeddings(query)
        query_selector = query_embeddings[0] if query_embeddings.ndim > 1 else query_embeddings
        distances, indices = rag_vector_store.search(query_selector, k=self.k)
        
        # 2. Proper Distance Handling
        similarities = self._normalize_distances(distances)
        
        # Filter indices (Using a similarity threshold rather than raw L2 distance)
        # Threshold 0.3 is a common baseline for 'relatedness' in L2-space
        valid_hits = [(idx, sim) for idx, sim in zip(indices, similarities) if idx != -1 and sim > STRICT_THRESHOLD]
        
        if not valid_hits:
            return ["No direct document matches found. Proceeding with general knowledge."], {"status": "fallback"}

        valid_indices = [int(h[0]) for h in valid_hits]

        # 3. Database Fetch
        chunks_with_docs = (
            db.query(DocumentChunk, Document)
            .join(Document, DocumentChunk.document_id == Document.id)
            .filter(DocumentChunk.vector_id.in_(valid_indices))
            .all()
        )

        if not chunks_with_docs:
            return ["Primary record retrieval failed."], {"status": "error"}

        # 4. Re-Ranking (Cross-Encoder)
        pairs = [[query, item[0].content] for item in chunks_with_docs]
        rerank_scores = self.rerank_model.predict(pairs)

        # 5. Hybrid Scoring (Semantic + Recency)
        scored_chunks = []
        now = datetime.now(timezone.utc)
        for i, (chunk_obj, doc_obj) in enumerate(chunks_with_docs):
            doc_date = doc_obj.upload_date.replace(tzinfo=timezone.utc)
            days_old = (now - doc_date).days
            recency_boost = 1.0 / (1.0 + (days_old / 30))
            
            # Weighted Score: 70% Semantic, 30% Recency
            final_score = (rerank_scores[i] * 0.7) + (recency_boost * 0.3)
            
            scored_chunks.append({
                "content": chunk_obj.content,
                "source": doc_obj.filename,
                "score": final_score
            })

        # 6. Diversity & Truncation
        top_ranked = sorted(scored_chunks, key=lambda x: x["score"], reverse=True)
        final_context = []
        seen_sources = {}
        for c in top_ranked:
            if seen_sources.get(c["source"], 0) < 2:
                final_context.append(f"[{c['source']}]: {c['content']}")
                seen_sources[c["source"]] = seen_sources.get(c["source"], 0) + 1
            if len(final_context) >= self.final_k: break

        # 7. TIME-AWARE ADAPTATION
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        
        # If we are nearing our SLA, skip T5 to save ~100-200ms
        if elapsed_ms > self.time_threshold_ms or bypass_summarization:
            return final_context, {"retrieval_time": elapsed_ms, "mode": "fast_path"}

        # 8. BATCH Summarization (Optimization)
        compressed = self.batch_compress(final_context)
        
        total_time = (time.perf_counter() - start_time) * 1000
        return compressed, {"retrieval_time": total_time, "mode": "deep_reasoning"}

    def batch_compress(self, chunks: list):
        """Runs T5 in a single batch to maximize GPU utilization."""
        if not chunks: return []
        
        # Extract headers
        headers = [c.split("]: ")[0] + "]: " if "]: " in c else "" for c in chunks]
        bodies = [c.split("]: ")[1] if "]: " in c else c for c in chunks]
        
        prompts = [f"summarize: {b}" for b in bodies]
        
        inputs = self.summarizer_tokenizer(prompts, return_tensors="pt", padding=True, truncation=True).to(self.device)
        
        summary_ids = self.summarizer_model.generate(
                      inputs["input_ids"], 
                      max_length=80, 
                      num_beams=2, 
                      early_stopping=True
                    )
        
        summaries = self.summarizer_tokenizer.batch_decode(summary_ids, skip_special_tokens=True)
        return [f"{h}{s}" for h, s in zip(headers, summaries)]

rag_retriever = Retriever()