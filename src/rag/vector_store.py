from pathlib import Path
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import MarkdownHeaderTextSplitter
from src.config import embeddings

INDEX_DIR = "data/faiss_index"
SOURCE = "data/static/parking_info.md"


def build_index():
    """Read the static info, split it by headers, embed it and save it."""
    text = Path(SOURCE).read_text(encoding="utf-8")
    splitter = MarkdownHeaderTextSplitter(headers_to_split_on=[("#", "title"), ("##", "section")])
    chunks = splitter.split_text(text)
    for i, c in enumerate(chunks):
        c.metadata["chunk_id"] = i
        # put the section name inside the text so it helps retrieval
        c.page_content = f"{c.metadata.get('section', '')}\n{c.page_content}"
    store = FAISS.from_documents(chunks, embeddings)
    store.save_local(INDEX_DIR)
    print(f"Saved {len(chunks)} chunks")
    return store


def load_retriever(k: int = 3):
    store = FAISS.load_local(INDEX_DIR, embeddings, allow_dangerous_deserialization=True)
    return store.as_retriever(search_kwargs={"k": k})