"""DeployStep — 把完整歷史存檔發佈成公開站台。

SentinelCodec：成功後 touch deploy.done（存在 = 已發佈 → 下次 LOAD 略過）。
guard：今日 report.md 必須存在（gate-on-success）。
注入 build 為**零參 thunk**（loader 讀全部歷史天 → build_site_archive → {path: html}
全量 map），確保每次發佈全量重建整站、公開站與本機真實狀態一致；以及一個 push
副作用 callable（把 build 產物 force-push 到 gh-pages branch，git 隔離藏在 push 內部）。
_produce 把 builder 產出寫進獨立 build 目錄後交給 push。
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from config import get_logger

from ..codecs import SentinelCodec
from ..step import Step, StepOutput
from tools.site_builder import write_site

logger = get_logger(__name__)


def push_site(build_dir: Path) -> None:
    """把 build 產物 force-push 到 gh-pages branch（獨立 git worktree 隔離）。

    用 `git worktree` 在臨時目錄上 checkout 一個孤立 gh-pages，複製站台檔案、
    commit、force-push origin/gh-pages。全程不動主工作區、main 不產生每日 commit。
    副作用集中於此（DeployStep 預設注入它，測試注入 fake）。
    """
    from ..config import OUTPUT_DIR

    repo_root = OUTPUT_DIR.parent.parent  # _PROJECT_ROOT/outputs/daily-brief → repo root
    branch = "gh-pages"

    def _git(*args: str, cwd: Path) -> None:
        subprocess.run(
            ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
        )

    with tempfile.TemporaryDirectory(prefix="gh-pages-wt-") as tmp:
        worktree = Path(tmp) / "wt"
        # 以孤立 worktree checkout gh-pages（不存在則建空 orphan 分支）
        try:
            _git(
                "worktree", "add", "--force", "-B", branch, str(worktree),
                f"origin/{branch}", cwd=repo_root,
            )
        except subprocess.CalledProcessError:
            _git("worktree", "add", "--force", "--detach", str(worktree), cwd=repo_root)
            _git("checkout", "--orphan", branch, cwd=worktree)
            _git("rm", "-rf", "--quiet", ".", cwd=worktree)
        try:
            # 清掉舊站台檔案（保留 .git），複製新產物
            for child in worktree.iterdir():
                if child.name == ".git":
                    continue
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            for item in Path(build_dir).iterdir():
                dest = worktree / item.name
                if item.is_dir():
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)
            (worktree / ".nojekyll").touch()

            _git("add", "-A", cwd=worktree)
            _git("commit", "-m", "deploy: daily brief site", cwd=worktree)
            _git("push", "--force", "origin", f"HEAD:{branch}", cwd=worktree)
            logger.info("Deploy: force-pushed → %s", branch)
        finally:
            # 清掉 worktree 註冊，主工作區保持乾淨
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=str(repo_root), capture_output=True, text=True,
            )


class DeployStep(Step):
    name = "deploy"
    codec = SentinelCodec()

    def __init__(
        self,
        build: Callable[[], dict[str, str]],
        today: str,
        push: Callable[[Path], None] = push_site,
    ) -> None:
        self._build = build
        self._push = push
        self._today = today

    def artifact_path(self, ctx) -> Path:
        return ctx.day_dir / "deploy.done"

    def _guard(self, ctx, input) -> bool:
        # gate-on-success：今日有 report.md 才發佈
        return (ctx.day_dir / "report.md").exists()

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        # 全量重建：build thunk 內部讀全部歷史天 → 整站 map。
        site_map = self._build()
        with tempfile.TemporaryDirectory(prefix="site-build-") as tmp:
            build_dir = Path(tmp)
            write_site(site_map, build_dir)
            logger.info("Deploy: 全量建造 %d 個檔案 → push", len(site_map))
            self._push(build_dir)
        return StepOutput(persist=None, value=None)

    def _default(self, input):
        return None
