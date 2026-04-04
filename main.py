import time, os, httpx, json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from database import init_db, get_conn

app = FastAPI()
app.add_middleware(CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

GEMINI_API_KEY = "AIzaSyCO5f1vVZQDIVDT1SEko-jVruRRkyocz3s" 
RATE_PER_MIN  = 6
RATE_PER_HOUR = 40
RATE_PER_DAY  = 150

init_db()

# ── Models ──────────────────────────────
class MemoryIn(BaseModel):
    question: str
    def_:     str = ""
    exp:      str = ""
    example:  str = ""
    tip:      str = ""
    subject:  str = "general"

class AskIn(BaseModel):
    question: str
    subject:  str = "all"

class CorrectIn(BaseModel):
    wrong:    str
    right:    str
    question: str = ""

# ── Rate limit check ────────────────────
def check_rate():
    conn = get_conn()
    now = int(time.time() * 1000)
    conn.execute("DELETE FROM api_calls WHERE time < ?", (now - 86400000,))
    conn.commit()
    per_min  = conn.execute("SELECT COUNT(*) FROM api_calls WHERE time > ?", (now-60000,)).fetchone()[0]
    per_hour = conn.execute("SELECT COUNT(*) FROM api_calls WHERE time > ?", (now-3600000,)).fetchone()[0]
    per_day  = conn.execute("SELECT COUNT(*) FROM api_calls").fetchone()[0]
    conn.close()
    if per_min  >= RATE_PER_MIN:  raise HTTPException(429, "Rate limit: 1 min")
    if per_hour >= RATE_PER_HOUR: raise HTTPException(429, "Rate limit: 1 hour")
    if per_day  >= RATE_PER_DAY:  raise HTTPException(429, "Rate limit: daily")

def record_call():
    conn = get_conn()
    conn.execute("INSERT INTO api_calls (time) VALUES (?)", (int(time.time()*1000),))
    conn.commit(); conn.close()

# ── Routes ──────────────────────────────
@app.get("/")
def root(): return {"status": "ARIA backend running — Gemini powered"}

@app.post("/learn")
def learn(m: MemoryIn):
    conn = get_conn()
    now = int(time.time()*1000)
    conn.execute("""INSERT INTO memories
        (question,def,exp,example,tip,subject,weight,uses,created,updated)
        VALUES (?,?,?,?,?,?,1.0,0,?,?)""",
        (m.question,m.def_,m.exp,m.example,m.tip,m.subject,now,now))
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    conn.close()
    return {"msg": f"Learned! Total: {total}"}

@app.get("/memories")
def get_memories(subject: str = "all"):
    conn = get_conn()
    if subject == "all":
        rows = conn.execute("SELECT * FROM memories ORDER BY created DESC").fetchall()
    else:
        rows = conn.execute("SELECT * FROM memories WHERE subject=? ORDER BY created DESC", (subject,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.delete("/memories/{id}")
def delete_memory(id: int):
    conn = get_conn()
    conn.execute("DELETE FROM memories WHERE id=?", (id,))
    conn.commit(); conn.close()
    return {"msg": "Deleted"}

@app.post("/ask")
async def ask(body: AskIn):
    # Step 1: Check local SQLite memories first
    conn = get_conn()
    q_words = set(body.question.lower().split())
    rows = conn.execute("SELECT * FROM memories" +
        (" WHERE subject=?" if body.subject != "all" else ""),
        (body.subject,) if body.subject != "all" else ()).fetchall()
    conn.close()

    best, best_score = None, 0
    for row in rows:
        row_words = set(row["question"].lower().split())
        score = len(q_words & row_words) / max(len(q_words | row_words), 1)
        if score > best_score:
            best_score, best = score, row

    if best and best_score >= 0.35:
        return {"source": "memory", "conf": best_score, "data": dict(best)}

    # Step 2: Fallback → Gemini API
    check_rate()
    record_call()

    prompt = f"""You are ARIA, a Class 10 study assistant for Indian students (CBSE/NCERT).
Answer ONLY in this exact JSON format, no markdown, no extra text:
{{"def":"short definition in 1 sentence","exp":"clear explanation in 2-3 sentences","ex":"a real example","tip":"one exam tip for students","subject":"maths or science or english or general"}}
Question: {body.question}"""

    # Gemini API call — using gemini-2.5-flash
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

    r = None
    async with httpx.AsyncClient() as client:
        r = await client.post(url,
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 800}
            },
            timeout=20)

    if not r or r.status_code != 200:
        raise HTTPException(500, f"Gemini API error: {r.text}")

    data = r.json()

    # Extract text from Gemini response
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError):
        raise HTTPException(500, "Gemini returned unexpected response format")

    # Parse JSON from response
    try:
        clean = text.replace("```json","").replace("```","").strip()
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        # If Gemini didn't return clean JSON, wrap it
        parsed = {"def": "", "exp": text, "ex": "", "tip": "", "subject": body.subject or "general"}

    parsed["structured"] = True

    # Auto-save to SQLite so ARIA learns it
    conn = get_conn()
    now = int(time.time()*1000)
    conn.execute("""INSERT INTO memories
        (question,def,exp,example,tip,subject,weight,uses,created,updated)
        VALUES (?,?,?,?,?,?,1.0,0,?,?)""",
        (body.question,
         parsed.get("def",""),
         parsed.get("exp",""),
         parsed.get("ex",""),
         parsed.get("tip",""),
         parsed.get("subject","general"),
         now, now))
    conn.commit()
    conn.close()

    return {"source": "gemini-api", "conf": 0.9, "data": parsed}

@app.post("/correct")
def correct(c: CorrectIn):
    conn = get_conn()
    now = int(time.time()*1000)
    conn.execute("INSERT INTO corrections (wrong,right,question,time) VALUES (?,?,?,?)",
        (c.wrong, c.right, c.question, now))
    conn.execute("UPDATE memories SET def=? WHERE def LIKE ?", (c.right, f"%{c.wrong}%"))
    conn.commit(); conn.close()
    return {"msg": "Corrected!"}

@app.get("/stats")
def stats():
    conn = get_conn()
    memories = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    facts    = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    now = int(time.time()*1000)
    api_today = conn.execute("SELECT COUNT(*) FROM api_calls WHERE time > ?",
        (now-86400000,)).fetchone()[0]
    conn.close()
    return {"memories": memories, "facts": facts, "api_calls_today": api_today}
