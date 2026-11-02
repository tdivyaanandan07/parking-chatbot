# 🅿️ CityPark Parking Reservation Chatbot

![CI](https://github.com/YOURNAME/parking-chatbot/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.12-blue)

A multi-agent chatbot for a parking facility. It answers questions about the parking lot, collects reservation details interactively, escalates each request to a **human administrator** for approval, and records approved bookings through an **MCP server**. The whole pipeline is orchestrated with **LangGraph**.

| Customer chat | Administrator page |
|---|---|
| ![Chat UI](screenshots/04-ui-chat.png) | ![Admin UI](screenshots/05-ui-admin.png) |

---

## Table of contents

1. [Features](#features)
2. [Architecture](#architecture)
3. [Tech stack](#tech-stack)
4. [Setup](#setup)
5. [Usage](#usage)
6. [Demo](#demo)
7. [Evaluation](#evaluation)
8. [Load testing](#load-testing)
9. [Automated tests and CI](#automated-tests-and-ci)
10. [Security](#security)
11. [Project structure](#project-structure)
12. [Stages](#stages)
13. [Limitations and future work](#limitations-and-future-work)

---

## Features

- **RAG chatbot (LangChain):** answers questions using retrieved context only, and declines off-topic questions.
- **Static and dynamic data split:**
  - *Static* data (general info, location, booking process, rules) is stored in a **FAISS vector store**.
  - *Dynamic* data (prices, working hours, free spaces) is stored in **SQLite** and read live, so it is never stale or hallucinated.
- **Interactive booking:** collects name, surname, car number and reservation period one field at a time, with input validation. Questions can be asked in the middle of a booking.
- **Guardrails:** Microsoft Presidio (pre-trained NLP) redacts emails, phone numbers, card numbers, IBAN and SSN. A pattern filter blocks prompt-injection and data-extraction attempts.
- **Human-in-the-loop:** a second LangChain agent writes an approval request and waits for the administrator's decision through a REST API.
- **MCP server:** writes approved reservations to a text file as `Name | Car Number | Reservation Period | Approval Time`.
- **LangGraph orchestration** of all components.
- **Web UI (Streamlit)** for customers and for the administrator.
- **Evaluation, load tests, automated tests and CI.**

---

## Architecture

```mermaid
flowchart LR
    U[User] --> C[Chat node<br/>RAG agent]
    C -->|question / next field| U
    C -->|booking complete| A[Admin node<br/>approval agent]
    A -->|approved| R[Record node<br/>MCP server]
    A -->|refused / timeout| F[Refused node]
    R --> FILE[(reservations.txt)]
    A <-->|REST| API[Admin Inbox API]
    ADMIN((Human<br/>administrator)) <--> API
```

```mermaid
flowchart TB
    Q[User message] --> G{Guardrail:<br/>malicious?}
    G -->|yes| BLOCK[Refuse]
    G -->|no| I[LLM: classify intent<br/>and extract fields]
    I -->|info| RET[Retrieve static chunks<br/>FAISS top-3]
    I -->|info| SQL[Read dynamic data<br/>SQLite]
    RET --> ANS[LLM answers from context only]
    SQL --> ANS
    ANS --> RED[Presidio redaction]
    RED --> OUT[Reply]
    I -->|reserve| COL[Validate and store field<br/>ask for the next one]
```

| Component | File | Role |
|---|---|---|
| Agent 1: RAG chatbot | `src/rag/chatbot.py` | Intent detection, retrieval, answers, booking data collection |
| Vector store | `src/rag/vector_store.py` | Builds and loads the FAISS index (static data) |
| SQL database | `src/db/sql_db.py` | Prices, hours, availability (dynamic data) |
| Guardrails | `src/guardrails/filters.py` | Sensitive-data redaction and attack filtering |
| Agent 2: admin agent | `src/admin/agent.py` | Writes the approval request and waits for the decision |
| Admin Inbox API | `src/admin/api.py` | FastAPI service where the administrator approves or refuses |
| MCP server | `mcp_server/server.py` | Secure file writer (stdio transport) |
| MCP client | `src/mcp_client.py` | Calls the MCP server from the graph |
| Orchestration | `src/graph.py` | LangGraph state machine: `chat → admin → record / refused` |
| Customer UI | `app.py` | Streamlit chat |
| Admin UI | `admin_ui.py` | Streamlit approve / refuse page |

### Design choices

- **Static vs dynamic split.** Information that changes (prices, availability) lives in SQL, so answers are exact. Stable text lives in the vector store.
- **Markdown-header chunking.** Each section of the source file becomes one chunk, so a retrieved chunk is a complete, self-contained answer.
- **FAISS** was chosen as the vector database because it is lightweight and runs locally with no extra services. It can be swapped for Milvus, Pinecone or Weaviate by changing only `src/rag/vector_store.py`.
- **Validation outside the LLM.** Field values (names, car number, exact `YYYY-MM-DD` dates) are validated in code rather than trusted from the model, which makes the booking flow predictable.
- **Models** are accessed through **EPAM DIAL** using the Azure OpenAI interface.

---

## Tech stack

| Area | Technology |
|---|---|
| Language | Python 3.12 |
| LLM framework | LangChain, LangGraph |
| LLM and embeddings | EPAM DIAL (Azure OpenAI interface) |
| Vector database | FAISS |
| SQL database | SQLite |
| Guardrails | Microsoft Presidio, spaCy |
| Admin service | FastAPI, Uvicorn |
| MCP | MCP Python SDK, `langchain-mcp-adapters` |
| UI | Streamlit |
| Tests and CI | pytest, GitHub Actions |

---

## Setup

**Requirements:** Python 3.12, a DIAL API key, and the EPAM VPN when calling DIAL.

```bash
git clone https://github.com/YOURNAME/parking-chatbot.git
cd parking-chatbot

python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env     # then edit .env: add your DIAL key and a random MCP_SECRET
python build_data.py     # builds the SQLite database and the FAISS index
```

`.env` variables:

| Variable | Meaning |
|---|---|
| `DIAL_ENDPOINT` | DIAL base URL, e.g. `https://ai-proxy.lab.epam.com` |
| `DIAL_API_KEY` | Your personal DIAL key (never commit it) |
| `DIAL_API_VERSION` | e.g. `2025-04-01-preview` |
| `CHAT_MODEL` | Chat deployment name |
| `EMBED_MODEL` | Embedding deployment name |
| `MCP_SECRET` | Random string; the MCP server rejects calls without it |

![Build data](screenshots/01-build-data.png)

---

## Usage

Start the admin inbox first (leave it running):

```bash
uvicorn src.admin.api:app --port 8001
```

### Option A: Web UI

```bash
streamlit run app.py --server.port 8501        # customer chat   -> http://localhost:8501
streamlit run admin_ui.py --server.port 8502   # administrator   -> http://localhost:8502
```

The customer asks questions or books a space. When the booking is complete, the request appears on the administrator page within 2 seconds. Clicking **Approve** or **Refuse** completes the customer's conversation.

### Option B: Terminal

```bash
python main.py
```

Example conversation:

```
You: How much is covered parking?
You: I want to book a space
You: Divya
You: Anandan
You: AB-1234
You: 2026-11-05 from 09:00 to 18:00
```

The bot then waits for the administrator. Approve through the Streamlit admin page, or open http://localhost:8001/docs, copy the id from `GET /requests/pending`, and send `{"approved": true}` (or `false`) to `POST /requests/{rid}/decision`.

Approved bookings are appended to `reservations.txt`:

```
Divya Anandan | AB-1234 | 2026-11-05 from 09:00 to 18:00 | 2026-11-01T20:29:19
```

---

## Demo

### Answering questions (RAG + SQL)
Static facts come from the vector store, prices and availability from SQL, and off-topic questions are declined.

![RAG answers](screenshots/02-rag-answers.png)

### Guardrails
A prompt-injection attempt is blocked before it reaches the model.

![Guardrail](screenshots/03-guardrail-block.png)

### Human-in-the-loop approval
The administrator sees the pending request, written by the second agent, and approves it.

![Pending request](screenshots/06-admin-pending.png)
![Approve](screenshots/07-admin-approve.png)

### Full pipeline: chat → admin → MCP → file
![Full flow](screenshots/08-full-flow.png)

### Refused reservation
![Refusal](screenshots/09-refusal.png)

---

## Evaluation

12 labelled questions, retrieval depth K = 3. Each question is labelled with the chunk id(s) that contain the answer.

| Metric | Value |
|---|---|
| Recall@3 | **1.00** |
| Precision@3 | 0.36 |
| Average retrieval latency | 605 ms |
| Max retrieval latency | 1564 ms |

Recall is perfect: the right chunk was retrieved for every question. Precision is capped by the setup, because each question has only 1-2 relevant chunks while 3 are returned. Latency is dominated by the embedding API call. Full analysis: [docs/evaluation_report.md](docs/evaluation_report.md).

```bash
python -m eval.evaluate
```

![Evaluation](screenshots/10-evaluation.png)

---

## Load testing

20 requests per component, 5 parallel workers.

| Component | Success | Avg | p95 | Max |
|---|---|---|---|---|
| Chatbot (RAG, info mode) | 20/20 | 4271 ms | 5682 ms | 6248 ms |
| Admin API (create + decide) | 20/20 | 14 ms | 21 ms | 22 ms |
| MCP file writer | 20/20 | 1 ms | 2 ms | 2 ms |

The chatbot is the slowest part: each message makes about two LLM calls and one embedding call over the network. The admin API and the file writer add negligible latency. Full report: [docs/load_test_report.md](docs/load_test_report.md).

```bash
python -m eval.load_test      # needs the admin inbox running
```

![Load test](screenshots/11-load-test.png)

---

## Automated tests and CI

```bash
python -m pytest -v
```

10 tests cover the guardrails, the chatbot logic and validation, the admin API and the MCP server (at least 2 per module). GitHub Actions runs them on every push (`.github/workflows/ci.yml`).

![pytest](screenshots/12-pytest.png)

---

## Security

- **Secrets** are kept in `.env`, which is excluded from Git. `.env.example` contains placeholders only.
- **MCP server:**
  - runs over stdio as a local child process, so it opens **no network port**;
  - requires a secret token on every call;
  - validates the car number format;
  - strips `|` and newline characters to prevent file-format injection.
- **Sensitive data protection:** Presidio redacts personal data from retrieved context and from bot replies.
- **Prompt-injection filter:** blocks attempts to override instructions, reveal the system prompt, or list other customers' data.
- **Grounded answers:** the model may only answer from retrieved context and otherwise says it does not know.
- **Reservation data** (`reservations.txt`) and the databases are excluded from Git.

---

## Project structure

```
.
├── app.py                  Streamlit customer chat
├── admin_ui.py             Streamlit administrator page
├── main.py                 Terminal chat (runs the LangGraph pipeline)
├── build_data.py           Builds SQLite and the FAISS index
├── src/
│   ├── config.py           DIAL connection
│   ├── graph.py            LangGraph orchestration
│   ├── mcp_client.py       MCP client
│   ├── rag/                chatbot, vector store
│   ├── db/                 SQLite data (prices, hours, availability)
│   ├── admin/              admin agent and inbox API
│   └── guardrails/         redaction and attack filters
├── mcp_server/             MCP server that writes reservations
├── eval/                   evaluation and load tests
├── tests/                  pytest tests
├── docs/                   evaluation and load-test reports
├── screenshots/            images used in this README
├── data/static/            source text for the vector store
└── .github/workflows/      CI
```

---

## Stages

The repository is tagged per stage of the assignment:

| Stage | Tag | Content |
|---|---|---|
| 1 | `stage-1` | RAG chatbot, vector DB, SQL, guardrails, evaluation |
| 2 | `stage-2` | Human-in-the-loop admin agent and approval API |
| 3 | `stage-3` | MCP server writing confirmed reservations |
| 4 | `stage-4` | LangGraph orchestration, load tests, UI, documentation |

---

## Limitations and future work

- Free-space counts are not decremented when a booking is approved.
- The admin inbox keeps requests in memory, so pending requests are lost on restart, and the API itself has no authentication. A production version would add login and a database.
- Reservation periods must be given as exact dates (`YYYY-MM-DD`). Natural phrases like "tomorrow" are rejected rather than interpreted.
- The evaluation set is small. A larger set and a re-ranker would give a more reliable measurement.
- Each chat message uses two LLM calls. Merging intent detection and answering would cut latency.
- FAISS could be replaced with Milvus, Pinecone or Weaviate for a hosted deployment.