import time
from src.rag.vector_store import load_retriever

K = 3
retriever = load_retriever(k=K)

TESTS = [
    {"q": "Where is the parking located?", "relevant": {1}},
    {"q": "How do I reserve a space?", "relevant": {2}},
    {"q": "How far in advance can I book?", "relevant": {3}},
    {"q": "What is the cancellation policy?", "relevant": {3}},
    {"q": "What is the maximum vehicle height?", "relevant": {4}},
    {"q": "How can I pay?", "relevant": {5}},
    {"q": "Is cash accepted?", "relevant": {5}},
    {"q": "How do I contact the front desk?", "relevant": {6}},
    {"q": "Are there electric vehicle chargers?", "relevant": {0, 7}},
    {"q": "How many spaces does the parking have?", "relevant": {0}},
    {"q": "Which metro station is nearby?", "relevant": {1}},
    {"q": "Can I park overnight?", "relevant": {4}},
]

recalls, precisions, latencies = [], [], []
for t in TESTS:
    start = time.perf_counter()
    got = {d.metadata["chunk_id"] for d in retriever.invoke(t["q"])}
    latencies.append(time.perf_counter() - start)
    hits = got & t["relevant"]
    recalls.append(len(hits) / len(t["relevant"]))
    precisions.append(len(hits) / K)

n = len(TESTS)
print(f"Questions:        {n}")
print(f"Recall@{K}:        {sum(recalls)/n:.2f}")
print(f"Precision@{K}:     {sum(precisions)/n:.2f}")
print(f"Avg latency:      {sum(latencies)/n*1000:.0f} ms")
print(f"Max latency:      {max(latencies)*1000:.0f} ms")