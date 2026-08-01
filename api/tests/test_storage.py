from pathlib import Path

from app.services import storage


class FakeSettings:
    def __init__(self, upload_dir: Path) -> None:
        self.resolved_upload_dir = upload_dir


class FakeResponse:
    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self):
        yield b"%PDF"


def test_save_remote_pdf_follows_redirects(monkeypatch, tmp_path) -> None:
    calls = []

    def fake_stream(method: str, url: str, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr(storage, "settings", FakeSettings(tmp_path))
    monkeypatch.setattr(storage.httpx, "stream", fake_stream)

    saved_path = storage.save_remote_pdf("https://arxiv.org/pdf/2606.05868v1.pdf", "paper.pdf")

    assert Path(saved_path).read_bytes() == b"%PDF"
    assert calls[0]["follow_redirects"] is True
