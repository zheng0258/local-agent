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


# ── 發佈自證：站台看得到 = 這次 push 成功 ─────────────────────────────
#
# 站台在 push「之前」建置，讀到的 health 快照還沒有當天 deploy 結果（09-24 實測：
# 線上 D 格恆為「未執行」、首頁 deploy 成功率少算當天）。但這份產物只有 push 成功
# 才會出現在 gh-pages，故建站時可直接把發佈日的 deploy 標為 ok。


def _write_health(base, records):
    (base / "_health-history.json").write_text(json.dumps(records), encoding="utf-8")


def _deploy_by_date(site):
    return {
        r["date"]: r["results"].get("deploy")
        for r in json.loads(site["health-history.json"])
    }


def test_publishing_date_marks_deploy_ok_on_all_surfaces(tmp_path):
    _make_day(tmp_path, "2026-09-24")
    _write_health(tmp_path, [
        {"date": "2026-09-23", "results": {"hn": "ok", "deploy": "ok"}},
        {"date": "2026-09-24", "results": {"hn": "ok"}},
    ])

    site = build_full_site(tmp_path, publishing_date="2026-09-24")

    assert _deploy_by_date(site)["2026-09-24"] == "ok"
    assert 'title="deploy: ok"' in site["run-history.html"]
    assert 'title="deploy: 未執行"' not in site["run-history.html"]
    # 首頁成功率計入當天：2/2
    assert "2/2" in site["index.html"]


def test_publishing_date_overrides_earlier_same_day_failure(tmp_path):
    # 同日稍早 deploy 失敗（alert → other），補跑的這次 push 成功才看得到本頁
    _make_day(tmp_path, "2026-09-24")
    _write_health(tmp_path, [{"date": "2026-09-24", "results": {"deploy": "other"}}])

    site = build_full_site(tmp_path, publishing_date="2026-09-24")

    assert _deploy_by_date(site)["2026-09-24"] == "ok"


def test_publishing_date_leaves_other_days_and_local_file_untouched(tmp_path):
    _make_day(tmp_path, "2026-09-24")
    records = [
        {"date": "2026-09-22", "results": {"deploy": "other"}},
        {"date": "2026-09-24", "results": {"hn": "ok"}},
    ]
    _write_health(tmp_path, records)

    site = build_full_site(tmp_path, publishing_date="2026-09-24")

    assert _deploy_by_date(site)["2026-09-22"] == "other"
    # 只改記憶體：本機歷史檔仍由 observe 在 deploy 後如實補記
    on_disk = json.loads((tmp_path / "_health-history.json").read_text(encoding="utf-8"))
    assert on_disk == records


def test_without_publishing_date_health_is_published_verbatim(tmp_path):
    _make_day(tmp_path, "2026-09-24")
    _write_health(tmp_path, [{"date": "2026-09-24", "results": {"hn": "ok"}}])

    site = build_full_site(tmp_path)

    assert _deploy_by_date(site)["2026-09-24"] is None
