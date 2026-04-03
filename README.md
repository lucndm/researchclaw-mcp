# ResearchClaw MCP Server

MCP server wrapping [AutoResearchClaw](https://github.com/aiming-lab/AutoResearchClaw) — an autonomous research pipeline (23 stages, topic → academic paper with verified references, experiments, and charts).

## Quick Reference for LLM Agents

### Connection

```
Transport: SSE
URL: http://<host>:8000/sse
```

Docker: `ghcr.io/lucndm/researchclaw-mcp:latest`

### Tools

| Tool | Params | Returns | Description |
|------|--------|---------|-------------|
| `run_pipeline` | `topic: str`, `callback_url?: str`, `auto_approve?: bool`, `config_path?: str` | `{run_id, status, output_dir}` | Start research. Non-blocking, returns immediately. |
| `get_pipeline_status` | `run_id: str` | `{run_id, status, stage?, started_at, commit?}` | Check status. `status` = running/completed/failed/queued. |
| `get_paper` | `run_id: str`, `format?: str` (markdown/latex) | `{run_id, content, references_count, charts}` | Get generated paper content. |
| `get_experiment_results` | `run_id: str` | `{results}` or `{files}` | Get experiment output. |
| `search_literature` | `query: str`, `max_results?: int` (default 10) | `[{title, authors, year, doi, abstract}]` | Standalone literature search. No pipeline needed. |
| `list_runs` | `status?: str` | `{runs: [{run_id, topic, status, started_at}]}` | List all runs, newest first. |
| `cancel_run` | `run_id: str` | `{run_id, status: "cancelled"}` | Kill a running pipeline. |

### Typical Workflow

```
1. run_pipeline(topic) → get run_id
2. Wait 20-60 minutes (poll get_pipeline_status, or use callback_url)
3. get_paper(run_id) → full paper markdown + references + charts
4. (optional) get_experiment_results(run_id)
```

### Callback / Webhook

Pass `callback_url` to `run_pipeline`. When the pipeline finishes, the server POSTs:

```json
{"run_id": "research_20260402_100000_a1b2c3d4", "status": "completed", "commit": "abc1234"}
```

or on failure:

```json
{"run_id": "research_20260402_100000_a1b2c3d4", "status": "failed", "exit_code": 1}
```

### Concurrency

Default max 1 concurrent pipeline run. If full, `run_pipeline` returns `{status: "queued"}` instead of starting.

### Cost & Duration

- ~$2-5 per run (LLM API calls)
- 20-60 minutes depending on topic complexity
- References are real (OpenAlex, Semantic Scholar, arXiv), 4-layer verified

### Error Patterns

| Scenario | What happens |
|----------|-------------|
| `run_pipeline` with full semaphore | Returns `{status: "queued"}` |
| `get_pipeline_status` unknown run_id | Returns `{error: "Run ... not found"}` |
| `get_paper` before completion | Returns `{error: "Paper not found for run ..."}` |
| Pipeline crashes | `get_pipeline_status` returns `status: "failed"` |
| Git push fails | `status: "completed"` but no `commit` field |

## Setup

```bash
# Clone
git clone git@github.com:lucndm/researchclaw-mcp.git
cd researchclaw-mcp

# Configure
cp .env.example .env
# Edit .env with API keys and OUTPUT_REPO_URL

# Run
docker compose up -d

# Verify
curl http://localhost:8000/sse
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI API key |
| `ANTHROPIC_API_KEY` | No | Anthropic API key (alternative model) |
| `OUTPUT_REPO_URL` | No | Git repo for output papers (SSH) |
| `MAX_CONCURRENT_RUNS` | No | Max parallel pipelines (default: 1) |

### Volumes

| Host | Container | Purpose |
|------|-----------|---------|
| `./runs` | `/workspace/runs` | Persist run data |
| `~/.ssh` | `/root/.ssh:ro` | Git push SSH key |
| `./config.arc.yaml` | `/workspace/config.arc.yaml:ro` | ResearchClaw config |

## Why This Wrapper Exists

AutoResearchClaw upstream has two modules that sound relevant but neither provides a working MCP server:

### `researchclaw/server/` — Web Dashboard (NOT MCP)

FastAPI app (v0.5.0) with REST endpoints (`/api/pipeline/start`, `/api/runs`) and WebSocket for a web UI. This is a **dashboard**, not an MCP server.

### `researchclaw/mcp/` — Stubs Only

As of upstream main (checked 2026-04-03), the MCP module is incomplete:

| Component | Status |
|-----------|--------|
| `tools.py` | Schema definitions only — no handler logic |
| `server.py` | All 6 tool handlers are stubs (`return "mcp-stub-..."`, `"Literature search stub"`, etc.) |
| `transport.py` | `StdioTransport` works, `SSETransport` raises `NotImplementedError` |

Missing from native MCP module: `list_runs`, `cancel_run`, `callback_url`, git commit+push, Docker setup, concurrency control, run isolation.

### Decision

Rather than forking and completing the stubs, this repo wraps the proven CLI (`researchclaw run`) via subprocess. **If upstream completes its MCP module in the future, this wrapper should be replaced.**

## Architecture

```
MCP Client (nanobot, Claude Code, etc.)
  → SSE → FastMCP Server (port 8000)
              → researchclaw CLI (subprocess)
              → /workspace/runs/<run_id>/
                  ├── meta.json
                  ├── deliverables/
                  │   ├── paper_draft.md
                  │   ├── paper.tex
                  │   ├── references.bib
                  │   └── charts/
                  └── experiment_runs/
              → Git commit+push (on completion)
              → POST callback_url
```

## Development

```bash
pip install mcp[cli] httpx loguru pytest ruff
pytest test_server.py -v
ruff check server.py test_server.py
```
