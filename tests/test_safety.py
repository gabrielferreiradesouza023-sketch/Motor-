import ast
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from arb import safety
from arb.launcher.approval import sign
from arb.models import Approval


def authorize(directory, kind, fingerprint="a" * 64):
    directory.mkdir(exist_ok=True)
    item = sign(
        Approval(
            id="signed",
            kind=kind,
            plan_hash=fingerprint,
            summary="Fixture",
            max_exposure_cents=6000,
            status="approved",
            decided_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    (directory / "signed.json").write_text(item.model_dump_json())
    return item


@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("kind", [*sorted(safety.KINDS), "delete"])
@pytest.mark.parametrize("state", ["missing", "unsigned", "wrong_hash", "valid"])
def test_mode_kind_approval_matrix(tmp_path, monkeypatch, live, kind, state):
    # Exercita permissão com função mockada, nunca coloca processo em LIVE_MODE=true.
    monkeypatch.setattr(safety, "live_mode", lambda: live)
    directory = tmp_path / "approved"
    identifier = None
    if kind in safety.KINDS and kind != "pause" and state != "missing":
        item = authorize(directory, kind)
        identifier = item.id
        if state == "unsigned":
            item.signature = None
        if state == "wrong_hash":
            item.plan_hash = "b" * 64
        (directory / "signed.json").write_text(item.model_dump_json())
    allowed = live and kind in safety.KINDS and (kind == "pause" or state == "valid")
    if allowed:
        result = safety.require_external_write(
            kind, identifier, fingerprint="a" * 64, exposure=6000, approval_dir=directory
        )
        assert result.kind == kind and result.live
    else:
        with pytest.raises(ValueError):
            safety.require_external_write(
                kind, identifier, fingerprint="a" * 64, exposure=6000, approval_dir=directory
            )


def test_local_and_invalid_mode(monkeypatch, caplog):
    monkeypatch.delenv("LIVE_MODE", raising=False)
    with caplog.at_level(logging.INFO):
        assert not safety.require_external_write("launch", simulation=True).live
    assert "write_intent" in caplog.text and "APPROVAL_SIGNING_KEY" not in caplog.text
    monkeypatch.setattr(safety, "live_mode", lambda: True)
    with pytest.raises(ValueError, match="LIVE_MODE=false"):
        safety.require_external_write("launch", simulation=True)
    monkeypatch.undo()
    monkeypatch.setenv("LIVE_MODE", "garbage")
    with pytest.raises(ValueError, match="inválido"):
        safety.live_mode()


def unsafe_writes(root):
    allowed = {
        ("scheduler/alerts.py", "Telegram.__call__", "post"),
        ("meta/pause.py", "PauseWriter.pause", "post"),
        ("accept_tracking.py", "tracking", "post"),
    }
    violations = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        aliases = {
            a.asname or a.name: a.name
            for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) and n.module in {"httpx", "requests"}
            for a in n.names
        }

        class Visitor(ast.NodeVisitor):
            def __init__(self, aliases, relative_path):
                self.aliases = aliases
                self.relative_path = relative_path
                self.scope = []

            def visit_ClassDef(self, node):
                self.scope.append(node.name)
                self.generic_visit(node)
                self.scope.pop()

            visit_FunctionDef = visit_ClassDef
            visit_AsyncFunctionDef = visit_ClassDef

            def visit_Call(self, node):
                method = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else self.aliases.get(node.func.id)
                    if isinstance(node.func, ast.Name)
                    else None
                )
                write = method in {"post", "put", "patch", "delete"}
                if method == "request":
                    argument = (
                        node.args[0]
                        if node.args
                        else next((k.value for k in node.keywords if k.arg == "method"), None)
                    )
                    write = not (
                        isinstance(argument, ast.Constant)
                        and isinstance(argument.value, str)
                        and argument.value.upper() in {"GET", "HEAD", "OPTIONS"}
                    )
                identity = (self.relative_path, ".".join(self.scope), method)
                if write and identity not in allowed:
                    violations.append((identity, node.lineno))
                self.generic_visit(node)

        Visitor(aliases, path.relative_to(root).as_posix()).visit(tree)
    return violations


def test_repository_write_allowlist():
    assert unsafe_writes(Path(__file__).resolve().parents[1] / "src/arb") == []


@pytest.mark.parametrize(
    "code",
    [
        "httpx.post('https://example.test')",
        "client.put('x')",
        "client.patch('x')",
        "client.delete('x')",
        "client.request('POST', 'x')",
        "client.request(method=unknown)",
        "from httpx import post as send\nsend('x')",
    ],
)
def test_static_barrier_detects_planted_calls(tmp_path, code):
    (tmp_path / "planted.py").write_text(code)
    assert len(unsafe_writes(tmp_path)) == 1


def test_static_barrier_allows_only_read_requests(tmp_path):
    (tmp_path / "read.py").write_text("client.request('GET', 'x')\nclient.get('x')")
    assert not unsafe_writes(tmp_path)
