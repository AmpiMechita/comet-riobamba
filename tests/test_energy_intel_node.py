# -*- coding: utf-8 -*-
"""Tests for docs/ein/energy_intel_node.py — DB_PATH resolution and ingest."""

import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _add_ein_to_path():
    """Ensure docs/ein/ is importable during tests."""
    ein_path = str(Path(__file__).resolve().parents[1] / "docs" / "ein")
    sys.path.insert(0, ein_path)
    yield
    # Cleanup not needed — tests run in isolated processes


def test_db_path_is_absolute():
    """DB_PATH must be an absolute path, not relative."""
    import energy_intel_node
    path = Path(energy_intel_node.DB_PATH)
    assert path.is_absolute(), f"DB_PATH is not absolute: {path}"


def test_db_path_ends_with_correct_location():
    """DB_PATH must resolve to data/energy_intel.db."""
    import energy_intel_node
    path = Path(energy_intel_node.DB_PATH)
    assert path.name == "energy_intel.db"
    assert path.parent.name == "data"


def test_db_path_independent_of_cwd(tmp_path):
    """DB_PATH must be the same regardless of the current working directory."""
    # Import the module with the original cwd
    import energy_intel_node
    original_path = energy_intel_node.DB_PATH

    # Change to a temp directory and re-import (force reload)
    old_cwd = os.getcwd()
    try:
        os.chdir(str(tmp_path))
        import importlib
        importlib.reload(energy_intel_node)
        new_path = energy_intel_node.DB_PATH
    finally:
        os.chdir(old_cwd)

    assert original_path == new_path, (
        f"DB_PATH changed with cwd:\n  original={original_path}\n  new={new_path}"
    )


def test_db_path_matches_orchestrator_energy_knowledge_base():
    """DB_PATH must point to the same file that EnergyKnowledgeBase uses."""
    import energy_intel_node
    from pathlib import Path as PathCls
    from config import BASE_DIR

    ein_path = Path(energy_intel_node.DB_PATH).resolve()
    kb_path = (BASE_DIR / "data" / "energy_intel.db").resolve()
    assert ein_path == kb_path, (
        f"DB_PATH mismatch:\n  ein={ein_path}\n  kb={kb_path}"
    )


def test_module_exports_run_ingest():
    """The module must export run_ingest function."""
    import energy_intel_node
    assert hasattr(energy_intel_node, "run_ingest")
    assert callable(energy_intel_node.run_ingest)


# ── Mejoras P1/P2: query refinada, keywords, metricas, USPTO ───────

def test_default_arxiv_query_targets_applied_categories():
    """La query por defecto debe restringir a categorias aplicadas + terminos de
    energia (antes 'all:renewable energy AND cat:physics*' traia 80% ruido)."""
    import energy_intel_node
    q = energy_intel_node.DEFAULT_QUERY
    assert "cat:physics.app-ph" in q
    assert "cat:cond-mat.mtrl-sci" in q
    assert "all:battery" in q
    assert "all:\"solar cell\"" in q
    assert "all:renewable energy AND cat:physics*" not in q


def test_scrape_arxiv_uses_refined_default_query():
    """scrape_arxiv() sin argumento usa la query refinada."""
    import energy_intel_node
    assert energy_intel_node.scrape_arxiv.__defaults__[0] == energy_intel_node.DEFAULT_QUERY


@pytest.mark.parametrize("text,expected", [
    ("solid electrolyte sulfide-based battery", "solid-state-battery"),
    ("prussian blue sodium battery cathode", "sodium-ion"),
    ("alkaline water electrolysis for hydrogen", "green-hydrogen"),
    ("anion exchange membrane electrolyzer", "green-hydrogen"),
    ("tokamak fusion plasma stability", "fusion"),
    ("agri-voltaic dual use solar farming", "agrivoltaics"),
    ("thermophotovoltaic TPV waste heat recovery", "thermophotovoltaic"),
    ("vanadium redox flow battery", "flow-battery"),
])
def test_classify_technology_real_corpus_vocabulary(text, expected):
    """Keywords ampliadas: el vocabulario real de papers del corpus clasifica."""
    import energy_intel_node
    assert energy_intel_node.classify_technology(text) == expected


@pytest.mark.parametrize("text,name,value,unit", [
    ("energy density of 165 Wh kg-1", "energy_density", 165.0, "Wh/kg"),
    ("165 Wh/kg with long cycling", "energy_density", 165.0, "Wh/kg"),
    ("capacity of 1100 mAh g−1", "specific_capacity", 1100.0, "mAh/g"),
    ("achieved efficiency of 28.9%", "efficiency", 28.9, "%"),
    ("28.9% power conversion efficiency", "efficiency", 28.9, "%"),
    ("retains 88% after 500 cycles", "capacity_retention", 88.0, "%"),
    ("cost of 45 cents/kWh", "cost", 45.0, "cents/kWh"),
    ("ran for 1200 cycles", "cycle_life", 1200.0, "cycles"),
])
def test_extract_metrics_real_corpus_patterns(text, name, value, unit):
    """Patrones de metricas ampliados: unidades reales del corpus (Wh kg-1,
    mAh g-1, 'efficiency of X%', cents/kWh, retention)."""
    import energy_intel_node
    m = energy_intel_node.extract_metrics(text)
    assert m.get("metric_name") == name, f"esperaba {name}, got {m}"
    assert m.get("metric_value") == value
    assert m.get("metric_unit") == unit


def test_extract_metrics_no_false_positive_on_generic_text():
    """Texto sin unidades reconocidas no produce metrica (evita metricas inventadas)."""
    import energy_intel_node
    assert energy_intel_node.extract_metrics(
        "the battery showed exceptional stability over long durations") == {}


def test_uspto_skips_without_api_key():
    """Sin USPTO_API_KEY el scraper no llama a la red y devuelve [] (la API
    legacy migro al Open Data Portal; antes fallaba en silencio)."""
    import energy_intel_node
    import os
    old = os.environ.get("USPTO_API_KEY")
    os.environ.pop("USPTO_API_KEY", None)
    try:
        with patch("requests.post") as mock_post:
            assert energy_intel_node.scrape_uspto() == []
            mock_post.assert_not_called()
    finally:
        if old:
            os.environ["USPTO_API_KEY"] = old


# ── EPO OPS (patentes sin SSN) ────────────────────────────────────

_SEARCH_SAMPLE = {
    "ops:world-patent-data": {
        "ops:query-result": {
            "ops:search-result": {
                "ops:publication-reference": [
                    {
                        "ops:document-id": [
                            {"@document-id-type": "docdb", "ops:country": "US", "ops:doc-number": "12345678", "ops:kind": "B2"},
                            {"@document-id-type": "epodoc", "ops:doc-number": "US12345678B2"},
                        ]
                    },
                    {
                        "ops:document-id": [
                            {"@document-id-type": "epodoc", "ops:doc-number": "EP4000001A1"},
                        ]
                    },
                    {
                        "ops:document-id": [
                            {"@document-id-type": "docdb", "ops:country": "EP", "ops:doc-number": "3999999", "ops:kind": "A1"},
                        ]
                    },
                ]
            }
        }
    }
}

_BIBLIO_SAMPLE = {
    "ops:world-patent-data": {
        "ops:document-instance": {
            "ops:exchange-document": {
                "ops:bibliographic-data": {
                    "ops:publication-reference": {
                        "ops:document-id": [
                            {"@document-id-type": "docdb", "ops:country": "US",
                             "ops:doc-number": "12345678", "ops:kind": "B2",
                             "ops:publication-date": {"$": "20250915"}}
                        ]
                    },
                    "ops:invention-title": {"@value": "Solid state battery with sulfide electrolyte"},
                    "ops:abstract": {
                        "@lang": "en",
                        "ops:abstract-text": {"$": "A solid state battery achieving 165 Wh/kg with sulfide electrolyte."},
                    },
                }
            }
        }
    }
}


def test_parse_epo_search_response_extracts_epodoc_numbers():
    """Solo los document-id tipo epodoc salen del search (los docdb no tienen doc-number util)."""
    import energy_intel_node
    refs = energy_intel_node._parse_epo_search_response(_SEARCH_SAMPLE)
    assert refs == ["US12345678B2", "EP4000001A1"]


def test_parse_epo_biblio_response_extracts_fields():
    """Del biblio salen titulo, fecha (normalizada) y abstract."""
    import energy_intel_node
    b = energy_intel_node._parse_epo_biblio_response(_BIBLIO_SAMPLE)
    assert b["title"] == "Solid state battery with sulfide electrolyte"
    assert b["date"] == "2025-09-15"
    assert "165 Wh/kg" in b["abstract"]


def test_parse_epo_responses_malformed_return_empty():
    """Respuestas malformadas no lanzan — devuelven vacio (error-safe)."""
    import energy_intel_node
    assert energy_intel_node._parse_epo_search_response({}) == []
    assert energy_intel_node._parse_epo_biblio_response({}) == {}


def test_epo_ops_skips_without_credentials():
    """Sin EPO_CONSUMER_KEY/SECRET el scraper no llama a la red."""
    import energy_intel_node
    import os
    old_key = os.environ.get("EPO_CONSUMER_KEY")
    old_secret = os.environ.get("EPO_CONSUMER_SECRET")
    os.environ.pop("EPO_CONSUMER_KEY", None)
    os.environ.pop("EPO_CONSUMER_SECRET", None)
    try:
        with patch("requests.post") as mock_post:
            assert energy_intel_node.scrape_epo_ops() == []
            mock_post.assert_not_called()
    finally:
        if old_key:
            os.environ["EPO_CONSUMER_KEY"] = old_key
        if old_secret:
            os.environ["EPO_CONSUMER_SECRET"] = old_secret


def test_epo_ops_ingests_patents_with_credentials(monkeypatch):
    """Con credenciales, search+biblio producen claims de patente clasificados."""
    import energy_intel_node as ein
    monkeypatch.setenv("EPO_CONSUMER_KEY", "k")
    monkeypatch.setenv("EPO_CONSUMER_SECRET", "s")
    ein._EPO_TOKEN_CACHE.update({"token": "tok", "expires_at": time.time() + 600})
    token_body = {
        "ops:world-patent-data": {
            "ops:query-result": {
                "ops:search-result": {
                    "ops:publication-reference": [
                        {"ops:document-id": [{"@document-id-type": "epodoc", "ops:doc-number": "US9999999B2"}]}
                    ]
                }
            }
        }
    }
    biblio_body = {
        "ops:world-patent-data": {
            "ops:document-instance": {
                "ops:exchange-document": {
                    "ops:bibliographic-data": {
                        "ops:publication-reference": {
                            "ops:document-id": [
                                {"@document-id-type": "docdb", "ops:doc-number": "9999999",
                                 "ops:publication-date": {"$": "20250601"}}
                            ]
                        },
                        "ops:invention-title": {"@value": "Sodium ion battery cathode"},
                        "ops:abstract": {"ops:abstract-text": {"$": "A sodium-ion battery with 1100 mAh g-1 capacity."}},
                    }
                }
            }
        }
    }

    def fake_get(url, params=None, headers=None, timeout=None):
        resp = MagicMock()
        if "search" in url:
            resp.json.return_value = token_body
        else:
            resp.json.return_value = biblio_body
        return resp

    with patch("energy_intel_node.requests.get", side_effect=fake_get), \
         patch("energy_intel_node.SCRAPE_DELAY", 0), \
         patch("energy_intel_node.time.sleep"):
        claims = ein.scrape_epo_ops(terms=["sodium ion battery"], max_results=1)

    assert len(claims) == 1
    assert claims[0]["source_type"] == "patent"
    assert claims[0]["technology"] == "sodium-ion"
    assert claims[0]["metric_name"] == "specific_capacity"
    assert "1100.0" in str(claims[0]["metric_value"])
    assert "espacenet.com" in claims[0]["source_url"]
