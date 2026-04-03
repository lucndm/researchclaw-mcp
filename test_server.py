"""Tests for researchclaw-mcp server helper functions and MCP tools."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "server",
    str(Path(__file__).resolve().parent / "server.py"),
)
_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_server)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json(result: str) -> dict:
    return json.loads(result)


def _seed_run(
    tmp_path: Path,
    run_id: str,
    status: str = "completed",
    topic: str = "test topic",
    commit: str | None = None,
    with_deliverables: bool = False,
) -> None:
    """Create a fake run directory with meta.json and optional deliverables."""
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "run_id": run_id,
        "topic": topic,
        "status": status,
        "started_at": "2026-04-02T10:00:00Z",
    }
    if commit:
        meta["commit"] = commit
    (run_dir / "meta.json").write_text(json.dumps(meta))
    if with_deliverables:
        d = run_dir / "deliverables"
        d.mkdir()
        (d / "paper_draft.md").write_text("# Test Paper\n\nSome content.")
        (d / "references.bib").write_text("@article{a}\n@article{b}\n@article{c}\n")
        charts = d / "charts"
        charts.mkdir()
        (charts / "fig1.png").write_bytes(b"\x89PNG")
        (charts / "fig2.png").write_bytes(b"\x89PNG")


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestGenerateRunId:
    _pattern = re.compile(r"^research_\d{8}_\d{6}_[0-9a-f]{8}$")

    def test_format(self) -> None:
        run_id = _server._generate_run_id()
        assert self._pattern.match(run_id), f"Run ID {run_id!r} does not match expected pattern"

    def test_uniqueness(self) -> None:
        id1 = _server._generate_run_id()
        id2 = _server._generate_run_id()
        assert id1 != id2


class TestReadWriteMeta:
    def test_round_trip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_server, "RUNS_DIR", tmp_path)
        data = {"run_id": "test-run", "topic": "test topic", "status": "running"}
        _server._write_meta("test-run", data)
        result = _server._read_meta("test-run")
        assert result["run_id"] == "test-run"
        assert result["topic"] == "test topic"
        assert result["status"] == "running"

    def test_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_server, "RUNS_DIR", tmp_path)
        assert _server._read_meta("nonexistent") == {}


class TestHasDeliverables:
    def test_present(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_server, "RUNS_DIR", tmp_path)
        run_dir = tmp_path / "test-run" / "deliverables"
        run_dir.mkdir(parents=True)
        (run_dir / "paper_draft.md").write_text("# Paper")
        assert _server._has_deliverables("test-run") is True

    def test_absent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_server, "RUNS_DIR", tmp_path)
        run_dir = tmp_path / "test-run"
        run_dir.mkdir(parents=True)
        assert _server._has_deliverables("test-run") is False

    def test_no_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_server, "RUNS_DIR", tmp_path)
        assert _server._has_deliverables("nonexistent") is False


# ---------------------------------------------------------------------------
# list_runs
# ---------------------------------------------------------------------------


class TestListRuns:
    def test_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_server, "RUNS_DIR", tmp_path)
        result = asyncio.get_event_loop().run_until_complete(_server.list_runs())
        assert _json(result) == {"runs": []}

    def test_returns_all_runs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_server, "RUNS_DIR", tmp_path)
        _seed_run(tmp_path, "run_a", status="completed")
        _seed_run(tmp_path, "run_b", status="running")
        result = asyncio.get_event_loop().run_until_complete(_server.list_runs())
        data = _json(result)
        assert len(data["runs"]) == 2

    def test_filter_by_status(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_server, "RUNS_DIR", tmp_path)
        _seed_run(tmp_path, "run_a", status="completed")
        _seed_run(tmp_path, "run_b", status="running")
        result = asyncio.get_event_loop().run_until_complete(_server.list_runs(status="running"))
        data = _json(result)
        assert len(data["runs"]) == 1
        assert data["runs"][0]["run_id"] == "run_b"

    def test_sorted_newest_first(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_server, "RUNS_DIR", tmp_path)
        _seed_run(tmp_path, "old_run", status="completed")
        _seed_run(tmp_path, "new_run", status="completed")
        # Update started_at on old_run to be earlier
        old_meta_path = tmp_path / "old_run" / "meta.json"
        old_meta = json.loads(old_meta_path.read_text())
        old_meta["started_at"] = "2026-01-01T00:00:00Z"
        old_meta_path.write_text(json.dumps(old_meta))

        result = asyncio.get_event_loop().run_until_complete(_server.list_runs())
        data = _json(result)
        assert data["runs"][0]["run_id"] == "new_run"
        assert data["runs"][1]["run_id"] == "old_run"


# ---------------------------------------------------------------------------
# get_paper
# ---------------------------------------------------------------------------


class TestGetPaper:
    def test_markdown(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_server, "RUNS_DIR", tmp_path)
        _seed_run(tmp_path, "run1", with_deliverables=True)
        result = asyncio.get_event_loop().run_until_complete(_server.get_paper("run1", "markdown"))
        data = _json(result)
        assert "Test Paper" in data["content"]
        assert data["references_count"] == 3
        assert len(data["charts"]) == 2
        assert "fig1.png" in data["charts"]

    def test_latex(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_server, "RUNS_DIR", tmp_path)
        _seed_run(tmp_path, "run1", with_deliverables=True)
        (tmp_path / "run1" / "deliverables" / "paper.tex").write_text("\\documentclass{article}")
        result = asyncio.get_event_loop().run_until_complete(_server.get_paper("run1", "latex"))
        data = _json(result)
        assert "\\documentclass" in data["content"]

    def test_no_paper(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_server, "RUNS_DIR", tmp_path)
        result = asyncio.get_event_loop().run_until_complete(_server.get_paper("missing"))
        data = _json(result)
        assert "error" in data


# ---------------------------------------------------------------------------
# get_experiment_results
# ---------------------------------------------------------------------------


class TestGetExperimentResults:
    def test_json_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_server, "RUNS_DIR", tmp_path)
        run_dir = tmp_path / "run1"
        run_dir.mkdir()
        (run_dir / "experiment_results.json").write_text('{"metrics": {"accuracy": 0.95}}')
        result = asyncio.get_event_loop().run_until_complete(_server.get_experiment_results("run1"))
        data = _json(result)
        assert data["metrics"]["accuracy"] == 0.95

    def test_experiment_runs_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_server, "RUNS_DIR", tmp_path)
        exp_dir = tmp_path / "run1" / "experiment_runs"
        exp_dir.mkdir(parents=True)
        (exp_dir / "exp1.json").write_text("{}")
        (exp_dir / "exp2.json").write_text("{}")
        result = asyncio.get_event_loop().run_until_complete(_server.get_experiment_results("run1"))
        data = _json(result)
        assert sorted(data["files"]) == ["exp1.json", "exp2.json"]

    def test_no_results(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_server, "RUNS_DIR", tmp_path)
        result = asyncio.get_event_loop().run_until_complete(_server.get_experiment_results("missing"))
        data = _json(result)
        assert "error" in data


# ---------------------------------------------------------------------------
# get_pipeline_status
# ---------------------------------------------------------------------------


class TestGetPipelineStatus:
    def test_not_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_server, "RUNS_DIR", tmp_path)
        result = asyncio.get_event_loop().run_until_complete(_server.get_pipeline_status("missing"))
        data = _json(result)
        assert "error" in data

    def test_completed_status(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_server, "RUNS_DIR", tmp_path)
        _seed_run(tmp_path, "done_run", status="completed", commit="abc1234")
        result = asyncio.get_event_loop().run_until_complete(_server.get_pipeline_status("done_run"))
        data = _json(result)
        assert data["status"] == "completed"
        assert data["commit"] == "abc1234"

    def test_failed_status(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_server, "RUNS_DIR", tmp_path)
        _seed_run(tmp_path, "fail_run", status="failed")
        result = asyncio.get_event_loop().run_until_complete(_server.get_pipeline_status("fail_run"))
        data = _json(result)
        assert data["status"] == "failed"


# ---------------------------------------------------------------------------
# cancel_run
# ---------------------------------------------------------------------------


class TestCancelRun:
    def test_no_active_process(self) -> None:
        result = asyncio.get_event_loop().run_until_complete(_server.cancel_run("nonexistent"))
        data = _json(result)
        assert "error" in data


# ---------------------------------------------------------------------------
# run_pipeline
# ---------------------------------------------------------------------------


class TestRunPipeline:
    def test_semaphore_full(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When semaphore is full, returns queued status immediately."""
        monkeypatch.setattr(_server, "RUNS_DIR", tmp_path)
        sem = asyncio.Semaphore(0)
        monkeypatch.setattr(_server, "_run_semaphore", sem)
        result = asyncio.get_event_loop().run_until_complete(_server.run_pipeline("test"))
        data = _json(result)
        assert data["status"] == "queued"


# ---------------------------------------------------------------------------
# search_literature
# ---------------------------------------------------------------------------


class TestSearchLiterature:
    def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_output = json.dumps([{"title": "Paper A", "year": 2024}]).encode()

        class FakeProc:
            returncode = 0

            async def communicate(self):
                return fake_output, b""

        async def _fake_create(*args, **kwargs):
            return FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)
        result = asyncio.get_event_loop().run_until_complete(
            _server.search_literature("transformers")
        )
        data = json.loads(result)
        assert data[0]["title"] == "Paper A"

    def test_cli_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake_create(*args, **kwargs):
            raise FileNotFoundError("researchclaw")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)
        result = asyncio.get_event_loop().run_until_complete(
            _server.search_literature("test")
        )
        data = _json(result)
        assert "error" in data
        assert "not found" in data["error"]

    def test_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake_create(*args, **kwargs):
            raise asyncio.TimeoutError()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)
        result = asyncio.get_event_loop().run_until_complete(
            _server.search_literature("test")
        )
        data = _json(result)
        assert "timed out" in data["error"]


# ---------------------------------------------------------------------------
# _git_commit_and_push
# ---------------------------------------------------------------------------


class TestGitCommitAndPush:
    def test_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_server, "RUNS_DIR", tmp_path)
        repo = tmp_path / "output-repo"
        repo.mkdir()
        # Fake deliverables
        run_dir = tmp_path / "run1" / "deliverables"
        run_dir.mkdir(parents=True)
        (run_dir / "paper_draft.md").write_text("# Paper")

        monkeypatch.setattr(_server, "OUTPUT_REPO", repo)
        call_log: list[list[str]] = []

        def _fake_run(cmd, **kwargs):
            call_log.append(cmd)
            # Return commit hash for rev-parse
            if "rev-parse" in cmd:
                r = type("R", (), {"stdout": "abcdef1234567890\n", "returncode": 0})()
                return r
            r = type("R", (), {"returncode": 0})()
            return r

        monkeypatch.setattr(_server.subprocess, "run", _fake_run)
        result = _server._git_commit_and_push("run1", "test topic")
        assert result == "abcdef12"
        # Should have: git add, git commit, git rev-parse, git push
        commands = [c[1] for c in call_log]
        assert "add" in commands
        assert "commit" in commands
        assert "push" in commands

    def test_no_deliverables(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_server, "OUTPUT_REPO", tmp_path / "no-repo")
        result = _server._git_commit_and_push("missing", "test")
        assert result is None

    def test_git_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = tmp_path / "output-repo"
        repo.mkdir()
        run_dir = tmp_path / "run1" / "deliverables"
        run_dir.mkdir(parents=True)
        (run_dir / "paper_draft.md").write_text("# Paper")

        monkeypatch.setattr(_server, "OUTPUT_REPO", repo)

        def _fake_run(cmd, **kwargs):
            if "commit" in cmd:
                raise _server.subprocess.CalledProcessError(1, cmd)

        monkeypatch.setattr(_server.subprocess, "run", _fake_run)
        result = _server._git_commit_and_push("run1", "test")
        assert result is None
