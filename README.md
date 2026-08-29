# ⚡ EdgeDash — Autonomous Career Intelligence Agent

An autonomous multi-agent career intelligence platform that continuously tracks the job market, extracts skill requirements using LLMs, computes deterministic fit scores, identifies high-ROI skill gaps, and serves verified insights on a Streamlit dashboard with natural language query capabilities.

---

## 🌟 Key Features

- **🤖 Autonomous Multi-Agent Pipeline:**
  - `Fetcher`: Scrapes job postings from multiple sources (Arbeitnow, Apify, etc.) with rate-limiting and deduplication.
  - `Scorer`: Deterministically scores listings (0–100) based on required skills, seniority fit, location/remote match, and recency.
  - `GapAnalyzer`: Computes market skill gaps weighted by opportunity cost ($\sum \text{fit\_score} / 100$).
  - `Verifier`: Self-audits output data against 6 statistical quality bars before promoting cycles to production.
  - `Orchestrator`: Coordinates agents with state planning and error-recovery budgets.

- **💬 Natural Language Career Queries (Rules 40–46):**
  - Ask questions in plain English (e.g. *"What are my best matches?"*, *"Which companies are hiring right now?"*).
  - Abuse-guarded routing with parameter validation and strict underlying data row rendering.
  - Zero text-to-SQL — deterministic parameterised tool registry only.

- **☁️ Production-Ready Storage Architecture (Rules 2, 47–51):**
  - Dual backend support: Hosted **PostgreSQL** (Supabase) in production and **SQLite** for offline local development.
  - Hostile-startup hardening: Dashboard starts cleanly even if database is empty or initializing.
  - Zero secret leakage in logs, traces, or UI.

---

## 📁 Repository Structure

```text
├── .streamlit/
│   └── config.toml          # Dark theme UI configuration
├── edgedash/
│   ├── agents/              # Autonomous agent implementations
│   │   ├── base.py
│   │   ├── fetcher.py
│   │   ├── scorer.py
│   │   ├── gap_analyzer.py
│   │   ├── verifier.py
│   │   └── orchestrator.py
│   ├── query/               # Natural language query pipeline & abuse guards
│   │   ├── ask.py
│   │   ├── guards.py
│   │   └── tools.py
│   ├── sources/             # Job board fetcher adapters
│   ├── config.py            # Configuration loader
│   ├── llm.py               # Multi-provider LLM client (Groq, Gemini, Ollama)
│   ├── storage.py           # Unified Postgres/SQLite storage layer
│   └── skills.py            # Skill extraction & canonicalization
├── tests/                   # Complete automated test suite (50 unit tests)
├── app.py                   # Streamlit Community Cloud dashboard
├── run_cycle.py             # Scheduled autonomous execution entrypoint
├── config.yaml              # User preferences & threshold configurations
├── requirements.txt         # Pinned production dependencies
└── .env.example             # Template environment variables
```

---

## 🚀 Quick Start (Local Development)

### 1. Clone & Setup Virtual Environment
```bash
git clone https://github.com/Rehansheikh787/EdgeDash-autonomous-career-agent-.git
cd EdgeDash-autonomous-career-agent-

python -m venv .venv
# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# On Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment
Copy `.env.example` to `.env` and configure your API keys:
```bash
cp .env.example .env
```

### 3. Initialize & Check Database
```bash
python -m edgedash.storage --migrate
python -m edgedash.storage --check
```

### 4. Run an Autonomous Data Cycle
```bash
python run_cycle.py
```

### 5. Launch the Dashboard
```bash
streamlit run app.py
```

---

## 🧪 Testing

Run all unit tests:
```bash
python -m unittest discover -s tests
```

---

## 📄 License
MIT License
>>>>>>> e13b32a (feat: EdgeDash autonomous career intelligence platform with multi-agent system, Postgres/SQLite storage, and NL querying)
