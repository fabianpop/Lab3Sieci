import os
import json
import threading
import time as _time
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
# Import 'date' dla due_date
from datetime import date

from fastapi_pagination import Page, paginate, add_pagination

DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")
LOCK = threading.Lock()


def _ensure_db():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            # Używamy klucza "notes" dla kompatybilności z istniejącymi funkcjami load_db/save_db
            json.dump({"notes": [], "next_id": 1}, f, ensure_ascii=False, indent=2)


def load_db():
    _ensure_db()
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(db):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


# Zmienione modele z NoteIn/NoteOut na TaskIn/TaskOut
class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    done: bool = False  # Nowe pole
    priority: int = Field(ge=1, le=5)  # Nowe pole
    labels: List[str] = []  # Zmienione tags na labels
    due_date: Optional[date] = None  # Opcjonalne pole


class TaskOut(TaskIn):
    id: int
    created_at: float


app = FastAPI(
    title="LAB03 - Tasks API (API Key + Pagination)",  # Zmieniony tytuł
    description="CRUD Zadań + prosty X-API-Key + paginacja, q, sort asc/desc po created_at.",
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


API_KEY = os.getenv("API_KEY", "secret")


@app.middleware("http")
async def api_key_guard(request: Request, call_next):
    # Zmienione z /notes na /tasks
    if request.url.path.startswith("/tasks"):
        provided = request.headers.get("X-API-Key")
        if provided != API_KEY:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized (X-API-Key)"})
    return await call_next(request)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/tasks", response_model=Page[TaskOut])  # Zmienione /notes na /tasks
def list_tasks(q: str | None = None, sort: str = "desc", done: Optional[bool] = None):  # Dodano parametr 'done'
    db = load_db()
    data = db["notes"]  # Korzystamy z klucza "notes"
    if q:
        ql = q.lower()
        # Filtrowanie po title i labels
        data = [t for t in data if ql in t["title"].lower()
                or any(ql in l.lower() for l in t.get("labels", []))]

    if done is not None:
        data = [t for t in data if t.get("done") == done]

    data = sorted(data, key=lambda t: t["created_at"], reverse=(sort == "desc"))
    return paginate(data)


add_pagination(app)


@app.get("/tasks/{task_id}", response_model=TaskOut)  # Zmienione /notes/{note_id} na /tasks/{task_id}
def get_task(task_id: int):
    db = load_db()
    for t in db["notes"]:
        if t["id"] == task_id:
            return t
    raise HTTPException(status_code=404, detail="Task not found")


@app.post("/tasks", response_model=TaskOut, status_code=201)  # Zmienione /notes na /tasks, NoteIn na TaskIn
def create_task(task: TaskIn):
    with LOCK:
        db = load_db()
        new_id = int(db.get("next_id", 1))
        # Używamy task.dict(exclude_none=True) aby pominąć pola None (np. due_date)
        rec = {"id": new_id, "created_at": _time.time(), **task.dict(exclude_none=True)}
        db["notes"].append(rec)
        db["next_id"] = new_id + 1
        save_db(db)
        return rec


@app.put("/tasks/{task_id}", response_model=TaskOut)  # Zmienione /notes/{note_id} na /tasks/{task_id}
def update_task(task_id: int, task: TaskIn):
    with LOCK:
        db = load_db()
        for i, t in enumerate(db["notes"]):
            if t["id"] == task_id:
                updated = {"id": task_id, "created_at": t["created_at"], **task.dict(exclude_none=True)}
                db["notes"][i] = updated
                save_db(db)
                return updated
    raise HTTPException(status_code=404, detail="Task not found")


@app.delete("/tasks/{task_id}", status_code=204)  # Zmienione /notes/{note_id} na /tasks/{task_id}
def delete_task(task_id: int):
    with LOCK:
        db = load_db()
        for i, t in enumerate(db["notes"]):
            if t["id"] == task_id:
                db["notes"].pop(i)
                save_db(db)
                return
    raise HTTPException(status_code=404, detail="Task not found")
