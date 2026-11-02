from src.config import llm, embeddings

print("Chat test:", llm.invoke("Say hello in one short sentence").content)

vector = embeddings.embed_query("parking lot")
print("Embedding test: got", len(vector), "numbers")