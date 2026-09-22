"""build_full_site 深入口（tools/site_builder/assemble.py）測試。"""

import json

import pytest

from tools.site_builder import build_full_site

pytestmark = pytest.mark.unit


def _make_day(base, date, body="# 報告\n\n內容"):
    day = base / date
    (day / "steps").mkdir(parents=True, exist_ok=True)
    (day / "report.md").write_text(body, encoding="utf-8")
    return day


def test_build_full_site_composes_pages_and_endpoints(tmp_path):
    _make_day(tmp_path, "2026-09-06")
    _make_day(tmp_path, "2026-09-07")
    # 機器可讀端點來源：本機底線檔
    (tmp_path / "_judge-history.json").write_text(
        json.dumps([{"date": "2026-09-07", "overall": 4.2}]), encoding="utf-8"
    )
    (tmp_path / "_health-history.json").write_text(
        json.dumps([{"date": "2026-09-07", "results": {"hn": "ok"}}]), encoding="utf-8"
    )

    site = build_full_site(tmp_path)

    # 站頁：首頁 + 每天存檔頁
    assert "index.html" in site
    assert any("2026-09-07" in path for path in site)
    # 機器可讀端點以乾淨檔名發佈
    assert "judge-history.json" in site
    assert "health-history.json" in site
    # 端點內容為合法 JSON list（原文轉存）
    assert json.loads(site["judge-history.json"])[0]["overall"] == 4.2


def test_build_full_site_empty_dir_is_safe(tmp_path):
    # 無任何歷史天 → 仍回 dict（可能只有首頁），不報錯
    site = build_full_site(tmp_path)
    assert isinstance(site, dict)


def test_build_full_site_missing_histories_skip_endpoints(tmp_path):
    _make_day(tmp_path, "2026-09-07")
    site = build_full_site(tmp_path)
    # 缺歷史檔 → 不寫端點（靜默略過），但站頁仍在
    assert "index.html" in site
    assert "judge-history.json" not in site
