from sentence_transformers import SentenceTransformer
import torch
import os

class Embedder:
    def __init__(self, model_name="./models/all-MiniLM-L6-V2"):
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        # We store the model in a private variable initially
        self._model = None
        print(f"--- RAG: Embedder Bridge Ready (Lazy Mode on {self.device.upper()}) ---")

    @property
    def model(self):
        """Loads the model weights only when first accessed."""
        if self._model is None:
            print(f"--- RAG: Loading Embedding Model '{self.model_name}' to {self.device.upper()}... ---")
            self._model = SentenceTransformer(self.model_name, device=self.device)
            # Perform warmup to initialize the CUDA context
            self._model.encode(["warmup"])
            print("--- RAG: Embedding Model Loaded Successfully ---")
        return self._model
    
    def generate_embeddings(self, text_list):
        # Input normalization
        if isinstance(text_list, str):
            text_list = [text_list]
        
        # We access the model via the property 'self.model'
        # This triggers the loading logic if self._model is None
        embeddings = self.model.encode(text_list, show_progress_bar=False)
        return embeddings

# This now executes instantly and consumes ~0MB of extra RAM at startup
rag_embedder = Embedder()