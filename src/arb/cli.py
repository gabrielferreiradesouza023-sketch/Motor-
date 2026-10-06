import typer

app = typer.Typer(no_args_is_help=True)


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
    typer.echo("Doctor OK — F0 local, LIVE_MODE=false; sem integrações externas.")


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
