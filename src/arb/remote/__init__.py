"""Porta abstrata sobre entidades do motor; não é contrato de payload Graph."""

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from arb.models import Entity


@runtime_checkable
class RemoteWriter(Protocol):
    create: Callable[[Entity, str], dict]
    activate: Callable[[str, str], dict]
    set_budget: Callable[[str, int, str], dict]
    pause: Callable[[str, str], dict]
    read: Callable[[str], Entity | None]
    locate: Callable[[str], Entity | None]
