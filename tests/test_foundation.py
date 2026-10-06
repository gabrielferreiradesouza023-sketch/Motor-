from pathlib import Path


def test_agent_constitution_and_future_board():
    root = Path(__file__).resolve().parents[1]
    assert "## 0. Princípios inegociáveis" in (root / "AGENTS.md").read_text()
    assert "## 9. Protocolo multiagente" in (root / "AGENTS.md").read_text()
    for number in range(5, 30):
        task = (root / f"ops/board/todo/T-{number:02d}.md").read_text()
        for heading in [
            "## Objetivo",
            "## Arquivos",
            "## Critérios de aceite",
            "## Testes obrigatórios",
        ]:
            assert heading in task
