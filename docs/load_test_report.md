# Load Test Report (Stage 4)

Run with `python -m eval.load_test` on 2026-11-20, locally (WSL), against EPAM DIAL.
5 parallel workers. Every row goes through the real code path: the LangGraph pipeline,
the real LLM and the real MCP server as a stdio child process. The admin API is called
in-process through FastAPI's TestClient, so the numbers exclude HTTP/uvicorn overhead
(about 10-20 ms per call on localhost). All data goes to a temporary folder, so real
bookings are never touched.

| Component | What one request does | Requests | Success | Avg | p95 | Max |
|---|---|---|---|---|---|---|
| Chatbot dialogue | info question through the graph: `chat` node (guardrail, intent LLM call, FAISS + SQL, answer LLM call) | 20 | 20 | 4184 ms | 5983 ms | 6139 ms |
| Booking submit | customer says "yes": `chat → submit` (agent 2 LLM call, inbox insert) → pause at `admin_approval` | 40 | 40 | 2350 ms | 3848 ms | 4182 ms |
| Admin refuse | `POST /decision` resumes the paused run → `END` | 20 | 20 | 74 ms | 189 ms | 226 ms |
| Admin approve | `POST /decision` resumes the run → `record` node → MCP write | 20 | 20 | 1005 ms | 1114 ms | 1122 ms |
| MCP server, stdio | `save_via_mcp`: start the server process, MCP handshake, tool call | 20 | 20 | 901 ms | 930 ms | 943 ms |
| MCP writer logic | `write_reservation` only (validation, conflict check, append) | 20 | 20 | 2 ms | 4 ms | 5 ms |

End-of-run consistency check:

```
Statuses: {'refused': 20, 'approved': 20}
Reservations file: 60 lines; approved bookings recorded: 20/20; unexpected: 0
```

Every approved booking was written exactly once and no refused booking was written.
The other 40 lines come from the two MCP-only rows.

## Analysis
- **100% success** on all 180 operations, with no rate-limit errors from DIAL and no
  lost or duplicated writes under parallel load.
- **The chatbot is the bottleneck.** Each info message makes two LLM calls and one
  embedding call. Under parallel load, requests queue at the remote API (p95 is about 1.4× the average).
- **Submitting a booking** costs one LLM call (agent 2 writes the admin message). The customer
  gets the reference number as soon as the run pauses and doesn't wait for the administrator.
- **Admin decisions are cheap.** Loading the paused run from the SQLite checkpoint and
  finishing it takes under 100 ms. Approval adds the MCP write.
- **The MCP cost is process start-up, not writing.** The stdio round trip takes about 0.9 s, almost
  all of it spawning the server and doing the handshake. The write itself takes 2 ms.

## Possible improvements
- Merge intent detection and answering into one LLM call, or use a smaller model for intent.
- Keep one MCP client session open in the admin API instead of starting the server for each
  approval. That would bring an approval close to the 74 ms refusal time.
