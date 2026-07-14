from __future__ import annotations

from intelligent_memory.cli import build_parser, run_command


def test_cli_status_and_dry_run_have_machine_readable_exit_codes(tmp_path, capsys) -> None:
    parser = build_parser()
    status_args = parser.parse_args(["status", "--hermes-home", str(tmp_path)])
    dry_args = parser.parse_args(["migrate", "--dry-run", "--hermes-home", str(tmp_path)])

    assert run_command(status_args) == 0
    assert run_command(dry_args) == 0
    output = capsys.readouterr().out
    assert "intelligent_memory" in output
    assert "dry_run" in output


def test_cli_rejects_rollback_without_backup(tmp_path) -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["rollback", "--backup", str(tmp_path / "missing"), "--hermes-home", str(tmp_path)]
    )

    assert run_command(args) == 2
