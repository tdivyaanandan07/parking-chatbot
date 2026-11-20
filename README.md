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
10. [Deployment](#deployment)
11. [Security](#security)
12. [Project structure](#project-structure)
13. [Stages](#stages)
14. [Limitations and future work](#limitations-and-future-work)

---

## Features

- **RAG chatbot (LangChain):** answers questions using retrieved context only, and declines off-topic questions.
- **Static and dynamic data split:**
  - *Static* data (general info, location, booking process, rules) is stored in a **FAISS vector store**.
  - *Dynamic* data (prices, working hours, free spaces) is stored in **SQLite** and read live, so it is never stale or hallucinated.
- **Interactive booking:** collects name, surname, car number and reservation period one field at a time, with input validation. Questions can be asked in the middle of a booking.
- **Guardrails:** Microsoft Presidio (pre-trained NLP) redacts emails, phone numbers, card numbers, IBAN and SSN. A pattern filter blocks prompt-injection and data-extraction attempts.
- **Confirm before submitting:** once all details are in, the bot shows a summary and waits for **yes**, a correction ("change the car to XY-123") or **cancel**.
- **Human-in-the-loop:** a second LangChain agent writes an approval request and sends it to the administrator through a REST API. The chat doesn't wait: the customer gets a unique **reference number** (e.g. `CP-7K3F9Q`) and can keep chatting or book again.
- **Status checks:** ask the bot for a reservation's status. For privacy it needs **both** the reference number and the car number plate, and it gives the same "not found" answer whichever one is wrong.
- **MCP server:** when the administrator approves, the admin API writes the reservation to a text file as `Name | Car Number | Reservation Period | Approval Time | Reference`.
- **LangGraph orchestration** of all components in one graph: `chat → submit → admin_approval → record`. The approval node pauses with LangGraph's `interrupt()`, and the administrator's decision resumes it.
- **Web UI (Streamlit)** for customers and for the administrator.
- **Evaluation, load tests, automated tests and CI.**

---

## Architecture

The whole pipeline is one LangGraph graph (`src/graph.py`) with a node per stage:

```mermaid
flowchart TB
    START((start)) --> CHAT[chat<br/>Agent 1: RAG chatbot]
    CHAT -->|answer, next question,<br/>summary or status| END1((end))
    CHAT -->|customer confirmed| SUBMIT[submit<br/>Agent 2: approval request]
    SUBMIT -->|inbox unreachable| END2((end))
    SUBMIT --> APPROVAL[admin_approval<br/>⏸ interrupt: waits for the admin]
    APPROVAL -->|refused| END3((end))
    APPROVAL -->|approved| RECORD[record<br/>MCP server writes the file]
    RECORD --> END4((end))
```

How the processes work together:

```mermaid
flowchart LR
    U[Customer] <--> UI[Streamlit chat<br/>app.py]
    UI -->|run_turn| G[LangGraph<br/>chat → submit → pause]
    G -->|POST /requests<br/>+ thread id| API[Admin Inbox API<br/>FastAPI + SQLite]
    G <-->|checkpoints| CP[(data/checkpoints.db)]
    ADMIN((Administrator)) <--> AUI[Streamlit admin<br/>admin_ui.py] -->|POST /decision| API
    API -->|resume thread| G2[LangGraph<br/>admin_approval → record]
    G2 <-->|checkpoints| CP
    G2 -->|stdio| M[MCP server] --> FILE[(reservations.txt)]
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
| Agent 2: admin agent | `src/admin/agent.py` | Writes the approval request, submits it and returns the reference; looks up status |
| Admin Inbox API | `src/admin/api.py` | FastAPI service where the administrator approves or refuses; a decision resumes the paused graph run |
| Recording step | `src/admin/recording.py` | Saves an approved request through MCP and stores the outcome |
| Request store | `src/db/requests_db.py` | SQLite table of requests, reference numbers, statuses and graph thread ids |
| MCP server | `mcp_server/server.py` | Secure file writer (stdio transport) |
| MCP client | `src/mcp_client.py` | Starts the MCP server and calls its `save_reservation` tool |
| Orchestration | `src/graph.py` | LangGraph graph `chat → submit → admin_approval → record`, SQLite checkpoints |
| Customer UI | `app.py` | Streamlit chat |
| Admin UI | `admin_ui.py` | Streamlit approve / refuse page |

### Agent and server logic

**Graph state** (`State` in `src/graph.py`): the user message, the booking draft, whether details are being collected, the reply, a `ready` flag, the reference number, and the administrator's decision.

**One thread per customer message.** `run_turn()` runs each message on a new LangGraph thread. Most threads end after `chat`. A confirmed booking continues to `submit` and then stops at `admin_approval`, and that thread now represents the booking. Because the next message starts a new thread, a booking waiting for approval never blocks the conversation.

| Node | Runs in | What it does | Next |
|---|---|---|---|
| `chat` (Agent 1) | chat process | Blocks attacks, then uses one LLM call to classify intent (`info`, `reserve`, `status`, `other`) and extract booking fields. For `info` it answers from FAISS chunks and live SQL data, then redacts the answer with Presidio. For `reserve` it validates and stores fields, asks for the missing ones, and shows a summary to confirm. A plain "yes" sets `ready`, with no LLM call. For `status` it looks up the request by reference **and** car plate. | `submit` if `ready`, else end |
| `submit` (Agent 2) | chat process | The LLM writes a short approval request. The node posts it with the booking and the **thread id** to `POST /requests`, and returns the reference number to the customer. If the inbox is unreachable, it keeps the draft so "yes" retries. | `admin_approval` if a reference was issued, else end |
| `admin_approval` (human in the loop) | paused, then admin API process | Calls LangGraph `interrupt()`. The run is checkpointed to `data/checkpoints.db` and the graph returns to the chat at once. When the administrator decides, the admin API resumes this thread with `Command(resume={"approved": ...})`. A refusal sets the status to `refused`. | `record` if approved, else end |
| `record` (data recording) | admin API process | `record_approved()` starts the MCP server over stdio and calls `save_reservation`. The status becomes `approved`, or `save_failed` with the reason (for example an overlapping booking). | end |

**Admin Inbox API** (`src/admin/api.py`, port 8001):

| Endpoint | Purpose |
|---|---|
| `POST /requests` | Agent 2 files a request; returns it with a new reference (`CP-XXXXXX`) |
| `GET /requests/pending` | What the admin page lists |
| `POST /requests/{ref}/decision` `{"approved": bool}` | Resumes the paused graph run; `409` if already decided |
| `POST /requests/lookup` `{"reference", "car_number"}` | Customer status check; the same `404` whichever value is wrong |

A request that was posted straight to the API, with no graph thread waiting, is decided by the same refuse and record steps inside the endpoint, so both paths end in the same states.

**MCP server** (`mcp_server/server.py`): a FastMCP server with one tool, `save_reservation(name, car_number, period, token, reference)`. It runs only as a stdio child process, so it opens no network port. It rejects a wrong `MCP_SECRET` token and an invalid plate, strips `|` and newlines, refuses a period that overlaps an existing booking for the same car, and appends `Name | Car | Period | Approval time | Reference` to the file named by `RESERVATIONS_FILE` (default `reservations.txt`).

**Request statuses:** `pending → approved | refused | save_failed`.

### Design choices

- **Human in the loop with `interrupt()` and a SQLite checkpointer.** The approval step is a real graph node, not a side channel. Its state is saved to `data/checkpoints.db`, so the chat process and the admin API process share the paused runs, and those runs survive restarts of either.

- **Static vs dynamic split.** Information that changes (prices, availability) lives in SQL, so answers are exact. Stable text lives in the vector store.
- **Markdown-header chunking.** Each section of the source file becomes one chunk, so a retrieved chunk is a complete, self-contained answer.
- **FAISS** was chosen as the vector database because it is lightweight and runs locally with no extra services. It can be swapped for Milvus, Pinecone or Weaviate by changing only `src/rag/vector_store.py`.
- **Validation outside the LLM.** Field values (names, car number, dates) are validated in code rather than trusted from the model, which makes the booking flow predictable. Natural periods like "tomorrow 9am to 5pm" are parsed in code (`src/datetime_nl.py`) and stored in a canonical form.
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
| `ADMIN_URL` | Optional. Where the chat and admin page reach the inbox API (default `http://localhost:8001`) |
| `RESERVATIONS_FILE` | Optional. File the MCP server appends to (default `reservations.txt`) |

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

The customer asks questions or books a space. When the details are complete, the bot shows a summary. After the customer confirms, the graph run pauses at `admin_approval`, the request appears on the administrator page within 2 seconds, and the customer gets a reference number straight away. **Approve** resumes the run, which saves the booking through MCP. **Refuse** ends the run. The customer sees the result by asking for the status.

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
Bot: Please check your reservation: ... Reply yes to send it ...
You: yes
Bot: Your reservation has been sent to the administrator for approval.
     Reference number: CP-7K3F9Q ...
You: what's the status of CP-7K3F9Q for car AB-1234?
Bot: Reservation CP-7K3F9Q is waiting for the administrator's approval.
```

Approve through the Streamlit admin page, or open http://localhost:8001/docs, copy the id from `GET /requests/pending`, and send `{"approved": true}` (or `false`) to `POST /requests/{rid}/decision`. Statuses are `pending`, `approved`, `refused`, or `save_failed` (approved but the MCP writer rejected it, e.g. an overlapping booking for the same car). Requests are kept in `data/parking.db` and paused graph runs in `data/checkpoints.db`, so both reference numbers and pending approvals survive restarts.

To see the graph: `python draw_graph.py` prints it as Mermaid.

Approved bookings are appended to `reservations.txt`:

```
Divya Anandan | AB-1234 | 2026-11-05 09:00 to 18:00 | 2026-11-01T20:29:19 | CP-7K3F9Q
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

5 parallel workers, through the real graph, LLM and MCP server. All data goes to a temporary folder.

| Component | Success | Avg | p95 | Max |
|---|---|---|---|---|
| Chatbot dialogue (`chat` node) | 20/20 | 4184 ms | 5983 ms | 6139 ms |
| Booking submit (`chat → submit →` pause) | 40/40 | 2350 ms | 3848 ms | 4182 ms |
| Admin refuse (resume → end) | 20/20 | 74 ms | 189 ms | 226 ms |
| Admin approve (resume → `record` → MCP) | 20/20 | 1005 ms | 1114 ms | 1122 ms |
| MCP server, stdio round trip | 20/20 | 901 ms | 930 ms | 943 ms |
| MCP writer logic only | 20/20 | 2 ms | 4 ms | 5 ms |

At the end, the script checks that all 20 approved bookings were written to the file exactly once and that none of the refused ones were. The chatbot is the slowest part, because each message makes two LLM calls and one embedding call. MCP time is almost all server start-up; the write itself takes 2 ms. Full report: [docs/load_test_report.md](docs/load_test_report.md).

```bash
python -m eval.load_test      # needs DIAL access; the admin inbox need not be running
```

![Load test](screenshots/11-load-test.png)

---

## Automated tests and CI

```bash
python -m pytest -v
```

55 tests, with no DIAL access needed:

- **Unit tests** cover the guardrails, the chatbot logic and validation, booking overlap checks, the request store, the admin API and the MCP server.
- **Integration tests** (`tests/test_pipeline.py`) push one booking through every node: `chat → submit → admin_approval` (paused) → the decision through the admin API → `record` → the **real MCP server** over stdio → the reservations file. Only the LLM is stubbed. The decision is resumed on a freshly built graph that shares the checkpoint file, as in the separate admin process. They cover approval, refusal, an overlapping booking (`save_failed`), a second decision (`409`), a turn that stops after `chat`, and an unreachable inbox.

GitHub Actions runs them on every push (`.github/workflows/ci.yml`).

![pytest](screenshots/12-pytest.png)

---

## Deployment

The system runs as three long-lived processes. The MCP server is not a separate service: the admin API starts it as a child process for each approval.

| Process | Command | Port | Needs |
|---|---|---|---|
| Admin Inbox API | `uvicorn src.admin.api:app --host 0.0.0.0 --port 8001` | 8001 | `.env` (`MCP_SECRET`, DIAL vars), `data/`, write access to `RESERVATIONS_FILE` |
| Customer chat | `streamlit run app.py --server.port 8501` | 8501 | `.env` (DIAL vars), `data/` (FAISS index, databases), `ADMIN_URL` |
| Admin page | `streamlit run admin_ui.py --server.port 8502` | 8502 | `ADMIN_URL` |

Steps for a new machine or server:

1. Install Python 3.12, clone the repo, create the virtual env and run `pip install -r requirements.txt`.
2. Create `.env` from `.env.example` with a real DIAL key and a long random `MCP_SECRET`. On a server, set these as environment variables or secrets instead of using a file.
3. Run `python build_data.py` once to create `data/parking.db` and the FAISS index.
4. Start the three processes under a process manager (systemd, supervisord, or one container per process), with the **same working directory**. The chat and the admin API must share `data/checkpoints.db` and `data/parking.db`, because paused approvals and requests live there. If they run in separate containers, mount `data/` as a shared volume.
5. If the admin API runs on another host, set `ADMIN_URL` for the chat and the admin page.
6. Check it works: `python -m pytest`, then make a booking in the chat and approve it on the admin page. A new line should appear in `reservations.txt`.

Production notes:

- **Put the admin page and the admin API behind authentication** (a reverse proxy with SSO or basic auth, or a VPN). The API has no login of its own, and only the chat port should be public.
- **Back up** `data/parking.db`, `data/checkpoints.db` and `reservations.txt`.
- SQLite suits a single host. To scale out, swap `SqliteSaver` for LangGraph's Postgres checkpointer and move the request store to Postgres. Only `src/graph.py` and `src/db/requests_db.py` would change.
- Every chat message is a short graph thread, so `data/checkpoints.db` grows over time. Threads that ended can be deleted periodically.

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
│   ├── graph.py            LangGraph orchestration (chat → submit → admin_approval → record)
│   ├── mcp_client.py       MCP client
│   ├── rag/                chatbot, vector store
│   ├── db/                 SQLite data (prices, hours, availability)
│   ├── admin/              admin agent, inbox API, recording step
│   └── guardrails/         redaction and attack filters
├── mcp_server/             MCP server that writes reservations
├── eval/                   evaluation and load tests
├── tests/                  pytest unit tests and pipeline integration tests
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
- The admin API has no authentication of its own; it must sit behind a proxy or VPN (see [Deployment](#deployment)).
- Each approval starts a new MCP server process (about 0.9 s). Keeping one client session open would make approvals faster.
- SQLite checkpoints and requests suit a single host; scaling out needs Postgres.
- The evaluation set is small. A larger set and a re-ranker would give a more reliable measurement.
- Each chat message uses two LLM calls. Merging intent detection and answering would cut latency.
- FAISS could be replaced with Milvus, Pinecone or Weaviate for a hosted deployment.