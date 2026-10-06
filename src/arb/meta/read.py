"""Graph API somente GET. Sem suporte a escrita, delete ou ativação."""

import json
import re
import time
from collections.abc import Callable
from datetime import date

import httpx


class MetaReadError(RuntimeError):
    """Erro sanitizado: nunca inclui token, headers ou corpo da resposta."""


class Reader:
    def __init__(
        self,
        token: str,
        account_id: str,
        version: str,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        attempts: int = 5,
    ):
        if not token or not re.fullmatch(r"(?:act_)?\d+", account_id):
            raise ValueError("META_ACCESS_TOKEN e META_AD_ACCOUNT_ID são obrigatórios")
        if not re.fullmatch(r"v\d+\.\d+", version):
            raise ValueError("Defina META_API_VERSION após validar V-06")
        if attempts < 1:
            raise ValueError("attempts precisa ser positivo")
        self.account_id = account_id if account_id.startswith("act_") else "act_" + account_id
        self.base = "https://graph.facebook.com/" + version
        self._token = token
        self.client = client or httpx.Client(timeout=30)
        self.owned = client is None
        self.sleep = sleep
        self.attempts = attempts
        self.throttle = 0.0

    def close(self):
        if self.owned:
            self.client.close()

    def get(self, path: str, params: dict) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9_/]+", path):
            raise ValueError("Caminho Graph inválido")
        for attempt in range(self.attempts):
            if self.throttle:
                self.sleep(self.throttle)
            try:
                response = self.client.get(
                    self.base + "/" + path,
                    params=params,
                    headers={"Authorization": "Bearer " + self._token},
                )
            except httpx.TransportError:
                if attempt + 1 == self.attempts:
                    raise MetaReadError("Meta indisponível: falha de transporte") from None
                self.sleep(min(2**attempt, 30))
                continue
            try:
                body = response.json()
            except ValueError:
                body = {}
            if not isinstance(body, dict):
                raise MetaReadError("Meta retornou payload inválido")
            error = body.get("error", {})
            code = error.get("code") if isinstance(error, dict) else None
            if code == 190:
                raise MetaReadError("Meta: token expirado ou inválido (190)")
            transient = (
                response.status_code == 429
                or response.status_code >= 500
                or code in (4, 17, 32, 613)
            )
            if transient:
                if attempt + 1 == self.attempts:
                    raise MetaReadError("Meta: retries esgotados por rate limit/indisponibilidade")
                try:
                    retry_after = float(response.headers.get("Retry-After", 0))
                except ValueError:
                    retry_after = 0
                self.sleep(min(max(2**attempt, retry_after), 30))
                continue
            if response.is_error or error:
                raise MetaReadError(f"Meta recusou leitura (HTTP {response.status_code})")
            for header in ("X-App-Usage", "X-Ad-Account-Usage"):
                try:
                    usage = json.loads(response.headers.get(header, "{}"))
                    if any(float(v) >= 90 for v in usage.values() if isinstance(v, (int, float))):
                        self.throttle = 5
                except (ValueError, AttributeError):
                    pass
            return body
        raise MetaReadError("Leitura não concluída")

    def pages(self, path: str, params: dict) -> list[dict]:
        result = []
        after = None
        seen = set()
        for _ in range(10000):
            body = self.get(path, params | ({"after": after} if after else {}))
            if not isinstance(body.get("data"), list):
                raise MetaReadError("Meta: página sem data válido")
            result.extend(body["data"])
            paging = body.get("paging", {})
            if not paging.get("next"):
                return result
            # Não seguir URLs externas ou next contendo tokens. Reusar endpoint e cursor.
            after = paging.get("cursors", {}).get("after")
            if not isinstance(after, str) or not after or after in seen:
                raise MetaReadError("Meta: cursor repetido/ausente")
            seen.add(after)
        raise MetaReadError("Meta: limite de paginação excedido")

    def account(self) -> dict:
        result = self.get(self.account_id, {"fields": "id,currency,timezone_name"})
        if result.get("currency") != "BRL" or result.get("timezone_name") != "America/Sao_Paulo":
            raise MetaReadError("Conta exige moeda BRL e fuso America/Sao_Paulo")
        return result

    def insights(self, since: date, until: date) -> list[dict]:
        if since > until:
            raise ValueError("Intervalo de datas invertido")
        fields = (
            "ad_id,ad_name,adset_id,campaign_id,impressions,inline_link_clicks,"
            "spend,actions,date_start,date_stop"
        )
        return self.pages(
            self.account_id + "/insights",
            {
                "fields": fields,
                "level": "ad",
                "time_increment": "1",
                "limit": "100",
                "time_range": json.dumps({"since": since.isoformat(), "until": until.isoformat()}),
            },
        )

    def ads(self) -> list[dict]:
        return self.pages(
            self.account_id + "/ads",
            {
                "limit": "100",
                "fields": (
                    "id,name,status,adset{id,name,status,daily_budget,campaign{id,name,status}}"
                ),
            },
        )
