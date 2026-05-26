import json
import pytest
from scraper import compute_diff, parse_holdings_from_html


def _holding(code, name, shares, weight, amount=0):
    return {"code": code, "name": name, "shares": shares, "amount": amount, "weight": weight}


def test_compute_diff_no_prev_returns_empty():
    curr = {"holdings": [_holding("2330", "台積電", 1000, 5.0)]}
    result = compute_diff(None, curr)
    assert result == {"added": [], "removed": [], "increased": [], "decreased": []}


def test_compute_diff_new_stock_is_added():
    prev = {"holdings": [_holding("2330", "台積電", 1000, 5.0)]}
    curr = {"holdings": [
        _holding("2330", "台積電", 1000, 5.0),
        _holding("2454", "聯發科", 500, 3.0),
    ]}
    result = compute_diff(prev, curr)
    assert len(result["added"]) == 1
    assert result["added"][0]["code"] == "2454"
    assert result["added"][0]["shares"] == 500
    assert result["added"][0]["weight"] == 3.0
    assert result["removed"] == []
    assert result["increased"] == []
    assert result["decreased"] == []


def test_compute_diff_removed_stock():
    prev = {"holdings": [
        _holding("2330", "台積電", 1000, 5.0),
        _holding("1303", "南亞", 4000, 2.0),
    ]}
    curr = {"holdings": [_holding("2330", "台積電", 1000, 5.0)]}
    result = compute_diff(prev, curr)
    assert len(result["removed"]) == 1
    assert result["removed"][0]["code"] == "1303"
    assert result["removed"][0]["shares_prev"] == 4000
    assert result["removed"][0]["weight_prev"] == 2.0
    assert result["added"] == []


def test_compute_diff_increased_shares():
    prev = {"holdings": [_holding("2330", "台積電", 1000, 5.0)]}
    curr = {"holdings": [_holding("2330", "台積電", 1200, 5.5)]}
    result = compute_diff(prev, curr)
    assert len(result["increased"]) == 1
    d = result["increased"][0]
    assert d["code"] == "2330"
    assert d["shares_delta"] == 200
    assert round(d["shares_pct"], 2) == 20.0
    assert round(d["weight_delta"], 4) == 0.5
    assert d["weight_curr"] == 5.5
    assert result["decreased"] == []


def test_compute_diff_decreased_shares():
    prev = {"holdings": [_holding("2330", "台積電", 1000, 5.0)]}
    curr = {"holdings": [_holding("2330", "台積電", 800, 4.5)]}
    result = compute_diff(prev, curr)
    assert len(result["decreased"]) == 1
    d = result["decreased"][0]
    assert d["shares_delta"] == -200
    assert round(d["shares_pct"], 2) == -20.0
    assert round(d["weight_delta"], 4) == -0.5
    assert d["weight_curr"] == 4.5
    assert result["increased"] == []


def test_compute_diff_unchanged_stock_not_in_any_list():
    prev = {"holdings": [_holding("2330", "台積電", 1000, 5.0)]}
    curr = {"holdings": [_holding("2330", "台積電", 1000, 5.0)]}
    result = compute_diff(prev, curr)
    assert result == {"added": [], "removed": [], "increased": [], "decreased": []}


import csv
import json
import shutil
from pathlib import Path
from scraper import save_data, load_previous


SAMPLE_DATA = {
    "fund_code": "00981A",
    "date": "2026-05-27",
    "nav": 31.48,
    "total_asset": 286439360959,
    "holdings": [
        {"code": "2330", "name": "台積電", "shares": 11657000, "amount": 26461390000, "weight": 9.24}
    ],
}


def test_save_data_creates_all_four_files(tmp_path):
    save_data(SAMPLE_DATA, "2026-05-27", data_dir=tmp_path)
    assert (tmp_path / "2026-05-27.json").exists()
    assert (tmp_path / "2026-05-27.csv").exists()
    assert (tmp_path / "latest.json").exists()
    assert (tmp_path / "latest.csv").exists()


def test_save_data_json_content(tmp_path):
    save_data(SAMPLE_DATA, "2026-05-27", data_dir=tmp_path)
    saved = json.loads((tmp_path / "2026-05-27.json").read_text(encoding="utf-8"))
    assert saved["fund_code"] == "00981A"
    assert saved["nav"] == 31.48
    assert saved["holdings"][0]["code"] == "2330"


def test_save_data_csv_headers_and_row(tmp_path):
    save_data(SAMPLE_DATA, "2026-05-27", data_dir=tmp_path)
    lines = (tmp_path / "2026-05-27.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "date,code,name,shares,amount,weight"
    assert lines[1].startswith("2026-05-27,2330,台積電")


def test_save_data_latest_matches_dated(tmp_path):
    save_data(SAMPLE_DATA, "2026-05-27", data_dir=tmp_path)
    dated = (tmp_path / "2026-05-27.json").read_text(encoding="utf-8")
    latest = (tmp_path / "latest.json").read_text(encoding="utf-8")
    assert dated == latest


def test_save_data_is_idempotent(tmp_path):
    save_data(SAMPLE_DATA, "2026-05-27", data_dir=tmp_path)
    save_data(SAMPLE_DATA, "2026-05-27", data_dir=tmp_path)  # should not raise
    assert (tmp_path / "2026-05-27.json").exists()


def test_load_previous_returns_none_when_no_snapshots(tmp_path):
    result = load_previous("2026-05-27", data_dir=tmp_path)
    assert result is None


def test_load_previous_returns_most_recent_before_today(tmp_path):
    d1 = {**SAMPLE_DATA, "date": "2026-05-25"}
    d2 = {**SAMPLE_DATA, "date": "2026-05-26"}
    (tmp_path / "2026-05-25.json").write_text(json.dumps(d1), encoding="utf-8")
    (tmp_path / "2026-05-26.json").write_text(json.dumps(d2), encoding="utf-8")
    result = load_previous("2026-05-27", data_dir=tmp_path)
    assert result["date"] == "2026-05-26"


def test_load_previous_skips_today(tmp_path):
    d = {**SAMPLE_DATA, "date": "2026-05-27"}
    (tmp_path / "2026-05-27.json").write_text(json.dumps(d), encoding="utf-8")
    result = load_previous("2026-05-27", data_dir=tmp_path)
    assert result is None


def test_load_previous_skips_latest_files(tmp_path):
    # latest.json should be ignored (not a date)
    d = {**SAMPLE_DATA, "date": "2026-05-26"}
    (tmp_path / "2026-05-26.json").write_text(json.dumps(d), encoding="utf-8")
    (tmp_path / "latest.json").write_text(json.dumps(d), encoding="utf-8")
    result = load_previous("2026-05-27", data_dir=tmp_path)
    assert result is not None
    assert result["date"] == "2026-05-26"


from scraper import update_readme

README_TEMPLATE = """\
# Title

<!-- DAILY_REPORT_START -->
old report
<!-- DAILY_REPORT_END -->

<!-- HOLDINGS_TABLE_START -->
old table
<!-- HOLDINGS_TABLE_END -->
"""

SAMPLE_DATA_FULL = {
    "fund_code": "00981A",
    "date": "2026-05-27",
    "nav": 31.48,
    "total_asset": 286439360959,
    "holdings": [
        {"code": "2330", "name": "台積電", "shares": 11657000, "amount": 26461390000, "weight": 9.24},
        {"code": "2454", "name": "聯發科", "shares": 4263000, "amount": 18181695000, "weight": 6.35},
    ],
}

EMPTY_DIFF = {"added": [], "removed": [], "increased": [], "decreased": []}


def test_update_readme_replaces_old_content(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(README_TEMPLATE, encoding="utf-8")
    update_readme(SAMPLE_DATA_FULL, EMPTY_DIFF, readme_path=readme)
    content = readme.read_text(encoding="utf-8")
    assert "old report" not in content
    assert "old table" not in content


def test_update_readme_preserves_markers(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(README_TEMPLATE, encoding="utf-8")
    update_readme(SAMPLE_DATA_FULL, EMPTY_DIFF, readme_path=readme)
    content = readme.read_text(encoding="utf-8")
    assert "<!-- DAILY_REPORT_START -->" in content
    assert "<!-- DAILY_REPORT_END -->" in content
    assert "<!-- HOLDINGS_TABLE_START -->" in content
    assert "<!-- HOLDINGS_TABLE_END -->" in content


def test_update_readme_shows_date_and_nav(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(README_TEMPLATE, encoding="utf-8")
    update_readme(SAMPLE_DATA_FULL, EMPTY_DIFF, readme_path=readme)
    content = readme.read_text(encoding="utf-8")
    assert "2026-05-27" in content
    assert "31.48" in content


def test_update_readme_shows_no_change_when_diff_empty(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(README_TEMPLATE, encoding="utf-8")
    update_readme(SAMPLE_DATA_FULL, EMPTY_DIFF, readme_path=readme)
    content = readme.read_text(encoding="utf-8")
    assert "今日無異動" in content


def test_update_readme_shows_increased_stock(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(README_TEMPLATE, encoding="utf-8")
    diff = {
        "added": [],
        "removed": [],
        "increased": [{"code": "2404", "name": "漢唐", "shares_delta": 64000, "shares_pct": 19.94, "weight_delta": 0.15, "weight_curr": 0.83}],
        "decreased": [],
    }
    update_readme(SAMPLE_DATA_FULL, diff, readme_path=readme)
    content = readme.read_text(encoding="utf-8")
    assert "2404" in content
    assert "⬆️" in content
    assert "+64,000" in content


def test_update_readme_shows_decreased_stock(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(README_TEMPLATE, encoding="utf-8")
    diff = {
        "added": [],
        "removed": [],
        "increased": [],
        "decreased": [{"code": "1303", "name": "南亞", "shares_delta": -4129000, "shares_pct": -99.98, "weight_delta": -0.61, "weight_curr": 0.0}],
    }
    update_readme(SAMPLE_DATA_FULL, diff, readme_path=readme)
    content = readme.read_text(encoding="utf-8")
    assert "1303" in content
    assert "⬇️" in content
    assert "-4,129,000" in content


def test_update_readme_holdings_table_has_all_stocks(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(README_TEMPLATE, encoding="utf-8")
    update_readme(SAMPLE_DATA_FULL, EMPTY_DIFF, readme_path=readme)
    content = readme.read_text(encoding="utf-8")
    assert "2330" in content
    assert "2454" in content
    assert "台積電" in content
    assert "聯發科" in content


# Minimal HTML fixture that mimics the real page's data-content attribute
SAMPLE_HTML = (
    '<div id="DataAsset" data-content=\'['
    '{"FundCode":"49YTW","AssetCode":"NAV","AssetName":"淨資產","Value":286439360959.0,"Details":null},'
    '{"FundCode":"49YTW","AssetCode":"P_UNIT","AssetName":"每單位淨值","Value":31.48,"Details":null},'
    '{"FundCode":"49YTW","AssetCode":"ST","AssetName":"股票","Value":276222913420.0,"Details":['
    '{"DetailCode":"2330","DetailName":"台積電","Share":11657000.0,"Amount":26461390000.0,"NavRate":9.24},'
    '{"DetailCode":"2454","DetailName":"聯發科","Share":4263000.0,"Amount":18181695000.0,"NavRate":6.35}'
    ']}]\'>'
)


def test_parse_holdings_fund_code():
    result = parse_holdings_from_html(SAMPLE_HTML)
    assert result["fund_code"] == "00981A"


def test_parse_holdings_nav():
    result = parse_holdings_from_html(SAMPLE_HTML)
    assert result["nav"] == 31.48


def test_parse_holdings_total_asset():
    result = parse_holdings_from_html(SAMPLE_HTML)
    assert result["total_asset"] == 286439360959


def test_parse_holdings_stock_count():
    result = parse_holdings_from_html(SAMPLE_HTML)
    assert len(result["holdings"]) == 2


def test_parse_holdings_first_stock():
    result = parse_holdings_from_html(SAMPLE_HTML)
    h = result["holdings"][0]
    assert h["code"] == "2330"
    assert h["name"] == "台積電"
    assert h["shares"] == 11657000
    assert h["amount"] == 26461390000
    assert h["weight"] == 9.24


def test_parse_holdings_date_field_present():
    result = parse_holdings_from_html(SAMPLE_HTML)
    # date is set by caller via today's date — parse returns it as empty string or today
    assert "date" in result
