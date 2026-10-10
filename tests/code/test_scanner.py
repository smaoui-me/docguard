import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from docguard.code.python_parser import parse_python_file
from docguard.code.scanner import discover_python_files


class TestRepositoryScanner(unittest.TestCase):
    def test_discovers_sorted_python_files_and_excludes_environment_directories(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (
                "z.py",
                "src/a.py",
                "tests/test_a.py",
                "README.md",
                ".venv/lib/ignored.py",
                "venv/ignored.py",
                ".git/ignored.py",
                "src/__pycache__/ignored.py",
                ".mypy_cache/ignored.py",
                ".pytest_cache/ignored.py",
                ".ruff_cache/ignored.py",
            ):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")

            first = discover_python_files(root)

            self.assertEqual(
                first, [root / "src/a.py", root / "tests/test_a.py", root / "z.py"]
            )
            self.assertEqual(first, discover_python_files(root))

    def test_empty_directory(self):
        with TemporaryDirectory() as directory:
            self.assertEqual(discover_python_files(Path(directory)), [])

    def test_invalid_roots_raise_explicit_errors(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(FileNotFoundError):
                discover_python_files(root / "missing")
            file = root / "module.py"
            file.touch()
            with self.assertRaises(NotADirectoryError):
                discover_python_files(file)

    def test_discovered_files_can_be_parsed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "client.py").write_text(
                "class Client:\n    def connect(self):\n        pass\n",
                encoding="utf-8",
            )
            (root / "helpers.py").write_text(
                "def greet():\n    pass\n", encoding="utf-8"
            )

            entities = [
                entity
                for path in discover_python_files(root)
                for entity in parse_python_file(path)
            ]

            self.assertEqual(
                [entity.qualified_name for entity in entities],
                [
                    "Client",
                    "Client.connect",
                    "greet",
                ],
            )

    def test_skips_symbolic_links(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()
            (target / "module.py").touch()
            try:
                (root / "linked.py").symlink_to(target / "module.py")
                (root / "linked_directory").symlink_to(target, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"Symbolic links unavailable: {error}")

            self.assertEqual(discover_python_files(root), [target / "module.py"])
