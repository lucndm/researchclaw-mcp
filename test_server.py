"""Tests for researchclaw-mcp server helper functions."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "server",
    str(Path(__file__).resolve().parent / "server.py"),
)
_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_server)  # type: ignore[union-attr]


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
