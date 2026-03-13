# CloudCanvasAI

An AI-powered document creation and editing platform that combines Claude AI with real-time document preview. Chat with Claude on the left, see generated documents (`.docx`, `.pptx`, `.pdf`, `.xlsx`) rendered live on the right.

## How It Works

```mermaid
graph LR
    User(("👤 User"))

    subgraph Browser["🖥️ Browser"]
        direction TB
        Login["🔐 Sign In\n(Google / Email)"]

        subgraph SplitPanel["Split-Panel Interface"]
            direction LR
            ChatPanel["💬 Chat\nAsk Claude to create\nor edit documents"]
            DocPanel["📄 Live Preview\nSee documents render\nin real-time"]
        end

        FileExplorer["📂 File Browser\nBrowse & download\ngenerated files"]
    end

    subgraph Cloud["☁️ Cloud"]
        direction TB
        AI["🤖 Claude AI\nUnderstands your request\nand writes documents"]

        subgraph Sandbox["🔒 Your Private Sandbox"]
            direction LR
            DocSkills["📝 Document Skills\n.docx  .pptx  .pdf  .xlsx"]
            Files["💾 Your Files\nIsolated per user"]
        end
    end

    User -->|"Opens app"| Login
    Login -->|"Authenticated"| SplitPanel
    ChatPanel -->|"Send message"| AI
    AI -->|"Streams response"| ChatPanel
    AI -->|"Creates / edits"| DocSkills
    DocSkills -->|"Saves to"| Files
    Files -->|"Renders"| DocPanel
    Files -->|"Lists"| FileExplorer
    FileExplorer -->|"Download"| User

    style User fill:#7c3aed,stroke:#7c3aed,color:#fff
    style Browser fill:#1e1b4b,stroke:#4338ca,color:#e0e7ff
    style SplitPanel fill:#312e81,stroke:#6366f1,color:#c7d2fe
    style Cloud fill:#0f172a,stroke:#3b82f6,color:#bfdbfe
    style Sandbox fill:#1e293b,stroke:#38bdf8,color:#bae6fd
    style ChatPanel fill:#4338ca,stroke:#818cf8,color:#fff
    style DocPanel fill:#4338ca,stroke:#818cf8,color:#fff
    style AI fill:#7c3aed,stroke:#a78bfa,color:#fff
    style DocSkills fill:#0369a1,stroke:#38bdf8,color:#fff
    style Files fill:#0369a1,stroke:#38bdf8,color:#fff
    style Login fill:#4338ca,stroke:#818cf8,color:#fff
    style FileExplorer fill:#4338ca,stroke:#818cf8,color:#fff
```

## Technical Architecture

```mermaid
graph TB
    subgraph "Frontend · React + Vite"
        UI[Split-Panel UI]
        Chat[Chat Panel]
        Preview[Document Preview]
        FBAuth[Firebase Auth Client]
    end

    subgraph "Backend · FastAPI"
        API[REST API + SSE Streaming]
        SandboxMgr[Sandbox Manager]
        FBAdmin[Firebase Admin SDK]
    end

    subgraph "E2B Sandbox · Per-User Isolation"
        Agent[Claude Agent SDK]
        Skills[Skills: docx / pdf / pptx / xlsx]
        FS[Isolated Filesystem]
    end

    subgraph "External Services"
        Firebase[(Firebase Auth)]
        Claude[Anthropic Claude API]
        E2B[E2B Platform]
    end

    Chat -->|"SSE / HTTP"| API
    Preview -->|"HTTP (file fetch)"| API
    FBAuth -->|"ID Token"| Firebase
    API -->|"Verify Token"| FBAdmin
    FBAdmin --> Firebase
    API --> SandboxMgr
    SandboxMgr -->|"Create / Connect"| E2B
    E2B --> Agent
    Agent -->|"API Calls"| Claude
    Agent --> Skills
    Skills --> FS
```

## Project Structure

```
CloudCanvasAI/
├── backend/          # FastAPI backend (Python)
│   ├── routers/      # API endpoints (chat SSE, file serving)
│   ├── sandbox_manager.py  # E2B sandbox lifecycle
│   ├── e2b-template/ # Custom E2B sandbox template
│   └── skills/       # Document manipulation skills
├── frontend/         # React + Vite frontend
│   ├── src/pages/    # Chat page with split-panel UI
│   ├── src/components/  # DocumentPreview, FileList
│   └── src/services/ # API client, Firebase auth
└── skills/           # Git submodule → github.com/anthropics/skills
```

## Prerequisites

- Python 3.11+
- Node.js 18+
- API keys: `ANTHROPIC_API_KEY`, `E2B_API_KEY`
- Firebase project with Auth enabled

## Setup

### Clone with submodules

```bash
git clone --recurse-submodules <repo-url>
cd CloudCanvasAI
```

If already cloned:
```bash
git submodule update --init --recursive
```

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # Fill in your API keys
uvicorn main:app --reload
```

API available at `http://localhost:8000` (Swagger UI at `/docs`)

### Frontend

```bash
cd frontend
npm install
cp .env.example .env   # Fill in Firebase config
npm run dev
```

App available at `http://localhost:5173`

## Environment Variables

See `backend/.env.example` and `frontend/.env.example` for all required variables.

Key variables:
- `ANTHROPIC_API_KEY` — Claude API access
- `E2B_API_KEY` — Sandbox creation
- `E2B_TEMPLATE` — E2B template alias (default: `cloudcanvasai-docs`)
- `VITE_API_BASE_URL` — Backend URL for production (defaults to localhost in dev)
- `VITE_FIREBASE_*` — Firebase web config

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19, Vite 7, Firebase Auth |
| Backend | FastAPI, Uvicorn, Claude Agent SDK |
| Sandbox | E2B Code Interpreter (per-user isolation) |
| Doc Rendering | mammoth.js (docx), react-markdown |
| Auth | Firebase (Google + email/password) |
| Deployment | Railway (backend), Vercel (frontend) |
