"""Checksum utilities (§50)."""

import hashlib

from app.modules.storage.checksum import md5_file, sha256_file


def test_sha256_matches_hashlib(tmp_path) -> None:
    payload = b"hello clipforge " * 1000
    path = tmp_path / "sample.bin"
    path.write_bytes(payload)

    expected = hashlib.sha256(payload).hexdigest()
    assert sha256_file(path) == expected


def test_md5_matches_hashlib(tmp_path) -> None:
    payload = b"checksum me"
    path = tmp_path / "sample.bin"
    path.write_bytes(payload)

    expected = hashlib.md5(payload).hexdigest()
    assert md5_file(path) == expected


def test_empty_file(tmp_path) -> None:
    path = tmp_path / "empty.bin"
    path.write_bytes(b"")
    assert sha256_file(path) == hashlib.sha256(b"").hexdigest()
    assert md5_file(path) == hashlib.md5(b"").hexdigest()
