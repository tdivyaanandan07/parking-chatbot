# Evaluation Report: RAG System (Stage 1)

## Setup
- Vector store: FAISS (static data: general info, location, booking rules)
- SQL store: SQLite (dynamic data: prices, hours, availability)
- Embeddings: text-embedding-3-small-1 via EPAM DIAL
- Chunking: Markdown header split (8 chunks, one per section)
- Test set: 12 questions, each labeled with the relevant chunk id(s)
- Retrieval depth: K = 3

## Results

| Metric | Value |
|---|---|
| Recall@3 | 1.00 |
| Precision@3 | 0.36 |
| Average retrieval latency | 605 ms |
| Max retrieval latency | 1564 ms |

## Analysis
- **Recall@3 = 1.00:** the relevant chunk was retrieved for all 12 questions.
- **Precision@3 = 0.36:** each question has 1 or 2 relevant chunks but 3 are returned, so precision is capped at about 0.33-0.67. A smaller K (e.g. 2) would raise precision but risks lower recall.
- **Latency:** dominated by the embedding API call. The maximum is likely a cold-start effect on the first request.
- **Dynamic data** (prices, hours, availability) is read from SQL, not retrieved by similarity, so it is always exact and up to date.

## Guardrails
- Presidio detects and redacts emails, phone numbers, card numbers, IBAN and SSN in retrieved context and in bot replies.
- A pattern filter blocks prompt-injection and data-extraction attempts.

## Limitations
- Small test set and small corpus.
- Embedding latency depends on network and DIAL load.