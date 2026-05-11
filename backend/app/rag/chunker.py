import re

class Chunker:
    def __init__(self, chunk_size=300, chunk_overlap=50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def clean_text(self, text):
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
    
    def create_chunks(self, text):
        text = self.clean_text(text)
        words = text.split()
        chunks = []

        for i in range(0, len(words), self.chunk_size - self.chunk_overlap):
            chunk_words = words[i:i+self.chunk_size]
            chunk_text = " ".join(chunk_words)
            chunks.append(chunk_text)

            #Stop if end is reached
            if i + self.chunk_size >= len(words):
                break

        return chunks
    
rag_chunker = Chunker()