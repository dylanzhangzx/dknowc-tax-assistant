#!/usr/bin/env python3
"""Skill 内脚本的读写路径白名单。

能力层脚本（question_profile / source_cards / verify_claims）只能：
- 读：SKILL_ROOT 内的文件；
- 写：official-docs/search-results/ 内。

避免 `--output /tmp/x` 或 `--input /etc/passwd` 越过 SKILL.md 的 local_read /
local_write 声明。
"""

from __future__ import annotations

from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = (SKILL_ROOT / "official-docs" / "search-results").resolve()


def _resolve(value: str, base: Path) -> Path:
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        parts = raw.parts
        # 兼容调用方写 official-docs/search-results/xxx.json；否则按文件名落到 results。
        if len(parts) >= 2 and parts[0] == "official-docs" and parts[1] == "search-results":
            raw = SKILL_ROOT / raw
        else:
            raw = base / raw
    return raw.resolve()


def safe_read_path(value: str) -> Path:
    path = _resolve(value, RESULTS_DIR)
    if not (path == SKILL_ROOT or SKILL_ROOT in path.parents):
        raise ValueError(f"输入路径必须位于 skill 目录内：{value}")
    return path


def safe_write_path(value: str) -> Path:
    path = _resolve(value, RESULTS_DIR)
    if not (path == RESULTS_DIR or RESULTS_DIR in path.parents):
        raise ValueError(f"输出路径必须位于 official-docs/search-results/ 内：{value}")
    return path
