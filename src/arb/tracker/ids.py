"""Fallback V-02: identificador determinístico, persistido e sem colisão silenciosa."""

import hashlib
import re

from arb.db import Repository
from arb.models import Entity

ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def validate(length, alphabet):
    if type(length) is not int or not 1 <= length <= 128:
        raise ValueError("tamanho de rastreio deve ser 1–128")
    if (
        not isinstance(alphabet, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{2,64}", alphabet)
        or len(set(alphabet)) != len(alphabet)
    ):
        raise ValueError("alfabeto de rastreio inválido ou repetido")


def candidate(entity_id, length, alphabet):
    number = int.from_bytes(hashlib.sha256(entity_id.encode()).digest(), "big")
    result = ""
    for _ in range(length):
        number, digit = divmod(number, len(alphabet))
        result = alphabet[digit] + result
    return result


def tracking_id(connection, entity_id, *, max_length=None, alphabet=ALPHABET):
    entity = Repository(connection, Entity).get(entity_id)
    if entity is None:
        raise ValueError("entidade de rastreio desconhecida")
    full = entity.meta_id or entity.id
    if max_length is None:
        return full
    validate(max_length, alphabet)
    token = full if len(full) <= max_length else candidate(entity.id, max_length, alphabet)
    # Inclusive collision with a full id: neither interpretation may become ambiguous.
    for other in Repository(connection, Entity).list():
        if other.id != entity.id and token in {other.id, other.meta_id}:
            raise ValueError("colisão de id de rastreio; escolher outro tamanho/alfabeto")
    row = connection.execute(
        "SELECT entity_id FROM tracking_ids WHERE token=?", (token,)
    ).fetchone()
    if row and row[0] != entity.id:
        raise ValueError("colisão de id de rastreio; escolher outro tamanho/alfabeto")
    connection.execute("INSERT OR IGNORE INTO tracking_ids VALUES(?,?)", (token, entity.id))
    return token
