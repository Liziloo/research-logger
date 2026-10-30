# Research Logger & Copilot

A self-hosted, privacy-first research logging pipeline designed for genealogists, historians, and researchers. It automatically captures records, archive image viewers, and articles as you browse, structures them using a local **Ollama** model, and appends them straight into an **Obsidian** vault folder over your local network.

Built to run alongside harnesses like **OpenClaw** on a local home server (e.g., KDE Neon / Linux).

---

## Architecture

```text
[ Vivaldi Browser ]
  └─ research-copilot/ (MV3 Extension)
        │
        │  (HTTP POST / LAN / Bearer Token)
        ▼
[ Logger Server (Port 8766) ]
  ├─ FastAPI (main.py)
  ├─ Ollama (localhost:11434) ─── Extracts Who/What/When/Where or Article summaries
  │                               (Falls back cleanly to raw metadata if offline)
  └─ Writes directly to ─────────► [ Obsidian Vault ] (e.g. ~/vault/PA-Zone/)
                                          ▲
                                          │
                                   [ OpenClaw Harness ]
                                   (Queries & synthesizes logs)
```

---

## Features

- **Passive & Hands-Free:** No manual copy-pasting or text highlighting required.
- **12-Second Dwell Timer:** Skips fast redirects, accidental clicks, and quick tab flips; only logs pages you actually stop to read.
- **Genealogy-Aware DOM Parsing:**
  - **FamilySearch:** Automatically parses indexed record detail tables, image viewer film/DGS/image metadata, and full-text search transcriptions (deeds, probate, wills).
  - **Ancestry:** Extracts structured record grids, citation sources, and household/census tables.
  - **General Archives & Web:** Extracts tabular data from Find A Grave, state archives, and directories, while capturing clean readable text from Wikipedia and history blogs.
- **Dual-Mode AI Summarization:**
  - Archival records are formatted into structured evidence abstracts (*Principal, Event/Date, Location, Relationships/Household, Citation Details*).
  - General articles/blogs are formatted into concise context and historical takeaways.
- **Zero Data-Loss Offline Fallback:** If Ollama is turned off, busy, or unreachable, the server immediately formats the raw extracted fields directly into Markdown. Nothing is lost.
- **Offline Extension Queue:** If the server is offline or unreachable, the browser extension holds captures in local storage and retries every minute via background alarms.
- **LAN-Secured:** All requests require a shared Bearer token to prevent unauthorized writes across your local network.

---

## Repository Layout

```text
research-logger/
├── .env.example              # Configuration template
├── .gitignore                # Protects secrets, venvs, and state
├── requirements.txt          # Python dependencies
├── main.py                   # FastAPI logging backend
├── research-logger.service   # Systemd user service unit
├── README.md
│
└── research-copilot/         # Vivaldi / Chromium Manifest V3 Extension
    ├── manifest.json
    ├── background.js         # Service worker, dwell timer, retry queue
    ├── content.js            # Smart DOM metadata extractor
    ├── popup.html            # Session controls & configuration UI
    └── popup.js
```

---

## Server Setup (KDE Neon / Linux Host)

### 1. Prerequisites
- Python 3.10+
- [Ollama](https://ollama.com/) running locally (`ollama run qwen2.5:latest` or similar)
- An Obsidian vault located on the host

### 2. Installation
```bash
# Clone the repository
cd ~
git clone <YOUR_REPO_URL> research-logger
cd research-logger

# Create virtual environment & install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create your local environment configuration
cp .env.example .env
nano .env
```

### 3. Configure `.env`
Update `.env` with your preferred settings:
```ini
VAULT_DIR=~/vault/PA-Zone
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:latest
API_SECRET_TOKEN=generate-a-strong-secret-token-here
HOST=0.0.0.0
PORT=8766
```

### 4. Enable Background Service (Systemd User Unit)
Run the server continuously in the background without needing root privileges:

```bash
mkdir -p ~/.config/systemd/user/
cp research-logger.service ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable --now research-logger

# Ensure the service stays running even when you log out
loginctl enable-linger $USER

# Check service status
systemctl --user status research-logger
```

---

## Browser Extension Setup (Vivaldi / Chromium)

1. Open Vivaldi and navigate to `vivaldi://extensions`.
2. Toggle on **Developer mode** (top-right corner).
3. Click **Load unpacked**.
4. Select the **`research-logger/research-copilot/`** subfolder (the directory containing `manifest.json`).
5. Pin **Research Copilot** to your browser toolbar.
6. Click the extension icon and expand **Connection Settings**:
   - **Server URL:** `http://192.168.5.159:8766` (adjust to your host's LAN IP/port)
   - **Secret Token:** Paste the same `API_SECRET_TOKEN` you set in `.env`
   - Click **Save Settings**.

---

## Usage Workflow

1. **Start a Session:** Click the toolbar extension icon, type a target topic (e.g., `Baker Family - Berks Co Deeds`), and click **Start Session**.
   - The toolbar badge turns green with **`REC`**.
   - A new markdown file is created in your Obsidian vault: `vault/PA-Zone/YYYY-MM-DD-Baker-Family-Berks-Co-Deeds.md`.
2. **Browse Normally:** Open tabs across FamilySearch, Ancestry, Find A Grave, state archives, or Wikipedia.
   - Any tab open for longer than 12 seconds is automatically captured.
   - Repeating visits to the same URL in the same session are automatically deduplicated.
3. **Stop Session:** When finished, open the popup and click **Stop Session**. The log file is finalized with a conclusion timestamp.

---

## Sample Markdown Output in Obsidian

### Archival Record (Ollama Online)
```markdown
### [14:23:05] [John H Baker in the 1880 United States Federal Census](https://www.ancestry.com/discoveryui-content/view/37198302:6742)
- **Principal Individual(s):** John H. Baker (Age 42, b. ~1838, Pennsylvania)
- **Event & Date:** 1880 Federal Census (Enumerated June 10, 1880)
- **Location:** Robeson Township, Berks County, Pennsylvania
- **Key Relationships / Household:** Sarah Baker (Wife, 39), Charles (Son, 14), Emma (Daughter, 11)
- **Source / Citation Details:** Tenth Census of the United States; NARA Roll: 1099; Page: 142A; ED: 038
- **Research Notes:** Occupation listed as Blacksmith; parents born in PA.
---
```

### Record Image Viewer (FamilySearch DGS Film)
```markdown
### [14:26:18] [Estate Papers 1895-1902 • FamilySearch](https://familysearch.org/ark:/61903/3:1:3Q9M-C9Y8-K9)
> 📷 **Type:** Record Image / Archive Viewer

- **Principal Individual(s):** John H. Baker (Deceased)
- **Event & Date:** Letters of Administration granted October 14, 1898
- **Location:** Berks County Register of Wills, Pennsylvania
- **Key Relationships / Household:** Administrator: Sarah Baker; Bondsmen: George Miller, Jacob Fisher
- **Source / Citation Details:** DGS Film #008742193, Image 412 of 850
---
```

### Archival Record (Ollama Offline Fallback)
```markdown
### [14:31:02] [William H. Miller (1842-1915) - Find a Grave Memorial](https://www.findagrave.com/memorial/12345678)
*(AI offline – direct extract logged)*

- **Birth:** 14 Apr 1842
- **Death:** 22 Oct 1915
- **Burial:** Aulenbach's Cemetery, Mount Penn, Berks County, Pennsylvania
- **Memorial ID:** 12345678
---
```

---

## API Reference (For OpenClaw Integration)

All endpoints require the `Authorization: Bearer <API_SECRET_TOKEN>` header.

| Endpoint | Method | Payload | Description |
|---|---|---|---|
| `/session/status` | `GET` | *None* | Returns current session state, topic, and active filename. |
| `/session/start` | `POST` | `{"topic": "..."}` | Initializes a new research session file in the vault. |
| `/session/stop` | `POST` | *None* | Concludes the active research session. |
| `/capture` | `POST` | `CaptureRequest` | Queues page extraction, Ollama processing, and vault write. |

---

## Troubleshooting

- **Server won't start:** Check the logs using `journalctl --user -u research-logger -f`. Verify port `8766` isn't in use.
- **Extension shows connection error:** Ensure the host's firewall allows incoming traffic on port `8766` (`sudo ufw allow 8766/tcp`), and verify your LAN IP and Bearer token match in both `.env` and extension settings.
- **Ollama summaries missing:** Ensure Ollama is running (`curl http://localhost:11434/api/tags`) and that the model specified in `.env` is installed (`ollama pull qwen2.5:latest`).

---
