"""Diagnóstico local de leitura. Não instala nem controla unidades."""

import os
import shutil
import subprocess
from pathlib import Path

from arb.service import NAMES

PROPERTIES = "ActiveState,UnitFileState,NextElapseUSecRealtime"


def read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def is_wsl(*, proc=Path("/proc")) -> bool:
    return bool(os.environ.get("WSL_DISTRO_NAME")) or "microsoft" in read(proc / "version").lower()


def inspect(*, proc=Path("/proc"), timezone=Path("/etc/timezone")) -> dict:
    wsl = is_wsl(proc=proc)
    systemd = read(proc / "1/comm") == "systemd"
    zone = read(timezone)
    if not zone:
        try:
            zone = str(Path("/etc/localtime").readlink()).split("zoneinfo/")[-1]
        except OSError:
            zone = "desconhecido"
    warnings = []
    if wsl:
        if not systemd:
            warnings.append("WSL sem systemd")
        warnings.append("WSL pode suspender; não usar para dinheiro real sem host sempre ligado")
    command = shutil.which("systemctl")
    units = []
    for name in NAMES:
        row = {
            "name": name,
            "available": False,
            "installed": False,
            "active": False,
            "active_state": "desconhecido",
            "unit_file_state": "desconhecido",
            "next": "",
        }
        if command:
            try:
                result = subprocess.run(
                    [command, "show", name, "-p", PROPERTIES],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                    shell=False,
                )
                if result.returncode != 0:
                    raise ValueError("estado indisponível")
                values = dict(
                    line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
                )
                active = values["ActiveState"]
                state = values["UnitFileState"]
                next_time = values["NextElapseUSecRealtime"]
                if active not in {
                    "active",
                    "inactive",
                    "failed",
                    "activating",
                    "deactivating",
                    "reloading",
                    "maintenance",
                    "refreshing",
                }:
                    raise ValueError("estado inválido")
                if state not in {
                    "",
                    "enabled",
                    "disabled",
                    "static",
                    "masked",
                    "generated",
                    "indirect",
                    "linked",
                    "linked-runtime",
                    "enabled-runtime",
                    "masked-runtime",
                    "alias",
                    "transient",
                    "bad",
                }:
                    raise ValueError("estado inválido")
                if len(next_time) > 160 or (next_time and not next_time.isprintable()):
                    raise ValueError("timer inválido")
                row.update(
                    available=True,
                    installed=bool(state),
                    active=active == "active",
                    active_state=active,
                    unit_file_state=state,
                    next=next_time,
                )
            except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
                pass
        units.append(row)
    return {
        "wsl": wsl,
        "systemd_pid1": systemd,
        "timezone": zone,
        "systemctl_available": bool(command),
        "units": units,
        "warnings": warnings,
        "scope": "diagnóstico de leitura; persistência exige confirmação humana assinada",
    }
