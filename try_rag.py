from src.config import llm
from src.db.sql_db import get_dynamic_context
from src.rag.vector_store import load_retriever

retriever = load_retriever()

question = input("Ask a question about the parking: ")
docs = retriever.invoke(question)
static = "\n\n".join(d.page_content for d in docs)

prompt = f"""You are a friendly parking assistant. Answer ONLY using the information below.
If the answer is not there, say you don't know.

GENERAL INFO:
{static}

LIVE DATA:
{get_dynamic_context()}

QUESTION: {question}"""

print("\nBot:", llm.invoke(prompt).content)