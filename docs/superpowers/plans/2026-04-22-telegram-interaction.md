# Telegram 使用者互動 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓使用者在 Telegram digest 訊息上點擊 ⭐ 按鈕標記文章，系統學習偏好並在隔日 fetch 評分時自動調整 LLM interest 分數。

**Architecture:** 新增 `preferences.py` 資料層管理所有持久化檔案；`telegram.py` 增加 `send_with_buttons` / `get_updates` / `answer_callback_query`；pipeline 前端插入 `feedback` 與 `update_profile` 兩個步驟；fetch 評分 prompt 在偏好累積 ≥ 3 筆後自動注入偏好輪廓。

**Tech Stack:** Python 3, urllib（無新依賴）, hashlib, pytest

---

## 檔案地圖

| 動作 | 路徑 | 職責 |
|---|---|---|
| **新增** | `agents/daily_brief/preferences.py` | starred.json / preference_profile.json / tg_offset.json / article_map.json 讀寫 |
| **新增** | `tests/test_preferences.py` | preferences.py 單元測試 |
| **新增** | `tests/test_telegram_new.py` | 新增 telegram 函式單元測試 |
| **修改** | `tools/notifiers/telegram.py` | 新增 `send_with_buttons` / `get_updates` / `answer_callback_query` |
| **修改** | `agents/daily_brief/prompts.py` | 新增 `build_preference_context` / `build_tag_extraction_prompt` |
| **修改** | `agents/daily_brief/config.py` | STEP_CONFIGS 新增 feedback / update_profile |
| **修改** | `agents/daily_brief/agent.py` | ALL_STEPS 更新；新增 `_phase_feedback` / `_phase_update_profile` / `_run_feedback` / `_run_update_profile` / `_get_preference_context`；修改 `_notify` 加按鈕與 article_map；修改 fetch 方法注入偏好 |

---

## Task 1: `preferences.py` — 資料層

**Files:**
- Create: `agents/daily_brief/preferences.py`

- [ ] **Step 1: 寫入 preferences.py**

```python
"""
Daily Brief 使用者偏好資料層。

管理：
  outputs/starred.json              — 永久星標文章清單
  outputs/preference_profile.json   — 主題 tag 權重輪廓
  outputs/tg_offset.json            — Telegram getUpdates offset
  outputs/daily-brief/{date}/steps/article_map.json — index → 文章資料
"""
from __future__ import annotations

import json
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_OUTPUTS_DIR = _PROJECT_ROOT / "outputs"
_STARRED_FILE = _OUTPUTS_DIR / "starred.json"
_PROFILE_FILE = _OUTPUTS_DIR / "preference_profile.json"
_OFFSET_FILE = _OUTPUTS_DIR / "tg_offset.json"
_DAILY_DIR = _OUTPUTS_DIR / "daily-brief"


def read_starred() -> list[dict]:
    if not _STARRED_FILE.exists():
        return []
    return json.loads(_STARRED_FILE.read_text(encoding="utf-8"))


def append_starred(articles: list[dict]) -> None:
    """追加新星標文章（同 URL 不重複）。"""
    existing = read_starred()
    existing_urls = {a["url"] for a in existing}
    new_items = [a for a in articles if a["url"] not in existing_urls]
    if new_items:
        _STARRED_FILE.write_text(
            json.dumps(existing + new_items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def mark_starred_processed(urls: set[str]) -> None:
    """將指定 URL 的項目標記為 processed: true。"""
    items = read_starred()
    for item in items:
        if item["url"] in urls:
            item["processed"] = True
    _STARRED_FILE.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def read_preference_profile() -> dict:
    if not _PROFILE_FILE.exists():
        return {"total_starred": 0, "tags": {}}
    return json.loads(_PROFILE_FILE.read_text(encoding="utf-8"))


def write_preference_profile(profile: dict) -> None:
    _OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    _PROFILE_FILE.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def read_tg_offset() -> int | None:
    if not _OFFSET_FILE.exists():
        return None
    return json.loads(_OFFSET_FILE.read_text(encoding="utf-8")).get("offset")


def write_tg_offset(offset: int) -> None:
    _OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    _OFFSET_FILE.write_text(
        json.dumps({"offset": offset}, ensure_ascii=False), encoding="utf-8"
    )


def read_article_map(date: str) -> dict:
    """讀取特定日期的 article_map.json。date 格式：YYYY-MM-DD。"""
    path = _DAILY_DIR / date / "steps" / "article_map.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_article_map(date: str, mapping: dict) -> None:
    """寫入特定日期的 article_map.json。"""
    path = _DAILY_DIR / date / "steps" / "article_map.json"
    path.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )
```

- [ ] **Step 2: Commit**

```bash
git add agents/daily_brief/preferences.py
git commit -m "feat: add preferences data layer for starred articles and profile"
```

---

## Task 2: `preferences.py` 測試

**Files:**
- Create: `tests/test_preferences.py`

- [ ] **Step 1: 寫入測試檔**

```python
"""Unit tests for agents/daily_brief/preferences.py"""
import json
import pytest
from pathlib import Path


@pytest.fixture
def isolated_prefs(tmp_path, monkeypatch):
    """將 preferences 的所有路徑重導向 tmp_path。"""
    import agents.daily_brief.preferences as prefs
    monkeypatch.setattr(prefs, "_OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(prefs, "_STARRED_FILE", tmp_path / "starred.json")
    monkeypatch.setattr(prefs, "_PROFILE_FILE", tmp_path / "preference_profile.json")
    monkeypatch.setattr(prefs, "_OFFSET_FILE", tmp_path / "tg_offset.json")
    monkeypatch.setattr(prefs, "_DAILY_DIR", tmp_path / "daily-brief")
    return prefs


def test_read_starred_returns_empty_when_missing(isolated_prefs):
    assert isolated_prefs.read_starred() == []


def test_append_starred_writes_new_articles(isolated_prefs):
    articles = [{"url": "https://a.com", "title": "A", "processed": False}]
    isolated_prefs.append_starred(articles)
    result = isolated_prefs.read_starred()
    assert len(result) == 1
    assert result[0]["url"] == "https://a.com"


def test_append_starred_deduplication(isolated_prefs):
    article = {"url": "https://a.com", "title": "A", "processed": False}
    isolated_prefs.append_starred([article])
    isolated_prefs.append_starred([article])
    assert len(isolated_prefs.read_starred()) == 1


def test_mark_starred_processed(isolated_prefs):
    isolated_prefs.append_starred([{"url": "https://a.com", "title": "A", "processed": False}])
    isolated_prefs.mark_starred_processed({"https://a.com"})
    result = isolated_prefs.read_starred()
    assert result[0]["processed"] is True


def test_read_preference_profile_default(isolated_prefs):
    profile = isolated_prefs.read_preference_profile()
    assert profile == {"total_starred": 0, "tags": {}}


def test_write_and_read_preference_profile(isolated_prefs):
    profile = {"total_starred": 5, "tags": {"claude-code": 3}, "updated_at": "2026-04-22"}
    isolated_prefs.write_preference_profile(profile)
    assert isolated_prefs.read_preference_profile() == profile


def test_read_tg_offset_returns_none_when_missing(isolated_prefs):
    assert isolated_prefs.read_tg_offset() is None


def test_write_and_read_tg_offset(isolated_prefs):
    isolated_prefs.write_tg_offset(12345)
    assert isolated_prefs.read_tg_offset() == 12345


def test_read_article_map_returns_empty_when_missing(isolated_prefs):
    assert isolated_prefs.read_article_map("2026-04-22") == {}


def test_write_and_read_article_map(isolated_prefs, tmp_path):
    (tmp_path / "daily-brief" / "2026-04-22" / "steps").mkdir(parents=True)
    mapping = {"1": {"url": "https://a.com", "title": "A"}}
    isolated_prefs.write_article_map("2026-04-22", mapping)
    assert isolated_prefs.read_article_map("2026-04-22") == mapping
```

- [ ] **Step 2: 執行測試，確認全過**

```bash
python3 -m pytest tests/test_preferences.py -v
```

Expected: 10 tests PASSED

- [ ] **Step 3: Commit**

```bash
git add tests/test_preferences.py
git commit -m "test: add unit tests for preferences data layer"
```

---

## Task 3: `telegram.py` — 新增三個函式

**Files:**
- Modify: `tools/notifiers/telegram.py`

- [ ] **Step 1: 在 import 區塊頂端加入 `import json`**

在 `telegram.py` 第 11 行（`from __future__ import annotations` 下方）加入：

```python
import json
```

- [ ] **Step 2: 在檔案尾端追加三個函式**

在 `send_many()` 之後追加：

```python

def get_updates(offset: int | None = None, timeout: int = 0) -> list[dict]:
    """批次讀取 Telegram updates（不阻塞，timeout=0 立即返回）。"""
    _load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("⚠️  TELEGRAM_BOT_TOKEN 未設定，略過 getUpdates。")
        return []
    params: dict[str, int] = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    url = f"https://api.telegram.org/bot{token}/getUpdates?" + urllib.parse.urlencode(params)
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(url, context=ctx) as resp:
            return json.loads(resp.read().decode()).get("result", [])
    except Exception as e:
        print(f"❌ getUpdates 失敗：{e}")
        return []


def answer_callback_query(callback_query_id: str, text: str = "") -> bool:
    """回應 callback query，清除 Telegram 的 loading 轉圈狀態。"""
    _load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return False
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    data = urllib.parse.urlencode(
        {"callback_query_id": callback_query_id, "text": text}
    ).encode()
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    try:
        urllib.request.urlopen(url, data=data, context=ctx)
        return True
    except Exception:
        return False


def send_with_buttons(text: str, buttons: list[list[dict]]) -> bool:
    """
    發送帶 InlineKeyboardMarkup 的 Telegram 訊息。

    buttons 格式（每個子 list 是一排）：
      [[{"text": "⭐1", "callback_data": "20260422:1"}, ...], ...]

    失敗時自動 fallback 到 send()，確保訊息一定送出。
    """
    _load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("⚠️  TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID 未設定，略過通知。")
        return False
    text = _sanitize_html(text)
    if len(text) > MAX_LEN:
        text = text[: MAX_LEN - 3] + "..."
    reply_markup = json.dumps({"inline_keyboard": buttons})
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": reply_markup,
    }).encode()
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    try:
        urllib.request.urlopen(url, data=data, context=ctx)
        print("✅ Telegram 訊息（含按鈕）傳送成功")
        return True
    except urllib.error.HTTPError as e:
        print(f"⚠️  send_with_buttons 失敗（{e.code} {e.read().decode()}），fallback 純文字")
        return send(text)
    except urllib.error.URLError as e:
        print(f"⚠️  send_with_buttons 網路錯誤（{e.reason}），fallback 純文字")
        return send(text)
```

- [ ] **Step 3: Commit**

```bash
git add tools/notifiers/telegram.py
git commit -m "feat: add send_with_buttons, get_updates, answer_callback_query to telegram notifier"
```

---

## Task 4: `telegram.py` 新函式測試

**Files:**
- Create: `tests/test_telegram_new.py`

- [ ] **Step 1: 寫入測試**

```python
"""Unit tests for new telegram functions (no network calls)."""
import pytest
from unittest.mock import patch
from tools.notifiers import telegram


def test_get_updates_returns_empty_when_no_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    # 確保 _load_env 不會載入 .env
    with patch.object(telegram, "_load_env", return_value=None):
        result = telegram.get_updates()
    assert result == []


def test_answer_callback_query_returns_false_when_no_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with patch.object(telegram, "_load_env", return_value=None):
        result = telegram.answer_callback_query("fake_id")
    assert result is False


def test_send_with_buttons_returns_false_when_no_credentials(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with patch.object(telegram, "_load_env", return_value=None):
        result = telegram.send_with_buttons("test", [[]])
    assert result is False


def test_send_with_buttons_button_format():
    """驗證 buttons 格式正確組成 inline_keyboard JSON。"""
    import json
    captured = {}

    def fake_urlopen(url, data=None, context=None):
        captured["data"] = urllib.parse.parse_qs(data.decode())
        class FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self): return b""
        return FakeResp()

    import urllib.parse
    buttons = [[{"text": "⭐1", "callback_data": "20260422:1"}]]
    with patch.object(telegram, "_load_env", return_value=None), \
         patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}), \
         patch("urllib.request.urlopen", fake_urlopen):
        telegram.send_with_buttons("hello", buttons)

    markup = json.loads(captured["data"]["reply_markup"][0])
    assert markup["inline_keyboard"] == buttons
```

- [ ] **Step 2: 執行測試**

```bash
python3 -m pytest tests/test_telegram_new.py -v
```

Expected: 4 tests PASSED

- [ ] **Step 3: Commit**

```bash
git add tests/test_telegram_new.py
git commit -m "test: add unit tests for new telegram functions"
```

---

## Task 5: `prompts.py` — 新增兩個 prompt 函式

**Files:**
- Modify: `agents/daily_brief/prompts.py`

- [ ] **Step 1: 在 prompts.py 尾端追加兩個函式**

```python
# ── 使用者偏好注入 ─────────────────────────────────────────────────

def build_preference_context(profile: dict) -> str:
    """
    從偏好輪廓建立 prompt 注入片段。
    total_starred < 3 時回傳空字串（避免偏好過少導致偏差）。
    """
    if profile.get("total_starred", 0) < 3:
        return ""
    tags = profile.get("tags", {})
    if not tags:
        return ""
    sorted_tags = sorted(tags.items(), key=lambda x: x[1], reverse=True)[:10]
    tag_str = ", ".join(f"{tag}({count})" for tag, count in sorted_tags)
    return (
        "\n\n## 使用者偏好（歷史星標累積）\n"
        f"使用者對以下主題興趣較高（由高到低）：{tag_str}\n"
        "評分時請適當提高與上述主題相關文章的 interest 分數。"
    )


def build_tag_extraction_prompt(articles_json: str) -> str:
    """從星標文章清單萃取主題 tag 的 prompt。"""
    return f"""\
以下是使用者星標的科技文章清單（title + summary）：

{articles_json}

## 任務

為這批文章整體萃取 3-8 個英文主題 tag（小寫、連字號格式，例：supply-chain-attack、claude-code、llm-tools）。

## 輸出格式

```json
{{
  "tags": ["supply-chain-attack", "claude-code", "llm-tools"]
}}
```

只輸出 tag 清單，不重複，按重要性排序。\
"""
```

- [ ] **Step 2: Commit**

```bash
git add agents/daily_brief/prompts.py
git commit -m "feat: add build_preference_context and build_tag_extraction_prompt"
```

---

## Task 6: `config.py` — 新增步驟設定

**Files:**
- Modify: `agents/daily_brief/config.py`

- [ ] **Step 1: 在 STEP_CONFIGS 中新增 feedback 與 update_profile**

在 `STEP_CONFIGS` dict 的 `"hatena"` 項目**之前**插入：

```python
    "feedback": StepConfig(
        max_retries=2,
        strategy="plain",
        backoff_seconds=(1.0, 3.0),
        task_description="批次讀取 Telegram callback，更新星標清單",
    ),
    "update_profile": StepConfig(
        max_retries=2,
        strategy="plain",
        backoff_seconds=(1.0, 3.0),
        task_description="從新星標文章萃取主題 tag，累積偏好輪廓",
    ),
```

- [ ] **Step 2: Commit**

```bash
git add agents/daily_brief/config.py
git commit -m "feat: add STEP_CONFIGS entries for feedback and update_profile steps"
```

---

## Task 7: `notify` 步驟改造 — 加按鈕與 article_map

**Files:**
- Modify: `agents/daily_brief/agent.py`

- [ ] **Step 1: 在 agent.py 頂端 import 區塊新增 `import hashlib`**

在 `import json` 後面加：

```python
import hashlib
```

- [ ] **Step 2: 在 `_notify()` 方法中建立 article_map 並使用 `send_with_buttons`**

找到 `_notify()` 方法中的這段（約第 656 行）：

```python
        tg_digest = digest_result.get("tg_digest", "")
        ok2 = False
        if tg_digest:
            if steps_dir:
                (steps_dir / "telegram_digest.txt").write_text(tg_digest, encoding="utf-8")
            ok2 = send(tg_digest)
            if not ok2:
                logger.error("Step notify   : 第二封訊息發送失敗，telegram.done 不寫入")
```

替換為：

```python
        tg_digest = digest_result.get("tg_digest", "")
        ok2 = False
        if tg_digest:
            if steps_dir:
                (steps_dir / "telegram_digest.txt").write_text(tg_digest, encoding="utf-8")

            # 建立 article_map 並寫入（index → 文章資料）
            top_digests = digests[:8]
            article_map = {
                str(i + 1): {
                    "url": d.get("url", ""),
                    "title": d.get("title", ""),
                    "source": d.get("source", ""),
                    "summary": d.get("summary", ""),
                }
                for i, d in enumerate(top_digests)
            }
            if steps_dir:
                from . import preferences as prefs
                prefs.write_article_map(today, article_map)

            # 建立 inline keyboard（每排 4 顆，callback_data = YYYYMMDD:index）
            date_compact = today.replace("-", "")
            btn_flat = [
                {"text": f"⭐{i + 1}", "callback_data": f"{date_compact}:{i + 1}"}
                for i in range(len(top_digests))
            ]
            buttons = [btn_flat[i:i + 4] for i in range(0, len(btn_flat), 4)]

            from tools.notifiers.telegram import send_with_buttons
            ok2 = send_with_buttons(tg_digest, buttons)
            if not ok2:
                logger.error("Step notify   : 第二封訊息發送失敗，telegram.done 不寫入")
```

- [ ] **Step 3: Commit**

```bash
git add agents/daily_brief/agent.py
git commit -m "feat: add inline keyboard buttons and article_map to notify step"
```

---

## Task 8: `feedback` 步驟

**Files:**
- Modify: `agents/daily_brief/agent.py`

- [ ] **Step 1: 更新 ALL_STEPS**

找到：

```python
ALL_STEPS = [*FETCH_STEPS, "compress", "digest", "judge", "report", "save", "notify"]
```

替換為：

```python
ALL_STEPS = ["feedback", "update_profile", *FETCH_STEPS, "compress", "digest", "judge", "report", "save", "notify"]
```

- [ ] **Step 2: 在 `run()` 方法中，`source_data = self._phase_fetch(ctx)` 之前插入兩個新步驟呼叫**

找到：

```python
        source_data = self._phase_fetch(ctx)
```

在其前方插入：

```python
        self._phase_feedback(ctx)
        self._phase_update_profile(ctx)
```

- [ ] **Step 3: 新增 `_phase_feedback()` 與 `_run_feedback()` 方法**

在 `_phase_fetch()` 之前插入：

```python
    def _phase_feedback(self, ctx: _RunContext) -> None:
        feedback_artifact = ctx.steps_dir / "feedback.json"
        if "feedback" not in ctx.steps_to_run:
            return
        if feedback_artifact.exists() and "feedback" not in ctx.force_steps:
            logger.info("Step feedback  : 載入既有 artifact")
            return

        logger.info("Step feedback  : 執行中...")

        def _feedback_fn() -> dict:
            return self._run_feedback(ctx.steps_dir, ctx.today)

        result = ctx.supervisor.run_step(
            "feedback", _feedback_fn, force=("feedback" in ctx.force_steps)
        )
        if result.success:
            feedback_artifact.write_text(
                json.dumps(result.output, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info(
                "Step feedback  : 完成（新增 %d 篇星標）",
                result.output.get("new_starred", 0),
            )
        else:
            logger.warning("Step feedback  : 失敗，略過（不影響後續步驟）")

    def _run_feedback(self, steps_dir: Path, today: str) -> dict:
        from tools.notifiers import telegram as tg
        from . import preferences

        offset = preferences.read_tg_offset()

        if offset is None:
            # 首次執行：只取得當前最新 update_id，設 offset，本次不處理歷史 callback
            updates = tg.get_updates(timeout=0)
            new_offset = (max(u["update_id"] for u in updates) + 1) if updates else 1
            preferences.write_tg_offset(new_offset)
            logger.info("Step feedback  : 首次初始化 offset=%d，跳過本次處理", new_offset)
            return {"new_starred": 0, "offset": new_offset, "initialized": True}

        updates = tg.get_updates(offset=offset, timeout=0)
        if not updates:
            return {"new_starred": 0, "offset": offset}

        new_offset = max(u["update_id"] for u in updates) + 1
        callbacks = [u for u in updates if "callback_query" in u]

        new_articles: list[dict] = []
        callback_ids: list[str] = []

        for update in callbacks:
            cq = update["callback_query"]
            callback_ids.append(cq["id"])
            data = cq.get("data", "")
            parts = data.split(":", 1)
            if len(parts) != 2:
                continue
            date_compact, index_str = parts
            if len(date_compact) != 8 or not index_str.isdigit():
                continue
            date_fmt = f"{date_compact[:4]}-{date_compact[4:6]}-{date_compact[6:]}"
            article_map = preferences.read_article_map(date_fmt)
            article = article_map.get(index_str)
            if article:
                new_articles.append({
                    **article,
                    "date": date_fmt,
                    "starred_at": datetime.now().isoformat(timespec="seconds"),
                    "processed": False,
                })

        preferences.append_starred(new_articles)

        for cid in callback_ids:
            tg.answer_callback_query(cid)

        preferences.write_tg_offset(new_offset)
        return {"new_starred": len(new_articles), "offset": new_offset}
```

- [ ] **Step 4: Commit**

```bash
git add agents/daily_brief/agent.py
git commit -m "feat: add feedback step to batch-read Telegram callbacks and update starred list"
```

---

## Task 9: `update_profile` 步驟

**Files:**
- Modify: `agents/daily_brief/agent.py`

- [ ] **Step 1: 新增 `_phase_update_profile()` 與 `_run_update_profile()` 方法**

在 `_phase_feedback()` 之後插入：

```python
    def _phase_update_profile(self, ctx: _RunContext) -> None:
        artifact = ctx.steps_dir / "update_profile.json"
        if "update_profile" not in ctx.steps_to_run:
            return
        if artifact.exists() and "update_profile" not in ctx.force_steps:
            logger.info("Step update_profile: 載入既有 artifact")
            return

        logger.info("Step update_profile: 執行中...")

        def _fn() -> dict:
            return self._run_update_profile()

        result = ctx.supervisor.run_step(
            "update_profile", _fn, force=("update_profile" in ctx.force_steps)
        )
        if result.success:
            artifact.write_text(
                json.dumps(result.output, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info(
                "Step update_profile: 完成（處理 %d 篇，新 tags: %s）",
                result.output.get("processed", 0),
                result.output.get("new_tags", []),
            )
        else:
            logger.warning("Step update_profile: 失敗，略過（不影響後續步驟）")

    def _run_update_profile(self) -> dict:
        from . import preferences
        from datetime import date as _date

        starred = preferences.read_starred()
        new_items = [a for a in starred if not a.get("processed", False)]

        if not new_items:
            logger.info("Step update_profile: 無新星標文章，略過 LLM")
            return {"processed": 0, "new_tags": []}

        articles_json = json.dumps(
            [{"title": a["title"], "summary": a.get("summary", "")} for a in new_items],
            ensure_ascii=False,
        )
        raw = self._complete(prompts.build_tag_extraction_prompt(articles_json))
        result = parse_llm_json(raw)
        new_tags: list[str] = result.get("tags", [])

        profile = preferences.read_preference_profile()
        tag_counts: dict[str, int] = profile.get("tags", {})
        for tag in new_tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

        profile["tags"] = tag_counts
        profile["total_starred"] = profile.get("total_starred", 0) + len(new_items)
        profile["updated_at"] = _date.today().strftime("%Y-%m-%d")

        preferences.write_preference_profile(profile)
        preferences.mark_starred_processed({a["url"] for a in new_items})

        return {"processed": len(new_items), "new_tags": new_tags}
```

- [ ] **Step 2: Commit**

```bash
git add agents/daily_brief/agent.py
git commit -m "feat: add update_profile step to extract topic tags from starred articles"
```

---

## Task 10: fetch 評分 prompt 注入偏好

**Files:**
- Modify: `agents/daily_brief/agent.py`
- Modify: `agents/daily_brief/prompts.py`

- [ ] **Step 1: 讓四個 fetch prompt 函式支援 `preference_context` 參數**

在 `prompts.py` 中，修改四個 `build_*_prompt` 函式，在 `_scoring_block()` 後面插入 `{preference_context}`：

`build_hatena_prompt`：
```python
def build_hatena_prompt(articles_json: str, preference_context: str = "") -> str:
    return f"""\
## 文章清單（Hatena Bookmark IT）

{articles_json}

## 任務

對每篇文章依以下標準評定興趣度：
{_scoring_block()}{preference_context}

## 輸出格式

```json
{{
  "articles": [
    {{"title": "繁體中文標題", "url": "原文URL", "bookmarks": 123, "interest": "***", "category": "AI"}}
  ]
}}
```\
"""
```

`build_hn_prompt`：
```python
def build_hn_prompt(articles_json: str, preference_context: str = "") -> str:
    return f"""\
## 文章清單（Hacker News）

{articles_json}

## 任務

對每篇文章評定興趣度：
{_scoring_block()}{preference_context}

連結一律使用 HN 討論頁 URL（https://news.ycombinator.com/item?id=...）。

## 輸出格式

```json
{{
  "articles": [
    {{"title": "繁體中文標題", "url": "https://news.ycombinator.com/item?id=...", "score": 456, "interest": "***", "category": "Security"}}
  ]
}}
```

注意：key 後必須用半形 ": " 分隔，禁用全形冒號「：」；標題中若含雙引號須逸脫為 \"。\
"""
```

`build_reddit_prompt`：
```python
def build_reddit_prompt(posts_json: str, preference_context: str = "") -> str:
    return f"""\
## 文章清單（Reddit 16 子版）

{posts_json}

## 任務

對每篇文章評定興趣度：
{_scoring_block()}{preference_context}

## 輸出格式

```json
{{
  "articles": {{
    "資安類": [{{"title": "...", "url": "...", "score": 123, "interest": "***", "category": "資安", "subreddit": "r/cybersecurity"}}],
    "AI 類": [...],
    "AI 開發工具類": [...],
    "核心技術類": [...],
    "OSS・獨立開發類": [...],
    "職涯・實踐類": [...]
  }}
}}
```

注意：標題中若含雙引號須逸脫為 \"；key 後必須用半形 ": " 分隔。\
"""
```

`build_security_blogs_prompt`：
```python
def build_security_blogs_prompt(content: str, preference_context: str = "") -> str:
    return f"""\
## 資安部落格內容（aikido.dev / wiz.io）

{content}

## 任務

識別最新 1–3 篇文章，評定興趣度（只保留 ***）。
{_scoring_block()}{preference_context}

## 輸出格式

```json
{{
  "articles": [
    {{"title": "...", "url": "...", "source": "aikido.dev", "interest": "***"}}
  ]
}}
```\
"""
```

- [ ] **Step 2: 在 `agent.py` 新增 `_get_preference_context()` 輔助方法**

在 `_complete()` 前插入：

```python
    def _get_preference_context(self) -> str:
        from . import preferences
        profile = preferences.read_preference_profile()
        return prompts.build_preference_context(profile)
```

- [ ] **Step 3: 修改四個 `_fetch_*` 方法，傳入偏好 context**

修改 `_fetch_hatena`：

```python
    def _fetch_hatena(self, mod) -> dict:
        from tools.fetchers.schema import clean_articles
        raw = mod.fetch()
        logger.info("Hatena 抓取：%d 篇文章", len(raw))
        pref = self._get_preference_context()
        result = parse_llm_json(
            self._complete(prompts.build_hatena_prompt(json.dumps(raw, ensure_ascii=False), pref))
        )
        cleaned = clean_articles(result.get("articles", []))
        result["articles"] = [article.to_dict() for article in cleaned]
        logger.info("Hatena LLM + 清洗完成：%d 篇", len(result["articles"]))
        return result
```

同樣方式修改 `_fetch_hn`、`_fetch_reddit`、`_fetch_security`，各加上 `pref = self._get_preference_context()` 並傳入對應 prompt 函式。

- [ ] **Step 4: Commit**

```bash
git add agents/daily_brief/agent.py agents/daily_brief/prompts.py
git commit -m "feat: inject preference context into fetch scoring prompts"
```

---

## Task 11: CLAUDE.md 更新

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 更新步驟名稱列表**

找到：

```
# 可用 step 名稱：hatena / hn / reddit / security / compress / digest / judge / report / save / notify
```

替換為：

```
# 可用 step 名稱：feedback / update_profile / hatena / hn / reddit / security / compress / digest / judge / report / save / notify
```

- [ ] **Step 2: 在輸出目錄結構區塊補充新檔案**

找到 `outputs/daily-brief/{today}/` 結構說明，在 `steps/` 區塊新增：

```
│   ├── feedback.json     # 本次批次讀取到的新星標數量與 offset
│   ├── update_profile.json # 本次處理的星標數量與萃取的 tags
│   └── article_map.json  # notify 寫入，index → 文章資料
```

並在 `outputs/daily-brief/` 同層補充：

```
outputs/
├── starred.json              # 永久星標文章清單（含 processed 欄位）
├── preference_profile.json   # 主題 tag 權重輪廓
└── tg_offset.json            # Telegram getUpdates offset 記錄
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with feedback/update_profile steps and new output files"
```

---

## 驗收

- [ ] `python3 -m pytest tests/test_preferences.py tests/test_telegram_new.py -v` — 全過
- [ ] `python lint/check_agent_interface.py` — 無錯誤
- [ ] `python3 main.py "/daily-brief --only feedback"` — 首次執行初始化 offset，無錯誤
- [ ] `python3 main.py "/daily-brief --only update_profile"` — 無新星標時直接略過 LLM
- [ ] Telegram digest 訊息底部出現 `⭐1`…`⭐N` 按鈕
- [ ] 點擊按鈕後隔天 pipeline 的 `feedback` 步驟正確讀取並寫入 `starred.json`
