
<div align="center">

# 🧠 Illume

  **AI Powered Codebase Onboarding & Architecture Intelligence**

  An enterprise-grade codebase intelligence and developer velocity platform. Illume parses multi-language syntax trees, builds relational dependency graphs, digests git history, and applies LLM reasoning to compile static repositories into living, interactive onboarding guides.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](LICENSE)
[![Python: 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg?logo=python&logoColor=white&style=flat-square)](https://www.python.org)
[![Next.js: 16+](https://img.shields.io/badge/Next.js-16%2B-black.svg?logo=nextdotjs&logoColor=white&style=flat-square)](https://nextjs.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.135%2B-009688.svg?logo=fastapi&logoColor=white&style=flat-square)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Supported-blue.svg?logo=docker&logoColor=white&style=flat-square)](https://www.docker.com)
[![Celery](https://img.shields.io/badge/Celery-5.6%2B-37814A.svg?logo=celery&logoColor=white&style=flat-square)](https://docs.celeryq.dev)


[Live Demo](https://illume.tejasnasa.me) · [Architecture Deep-Dive](#-system-architecture) · [Key Features](#-core-capabilities) · [Getting Started](#-installation--getting-started)

</div>

---

## 📖 Introduction & Philosophy

Codebases grow in complexity far faster than engineering teams can scale. When a new engineer joins a team, they face a massive cognitive load: thousands of lines of code, complex module connections, outdated wikis, and hidden tribal knowledge about who owns what. Traditional static documentations get stale immediately, and senior engineers spend valuable hours manually walking new hires through the architecture.

**Illume** is built on the philosophy that **the codebase itself is the single source of truth**. By combining:
1. **Deterministic AST Parsing** (using Tree-sitter) to extract syntax models.
2. **Git intelligence mining** to attribute active contributions and capture knowledge silos.
3. **Graph-theoretic topological analysis** to calculate dependency tiers.
4. **Semantic LLM reasoning & vector search** (`pgvector`) to contextually explain modules.

Illume builds a fully indexable, interactive, 3D visual workspace that turns repository onboarding from a weeks-long struggle into a self-guided, afternoon task.

---

## ⚡ Core Capabilities

### 🗺️ Deterministic Topological Learning Paths
Rather than listing files alphabetically or leaving it to guesswork, Illume runs a **Topological Sorting Algorithm** on the codebase's internal import graph.
* **How it works**: Files are nodes, and directed edges are created when a file imports a symbol defined in another file.
* **Cycle Handling**: Codebases frequently contain cyclic dependencies. Illume identifies cycles, groups them cleanly, and falls back to sorting files within cycles by their architectural weight (**fan-in** count) before appending them to the reading guide.
* **AI Contextualization**: Each step in the path is sent in batches to the LLM to generate clear, 1-2 sentence descriptions detailing *why* reading this file unlocks understanding of downstream components.

### 👥 Git Intelligence & Knowledge Silo Maps
Illume mines up to `500` historical git commits using `git log --numstat` parsing.
* **Contribution Attribution**: Calculates exactly what percentage of each file's changes were authored by which engineer.
* **Knowledge Silo Flags**: Flags files with a **Bus Factor of 1** (e.g., touched only by a single engineer) so teams can spot single points of human failure immediately.
* **Test Presence Safeguards**: Auto-generates template mappings (e.g., `test_{stem}.py`, `{stem}.spec.ts`) to cross-check file test coverage against git update frequency.

### 🔴 Architectural Criticality (Traffic-Light Prioritization)
Files are automatically grouped into three distinct priority levels based on mathematical thresholds:
* 🔴 **Critical**: Core plumbing and highly volatile infrastructure. Identified by high code **fan-in** (imported by $\ge 10$ files), alignment with sensitive path patterns (e.g., `database.py`, `auth.py`, `middleware/`), or lack of test coverage despite high change frequency.
* 🟡 **Caution**: Moderate architectural importance (imported by 5–9 files).
* 🟢 **Safe to Explore**: Low risk, decoupled modules, perfect for new hires to start writing PRs.

### 🌐 Interactive 3D WebGL Dependency Graph
Renders module imports dynamically inside the browser utilizing WebGL and `react-force-graph-3d` (powered by Three.js).
* **Visual Semantics**: Nodes represent files, sized relative to their **architectural weight** (sum of fan-in & fan-out) and colored according to their traffic-light criticality.
* **Focus States**: Highlighting a node reveals its immediate upstream importers and downstream dependencies, entirely removing the obscurity of microservice architectures.

### 🔍 Unified Semantic RAG Chat & Glossary
* **Domain Glossary**: Tree-sitter extracts all classes, functions, and interfaces. The LLM translates these technical symbols into business-domain definitions, compiling a searchable, living glossary.
* **Multi-Source RAG**: Vector search combines code syntax blocks, commit messages, and PR summaries. Embedding vectors are generated using `text-embedding-3d` (1536 dimensions) and indexed in `pgvector` for fast cosine-similarity search.

---

## 🛠 Tech Stack

Illume leverages a modern, robust tech stack designed for architectural scanning, distributed ingestion, and high-performance visual graphing.

| Layer | Technology | Description |
|---|---|---|
| **Frontend Framework** | Next.js 16 (App Router) | Dynamic React framework for production-grade web applications. |
| **Backend Framework** | FastAPI (Python 3.12+, Async) | High-performance web framework for APIs and WebSocket logic. |
| **Syntax Parsing** | Tree-sitter | Deterministic multi-language Abstract Syntax Tree (AST) scanning. |
| **Task Queue** | Celery + Redis | Distributed asynchronous queue pipeline for heavy clone and scan operations. |
| **Database & ORM** | PostgreSQL + SQLAlchemy 2.0 | Scalable relational storage for file graphs, AST symbols, and git logs. |
| **Vector Search** | pgvector + OpenAI Embeddings | Cosine-similarity searches over 1536-dimensional semantic chunk spaces. |
| **Real-time Logs** | WebSockets + Redis Pub/Sub | Real-time progressive ingestion log streams from worker to browser. |
| **3D Force Graphing** | WebGL (react-force-graph-3d) | Accelerated interactive 3D module import graph visualization. |
| **UI & Animations** | Tailwind CSS 4 + Motion | Modern design tokens and fluid micro-animations for high-fidelity UX. |

---

## 📂 Codebase Directory Structure

```
illume/
├── client/                     # Next.js Frontend Application
│   ├── src/
│   │   ├── app/                # Next.js App Router Page Layouts
│   │   │   ├── dashboard/      # User repository workspace dashboard
│   │   │   ├── login/          # User Authentication forms
│   │   │   ├── repo/[id]/      # Deep Repository intelligence views
│   │   │   │   ├── explorer/   # File tree explorer & RAG workspace
│   │   │   │   ├── glossary/   # AI glossary search engine
│   │   │   │   └── graph/      # WebGL 3D Force-Graph canvas
│   │   │   └── globals.css     # Tailwind CSS 4 Design System Tokens
│   │   ├── components/         # High-Fidelity UI Components
│   │   │   ├── Chat.tsx        # Floating AI RAG chat system
│   │   │   ├── GraphClient.tsx # 3D force-graph wrapper
│   │   │   └── TerminalLogs.tsx# WebSocket streaming telemetry logger
│   │   └── hooks/              # Custom React logic hooks (useChat, etc.)
│   └── package.json            # Frontend dependency specifications
│
└── server/                     # FastAPI Backend Application
    ├── app/
    │   ├── api/                # FastAPI Routers
    │   │   ├── deps.py         # SQLAlchemy Session & Current User injections
    │   │   └── v1/             # API v1 Versioned endpoints
    │   ├── core/               # App configuration, security, database setups
    │   ├── models/             # SQLAlchemy ORM Database Schemas
    │   ├── services/           # Decoupled Core Domain Engines
    │   │   ├── parser.py       # Tree-sitter AST symbol extractor
    │   │   ├── import_resolver.py# Path aliases & package exports resolver
    │   │   ├── git_analyzer.py # git log --numstat history scraper
    │   │   ├── reading_order.py# Topological sorting & annotation logic
    │   │   ├── brief_generator.py# LLM executive architecture brief synthesiser
    │   │   └── embedder.py     # pgvector chunking & indexing engine
    │   └── tasks/              # Celery distributed tasks (ingestion workflow)
    ├── alembic/                # Relational DB Migration scripts
    └── pyproject.toml          # Python UV Package specification
```

---

## 🚀 Installation & Getting Started

### 📋 Prerequisites
* **Python 3.12+** (configured via [uv](https://github.com/astral-sh/uv) package manager)
* **Node.js 18+** & **npm**
* **Docker & Docker Compose** (for PostgreSQL and Redis microservices)
* **OpenAI API Key** (for RAG and glossary building)
* **GitHub OAuth app credentials** (Optional, for scanning private repositories)

---

### 📦 Step 1: Start PostgreSQL and Redis Infrastructure
Illume uses a pre-configured Docker Compose cluster. PostgreSQL includes the `pgvector` extension by default.

Verify that your `.env` is configured correctly, then run:

```bash
# Spin up the cluster in the background
docker compose up -d
```

Verify that PostgreSQL and Redis are running:
```bash
docker compose ps
```

---

### 🐍 Step 2: Configure the FastAPI Backend Server
Navigate to the `server/` directory, set up your `.env` from `.env.example`, sync dependencies, and perform database migrations.

```bash
cd server
cp .env.example .env
```

#### Synchronize Python Package Manager (UV)
```bash
# Sync dependency packages
uv sync

# Run database migrations using Alembic
uv run alembic upgrade head

# Spin up the FastAPI Web Server (port 8000)
uv run fastapi dev
```

---

### 🌾 Step 3: Run the Celery Worker Pipeline
Celery handles long-running, multi-layered repository ingestion tasks. Start a worker pointing to Redis.

```bash
cd server
uv run celery -A app.core.celery worker --loglevel=info -P threads
```

---

### 💻 Step 4: Boot the Next.js Web Client
Navigate to the `client/` directory, install packages, and boot the frontend dev server.

```bash
cd ../client
cp .env.example .env
npm install
npm run dev
```

The Web Interface is now accessible at **`http://localhost:3000`**. You can sign up locally, create a user workspace, submit any public or private GitHub repository, and watch the ingestion pipeline run in real-time!

---

## 🛡 Security

If you discover a security vulnerability within Illume, please send an e-mail to tejasnasa1908@gmail.com. All security vulnerabilities will be promptly addressed.

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.

---

<div align="center">

**Built with ❤️ for teams everywhere by [Tejas Nasa](https://github.com/tejasnasa)**

[![Follow Tejas](https://img.shields.io/github/followers/tejasnasa?label=Follow&style=social)](https://github.com/tejasnasa)
[![Twitter Follow](https://img.shields.io/twitter/follow/tejasnasa?style=social)](https://twitter.com/tejasnasa)

</div>
