import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from docguard.code.index import index_repository
from docguard.code.python_parser import _parse_source


class TestRepositoryIndex(unittest.TestCase):
    def test_multifile_index_is_portable_and_deterministic(self):
        with TemporaryDirectory() as directory:
            snapshots = []
            for name in ("first", "second"):
                root = Path(directory) / name
                (root / "src").mkdir(parents=True)
                (root / "src/client.py").write_text(
                    "class Client:\n    async def fetch(self): pass\n",
                    encoding="utf-8",
                )
                (root / "helpers.py").write_text(
                    "def f(): pass\ndef f(): pass\n",
                    encoding="utf-8",
                )
                (root / ".venv").mkdir()
                (root / ".venv/bad.py").write_text("invalid python !", encoding="utf-8")
                snapshots.append(index_repository(root))
                self.assertEqual(snapshots[-1], index_repository(root))
            self.assertEqual(snapshots[0], snapshots[1])
            self.assertEqual(
                list(snapshots[0]),
                [
                    "helpers.py:f",
                    "helpers.py:f#2",
                    "src/client.py:Client",
                    "src/client.py:Client.fetch",
                ],
            )

    def test_empty_repository(self):
        with TemporaryDirectory() as directory:
            self.assertEqual(index_repository(Path(directory)), {})

    def test_parse_error_propagates_after_a_valid_file(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.py").write_text("def valid(): pass\n", encoding="utf-8")
            (root / "z.py").write_text("def invalid(:", encoding="utf-8")
            with self.assertRaises(SyntaxError) as raised:
                index_repository(root)
            self.assertEqual(raised.exception.filename, "z.py")

    def test_invalid_roots(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(FileNotFoundError):
                index_repository(root / "missing")
            file = root / "file.py"
            file.touch()
            with self.assertRaises(NotADirectoryError):
                index_repository(file)

    def test_unexpected_duplicate_ids_do_not_silently_overwrite(self):
        entity = _parse_source("def f(): pass", "module.py")[0]
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch(
                    "docguard.code.index.discover_python_files",
                    return_value=[root / "module.py"],
                ),
                patch(
                    "docguard.code.index.parse_python_file",
                    return_value=[entity, entity],
                ),
                self.assertRaisesRegex(ValueError, "Duplicate entity ID"),
            ):
                index_repository(root)
