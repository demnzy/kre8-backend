# Kre8 Backend — Creator Intelligence & Workflow Engine

Kre8 Backend is a high-performance Python FastAPI service providing content intelligence, real-time niche news aggregation, live Google Gemini script generation, publishing schedule management, and creator analytics telemetry.

---

## 🚀 Key Features

- **Live Google Gemini 2.5 Engine**:
  - Live scriptwriting with viral hook formulas, CTA generators, and scene-by-scene audio/visual cues via `google-genai` SDK.
  - Scene breakdown director splitting raw scripts into timed video scenes with transition types and on-screen text overlays.
  - Automated performance reviews analyzing retention, publishing consistency, and platform distribution.
- **Dual-Engine Real-Time News Pipeline**:
  - Specialized Free API support: Integrates NewsAPI.org and GNews.io when `NEWS_API_KEY` is provided.
  - Zero-configuration Google News RSS search engine with thumbnail image extraction (`image_url`).
  - Automated AI synthesis turning breaking news into 3-second hooks and content angles.
- **Creator Relational Data Model (SQLAlchemy 2.0)**:
  - 16 relational models: Users, User Preferences, Content Items (10-stage Kanban), Ideas Bank, Scripts, Script Clips, Calendar Events, Production Tasks, Notes Archive, Goals & Streaks, Social Accounts, and Analytics Snapshots.
- **Social Telemetry & Public Channel Lookup**:
  - `POST /api/social/youtube-lookup`: Inspects public YouTube channel metadata to return channel title, avatar, and live subscriber counts.
  - Account connection and baseline metrics syncing (`PUT /api/social/accounts/{id}/stats`).
- **Authentication & Security**:
  - JWT Bearer tokens with PBKDF2/SHA-256 password hashing and scoped user ownership on all endpoints.

---

## 🛠️ Tech Stack

- **Runtime**: Python 3.12+ / 3.14
- **Web Framework**: [FastAPI](https://fastapi.tiangolo.com/)
- **Server**: [Uvicorn](https://www.uvicorn.org/) with reload support
- **ORM & DB**: [SQLAlchemy 2.0](https://www.sqlalchemy.org/) with SQLite (local) / PostgreSQL (production)
- **AI SDK**: [Google GenAI Python SDK](https://github.com/googleapis/python-genai) (`gemini-2.5-flash`)
- **Validation**: [Pydantic v2](https://docs.pydantic.dev/)

---

## 📁 Directory Structure

```text
kre8-backend/
├── app/
│   ├── api/                 # Modular API routes
│   │   ├── ai.py            # Script generation, clip breakdown, diagnostics
│   │   ├── auth.py          # Registration, login, JWT validation
│   │   ├── calendar.py      # Events & publishing timetable
│   │   ├── content.py       # Kanban workflow stages & content records
│   │   ├── goals.py         # Output targets & publishing cadence
│   │   ├── ideas.py         # Creative ideas bank & promotion
│   │   ├── news.py          # Daily niche news & AI synthesis
│   │   ├── notes.py         # Knowledge archive & AI extraction
│   │   ├── profile.py       # Creator preferences & niche targeting
│   │   ├── scripts.py       # Full scripts & structured scene clips
│   │   ├── seed.py          # Demo data loader & workspace reset
│   │   ├── social.py        # Channel connection, stats sync & YT lookup
│   │   └── tasks.py         # Production shoot checklists & priorities
│   ├── core/
│   │   ├── config.py        # App settings & env loading
│   │   ├── database.py      # Database session & engine setup
│   │   └── security.py      # Password hashing & JWT tokens
│   ├── models/
│   │   └── models.py        # SQLAlchemy 2.0 database entities
│   ├── schemas/
│   │   └── schemas.py       # Pydantic v2 request/response contracts
│   ├── services/
│   │   ├── ai_service.py    # Google Gemini client & prompts
│   │   └── news_service.py  # Dual-engine news fetcher & image extractor
│   └── main.py              # Application entrypoint & CORS config
├── .env.example             # Template for environment variables
├── requirements.txt         # Python package dependencies
└── README.md                # Project documentation
```

---

## ⚙️ Environment Configuration

Create a `.env` file in the `kre8-backend/` root directory:

```env
# 1. Google Gemini API Key (Get at https://aistudio.google.com/app/apikey)
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash

# 2. Database Connection
DATABASE_URL=sqlite:///./kre8.db

# 3. Specialized News API (Optional - free key from newsapi.org or gnews.io)
NEWS_API_KEY=your_news_api_key_here

# 4. JWT Security
SECRET_KEY=your_random_secret_jwt_key_here
```

---

## 🚀 Getting Started

### 1. Create and Activate Virtual Environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 3. Run the Development Server
```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

The server will be available at:
- **API Base**: `http://127.0.0.1:8000`
- **Interactive OpenAPI Docs**: `http://127.0.0.1:8000/docs`
- **ReDoc**: `http://127.0.0.1:8000/redoc`

---

## 📡 Key API Endpoints

| Category | Method | Endpoint | Description |
| :--- | :--- | :--- | :--- |
| **Auth** | `POST` | `/api/auth/register` | Register new creator account |
| **Auth** | `POST` | `/api/auth/login` | Login and receive JWT access token |
| **Auth** | `GET` | `/api/auth/me` | Fetch authenticated creator user profile |
| **AI** | `POST` | `/api/ai/test-connection` | Verify Gemini live engine round-trip & latency |
| **AI** | `POST` | `/api/ai/generate-script` | Generate full script, hooks, CTAs, and scene clips |
| **AI** | `POST` | `/api/ai/breakdown-clips` | Break down raw text into timed visual scene scenes |
| **AI** | `POST` | `/api/ai/performance-review` | Live pattern and consistency audit |
| **News** | `GET` | `/api/news/daily` | Fetch breaking niche stories + thumbnails |
| **News** | `POST` | `/api/news/synthesize-ideas` | Synthesize daily news stories into creator angles |
| **Social** | `POST` | `/api/social/youtube-lookup` | Fetch public YouTube channel stats & avatar |
| **Social** | `POST` | `/api/social/connect/{platform}` | Connect channel with real baseline metrics |
| **Social** | `PUT` | `/api/social/accounts/{id}/stats` | Update channel followers, views, and engagement |
| **Social** | `GET` | `/api/social/analytics/summary` | Aggregate telemetry across all channels |
| **Content** | `GET/POST` | `/api/content` | Manage 10-stage production Kanban items |
| **Scripts** | `GET/POST` | `/api/scripts` | Save and manage creator scripts and scene clips |
| **Calendar** | `GET/POST` | `/api/calendar` | Schedule publishing events and deadlines |
| **Tasks** | `GET/POST` | `/api/tasks` | Checklist tasks with priority filtering |
| **Goals** | `GET/POST` | `/api/goals` | Habit cadence and publishing streak targets |

---

## 🗄️ Production Database Notes

Kre8 uses SQLAlchemy 2.0 ORM models that are 100% database-agnostic. To deploy to **PostgreSQL** (e.g. Supabase, Neon, AWS RDS, or Render):
1. Install `psycopg2-binary` or `asyncpg`.
2. Change `DATABASE_URL` in `.env`:
   ```env
   DATABASE_URL=postgresql://postgres:[PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres
   ```
3. Restart the backend service. SQLAlchemy will automatically create all tables on startup.
