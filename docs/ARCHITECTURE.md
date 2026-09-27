# F.K. v4 Architecture

```
Browser (static/index.html, vanilla JS)
   |  Authorization: Bearer <token>
   v
FastAPI (main.py)
   |-- auth: register/login, PBKDF2-HMAC-SHA256 password hashing,
   |         HMAC-signed bearer tokens (no external JWT dependency)
   |-- conversations & messages (SQLite, scoped per user_id)
   |-- chat: builds a system prompt from personality + relevant memory +
   |         relevant knowledge-base chunks + optional web search, then
   |         calls a provider adapter:
   |           -> Ollama (local, http://127.0.0.1:11434)
   |           -> OpenAI API (optional, needs OPENAI_API_KEY)
   |-- long-term memory: user-added facts, ranked by a lightweight TF-IDF
   |         style relevance score against the current message (see
   |         rank_by_relevance), not just "most recent"
   |-- document knowledge base: PDF/TXT/MD/CSV uploads are chunked
   |         (~1000 chars, 120 overlap) into document_chunks and the same
   |         relevance ranking picks the passages worth sending to the model
   |-- tasks/reminders: simple CRUD with due date + priority
   |-- dashboard: aggregate counts across the above
   `-- trading.py (mounted onto the same app):
          |-- academy: static lesson content + curated video links
          |-- market watch: live quotes via Yahoo Finance's public chart
          |         endpoint (query1.finance.yahoo.com), no API key
          `-- trading journal: per-user trade log + win-rate/P&L stats
   |
   v
SQLite (data/fk.db) — one file, per-user rows via user_id foreign keys
```

## Why no external JWT/bcrypt dependency

To keep `pip install -r requirements.txt` short and avoid native-build
headaches on Windows, auth uses only the Python standard library:
`hashlib.pbkdf2_hmac` for password hashing (200,000 iterations, salted) and
an HMAC-SHA256-signed, base64url token (header removed — it's just a signed
payload) instead of a full JWT library. A random secret is generated on
first run and persisted to `data/secret.key` (excluded from Git).

## Why keyword ranking instead of embeddings

Running a local embedding model would add a large, slow-to-install
dependency and, in the OpenAI-only case, per-call cost just to search a
handful of personal notes and documents. `rank_by_relevance` uses a small
TF-IDF-style scorer (term frequency weighted by inverse document frequency)
computed on the fly over the user's own memories/chunks — no extra
dependency, works offline, and is genuinely relevance-ranked rather than
"the last N items," which was the main limitation of v3's memory and
document context.
