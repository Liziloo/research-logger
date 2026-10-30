import os
import re
import json
import datetime
import threading
from pathlib import Path
from typing import Optional, Dict
from fastapi import FastAPI, Header, HTTPException, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from dotenv import load_dotenv

load_dotenv()

# Resolve path properly with tilde expansion
VAULT_DIR = Path(os.getenv("VAULT_DIR", "~/vault/PA-Zone")).expanduser().resolve()
VAULT_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = Path(__file__).parent / "session_state.json"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:latest")
API_SECRET_TOKEN = os.getenv("API_SECRET_TOKEN", "change-this-to-a-secure-random-token")

file_write_lock = threading.Lock()

app = FastAPI(title="Genealogy & Archival Research Logger")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def load_session() -> dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "active": False,
        "topic": "General Research",
        "filename": None,
        "start_time": None
    }

def save_session(session_data: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(session_data, f, indent=2)

current_session = load_session()

class CaptureRequest(BaseModel):
    url: str
    title: str
    isImageRecord: Optional[bool] = False
    recordData: Optional[Dict[str, str]] = {}
    transcription: Optional[str] = ""
    selection: Optional[str] = ""
    rawFallback: Optional[str] = ""
    timestamp: Optional[str] = None

class SessionStartRequest(BaseModel):
    topic: Optional[str] = "Family Research"

def verify_token(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token != API_SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")
    return token

def clean_url(url: str) -> str:
    """Strip noisy session tracking parameters while keeping vital query IDs & ARKs."""
    cleaned = re.sub(r'([&?])(treeref|queryId|clickref|authProvider|recId|_gl)=[^&]*', '', url)
    cleaned = cleaned.rstrip('?&')
    return cleaned

def format_with_ollama(title: str, url: str, record_data: dict, text_content: str, selection: str, is_image: bool) -> Optional[str]:
    """Generates a structured genealogical evidence abstract or research article summary."""
    data_lines = [f"{k}: {v}" for k, v in record_data.items()]
    data_dump = "\n".join(data_lines)
    snippet = text_content[:3000].strip()

    prompt = (
        "You are an expert genealogical and historical research assistant. "
        "Analyze the following webpage content and produce a concise research log entry.\n\n"
        f"Page Title: {title}\n"
        f"URL: {url}\n"
        f"Is Record Image / Viewer: {is_image}\n"
        f"User Highlighted Text: {selection if selection else 'None'}\n"
        f"Structured Record Fields:\n{data_dump if data_dump else 'None'}\n\n"
        f"Text / Transcription Snippet:\n{snippet if snippet else 'None'}\n\n"
        "Instructions:\n"
        "1. If this is a historical, vital, census, or genealogical record, format as:\n"
        "- **Principal Individual(s):** [Names, age/birth if available]\n"
        "- **Event & Date:** [Event type, date]\n"
        "- **Location:** [Town/County/State/Country]\n"
        "- **Key Relationships / Household:** [Parents, spouse, children, witnesses, associates]\n"
        "- **Source / Citation Details:** [Collection, DGS/film #, image #, page/certificate #]\n\n"
        "2. If this is an article, history essay, reference page (like Wikipedia), or blog, format as:\n"
        "- **Topic / Context:** [1-sentence summary of the page]\n"
        "- **Key Takeaways:** [2-3 concise bullet points with relevant historical facts]\n\n"
        "Output ONLY the markdown bullet points. Do not write conversational filler."
    )

    try:
        with httpx.Client(timeout=12.0) as client:
            resp = client.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False
                }
            )
            if resp.status_code == 200:
                out = resp.json().get("response", "").strip()
                if out:
                    return out
    except Exception as e:
        print(f"[Ollama] Offline or busy ({e}). Using direct markdown fallback.")
    return None

def append_to_vault(capture: CaptureRequest):
    now = datetime.datetime.now()
    time_str = now.strftime("%H:%M:%S")

    if current_session["active"] and current_session["filename"]:
        filepath = VAULT_DIR / current_session["filename"]
    else:
        date_str = now.strftime("%Y-%m-%d")
        filepath = VAULT_DIR / f"{date_str}-research-log.md"

    cleaned_url = clean_url(capture.url)
    cleaned_title = capture.title.replace(" - FamilySearch", "").replace(" | Ancestry®", "").strip()

    # Attempt AI processing
    ai_summary = format_with_ollama(
        cleaned_title,
        cleaned_url,
        capture.recordData or {},
        capture.transcription or capture.rawFallback or "",
        capture.selection or "",
        capture.isImageRecord
    )

    # Build entry
    entry = f"\n### [{time_str}] [{cleaned_title}]({cleaned_url})\n"
    if capture.isImageRecord:
        entry += "> 📷 **Type:** Record Image / Archive Viewer\n\n"

    if capture.selection:
        entry += f"> **Highlighted Excerpt:**\n> {capture.selection.strip()}\n\n"

    if ai_summary:
        entry += f"{ai_summary}\n"
    else:
        # Graceful zero-AI fallback: logs clean structured fields or readable text preview
        entry += "*(AI offline – direct extract logged)*\n\n"
        if capture.recordData:
            for k, v in capture.recordData.items():
                entry += f"- **{k}:** {v}\n"
        elif capture.transcription:
            entry += f"> {capture.transcription[:500]}...\n"
        else:
            entry += f"> {capture.rawFallback[:300]}...\n"

    entry += "\n---\n"

    # Thread-safe write
    with file_write_lock:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(entry)

@app.get("/session/status")
def get_status(_: str = Depends(verify_token)):
    return current_session

@app.post("/session/start")
def start_session(req: SessionStartRequest, _: str = Depends(verify_token)):
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    slug = re.sub(r'[^a-zA-Z0-9_\- ]+', '', req.topic).strip().replace(" ", "-")[:40] or "research-session"
    filename = f"{date_str}-{slug}.md"
    filepath = VAULT_DIR / filename

    current_session.update({
        "active": True,
        "topic": req.topic,
        "filename": filename,
        "start_time": now.isoformat()
    })
    save_session(current_session)

    with file_write_lock:
        if not filepath.exists():
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"# Research Log: {req.topic}\n")
                f.write(f"- **Date Started:** {now.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write("## Records & Sources Examined\n")

    return {"message": "Session started", "session": current_session}

@app.post("/session/stop")
def stop_session(_: str = Depends(verify_token)):
    if not current_session["active"]:
        return {"message": "No active session"}

    now = datetime.datetime.now()
    if current_session.get("filename"):
        filepath = VAULT_DIR / current_session["filename"]
        with file_write_lock:
            if filepath.exists():
                with open(filepath, "a", encoding="utf-8") as f:
                    f.write(f"\n**Session concluded at:** {now.strftime('%Y-%m-%d %H:%M:%S')}\n")

    topic = current_session["topic"]
    current_session.update({
        "active": False,
        "topic": "General Research",
        "filename": None,
        "start_time": None
    })
    save_session(current_session)
    return {"message": f"Session '{topic}' stopped"}

@app.post("/capture")
def capture_page(capture: CaptureRequest, bg: BackgroundTasks, _: str = Depends(verify_token)):
    bg.add_task(append_to_vault, capture)
    return {"status": "queued"}
