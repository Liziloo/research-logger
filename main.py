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

VAULT_DIR = Path(os.getenv("VAULT_DIR", "~/Obsidian/PA-Zone")).expanduser().resolve()
VAULT_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = Path(__file__).parent / "session_state.json"
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://192.168.2.86:8080/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "mistral-small-24b")
API_SECRET_TOKEN = os.getenv("API_SECRET_TOKEN", "change-this-to-a-secure-random-token")

file_write_lock = threading.Lock()

app = FastAPI(title="Genealogy & Archival Research Logger (Atomic Notes)")

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
        "folder": None,
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

def sanitize_slug(text: str) -> str:
    slug = re.sub(r'[^a-zA-Z0-9_\- ]+', '', text).strip().replace(" ", "-")
    return slug[:40] if slug else "record"

def clean_url(url: str) -> str:
    cleaned = re.sub(r'([&?])(treeref|queryId|clickref|authProvider|recId|_gl)=[^&]*', '', url)
    return cleaned.rstrip('?&')

def clean_noise(text: str) -> str:
    if not text:
        return ""
    noise_patterns = [
        r"(?i)Skip Ancestry main menu.*?(?=\n\n|\Z)",
        r"(?i)Home\s+Trees\s+Search\s+Memories\s+DNA.*?(?=\n\n|\Z)",
        r"(?i)Does this record match the person in your tree\?.*?(?=\n\n|\Z)",
        r"(?i)Add new information to your tree.*?(?=\n\n|\Z)",
        r"(?i)FactsHints\d+GalleryLifeStoryExp.*?(?=\n\n|\Z)",
        r"(?i)An official website of The Church of Jesus Christ of Latter-day Saints.*?(?=\n\n|\Z)",
        r"(?i)Family Tree\s+Search\s+Memories\s+Get Involved.*?(?=\n\n|\Z)",
        r"(?i)Memorials\s+Cemeteries\s+Contribute\s+Famous.*?(?=\n\n|\Z)",
        r"(?i)We use cookies.*?(?=\n\n|\Z)",
        r"(?i)Sign [Ii]n\s+to\s+your\s+account.*?(?=\n\n|\Z)",
    ]
    cleaned = text
    for p in noise_patterns:
        cleaned = re.sub(p, "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'[ \t]+', ' ', cleaned)
    return re.sub(r'\n{3,}', '\n\n', cleaned).strip()

def format_with_llm(title: str, url: str, record_data: dict, text_content: str, selection: str, is_image: bool) -> Optional[str]:
    data_lines = [f"{k}: {v}" for k, v in record_data.items()]
    data_dump = "\n".join(data_lines)
    snippet = clean_noise(text_content[:3000])

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
        with httpx.Client(timeout=45.0) as client:
            resp = client.post(
                f"{LLM_BASE_URL}/chat/completions",
                json={
                    "model": LLM_MODEL,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1
                }
            )
            if resp.status_code == 200:
                out = resp.json()["choices"][0]["message"]["content"].strip()
                if out:
                    return out
    except Exception as e:
        print(f"[LLM] Offline or busy ({e}). Using direct markdown fallback.")
    return None

def append_to_vault(capture: CaptureRequest):
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    time_slug = now.strftime("%H%M%S")

    if current_session["active"] and current_session.get("folder"):
        session_dir = VAULT_DIR / current_session["folder"]
    else:
        session_dir = VAULT_DIR / f"{date_str}-Quick-Captures"

    session_dir.mkdir(parents=True, exist_ok=True)

    cleaned_url = clean_url(capture.url)
    cleaned_title = capture.title.replace(" - FamilySearch", "").replace(" | Ancestry®", "").strip()
    title_slug = sanitize_slug(cleaned_title)

    ai_summary = format_with_llm(
        cleaned_title,
        cleaned_url,
        capture.recordData or {},
        capture.transcription or capture.rawFallback or "",
        capture.selection or "",
        capture.isImageRecord
    )

    record_filename = f"{time_slug}-{title_slug}.md"
    record_path = session_dir / record_filename

    fence = "---"
    rec_type = "archive-image" if capture.isImageRecord else "record"
    ai_flag = "true" if ai_summary else "false"

    lines = [
        fence,
        f'title: "{cleaned_title}"',
        f'date: {now.isoformat()}',
        f'url: "{cleaned_url}"',
        f'type: {rec_type}',
        f'ai_processed: {ai_flag}',
        fence,
        "",
        f"# [{cleaned_title}]({cleaned_url})",
        f"- **Captured:** {now.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Source Link:** {cleaned_url}",
        ""
    ]

    if capture.isImageRecord:
        lines.append("> 📷 **Type:** Record Image / Archive Viewer\n")

    if capture.selection:
        lines.append(f"> **Highlighted Excerpt:**\n> {capture.selection.strip()}\n")

    if ai_summary:
        lines.append("## Research Abstract")
        lines.append(ai_summary)
    else:
        lines.append("*(AI offline – direct extract logged)*\n")
        lines.append("## Record Data")
        if capture.recordData and len(capture.recordData) > 0:
            for k, v in capture.recordData.items():
                clean_val = clean_noise(str(v))
                if clean_val:
                    lines.append(f"- **{k}:** {clean_val}")
        elif capture.transcription:
            clean_sub = clean_noise(capture.transcription)[:350].strip()
            lines.append(f"> {clean_sub}...")
        elif capture.rawFallback:
            clean_sub = clean_noise(capture.rawFallback)[:250].strip()
            lines.append(f"> {clean_sub}...")

    note_content = "\n".join(lines) + "\n"

    with file_write_lock:
        with open(record_path, "w", encoding="utf-8") as f:
            f.write(note_content)

        index_path = session_dir / "_Index.md"
        if not index_path.exists():
            with open(index_path, "w", encoding="utf-8") as f:
                f.write(f"# Research Session: {current_session.get('topic', 'General Research')}\n")
                f.write(f"- **Started:** {date_str} {time_str}\n\n## Captured Records\n")

        with open(index_path, "a", encoding="utf-8") as f:
            note_stem = record_filename[:-3]
            f.write(f"- [{time_str}] [[{note_stem}|{cleaned_title}]] — [External Source]({cleaned_url})\n")

@app.get("/session/status")
def get_status(_: str = Depends(verify_token)):
    return current_session

@app.post("/session/start")
def start_session(req: SessionStartRequest, _: str = Depends(verify_token)):
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    slug = sanitize_slug(req.topic)
    folder_name = f"{date_str}-{slug}"
    session_dir = VAULT_DIR / folder_name
    session_dir.mkdir(parents=True, exist_ok=True)

    current_session.update({
        "active": True,
        "topic": req.topic,
        "folder": folder_name,
        "start_time": now.isoformat()
    })
    save_session(current_session)

    index_path = session_dir / "_Index.md"
    with file_write_lock:
        if not index_path.exists():
            with open(index_path, "w", encoding="utf-8") as f:
                f.write(f"# Research Session: {req.topic}\n")
                f.write(f"- **Date Started:** {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"- **Folder:** `{folder_name}`\n\n")
                f.write("## Captured Records\n")

    return {"message": "Session started", "session": current_session}

@app.post("/session/stop")
def stop_session(_: str = Depends(verify_token)):
    if not current_session["active"]:
        return {"message": "No active session"}

    now = datetime.datetime.now()
    if current_session.get("folder"):
        index_path = VAULT_DIR / current_session["folder"] / "_Index.md"
        with file_write_lock:
            if index_path.exists():
                with open(index_path, "a", encoding="utf-8") as f:
                    f.write(f"\n**Session concluded at:** {now.strftime('%Y-%m-%d %H:%M:%S')}\n")

    topic = current_session["topic"]
    current_session.update({
        "active": False,
        "topic": "General Research",
        "folder": None,
        "start_time": None
    })
    save_session(current_session)
    return {"message": f"Session '{topic}' stopped"}

@app.post("/capture")
def capture_page(capture: CaptureRequest, bg: BackgroundTasks, _: str = Depends(verify_token)):
    bg.add_task(append_to_vault, capture)
    return {"status": "queued"}
