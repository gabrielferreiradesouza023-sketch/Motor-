"""Restauração validada em caminho novo. Nunca sobrescreve o banco de trabalho."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import NamedTemporaryFile

from arb.db import TABLES, Repository, migrate


def restore_new(backup: Path, destination: Path) -> Path:
    backup = backup.resolve()
    destination = destination.resolve()
    if not backup.is_file():
        raise ValueError("backup não encontrado")
    if destination.exists():
        raise ValueError("destino existe; restaure em banco novo")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        dir=destination.parent, prefix="arb-restore-", suffix=".db", delete=False
    ) as file:
        temporary = Path(file.name)
    try:
        with closing(sqlite3.connect(f"{backup.as_uri()}?mode=ro", uri=True)) as source:
            if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("backup com integridade inválida")
            with closing(sqlite3.connect(temporary)) as restored:
                source.backup(restored)
                restored.execute("PRAGMA foreign_keys=ON")
                migrate(restored)  # também confere checksums, aceita versões anteriores válidas
                if (
                    restored.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                    or restored.execute("PRAGMA foreign_key_check").fetchall()
                ):
                    raise ValueError("backup com integridade/referências inválidas")
                for model in TABLES:
                    Repository(restored, model).list()
        # Publicação atômica que recusa concorrência, sem substituir caminho existente.
        os.link(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)
