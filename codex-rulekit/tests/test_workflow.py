from __future__ import annotations

import contextlib
import io
import json
import unittest
import uuid
from pathlib import Path
from unittest import mock

from codex_rulekit.cli import main as cli_main
from codex_rulekit.core import (
    annotate_generated_profile,
    bootstrap_library,
    build_catalog,
    catalog_is_stale,
    compute_render_context_hash,
    create_inbox_draft,
    dump_yaml,
    ensure_project_integration,
    infer_profile,
    init_project_rules,
    load_catalog,
    load_profile,
    promote_inbox_rule,
    select_rules,
)
from codex_rulekit.profile import scan_project_snapshot


class WorkflowTest(unittest.TestCase):
    def _make_case(self) -> tuple[Path, Path]:
        repo_tmp = Path(__file__).resolve().parents[1] / ".tmp-tests"
        repo_tmp.mkdir(parents=True, exist_ok=True)
        case_root = repo_tmp / f"workflow-{uuid.uuid4().hex}"
        case_root.mkdir(parents=True, exist_ok=True)
        root = case_root / ".codex"
        project = case_root / "demo-project"
        project.mkdir()
        return root, project

    def test_bootstrap_init_and_promote(self) -> None:
        root, project = self._make_case()
        (project / "requirements.txt").write_text("pyyaml\n", encoding="utf-8")

        bootstrap_result = bootstrap_library(root, overwrite=False)
        self.assertTrue((root / "AGENTS.md").exists())
        self.assertTrue((root / "rule-library" / "catalog.json").exists())
        self.assertTrue(bootstrap_result["created"])

        init_result = init_project_rules(
            library_root=root,
            project_root=project,
            apply=True,
            limit=6,
            generator_version="test",
        )
        self.assertIn(init_result["status"], {"applied", "cache_hit"})
        self.assertTrue((project / ".codex" / "project-profile.yaml").exists())
        self.assertTrue((project / ".codex" / "project-rules.selection.json").exists())
        self.assertTrue((project / ".codex" / "project-rules.generated.md").exists())

        selection = json.loads((project / ".codex" / "project-rules.selection.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(selection["accepted"]), 1)

        create_inbox_draft(
            library_root=root,
            title="CSV quick patch",
            body="Allow a fast temporary data cleaning shortcut for research notebooks.",
            tags=["python", "research"],
            project_types=["research"],
        )
        inbox_file = root / "rule-library" / "inbox" / "csv-quick-patch.md"
        self.assertTrue(inbox_file.exists())

        promote_result = promote_inbox_rule(root, inbox_file.name, "general")
        self.assertTrue((root / "rule-library" / "curated" / "general" / inbox_file.name).exists())
        self.assertIn("catalog_hash", promote_result)

    def test_cache_hit_and_rejection_reason(self) -> None:
        root, project = self._make_case()
        bootstrap_library(root, overwrite=False)
        codex_dir = project / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        (codex_dir / "project-profile.yaml").write_text(
            "\n".join(
                [
                    "name: demo-project",
                    "project_type: coding",
                    "risk_level: low",
                    "tags:",
                    "  - windows",
                    "context_description: Windows coding repo.",
                    "force_include: []",
                    "exclude_rules:",
                    "  - id: prefer-temp-script",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        preview = init_project_rules(
            library_root=root,
            project_root=project,
            apply=False,
            limit=6,
            generator_version="test",
        )
        self.assertEqual(preview["status"], "preview")
        selection = json.loads((codex_dir / "project-rules.selection.json").read_text(encoding="utf-8"))
        rejected = {item["id"]: item["reason"] for item in selection["rejected"]}
        self.assertEqual(rejected["prefer-temp-script"], "excluded_by_id")

        first_apply = init_project_rules(
            library_root=root,
            project_root=project,
            apply=True,
            limit=6,
            generator_version="test",
        )
        second_apply = init_project_rules(
            library_root=root,
            project_root=project,
            apply=True,
            limit=6,
            generator_version="test",
        )
        self.assertEqual(first_apply["status"], "applied")
        self.assertIn(second_apply["status"], {"applied", "cache_hit"})
        statuses = [second_apply["status"]]
        for _ in range(4):
            statuses.append(
                init_project_rules(
                    library_root=root,
                    project_root=project,
                    apply=True,
                    limit=6,
                    generator_version="test",
                )["status"]
            )
        self.assertIn("cache_hit", statuses)

    def test_catalog_rebuild_after_curated_change(self) -> None:
        root, project = self._make_case()
        bootstrap_library(root, overwrite=False)
        catalog = load_catalog(root)
        self.assertFalse(catalog_is_stale(root, catalog))

        create_inbox_draft(
            library_root=root,
            title="Research fast mode",
            body="Allow temporary shortcuts in exploratory notebooks.",
            tags=["research", "python"],
            project_types=["research"],
        )
        promote_inbox_rule(root, "research-fast-mode.md", "general")
        refreshed = load_catalog(root)
        self.assertFalse(catalog_is_stale(root, refreshed))
        ids = {item["id"] for item in refreshed["rules"]}
        self.assertIn("research-fast-mode", ids)

    def test_out_of_scope_rule_is_rejected(self) -> None:
        root, project = self._make_case()
        bootstrap_library(root, overwrite=False)
        curated = root / "rule-library" / "curated" / "windows"
        curated.mkdir(parents=True, exist_ok=True)
        (curated / "python-helper.md").write_text(
            "\n".join(
                [
                    "---",
                    "id: python-helper",
                    "title: Python helper",
                    "tags: [python]",
                    "project_types: [coding]",
                    "priority: 70",
                    "confidence: 0.8",
                    "stability: stable",
                    "conflicts_with: []",
                    "review_after: 2026-12-31",
                    "last_validated: 2026-04-22",
                    "---",
                    "Prefer Python helpers.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        build_catalog(root)
        codex_dir = project / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        (codex_dir / "project-profile.yaml").write_text(
            "\n".join(
                [
                    "name: research-demo",
                    "project_type: research",
                    "risk_level: low",
                    "tags:",
                    "  - python",
                    "context_description: Exploratory notebook work.",
                    "force_include: []",
                    "exclude_rules: []",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        init_project_rules(root, project, apply=False, limit=6, generator_version="test")
        selection = json.loads((codex_dir / "project-rules.selection.json").read_text(encoding="utf-8"))
        rejected = {item["id"]: item["reason"] for item in selection["rejected"]}
        self.assertEqual(rejected["python-helper"], "out_of_scope")

    def test_ensure_project_writes_agents_once(self) -> None:
        root, project = self._make_case()
        bootstrap_library(root, overwrite=False)
        (project / "requirements.txt").write_text("pyyaml\n", encoding="utf-8")

        first = ensure_project_integration(
            library_root=root,
            project_root=project,
            limit=6,
            generator_version="test",
            overwrite_agents=False,
        )
        self.assertEqual(first["project_agents_status"], "written")
        agents_path = project / "AGENTS.md"
        self.assertTrue(agents_path.exists())
        original_agents = agents_path.read_text(encoding="utf-8")
        self.assertIn("@.codex/project-rules.generated.md", original_agents)
        self.assertTrue(first["profile_change_summary"])
        self.assertTrue(first["project_activity_summary"])

        agents_path.write_text("# Existing AGENTS\n", encoding="utf-8")
        second = ensure_project_integration(
            library_root=root,
            project_root=project,
            limit=6,
            generator_version="test",
            overwrite_agents=False,
        )
        self.assertEqual(second["project_agents_status"], "exists")
        self.assertEqual(agents_path.read_text(encoding="utf-8"), "# Existing AGENTS\n")
        state_path = project / ".codex" / "project-state.json"
        self.assertTrue(state_path.exists())
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertIn("rule_history", state)
        self.assertIn("last_snapshot", state)
        usage_log = root / "usage-log.jsonl"
        usage_summary = root / "usage-summary.json"
        self.assertTrue(usage_log.exists())
        self.assertTrue(usage_summary.exists())
        lines = [json.loads(line) for line in usage_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[-1]["project_root"], str(project))
        summary = json.loads(usage_summary.read_text(encoding="utf-8"))
        project_summary = summary["projects"][str(project)]
        self.assertEqual(project_summary["project_root"], str(project))
        self.assertEqual(project_summary["total_runs"], 2)
        self.assertEqual(project_summary["last_agents_status"], "exists")
        self.assertIn(project_summary["last_status"], {"applied", "cache_hit"})

    def test_infer_profile_detects_static_frontend_game(self) -> None:
        root, project = self._make_case()
        bootstrap_library(root, overwrite=False)
        (project / "index.html").write_text("<!doctype html>", encoding="utf-8")
        (project / "styles.css").write_text("body {}", encoding="utf-8")
        (project / "game.js").write_text("console.log('game')", encoding="utf-8")
        (project / "battle-current.png").write_text("fake", encoding="utf-8")

        profile = infer_profile(project)
        tags = set(profile["tags"])
        self.assertTrue({"frontend", "html", "css", "javascript", "browser-game"}.issubset(tags))
        self.assertIn("static frontend project", profile["context_description"].lower())

    def test_infer_profile_ignores_rule_template_game_names(self) -> None:
        _, project = self._make_case()
        (project / "pyproject.toml").write_text("[project]\nname = 'tooling'\n", encoding="utf-8")
        template_dir = project / "src" / "codex_rulekit" / "templates" / "rule-library" / "curated" / "frontend"
        template_dir.mkdir(parents=True)
        (template_dir / "browser-game-frontend.md").write_text("Rule text.", encoding="utf-8")

        snapshot = scan_project_snapshot(project)
        profile = infer_profile(project, snapshot=snapshot)

        self.assertEqual(snapshot["game_named_hits"], [])
        self.assertIn("python", profile["tags"])
        self.assertNotIn("browser-game", profile["tags"])
        self.assertNotIn("game-ui", profile["tags"])

    def test_infer_profile_detects_nested_frontend_structure(self) -> None:
        root, project = self._make_case()
        bootstrap_library(root, overwrite=False)
        web_dir = project / "web"
        web_dir.mkdir()
        (web_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
        (web_dir / "styles.css").write_text("body {}", encoding="utf-8")
        (web_dir / "app.js").write_text("console.log('app')", encoding="utf-8")

        profile = infer_profile(project)
        tags = set(profile["tags"])
        self.assertTrue({"frontend", "html", "css", "javascript", "static-web"}.issubset(tags))

    def test_auto_profile_refresh_enables_frontend_rule(self) -> None:
        root, project = self._make_case()
        bootstrap_library(root, overwrite=False)
        (project / "index.html").write_text("<!doctype html>", encoding="utf-8")
        (project / "styles.css").write_text("body {}", encoding="utf-8")
        (project / "game.js").write_text("console.log('game')", encoding="utf-8")
        codex_dir = project / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        profile = annotate_generated_profile(
            {
                "name": "demo-project",
                "project_type": "coding",
                "risk_level": "low",
                "tags": ["general"],
                "context_description": "Auto-generated draft. Confirm before long-term use.",
                "force_include": [],
                "exclude_rules": [],
                "_profile_meta": {
                    "managed_by": "codex-rulekit",
                    "inference_version": 2,
                    "auto_generated": True,
                },
            }
        )
        (codex_dir / "project-profile.yaml").write_text(
            dump_yaml(profile),
            encoding="utf-8",
        )

        result = ensure_project_integration(
            library_root=root,
            project_root=project,
            limit=6,
            generator_version="test",
            overwrite_agents=False,
        )
        self.assertIn(result["status"], {"applied", "cache_hit"})
        refreshed_profile = load_profile(codex_dir / "project-profile.yaml")
        self.assertIn("frontend", refreshed_profile["tags"])
        selection = json.loads((codex_dir / "project-rules.selection.json").read_text(encoding="utf-8"))
        accepted_ids = {item["id"] for item in selection["accepted"]}
        self.assertIn("browser-game-frontend", accepted_ids)
        self.assertIn("static-web-minimal-stack", accepted_ids)
        self.assertTrue(result["profile_change_summary"])
        self.assertTrue(result["project_activity_summary"])

    def test_user_edited_profile_is_not_overwritten(self) -> None:
        root, project = self._make_case()
        bootstrap_library(root, overwrite=False)
        (project / "index.html").write_text("<!doctype html>", encoding="utf-8")
        (project / "styles.css").write_text("body {}", encoding="utf-8")
        (project / "game.js").write_text("console.log('game')", encoding="utf-8")
        codex_dir = project / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        generated_profile = annotate_generated_profile(
            {
                "name": "demo-project",
                "project_type": "coding",
                "risk_level": "low",
                "tags": ["general"],
                "context_description": "Auto-generated draft. Confirm before long-term use.",
                "force_include": [],
                "exclude_rules": [],
                "_profile_meta": {
                    "managed_by": "codex-rulekit",
                    "inference_version": 2,
                    "auto_generated": True,
                },
            }
        )
        generated_profile["tags"] = ["python", "windows"]
        generated_profile["context_description"] = "User tuned profile."
        (codex_dir / "project-profile.yaml").write_text(dump_yaml(generated_profile), encoding="utf-8")

        ensure_project_integration(
            library_root=root,
            project_root=project,
            limit=6,
            generator_version="test",
            overwrite_agents=False,
        )
        profile_after = load_profile(codex_dir / "project-profile.yaml")
        self.assertEqual(profile_after["tags"], ["python", "windows"])
        self.assertEqual(profile_after["context_description"], "User tuned profile.")

    def test_matching_generated_profile_refreshes_after_detector_change(self) -> None:
        root, project = self._make_case()
        bootstrap_library(root, overwrite=False)
        (project / "pyproject.toml").write_text("[project]\nname = 'tooling'\n", encoding="utf-8")
        template_dir = project / "src" / "codex_rulekit" / "templates" / "rule-library" / "curated" / "frontend"
        template_dir.mkdir(parents=True)
        (template_dir / "browser-game-frontend.md").write_text("Rule text.", encoding="utf-8")
        codex_dir = project / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        generated_profile = annotate_generated_profile(
            {
                "name": "demo-project",
                "project_type": "coding",
                "risk_level": "low",
                "tags": ["browser-game", "game-ui", "python"],
                "context_description": "Detected browser-game style files or gameplay-oriented asset names. Detected Python project files.",
                "force_include": [],
                "exclude_rules": [],
                "_profile_meta": {
                    "managed_by": "codex-rulekit",
                    "inference_version": 2,
                    "auto_generated": True,
                },
            }
        )
        (codex_dir / "project-profile.yaml").write_text(dump_yaml(generated_profile), encoding="utf-8")

        ensure_project_integration(
            library_root=root,
            project_root=project,
            limit=6,
            generator_version="test",
            overwrite_agents=False,
        )
        profile_after = load_profile(codex_dir / "project-profile.yaml")
        self.assertIn("python", profile_after["tags"])
        self.assertNotIn("browser-game", profile_after["tags"])
        self.assertNotIn("game-ui", profile_after["tags"])

    def test_legacy_auto_generated_profile_without_fingerprint_refreshes_once(self) -> None:
        root, project = self._make_case()
        bootstrap_library(root, overwrite=False)
        (project / "index.html").write_text("<!doctype html>", encoding="utf-8")
        (project / "styles.css").write_text("body {}", encoding="utf-8")
        (project / "app.js").write_text("console.log('app')", encoding="utf-8")
        codex_dir = project / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        legacy_profile = {
            "name": "demo-project",
            "project_type": "coding",
            "risk_level": "low",
            "tags": ["general"],
            "context_description": "Auto-generated draft. Confirm before long-term use.",
            "force_include": [],
            "exclude_rules": [],
            "_profile_meta": {
                "managed_by": "codex-rulekit",
                "inference_version": 1,
                "auto_generated": True,
            },
        }
        (codex_dir / "project-profile.yaml").write_text(dump_yaml(legacy_profile), encoding="utf-8")

        ensure_project_integration(
            library_root=root,
            project_root=project,
            limit=6,
            generator_version="test",
            overwrite_agents=False,
        )
        profile_after = load_profile(codex_dir / "project-profile.yaml")
        self.assertIn("frontend", profile_after["tags"])
        self.assertIn("profile_fingerprint", profile_after["_profile_meta"])

    def test_rule_history_updates_after_repeated_selection(self) -> None:
        root, project = self._make_case()
        bootstrap_library(root, overwrite=False)
        (project / "index.html").write_text("<!doctype html>", encoding="utf-8")
        (project / "styles.css").write_text("body {}", encoding="utf-8")
        (project / "game.js").write_text("console.log('game')", encoding="utf-8")

        ensure_project_integration(
            library_root=root,
            project_root=project,
            limit=6,
            generator_version="test",
            overwrite_agents=False,
        )
        ensure_project_integration(
            library_root=root,
            project_root=project,
            limit=6,
            generator_version="test",
            overwrite_agents=False,
        )
        state = json.loads((project / ".codex" / "project-state.json").read_text(encoding="utf-8"))
        browser_rule = state["rule_history"]["browser-game-frontend"]
        self.assertGreaterEqual(browser_rule["accepted_total"], 2)
        self.assertGreaterEqual(browser_rule["accepted_streak"], 2)

    def test_repeated_rejections_produce_maintenance_suggestion(self) -> None:
        root, project = self._make_case()
        bootstrap_library(root, overwrite=False)
        (project / "requirements.txt").write_text("pyyaml\n", encoding="utf-8")
        codex_dir = project / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        (codex_dir / "project-profile.yaml").write_text(
            "\n".join(
                [
                    "name: demo-project",
                    "project_type: coding",
                    "risk_level: low",
                    "tags:",
                    "  - general",
                    "context_description: Auto-generated draft. Confirm before long-term use.",
                    "force_include: []",
                    "exclude_rules: []",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        result = None
        for _ in range(5):
            result = ensure_project_integration(
                library_root=root,
                project_root=project,
                limit=3,
                generator_version="test",
                overwrite_agents=False,
            )
        assert result is not None
        suggestions = "\n".join(result["maintenance_suggestions"])
        self.assertIn("prefer-temp-script", suggestions)
        self.assertIn("acceptance rate", suggestions)
        selection = json.loads((project / ".codex" / "project-rules.selection.json").read_text(encoding="utf-8"))
        self.assertIn("governance", selection["metadata"])
        generated = (project / ".codex" / "project-rules.generated.md").read_text(encoding="utf-8")
        self.assertNotIn("## Governance Suggestions", generated)
        self.assertNotIn("## Governance Metrics", generated)

    def test_generated_markdown_uses_readable_chinese_labels(self) -> None:
        root, project = self._make_case()
        bootstrap_library(root, overwrite=False)
        (project / "requirements.txt").write_text("pyyaml\n", encoding="utf-8")

        ensure_project_integration(
            library_root=root,
            project_root=project,
            limit=6,
            generator_version="test",
            overwrite_agents=False,
        )
        generated = (project / ".codex" / "project-rules.generated.md").read_text(encoding="utf-8")
        self.assertIn("> 优先级声明:", generated)
        self.assertIn("- 项目:", generated)
        self.assertIn("来源:", generated)
        self.assertIn("摘要:", generated)
        self.assertNotIn("浼樺厛", generated)

    def test_scan_ignores_temp_directories(self) -> None:
        _, project = self._make_case()
        (project / "requirements.txt").write_text("pyyaml\n", encoding="utf-8")
        tmp_tests = project / ".tmp-tests" / "fixture-ui"
        tmp_tests.mkdir(parents=True, exist_ok=True)
        (tmp_tests / "index.html").write_text("<!doctype html>", encoding="utf-8")
        (tmp_tests / "styles.css").write_text("body {}", encoding="utf-8")
        (tmp_tests / "app.js").write_text("console.log('tmp')", encoding="utf-8")
        temp_dir = project / "tmp" / "fixture-ui"
        temp_dir.mkdir(parents=True, exist_ok=True)
        (temp_dir / "battle-screen.png").write_text("fake", encoding="utf-8")
        archive_dir = project / "archive" / "desktop-sources" / "old-web"
        archive_dir.mkdir(parents=True, exist_ok=True)
        (archive_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
        (archive_dir / "styles.css").write_text("body {}", encoding="utf-8")
        (archive_dir / "game.js").write_text("console.log('old')", encoding="utf-8")

        snapshot = scan_project_snapshot(project)
        self.assertEqual(snapshot["ext_counts"].get(".html", 0), 0)
        self.assertEqual(snapshot["ext_counts"].get(".css", 0), 0)
        self.assertEqual(snapshot["ext_counts"].get(".js", 0), 0)
        self.assertEqual(snapshot["ext_counts"].get(".png", 0), 0)
        self.assertEqual(snapshot["game_named_hits"], [])
        self.assertEqual(sorted(snapshot["file_manifest"].keys()), ["requirements.txt"])

    def test_experimental_rules_stay_in_shadow_mode(self) -> None:
        root, project = self._make_case()
        bootstrap_library(root, overwrite=False)
        curated = root / "rule-library" / "curated" / "frontend"
        curated.mkdir(parents=True, exist_ok=True)
        (project / "index.html").write_text("<!doctype html>", encoding="utf-8")
        (project / "styles.css").write_text("body {}", encoding="utf-8")
        (project / "app.js").write_text("console.log('ui')", encoding="utf-8")
        (curated / "experimental-ui-rule.md").write_text(
            "\n".join(
                [
                    "---",
                    "id: experimental-ui-rule",
                    "title: Experimental UI rule",
                    "tags: [frontend, html, css, visual-ui]",
                    "project_types: [coding]",
                    "priority: 82",
                    "confidence: 0.86",
                    "layer: domain",
                    "domain_scope: [frontend, static-web]",
                    "stability: experimental",
                    "conflicts_with: []",
                    "---",
                    "Try a more aggressive UI polish pass before promoting this rule.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        build_catalog(root)

        result = ensure_project_integration(
            library_root=root,
            project_root=project,
            limit=6,
            generator_version="test",
            overwrite_agents=False,
        )
        self.assertIn(result["status"], {"applied", "cache_hit"})
        selection = json.loads((project / ".codex" / "project-rules.selection.json").read_text(encoding="utf-8"))
        experimental_ids = {item["id"] for item in selection["experimental"]}
        self.assertIn("experimental-ui-rule", experimental_ids)
        accepted_ids = {item["id"] for item in selection["accepted"]}
        self.assertNotIn("experimental-ui-rule", accepted_ids)
        generated = (project / ".codex" / "project-rules.generated.md").read_text(encoding="utf-8")
        self.assertIn("## Experimental Rules", generated)
        self.assertIn("[Experimental] Experimental UI rule", generated)
        self.assertNotIn("## Rejected Rules", generated)

    def test_domain_rule_can_replace_conflicting_base_rule(self) -> None:
        root, project = self._make_case()
        bootstrap_library(root, overwrite=False)
        curated_general = root / "rule-library" / "curated" / "general"
        curated_frontend = root / "rule-library" / "curated" / "frontend"
        curated_frontend.mkdir(parents=True, exist_ok=True)
        (project / "index.html").write_text("<!doctype html>", encoding="utf-8")
        (project / "styles.css").write_text("body {}", encoding="utf-8")
        (project / "app.js").write_text("console.log('ui')", encoding="utf-8")
        (curated_general / "generic-ui-baseline.md").write_text(
            "\n".join(
                [
                    "---",
                    "id: generic-ui-baseline",
                    "title: Generic UI baseline",
                    "tags: [general, ui]",
                    "project_types: [general, coding]",
                    "priority: 95",
                    "confidence: 0.95",
                    "layer: base",
                    "domain_scope: [general]",
                    "stability: stable",
                    "conflicts_with: [frontend-ui-specialist]",
                    "---",
                    "Use a conservative shared UI baseline.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (curated_frontend / "frontend-ui-specialist.md").write_text(
            "\n".join(
                [
                    "---",
                    "id: frontend-ui-specialist",
                    "title: Frontend UI specialist",
                    "tags: [frontend, html, css, ui]",
                    "project_types: [coding]",
                    "priority: 88",
                    "confidence: 0.9",
                    "layer: domain",
                    "domain_scope: [frontend, static-web]",
                    "stability: stable",
                    "conflicts_with: [generic-ui-baseline]",
                    "---",
                    "Prefer frontend-specific UI decisions when the project is clearly browser-facing.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        build_catalog(root)

        ensure_project_integration(
            library_root=root,
            project_root=project,
            limit=6,
            generator_version="test",
            overwrite_agents=False,
        )
        selection = json.loads((project / ".codex" / "project-rules.selection.json").read_text(encoding="utf-8"))
        accepted_ids = {item["id"] for item in selection["accepted"]}
        rejected = {item["id"]: item["reason"] for item in selection["rejected"]}
        self.assertIn("frontend-ui-specialist", accepted_ids)
        self.assertEqual(rejected["generic-ui-baseline"], "displaced_by:frontend-ui-specialist")

    def test_expired_rule_is_rejected(self) -> None:
        root, project = self._make_case()
        bootstrap_library(root, overwrite=False)
        curated = root / "rule-library" / "curated" / "frontend"
        curated.mkdir(parents=True, exist_ok=True)
        (project / "index.html").write_text("<!doctype html>", encoding="utf-8")
        (project / "styles.css").write_text("body {}", encoding="utf-8")
        (curated / "expired-ui-rule.md").write_text(
            "\n".join(
                [
                    "---",
                    "id: expired-ui-rule",
                    "title: Expired UI rule",
                    "tags: [frontend, html, css]",
                    "project_types: [coding]",
                    "priority: 95",
                    "confidence: 0.95",
                    "layer: domain",
                    "domain_scope: [frontend]",
                    "stability: stable",
                    "valid_until: 2020-01-01",
                    "review_after: 2020-06-01",
                    "last_validated: 2020-01-01",
                    "conflicts_with: []",
                    "---",
                    "This rule is intentionally expired.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        build_catalog(root)

        result = ensure_project_integration(
            library_root=root,
            project_root=project,
            limit=6,
            generator_version="test",
            overwrite_agents=False,
        )
        selection = json.loads((project / ".codex" / "project-rules.selection.json").read_text(encoding="utf-8"))
        rejected = {item["id"]: item["reason"] for item in selection["rejected"]}
        self.assertEqual(rejected["expired-ui-rule"], "expired_rule")
        suggestions = "\n".join(result["maintenance_suggestions"])
        self.assertIn("expired-ui-rule", suggestions)
        self.assertIn("valid_until", suggestions)

    def test_stale_rule_generates_revalidation_suggestion(self) -> None:
        root, project = self._make_case()
        bootstrap_library(root, overwrite=False)
        curated = root / "rule-library" / "curated" / "general"
        curated.mkdir(parents=True, exist_ok=True)
        (curated / "stale-general-rule.md").write_text(
            "\n".join(
                [
                    "---",
                    "id: stale-general-rule",
                    "title: Stale general rule",
                    "tags: [general]",
                    "project_types: [general, coding]",
                    "priority: 99",
                    "confidence: 0.98",
                    "layer: base",
                    "domain_scope: [general]",
                    "stability: stable",
                    "review_after: 2020-06-01",
                    "last_validated: 2020-01-01",
                    "conflicts_with: []",
                    "---",
                    "A high-priority but stale base rule.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        build_catalog(root)
        (project / "requirements.txt").write_text("pyyaml\n", encoding="utf-8")

        result = ensure_project_integration(
            library_root=root,
            project_root=project,
            limit=6,
            generator_version="test",
            overwrite_agents=False,
        )
        suggestions = "\n".join(result["maintenance_suggestions"])
        self.assertIn("stale-general-rule", suggestions)
        self.assertIn("revalidate", suggestions)
        selection = json.loads((project / ".codex" / "project-rules.selection.json").read_text(encoding="utf-8"))
        accepted = {item["id"]: item for item in selection["accepted"]}
        self.assertGreater(accepted["stale-general-rule"]["freshness"]["validation_age_days"], 365)

    def test_history_decay_penalizes_long_unseen_rule(self) -> None:
        root, project = self._make_case()
        bootstrap_library(root, overwrite=False)
        curated = root / "rule-library" / "curated" / "frontend"
        curated.mkdir(parents=True, exist_ok=True)
        (curated / "fresh-rule.md").write_text(
            "\n".join(
                [
                    "---",
                    "id: fresh-rule",
                    "title: Fresh rule",
                    "tags: [frontend, html]",
                    "project_types: [coding]",
                    "priority: 80",
                    "confidence: 0.9",
                    "layer: domain",
                    "domain_scope: [frontend]",
                    "stability: stable",
                    "conflicts_with: []",
                    "---",
                    "Fresh rule body.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (curated / "stale-history-rule.md").write_text(
            "\n".join(
                [
                    "---",
                    "id: stale-history-rule",
                    "title: Stale history rule",
                    "tags: [frontend, html]",
                    "project_types: [coding]",
                    "priority: 80",
                    "confidence: 0.9",
                    "layer: domain",
                    "domain_scope: [frontend]",
                    "stability: stable",
                    "conflicts_with: []",
                    "---",
                    "Stale history rule body.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        build_catalog(root)

        profile = {
            "name": "demo",
            "project_type": "coding",
            "tags": ["frontend", "html"],
            "context_description": "Frontend project.",
            "force_include": [],
            "exclude_rules": [],
        }
        project_state = {
            "rule_history": {
                "stale-history-rule": {
                    "accepted_total": 3,
                    "accepted_streak": 0,
                    "rejected_total": 0,
                    "rejected_streak": 0,
                    "last_status": "accepted",
                    "last_reason": None,
                    "last_seen_at": "2020-01-01T00:00:00+00:00",
                }
            }
        }
        selection = select_rules(root, profile, limit=6, project_state=project_state)
        scores = {item["id"]: item["score"] for item in selection["accepted"] + selection["rejected"]}
        self.assertGreater(scores["fresh-rule"], scores["stale-history-rule"])

    def test_render_context_hash_ignores_governance_only_changes(self) -> None:
        selection = {
            "metadata": {
                "profile_change_summary": ["Project profile stayed materially the same."],
                "project_activity_summary": ["No file changes detected since last scan."],
                "maintenance_suggestions": ["Rule `x` should be reviewed."],
                "governance": {"accepted_count": 1, "rejected_count": 2},
                "selected_rule_hashes": {"rule-a": "hash-a"},
                "experimental_rule_hashes": {"rule-b": "hash-b"},
            },
            "accepted": [{"id": "rule-a"}],
            "experimental": [{"id": "rule-b"}],
            "rejected": [{"id": "rule-c", "reason": "low_relevance"}],
        }
        first = compute_render_context_hash(selection)
        selection["metadata"]["maintenance_suggestions"] = ["Different suggestion."]
        selection["metadata"]["governance"] = {"accepted_count": 99, "rejected_count": 0}
        selection["rejected"] = [{"id": "rule-z", "reason": "expired_rule"}]
        second = compute_render_context_hash(selection)
        self.assertEqual(first, second)

    def test_usage_logging_reports_root_fallback_reason(self) -> None:
        root, project = self._make_case()
        bootstrap_library(root, overwrite=False)
        import codex_rulekit.core as core

        original_append = core.append_usage_log

        def append_with_root_denied(storage_root: Path, payload: dict[str, object]) -> Path:
            if storage_root == root:
                raise PermissionError("root usage log denied")
            return original_append(storage_root, payload)

        with mock.patch.object(core, "append_usage_log", side_effect=append_with_root_denied):
            result = ensure_project_integration(
                library_root=root,
                project_root=project,
                limit=6,
                generator_version="test",
                overwrite_agents=False,
            )

        self.assertEqual(result["usage_storage_mode"], "memories_fallback")
        self.assertIn("root usage log denied", result["usage_storage_fallback_reason"])
        self.assertEqual(result["usage_storage_skipped"][0]["mode"], "root")
        self.assertTrue((root / "memories" / "codex-rulekit" / "usage-log.jsonl").exists())

    def test_cli_reports_readable_error_when_library_is_missing(self) -> None:
        root, project = self._make_case()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = cli_main(
                [
                    "ensure-project",
                    "--root",
                    str(root),
                    "--project",
                    str(project),
                ]
            )
        self.assertEqual(exit_code, 2)
        message = stderr.getvalue()
        self.assertIn("Run `codex-rulekit bootstrap --root", message)
        self.assertNotIn("Traceback", message)


if __name__ == "__main__":
    unittest.main()
