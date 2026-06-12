import json
import re
import sys
from pathlib import Path


def _has(root, name):
    return (Path(root) / name).exists()


def _js_pm(root):
    """Return the JS package manager to use based on lockfile presence.

    Priority: bun > pnpm > yarn > npm
    bun.lockb or bun.lock -> bun
    pnpm-lock.yaml -> pnpm
    yarn.lock -> yarn
    else -> npm
    """
    root = Path(root)
    if (root / "bun.lockb").exists() or (root / "bun.lock").exists():
        return "bun"
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    return "npm"


def _js_test_cmd(root, pkg):
    """Return the test command for a JS project respecting package manager."""
    if "test" not in pkg.get("scripts", {}):
        return None
    pm = _js_pm(root)
    if pm == "npm":
        return ["npm", "test", "--silent"]
    return [pm, "run", "test"]


def _js_build_cmd(root, pkg):
    """Return the build command for a JS project respecting package manager."""
    if "build" not in pkg.get("scripts", {}):
        return None
    pm = _js_pm(root)
    if pm == "npm":
        return ["npm", "run", "build"]
    return [pm, "run", "build"]


def _gradle_wrapper(root):
    """Return the gradle wrapper executable if present, else None."""
    root = Path(root)
    if sys.platform == "win32":
        # Prefer gradlew.bat on Windows
        bat = root / "gradlew.bat"
        if bat.exists():
            return str(bat)
    unix = root / "gradlew"
    if unix.exists():
        return str(unix)
    return None


def detect_test_cmd(root):
    root = Path(root)

    # 1. package.json (JS/Node)
    if _has(root, "package.json"):
        try:
            pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pkg = {}
        cmd = _js_test_cmd(root, pkg)
        if cmd:
            return cmd

    # 2. Python (pyproject.toml, pytest.ini, tests dir)
    if _has(root, "pyproject.toml") or _has(root, "pytest.ini") or _has(root, "tests"):
        return ["python", "-m", "pytest", "-q"]

    # 3. Rust
    if _has(root, "Cargo.toml"):
        return ["cargo", "test", "-q"]

    # 4. Go
    if _has(root, "go.mod"):
        return ["go", "test", "./..."]

    # 5. Maven
    if _has(root, "pom.xml"):
        return ["mvn", "-q", "test"]

    # 6. Gradle (wrapper preferred over bare gradle)
    if (_has(root, "build.gradle") or _has(root, "build.gradle.kts")
            or _has(root, "gradlew") or _has(root, "gradlew.bat")):
        wrapper = _gradle_wrapper(root)
        if wrapper:
            return [wrapper, "test"]
        return ["gradle", "test"]

    # 7. Dotnet
    sln = list(root.glob("*.sln"))
    csproj = list(root.glob("*.csproj"))
    if sln or csproj:
        return ["dotnet", "test"]

    # 8. Make with test target
    if _has(root, "Makefile"):
        try:
            content = (root / "Makefile").read_text(encoding="utf-8")
            if re.search(r"^test:", content, re.M):
                return ["make", "test"]
        except OSError:
            pass

    # 9. Mix (Elixir)
    if _has(root, "mix.exs"):
        return ["mix", "test"]

    # 10. Composer (PHP) with scripts.test
    if _has(root, "composer.json"):
        try:
            data = json.loads((root / "composer.json").read_text(encoding="utf-8"))
            if "test" in data.get("scripts", {}):
                return ["composer", "test"]
        except (json.JSONDecodeError, OSError):
            pass

    return None


def detect_build_cmd(root):
    root = Path(root)

    # 1. package.json (JS/Node)
    if _has(root, "package.json"):
        try:
            pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pkg = {}
        cmd = _js_build_cmd(root, pkg)
        if cmd:
            return cmd

    # 2. Rust
    if _has(root, "Cargo.toml"):
        return ["cargo", "build", "-q"]

    # 3. Go
    if _has(root, "go.mod"):
        return ["go", "build", "./..."]

    # 4. Maven
    if _has(root, "pom.xml"):
        return ["mvn", "-q", "compile"]

    # 5. Gradle
    if (_has(root, "build.gradle") or _has(root, "build.gradle.kts")
            or _has(root, "gradlew") or _has(root, "gradlew.bat")):
        wrapper = _gradle_wrapper(root)
        if wrapper:
            return [wrapper, "build"]
        return ["gradle", "build"]

    # 6. Dotnet
    sln = list(root.glob("*.sln"))
    csproj = list(root.glob("*.csproj"))
    if sln or csproj:
        return ["dotnet", "build"]

    return None
