from src.booking import parse_period, overlaps, find_conflict


def test_parse_valid_period():
    assert parse_period("2026-11-05 from 09:00 to 18:00") is not None


def test_parse_rejects_end_before_start():
    assert parse_period("2026-11-05 from 18:00 to 09:00") is None


def test_overlapping_same_car_is_conflict(tmp_path):
    f = tmp_path / "r.txt"
    f.write_text("Ann Lee | AB-1234 | 2026-11-05 from 09:00 to 12:00 | 2026-11-01T10:00:00\n")
    assert find_conflict("ab 1234", "2026-11-05 from 10:00 to 13:00", str(f)) is not None


def test_back_to_back_is_allowed(tmp_path):
    f = tmp_path / "r.txt"
    f.write_text("Ann Lee | AB-1234 | 2026-11-05 from 09:00 to 12:00 | 2026-11-01T10:00:00\n")
    assert find_conflict("AB-1234", "2026-11-05 from 12:00 to 15:00", str(f)) is None


def test_different_car_is_allowed(tmp_path):
    f = tmp_path / "r.txt"
    f.write_text("Ann Lee | AB-1234 | 2026-11-05 from 09:00 to 12:00 | 2026-11-01T10:00:00\n")
    assert find_conflict("CD-9999", "2026-11-05 from 10:00 to 13:00", str(f)) is None