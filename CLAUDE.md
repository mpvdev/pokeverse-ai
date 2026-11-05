# PokéVerse AI — Project Context & Development Guidelines

## 1. Project Overview

**Project Name:** PokéVerse AI  
**GitHub Repository:** `mpvdev/pokeverse-ai`  
**Project Type:** Multi-Agent AI + AWS Portfolio Project  
**Current Phase:** Phase 1 — Intelligent Pokédex  
**Development Approach:** Backend-first, CLI-first, learning-oriented

### Vision

PokéVerse AI is a Pokémon-themed, cloud-native multi-agent AI platform where users can:

- Research Pokémon and their abilities.
- Build and optimize competitive Pokémon teams.
- Learn battle strategies through personalized AI coaching.
- Participate in Pokémon battles powered by intelligent agents.
- Explore an interactive Pokémon world with autonomous NPCs and quests.
- Compete against autonomous AI trainers in tournaments.

The objective is to combine these capabilities into **one interconnected AI ecosystem**, rather than six independent applications.

### Primary Goals

1. Learn Generative AI, LLMs, and multi-agent systems from first principles.
2. Build a technically impressive AI + AWS engineering portfolio.
3. Demonstrate agent orchestration, tool calling, memory, RAG, reasoning, evaluation, and autonomous decision-making.
4. Apply production-grade software engineering and AWS architecture practices.
5. Understand every major implementation and architectural decision.

**This is primarily a learning project: the AI assistant implements in small, explained, reviewable steps, and the developer reviews and understands every change.**

---

## 2. Developer Background

The developer has:

- Advanced Python knowledge.
- Strong AWS experience.
- Experience with Terraform, Docker, Kubernetes, and EKS.
- Professional experience with cloud infrastructure, automation, CI/CD, and platform engineering.
- AWS Solutions Architect Professional and DevOps Engineer Professional certifications.

However, the developer is relatively new to:

- Large Language Models.
- Generative AI application development.
- Multi-agent frameworks.
- RAG and vector databases.
- Agent orchestration and memory.
- AI evaluation techniques.

### Mentorship Expectations

Act as a senior AI engineer, software architect, and technical mentor.

- Explain AI concepts deeply when they are introduced.
- Do not assume prior experience with LLM application development.
- Avoid spending excessive time explaining basic Python or AWS concepts.
- Explain why a technology or design is chosen.
- Discuss relevant trade-offs and alternatives.
- Make the implemented code easy to review and learn from.

---

## 3. Core Development Rules

### Rule 1 — Assistant Implements, Developer Reviews

The assistant writes the code; the developer reviews it.

Work in small, reviewable increments:

1. Explain the concept and the proposed design, including trade-offs.
2. Implement one small, well-scoped step (code + tests + doc updates).
3. Run tests and linting before handing over.
4. Summarize what changed, key design decisions, and open questions for review.
4a. Always end with copy-pasteable **"How to test"** scripts (verified to run): automated tests for the step, manual `uv run` scripts exercising the happy path and failure/edge cases, and expected output.
4b. When the last step of a phase is completed, clearly announce **"Phase N complete"** with a summary of the phase deliverable, an end-to-end test script for the whole phase, and what the next phase covers. Update `docs/PROGRESS.md` and the current phase in this file. I would prefer pushing only at the end of each phase, so suggest a good commit message when `git add` at the end of each phase.
5. Address review feedback.

Constraints:

- Keep each change small enough to review in one sitting; do not implement a whole phase at once.
- Ask before introducing new dependencies, infrastructure resources, or large refactors.
- Record significant design decisions in `CLAUDE.local.md` (local only, git-ignored; never commit or push decisions).
- **Never run `git add`, `git commit`, or `git push` (or any other command that changes the index, history, or remote).** The developer performs all git operations. Read-only git commands (`status`, `diff`, `log`) are fine.

### Rule 2 — Backend First

The project will initially be developed using:

- Python CLI applications.
- Python modules and packages.
- JSON-based input/output.
- Automated tests.
- REST APIs when required.

**Do not introduce a frontend until the explicitly planned frontend phase.**

React, Streamlit, or other UI technologies should not be introduced during early development.

### Rule 3 — Local Development First

Begin with a locally executable Python application.

Introduce AWS components progressively when they provide meaningful engineering value.

Avoid deploying unnecessary cloud infrastructure during the initial learning phases.

### Rule 4 — Incremental Complexity

Do not build the entire multi-agent architecture immediately.

Start with one agent, then progressively introduce:

- Tool calling.
- Structured outputs.
- Multiple agents.
- Agent orchestration.
- Shared state and memory.
- Retrieval-augmented generation.
- Evaluation.
- AWS deployment.
- Observability.

### Rule 5 — Production Engineering Mindset

Even though this is a learning project, apply sound engineering practices:

- Modular architecture.
- Type hints.
- Automated testing.
- Dependency management.
- Configuration management.
- Structured logging.
- Error handling.
- Security and secret management.
- Documentation.
- Reproducible infrastructure.
- CI/CD when appropriate.

Avoid overengineering early milestones.

---

## 4. Repository Strategy

The project uses a **single monorepo**.

Do not create separate repositories for individual agents or modules.

A possible long-term structure is:

```text
pokeverse-ai/
├── src/
│   └── pokeverse/
│       ├── agents/
│       ├── orchestration/
│       ├── catalog/
│       ├── battles/
│       ├── adventure/
│       ├── tournaments/
│       └── cli/
├── tests/
├── infra/
│   └── terraform/
├── docs/
├── scripts/
├── pyproject.toml
├── CLAUDE.md
└── README.md
```

This structure is a future target, not a requirement to create every directory immediately.

Only introduce modules and directories when they are needed.

---

## 5. Multi-Agent Architecture

The current long-term proposal includes **16 AI agents** grouped into seven areas.

This number is an architectural target, not a strict implementation requirement.

### 5.1 Core Orchestration — 1 Agent

**Supervisor Agent**

Responsibilities:

- Understand user requests.
- Delegate tasks to specialized agents.
- Coordinate agent execution.
- Aggregate results.
- Handle workflow-level failures.

### 5.2 Pokédex Research Lab — 3 Agents

**Pokémon Research Agent**
- Retrieve Pokémon details, abilities, types, moves, and statistics.
- Answer questions using verified data.

**Evolution Specialist**
- Analyze evolution paths and requirements.
- Explain evolution conditions.

**Knowledge Validator**
- Validate factual responses.
- Detect unsupported claims and inconsistencies.

### 5.3 Trainer Academy — 2 Agents

**AI Trainer Coach**
- Teach battle concepts.
- Provide personalized guidance.
- Recommend training exercises.

**Learning Assessment Agent**
- Evaluate trainer knowledge.
- Monitor learning progress.
- Identify areas for improvement.

### 5.4 Team Builder — 2 Agents

**Team Composition Agent**
- Construct Pokémon teams based on user constraints.
- Consider roles, types, abilities, and compatibility.

**Team Optimization Agent**
- Identify weaknesses in team composition.
- Recommend improvements.
- Evaluate alternative teams.

### 5.5 Battle Intelligence — 3 Agents

**Opponent Analysis Agent**
- Analyze opposing teams.
- Identify threats and potential counters.

**Battle Strategy Agent**
- Plan battle actions.
- Recommend moves, switches, and strategies.

**Battle Evaluation Agent**
- Analyze simulated battle results.
- Identify mistakes and improvement opportunities.

### 5.6 Adventure World — 3 Agents

**Game Master Agent**
- Manage interactive narratives.
- Generate contextual adventures and world interactions.

**NPC Agent**
- Generate NPC dialogue and decisions.
- Respond to player actions within defined constraints.

**Quest Designer Agent**
- Create quests, objectives, and challenges.
- Adapt quests to trainer progression.

### 5.7 Autonomous Tournament — 2 Agents

**AI Competitor Agent**
- Control autonomous AI trainers.
- Select actions based on competitive strategies.

**Tournament Analyst Agent**
- Analyze matches.
- Evaluate competitors.
- Provide tournament insights and performance summaries.

### Architectural Principle

Not every responsibility requires an AI agent.

Deterministic operations should remain ordinary software components, including:

- Damage calculations.
- Pokémon type effectiveness.
- Rules validation.
- Inventory updates.
- Battle state transitions.
- Tournament scheduling.
- Scorekeeping.
- Database operations.

Introduce distinct agents only when their independent reasoning responsibilities justify the complexity.

The final architecture may consolidate or expand agent responsibilities based on empirical evaluation.

---

## 6. Pokémon Data Architecture

### Decision: Hybrid Pokémon Catalog

PokéVerse AI will use **PokéAPI as an upstream reference data source** while maintaining its own local Pokémon catalog.

Do not make the external PokéAPI a mandatory runtime dependency for normal gameplay.

### Proposed Flow

```text
PokéAPI / Static Dataset
          |
          v
Data Ingestion Pipeline
          |
          v
Local Pokémon Catalog
          |
          v
Shared Catalog Interface
          |
          v
AI Agents and Game Services
```

### Initial Implementation

- Fetch relevant Pokémon information from PokéAPI.
- Validate and normalize API responses.
- Cache required data locally.
- Consider SQLite for the initial local database.
- Access Pokémon data through a shared interface.

### Future Enhancements

- Versioned reference datasets.
- Synchronization workflows.
- S3 backups.
- Data integrity checks.
- AWS-hosted catalog storage.
- Alternative upstream data imports.

### Resilience Requirements

PokéVerse AI should continue operating when PokéAPI is unavailable.

Design for:

- Temporary API outages.
- Network failures.
- API timeouts.
- Rate limiting.
- Permanent upstream shutdown.
- Local database recovery.

Previously synchronized Pokémon data must remain accessible even when the upstream API is unavailable.

An upstream outage may prevent importing new Pokémon data, but should not break existing gameplay.

### Data Ownership Separation

Maintain a clear distinction between:

**Reference Data**
- Pokémon identities.
- Types.
- Abilities.
- Moves.
- Base stats.
- Evolution rules.

**Application State**
- Trainer profiles.
- Captured Pokémon.
- Teams.
- Inventory.
- Quest progress.
- Battle history.

**AI-Generated Intelligence**
- Battle recommendations.
- Team optimization suggestions.
- Training plans.
- Quest narratives.
- Strategic explanations.

LLMs must not invent authoritative game mechanics or directly modify validated reference data.

---

## 7. Technology Preferences

These are proposed technologies, not immutable decisions.

### Application

- Python
- FastAPI, when REST APIs become necessary
- CLI for early development

### AI Engineering

- Amazon Bedrock
- Strands Agents or LangGraph, to be evaluated
- Tool calling and structured outputs
- RAG and vector search when justified
- Agent memory and orchestration
- Evaluation frameworks and tracing

### Storage

- SQLite during local development
- DynamoDB for appropriate cloud application state
- S3 for datasets, exports, and backups
- Vector search storage when required

### AWS Infrastructure

- Amazon Bedrock
- Lambda
- ECS/Fargate or EKS where justified
- SQS for asynchronous processing
- CloudWatch
- OpenTelemetry / ADOT
- Terraform

### Engineering Tooling

- Git and GitHub
- Python 3.15 (intentionally pinned to `>=3.15,<3.16`)
- uv for dependency management (`uv.lock`, `.python-version`, `[dependency-groups] dev`)
- httpx for HTTP
- boto3 / Amazon Bedrock Converse API for LLM inference (default model: Amazon Nova Lite)
- pytest
- Python linting and formatting
- Docker
- GitHub Actions

Do not select or introduce every technology upfront.

Every dependency should have a clear purpose.

---

## 8. Development Roadmap

### Phase 0 — Repository Foundation

Goals:
- Establish repository conventions.
- Select Python dependency management.
- Initialize the Python package.
- Establish testing and linting conventions.
- Create initial documentation.
- Build a minimal runnable CLI.

No agent implementation is required yet.

### Phase 1 — Intelligent Pokédex

Goals:
- Understand LLM inference.
- Learn prompting fundamentals.
- Integrate PokéAPI.
- Implement tool calling.
- Introduce structured outputs.
- Build the first Pokémon Research Agent.
- Develop a local catalog and caching approach.

Deliverable: A CLI-based intelligent Pokédex.

### Phase 2 — Multi-Agent Trainer System

Goals:
- Introduce the Supervisor Agent.
- Add specialized research and team-building capabilities.
- Implement agent delegation.
- Introduce shared context and task handoffs.
- Evaluate multi-agent collaboration.

Deliverable: A multi-agent Pokémon team advisor.

### Phase 3 — Battle Intelligence

Goals:
- Implement deterministic battle mechanics.
- Introduce battle strategy agents.
- Simulate battles.
- Analyze opponent strategies.
- Evaluate outcomes.
- Introduce feedback and improvement loops.

Deliverable: An AI-assisted battle strategy system.

### Phase 4 — Persistent Pokémon World

Goals:
- Implement trainer profiles.
- Introduce persistent application state.
- Add NPC interactions.
- Implement quests and exploration.
- Introduce relevant memory mechanisms.

Deliverable: A CLI-based Pokémon adventure experience.

### Phase 5 — AWS Deployment

Goals:
- Deploy appropriate components to AWS.
- Integrate Bedrock-based inference.
- Provision infrastructure through Terraform.
- Add persistent cloud storage.
- Implement logging, tracing, and monitoring.
- Introduce CI/CD and security controls.

Deliverable: A cloud-hosted PokéVerse AI backend.

### Phase 6 — Autonomous Tournament

Goals:
- Implement autonomous AI competitors.
- Coordinate tournament workflows.
- Support asynchronous simulations.
- Measure strategies and win rates.
- Evaluate agent decision quality.

Deliverable: A simulated autonomous Pokémon tournament system.

### Phase 7 — Frontend (Optional)

Goals:
- Introduce an interactive web application.
- Build a trainer dashboard.
- Visualize battles, tournaments, and exploration.

Frontend implementation is explicitly deferred until this phase.

---

## 9. Engineering and AI Evaluation

Throughout development, progressively introduce measurable quality criteria.

### Agent Evaluation

- Factual correctness.
- Tool-call accuracy.
- Validity of recommended teams.
- Strategy quality.
- Hallucination rates.
- Multi-agent versus single-agent performance.

### System Evaluation

- Response latency.
- Reliability during tool failures.
- Retry behavior.
- Test coverage.
- Observability.
- Token usage.
- Inference cost.
- AWS infrastructure cost.

### Portfolio Objectives

The completed repository should demonstrate:

- Real-world agent orchestration.
- Tool-driven LLM reasoning.
- Persistent state and memory.
- Production-style AWS architecture.
- Infrastructure as code.
- Fault tolerance.
- AI evaluation and observability.
- Clear technical documentation.

---

## 10. AI Assistant Collaboration

The developer uses a single AI assistant: **GitHub Copilot (Claude) in VS Code**, for everything.

### Assistant Responsibilities

- AI concepts and learning.
- Architecture discussions, design decisions, and trade-off reviews.
- Development planning and breaking work into small, reviewable steps.
- Implementing application code, tests, and documentation.
- Technical mentorship.
- Understanding the local repository.
- Reviewing developer-written code, identifying bugs, and explaining failures.
- Suggesting tests.
- Performing explicitly requested file changes (documentation, configuration, or code only when asked).

Per Rule 1: the assistant explains, designs, and implements; the developer reviews every change.

### Shared Context

The GitHub repository is the shared source of truth.

Maintain relevant information in:

- `CLAUDE.md` — Development guidance and project context.
- `docs/ARCHITECTURE.md` — Current technical architecture.
- `docs/PROGRESS.md` — Completed work, current phase, and next steps.

Architecture decisions are kept only in `CLAUDE.local.md`, which is git-ignored and must never be committed or pushed.

Keep documentation aligned with actual implementation.

Do not silently change established architectural decisions.

---

## 11. Current Status

The following decisions have already been made:

- Project name: PokéVerse AI.
- Repository: `mpvdev/pokeverse-ai`.
- Repository strategy: Single monorepo.
- Development strategy: Backend-first and CLI-first.
- Frontend: Deferred.
- Pokémon data source: PokéAPI with a locally maintained catalog.
- Data resilience: Core functionality must survive upstream API outages.
- Agent architecture: Proposed 16 agents, introduced progressively.
- AWS: Introduced incrementally.
- Python version: 3.15 only (`>=3.15,<3.16`), intentionally.
- Assistant writes the implementation code; developer reviews it.
- GitHub Copilot (Claude) in VS Code provides mentorship, architecture guidance, reviews, debugging, and explicitly requested changes.

**Current development phase: Phase 1 — Intelligent Pokédex** (branch `phase-1`).

Phase 0 (Repository Foundation) is complete:

- `src/` layout package `pokeverse` built with setuptools via `pyproject.toml`.
- Typer CLI (`pokeverse` / `python -m pokeverse`) with a welcome message and `--version`.
- Immutable, validated `Pokemon` domain model in `pokeverse.catalog`.
- pytest test suite and ruff linting/formatting conventions.

See `docs/PROGRESS.md` for detailed progress and next steps.

---

## 12. Immediate Next Steps

1. Build the deterministic PokéAPI client and local catalog before introducing any LLM.
2. Introduce LLM inference, then tool calling, then structured outputs — one step at a time.

Implement Phase 1 one step at a time (see `docs/PROGRESS.md`), handing each step to the developer for review before starting the next.

Wait for explicit instructions from the developer.

---

## 13. Additional Considerations

PokéVerse AI is an unofficial Pokémon fan project.

- Do not claim affiliation with Nintendo, The Pokémon Company, or Game Freak.
- Respect external API terms and data licensing.
- Avoid distributing copyrighted assets without appropriate permission.
- Prefer clearly documented data sources.
- Keep any eventual public deployment consistent with applicable intellectual property requirements.

---

## Guiding Philosophy

**Build to understand, not merely to finish.**

PokéVerse AI should evolve from a small, understandable Python application into a sophisticated multi-agent AI platform.

Favor clear reasoning, reliable engineering, measurable outcomes, and gradual complexity over unnecessary frameworks or premature architectural sophistication.