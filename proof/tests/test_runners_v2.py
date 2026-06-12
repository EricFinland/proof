"""Tests for extended runner detection (Task 7.3)."""
import json
from pathlib import Path
import pytest
from proofkit.runners import detect_test_cmd, detect_build_cmd, _js_pm


# ---------------------------------------------------------------------------
# JS package manager resolution
# ---------------------------------------------------------------------------

def test_js_pm_bun_lockb(tmp_path):
    (tmp_path / "bun.lockb").write_bytes(b"")
    assert _js_pm(tmp_path) == "bun"


def test_js_pm_bun_lock(tmp_path):
    (tmp_path / "bun.lock").write_text("", encoding="utf-8")
    assert _js_pm(tmp_path) == "bun"


def test_js_pm_pnpm(tmp_path):
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    assert _js_pm(tmp_path) == "pnpm"


def test_js_pm_yarn(tmp_path):
    (tmp_path / "yarn.lock").write_text("", encoding="utf-8")
    assert _js_pm(tmp_path) == "yarn"


def test_js_pm_default_npm(tmp_path):
    assert _js_pm(tmp_path) == "npm"


def test_js_pm_bun_wins_over_yarn(tmp_path):
    """bun.lockb + yarn.lock present: bun wins."""
    (tmp_path / "bun.lockb").write_bytes(b"")
    (tmp_path / "yarn.lock").write_text("", encoding="utf-8")
    assert _js_pm(tmp_path) == "bun"


def test_js_pm_pnpm_wins_over_yarn(tmp_path):
    """pnpm-lock.yaml + yarn.lock present: pnpm wins."""
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    (tmp_path / "yarn.lock").write_text("", encoding="utf-8")
    assert _js_pm(tmp_path) == "pnpm"


# ---------------------------------------------------------------------------
# JS test/build commands use package manager
# ---------------------------------------------------------------------------

def test_npm_test_command_unchanged(tmp_path):
    """npm still uses legacy form: npm test --silent."""
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "jest"}}), encoding="utf-8"
    )
    cmd = detect_test_cmd(tmp_path)
    assert cmd == ["npm", "test", "--silent"]


def test_bun_test_command(tmp_path):
    """bun lockfile -> bun run test."""
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "jest"}}), encoding="utf-8"
    )
    (tmp_path / "bun.lockb").write_bytes(b"")
    cmd = detect_test_cmd(tmp_path)
    assert cmd == ["bun", "run", "test"]


def test_pnpm_build_command(tmp_path):
    """pnpm lockfile -> pnpm run build."""
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "jest", "build": "tsc"}}), encoding="utf-8"
    )
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    cmd = detect_build_cmd(tmp_path)
    assert cmd == ["pnpm", "run", "build"]


def test_yarn_test_command(tmp_path):
    """yarn lockfile -> yarn run test."""
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "jest"}}), encoding="utf-8"
    )
    (tmp_path / "yarn.lock").write_text("", encoding="utf-8")
    cmd = detect_test_cmd(tmp_path)
    assert cmd == ["yarn", "run", "test"]


# ---------------------------------------------------------------------------
# Maven
# ---------------------------------------------------------------------------

def test_maven_test_cmd(tmp_path):
    (tmp_path / "pom.xml").write_text("<project/>", encoding="utf-8")
    assert detect_test_cmd(tmp_path) == ["mvn", "-q", "test"]


def test_maven_build_cmd(tmp_path):
    (tmp_path / "pom.xml").write_text("<project/>", encoding="utf-8")
    assert detect_build_cmd(tmp_path) == ["mvn", "-q", "compile"]


# ---------------------------------------------------------------------------
# Gradle
# ---------------------------------------------------------------------------

def test_gradle_wrapper_bat_test_cmd(tmp_path):
    """On Windows: gradlew.bat is preferred wrapper."""
    (tmp_path / "gradlew.bat").write_text("@echo off", encoding="utf-8")
    (tmp_path / "build.gradle").write_text("", encoding="utf-8")
    cmd = detect_test_cmd(tmp_path)
    assert cmd[0].endswith("gradlew.bat") or cmd[0] == "gradlew.bat"
    assert cmd[1:] == ["test"]


def test_gradle_wrapper_unix_test_cmd(tmp_path):
    """gradlew (unix) wrapper -> ['gradlew', 'test']."""
    (tmp_path / "gradlew").write_text("#!/bin/sh", encoding="utf-8")
    (tmp_path / "build.gradle").write_text("", encoding="utf-8")
    cmd = detect_test_cmd(tmp_path)
    assert cmd[0].endswith("gradlew") and not cmd[0].endswith(".bat")
    assert cmd[1:] == ["test"]


def test_gradle_bare_test_cmd(tmp_path):
    """No wrapper, build.gradle only -> ['gradle', 'test']."""
    (tmp_path / "build.gradle").write_text("", encoding="utf-8")
    assert detect_test_cmd(tmp_path) == ["gradle", "test"]


def test_gradle_kts_test_cmd(tmp_path):
    (tmp_path / "build.gradle.kts").write_text("", encoding="utf-8")
    assert detect_test_cmd(tmp_path) == ["gradle", "test"]


# ---------------------------------------------------------------------------
# Dotnet
# ---------------------------------------------------------------------------

def test_dotnet_sln_test_cmd(tmp_path):
    (tmp_path / "App.sln").write_text("", encoding="utf-8")
    assert detect_test_cmd(tmp_path) == ["dotnet", "test"]


def test_dotnet_csproj_test_cmd(tmp_path):
    (tmp_path / "App.csproj").write_text("", encoding="utf-8")
    assert detect_test_cmd(tmp_path) == ["dotnet", "test"]


def test_dotnet_build_cmd(tmp_path):
    (tmp_path / "App.sln").write_text("", encoding="utf-8")
    assert detect_build_cmd(tmp_path) == ["dotnet", "build"]


# ---------------------------------------------------------------------------
# Make
# ---------------------------------------------------------------------------

def test_make_with_test_target(tmp_path):
    (tmp_path / "Makefile").write_text("test:\n\tpython -m pytest\n", encoding="utf-8")
    assert detect_test_cmd(tmp_path) == ["make", "test"]


def test_make_without_test_target_falls_through(tmp_path):
    (tmp_path / "Makefile").write_text("build:\n\tmake all\n", encoding="utf-8")
    assert detect_test_cmd(tmp_path) is None


# ---------------------------------------------------------------------------
# Mix (Elixir)
# ---------------------------------------------------------------------------

def test_mix_test_cmd(tmp_path):
    (tmp_path / "mix.exs").write_text("defmodule App do end\n", encoding="utf-8")
    assert detect_test_cmd(tmp_path) == ["mix", "test"]


# ---------------------------------------------------------------------------
# Composer (PHP)
# ---------------------------------------------------------------------------

def test_composer_with_test_script(tmp_path):
    data = {"scripts": {"test": "phpunit"}}
    (tmp_path / "composer.json").write_text(json.dumps(data), encoding="utf-8")
    assert detect_test_cmd(tmp_path) == ["composer", "test"]


def test_composer_without_test_script_falls_through(tmp_path):
    data = {"scripts": {"lint": "phpcs"}}
    (tmp_path / "composer.json").write_text(json.dumps(data), encoding="utf-8")
    assert detect_test_cmd(tmp_path) is None


# ---------------------------------------------------------------------------
# Existing detections still work (regression)
# ---------------------------------------------------------------------------

def test_existing_cargo_still_works(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]\n", encoding="utf-8")
    assert detect_test_cmd(tmp_path) == ["cargo", "test", "-q"]


def test_existing_go_still_works(tmp_path):
    (tmp_path / "go.mod").write_text("module app\n", encoding="utf-8")
    assert detect_test_cmd(tmp_path) == ["go", "test", "./..."]


def test_existing_pytest_still_works(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    assert detect_test_cmd(tmp_path)[0] in ("python", "pytest")
