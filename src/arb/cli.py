from typing import Annotated

import typer

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)


@app.command()
def doctor(root: str = "."):
    """Valida config, contratos, banco e simulação; lista nomes de variáveis faltantes."""
    from pathlib import Path

    from arb.doctor import diagnose

    errors, warnings = diagnose(Path(root).resolve())
    for warning in warnings:
        typer.echo(f"AVISO: {warning}")
    for error in errors:
        typer.echo(f"ERRO: {error}", err=True)
    if errors:
        raise typer.Exit(1)
    typer.echo(
        "Doctor OK — fundação local, LIVE_MODE=false; integrações reais têm aceite separado."
    )


contracts_app = typer.Typer(help="Contratos JSON Schema")
app.add_typer(contracts_app, name="contracts")


@contracts_app.command("export")
def contracts_export(output: str = "contracts"):
    from pathlib import Path

    from arb.models import export_contracts

    paths = export_contracts(Path(output))
    typer.echo(f"{len(paths)} contratos exportados em {output}")


db_app = typer.Typer(help="SQLite local")
app.add_typer(db_app, name="db")


@db_app.command("migrate")
def db_migrate(database: str = "data/engine.db"):
    from pathlib import Path

    from arb.db import connect, migrate

    connection = connect(Path(database))
    try:
        migrate(connection)
    finally:
        connection.close()
    typer.echo("Migrações OK")


@db_app.command("backup")
def db_backup(database: str = "data/engine.db", output: str = "data/backups"):
    from pathlib import Path

    from arb.db import backup_daily, connect, migrate

    connection = connect(Path(database))
    try:
        migrate(connection)
        target = backup_daily(connection, Path(output))
    finally:
        connection.close()
    typer.echo(f"Backup OK: {target}")


sim_app = typer.Typer(help="Laboratório sintético, sem APIs")
app.add_typer(sim_app, name="sim")


@sim_app.command("run")
def sim_run(
    seed: int = 42, budget: int = 2400, database: str | None = None, profile: str = "planted"
):
    """Budget em BRL inteiros. Persistência opcional em banco separado e novo."""
    import json
    from pathlib import Path

    from arb.launcher.execute import require_simulation
    from arb.sim.lab import persist, run_lab

    try:
        require_simulation()
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    try:
        run = run_lab(seed, budget * 100, profile=profile)
        if database:
            persist(run, Path(database))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(run.summary(), ensure_ascii=False, indent=2))


@app.command("report")
def report(database: str = "data/engine.db", output: str = "reports"):
    from pathlib import Path

    from arb.analyst.report import generate_report
    from arb.db import connect, migrate

    connection = connect(Path(database))
    try:
        migrate(connection)
        target = generate_report(connection, Path(output))
    finally:
        connection.close()
    typer.echo(f"Relatório gerado: {target}")


library_app = typer.Typer(help="Biblioteca de ângulos encerrados")
app.add_typer(library_app, name="library")


@library_app.command("archive")
def library_archive(database: str = "data/engine.db"):
    from pathlib import Path

    from arb.analyst.library import archive
    from arb.db import connect, migrate

    connection = connect(Path(database))
    try:
        migrate(connection)
        typer.echo(f"{archive(connection)} aprendizados arquivados")
    finally:
        connection.close()


@library_app.command("query")
def library_query(niche: str, database: str = "data/engine.db"):
    import json
    from pathlib import Path

    from arb.analyst.library import query
    from arb.db import connect, migrate

    connection = connect(Path(database))
    try:
        migrate(connection)
        typer.echo(
            json.dumps(
                [r.model_dump(mode="json") for r in query(connection, niche)],
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        connection.close()


scout_app = typer.Typer(help="CSV manual de ofertas e anúncios")
app.add_typer(scout_app, name="scout")


@scout_app.command("import")
def scout_import(
    offers: str = typer.Option(...),
    adlibrary: str = typer.Option(...),
    database: str = "data/engine.db",
):
    from pathlib import Path

    from arb.db import Repository, connect, migrate
    from arb.models import Offer
    from arb.scout import import_adlibrary, import_offers

    try:
        intake = import_offers(Path(offers))
        observations = import_adlibrary(Path(adlibrary))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    connection = connect(Path(database))
    try:
        migrate(connection)
        with connection:
            for item in intake:
                Repository(connection, Offer).add(item.offer)
    finally:
        connection.close()
    typer.echo(f"{len(intake)} ofertas importadas; {len(observations)} observações validadas")


@scout_app.command("rank")
def scout_rank(
    offers: str = typer.Option(...),
    adlibrary: str = typer.Option(...),
    database: str = "data/engine.db",
    output: str = "ops/approvals/pending",
):
    import json
    from pathlib import Path

    from arb.db import connect, migrate
    from arb.scout import import_adlibrary, import_offers
    from arb.scout.ranking import producer_report, propose, rank

    try:
        intake = import_offers(Path(offers))
        ranked, rejected = rank(intake, import_adlibrary(Path(adlibrary)))
        producer = producer_report(intake)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    connection = connect(Path(database))
    try:
        migrate(connection)
        path = propose(connection, ranked, Path(output))
    finally:
        connection.close()
    typer.echo(
        json.dumps(
            {
                "ranking": [{"id": o.id, "score": o.score} for o in ranked],
                "rejected": rejected,
                "approval": str(path),
                **({"producer": producer} if producer else {}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


bridge_app = typer.Typer(help="Gerar página-ponte estática")
app.add_typer(bridge_app, name="bridge")


@bridge_app.command("build")
def bridge_build(
    offer_id: str,
    content_file: str,
    worker_url: str = typer.Option(...),
    pixel_id: str = typer.Option(...),
    tracking_key: str = typer.Option(...),
    slug: str = typer.Option(...),
    database: str = "data/engine.db",
    output: str = "bridges_out",
    capi_enabled: bool = False,
):
    from pathlib import Path

    import yaml

    from arb.bridge import build
    from arb.config import Settings
    from arb.db import Repository, connect, migrate
    from arb.models import Offer

    connection = connect(Path(database))
    try:
        migrate(connection)
        offer = Repository(connection, Offer).get(offer_id)
        if offer is None:
            raise typer.BadParameter("Oferta desconhecida")
        settings = Settings.model_validate(yaml.safe_load(Path("config/settings.yaml").read_text()))
        target = build(
            offer,
            Path(content_file).read_text(),
            slug,
            worker_url=worker_url,
            pixel_id=pixel_id,
            tracking_key=tracking_key,
            output=Path(output),
            connection=connection,
            capi_enabled=capi_enabled,
            tracking_id_max_length=settings.tracking_id_max_length,
            tracking_id_alphabet=settings.tracking_id_alphabet,
        )
    finally:
        connection.close()
    typer.echo(f"Ponte gerada: {target}")


sales_app = typer.Typer(help="Vendas normalizadas de CSV")
app.add_typer(sales_app, name="sales")
sync_app = typer.Typer(help="Sincronização somente leitura de fontes externas")
app.add_typer(sync_app, name="sync")


@sales_app.command("import")
def sales_import(
    csv_file: str, database: str = "data/engine.db", mapping: str = "config/sales_csv.yaml"
):
    from pathlib import Path

    from arb.config import load_sales_csv
    from arb.db import connect, migrate
    from arb.tracker import import_sales

    connection = connect(Path(database))
    try:
        migrate(connection)
        count = import_sales(connection, Path(csv_file), mapping=load_sales_csv(Path(mapping)))
    finally:
        connection.close()
    typer.echo(f"{count} vendas novas/atualizadas")


@sync_app.command("events")
def sync_events(worker_url: str = typer.Option(...), database: str = "data/engine.db"):
    import os
    from pathlib import Path

    from arb.db import connect, migrate
    from arb.tracker.sync import sync

    connection = connect(Path(database))
    try:
        migrate(connection)
        result = sync(connection, worker_url, os.environ.get("TRACKER_SYNC_TOKEN", ""))
    finally:
        connection.close()
    typer.echo(f"Sincronização: {result}")


@sync_app.command("meta")
def sync_meta(
    since: str = typer.Option(...),
    until: str = typer.Option(...),
    database: str = "data/engine.db",
    mapping_file: str | None = None,
):
    import json
    import os
    from datetime import date
    from pathlib import Path

    import yaml

    from arb.db import connect, migrate
    from arb.launcher.execute import require_simulation
    from arb.meta.read import MetaReadError, Reader
    from arb.meta.sync import sync

    try:
        require_simulation()
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    version = os.environ.get("META_API_VERSION") or yaml.safe_load(
        Path("config/settings.yaml").read_text()
    ).get("meta_api_version")
    try:
        reader = Reader(
            os.environ.get("META_ACCESS_TOKEN", ""),
            os.environ.get("META_AD_ACCOUNT_ID", ""),
            version or "",
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    connection = connect(Path(database))
    try:
        migrate(connection)
        mapping = json.loads(Path(mapping_file).read_text()) if mapping_file else {}
        result = sync(
            connection,
            reader,
            date.fromisoformat(since),
            date.fromisoformat(until),
            mapping=mapping,
        )
    except (MetaReadError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        reader.close()
        connection.close()
    typer.echo(f"Meta somente leitura: {result}")


creative_app = typer.Typer(help="Candidatos locais; nenhum envio ou aprovação automática")
app.add_typer(creative_app, name="creative")


@creative_app.command("angles")
def creative_angles(offer_id: str, database: str = "data/engine.db"):
    from pathlib import Path

    from arb.analyst.library import query
    from arb.creative import generate_angles
    from arb.db import Repository, connect, migrate
    from arb.models import Angle, Offer

    connection = connect(Path(database))
    try:
        migrate(connection)
        offer = Repository(connection, Offer).get(offer_id)
        if offer is None:
            raise typer.BadParameter("Oferta desconhecida")
        angles = generate_angles(offer, query(connection, offer.niche))
        with connection:
            for angle in angles:
                if Repository(connection, Angle).get(angle.id) is None:
                    Repository(connection, Angle).add(angle)
        for angle in angles:
            typer.echo(angle.model_dump_json())
    finally:
        connection.close()


@creative_app.command("copies")
def creative_copies(angle_id: str, region: str = "neutral", database: str = "data/engine.db"):
    from pathlib import Path

    from arb.creative.copy import generate_copies
    from arb.db import Repository, connect, migrate
    from arb.models import Angle, Creative, Offer

    connection = connect(Path(database))
    try:
        migrate(connection)
        angle = Repository(connection, Angle).get(angle_id)
        if angle is None:
            raise typer.BadParameter("Ângulo desconhecido")
        offer = Repository(connection, Offer).get(angle.offer_id)
        copies = generate_copies(offer, angle, region=region)
        with connection:
            for creative in copies:
                if Repository(connection, Creative).get(creative.id) is None:
                    Repository(connection, Creative).add(creative)
        for creative in copies:
            typer.echo(creative.model_dump_json())
    finally:
        connection.close()


@creative_app.command("render")
def creative_render(
    creative_id: str, database: str = "data/engine.db", output: str = "data/creatives"
):
    import json
    from pathlib import Path

    from arb.creative.render import render_creative
    from arb.db import Repository, connect, migrate
    from arb.models import Creative

    connection = connect(Path(database))
    try:
        migrate(connection)
        creative = Repository(connection, Creative).get(creative_id)
        if creative is None:
            raise typer.BadParameter("Criativo desconhecido")
        result = render_creative(creative, Path(output))
        creative.asset_path = result["video"] or result["images"][0]
        with connection:
            Repository(connection, Creative).update(creative)
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        connection.close()


scheduler_app = typer.Typer(help="Ciclos locais e simulação acelerada")
app.add_typer(scheduler_app, name="scheduler")


@scheduler_app.command("simulate")
def scheduler_simulate(
    database: str = typer.Option(...),
    output: str = "reports/scheduler-sim",
    start: str = "2026-10-05",
    seed: int = 42,
):
    import json
    from datetime import date
    from pathlib import Path

    from arb.scheduler.simulation import simulate

    try:
        result = simulate(
            Path(database), start=date.fromisoformat(start), seed=seed, output=Path(output)
        )
    except (ValueError, FileExistsError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@scheduler_app.command("once")
def scheduler_once(database: str = typer.Option(...), output: str = "reports", root: str = "."):
    """Retoma ciclos incompletos e executa o último slot vencido, sem APIs."""
    import json
    from pathlib import Path

    from arb.db import connect, migrate
    from arb.scheduler import once

    connection = connect(Path(database))
    try:
        migrate(connection)
        result = once(connection, root=Path(root), output=Path(output))
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        connection.close()


@scheduler_app.command("status")
def scheduler_status(
    database: str = "data/engine.db",
    limit: int = 30,
    json_output: bool = typer.Option(False, "--json"),
):
    import json
    from pathlib import Path

    from arb.db import connect, migrate
    from arb.scheduler import status

    connection = connect(Path(database))
    try:
        migrate(connection)
        rows = status(connection, limit=limit)
        typer.echo(
            json.dumps(rows, ensure_ascii=False, sort_keys=True)
            if json_output
            else "\n".join(row["id"] + " " + row["status"] for row in rows)
        )
    finally:
        connection.close()


@app.command("panic")
def panic_command(database: str = "data/engine.db"):
    """Freio de pausa; simulação padrão mantém pausas remotas pendentes."""
    import json
    from pathlib import Path

    from arb.db import connect, migrate
    from arb.launcher.panic import panic

    if not Path(database).is_file():
        raise typer.BadParameter("Banco não encontrado")
    connection = connect(Path(database))
    try:
        migrate(connection)
        result = panic(connection)
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        if result["remote_pause_pending"] or result["errors"]:
            raise typer.Exit(1)
    finally:
        connection.close()


@db_app.command("restore")
def db_restore(backup: str, database: str = typer.Option(...)):
    """Restaura backup validado em caminho novo; recusa sobrescrita."""
    from pathlib import Path

    from arb.db.restore import restore_new

    try:
        target = restore_new(Path(backup), Path(database))
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Restauração OK em banco novo: {target}")


@sim_app.command("calibrate")
def sim_calibrate(
    seeds: int = 100,
    workers: int = 4,
    output: str = "docs/validation/calibration-grid.json",
    report: str = "reports/calibration.html",
    profile_file: str | None = None,
):
    import json
    from pathlib import Path

    from arb.sim.calibrate import calibrate, html_report

    if seeds < 1:
        raise typer.BadParameter("seeds precisa ser positivo")
    result = calibrate(
        seeds=list(range(seeds)),
        workers=workers,
        profile_file=Path(profile_file) if profile_file else None,
    )
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    html_report(result, Path(report))
    typer.echo(f"{len(result['rows'])} células; JSON: {target}; HTML: {report}")


approve_app = typer.Typer(help="Aprovação interativa somente na máquina do humano")
app.add_typer(approve_app, name="approve")


@approve_app.command("sign")
def approve_sign(file: str):
    from pathlib import Path

    from arb.launcher.approval import sign_file

    try:
        destination = sign_file(Path(file), typer.confirm)
    except (ValueError, OSError):
        raise typer.BadParameter(
            "aprovação recusada: tty, proposta, confirmação ou chave"
        ) from None
    typer.echo(f"Aprovação humana assinada: {destination}")


@approve_app.command("keygen")
def approve_keygen(output: str = typer.Option(..., help="Arquivo da chave privada, fora do repo")):
    """Gera a chave Ed25519 humana (0600) e mostra a chave pública para versionar."""
    from pathlib import Path

    from arb.launcher.approval import is_interactive, keygen

    if not is_interactive():
        raise typer.BadParameter("keygen exige tty interativo na máquina humana")
    try:
        public = keygen(Path(output), Path.cwd())
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(f"chave não gerada: {exc}") from None
    typer.echo(f"Chave privada gravada (0600): {Path(output).expanduser()}")
    typer.echo("Exporte APPROVAL_PRIVATE_KEY_FILE com esse caminho, só nesta máquina.")
    typer.echo("Cole em config/settings.yaml via PR revisado por você:")
    typer.echo(f"approval_public_key: {public}")


@approve_app.command("verify")
def approve_verify(file: str):
    from pathlib import Path

    from arb.launcher.approval import read_document, verify

    try:
        approval, _ = read_document(Path(file))
        verify(approval)
        if approval.status != "approved" or approval.decided_at is None:
            raise ValueError("decisão ausente")
    except (ValueError, OSError):
        raise typer.BadParameter(
            "aprovação ou assinatura inválida; confira a chave humana"
        ) from None
    typer.echo("Assinatura humana válida")


@app.command("preflight")
def preflight_command(
    json_output: bool = typer.Option(False, "--json"),
    read_meta: bool = typer.Option(False, "--read-meta", help="GET real somente no host humano"),
    database: str = "data/engine.db",
    root: str = ".",
):
    """Inspeção antes do aceite F5/F6; não habilita escrita ou live."""
    import json
    from pathlib import Path

    from arb.preflight import inspect

    result = inspect(root=Path(root), database=Path(database), allow_meta_read=read_meta)
    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for check in result["checks"]:
            typer.echo(f"{check['status'].upper()} {check['name']}: {check['message']}")
            if check["fix"]:
                typer.echo("  Correção: " + check["fix"])
    if not result["ok"]:
        raise typer.Exit(1)


ops_app = typer.Typer(help="Intenções e reconciliação operacional")
app.add_typer(ops_app, name="ops")


@ops_app.command("alerts")
def ops_alerts(database: str = "data/engine.db", json_output: bool = typer.Option(False, "--json")):
    import json
    from pathlib import Path

    from arb.db import connect, migrate
    from arb.scheduler.alerts import uncertain

    connection = connect(Path(database))
    try:
        migrate(connection)
        rows = uncertain(connection)
        typer.echo(
            json.dumps(rows, sort_keys=True)
            if json_output
            else "\n".join(row["id"] + " " + ",".join(row["codes"]) for row in rows)
        )
    finally:
        connection.close()


@ops_app.command("ack")
def ops_ack(alert_id: str, database: str = "data/engine.db"):
    from pathlib import Path

    from arb.db import connect, migrate
    from arb.scheduler.alerts import acknowledge

    connection = connect(Path(database))
    try:
        migrate(connection)
        action = acknowledge(connection, alert_id)
        typer.echo("Alerta reconhecido: " + action.id)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from None
    finally:
        connection.close()


@ops_app.command("pending")
def ops_pending(
    database: str = "data/engine.db", json_output: bool = typer.Option(False, "--json")
):
    import json
    from pathlib import Path

    from arb.db import connect, migrate
    from arb.ledger import pending

    connection = connect(Path(database))
    try:
        migrate(connection)
        rows = pending(connection)
        typer.echo(json.dumps(rows, sort_keys=True) if json_output else f"Pendências: {len(rows)}")
    finally:
        connection.close()


@ops_app.command("reconcile")
def ops_reconcile(
    database: str = "data/engine.db",
    read_meta: bool = False,
    json_output: bool = typer.Option(False, "--json"),
):
    import json
    import os
    from pathlib import Path

    from arb.db import connect, migrate
    from arb.meta.read import Reader
    from arb.reconcile import reconcile

    if not read_meta:
        raise typer.BadParameter("leitura remota exige --read-meta no host humano autorizado")
    reader = Reader(
        os.environ.get("META_ACCESS_TOKEN", ""),
        os.environ.get("META_AD_ACCOUNT_ID", ""),
        os.environ.get("META_API_VERSION", ""),
    )
    connection = connect(Path(database))
    try:
        migrate(connection)
        result = reconcile(connection, reader)
        typer.echo(json.dumps(result, sort_keys=True) if json_output else str(result))
        if result["alerts"]:
            raise typer.Exit(1)
    finally:
        connection.close()
        reader.close()


@db_app.command("release")
def db_release(database: str = "data/engine.db", read_meta: bool = False):
    import os
    from pathlib import Path

    from arb.db import connect, migrate
    from arb.meta.read import Reader
    from arb.quarantine import release

    connection = connect(Path(database))
    reader = None
    try:
        migrate(connection)
        if read_meta:
            reader = Reader(
                os.environ.get("META_ACCESS_TOKEN", ""),
                os.environ.get("META_AD_ACCOUNT_ID", ""),
                os.environ.get("META_API_VERSION", ""),
            )
        action = release(connection, reader=reader)
        typer.echo("Banco liberado" if action else "Banco sem quarentena")
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        connection.close()
        if reader:
            reader.close()


@db_app.command("drill")
def db_drill(backups: str = "data/backups", json_output: bool = typer.Option(False, "--json")):
    import json
    from pathlib import Path

    from arb.db.checkpoint import drill

    result = drill(Path(backups))
    typer.echo(json.dumps(result, sort_keys=True) if json_output else f"Drill: {result['status']}")
    if result["status"] != "passed":
        raise typer.Exit(1)


@scout_app.command("apply")
def scout_apply(
    approval_id: str, database: str = "data/engine.db", approvals: str = "ops/approvals/approved"
):
    from pathlib import Path

    from arb.db import connect, migrate
    from arb.scout.approve import apply

    connection = connect(Path(database))
    try:
        migrate(connection)
        action = apply(connection, approval_id, directory=Path(approvals))
        typer.echo(action.model_dump_json())
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        connection.close()


@creative_app.command("propose")
def creative_propose(
    offer_id: str, database: str = "data/engine.db", output: str = "ops/approvals/pending"
):
    from pathlib import Path

    from arb.creative.approve import propose
    from arb.db import connect, migrate

    connection = connect(Path(database))
    try:
        migrate(connection)
        typer.echo(str(propose(connection, offer_id, directory=Path(output))))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        connection.close()


@creative_app.command("apply")
def creative_apply(
    approval_id: str, database: str = "data/engine.db", approvals: str = "ops/approvals/approved"
):
    from pathlib import Path

    from arb.creative.approve import apply
    from arb.db import connect, migrate

    connection = connect(Path(database))
    try:
        migrate(connection)
        typer.echo(apply(connection, approval_id, directory=Path(approvals)).model_dump_json())
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        connection.close()


scale_app = typer.Typer(help="Escala assinada em simulação")
app.add_typer(scale_app, name="scale")


@scale_app.command("propose")
def scale_propose(
    entity_id: str,
    budget: int,
    database: str = "data/engine.db",
    output: str = "ops/approvals/pending",
):
    from pathlib import Path

    from arb.db import connect, migrate
    from arb.launcher.scale import propose

    connection = connect(Path(database))
    try:
        migrate(connection)
        typer.echo(str(propose(connection, entity_id, budget, directory=Path(output))))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        connection.close()


@scale_app.command("apply")
def scale_apply(
    approval_id: str, database: str = "data/engine.db", approvals: str = "ops/approvals/approved"
):
    from pathlib import Path

    from arb.db import connect, migrate
    from arb.launcher.scale import apply

    connection = connect(Path(database))
    try:
        migrate(connection)
        typer.echo(apply(connection, approval_id, directory=Path(approvals)).model_dump_json())
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        connection.close()


drill_app = typer.Typer(help="Ensaio descartável com dados e chave sintéticos; sem rede real")
app.add_typer(drill_app, name="drill")


@drill_app.command("run")
def drill_run(seed: int = 42, json_output: bool = typer.Option(False, "--json")):
    import json

    from arb.drill import run

    try:
        result = run(seed)
        typer.echo(
            json.dumps(result, sort_keys=True, indent=2)
            if json_output
            else f"Drill seed {seed}: invariantes verdes; apenas simulação e FakeMeta"
        )
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc


service_app = typer.Typer(help="Renderizar/verificar pacote; nunca instalar")
app.add_typer(service_app, name="service")


@service_app.command("render")
def service_render(
    root: str = typer.Option(...), user: str = typer.Option(...), output: str = "data/service"
):
    import json
    from pathlib import Path

    from arb.service import render

    try:
        result = render(Path(root), user, output=Path(output))
        typer.echo(json.dumps(result, sort_keys=True))
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from None


@service_app.command("check")
def service_check(output: str = "data/service", json_output: bool = typer.Option(False, "--json")):
    import json
    from pathlib import Path

    from arb.service import check

    result = check(output=Path(output))
    typer.echo(
        json.dumps(result, sort_keys=True)
        if json_output
        else "Serviço verificado"
        if result["ok"]
        else "\n".join(result["errors"])
    )
    if not result["ok"]:
        raise typer.Exit(1)


accept_app = typer.Typer(help="Kits executados pelo humano no próprio host; cloud só mocks")
app.add_typer(accept_app, name="accept")


@accept_app.command("f5")
def accept_f5(out: str = typer.Option(...), root: str = "."):
    import os
    from pathlib import Path

    from arb.accept import f5, require_host, save
    from arb.preflight import make_reader

    reader = None
    try:
        require_host()
        reader = make_reader(os.environ.get("META_API_VERSION", ""))
        result = f5(reader, root=Path(root))
        save(result, Path(out))
        typer.echo("Aceite F5: " + result["status"])
        if result["status"] != "passed":
            raise typer.Exit(1)
    except (ValueError, OSError):
        typer.echo("Kit F5 recusado; verificar modo, configuração e destino no host humano")
        raise typer.Exit(1) from None
    finally:
        if reader is not None:
            reader.close()


@accept_app.command("register-test")
def accept_register_test(meta_id: str = typer.Option(...), database: str = "data/engine.db"):
    from pathlib import Path

    from arb.accept_pause import register_test
    from arb.db import connect, migrate

    connection = connect(Path(database))
    try:
        migrate(connection)
        register_test(connection, meta_id)
        typer.echo("Entidade registrada como teste pelo humano")
    except (ValueError, OSError):
        typer.echo("Cadastro recusado; verificar entidade local, tty, quarentena e pendências")
        raise typer.Exit(1) from None
    finally:
        connection.close()


@accept_app.command("pause")
def accept_pause(
    meta_id: str = typer.Option(...), out: str = typer.Option(...), database: str = "data/engine.db"
):
    import os
    from pathlib import Path

    from arb.accept import require_host, save
    from arb.accept_pause import is_interactive, pause
    from arb.db import connect, migrate
    from arb.meta.pause import PauseWriter
    from arb.preflight import make_reader

    connection = reader = None
    try:
        require_host()
        if not is_interactive():
            raise ValueError("tty obrigatório")
        connection = connect(Path(database))
        migrate(connection)
        reader = make_reader(os.environ.get("META_API_VERSION", ""))
        result = pause(connection, meta_id, reader, PauseWriter.from_environment())
        save(result, Path(out))
        typer.echo("Aceite pausa: " + result["status"])
        if result["status"] != "passed":
            typer.echo(result["next_step"])
            raise typer.Exit(1)
    except (ValueError, OSError):
        typer.echo(
            "Kit recusado; verificar entidade de teste e reconciliar pendências no host humano"
        )
        raise typer.Exit(1) from None
    finally:
        if reader is not None:
            reader.close()
        if connection is not None:
            connection.close()


@accept_app.command("tracking-propose")
def accept_tracking_propose(
    url: str = typer.Option(...),
    origin: str = typer.Option(...),
    entity_id: str = typer.Option(...),
    tracking_id: str = "",
    database: str = "data/engine.db",
    output: str = "ops/approvals/pending",
):
    from pathlib import Path

    from arb.accept_tracking import propose
    from arb.db import connect, migrate

    connection = connect(Path(database))
    try:
        migrate(connection)
        path = propose(
            connection,
            entity_id,
            url,
            origin,
            tracking_id=tracking_id or None,
            directory=Path(output),
        )
        typer.echo(f"Proposta: {path}; revisar e assinar no próprio host com arb approve sign")
    except (ValueError, OSError):
        typer.echo("Proposta recusada; verificar modo, entidade, rastreio e URL/origem")
        raise typer.Exit(1) from None
    finally:
        connection.close()


@accept_app.command("tracking")
def accept_tracking(
    url: str = typer.Option(...),
    out: str = typer.Option(...),
    approval_id: str = typer.Option(...),
    database: str = "data/engine.db",
    approvals: str = "ops/approvals/approved",
):
    import os
    from pathlib import Path

    from arb.accept import require_host, save
    from arb.accept_tracking import tracking
    from arb.db import connect, migrate

    connection = None
    try:
        require_host()
        connection = connect(Path(database))
        migrate(connection)
        result = tracking(
            connection,
            url,
            os.environ.get("TRACKER_SYNC_TOKEN", ""),
            approval_id,
            approval_dir=Path(approvals),
        )
        save(result, Path(out))
        typer.echo("Aceite rastreio: " + result["status"])
        if result["status"] != "passed":
            typer.echo("Consultar ledger/export no host; não reenviar automaticamente")
            raise typer.Exit(1)
    except (ValueError, OSError):
        typer.echo("Kit recusado; verificar modo, aprovação exata e configuração no host humano")
        raise typer.Exit(1) from None
    finally:
        if connection is not None:
            connection.close()


@app.command("readiness")
def readiness(root: str = ".", json_output: bool = typer.Option(False, "--json")):
    import json
    from pathlib import Path

    from arb.readiness import inspect

    result = inspect(root=Path(root))
    if json_output:
        typer.echo(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))
    else:
        typer.echo(result["status"])
        for item in result["items"]:
            typer.echo(f"{'✔' if item['ok'] else '✘'} {item['name']}: {item['reason']}")
            if not item["ok"]:
                typer.echo("  Próximo passo: " + item["next_step"])
    if not result["ready"]:
        raise typer.Exit(1)


evidence_app = typer.Typer(help="Assinar evidências somente na máquina humana")
app.add_typer(evidence_app, name="evidence")


@evidence_app.command("sign")
def evidence_sign(arquivo: str):
    from pathlib import Path

    from arb.accept import sign_evidence

    try:
        sign_evidence(Path(arquivo), typer.confirm)
    except (OSError, ValueError) as error:
        typer.echo(str(error))
        raise typer.Exit(1) from None
    typer.echo("Evidência assinada; não autoriza exposição")


@evidence_app.command("verify")
def evidence_verify(arquivo: str):
    from pathlib import Path

    from arb.accept import verify_evidence

    try:
        verify_evidence(Path(arquivo))
    except (OSError, ValueError) as error:
        typer.echo(str(error))
        raise typer.Exit(1) from None
    typer.echo("Assinatura válida; aceite e validade temporal são avaliados por readiness")


validate_app = typer.Typer(help="Registrar validações assinadas na máquina humana")
app.add_typer(validate_app, name="validate")


@validate_app.command("record")
def validate_record(item: str, evidence: str = typer.Option(...), root: str = "."):
    from pathlib import Path

    from arb.validation import record

    try:
        record(item, evidence, typer.confirm, root=Path(root))
    except (OSError, ValueError) as error:
        typer.echo(str(error))
        raise typer.Exit(1) from None
    typer.echo(f"{item}: registro assinado; não autoriza exposição")


@validate_app.command("show")
def validate_show(root: str = ".", json_output: bool = typer.Option(False, "--json")):
    import json
    from pathlib import Path

    from arb.validation import show

    try:
        result = show(root=Path(root))
    except (OSError, ValueError) as error:
        typer.echo(str(error))
        raise typer.Exit(1) from None
    if json_output:
        typer.echo(json.dumps(result, sort_keys=True, indent=2))
    else:
        for name, row in result.items():
            typer.echo(f"{'✔' if row['valid'] else '✘'} {name}: {row['status']}")


@service_app.command("status")
def service_status(json_output: bool = typer.Option(False, "--json")):
    import json

    from arb.hostinfo import inspect

    result = inspect()
    if json_output:
        typer.echo(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))
    else:
        typer.echo(
            f"WSL={result['wsl']}; systemd PID1={result['systemd_pid1']}; "
            f"timezone={result['timezone']}"
        )
        for warning in result["warnings"]:
            typer.echo("AVISO: " + warning)
        for row in result["units"]:
            typer.echo(
                f"{row['name']}: instalado={row['installed']}; "
                f"estado={row['active_state']}; próximo={row['next']}"
            )
        typer.echo(result["scope"])


@service_app.command("install-plan")
def service_install_plan(output: str = "data/service"):
    from pathlib import Path

    from arb.service import install_plan

    try:
        plan = install_plan(output=Path(output))
    except (OSError, ValueError) as error:
        typer.echo(str(error))
        raise typer.Exit(1) from None
    typer.echo(plan, nl=False)


@sim_app.command("confirm-report")
def sim_confirm_report(
    seeds: str = "0-99",
    output: str = "reports/confirmation.json",
    report: str = "reports/confirmation.md",
    workers: int = 4,
):
    """Compara hipóteses atuais e C sem alterar regras nem chamar APIs."""
    import json
    import re
    from pathlib import Path

    from arb.permissions import private_open, reject_links
    from arb.sim.calibrate import confirm_report, confirmation_markdown

    match = re.fullmatch(r"(\d+)-(\d+)", seeds)
    if not match or not 0 <= int(match[1]) <= int(match[2]) <= 9999:
        raise typer.BadParameter("seeds: intervalo inclusivo 0-99, limite 9999")
    paths = [Path(output), Path(report)]
    try:
        for path in paths:
            reject_links(path)
            if "config" in path.absolute().parts:
                raise ValueError("relatório não pode escrever em config")
        if paths[0].absolute() == paths[1].absolute():
            raise ValueError("JSON e Markdown exigem destinos diferentes")
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    result = confirm_report(seeds=list(range(int(match[1]), int(match[2]) + 1)), workers=workers)
    for path, body in [
        (Path(output), json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"),
        (Path(report), confirmation_markdown(result)),
    ]:
        with private_open(path) as file:
            file.write(body)
    typer.echo(f"{len(result['rows'])} comparações; hipóteses, não mercado; JSON: {output}")


observed_app = typer.Typer(help="Perfis observados somente do banco local")
app.add_typer(observed_app, name="observed")


@observed_app.command("profile")
def observed_profile(
    since: str = typer.Option(...),
    until: str = typer.Option(...),
    database: str = "data/engine.db",
    output: str | None = None,
):
    import sqlite3
    from pathlib import Path

    import yaml

    from arb.config import Settings
    from arb.permissions import reject_links
    from arb.rules import load_rules
    from arb.sim.observed import profile, window, write_profile

    try:
        reject_links(Path(database))
        _, end = window(since, until)
        target = Path(output) if output else Path("reports") / f"observed-profile-{end.date()}.yaml"
        connection = sqlite3.connect(Path(database).absolute().as_uri() + "?mode=ro", uri=True)
        try:
            result = profile(
                connection,
                since,
                until,
                rules=load_rules(),
                settings=Settings.model_validate(
                    yaml.safe_load(Path("config/settings.yaml").read_text())
                ),
            )
            write_profile(result, target)
        finally:
            connection.close()
    except (ValueError, OSError, sqlite3.Error) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"Perfil local: {target}; suficientes: "
        + str(sum(row["status"] == "sufficient" for row in result["geos"].values()))
    )


smoke_app = typer.Typer(help="Campanha criada e operada pelo humano; motor só lê")
app.add_typer(smoke_app, name="smoke")


@smoke_app.command("register")
def smoke_register(
    campaign: str = typer.Option(...),
    adset: str = typer.Option(...),
    ad: Annotated[list[str], typer.Option()] = ...,
    offer: str = typer.Option(...),
    geo: str = typer.Option(...),
    cap_cents: int = typer.Option(...),
    database: str = "data/engine.db",
):
    import json
    from contextlib import closing
    from pathlib import Path

    from arb.db import connect, migrate
    from arb.smoke import register

    try:
        with closing(connect(Path(database))) as connection:
            migrate(connection)
            value = register(connection, campaign, adset, ad, offer, geo, cap_cents)
        typer.echo(json.dumps(value, sort_keys=True))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@smoke_app.command("invoice")
def smoke_invoice(
    campaign: str = typer.Option(...),
    platform_cents: int = typer.Option(...),
    total_cents: int = typer.Option(...),
    evidence_ref: str = typer.Option(...),
    database: str = "data/engine.db",
):
    from contextlib import closing
    from pathlib import Path

    from arb.db import connect, migrate
    from arb.smoke import record_invoice

    try:
        with closing(connect(Path(database))) as connection:
            migrate(connection)
            record_invoice(
                connection, "meta-" + campaign, platform_cents, total_cents, evidence_ref
            )
        typer.echo("Fatura registrada localmente; não é confirmação assinada V-04.")
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@smoke_app.command("report")
def smoke_report(
    campaign: str | None = None,
    database: str = "data/engine.db",
    output: str = "reports/smoke.json",
    report_file: str = "reports/smoke.md",
):
    import json
    import sqlite3
    from contextlib import closing
    from pathlib import Path

    import yaml

    from arb.config import Settings
    from arb.permissions import private_open, reject_links
    from arb.smoke import markdown, report

    try:
        path = Path(database)
        reject_links(path)
        targets = [Path(output), Path(report_file)]
        if targets[0].resolve() == targets[1].resolve():
            raise ValueError("saídas precisam ser diferentes")
        for target in targets:
            reject_links(target)
            if target.resolve() == path.resolve():
                raise ValueError("saída não pode sobrescrever o banco")
            if Path("config").resolve() in [target.resolve(), *target.resolve().parents]:
                raise ValueError("saída não pode ficar em config")
        settings = Settings.model_validate(yaml.safe_load(Path("config/settings.yaml").read_text()))
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as connection:
            value = report(
                connection,
                "meta-" + campaign if campaign is not None else None,
                media_tax_rate=settings.media_tax_rate,
            )
        text = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        for target, content in zip(targets, [text, markdown(value)], strict=True):
            with private_open(target) as stream:
                stream.write(content)
        typer.echo(text, nl=False)
    except (ValueError, sqlite3.Error) as exc:
        raise typer.BadParameter(str(exc)) from exc
