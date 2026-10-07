"""Provedor em memória: hipóteses de dedupe, sem rede e sem payloads Graph."""

import hashlib
import json
from collections.abc import Callable

from arb.models import Entity

FAULTS = {"before_timeout", "after_timeout", "server_error", "rate_limit", "invalid_response"}


class RemoteError(RuntimeError):
    pass


class FakeMeta:
    simulation_only = True

    def __init__(self, *, on_call: Callable | None = None):
        self.entities: dict[str, Entity] = {}
        self.creations: dict[str, str] = {}
        self.applied: dict[str, tuple[str, str]] = {}
        self.calls: list[dict] = []
        self.effects: list[dict] = []
        self.faults: dict[str, list[str]] = {}
        self.on_call = on_call

    def fail_next(self, operation: str, fault: str):
        if operation not in {"create", "activate", "scale", "pause"} or fault not in FAULTS:
            raise ValueError("falha simulada desconhecida")
        self.faults.setdefault(operation, []).append(fault)

    def read(self, remote_id: str) -> Entity | None:
        entity = self.entities.get(remote_id)
        return entity.model_copy(deep=True) if entity is not None else None

    def locate(self, key: str) -> Entity | None:
        identifier = self.creations.get(key)
        return self.read(identifier) if identifier else None

    def ads(self) -> list[dict]:
        # Adaptador de leitura para o shape id/status já consumido pelo reconciliador.
        return [
            {"id": identifier, "status": e.status.upper()}
            for identifier, e in sorted(self.entities.items())
        ]

    def _write(self, operation, key, arguments, perform):
        if not isinstance(key, str) or not key:
            raise ValueError("chave de operação obrigatória")
        fingerprint = json.dumps([operation, arguments], sort_keys=True, separators=(",", ":"))
        if key in self.applied and self.applied[key][0] != fingerprint:
            raise ValueError("chave reutilizada para outra intenção")
        call = {"operation": operation, "key": key, "arguments": arguments}
        self.calls.append(call)
        if self.on_call:
            self.on_call(call)
        queue = self.faults.get(operation, [])
        fault = queue.pop(0) if queue else None
        if fault == "before_timeout":
            raise TimeoutError("timeout antes do efeito")
        if fault in {"server_error", "rate_limit"}:
            raise RemoteError("falha simulada antes do efeito")
        if key not in self.applied:
            entity = perform()
            self.applied[key] = (fingerprint, entity.meta_id)
            self.effects.append(call)
        else:
            entity = self.read(self.applied[key][1])
        if fault == "after_timeout":
            raise TimeoutError("efeito aplicado, resposta perdida")
        if fault == "invalid_response":
            return {}
        return entity.model_dump(mode="json")

    def create(self, entity: Entity, key: str) -> dict:
        if entity.status != "paused" or entity.meta_id is not None:
            raise ValueError("criação somente de entidade pausada sem meta_id")

        def perform():
            identifier = "fake-" + hashlib.sha256(key.encode()).hexdigest()[:20]
            created = Entity.model_validate(entity.model_dump() | {"meta_id": identifier})
            self.entities[identifier] = created
            self.creations[key] = identifier
            return created

        return self._write("create", key, entity.model_dump(mode="json"), perform)

    def _update(self, identifier, changes):
        if identifier not in self.entities:
            raise ValueError("entidade remota desconhecida")
        updated = Entity.model_validate(self.entities[identifier].model_dump() | changes)
        self.entities[identifier] = updated
        return updated

    def activate(self, identifier: str, key: str) -> dict:
        return self._write(
            "activate",
            key,
            {"meta_id": identifier},
            lambda: self._update(identifier, {"status": "active"}),
        )

    def set_budget(self, identifier: str, budget: int, key: str) -> dict:
        return self._write(
            "scale",
            key,
            {"meta_id": identifier, "budget": budget},
            lambda: self._update(identifier, {"daily_budget_cents": budget}),
        )

    def pause(self, identifier: str, key: str) -> dict:
        return self._write(
            "pause",
            key,
            {"meta_id": identifier},
            lambda: self._update(identifier, {"status": "paused"}),
        )
