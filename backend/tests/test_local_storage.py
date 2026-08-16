"""LocalStorageProvider round-trip + path-traversal protection."""

import pytest

from app.modules.storage.errors import StorageError
from app.providers.storage.local import LocalStorageProvider


@pytest.fixture
def provider(tmp_path) -> LocalStorageProvider:
    return LocalStorageProvider(str(tmp_path))


def test_upload_list_download(provider, tmp_path) -> None:
    source = tmp_path / "video.mp4"
    source.write_bytes(b"0123456789" * 100)

    remote = provider.upload(str(source), "01_Inbox/video.mp4", mime_type="video/mp4")
    assert remote.filename == "video.mp4"
    assert remote.size == 1000

    files = provider.list_files("01_Inbox")
    assert [f.filename for f in files] == ["video.mp4"]

    dest = tmp_path / "out" / "copy.mp4"
    provider.download("01_Inbox/video.mp4", str(dest))
    assert dest.read_bytes() == source.read_bytes()


def test_move_and_delete(provider, tmp_path) -> None:
    source = tmp_path / "a.mp4"
    source.write_bytes(b"data")
    provider.upload(str(source), "01_Inbox/a.mp4")

    provider.move("01_Inbox/a.mp4", "06_Archive/a.mp4")
    assert provider.list_files("01_Inbox") == []
    assert [f.filename for f in provider.list_files("06_Archive")] == ["a.mp4"]

    provider.delete("06_Archive/a.mp4")
    assert provider.list_files("06_Archive") == []


def test_create_folder_idempotent(provider) -> None:
    path = provider.create_folder("03_Projects/My_Project")
    assert provider.create_folder("03_Projects/My_Project") == path


def test_path_traversal_rejected(provider, tmp_path) -> None:
    source = tmp_path / "x.txt"
    source.write_bytes(b"x")
    with pytest.raises(StorageError):
        provider.upload(str(source), "../../escape.txt")
