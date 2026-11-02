from mcp_server import server


def test_rejects_wrong_token():
    assert "unauthorized" in server.write_reservation("Ann Lee", "AB-123", "2026-11-05", "wrong")


def test_writes_line(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "FILE", str(tmp_path / "r.txt"))
    monkeypatch.setattr(server, "SECRET", "s")
    assert server.write_reservation("Ann Lee", "AB-123", "2026-11-05", "s").startswith("OK")
    assert "Ann Lee | AB-123" in (tmp_path / "r.txt").read_text()


def test_rejects_bad_car_number(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "FILE", str(tmp_path / "r.txt"))
    monkeypatch.setattr(server, "SECRET", "s")
    assert "invalid" in server.write_reservation("Ann", "AB|1; DROP", "x", "s")