"""Render/verificação determinísticos. Nunca instala, habilita ou inicia serviços."""

import fcntl
import hashlib
import json
import os
import re
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

from arb.config import Settings
from arb.permissions import inspect_paths, private_directory, private_open, reject_links

TEMPLATES = Path(__file__).resolve().parents[2] / "deploy/systemd"
NAMES = tuple(
    "arb-" + name + suffix
    for name in ("scheduler", "backup", "drill")
    for suffix in (".service", ".timer")
)


def contents(root: Path, user: str):
    if (
        not root.is_absolute()
        or any(char in str(root) for char in '\n\r"%$\\')
        or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user)
    ):
        raise ValueError("root absoluto e user Linux válidos são obrigatórios")
    reject_links(root)
    settings = Settings.model_validate(yaml.safe_load((root / "config/settings.yaml").read_text()))
    if settings.timezone != "America/Sao_Paulo":
        raise ValueError("serviço exige ciclos São Paulo")
    env = Environment(undefined=StrictUndefined, keep_trailing_newline=True, autoescape=False)
    return {
        name: env.from_string((TEMPLATES / name).read_text()).render(
            root=str(root), user=user, cycles=settings.cycles
        )
        for name in NAMES
    }


def render(root: Path, user: str, *, output: Path = Path("data/service")) -> dict:
    bodies = contents(root, user)
    private_directory(output)
    for name, body in bodies.items():
        with private_open(output / name) as file:
            file.write(body)
    manifest = {
        "schema": 1,
        "root": str(root),
        "user": user,
        "sha256": {
            name: hashlib.sha256(body.encode()).hexdigest() for name, body in bodies.items()
        },
    }
    with private_open(output / "manifest.json") as file:
        file.write(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return manifest


def check(*, output: Path = Path("data/service")) -> dict:
    errors = []
    try:
        reject_links(output / "manifest.json")
        manifest = json.loads((output / "manifest.json").read_text())
        if set(manifest) != {"schema", "root", "user", "sha256"} or manifest["schema"] != 1:
            raise ValueError("manifest inválido")
        root = Path(manifest["root"])
        expected = contents(root, manifest["user"])
        if set(manifest["sha256"]) != set(NAMES):
            raise ValueError("manifest incompleto")
        for name, body in expected.items():
            reject_links(output / name)
            actual = (output / name).read_text()
            if (
                actual != body
                or hashlib.sha256(actual.encode()).hexdigest() != manifest["sha256"][name]
            ):
                errors.append("unidade divergente: " + name)
        for name in (*NAMES, "manifest.json"):
            if (output / name).stat().st_mode & 0o077:
                errors.append("arquivo de serviço aberto: " + name)
        if output.stat().st_mode & 0o077:
            errors.append("diretório de serviço aberto")
        privacy = inspect_paths(root)
        if not privacy["ok"]:
            errors.append("permissões financeiras/symlinks inválidos")
        if not (root / ".venv/bin/arb").is_file() or not os.access(root / ".venv/bin/arb", os.X_OK):
            errors.append("executável local .venv/bin/arb ausente")
        reject_links(root / "data/engine.db.scheduler.lock")
        with (root / "data/engine.db.scheduler.lock").open("rb") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    except (OSError, ValueError, KeyError, TypeError):
        errors.append("pacote, configuração ou trava ausente/ocupada/inválida")
    return {
        "ok": not errors,
        "errors": sorted(set(errors)),
        "scope": "verificação somente leitura; serviço não instalado",
    }
