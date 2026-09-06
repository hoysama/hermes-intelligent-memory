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


def test_cli_search_export_and_import(tmp_path, capsys) -> None:
    parser = build_parser()

    # 1. Import markdown file
    md_file = tmp_path / "seed.md"
    md_file.write_text("- Abdullah prefers bun over npm\n- Second test memory", encoding="utf-8")
    import_args = parser.parse_args(
        ["import", str(md_file), "--hermes-home", str(tmp_path), "--format", "markdown"]
    )
    assert run_command(import_args) == 0
    import_out = capsys.readouterr().out
    assert '"imported": 2' in import_out

    # 2. Search
    search_args = parser.parse_args(
        ["search", "bun", "--hermes-home", str(tmp_path)]
    )
    assert run_command(search_args) == 0
    search_out = capsys.readouterr().out
    assert "Abdullah prefers bun" in search_out

    # 3. Export JSON
    json_export_file = tmp_path / "export.json"
    export_json_args = parser.parse_args(
        [
            "export",
            "--hermes-home",
            str(tmp_path),
            "--format",
            "json",
            "--output",
            str(json_export_file),
        ]
    )
    assert run_command(export_json_args) == 0
    assert json_export_file.exists()
    assert "Abdullah prefers bun" in json_export_file.read_text(encoding="utf-8")

    # 4. Export JSON-LD
    jsonld_file = tmp_path / "export.jsonld"
    export_jsonld_args = parser.parse_args(
        [
            "export",
            "--hermes-home",
            str(tmp_path),
            "--format",
            "json-ld",
            "--output",
            str(jsonld_file),
        ]
    )
    assert run_command(export_jsonld_args) == 0
    assert jsonld_file.exists()
    assert "@graph" in jsonld_file.read_text(encoding="utf-8")

    # 5. Export Markdown
    md_export_file = tmp_path / "export.md"
    export_md_args = parser.parse_args(
        [
            "export",
            "--hermes-home",
            str(tmp_path),
            "--format",
            "markdown",
            "--output",
            str(md_export_file),
        ]
    )
    assert run_command(export_md_args) == 0
    assert md_export_file.exists()
    assert "Exported Intelligent Memory Facts" in md_export_file.read_text(encoding="utf-8")
