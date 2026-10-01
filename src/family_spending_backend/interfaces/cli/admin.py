"""Offline administrative CLI for import, parity, backup, restore, and integrity."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from family_spending_backend.migration import import_legacy_copy, verify_parity
from family_spending_backend.operations import (
    check_integrity,
    create_backup,
    restore_backup,
)


def _json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="family-spending-admin")
    commands = parser.add_subparsers(dest="command", required=True)

    integrity = commands.add_parser("integrity-check")
    integrity.add_argument("--data-root", type=Path, required=True)
    integrity.add_argument("--parser-version", required=True)

    parity = commands.add_parser("parity")
    parity.add_argument("--left", type=Path, required=True)
    parity.add_argument("--right", type=Path, required=True)
    parity.add_argument("--parser-version", required=True)

    importer = commands.add_parser("import")
    importer.add_argument("--source", type=Path, required=True)
    importer.add_argument("--target", type=Path, required=True)
    importer.add_argument("--parser-version", required=True)

    backup = commands.add_parser("backup")
    backup.add_argument("--data-root", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)
    backup.add_argument("--parser-version", required=True)

    restore = commands.add_parser("restore")
    restore.add_argument("--archive", type=Path, required=True)
    restore.add_argument("--target", type=Path, required=True)
    restore.add_argument("--parser-version", required=True)
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    if arguments.command == "integrity-check":
        result = check_integrity(arguments.data_root, parser_version=arguments.parser_version)
    elif arguments.command == "parity":
        result = verify_parity(
            arguments.left,
            arguments.right,
            parser_version=arguments.parser_version,
        )
    elif arguments.command == "import":
        result = import_legacy_copy(
            arguments.source,
            arguments.target,
            parser_version=arguments.parser_version,
        )
    elif arguments.command == "backup":
        result = create_backup(
            arguments.data_root,
            arguments.output,
            parser_version=arguments.parser_version,
        )
    else:
        result = restore_backup(
            arguments.archive,
            arguments.target,
            parser_version=arguments.parser_version,
        )
    print(json.dumps(asdict(result), ensure_ascii=False, default=_json_default))
