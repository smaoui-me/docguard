"""Audit release payloads and write checksums; never extract untrusted archives."""

import argparse
import hashlib
import tarfile
import zipfile
from pathlib import Path, PurePosixPath


def check_path(name: str) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError(f"Unsafe archive path: {name}")
    if any(part.startswith((".env", ".git", ".docguard")) for part in path.parts):
        raise ValueError(f"Private/local file in distribution: {name}")


def audit(directory: Path) -> None:
    wheels = list(directory.glob("*.whl"))
    sources = list(directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise ValueError("Expected exactly one wheel and one source distribution")
    with zipfile.ZipFile(wheels[0]) as archive:
        names = archive.namelist()
        for name in names:
            check_path(name)
            top = PurePosixPath(name).parts[0]
            if top != "docguard" and not top.endswith(".dist-info"):
                raise ValueError(f"Unexpected wheel payload: {name}")
            if top == "docguard" and not name.endswith(".py"):
                raise ValueError(f"Unexpected package data: {name}")
        if "docguard/cli.py" not in names:
            raise ValueError("Wheel is missing the CLI")
    with tarfile.open(sources[0]) as archive:
        for member in archive.getmembers():
            check_path(member.name)
            if not member.isfile() and not member.isdir():
                raise ValueError(f"Unsupported archive entry: {member.name}")
            path = PurePosixPath(member.name)
            if len(path.parts) > 1 and path.parts[1] not in {
                "src",
                "examples",
                "README.md",
                "pyproject.toml",
                "MANIFEST.in",
                "PKG-INFO",
                "setup.cfg",
                "LICENSE",
                "LICENSE.md",
                "LICENSE.txt",
            }:
                raise ValueError(f"Unexpected source payload: {member.name}")
    checksums = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        for path in sorted(wheels + sources)
    )
    (directory / "SHA256SUMS").write_text(checksums, encoding="ascii")
    print("PASS: distribution payload audit; wrote SHA256SUMS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    audit(parser.parse_args().directory)
