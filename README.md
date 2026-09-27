# F.K. AI Assistant v4

A personal AI assistant you run on your own machine, with two AI providers:

- **Ollama** — local, private, and free
- **ChatGPT / OpenAI API** — cloud AI when an API key is configured

## What's new in v4

- **Accounts — login is optional.** F.K. opens straight into the assistant;
  the first time it loads it quietly creates a private local "guest" account
  for that browser, so every feature works immediately with no sign-up. The
  **👤 Guest** button top-right opens the account panel any time, where you
  can turn that guest account into a real username/password ("Save this
  account", so it survives clearing your browser data or moving to a
  different one), or log into an existing account. Either way, conversations,
  memories, documents, tasks and trades are private to whichever account is
  active (useful if more than one person shares the same install).
- **Long-term intelligent memory** — memories are ranked by relevance to what
  you're currently asking (not just "the last 20 things"), plus you can mark
  a memory as high importance so it's always considered.
- **A real document knowledge base** — upload PDFs/TXT/MD/CSV files; they're
  automatically split into chunks, and F.K. pulls in only the passages
  relevant to your question instead of dumping the whole file in.
- **Task & reminder management** — a Tasks tab with due dates and priority,
  summarized on the Dashboard.
- **Customizable personality & voice** — pick a personality preset (or write
  your own instructions), rename the assistant, and choose a browser voice,
  rate and pitch for spoken responses.
- **A proper dashboard** — conversation/message counts, memory & document
  counts, open trades, and upcoming tasks at a glance.
- **Trading section** — a self-contained learning corner:
  - **Lessons**: market basics, order types, technical analysis, risk
    management, psychology, trading styles, options basics, and a glossary.
  - **Video resources**: links to well-known, free educational YouTube
    channels (Investopedia, The Plain Bagel, Rayner Teo, Adam Khoo, Warrior
    Trading).
  - **Market Watch**: a personal watchlist with live quotes (via Yahoo
    Finance's public data feed — works for stocks, indexes, FX pairs like
    `EURUSD=X`, and crypto like `BTC-USD`; no API key needed).
  - **Trading Journal**: log your own trades and see win rate / P&L stats.
  - A **Trading mode** toggle in chat turns F.K. into a risk-aware trading
    tutor for that message — it explains concepts and reasoning, it does
    not hand out personalized buy/sell calls. This app is educational and
    is not a broker, and it doesn't place real trades.

All the v3 features are still here: persistent SQLite storage, conversation
sidebar, browser voice input/output, export conversation as JSON, and no API
key hard-coded in the source.

## Install

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

(macOS/Linux: `python3 -m venv .venv && source .venv/bin/activate`)

### Ollama (optional, for free local AI)

Install Ollama, then:

```powershell
ollama pull llama3.2:3b
```

Make sure Ollama is running before you chat with the Ollama provider selected.

### OpenAI (optional, for ChatGPT)

Copy `.env.example` to `.env`:

```powershell
copy .env.example .env
```

Then put your API key in `.env`:

```env
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-5-mini
```

Do not commit `.env`.

## Start F.K.

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

Open **http://127.0.0.1:8000** in your browser — you're straight into the
assistant, no sign-up needed. Everything is stored only in your own
`data/fk.db` — nothing is sent anywhere except to whichever AI provider you
pick per message.

### "Failed to fetch" or an unresponsive page

F.K. is a web app with a Python backend — it only works while `uvicorn` is
running and you're viewing it at `http://127.0.0.1:8000` (not by
double-clicking `index.html` directly, which opens it with no server behind
it and every button will silently fail). If the header says "Server
unavailable", start (or restart) the `uvicorn` command above and refresh the
page.

## GitHub

```powershell
git init
git add .
git commit -m "Build F.K. AI Assistant v4"
git branch -M main
git remote add origin YOUR_GITHUB_REPOSITORY_URL
git push -u origin main
```

## Notes

- Ollama runs models locally. OpenAI API usage can incur charges depending on
  your account and usage. Browser voice features depend on browser support
  (Chrome/Edge have the best coverage).
- Market quotes come from a free, public data endpoint and can occasionally
  be rate-limited or briefly unavailable — that's handled gracefully in the
  UI rather than breaking the page.
- **The Trading section is educational.** It is not financial advice, F.K.
  is not a licensed advisor or broker, and nothing in the app places real
  trades. Trading involves real risk of loss.
- The SQLite database (`data/fk.db`) and your auth secret (`data/secret.key`)
  are intentionally ignored by Git so personal data and credentials stay
  local to your machine.
