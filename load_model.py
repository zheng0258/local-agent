"""Model pre-loader for crontab scheduling.

Run ~15 minutes before main.py to ensure model is warmed up and API is stable.

Crontab example:
    45 1 * * * /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 /path/to/load_model.py
    0  2 * * * /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 /path/to/main.py "/daily-brief"
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import setup_logging
from config.settings import (
    DEFAULT_JUDGE_LLM_MODEL,
    DEFAULT_LOCAL_LLM_MODEL,
    ensure_llm_ready,
)
from tools.lms_lifecycle import ensure_models_loaded, get_loaded_models

_STABILIZE_SECONDS = 600


def _tg(msg: str) -> None:
    try:
        from tools.notifiers.telegram import send as tg_send
        tg_send(msg)
    except Exception:
        pass


def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)

    llm_model = os.environ.get("LOCAL_LLM_MODEL", DEFAULT_LOCAL_LLM_MODEL)
    judge_model = os.environ.get("JUDGE_LLM_MODEL", DEFAULT_JUDGE_LLM_MODEL)
    models = [llm_model, judge_model]

    # Step 1: 確保 LM Studio 已啟動
    if not ensure_llm_ready():
        msg = "LM Studio 未啟動且無法自動喚醒，模型載入中止。daily-brief 將無法執行。"
        logger.error(msg)
        _tg(f"✗ {msg}")
        sys.exit(1)

    # Step 2: 載入模型
    freshly_loaded = ensure_models_loaded(models)

    # Step 3: 驗證模型是否確實在 lms ps
    loaded = get_loaded_models()
    missing = [m for m in models if m not in loaded]
    if missing:
        msg = f"模型載入失敗，lms ps 中缺少：{', '.join(missing)}"
        logger.error(msg)
        _tg(f"✗ {msg}")
        sys.exit(1)

    # Step 4: 若是剛才才載入，等待 API 穩定
    if freshly_loaded:
        logger.info("模型剛載入，等待 %ds 確保 LM Studio API 就緒...", _STABILIZE_SECONDS)
        _tg(f"模型載入完成，等待 {_STABILIZE_SECONDS // 60} 分鐘讓 API 穩定...")
        time.sleep(_STABILIZE_SECONDS)
        logger.info("等待完畢，模型就緒")
    else:
        logger.info("模型已在 lms ps 中，無需等待")

    logger.info("load_model 完成，已就緒：%s", ", ".join(models))


if __name__ == "__main__":
    main()
