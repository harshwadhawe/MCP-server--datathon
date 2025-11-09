# Project Management MCP Server

A **Model Context Protocol (MCP)** server that acts as a context-aware middleware for AI assistants. It intercepts user queries, analyzes intent, fetches context from multiple productivity systems (Google Calendar, GitHub, Slack, and JIRA), assembles a structured context package, and delivers it alongside the original prompt to the Gemini AI model for hyper-relevant responses.

This repository (together with a Devpost demo video) forms the submission for the Build-Your-Own-MCP Challenge.

---

## Table of Contents
1. [High-Level Workflow](#high-level-workflow)
2. [Key Capabilities](#key-capabilities)
3. [Architecture](#architecture)
4. [Integrations & Required Credentials](#integrations--required-credentials)
5. [Installation & Setup](#installation--setup)
6. [Running the Server & UI](#running-the-server--ui)
7. [Available MCP Tools](#available-mcp-tools)
8. [Submission Checklist](#submission-checklist)
9. [Project Structure](#project-structure)
10. [Troubleshooting](#troubleshooting)
11. [License & Contact](#license--contact)

---

## High-Level Workflow

1. **Intercept** user queries (via MCP client, CLI, or Streamlit dashboard).
2. **Analyze** intent with an NLP-powered `QueryAnalyzer` (intent detection, entity extraction, domain classification, temporal parsing).
3. **Fetch** supplemental context from the relevant data sources.
4. **Assemble** a ranked & summarized context package using caching, ranking, summarization, and correlation engines.
5. **Deliver** the context bundle and original prompt to Gemini for the final response.

---

## Key Capabilities

### Intelligent Query Understanding
- Detects calendar, GitHub, Slack, and JIRA domains (or multi-domain queries).
- Extracts entities such as repositories, PR/issue counts, calendar dates, backlog keywords, etc.
- Supports relative and absolute time references via a time-aware analyzer.

### Multi-Source Context Gathering
- **Google Calendar:** Events, availability, conflicts, and multi-calendar aggregation.
- **GitHub:** Repositories, issues, PRs, commits, deployments, README summaries.
- **Slack:** Channels, mentions, unread messages, recent activity.
- **JIRA:** Boards, assigned issues, backlog items, sprint insights.

### Context Packaging
- **ContextCache:** TTL-based cache to minimize redundant API calls.
- **ContextRanker:** Prioritizes the most relevant events/issues per query.
- **ContextSummarizer:** Compresses context to stay within token budgets.
- **ContextCorrelator:** Cross-links signals across services (e.g., meetings vs. deployments vs. Slack alerts).

### Delivery via Gemini
- Aggregated context + user prompt → Gemini (primarily `gemini-2.5-flash`) to craft a tailored response.

---

## Architecture

```
┌──────────────────────────┐
│      User Request        │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│     Query Analyzer       │  ← intent detection, entities, time range
└────────────┬─────────────┘
             │
  ┌──────────┼───────────┐
  │          │           │
  ▼          ▼           ▼
Calendar   GitHub      Slack      JIRA
Client     Client      Client     Client
(fetch)    (fetch)     (fetch)    (fetch)
  │          │           │         │
  └──────────┴───────────┴─────────┘
             │
             ▼
┌──────────────────────────┐
│ Cache / Rank / Summarize │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ Gemini Client (Chat)     │ → context + prompt → AI answer
└──────────────────────────┘
```

---

## Integrations & Required Credentials

| Service          | Credentials / Env Vars                                  | Notes |
|------------------|----------------------------------------------------------|-------|
| Google Calendar  | `config/credentials.json`, `config/token.json` (generated) | OAuth desktop credentials with Calendar scopes |
| GitHub           | `.env` → `GITHUB_TOKEN`                                   | Personal Access Token with repo scope |
| Slack            | `.env` → `SLACK_USER_TOKEN`                               | User token with `channels:read`, `channels:history`, `groups:*`, `im:*`, `search:read`, `users:read` |
| JIRA             | `.env` → `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`  | Jira Cloud site, email, and API token |
| Gemini           | `.env` → `GEMINI_API_KEY`                                 | Google AI Studio API key |

Optional environment variables (with defaults in code):
- `GOOGLE_CREDENTIALS_PATH` (default `config/credentials.json`)
- `GOOGLE_TOKEN_PATH`       (default `config/token.json`)
- `CALENDAR_TIMEZONE`       (used for time parsing defaults)

Make sure sensitive files (credentials and tokens) stay out of version control. `.gitignore` already excludes them.

---

## Installation & Setup

1. **Clone the repository**
   ```bash
   git clone <repo-url>
   cd MCP\ server
   ```

2. **Create & activate a Python environment**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate            # Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Provide credentials**
   - Place Google OAuth desktop credentials at `config/credentials.json`.
   - Create a `.env` file (copy `.env.example`) and populate the tokens/keys listed above.

5. **Authenticate Google Calendar (first run)**
   Running the server for the first time will launch a browser window for Google OAuth and produce `config/token.json`.

---

## Running the Server & UI

### 1. MCP Server (JSON-RPC over stdio)
```bash
python main.py
```
This registers tools such as `chat`, `get_calendar_context`, `get_github_repositories`, `get_slack_mentions`, `get_jira_backlog`, etc.

### 2. Streamlit Dashboard (optional UI)
```bash
streamlit run streamlit_app.py
```
Features predefined queries, quick actions, and a custom prompt box for Calendar/GitHub/Slack/JIRA.

### 3. CLI Test Scripts (optional)
- `interactive_client.py` for command-line chat testing.
- `slack_test.py`, `jira_test.py` for quick credential and API verification.

---

## Available MCP Tools

| Tool | Description |
|------|-------------|
| `chat` | Main conversational endpoint; auto-fetches relevant context across all services. |
| **Calendar** |
| `get_calendar_context` | Analyze a query and return formatted calendar context. |
| `check_availability` | Check availability for a specific timeslot. |
| `get_upcoming_events` | List upcoming events. |
| `detect_conflicts` | Identify conflicts on a date. |
| **GitHub** |
| `get_github_repositories` | List repositories (with metadata). |
| `get_github_issues` | Fetch open issues. |
| `get_github_pull_requests` | Fetch PRs. |
| `get_github_deployments` | Retrieve deployments + status. |
| **Slack** |
| `get_slack_channels` | List channels. |
| `get_slack_unread` | Channels with unread messages. |
| `get_slack_mentions` | Recent mentions. |
| **JIRA** |
| `get_jira_boards` | List boards. |
| `get_jira_issues` | General issue retrieval (board/JQL). |
| `get_my_jira_issues` | Issues assigned to the authenticated user (with fallbacks). |
| `get_jira_backlog` | Backlog items (Agile API + JQL fallback). |

Each tool returns a formatted string suitable for direct inclusion in a context package.

---

## Submission Checklist

✅ **GitHub Repository** – contains the full MCP server implementation, connectors, UI, and test scripts.

✅ **Context-Aware Workflow** – intercept → analyze → fetch → assemble → deliver implemented across four services.

⚠️ **Devpost Video Demo** – still needed. Please record a short walkthrough showing:
  - How a query flows through the system (e.g., via Streamlit UI).
  - The resulting context assembly (logs/UI snippets).
  - The Gemini-powered responses.
  - Any unique 2.0 features (caching, correlation, summarization).
  Upload the video to Devpost along with the repo link.

---

## Project Structure

```
MCP server/
├── main.py                     # Entry point for MCP server
├── streamlit_app.py            # Optional Streamlit UI
├── interactive_client.py       # Simple CLI client
├── slack_test.py / jira_test.py# Quick integration smoke tests
├── src/
│   ├── server.py               # MCP tools & orchestration layer
│   ├── query_analyzer.py       # NLP intent/time/entity detection
│   ├── context_cache.py        # TTL cache for API responses
│   ├── context_ranker.py       # Relevance scoring
│   ├── context_summarizer.py   # Compression + summarization utilities
│   ├── context_correlator.py   # Multi-source correlation engine
│   ├── context_formatter.py    # Human-friendly context formatting
│   ├── gemini_client.py        # Gemini chat integration
│   ├── calendar_client.py      # Google Calendar wrapper
│   ├── github_client.py        # GitHub REST wrapper
│   ├── slack_client.py         # Slack WebClient wrapper
│   ├── jira_client.py          # Jira REST (Agile + Core) wrapper
│   └── connectors/             # Connector facades per service
├── config/
│   ├── credentials.json        # Google OAuth client (excluded from git)
│   └── token.json              # Google OAuth token (excluded from git)
├── requirements.txt
├── .env.example
└── README.md (this file)
```

---

## Troubleshooting

| Issue | Resolution |
|-------|------------|
| Google Calendar auth loop | Delete `config/token.json` and rerun to reauthenticate. Ensure OAuth consent screen has you as a test user. |
| GitHub 401 | Regenerate `GITHUB_TOKEN` (classic PAT) with `repo` scope. |
| Slack `missing_scope` | Add required scopes under **User Token Scopes** and reinstall the app. |
| JIRA 410 errors | Confirm you have access to the Jira Cloud site and use valid API tokens. The client already falls back to board-based queries when search fails. |
| Gemini errors | Verify `GEMINI_API_KEY` is correct and the selected model is available in your region/account. |

Logging is configured to stderr to avoid interfering with MCP stdio responses.

---

## License & Contact

Created for the **Build-Your-Own-MCP Challenge**.

For questions, open an issue or reach out via the Devpost discussion board when submitting your demo.
