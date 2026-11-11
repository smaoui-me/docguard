import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "distribution_audit", Path("examples/check_distributions.py")
)
audit_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_module)


def distributions(root, extra_wheel=None, tar_link=False):
    with zipfile.ZipFile(root / "docguard-0.1.0-py3-none-any.whl", "w") as wheel:
        wheel.writestr("docguard/cli.py", "# installed code")
        wheel.writestr("docguard-0.1.0.dist-info/METADATA", "Version: 0.1.0")
        if extra_wheel:
            wheel.writestr(extra_wheel, "must not ship")
    with tarfile.open(root / "docguard-0.1.0.tar.gz", "w:gz") as source:
        item = tarfile.TarInfo("docguard-0.1.0/README.md")
        if tar_link:
            item.type = tarfile.SYMTYPE
            item.linkname = "../../outside"
            source.addfile(item)
        else:
            item.size = 4
            source.addfile(item, io.BytesIO(b"demo"))


def test_valid_payload_checksums(tmp_path):
    distributions(tmp_path)
    audit_module.audit(tmp_path)
    rows = (tmp_path / "SHA256SUMS").read_text().splitlines()
    assert len(rows) == 2
    assert all(len(row.split()[0]) == 64 for row in rows)


@pytest.mark.parametrize(
    "path",
    [
        "docguard/.env",
        "../escape.py",
        "/absolute.py",
        "tests/test.py",
        "docguard/key.pem",
    ],
)
def test_reject_private_or_unexpected_wheel_payload(tmp_path, path):
    distributions(tmp_path, extra_wheel=path)
    with pytest.raises(ValueError):
        audit_module.audit(tmp_path)
    assert not (tmp_path / "SHA256SUMS").exists()


def test_reject_source_symlink(tmp_path):
    distributions(tmp_path, tar_link=True)
    with pytest.raises(ValueError, match="Unsupported archive"):
        audit_module.audit(tmp_path)


def test_reject_missing_distributions(tmp_path):
    with pytest.raises(ValueError, match="exactly one"):
        audit_module.audit(tmp_path)
