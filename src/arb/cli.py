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
        target = backup_daily(connection, Path(output).resolve())
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
    from arb.scout.ranking import propose, rank

    try:
        ranked, rejected = rank(import_offers(Path(offers)), import_adlibrary(Path(adlibrary)))
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
):
    from pathlib import Path

    from arb.bridge import build
    from arb.db import Repository, connect, migrate
    from arb.models import Offer

    connection = connect(Path(database))
    try:
        migrate(connection)
        offer = Repository(connection, Offer).get(offer_id)
        if offer is None:
            raise typer.BadParameter("Oferta desconhecida")
        target = build(
            offer,
            Path(content_file).read_text(),
            slug,
            worker_url=worker_url,
            pixel_id=pixel_id,
            tracking_key=tracking_key,
            output=Path(output),
        )
    finally:
        connection.close()
    typer.echo(f"Ponte gerada: {target}")


sales_app = typer.Typer(help="Vendas normalizadas de CSV")
app.add_typer(sales_app, name="sales")
sync_app = typer.Typer(help="Sincronização somente leitura de fontes externas")
app.add_typer(sync_app, name="sync")


@sales_app.command("import")
def sales_import(csv_file: str, database: str = "data/engine.db"):
    from pathlib import Path

    from arb.db import connect, migrate
    from arb.tracker import import_sales

    connection = connect(Path(database))
    try:
        migrate(connection)
        count = import_sales(connection, Path(csv_file))
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
    """Último slot vencido: fonte offline ausente congela simulação; não acessa APIs."""
    import json
    from datetime import UTC, datetime, timedelta
    from pathlib import Path

    from arb.db import connect, migrate
    from arb.scheduler import ZONE, run_cycle, schedule

    now = datetime.now(UTC)
    today = now.astimezone(ZONE).date()
    slot = max(s for s in schedule(today - timedelta(days=1), today) if s <= now)
    connection = connect(Path(database))
    try:
        migrate(connection)
        result = run_cycle(connection, slot, now=now, root=Path(root), output=Path(output))
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
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
):
    import json
    from pathlib import Path

    from arb.sim.calibrate import calibrate, html_report

    if seeds < 1:
        raise typer.BadParameter("seeds precisa ser positivo")
    result = calibrate(seeds=list(range(seeds)), workers=workers)
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
