"""Metadados apenas: modos financeiros fechados e recusa de symlinks."""

import os
import stat
from pathlib import Path


def posix():
    return os.name == "posix"


def reject_links(path: Path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("caminho financeiro não pode conter symlink")


def private_directory(path: Path):
    reject_links(path)
    missing = []
    parent = path
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700, exist_ok=True)
    if not path.is_dir():
        raise ValueError("diretório financeiro inválido")
    if posix():
        path.chmod(0o700)


def private_open(path: Path, *, exclusive=False, append=False):
    reject_links(path)
    private_directory(path.parent)
    flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    flags |= os.O_EXCL if exclusive else os.O_APPEND if append else os.O_TRUNC
    descriptor = os.open(path, flags, 0o600)
    try:
        if posix():
            os.fchmod(descriptor, 0o600)
        return os.fdopen(descriptor, "a" if append else "w", encoding="utf-8")
    except BaseException:
        os.close(descriptor)
        raise


def inspect_paths(root: Path, *, database: Path | None = None) -> dict:
    roots = [root / "data", root / "ops/approvals/approved", root / "reports"]
    if database is not None and database.parent not in roots:
        roots.append(database.parent)
    findings = []
    windows = not posix()
    for directory in roots:
        try:
            reject_links(directory)
            if not directory.exists():
                continue
            for path in (directory, *directory.rglob("*")):
                reject_links(path)
                metadata = path.stat()
                if path.name == ".gitkeep" and metadata.st_size == 0:
                    continue
                if not windows:
                    expected = 0o700 if path.is_dir() else 0o600
                    if stat.S_IMODE(metadata.st_mode) != expected:
                        findings.append(
                            {"path": str(path), "kind": "mode", "expected": oct(expected)}
                        )
        except (OSError, ValueError):
            findings.append({"path": str(directory), "kind": "symlink_or_unavailable"})
    return {
        "ok": not findings,
        "findings": findings,
        "warnings": [
            "Windows/non-POSIX: verificar ACLs no host; bits POSIX não comprovam isolamento"
        ]
        if windows
        else [],
    }


def report_paths(targets, *, source=None):
    """Operator pipeline outputs cannot alias inputs, config, or each other."""
    from pathlib import Path

    from arb.permissions import reject_links

    previous = [source] if source is not None else []
    for target in targets:
        reject_links(target)
        if Path("config").resolve() in (target.resolve(), *target.resolve().parents):
            raise ValueError("saída não pode escrever em config")
        for other in previous:
            if target.resolve() == other.resolve() or (
                target.exists() and other.exists() and target.samefile(other)
            ):
                raise ValueError("saída não pode sobrescrever origem ou outro relatório")
        previous.append(target)
