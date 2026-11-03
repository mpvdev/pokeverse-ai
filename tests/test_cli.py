from typer.testing import CliRunner

from pokeverse.cli import app

runner = CliRunner()


def test_cli_prints_welcome_message() -> None:
    result = runner.invoke(app)

    assert result.exit_code == 0
    assert result.stdout == "Welcome to PokéVerse AI\n"


def test_cli_reports_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout == "0.1.0\n"
