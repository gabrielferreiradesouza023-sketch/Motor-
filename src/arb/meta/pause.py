"""Única escrita Meta: status=PAUSED. Nenhum transporte real em simulação."""

import os
import re
from dataclasses import dataclass, field

import httpx

from arb import safety


class MetaPauseError(RuntimeError):
    """Erro sanitizado: não propaga URL, token, headers nem corpo HTTP."""


@dataclass(repr=False)
class PauseWriter:
    token: str = field(repr=False)
    version: str
    client: httpx.Client | None = field(default=None, repr=False)
    _paused: set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self):
        if not self.token or not re.fullmatch(r"v\d+\.\d+", self.version):
            raise ValueError("token e versão Graph definidos pelo operador são obrigatórios")

    @classmethod
    def from_environment(cls):
        if not safety.live_mode():
            raise ValueError("escritor real indisponível em LIVE_MODE=false")
        return cls(os.environ.get("META_ACCESS_TOKEN", ""), os.environ.get("META_API_VERSION", ""))

    def pause(
        self, meta_id: str, *, fields: dict | None = None, already_paused: bool = False
    ) -> dict:
        fields = {"status": "PAUSED"} if fields is None else fields
        if fields != {"status": "PAUSED"} or not re.fullmatch(r"\d+", meta_id):
            raise ValueError(
                "única escrita permitida: id numérico e status=PAUSED sem outros campos"
            )
        if already_paused or meta_id in self._paused:
            return {"status": "already_paused"}
        if not safety.live_mode():
            return {"status": "disabled"}
        safety.require_external_write("pause")
        client = self.client or httpx.Client(timeout=10, follow_redirects=False)
        try:
            response = client.post(
                f"https://graph.facebook.com/{self.version}/{meta_id}",
                data=fields,
                headers={"Authorization": "Bearer " + self.token},
                follow_redirects=False,
                timeout=10,
            )
            try:
                body = response.json()
            except ValueError:
                raise MetaPauseError("Meta: resposta de pausa inválida") from None
            if not isinstance(body, dict):
                raise MetaPauseError("Meta: resposta de pausa inválida")
            error = body.get("error")
            if isinstance(error, dict) and error.get("code") == 190:
                raise MetaPauseError("Meta: token inválido/expirado (190)")
            if response.status_code != 200 or error or body.get("success") is not True:
                raise MetaPauseError(f"Meta recusou pausa (HTTP {response.status_code})")
        except httpx.HTTPError:
            raise MetaPauseError(
                "Meta: transporte indisponível; confirmar estado antes de repetir"
            ) from None
        finally:
            if self.client is None:
                client.close()
        self._paused.add(meta_id)
        return {"status": "paused"}
