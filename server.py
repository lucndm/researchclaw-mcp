"""ResearchClaw MCP Server — exposes AutoResearchClaw pipeline via MCP tools."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from loguru import logger
from mcp.server.fastmcp import FastMCP

RUNS_DIR = Path(os.getenv("RUNS_DIR", "/workspace/runs"))
OUTPUT_REPO = Path(os.getenv("OUTPUT_REPO", "/workspace/output-repo"))
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT_RUNS", "1"))

mcp = FastMCP("ResearchClaw")

_run_semaphore = asyncio.Semaphore(MAX_CONCURRENT)
_active_processes: dict[str, asyncio.subprocess.Process] = {}


def _generate_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"research_{ts}_{secrets.token_hex(4)}"


def _meta_path(run_id: str) -> Path:
    return RUNS_DIR / run_id / "meta.json"


def _read_meta(run_id: str) -> dict[str, Any]:
    path = _meta_path(run_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_meta(run_id: str, data: dict[str, Any]) -> None:
    path = _meta_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _has_deliverables(run_id: str) -> bool:
    return (RUNS_DIR / run_id / "deliverables" / "paper_draft.md").is_file()


def _git_commit_and_push(run_id: str, topic: str) -> str | None:
    """Copy deliverables to output repo, commit and push. Returns commit hash or None."""
    src = RUNS_DIR / run_id / "deliverables"
    dst = OUTPUT_REPO / run_id
    if not src.exists():
        return None
    shutil.copytree(src, dst)
    try:
        subprocess.run(
            ["git", "add", run_id], cwd=OUTPUT_REPO, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", f"research: {topic} ({run_id})"],
            cwd=OUTPUT_REPO, check=True, capture_output=True,
        )
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=OUTPUT_REPO, capture_output=True, text=True, check=True,
        )
        subprocess.run(["git", "push"], cwd=OUTPUT_REPO, check=True, capture_output=True)
        return result.stdout.strip()[:8]
    except subprocess.CalledProcessError as exc:
        logger.error("Git operation failed for {}: {}", run_id, exc)
        return None


async def _monitor_run(run_id: str, callback_url: str | None) -> None:
    """Background task: wait for subprocess, git commit+push, send webhook callback."""
    proc = _active_processes.get(run_id)
    if not proc:
        return

    try:
        await proc.wait()
        meta = _read_meta(run_id)

        if proc.returncode == 0 and _has_deliverables(run_id):
            commit_hash = await asyncio.to_thread(
                _git_commit_and_push, run_id, meta.get("topic", ""),
            )
            _write_meta(run_id, {**meta, "status": "completed", "commit": commit_hash})
            payload: dict[str, Any] = {"run_id": run_id, "status": "completed", "commit": commit_hash}
        else:
            _write_meta(run_id, {**meta, "status": "failed", "exit_code": proc.returncode})
            payload = {"run_id": run_id, "status": "failed", "exit_code": proc.returncode}

        if callback_url:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(callback_url, json=payload, timeout=10)
                    logger.info("Callback {} -> {}", callback_url, resp.status_code)
            except Exception as exc:
                logger.warning("Webhook callback failed for {}: {}", run_id, exc)
    finally:
        _active_processes.pop(run_id, None)
        _run_semaphore.release()


@mcp.tool()
async def run_pipeline(
    topic: str,
    callback_url: str | None = None,
    auto_approve: bool = True,
    config_path: str | None = None,
) -> str:
    """Start an autonomous research pipeline. Returns run_id immediately."""
    try:
        await asyncio.wait_for(_run_semaphore.acquire(), timeout=0)
    except asyncio.TimeoutError:
        return json.dumps({"status": "queued", "message": "Max concurrent runs reached"})

    run_id = _generate_run_id()
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    cmd = ["researchclaw", "run", "--topic", topic, "--output-dir", str(run_dir)]
    if auto_approve:
        cmd.append("--auto-approve")
    if config_path:
        cmd.extend(["--config", config_path])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=open(run_dir / "stdout.log", "w"),
        stderr=open(run_dir / "stderr.log", "w"),
    )

    _active_processes[run_id] = proc
    _write_meta(run_id, {
        "run_id": run_id,
        "topic": topic,
        "pid": proc.pid,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "auto_approve": auto_approve,
        "status": "running",
        "callback_url": callback_url,
    })

    asyncio.create_task(_monitor_run(run_id, callback_url))
    logger.info("Started pipeline {} for topic: {}", run_id, topic)

    return json.dumps({"run_id": run_id, "status": "running", "output_dir": str(run_dir)})


@mcp.tool()
async def get_pipeline_status(run_id: str) -> str:
    """Get current status of a research pipeline run."""
    meta = _read_meta(run_id)
    if not meta:
        return json.dumps({"error": f"Run {run_id} not found"})

    pid = meta.get("pid")
    if pid:
        try:
            os.kill(pid, 0)
            checkpoint_path = RUNS_DIR / run_id / "checkpoint.json"
            stage = None
            if checkpoint_path.exists():
                cp = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                stage = cp.get("current_stage")
            return json.dumps({
                "run_id": run_id,
                "status": "running",
                "stage": stage,
                "started_at": meta.get("started_at"),
            })
        except ProcessLookupError:
            pass

    return json.dumps({
        "run_id": run_id,
        "status": meta.get("status", "unknown"),
        "commit": meta.get("commit"),
        "started_at": meta.get("started_at"),
    })


@mcp.tool()
async def get_paper(run_id: str, format: str = "markdown") -> str:
    """Get generated paper from a pipeline run."""
    ext = "paper_draft.md" if format == "markdown" else "paper.tex"
    path = RUNS_DIR / run_id / "deliverables" / ext
    if not path.exists():
        return json.dumps({"error": f"Paper not found for run {run_id}"})

    content = path.read_text(encoding="utf-8")
    bib_path = RUNS_DIR / run_id / "deliverables" / "references.bib"
    refs_count = 0
    if bib_path.exists():
        refs_count = bib_path.read_text(encoding="utf-8").count("@")

    charts_dir = RUNS_DIR / run_id / "deliverables" / "charts"
    charts = [f.name for f in charts_dir.iterdir()] if charts_dir.exists() else []

    return json.dumps({
        "run_id": run_id,
        "content": content,
        "references_count": refs_count,
        "charts": charts,
    })


@mcp.tool()
async def get_experiment_results(run_id: str) -> str:
    """Get experiment results from a pipeline run."""
    path = RUNS_DIR / run_id / "experiment_results.json"
    if not path.exists():
        exp_dir = RUNS_DIR / run_id / "experiment_runs"
        if exp_dir.exists():
            results = [f.name for f in exp_dir.iterdir()]
            return json.dumps({"run_id": run_id, "files": results})
        return json.dumps({"error": f"No experiment results found for run {run_id}"})
    return path.read_text(encoding="utf-8")


@mcp.tool()
async def search_literature(query: str, max_results: int = 10) -> str:
    """Search academic papers using OpenAlex, Semantic Scholar, and arXiv."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "researchclaw", "search", "--query", query, "--max-results", str(max_results),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode != 0:
            return json.dumps({"error": f"Literature search failed: {stderr.decode('utf-8', errors='replace')}"})
        return stdout.decode("utf-8", errors="replace")
    except FileNotFoundError:
        return json.dumps({"error": "researchclaw CLI not found — is it installed?"})
    except asyncio.TimeoutError:
        return json.dumps({"error": "Literature search timed out"})


@mcp.tool()
async def list_runs(status: str | None = None) -> str:
    """List all research pipeline runs, optionally filtered by status."""
    runs: list[dict[str, Any]] = []
    for meta_file in RUNS_DIR.glob("*/meta.json"):
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        if status and meta.get("status") != status:
            continue
        runs.append({
            "run_id": meta.get("run_id"),
            "topic": meta.get("topic"),
            "status": meta.get("status"),
            "started_at": meta.get("started_at"),
        })
    return json.dumps({"runs": sorted(runs, key=lambda r: r.get("started_at", ""), reverse=True)})


@mcp.tool()
async def cancel_run(run_id: str) -> str:
    """Cancel a running research pipeline."""
    proc = _active_processes.get(run_id)
    if not proc or proc.returncode is not None:
        return json.dumps({"error": f"No active process for run {run_id}"})
    proc.terminate()
    await asyncio.sleep(2)
    if proc.returncode is None:
        proc.kill()
    _active_processes.pop(run_id, None)
    meta = _read_meta(run_id)
    _write_meta(run_id, {**meta, "status": "cancelled"})
    _run_semaphore.release()
    return json.dumps({"run_id": run_id, "status": "cancelled"})


if __name__ == "__main__":
    mcp.run(transport="sse")
