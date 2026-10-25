"""Build the two Lambda code bundles (no Docker needed). Called by app.py at synth time.

    build/lambda/core   warranty_kg + functions + competency queries + ontology   (no dependencies)
    build/lambda/rdf    the same, plus rdflib and pySHACL installed for Linux arm64 / Python 3.13

The rdf bundle's dependencies are pure-Python wheels, downloaded once and cached: the bundle is
rebuilt only when functions/rdf_tools/requirements.txt changes. Source files are re-copied on
every synth so code changes always deploy.

    python scripts/build_assets.py          # build both
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build" / "lambda"
REQUIREMENTS = ROOT / "functions" / "rdf_tools" / "requirements.txt"
SOURCES = ("warranty_kg", "functions", "queries", "ontology")
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")


def _copy_sources(dest: Path) -> None:
    for name in SOURCES:
        target = dest / name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(ROOT / name, target, ignore=IGNORE)


def _install_deps(dest: Path) -> None:
    digest = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    marker = dest / ".requirements.sha256"
    if marker.exists() and marker.read_text() == digest:
        return
    for child in dest.iterdir() if dest.exists() else []:
        if child.name not in SOURCES:
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                    "--target", str(dest), "--platform", "manylinux2014_aarch64",
                    "--implementation", "cp", "--python-version", "3.13",
                    "--only-binary=:all:", "--upgrade", "-r", str(REQUIREMENTS)], check=True)
    marker.write_text(digest)


def build() -> dict[str, Path]:
    core, rdf = BUILD / "core", BUILD / "rdf"
    core.mkdir(parents=True, exist_ok=True)
    _copy_sources(core)
    _install_deps(rdf)
    _copy_sources(rdf)
    return {"core": core, "rdf": rdf}


if __name__ == "__main__":
    for name, path in build().items():
        print(f"{name}: {path}")
