import os
import json
import threading
import time as _time
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


from fastapi_pagination import add_pagination, paginate
from fastapi_pagination.limit_offset import LimitOffsetPage

DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")
LOCK = threading.Lock()

def _ensure_db():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({"notes": [], "next_id": 1}, f, ensure_ascii=False, indent=2)

def load_db():
    _ensure_db()
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(db):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=2000)
    tags: List[str] = []

class NoteOut(NoteIn):
    id: int
    created_at: float

app = FastAPI(
    title="LAB03 - Notes API (API Key + Pagination)",
    description="CRUD notatek + prosty X-API-Key + paginacja (limit/offset), q, sort asc/desc po created_at.",
    version="0.1.0",
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.middleware("http")
async def timing_header(request: Request, call_next):
    start = _time.perf_counter()
    resp = await call_next(request)
    dur_ms = (_time.perf_counter() - start) * 1000.0
    resp.headers["X-Process-Time"] = f"{dur_ms:.2f}ms"
    return resp


API_KEY = os.getenv("API_KEY", "secret") #Apikey zabezpieczone za pomocą .gitignore

@app.middleware("http")
async def api_key_guard(request: Request, call_next):
    if request.url.path.startswith("/notes"):
        provided = request.headers.get("X-API-Key")
        if provided != API_KEY:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized (X-API-Key)"})
    return await call_next(request)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/notes")
def list_notes(
    q: str | None = None,
    sort: str = "desc",
    limit: int = Query(10, ge=1),
    offset: int = Query(0, ge=0)
):
    db = load_db()
    data = db["notes"]

    # filtracja po q
    if q:
        ql = q.lower()
        data = [
            n for n in data
            if ql in n["title"].lower()
            or ql in n["content"].lower()
            or any(ql in t.lower() for t in n.get("tags", []))
        ]

    # sortowanie po created_at
    data = sorted(data, key=lambda n: n["created_at"], reverse=(sort == "desc"))

    # paginacja ręczna
    items = data[offset: offset + limit]

    return {
        "limit": limit,
        "offset": offset,
        "total": len(data),
        "count": len(items),
        "items": items
    }

@app.get("/notes/{note_id}", response_model=NoteOut)
def get_note(note_id: int):
    db = load_db()
    for n in db["notes"]:
        if n["id"] == note_id:
            return n
    raise HTTPException(status_code=404, detail="Note not found")

@app.post("/notes", response_model=NoteOut, status_code=201)
def create_note(note: NoteIn):
    with LOCK:
        db = load_db()
        new_id = int(db.get("next_id", 1))
        rec = {"id": new_id, "created_at": _time.time(), **note.dict()}
        db["notes"].append(rec)
        db["next_id"] = new_id + 1
        save_db(db)
        return rec

@app.put("/notes/{note_id}", response_model=NoteOut)
def update_note(note_id: int, note: NoteIn):
    with LOCK:
        db = load_db()
        for i, n in enumerate(db["notes"]):
            if n["id"] == note_id:
                updated = {"id": note_id, "created_at": n["created_at"], **note.dict()}
                db["notes"][i] = updated
                save_db(db)
                return updated
    raise HTTPException(status_code=404, detail="Note not found")

@app.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: int):
    with LOCK:
        db = load_db()
        for i, n in enumerate(db["notes"]):
            if n["id"] == note_id:
                db["notes"].pop(i)
                save_db(db)
                return
    raise HTTPException(status_code=404, detail="Note not found")
