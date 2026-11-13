import pytest
from pydantic import ValidationError

from georing.settings import Settings, load_dotenv


def test_the_satellite_set_names_known_positions_once(monkeypatch):
    monkeypatch.setenv("GEORING_SATELLITE_SET", '["goes-east", "himawari"]')
    assert Settings().satellite_set == ["goes-east", "himawari"]
    monkeypatch.setenv("GEORING_SATELLITE_SET", '["goes-east", "meteo"]')
    with pytest.raises(ValidationError, match="no such position: meteo"):
        Settings()
    monkeypatch.setenv("GEORING_SATELLITE_SET", '["goes-east", "goes-east"]')
    with pytest.raises(ValidationError, match="named twice"):
        Settings()


def test_dotenv_reads_values_and_skips_comments(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# a comment\nEUMETSAT_CONSUMER_KEY=abc\nEUMETSAT_CONSUMER_SECRET='x=y'\n\n")
    assert load_dotenv(env) == {"EUMETSAT_CONSUMER_KEY": "abc", "EUMETSAT_CONSUMER_SECRET": "x=y"}
    assert load_dotenv(tmp_path / "missing") == {}
