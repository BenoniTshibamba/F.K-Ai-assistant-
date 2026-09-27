"""
F.K. AI Assistant — v4
Core backend: accounts/auth, conversations & chat, long-term memory,
document knowledge base, tasks/reminders, dashboard, personality/voice
profile. The Trading Academy / Market Watch / Trading Journal endpoints
live in trading.py and are mounted onto this same app below.
"""
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pypdf import PdfReader

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - openai is an optional provider
    OpenAI = None

load_dotenv()

# --------------------------------------------------------------------------
# Paths / config
# --------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "uploads"
DATA_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "fk.db"
SECRET_PATH = DATA_DIR / "secret.key"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
WEB_SEARCH_ENABLED = os.getenv("WEB_SEARCH_ENABLED", "true").lower() == "true"
TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days

if SECRET_PATH.exists():
    APP_SECRET = SECRET_PATH.read_text().strip()
else:
    APP_SECRET = secrets.token_hex(32)
    SECRET_PATH.write_text(APP_SECRET)

PERSONALITY_PRESETS = {
    "professional": "Be polished, efficient and precise. Prefer structured, "
                    "no-nonsense answers.",
    "friendly": "Be warm, encouraging and conversational, like a supportive "
                "friend who happens to be very knowledgeable.",
    "direct": "Be terse and blunt. Skip pleasantries. Give the answer first, "
              "reasoning only if asked.",
    "creative": "Be imaginative and expressive. Use vivid language and "
                "analogies while staying accurate.",
    "trading_coach": "You are also an experienced, risk-aware trading "
                      "mentor. Explain markets, strategies and terminology "
                      "clearly and honestly, including the downside of "
                      "every approach. Never present a specific trade as a "
                      "guaranteed or personalized recommendation, never "
                      "promise profits, and note that markets involve real "
                      "risk of loss. You are an educational guide, not a "
                      "licensed financial advisor and not a broker.",
}

BASE_SYSTEM_PROMPT = """You are {name}, a professional personal AI assistant.
Be natural, helpful, direct and practical.
Use clear formatting when useful.
Never claim to have completed an action unless you actually completed it.
If information is uncertain, say so.
When document context is supplied, use it carefully and distinguish it from your general knowledge.
{personality}
"""

app = FastAPI(title="F.K. AI Assistant", version="4.0.0")


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def now():
    return datetime.now(timezone.utc).isoformat()


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def new_id():
    return str(uuid.uuid4())


STOPWORDS = set(
    "a an the of to in on for and or is are was were be been being this "
    "that these those it its as at by from with without into onto not no "
    "do does did doing have has had having i you he she we they my your "
    "his her our their me him them what which who whom will would shall "
    "should can could may might must if then than so but".split()
)


def tokenize(text):
    return [w for w in re.findall(r"[a-zA-ZÀ-ÿ0-9']+", (text or "").lower()) if w not in STOPWORDS and len(w) > 1]


def rank_by_relevance(query, candidates, top_k=6):
    """Lightweight TF-IDF style ranking so 'long-term memory' and the
    document knowledge base retrieve what's actually relevant instead of
    just 'the last N things'. candidates: list of (id, text). Returns a
    list of ids ordered by relevance (best first), only those with score>0.
    """
    q_tokens = set(tokenize(query))
    if not q_tokens or not candidates:
        return []
    doc_tokens = {cid: Counter(tokenize(text)) for cid, text in candidates}
    df = Counter()
    for toks in doc_tokens.values():
        for t in set(toks):
            df[t] += 1
    n_docs = len(doc_tokens)
    scores = {}
    for cid, toks in doc_tokens.items():
        score = 0.0
        for t in q_tokens:
            if t in toks:
                idf = math.log((n_docs + 1) / (df[t] + 1)) + 1
                score += toks[t] * idf
        if score > 0:
            scores[cid] = score
    ranked = sorted(scores, key=lambda c: scores[c], reverse=True)
    return ranked[:top_k]


# --------------------------------------------------------------------------
# Database schema
# --------------------------------------------------------------------------
def init_db():
    conn = db()
    conn.executescript(
        """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        assistant_name TEXT NOT NULL DEFAULT 'F.K.',
        personality_preset TEXT NOT NULL DEFAULT 'professional',
        personality_custom TEXT NOT NULL DEFAULT '',
        voice_name TEXT NOT NULL DEFAULT '',
        voice_rate REAL NOT NULL DEFAULT 1.0,
        voice_pitch REAL NOT NULL DEFAULT 1.0,
        is_guest INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        content TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'general',
        importance INTEGER NOT NULL DEFAULT 3,
        created_at TEXT NOT NULL,
        last_used_at TEXT
    );
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        name TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS document_chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id INTEGER NOT NULL,
        user_id TEXT NOT NULL,
        chunk_index INTEGER NOT NULL,
        content TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        notes TEXT NOT NULL DEFAULT '',
        due_at TEXT,
        priority TEXT NOT NULL DEFAULT 'medium',
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        completed_at TEXT
    );
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        direction TEXT NOT NULL DEFAULT 'long',
        entry_price REAL NOT NULL,
        exit_price REAL,
        quantity REAL NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'open',
        entry_at TEXT NOT NULL,
        exit_at TEXT,
        notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS watchlist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(user_id, symbol)
    );
    """
    )
    conn.commit()
    # Migration guard: databases created before is_guest existed.
    cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "is_guest" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN is_guest INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    conn.close()


init_db()


# --------------------------------------------------------------------------
# Auth (bcrypt-free: PBKDF2-HMAC-SHA256, stdlib only, no extra native deps)
# --------------------------------------------------------------------------
def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
    return digest.hex(), salt


def verify_password(password, salt, expected_hash):
    digest, _ = hash_password(password, salt)
    return hmac.compare_digest(digest, expected_hash)


def _b64(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64d(data: str) -> bytes:
    import base64
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def create_token(user_id):
    payload = {"uid": user_id, "exp": int(time.time()) + TOKEN_TTL_SECONDS}
    body = _b64(json.dumps(payload).encode())
    sig = _b64(hmac.new(APP_SECRET.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def decode_token(token):
    try:
        body, sig = token.split(".")
        expected_sig = _b64(hmac.new(APP_SECRET.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload = json.loads(_b64d(body))
        if payload.get("exp", 0) < time.time():
            return None
        return payload.get("uid")
    except Exception:
        return None


def get_current_user(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    token = authorization.removeprefix("Bearer ").strip()
    uid = decode_token(token)
    if not uid:
        raise HTTPException(401, "Session expired, please log in again")
    conn = db()
    row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(401, "Account not found")
    return dict(row)


# --------------------------------------------------------------------------
# Pydantic models
# --------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class ClaimRequest(BaseModel):
    username: str
    password: str


class ProfileUpdateRequest(BaseModel):
    assistant_name: str | None = None
    personality_preset: str | None = None
    personality_custom: str | None = None
    voice_name: str | None = None
    voice_rate: float | None = None
    voice_pitch: float | None = None


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str
    provider: str = "ollama"
    use_web: bool = False
    use_memory: bool = True
    use_kb: bool = True
    trading_mode: bool = False
    document_ids: list[int] = []


class MemoryRequest(BaseModel):
    content: str
    category: str = "general"
    importance: int = 3


class ConversationTitleRequest(BaseModel):
    title: str


class TaskRequest(BaseModel):
    title: str
    notes: str = ""
    due_at: str | None = None
    priority: str = "medium"


class TaskUpdateRequest(BaseModel):
    title: str | None = None
    notes: str | None = None
    due_at: str | None = None
    priority: str | None = None
    status: str | None = None


# --------------------------------------------------------------------------
# Conversation / message helpers
# --------------------------------------------------------------------------
def create_conversation(user_id, title="New conversation"):
    cid = new_id()
    conn = db()
    conn.execute(
        "INSERT INTO conversations VALUES (?, ?, ?, ?, ?)",
        (cid, user_id, title, now(), now()),
    )
    conn.commit()
    conn.close()
    return cid


def add_message(cid, user_id, role, content):
    conn = db()
    conn.execute(
        "INSERT INTO messages(conversation_id, user_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        (cid, user_id, role, content, now()),
    )
    conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now(), cid))
    conn.commit()
    conn.close()


def get_messages(cid, user_id):
    conn = db()
    rows = conn.execute(
        "SELECT role, content, created_at FROM messages WHERE conversation_id=? AND user_id=? ORDER BY id",
        (cid, user_id),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def search_web(query):
    if not WEB_SEARCH_ENABLED:
        return ""
    try:
        r = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        r.raise_for_status()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")
        results = []
        for item in soup.select(".result")[:5]:
            title = item.select_one(".result__title")
            snippet = item.select_one(".result__snippet")
            link = item.select_one(".result__url")
            if title and snippet:
                results.append(
                    f"- {title.get_text(' ', strip=True)}\n"
                    f"  {snippet.get_text(' ', strip=True)}\n"
                    f"  {link.get_text(' ', strip=True) if link else ''}"
                )
        return "\n".join(results)
    except Exception:
        return ""


def get_memory_context(user_id, query):
    conn = db()
    rows = conn.execute(
        "SELECT id, content, importance FROM memories WHERE user_id=?", (user_id,)
    ).fetchall()
    conn.close()
    if not rows:
        return ""
    candidates = [(r["id"], r["content"]) for r in rows]
    ranked_ids = rank_by_relevance(query, candidates, top_k=8)
    by_id = {r["id"]: r for r in rows}
    # Always weave in a couple of high-importance memories even if the
    # keyword match misses them (name, standing preferences, etc.)
    important_ids = [r["id"] for r in sorted(rows, key=lambda r: -r["importance"])[:3]]
    chosen = list(dict.fromkeys(ranked_ids + important_ids))[:10]
    if not chosen:
        return ""
    conn = db()
    conn.executemany(
        "UPDATE memories SET last_used_at=? WHERE id=?",
        [(now(), cid) for cid in chosen],
    )
    conn.commit()
    conn.close()
    return "\n".join(f"- {by_id[c]['content']}" for c in chosen if c in by_id)


def get_document_context(user_id, query, document_ids, use_kb):
    conn = db()
    if document_ids:
        placeholders = ",".join("?" for _ in document_ids)
        rows = conn.execute(
            f"SELECT dc.content, d.name FROM document_chunks dc "
            f"JOIN documents d ON d.id = dc.document_id "
            f"WHERE dc.user_id=? AND dc.document_id IN ({placeholders})",
            (user_id, *document_ids),
        ).fetchall()
    elif use_kb:
        rows = conn.execute(
            "SELECT dc.content, d.name FROM document_chunks dc "
            "JOIN documents d ON d.id = dc.document_id WHERE dc.user_id=?",
            (user_id,),
        ).fetchall()
    else:
        rows = []
    conn.close()
    if not rows:
        return ""
    candidates = [(i, r["content"]) for i, r in enumerate(rows)]
    ranked = rank_by_relevance(query, candidates, top_k=5)
    if not ranked and document_ids:
        # explicit selection with no keyword overlap: still include a slice
        ranked = list(range(min(3, len(rows))))
    chunks = [f"From \"{rows[i]['name']}\":\n{rows[i]['content']}" for i in ranked]
    return "\n\n".join(chunks)


def chunk_text(text, size=1000, overlap=120):
    text = re.sub(r"\s+", " ", text).strip()
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks or [""]


def build_messages(cid, user, request: ChatRequest):
    personality_bits = []
    preset = request and getattr(request, "personality_preset", None)
    personality_key = user.get("personality_preset", "professional")
    personality_bits.append(PERSONALITY_PRESETS.get(personality_key, PERSONALITY_PRESETS["professional"]))
    if user.get("personality_custom"):
        personality_bits.append("Additional instructions from the user: " + user["personality_custom"])
    if request.trading_mode:
        personality_bits.append(PERSONALITY_PRESETS["trading_coach"])
        personality_bits.append(
            "TRADING DISCLAIMER TO KEEP IN MIND: you are not a licensed "
            "financial advisor or broker. Provide education, definitions, "
            "and general reasoning about strategies and risk, not "
            "individualized buy/sell recommendations or price predictions. "
            "When it's relevant, remind the user that trading carries risk "
            "of loss."
        )
    system = BASE_SYSTEM_PROMPT.format(
        name=user.get("assistant_name") or "F.K.",
        personality=" ".join(personality_bits),
    )
    context_parts = [system]
    if request.use_memory:
        memory = get_memory_context(user["id"], request.message)
        if memory:
            context_parts.append("LONG-TERM MEMORY ABOUT THIS USER (only use what's relevant):\n" + memory)
    docs = get_document_context(user["id"], request.message, request.document_ids, request.use_kb)
    if docs:
        context_parts.append("KNOWLEDGE BASE CONTEXT:\n" + docs)
    if request.use_web:
        web = search_web(request.message)
        if web:
            context_parts.append("WEB SEARCH RESULTS:\n" + web)
    system_full = "\n\n".join(context_parts)
    history = get_messages(cid, user["id"])[-20:]
    messages = [{"role": "system", "content": system_full}]
    messages.extend({"role": x["role"], "content": x["content"]} for x in history)
    return messages


def ask_ollama(messages):
    r = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={"model": OLLAMA_MODEL, "messages": messages, "stream": False},
        timeout=180,
    )
    r.raise_for_status()
    data = r.json()
    return data["message"]["content"]


def ask_openai(messages):
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured in .env.")
    if OpenAI is None:
        raise RuntimeError("The openai package is not installed.")
    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(model=OPENAI_MODEL, messages=messages)
    return response.choices[0].message.content


# --------------------------------------------------------------------------
# Static frontend
# --------------------------------------------------------------------------
@app.get("/")
def home():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/config")
def config():
    ollama_online = False
    try:
        requests.get(f"{OLLAMA_URL}/api/tags", timeout=3).raise_for_status()
        ollama_online = True
    except Exception:
        pass
    return {
        "ollama": {"model": OLLAMA_MODEL, "online": ollama_online},
        "openai": {"configured": bool(OPENAI_API_KEY), "model": OPENAI_MODEL},
        "web_search": WEB_SEARCH_ENABLED,
    }


# --------------------------------------------------------------------------
# Auth endpoints
# --------------------------------------------------------------------------
@app.post("/api/auth/register")
def register(body: RegisterRequest):
    username = body.username.strip().lower()
    if len(username) < 3:
        raise HTTPException(400, "Username must be at least 3 characters.")
    if len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters.")
    conn = db()
    exists = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if exists:
        conn.close()
        raise HTTPException(409, "That username is already taken.")
    uid = new_id()
    pw_hash, salt = hash_password(body.password)
    conn.execute(
        "INSERT INTO users(id, username, password_hash, salt, created_at) VALUES (?, ?, ?, ?, ?)",
        (uid, username, pw_hash, salt, now()),
    )
    conn.commit()
    conn.close()
    return {"token": create_token(uid), "username": username}


@app.post("/api/auth/login")
def login(body: LoginRequest):
    username = body.username.strip().lower()
    conn = db()
    row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    conn.close()
    if not row or not verify_password(body.password, row["salt"], row["password_hash"]):
        raise HTTPException(401, "Incorrect username or password.")
    return {"token": create_token(row["id"]), "username": row["username"]}


@app.post("/api/auth/guest")
def guest_login():
    """No login required to use F.K. Each browser/device gets its own
    private local account automatically, created the first time the app
    loads and stored via a token in localStorage. The person can later
    turn this into a named account with a password (see /api/auth/claim)
    or log into an existing one — logging in is optional, never required."""
    uid = new_id()
    username = f"guest-{uid[:8]}"
    pw_hash, salt = hash_password(secrets.token_hex(16))
    conn = db()
    conn.execute(
        "INSERT INTO users(id, username, password_hash, salt, is_guest, created_at) VALUES (?, ?, ?, ?, 1, ?)",
        (uid, username, pw_hash, salt, now()),
    )
    conn.commit()
    conn.close()
    return {"token": create_token(uid), "username": username, "is_guest": True}


@app.post("/api/auth/claim")
def claim_account(body: ClaimRequest, user=Depends(get_current_user)):
    """Turn the current (usually guest) account into a named account with
    a real username/password, keeping all its existing data."""
    username = body.username.strip().lower()
    if len(username) < 3:
        raise HTTPException(400, "Username must be at least 3 characters.")
    if len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters.")
    conn = db()
    exists = conn.execute(
        "SELECT id FROM users WHERE username=? AND id!=?", (username, user["id"])
    ).fetchone()
    if exists:
        conn.close()
        raise HTTPException(409, "That username is already taken.")
    pw_hash, salt = hash_password(body.password)
    conn.execute(
        "UPDATE users SET username=?, password_hash=?, salt=?, is_guest=0 WHERE id=?",
        (username, pw_hash, salt, user["id"]),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "username": username}


@app.get("/api/auth/me")
def me(user=Depends(get_current_user)):
    return {
        "username": user["username"],
        "is_guest": bool(user["is_guest"]),
        "assistant_name": user["assistant_name"],
        "personality_preset": user["personality_preset"],
        "personality_custom": user["personality_custom"],
        "voice_name": user["voice_name"],
        "voice_rate": user["voice_rate"],
        "voice_pitch": user["voice_pitch"],
    }


@app.patch("/api/auth/me")
def update_me(body: ProfileUpdateRequest, user=Depends(get_current_user)):
    fields, values = [], []
    for key in ("assistant_name", "personality_preset", "personality_custom", "voice_name", "voice_rate", "voice_pitch"):
        val = getattr(body, key)
        if val is not None:
            fields.append(f"{key}=?")
            values.append(val)
    if fields:
        conn = db()
        conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id=?", (*values, user["id"]))
        conn.commit()
        conn.close()
    return {"ok": True}


# --------------------------------------------------------------------------
# Conversations & chat
# --------------------------------------------------------------------------
@app.get("/api/conversations")
def conversations(user=Depends(get_current_user)):
    conn = db()
    rows = conn.execute(
        "SELECT id, title, created_at, updated_at FROM conversations WHERE user_id=? ORDER BY updated_at DESC",
        (user["id"],),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/conversations")
def new_conversation(user=Depends(get_current_user)):
    cid = create_conversation(user["id"])
    return {"id": cid}


@app.patch("/api/conversations/{cid}")
def rename_conversation(cid: str, body: ConversationTitleRequest, user=Depends(get_current_user)):
    conn = db()
    cur = conn.execute(
        "UPDATE conversations SET title=?, updated_at=? WHERE id=? AND user_id=?",
        (body.title.strip() or "New conversation", now(), cid, user["id"]),
    )
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "Conversation not found")
    return {"ok": True}


@app.delete("/api/conversations/{cid}")
def delete_conversation(cid: str, user=Depends(get_current_user)):
    conn = db()
    conn.execute("DELETE FROM messages WHERE conversation_id=? AND user_id=?", (cid, user["id"]))
    cur = conn.execute("DELETE FROM conversations WHERE id=? AND user_id=?", (cid, user["id"]))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "Conversation not found")
    return {"ok": True}


@app.get("/api/conversations/{cid}/messages")
def conversation_messages(cid: str, user=Depends(get_current_user)):
    return get_messages(cid, user["id"])


@app.post("/api/chat")
def chat(request: ChatRequest, user=Depends(get_current_user)):
    if not request.message.strip():
        raise HTTPException(400, "Message cannot be empty.")
    cid = request.conversation_id
    if cid:
        conn = db()
        exists = conn.execute(
            "SELECT id FROM conversations WHERE id=? AND user_id=?", (cid, user["id"])
        ).fetchone()
        conn.close()
        if not exists:
            cid = None
    if not cid:
        cid = create_conversation(user["id"], request.message[:45])

    add_message(cid, user["id"], "user", request.message.strip())
    messages = build_messages(cid, user, request)
    try:
        if request.provider == "openai":
            answer = ask_openai(messages)
        else:
            answer = ask_ollama(messages)
    except requests.exceptions.ConnectionError:
        raise HTTPException(503, "F.K. cannot reach Ollama. Start Ollama or switch to ChatGPT.")
    except requests.exceptions.Timeout:
        raise HTTPException(504, "The local AI took too long to respond.")
    except Exception as exc:
        raise HTTPException(500, str(exc))

    add_message(cid, user["id"], "assistant", answer)
    return {"conversation_id": cid, "answer": answer}


# --------------------------------------------------------------------------
# Long-term memory
# --------------------------------------------------------------------------
@app.get("/api/memories")
def memories(user=Depends(get_current_user)):
    conn = db()
    rows = conn.execute(
        "SELECT id, content, category, importance, created_at, last_used_at FROM memories "
        "WHERE user_id=? ORDER BY importance DESC, id DESC",
        (user["id"],),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/memories")
def add_memory(request: MemoryRequest, user=Depends(get_current_user)):
    if not request.content.strip():
        raise HTTPException(400, "Memory cannot be empty.")
    importance = max(1, min(5, request.importance))
    conn = db()
    cur = conn.execute(
        "INSERT INTO memories(user_id, content, category, importance, created_at) VALUES (?, ?, ?, ?, ?)",
        (user["id"], request.content.strip(), request.category.strip() or "general", importance, now()),
    )
    conn.commit()
    mid = cur.lastrowid
    conn.close()
    return {"id": mid, "content": request.content.strip()}


@app.delete("/api/memories/{mid}")
def delete_memory(mid: int, user=Depends(get_current_user)):
    conn = db()
    conn.execute("DELETE FROM memories WHERE id=? AND user_id=?", (mid, user["id"]))
    conn.commit()
    conn.close()
    return {"ok": True}


# --------------------------------------------------------------------------
# Document knowledge base
# --------------------------------------------------------------------------
@app.get("/api/documents")
def documents(user=Depends(get_current_user)):
    conn = db()
    rows = conn.execute(
        "SELECT d.id, d.name, d.created_at, COUNT(dc.id) as chunk_count FROM documents d "
        "LEFT JOIN document_chunks dc ON dc.document_id = d.id "
        "WHERE d.user_id=? GROUP BY d.id ORDER BY d.id DESC",
        (user["id"],),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/documents")
async def upload_document(file: UploadFile = File(...), user=Depends(get_current_user)):
    name = file.filename or "document"
    data = await file.read()
    suffix = Path(name).suffix.lower()
    try:
        if suffix == ".pdf":
            temp = UPLOAD_DIR / f"{uuid.uuid4()}.pdf"
            temp.write_bytes(data)
            reader = PdfReader(str(temp))
            content = "\n".join(page.extract_text() or "" for page in reader.pages)
            temp.unlink(missing_ok=True)
        elif suffix in {".txt", ".md", ".csv"}:
            content = data.decode("utf-8", errors="ignore")
        else:
            raise HTTPException(400, "Supported files: PDF, TXT, MD, CSV.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"Could not read document: {exc}")

    if not content.strip():
        raise HTTPException(400, "The document appears to contain no readable text.")

    conn = db()
    cur = conn.execute(
        "INSERT INTO documents(user_id, name, created_at) VALUES (?, ?, ?)",
        (user["id"], name, now()),
    )
    did = cur.lastrowid
    chunks = chunk_text(content, size=1000, overlap=120)[:200]
    conn.executemany(
        "INSERT INTO document_chunks(document_id, user_id, chunk_index, content) VALUES (?, ?, ?, ?)",
        [(did, user["id"], i, c) for i, c in enumerate(chunks)],
    )
    conn.commit()
    conn.close()
    return {"id": did, "name": name, "chunks": len(chunks)}


@app.delete("/api/documents/{did}")
def delete_document(did: int, user=Depends(get_current_user)):
    conn = db()
    conn.execute("DELETE FROM document_chunks WHERE document_id=? AND user_id=?", (did, user["id"]))
    conn.execute("DELETE FROM documents WHERE id=? AND user_id=?", (did, user["id"]))
    conn.commit()
    conn.close()
    return {"ok": True}


# --------------------------------------------------------------------------
# Tasks / reminders
# --------------------------------------------------------------------------
@app.get("/api/tasks")
def list_tasks(status: str | None = None, user=Depends(get_current_user)):
    conn = db()
    if status:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE user_id=? AND status=? ORDER BY (due_at IS NULL), due_at ASC",
            (user["id"], status),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE user_id=? ORDER BY (due_at IS NULL), due_at ASC",
            (user["id"],),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/tasks")
def create_task(body: TaskRequest, user=Depends(get_current_user)):
    if not body.title.strip():
        raise HTTPException(400, "Task title cannot be empty.")
    conn = db()
    cur = conn.execute(
        "INSERT INTO tasks(user_id, title, notes, due_at, priority, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, 'pending', ?)",
        (user["id"], body.title.strip(), body.notes.strip(), body.due_at, body.priority, now()),
    )
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return {"id": tid}


@app.patch("/api/tasks/{tid}")
def update_task(tid: int, body: TaskUpdateRequest, user=Depends(get_current_user)):
    fields, values = [], []
    for key in ("title", "notes", "due_at", "priority", "status"):
        val = getattr(body, key)
        if val is not None:
            fields.append(f"{key}=?")
            values.append(val)
    if body.status == "done":
        fields.append("completed_at=?")
        values.append(now())
    elif body.status == "pending":
        fields.append("completed_at=NULL")
    if not fields:
        return {"ok": True}
    conn = db()
    cur = conn.execute(
        f"UPDATE tasks SET {', '.join(fields)} WHERE id=? AND user_id=?",
        (*values, tid, user["id"]),
    )
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "Task not found")
    return {"ok": True}


@app.delete("/api/tasks/{tid}")
def delete_task(tid: int, user=Depends(get_current_user)):
    conn = db()
    conn.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (tid, user["id"]))
    conn.commit()
    conn.close()
    return {"ok": True}


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
@app.get("/api/dashboard")
def dashboard(user=Depends(get_current_user)):
    conn = db()
    uid = user["id"]
    conv_count = conn.execute("SELECT COUNT(*) c FROM conversations WHERE user_id=?", (uid,)).fetchone()["c"]
    msg_count = conn.execute("SELECT COUNT(*) c FROM messages WHERE user_id=?", (uid,)).fetchone()["c"]
    mem_count = conn.execute("SELECT COUNT(*) c FROM memories WHERE user_id=?", (uid,)).fetchone()["c"]
    doc_count = conn.execute("SELECT COUNT(*) c FROM documents WHERE user_id=?", (uid,)).fetchone()["c"]
    pending = conn.execute(
        "SELECT COUNT(*) c FROM tasks WHERE user_id=? AND status='pending'", (uid,)
    ).fetchone()["c"]
    overdue = conn.execute(
        "SELECT COUNT(*) c FROM tasks WHERE user_id=? AND status='pending' AND due_at IS NOT NULL AND due_at < ?",
        (uid, now()),
    ).fetchone()["c"]
    upcoming = conn.execute(
        "SELECT id, title, due_at, priority FROM tasks WHERE user_id=? AND status='pending' "
        "ORDER BY (due_at IS NULL), due_at ASC LIMIT 5",
        (uid,),
    ).fetchall()
    open_trades = conn.execute(
        "SELECT COUNT(*) c FROM trades WHERE user_id=? AND status='open'", (uid,)
    ).fetchone()["c"]
    conn.close()
    return {
        "conversations": conv_count,
        "messages": msg_count,
        "memories": mem_count,
        "documents": doc_count,
        "tasks_pending": pending,
        "tasks_overdue": overdue,
        "upcoming_tasks": [dict(r) for r in upcoming],
        "open_trades": open_trades,
    }


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------
@app.get("/api/export/{cid}")
def export_conversation(cid: str, user=Depends(get_current_user)):
    conn = db()
    conv = conn.execute(
        "SELECT * FROM conversations WHERE id=? AND user_id=?", (cid, user["id"])
    ).fetchone()
    msgs = conn.execute(
        "SELECT role, content, created_at FROM messages WHERE conversation_id=? AND user_id=? ORDER BY id",
        (cid, user["id"]),
    ).fetchall()
    conn.close()
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return {"conversation": dict(conv), "messages": [dict(x) for x in msgs]}


# --------------------------------------------------------------------------
# Mount the trading module (Market Watch, journal, academy content)
# --------------------------------------------------------------------------
import trading  # noqa: E402

trading.register(app, db, now, get_current_user)
