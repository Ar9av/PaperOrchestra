from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from gui_app import storage


class NativeLauncherScriptsTests(unittest.TestCase):
    def test_build_native_launcher_help_exits_cleanly(self) -> None:
        completed = subprocess.run(
            ["/bin/bash", "scripts/build_native_launcher.sh", "--help"],
            cwd=storage.REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Build the native PaperOrchestra macOS launcher app bundle", completed.stdout)

    def test_install_native_launcher_help_exits_cleanly(self) -> None:
        completed = subprocess.run(
            ["/bin/bash", "scripts/install_native_launcher.sh", "--help"],
            cwd=storage.REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Install PaperOrchestra.app into /Applications by default", completed.stdout)

    def test_codex_run_button_targets_build_and_run_script(self) -> None:
        environment_file = storage.REPO_ROOT / ".codex" / "environments" / "environment.toml"
        self.assertTrue(environment_file.exists())
        content = environment_file.read_text(encoding="utf-8")
        self.assertIn('command = "./script/build_and_run.sh"', content)

    def test_native_launcher_swift_tests_pass(self) -> None:
        completed = subprocess.run(
            ["swift", "test"],
            cwd=storage.REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Test run", completed.stdout + completed.stderr)

    def test_launcher_uses_appearance_aware_icon_catalog(self) -> None:
        build_script = (storage.REPO_ROOT / "scripts" / "build.sh").read_text(encoding="utf-8")
        icon_manifest = (
            storage.REPO_ROOT
            / "Sources"
            / "PaperOrchestraLauncherApp"
            / "Resources"
            / "AppIcon.icon"
            / "icon.json"
        ).read_text(encoding="utf-8")

        self.assertIn('CONFIGURATION="${CONFIGURATION:-Release}"', build_script)
        self.assertIn('"appearance" : "dark"', icon_manifest)
        self.assertIn('"PaperOrchestra-Dark.png"', icon_manifest)


class NativeLauncherReadmeTests(unittest.TestCase):
    def test_readme_mentions_native_launcher_app(self) -> None:
        readme = (storage.REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("PaperOrchestra.app", readme)
        self.assertIn("scripts/install_native_launcher.sh", readme)

    def test_repo_contains_package_manifest(self) -> None:
        self.assertTrue((storage.REPO_ROOT / "Package.swift").exists())

    def test_native_launcher_includes_design_system_files(self) -> None:
        app_root = storage.REPO_ROOT / "Sources" / "PaperOrchestraLauncherApp"
        expected = [
            app_root / "AppDesignSystem" / "DesignTokens.swift",
            app_root / "AppDesignSystem" / "Typography.swift",
            app_root / "AppDesignSystem" / "SemanticColors.swift",
            app_root / "AppDesignSystem" / "Surfaces.swift",
            app_root / "AppDesignSystem" / "Motion.swift",
            app_root / "AppDesignSystem" / "Buttons.swift",
            app_root / "AppDesignSystem" / "Cards.swift",
            app_root / "AppDesignSystem" / "EmptyLoadingErrorStates.swift",
        ]

        missing = [str(path.relative_to(storage.REPO_ROOT)) for path in expected if not path.exists()]
        self.assertEqual(missing, [], f"Missing design-system files: {missing}")

    def test_native_launcher_includes_icon_composer_source(self) -> None:
        icon_source = storage.REPO_ROOT / "Sources" / "PaperOrchestraLauncherApp" / "Resources" / "AppIcon.icon" / "icon.json"
        self.assertTrue(icon_source.exists())
        content = icon_source.read_text(encoding="utf-8")
        self.assertIn('"image-name-specializations"', content)
        self.assertIn('"appearance" : "dark"', content)
        self.assertIn('"PaperOrchestra-Dark.png"', content)
