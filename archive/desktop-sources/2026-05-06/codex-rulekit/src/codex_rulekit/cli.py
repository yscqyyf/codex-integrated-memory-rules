from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from codex_rulekit import __version__
from codex_rulekit.core import (
    bootstrap_library,
    build_catalog,
    create_inbox_draft,
    ensure_project_integration,
    init_project_rules,
    list_inbox,
    promote_inbox_rule,
    retire_rule,
)


def format_user_error(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        return str(exc)
    if isinstance(exc, NotADirectoryError):
        return str(exc)
    if isinstance(exc, yaml.YAMLError):
        return f"YAML parse error: {exc}"
    if isinstance(exc, ValueError):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-rulekit",
        description="Codex helper for bootstrapping a shared rule library and attaching the right rules to a project.",
        epilog=(
            "Primary workflow: "
            "`codex-rulekit bootstrap --root <.codex>` once, then "
            "`codex-rulekit ensure-project --root <.codex> --project <repo>` when implementation starts. "
            "Other commands are advanced maintenance utilities."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser("bootstrap", help="[Primary] Bootstrap a shared ~/.codex-style rule library")
    bootstrap.add_argument("--root", required=True, help="Target root, for example C:\\Users\\admin\\.codex")
    bootstrap.add_argument("--overwrite", action="store_true", help="Overwrite existing files")

    catalog = subparsers.add_parser("build-catalog", help="[Advanced] Rebuild rule-library/catalog.json")
    catalog.add_argument("--root", required=True, help="Root that contains rule-library/")

    init_project = subparsers.add_parser("init-project", help="[Advanced] Preview or generate project rules directly")
    init_project.add_argument("--root", required=True, help="Root that contains rule-library/")
    init_project.add_argument("--project", required=True, help="Project root directory")
    init_project.add_argument("--apply", action="store_true", help="Write project-rules.generated.md")
    init_project.add_argument("--limit", type=int, default=8, help="Max accepted rule count")

    ensure_project = subparsers.add_parser(
        "ensure-project",
        help="[Primary] Attach the right rules to a project and ensure project AGENTS wiring",
    )
    ensure_project.add_argument("--root", required=True, help="Root that contains rule-library/")
    ensure_project.add_argument("--project", required=True, help="Project root directory")
    ensure_project.add_argument("--limit", type=int, default=8, help="Max accepted rule count")
    ensure_project.add_argument(
        "--overwrite-agents",
        action="store_true",
        help="Overwrite an existing project-root AGENTS.md",
    )

    review = subparsers.add_parser("review-inbox", help="[Advanced] List or promote inbox drafts")
    review.add_argument("--root", required=True, help="Root that contains rule-library/")
    review.add_argument("--promote", help="Draft filename to promote, for example example.md")
    review.add_argument("--dest-subdir", default="general", help="Curated subdir when promoting")

    draft = subparsers.add_parser("save-draft", help="[Advanced] Create an inbox draft from a new rule")
    draft.add_argument("--root", required=True, help="Root that contains rule-library/")
    draft.add_argument("--title", required=True, help="Draft title")
    draft.add_argument("--body", required=True, help="Draft body")
    draft.add_argument("--tags", nargs="*", default=["general"], help="Draft tags")
    draft.add_argument("--project-types", nargs="*", default=["general"], help="Draft project types")

    retire = subparsers.add_parser("retire-rule", help="[Advanced] Move a curated rule into retired/")
    retire.add_argument("--root", required=True, help="Root that contains rule-library/")
    retire.add_argument("--id", required=True, help="Rule id to retire")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "bootstrap":
            result = bootstrap_library(Path(args.root), overwrite=args.overwrite)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        if args.command == "build-catalog":
            result = build_catalog(Path(args.root))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        if args.command == "init-project":
            result = init_project_rules(
                library_root=Path(args.root),
                project_root=Path(args.project),
                apply=args.apply,
                limit=args.limit,
                generator_version=__version__,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        if args.command == "ensure-project":
            result = ensure_project_integration(
                library_root=Path(args.root),
                project_root=Path(args.project),
                limit=args.limit,
                generator_version=__version__,
                overwrite_agents=args.overwrite_agents,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        if args.command == "review-inbox":
            if args.promote:
                result = promote_inbox_rule(Path(args.root), args.promote, args.dest_subdir)
            else:
                result = {"drafts": list_inbox(Path(args.root))}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        if args.command == "save-draft":
            result = create_inbox_draft(
                library_root=Path(args.root),
                title=args.title,
                body=args.body,
                tags=args.tags,
                project_types=args.project_types,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        if args.command == "retire-rule":
            result = retire_rule(Path(args.root), args.id)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
    except (FileNotFoundError, NotADirectoryError, ValueError, yaml.YAMLError) as exc:
        print(f"Error: {format_user_error(exc)}", file=sys.stderr)
        return 2

    parser.error(f"unsupported command: {args.command}")
    return 2
