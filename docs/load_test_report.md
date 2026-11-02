# Load Test Report (Stage 4)

Setup: 20 requests per component, 5 parallel workers, run locally against EPAM DIAL.

| Component | Requests | Success | Avg | p95 | Max |
|---|---|---|---|---|---|
| Chatbot (RAG, info mode) | 20 | 20 | 4271 ms | 5682 ms | 6248 ms |
| Admin API (create + decide) | 20 | 20 | 14 ms | 21 ms | 22 ms |
| MCP file writer | 20 | 20 | 1 ms | 2 ms | 2 ms |

## Analysis
- 100% success on all components, with no rate-limit errors.
- Chatbot latency is dominated by LLM and embedding calls to DIAL (about 2 chat calls + 1 embedding per message). Under parallel load requests queue on the remote API.
- Admin API and MCP writer add negligible latency.
- Possible improvement: merge intent detection and answering into one LLM call, or use a smaller model.