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
def sim_run(seed: int = 42, budget: int = 2400, database: str | None = None):
    """Budget em BRL inteiros. Persistência opcional em banco separado e novo."""
    import json
    import os
    from pathlib import Path

    from arb.sim.lab import persist, run_lab

    if os.environ.get("LIVE_MODE", "false").lower() != "false":
        raise typer.BadParameter("LIVE_MODE deve ser false")
    try:
        run = run_lab(seed, budget * 100)
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
    from arb.meta.read import MetaReadError, Reader
    from arb.meta.sync import sync

    if os.environ.get("LIVE_MODE", "false").lower() != "false":
        raise typer.BadParameter("LIVE_MODE precisa ser false")
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
