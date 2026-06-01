import faiss
import numpy as np
import os

class VectorStore:
    def __init__(self, dimension=384, index_path="vector_index.bin"):
        self.dimension = dimension
        self.index_path = index_path

        if os.path.exists(self.index_path): #Load the index if it exists
            self.index = faiss.read_index(self.index_path, faiss.IO_FLAG_MMAP)
            print(f"---\t RAG: Loaded existing FAISS index from {self.index_path} ---")
        else: #Create a new index
            #L2 Distance (Euclidean) is standard for similarity
            self.index = faiss.IndexFlatL2(self.dimension)
            print(f"---\t RAG: Created a new index ---")

    def add_to_index(self, embeddings):
        #Convert list to numpy array
        embeddings_array = np.array(embeddings).astype('float32')

        start_id = self.index.ntotal
        self.index.add(embeddings_array)

        faiss.write_index(self.index, self.index_path)
        return start_id
    
    def search(self, query_embedding, k=3):
        query_array = np.array(query_embedding).astype('float32')
        if len(query_array.shape) == 1:
            query_array = query_array.reshape(1, -1)
            
        distances, indices = self.index.search(query_array, k)
        return distances[0], indices[0]
    
rag_vector_store = VectorStore()
