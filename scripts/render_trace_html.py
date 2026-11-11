#!/usr/bin/env python3
"""可信溯源核验报告渲染器：把搜索结果 JSON + 最终答案渲染为单文件可核验 HTML。

深知税务助手 public 版（渲染层与深知系列核验报告同构，数据口径保持自有与真实）。
输入直读 tax_search.py 的 --json-only 输出（content.data.检索文章），正文用 --answer-file
传入最终答案（关键结论带 [n] 角标），
成稿自检用 --self-check-file 传入五项结果。

报告定位：不止展示"材料从哪来"（溯源），更要传达"我们查过了，可以交付"（核验）。
架构（参考深知晓交互原型）：
- 顶栏：身份章 + 标题 + 工具组（只看正文 / 复制全文 / 打印归档）+ 阅读进度条
- Hero：大标题 + 真实统计（N 次检索 · M 篇来源文章 · K 处引用）+ 双视图切换
- 过程回顾条：检索 → 入库 → 逐条比对 → 核验完成（静态回放，数字全部真实计算；
  无思考流数据就不展示"思考"步骤——硬造即违背核验诚实性）
- 核验报告视图（默认）：核验报告单 + 正文分节卡；角标点击跳知识专库定位
- 知识专库视图（全屏）：大搜索 + 热词（标题/正文高频词真实计算）+ 检索分组 tabs + 材料卡
三个核验层次：报告级（核验报告单）／材料级（来源卡核验链标记）／引用级（角标一一绑定）。
诚实原则：脚本真实计算的结果才打勾；无法自动判定的项不虚构展示（"现行效力"人工复核提示行已移除，2026-09-19 起）。
生成前预处理（内置）：policyFiles 发文字号本地匹配、存档快照兜底（screenShotPath /A/ 容错 + 格式校验；
原文链接原样进报告、不做活性探测——2026-10-08 起，--skip-link-check 保留为兼容 no-op），
--no-snapshot 关闭）；缺原文链接不拖垮核验结论，按提醒呈现。
布局为单文件静态 HTML；打印归档模式单栏全展开并附材料附录。
所有输入输出经路径安全层限制在 skill 工作区 official-docs/ 内。
"""

from __future__ import annotations

import argparse
import html
import json
import re
from urllib.parse import urlparse
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chart_embed  # noqa: E402  图表渲染共享模块（1.4.0，与可视化报告共用）


SKILL_ROOT = Path(__file__).resolve().parent.parent
SEARCH_RESULTS_DIR = SKILL_ROOT / "official-docs" / "search-results"
OUTPUT_DIR = SKILL_ROOT / "official-docs" / "output"
# 默认标题（2026-11-05）：不传 --title 时旧版直接拿它当标题，导致正文页和
# "溯源核验报告：溯源核验报告" 的重复抬头。现在只在无法从文件名/问题推断时才用它。
DEFAULT_TITLE = "溯源核验报告"


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _safe_input_path(value: str, allowed_suffixes: set) -> Path:
    """输入文件必须位于 skill 工作区内且后缀合法，阻断路径遍历。

    兼容只写文件名的调用（1.4.0）：形如 `xxx.json` 的相对路径先在 SKILL_ROOT 下找，
    找不到再到 official-docs/search-results/ 找——避免 Agent 因"文件不在预期位置"
    转而全盘 find/grep 触发宿主安全策略。
    """
    raw = Path(value).expanduser()
    if not raw.is_absolute() and raw.parent == Path("."):
        candidate = SKILL_ROOT / raw
        if not candidate.exists() and (SEARCH_RESULTS_DIR / raw.name).exists():
            raw = SEARCH_RESULTS_DIR / raw.name
    resolved = raw.resolve() if raw.is_absolute() else (SKILL_ROOT / raw).resolve()
    if resolved.suffix.lower() not in allowed_suffixes:
        raise ValueError(f"输入文件后缀必须是 {sorted(allowed_suffixes)} 之一: {value}")
    if not (_is_within(resolved, SEARCH_RESULTS_DIR) or _is_within(resolved, SKILL_ROOT / "config") or resolved == SKILL_ROOT / "SKILL.md"):
        # 允许工作区内任意位置的答案/自检/搜索 JSON（search-results、output、根下临时文件）
        if not _is_within(resolved, SKILL_ROOT):
            raise ValueError(f"输入文件必须位于 skill 工作区内: {value}")
    return resolved


def _safe_output_path(value: str, allowed_suffixes: set, default_suffix: str) -> Path:
    """输出文件必须位于 official-docs/output/ 内且后缀合法。"""
    raw = Path(value).expanduser()
    if raw.suffix.lower() not in allowed_suffixes:
        raw = raw.with_suffix(default_suffix)
    resolved = raw.resolve() if not raw.is_absolute() else raw
    if not _is_within(resolved, OUTPUT_DIR):
        if raw.is_absolute():
            raise ValueError(f"输出文件必须位于 official-docs/output/ 内: {value}")
        resolved = (OUTPUT_DIR / raw.name).resolve()
    return resolved



# ============================================================
# 基础工具
# ============================================================

def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data
    return {"data": data}


def unwrap(data: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(data.get("data"), dict) and data.get("success") is True:
        return data["data"]
    if isinstance(data.get("content"), dict):
        return data["content"]
    return data


def first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value not in (None, "", [], {}) and not isinstance(value, (dict, list)):
            return str(value).strip()
    return ""


# 外部公开材料的来源性质（2026-11-10 与深知系列产品口径对齐）：
# `非官方来源=True` 只表示"不在深知库内"，不等于网站本身不官方，用户可见标签
# 统一写成"外部公开材料 · 政府网站/官方媒体/次级媒体/未知"。
EXTERNAL_SOURCE_NATURES = ("政府网站", "官方媒体", "次级媒体", "未知")
_GOV_ISSUER_TERMS = (
    "国务院", "人民政府", "税务局", "税务分局", "财政部", "财政厅", "财政局",
    "人力资源和社会保障", "人社局", "医保局", "海关", "发展和改革委员会",
    "工业和信息化", "住房和城乡建设", "市场监督管理局", "国家税务总局",
)
_OFFICIAL_MEDIA_TERMS = (
    "中国政府网", "新华社", "新华网", "人民日报", "人民网", "央视", "中央电视台",
    "中国税务报", "中国税务网", "经济日报", "光明日报", "央广网", "中国新闻网",
)
_SECONDARY_MEDIA_TERMS = (
    "新闻", "日报", "晚报", "时报", "商报", "财经", "资讯", "搜狐", "新浪", "网易",
    "腾讯", "百家号", "头条", "知乎", "微博", "公众号", "自媒体",
)


def external_source_nature(item: Dict[str, Any]) -> str:
    """判断外部材料的来源性质；无法判断写"未知"，不与"次级媒体"合并。"""
    explicit = first_str(item.get("来源性质"), item.get("source_nature"))
    if explicit in EXTERNAL_SOURCE_NATURES:
        return explicit
    issuer = first_str(
        item.get("发布或实施机构"), item.get("发布机关"), item.get("数据源"), item.get("来源")
    )
    url = first_str(item.get("源网址"), item.get("sourceUrl"), item.get("url"), item.get("原文链接"))
    host = (urlparse(url).hostname or "").lower() if url else ""
    if host.endswith(".gov.cn") or any(term in issuer for term in _GOV_ISSUER_TERMS):
        return "政府网站"
    if any(term in issuer for term in _OFFICIAL_MEDIA_TERMS):
        return "官方媒体"
    if any(term in issuer for term in _SECONDARY_MEDIA_TERMS) or any(
        term in host for term in ("news", "sina", "sohu", "163.com", "qq.com", "baidu.com")
    ):
        return "次级媒体"
    return "未知"


def short(text: Any, limit: int = 360) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "..."


def strip_tags(text: str) -> str:
    # 只删真正的 HTML 标签（< 后跟字母或 /），不动数学比较的半角小于号：
    # 旧正则 <[^>]+> 会把“800 元 < 1000 元，此时按…赔；\n\n> 引用块”从 < 一路吃到
    # 引用块的 > 开头，删掉中间正文并连带毁掉 quote 识别（2026-11-05 T4 实测丢句）。
    return re.sub(r"</?[a-zA-Z][^>]*>", "", text or "")


_VERSION_BOILERPLATE_RE = re.compile(
    r"(?m)^[ \t]*(?:[-*][ \t]*)?(?:\*\*)?版本与核验说明(?:\*\*)?[ \t]*[：:][\s\S]*?(?=\n[ \t]*\n|\Z)"
)


def strip_version_boilerplate(text: str) -> str:
    """兜底删除答案里的“版本与核验说明”整段（2026-11-05 定稿禁止这类核验元信息）。

    生成侧已在 SKILL.md 明令禁止；这里做确定性兜底，防止模型旧习惯或旧答案复用
    把数据层版本口径带进交付物。只匹配以该短语开头的整段，不误伤正文。
    """
    text = _VERSION_BOILERPLATE_RE.sub("", text or "")
    # 去掉因此悬在文末的分隔线
    return re.sub(r"\n[ \t]*(?:---|\*\*\*)[ \t]*\s*$", "\n", text)


def normalize_citations(text: str) -> str:
    text = strip_tags(text)
    text = strip_version_boilerplate(text)
    text = re.sub(r"【\s*(\d+)\s*】", r"[\1]", text)
    return re.sub(r"\[\^?(\d+)\^?\]", r"[\1]", text)


def strip_citation_markers(text: str) -> str:
    text = strip_tags(text)
    text = re.sub(r"【\s*\d+\s*】", "", text)
    text = re.sub(r"\[\^?\d+\^?\]", "", text)
    text = re.sub(r"[ \t]+(\n)", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + ("\n" if text.strip() else "")


# ============================================================
# 生成前预处理（文号匹配 / 快照兜底；链接活性检测已于 2026-10-08 移除）
# ============================================================

# 快照兜底开关：默认启用。接口 screenShotPath 曾存在路径缺 /A/ 层级的拼接 bug
# （后端修复中）；verify_snapshots 在展示前完成"/A/ 修订 + 格式校验 + 不合法弃用"。
SNAPSHOT_ENABLED = True

def normalize_snapshot_url(url: str) -> str:
    """快照路径容错：接口部分返回值缺 /A/ 层级（实测 60 条中 5 条，补全后即可访问），
    统一规范化为 https://attach.dknowc.cn/snapshot/A/<2位>/<2位>/<哈希>.jpg。"""
    u = (url or "").strip()
    if u.startswith("https://attach.dknowc.cn/snapshot/") and "/snapshot/A/" not in u:
        return u.replace("/snapshot/", "/snapshot/A/", 1)
    return u


def verify_snapshots(articles: List[Dict[str, Any]]) -> int:
    """快照展示前的路径校验（纯本地检查，不发网络请求）：
    组装阶段已由 normalize_snapshot_url 补全 /A/ 层级；此处校验修订后的路径
    是否符合合法格式（https://attach.dknowc.cn/snapshot/A/…），不合法则弃用。

    不做网络可达检测：attach 前置雷池 WAF 的拦截与请求方 IP 风控相关
    （检测机高频请求会被拦而普通用户正常），可达性实测会误杀好快照；
    快照文件本身的存在性由可信搜索侧的数据质量保障。
    """
    dropped = 0
    for a in articles:
        u = (a.get("快照链接") or "").strip()
        if not u:
            continue
        if u.startswith("https://attach.dknowc.cn/snapshot/A/"):
            continue
        a["快照链接"] = ""
        dropped += 1
    return dropped


def _normalize_title_for_match(value: str) -> str:
    """标题归一（文号匹配用）：全半角/大小写归一，去书名号括号与空白。"""
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = re.sub(r"[《》〈〉「」『』\[\]【】()（）]", "", text)
    text = re.sub(r"\s+", "", text)
    return text


def attach_doc_numbers(articles: List[Dict[str, Any]], payload: Dict[str, Any]) -> int:
    """从同一响应的 policyFiles 区按标题本地匹配发文字号（writtenText）。

    文号与检索文章分开展示在同一响应里，本地标题匹配即可拿到，无需接口改动；
    新闻/解读类不在 policyFiles 中（本就无文号），匹配不上则不显示。
    检索库对同一政策文件常有多个抓取变体（新闻稿版/发文版，文号挂在发文版条目上），
    标题精确匹配不上时**不做模糊猜测**（宁缺勿错）——变体识别与回填由 SKILL.md
    选材规则执行：Agent 引用政策文件时优先带文号的发文版条目。
    """
    doc_numbers: Dict[str, str] = {}
    for holder in (payload.get("content") if isinstance(payload.get("content"), dict) else {},
                   (payload.get("content") or {}).get("data") if isinstance((payload.get("content") or {}).get("data"), dict) else {},
                   payload.get("data") if isinstance(payload.get("data"), dict) else {}):
        for pf in (holder.get("policyFiles") or []):
            if not isinstance(pf, dict):
                continue
            doc_no = first_str(pf.get("writtenText"), pf.get("发文字号"))
            title = first_str(pf.get("title"), pf.get("标题"))
            if doc_no and title:
                doc_numbers.setdefault(_normalize_title_for_match(title), doc_no)
    if not doc_numbers:
        return 0
    matched = 0
    for a in articles:
        if a.get("文号"):
            continue
        no = doc_numbers.get(_normalize_title_for_match(first_str(a.get("文章标题"), a.get("title"), a.get("标题"))))
        if no:
            a["文号"] = no
            matched += 1
    return matched


def preprocess_articles(articles: List[Dict[str, Any]], payload: Dict[str, Any],
                        skip_link_check: bool = False, snapshot_enabled: bool = True) -> None:
    """extract_sources 前的统一预处理：文号匹配、快照兜底。

    直接改写文章 dict（注入 文号 / 快照链接 字段），供 source_from_article 读取；
    均为幂等操作，多轮渲染不叠加。
    原文链接活性检测已整体移除（2026-10-08 起）——接口返回的链接原样进报告；
    skip_link_check 参数保留为兼容 no-op。
    """
    attach_doc_numbers(articles, payload)
    if snapshot_enabled:
        for a in articles:
            raw_snap = first_str(a.get("screenShotPath"), a.get("screenshot_path"), a.get("快照链接"), a.get("snapshot"))
            a["快照链接"] = normalize_snapshot_url(raw_snap) if raw_snap else ""
        verify_snapshots(articles)
    else:
        for a in articles:
            a["快照链接"] = ""


# ============================================================
# 素材四分类
# ============================================================

KIND_CATALOG = {
    "policy": ("政策依据", "pol"),
    "data": ("数据支撑", "dat"),
    "case": ("参考案例", "cas"),
    "reference": ("表述参考", "ref"),
    "material": ("材料", "mat"),
}


def normalize_kind(raw: str) -> Tuple[str, str, str]:
    """把来源类型文本归一化为（类型键, 中文标签, css 类名）。"""
    text = str(raw or "")
    if "政策" in text or "法规" in text or "依据" in text or "policy" in text.lower():
        key = "policy"
    elif "数据" in text or "统计" in text or "指标" in text or "data" in text.lower():
        key = "data"
    elif "案例" in text or "经验" in text or "做法" in text or "case" in text.lower():
        key = "case"
    elif "表述" in text or "行文" in text or "reference" in text.lower():
        key = "reference"
    else:
        key = "material"
    label, css = KIND_CATALOG[key]
    return key, label, css


def parse_year_month(raw: str) -> Optional[Tuple[int, int]]:
    """从日期文本提取（年, 月）；识别 2025年8月 / 2025-08 / 2025.08 / 2025-08-15。"""
    text = str(raw or "").strip()
    if not text:
        return None
    m = re.search(r"(20\d{2})\s*[年./-]\s*(\d{1,2})", text)
    if m:
        return int(m.group(1)), min(int(m.group(2)), 12)
    m = re.search(r"(20\d{2})", text)
    if m:
        return int(m.group(1)), 1
    return None


# ============================================================
# 素材提取（沿用原数据层）
# ============================================================

def clean_paragraph_noise(text: str) -> str:
    """清洗接口段落文本中的附件链接噪音。

    接口段落内容格式为「段落标题 https://attach.dknowc.cn/file/<正文>」——
    URL 前是段落标题（已由标题链单独展示），URL 本身是附件地址（卡片有"查看原文"入口）。
    摘录只保留 URL 之后的正文；无该前缀时兜底剔除文本中的裸 URL。
    """
    value = str(text or "")
    # 接口 kb 元数据段剔除（2026-10-14）：部分公告类材料把"生效时间：…\n所属地域：…
    # \n成文日期：…\n修订说明：【…】相关文件有下面这些版本：…"这类结构化字段串当段落返回，
    # 展示为摘录是纯噪音（日期/属地已在卡片 meta 行）——段首即"生效时间："且含
    # "所属地域："标签行的整段剔除
    if value.startswith("生效时间：") and "所属地域：" in value:
        return ""
    m = re.search(r"https?://\S*attach\.dknowc\.cn/file/", value)
    if m:
        return value[m.end():].strip()
    value = re.sub(r"https?://\S+", " ", value)
    return re.sub(r"[ \t]{2,}", " ", value).strip()


def paragraph_text(item: Dict[str, Any]) -> str:
    paragraphs = item.get("content") or item.get("段落") or item.get("paragraphs") or item.get("paragraphList")
    if isinstance(paragraphs, list):
        chunks = []
        for para in paragraphs:
            if isinstance(para, dict):
                chunk = first_str(para.get("text"), para.get("内容"), para.get("content"), para.get("summary"), para.get("标题"), para.get("title"))
            else:
                chunk = str(para)
            chunk = clean_paragraph_noise(chunk)
            if chunk:
                chunks.append(chunk)
        text = "\n".join(chunks)
        if text:
            return text
    return clean_paragraph_noise(first_str(
        item.get("摘录"),
        item.get("摘要"),
        item.get("相关段落"),
        item.get("支撑内容"),
        item.get("support"),
        item.get("全文"),
        item.get("content"),
        item.get("text"),
        item.get("snippet"),
    ))


def content_segments(item: Dict[str, Any]) -> List[Dict[str, str]]:
    paragraphs = item.get("content") or item.get("段落") or item.get("paragraphs") or item.get("paragraphList")
    segments: List[Dict[str, str]] = []
    if not isinstance(paragraphs, list):
        return segments
    for para in paragraphs:
        if isinstance(para, dict):
            text = first_str(para.get("text"), para.get("内容"), para.get("content"), para.get("summary"))
            title = first_str(para.get("title"), para.get("标题"), para.get("name"))
            pid = first_str(para.get("id"), para.get("idx"), para.get("index"), para.get("seq"), para.get("编号"))
            if text or title:
                segments.append({"id": pid, "title": title, "text": text})
        else:
            text = first_str(para)
            if text:
                segments.append({"id": "", "title": "", "text": text})
    return segments


_VERIFY_DATE_RE = re.compile(r"最新修正日期?\s*([0-9]{4}-[0-9]{2}-[0-9]{2})")


def neutral_verify_note(note: str) -> str:
    """把材料卡说明收敛成中性事实（2026-11-05 定稿）。

    交付物不评价数据层的版本状态：任何"版本待复核/库内标记失效/建议复核现行版本"
    之类措辞都不进报告。只保留接口给的事实——正文含哪个最新修正日。
    兼容旧 JSON（早期 legal_search 会写评价性说明）。
    """
    note = (note or "").strip()
    if not note:
        return ""
    m = _VERIFY_DATE_RE.search(note)
    if m:
        return f"原文含最新修正日 {m.group(1)}"
    return "原文取自库内全文"


def source_from_article(item: Dict[str, Any], index: int, segment: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    vo = item.get("vo") if isinstance(item.get("vo"), dict) else {}
    segment = segment or {}
    # segment 的 id 是文章内段落序号（每篇各自从 1 起），不是材料角标号，不得用作材料 id，
    # 否则多篇材料的段落 id 同为 "1" 会互相冲突，导致角标绑定错乱。
    explicit_id = first_str(
        item.get("角标"),
        item.get("编号"),
        item.get("index"),
        item.get("idx"),
        item.get("seq"),
        item.get("serialNo"),
        item.get("materialIndex"),
        item.get("referenceIndex"),
        item.get("引用编号"),
        vo.get("index"),
        vo.get("idx"),
    )
    if explicit_id:
        match = re.search(r"\d+", explicit_id)
        explicit_id = match.group(0) if match else ""
    source = {
        "id": explicit_id or str(index),
        "title": first_str(
            item.get("文章标题"),
            item.get("material_name"),
            item.get("材料名称"),
            item.get("title"),
            item.get("标题"),
            item.get("name"),
            vo.get("showTitle"),
            vo.get("title"),
            "未命名来源文章",
        ),
        "agency": first_str(
            item.get("unit") if not isinstance(item.get("unit"), list) else "、".join(str(x) for x in item.get("unit")[:3]),
            item.get("sourceElement"),
            item.get("数据源"),
            item.get("发布或实施机构"),
            item.get("发布机关"),
            item.get("来源"),
            vo.get("typeName"),
            vo.get("sourceName"),
        ),
        "date": first_str(item.get("发布日期"), item.get("date"), item.get("发布时间"), item.get("createDate"), vo.get("dateTime"), vo.get("createDate")),
        "url": first_str(item.get("sourceUrl"), item.get("source_url"), item.get("源网址"), item.get("原文链接"), item.get("url"), item.get("原文"), vo.get("sourceUrl"), vo.get("url")),
        "policy_url": first_str(item.get("policyUrl"), item.get("policy_url"), vo.get("policyUrl")),
        "excerpt": segment.get("text") or paragraph_text(item),
        "section": first_str(item.get("正文对应"), item.get("section"), item.get("支撑")),
        "kind": first_str(item.get("类型"), item.get("type"), item.get("素材类型"), vo.get("typeName"), "材料"),
        "verify_note": neutral_verify_note(first_str(item.get("核验"), item.get("verification"), item.get("核验说明"))),
        "area": first_str(item.get("intentionArea"), item.get("area"), item.get("地域")),
    }
    # 段落级数据（多段分块展示用）：每段 {chain:[文章,章节,子节...], text}
    # 段落标题自带 > 层级，拆级成面包屑；段落标题与文章标题相同或缺失时链只含文章一级。
    segments = []
    for seg in content_segments(item):
        seg_title = first_str(seg.get("title"))
        levels = [lvl.strip() for lvl in re.split(r"\s*>\s*", seg_title) if lvl.strip()] if seg_title else []
        if levels and levels[0] == source["title"]:
            levels = levels[1:]
        seg_text = clean_paragraph_noise(seg.get("text"))
        chain_lvls = [source["title"]] + levels
        segments.append({"chain": chain_lvls, "text": strip_leading_chain(seg_text, chain_lvls)})
    source["segments"] = segments
    # 首段章节位置（兼容旧单行引用处）
    first_chain = segments[0]["chain"][1:] if segments else []
    source["doc_section"] = " › ".join(first_chain)
    source["chain_full"] = " › ".join(segments[0]["chain"]) if segments else ""
    # 发文字号（接口 policyFiles.writtenText，本地标题匹配）
    source["doc_number"] = first_str(item.get("文号"), item.get("doc_number"))
    # 所属搜索条件（多路检索分组）与引用状态（未引用=接口召回但正文未采用）
    source["search_key"] = first_str(item.get("搜索条件"), item.get("search_key"))
    # 检索通道（深知深度搜索 / 深知可信搜索）：由检索脚本在产物上打标、merge 透传，
    # 供过程条/hero 按接口通道拆分计数；历史 JSON 无该字段时为空（渲染层回退旧文案）
    source["channel"] = first_str(item.get("检索通道"), item.get("channel"))
    # 非官方来源：联网路（searchChannel=webSearch）召回的非权威站点材料。
    # 双口径判定：联网路脚本打标 非官方来源=True；或接口 dataAuthority 返回 数据权威性=非权威。
    source["unofficial"] = bool(item.get("非官方来源")) or str(
        item.get("数据权威性") or item.get("authority") or "").strip() in ("非权威", "non-authoritative")
    source["source_nature"] = external_source_nature(item) if source["unofficial"] else ""
    source["used"] = item.get("已引用", item.get("used", True))
    if not isinstance(source["used"], bool):
        source["used"] = True
    # 快照是接口自带的存档副本，统一作为附加回看入口展示（2026-10-08 起不再做
    # 链接活性探测，原文链接原样进报告；快照仅做本地格式校验，不发网络请求）。
    source["snapshot"] = first_str(item.get("快照链接"), item.get("snapshot"), item.get("screenShotPath"))
    # 发布日期可信度（实测：「高」=模型治理入库、标题模型精抽；「较高」=门户抓取、标题规则提取）
    source["conf"] = first_str(item.get("发布日期可信度"), item.get("可信度"), item.get("confidence"))
    key, label, css = normalize_kind(source["kind"])
    source["type_key"] = key
    source["type_label"] = label
    source["type_css"] = css
    live_url = bool(source["url"] and source["url"] != "接口未返回")
    source["has_link"] = live_url or bool(source["policy_url"]) or bool(source["snapshot"])
    # 核验状态只看摘录可比对；原文链接死活与快照有无是回看通道问题，不影响核验结论
    source["verified"] = bool(source["excerpt"])
    return source


def extract_articles_from_search(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """可信搜索 dependable/search 格式：content.data.检索文章。"""
    content = payload.get("content") if isinstance(payload.get("content"), dict) else payload
    data = content.get("data") if isinstance(content.get("data"), dict) else content.get("data")
    if isinstance(data, dict) and isinstance(data.get("检索文章"), list):
        return [x for x in data["检索文章"] if isinstance(x, dict)]
    return []


def extract_articles_from_deep(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """深度搜索 deep-query/v3 非流式格式：{"data": {"searches": [{"result": [...]}], "common_articles": [...]}}。

    按源网址去重摊平；为每篇材料注入"搜索条件"（子查询的地域·查询词），供知识专库检索分组筛选。
    """
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    searches = data.get("searches")
    if not isinstance(searches, list):
        return []
    seen: set = set()
    out: List[Dict[str, Any]] = []

    def _add(article: Any, search_key: str) -> None:
        if not isinstance(article, dict):
            return
        key = str(article.get("源网址") or article.get("文章标题") or "")
        if key and key in seen:
            return
        if key:
            seen.add(key)
        if search_key and not article.get("搜索条件"):
            article["搜索条件"] = search_key
        out.append(article)

    for search in searches:
        if not isinstance(search, dict):
            continue
        areas = "、".join(str(a) for a in (search.get("areas") or []))
        query = str(search.get("query") or "").strip()
        label = f"{areas}·{query[:14]}" if areas else query[:18]
        for article in search.get("result") or []:
            _add(article, label)
    for article in data.get("common_articles") or []:
        # 多查询公共文章给独立分组名（空 key 落不进任何分组 tab，无法筛选）
        _add(article, "多查询公共")
    return out


def extract_reference_materials(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    materials = payload.get("referenceMaterials")
    if isinstance(materials, list):
        return [x for x in materials if isinstance(x, dict)]
    return []


def extract_sources(payload: Dict[str, Any],
                    skip_link_check: bool = False, snapshot_enabled: bool = True) -> List[Dict[str, str]]:
    raw_sources: List[Dict[str, Any]] = []
    raw_sources.extend(extract_reference_materials(payload))
    is_deep = bool(extract_articles_from_deep(payload))
    raw_sources.extend(extract_articles_from_search(payload))
    raw_sources.extend(extract_articles_from_deep(payload))
    if not is_deep:
        # 可信搜索单次检索：材料统一标注"本次检索"分组（多轮检索由 Agent 合并 JSON 后各自携带）
        for item in raw_sources:
            if not item.get("搜索条件"):
                item["搜索条件"] = "本次检索"

    # 生成前预处理：文号匹配（policyFiles）、快照兜底（不做链接活性探测）
    preprocess_articles(raw_sources, payload, skip_link_check=skip_link_check, snapshot_enabled=snapshot_enabled)

    sources: List[Dict[str, str]] = []
    seen = set()
    for item in raw_sources:
        # 一篇材料一张卡：段落合并为摘录（paragraph_text 拼接全部段落），不按段落拆卡——
        # 溯源 JSON 的 materials 与正文角标按"材料"粒度一一对应，拆段会使编号错位。
        source = source_from_article(item, len(sources) + 1)
        # 去重键（2026-10-08 修复）：归一化「标题+URL」。旧键含 id（递增序号每条不同）
        # 等于从不去重——同一篇文章跨提取器/多段片段全部出卡（实测曾出现同名卡片 ×17）。单边缺失退用其一，均缺失退摘录前缀。
        t_key = re.sub(r"\s+", "", source["title"] or "")
        u_key = (source["url"] or "").strip().rstrip("/")
        if u_key == "接口未返回":
            u_key = ""
        if t_key and u_key:
            key = ("tu", t_key, u_key)
        elif t_key:
            key = ("t", t_key)
        elif u_key:
            key = ("u", u_key)
        else:
            key = ("e", (source["excerpt"] or "")[:80])
        if key in seen:
            continue
        seen.add(key)
        if not source["id"]:
            source["id"] = str(len(sources) + 1)
        sources.append(source)
    return sources


def extract_answer(payload: Dict[str, Any]) -> str:
    resp = payload.get("resp")
    if isinstance(resp, dict):
        answer = first_str(resp.get("content"), resp.get("answer"), resp.get("text"))
        if answer:
            return normalize_citations(answer)
    answer = first_str(payload.get("answer"), payload.get("contentText"), payload.get("text"))
    if answer:
        return normalize_citations(answer)
    articles = extract_articles_from_search(payload)
    if articles:
        rows = ["可信搜索召回了以下重点来源文章："]
        for idx, item in enumerate(articles[:8], start=1):
            rows.append(f"[{idx}] {first_str(item.get('文章标题'), item.get('title'), item.get('标题'), '未命名来源文章')}")
        return "\n".join(rows)
    deep_articles = extract_articles_from_deep(payload)
    if deep_articles:
        rows = ["深度搜索召回了以下重点来源文章："]
        for idx, item in enumerate(deep_articles[:8], start=1):
            vo = item.get("vo") if isinstance(item.get("vo"), dict) else {}
            rows.append(f"[{idx}] {first_str(item.get('文章标题'), vo.get('showTitle'), vo.get('title'), item.get('title'), '未命名来源文章')}")
        return "\n".join(rows)
    return "接口返回中未识别到正文内容；请查看知识专库或原始 JSON。"


def extract_question(payload: Dict[str, Any]) -> str:
    content = payload.get("content") if isinstance(payload.get("content"), dict) else payload
    data = content.get("data") if isinstance(content.get("data"), dict) else {}
    first_query = ""
    searches = data.get("searches") if isinstance(data.get("searches"), list) else None
    if searches and isinstance(searches[0], dict):
        first_query = str(searches[0].get("query") or "")
    return first_str(
        payload.get("question"),
        payload.get("input"),
        payload.get("query"),
        data.get("用户问题"),
        first_query,
        content.get("query"),
        content.get("question"),
    )


def citation_ids(answer: str) -> List[str]:
    ids: List[str] = []
    for match in re.finditer(r"\[(\d+)\]", answer):
        item = match.group(1)
        if item not in ids:
            ids.append(item)
    return ids


# ============================================================
# 核验计算（报告级）
# ============================================================

SELF_CHECK_ITEMS = [
    ("fact_basis", "事实有据"),
    ("binding", "角标绑定"),
    ("consistency", "答案一致"),
    ("freshness", "时效确认"),
    ("no_gap", "无未核验断言"),
]

SELF_CHECK_LABELS = dict(SELF_CHECK_ITEMS)
SELF_CHECK_LABELS.update({
    "事实有据": "事实有据", "角标绑定": "角标绑定", "答案一致": "答案一致",
    "时效确认": "时效确认", "无未核验断言": "无未核验断言",
})


_VERSION_EVAL_WORDS = (
    "待复核", "库内标记", "标记为失效", "已失效", "建议复核", "现行版本",
    "失效副本", "回退到失效", "版本状态",
)


_VERIFY_FACT_WORDS = ("最新修正日", "原文取自", "材料日期")


def scrub_version_eval(text: str) -> str:
    """自检说明里去掉版本状态评价（2026-11-05 定稿：交付物不评价数据层版本）。

    不含版本评价词的原样返回；含的话只保留中性事实子句（最新修正日/原文取自/材料日期），
    其余整句丢弃——评价措辞被拿掉后，"正文已如实写明"这类半句会变成没头没尾的话。
    """
    text = (text or "").strip()
    if not text or not any(w in text for w in _VERSION_EVAL_WORDS):
        return text
    parts = [p.strip() for p in re.split(r"[，,；;。]", text) if p.strip()]
    kept = [p for p in parts if any(k in p for k in _VERIFY_FACT_WORDS)]
    return "，".join(kept)


def classify_check_value(raw: Any) -> Tuple[str, str]:
    """把自检项的值解析为（状态, 核验说明）。

    兼容多种写法：`pass` / `true` / `通过` / `通过：说明文字` / `✓` 等；
    值后面的说明文字保留下来供核验单展示。无法识别的状态按未记录（none）处理：
    描述性文本不等于"未通过"——红项只给显式声明的未通过，避免书写格式问题
    被放大成核验未通过（2026-09-20 WorkBuddy 实测：Agent 把备注写成自检值导致 5/7 红项）。
    """
    text = str(raw or "").strip()
    lowered = text.lower()
    for prefix in ("未通过", "不通过", "不合格", "fail", "false", "否", "✗", "no"):
        if lowered.startswith(prefix):
            return "fail", text[len(prefix):].lstrip("：:，,、 ").strip()
    for prefix in ("已通过", "通过", "合格", "pass", "ok", "true", "是", "✓", "yes"):
        if lowered.startswith(prefix):
            return "pass", text[len(prefix):].lstrip("：:，,、 ").strip()
    return "none", text


# 用户可见报告不得暴露内部检索实现（三阶段/联网通道）；自检说明里模型常写这些词，
# 渲染前统一换成用户能理解的口径。只作用于自检说明，不改正文与材料内容。
USER_FACING_REPLACEMENTS = (
    ("宿主 WebSearch", "公开网络检索"),
    ("外部联网材料", "公开网络材料"),
    ("外部联网", "公开网络"),
    ("可信联网", "可信搜索"),
    ("阶段三", "补充检索"),
    ("阶段二", "补充检索"),
    ("阶段一", "检索"),
    ("非官方来源", "外部公开材料"),
)


def user_facing_text(text: str) -> str:
    out = str(text or "")
    for src, dst in USER_FACING_REPLACEMENTS:
        out = out.replace(src, dst)
    return out


def normalize_self_check(raw: Any) -> Optional[Dict[str, Tuple[str, str]]]:
    if not isinstance(raw, dict):
        return None
    items: Dict[str, Tuple[str, str]] = {}
    for key, value in raw.items():
        # 只认五项标准自检键（英文/中文）；白名单外的多余键（如 Agent 自行追加的
        # "备注""待核验/下一步补充"等描述性键）不构成"交付前检查"定义的核验项，
        # 直接忽略不计入——核验单只统计定义过的检查项（2026-09-20 实测修正）。
        label = SELF_CHECK_LABELS.get(key) or SELF_CHECK_LABELS.get(str(key))
        if not label:
            continue
        status, note = classify_check_value(value)
        items[label] = (status, scrub_version_eval(user_facing_text(note)))
    return items or None


def compute_verification(answer: str, sources: List[Dict[str, str]], payload: Dict[str, Any],
                         generated_at: Optional[datetime] = None) -> Dict[str, Any]:
    """核验报告单数据。只计算脚本真实可得的结果，不虚构通过。"""
    generated_at = generated_at or datetime.now()

    # ① 依据溯源：摘录可比对 + 原文链接可回看。
    # 只统计被正文引用的材料——未引用召回材料未进入正文核验流程，其缺链在自身卡片上如实标注，
    # 不应拖累"正文依据可交付"的报告级结论。
    # 缺原文链接（接口对部分治理库文章不返回源网址，属数据源覆盖问题而非核验工作缺失）
    # 不再拖垮整体结论——报告的正常结论即为"核验完成"，缺链在指标行黄色提醒并在卡片标注；
    # 缺摘录（正文依据无可比对的原文）仍视为核验问题计入未通过。
    cited_sources = [s for s in sources if s.get("used", True)]
    missing_links = [s["title"] for s in cited_sources if not s.get("has_link")]
    missing_excerpts = [s["title"] for s in cited_sources if not (s.get("excerpt") or "").strip()]
    trace_passed = len(cited_sources) - len(missing_excerpts)

    # ② 引用绑定：正文角标与来源卡一一对应（按角标出现次数计，与用户在正文中数到的一致）
    cited = citation_ids(answer)
    all_marks = re.findall(r"\[(\d+)\]", answer)
    source_ids = {s["id"] for s in sources}
    unbound_ids = [cid for cid in cited if cid not in source_ids]
    unbound = [cid for cid in unbound_ids for _ in range(all_marks.count(cid))]
    no_citation = bool(sources) and not cited

    # ③ 时效检查：材料日期范围与历史材料计数
    # ③ 时效只统计**正文依据**（2026-09-29 起）：sources 含未引用召回材料，
    # 此前误用全集，未引用材料里的异常日期（如接口标注的未来年份）会写进交付物口径。
    dated = [parse_year_month(s.get("date")) for s in cited_sources]
    dated = [d for d in dated if d]
    freshness = None
    old_count = 0
    if dated:
        freshness = {
            "min": min(dated),
            "max": max(dated),
            "old_count": sum(1 for y, _ in dated if y <= generated_at.year - 3),
        }

    # ④ 类型覆盖：**正文依据**的素材四分类分布（口径同③，2026-09-29 修复）
    coverage = {key: 0 for key in KIND_CATALOG}
    for s in cited_sources:
        coverage[s.get("type_key", "material")] = coverage.get(s.get("type_key", "material"), 0) + 1

    # ⑤ 成稿自检：由溯源 JSON 的 self_check 传入，未传入如实显示未记录
    self_check_raw = None
    for holder in (payload, payload.get("content") if isinstance(payload.get("content"), dict) else {}):
        self_check_raw = self_check_raw or holder.get("selfCheck") or holder.get("self_check")
    self_items = normalize_self_check(self_check_raw)
    self_check = None
    if self_items:
        passed = sum(1 for status, _ in self_items.values() if status == "pass")
        failed = sum(1 for status, _ in self_items.values() if status == "fail")
        # 状态只由显式 fail 决定：none（值无法识别，如描述性文本）不拖垮结论，
        # 显示为"通过，N 项未记录"——红项只给真正声明未通过的项。
        self_check = {"items": self_items, "passed": passed, "total": len(self_items), "failed": failed,
                      "status": "fail" if failed else "pass"}
    else:
        self_check = {"items": {}, "passed": 0, "total": len(SELF_CHECK_ITEMS), "failed": 0, "status": "missing"}

    # 政策效力：无法自动判定现行效力，列出建议人工复核
    policy_count = coverage.get("policy", 0)

    trace_ok = cited_sources and not missing_excerpts
    binding_ok = (not unbound) and not no_citation
    # 自检显式"未通过"纳为报告级否决项：不能自检失败还顶部打绿章。
    self_check_ok = self_check["status"] != "fail"
    overall_passed = bool(trace_ok and binding_ok and self_check_ok)

    reasons = []
    if not sources:
        reasons.append("没有找到来源文章")
    if no_citation:
        reasons.append("正文里没有来源角标，对不上来源文章")
    if unbound:
        reasons.append(f"有 {len(unbound)} 处角标找不到对应来源文章")
    if self_check["status"] == "fail":
        reasons.append("交付前检查有没过的项")
    if missing_links:
        reasons.append(f"有 {len(missing_links)} 条正文依据没有原文链接或存档快照，无法回看")

    if overall_passed and missing_links:
        # 摘录可比对、结论成立，但确有材料无回看通道时，顶部表述要与事实一致
        overall_label = f"核验完成，其中 {len(missing_links)} 条依据无原文或存档快照可回看"
    else:
        overall_label = "核验完成，正文依据逐条对过原文" if overall_passed else "核验未完全通过"

    return {
        "overall": {
            "passed": overall_passed,
            "label": overall_label,
            "reasons": reasons,
        },
        "traceability": {"total": len(cited_sources), "passed": trace_passed,
                         "missing_links": missing_links, "missing_excerpts": missing_excerpts},
        "binding": {"total": len(all_marks), "bound": len(all_marks) - len(unbound), "unbound": unbound_ids, "no_citation": no_citation},
        "freshness": freshness,
        "coverage": coverage,
        "self_check": self_check,
        "policy_count": policy_count,
        "manual_checks": [str(x) for x in (payload.get("verificationChecks") or payload.get("verification_checks") or []) if str(x).strip()],
    }


# ============================================================
# 过程回顾 / 热词（真实计算，不虚构流程）
# ============================================================

def compute_process_stats(sources: List[Dict[str, str]], answer: str,
                         calls: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """过程回顾条数据：检索次数、每组检索的召回/采用数、入库与引用计数。

    全部来自素材自带的真实字段（search_key 分组、used 引用状态、正文角标计数），
    不虚构任何流程步骤。
    """
    order: List[str] = []
    for s in sources:
        key = (s.get("search_key") or "").strip()
        if key and key not in order:
            order.append(key)
    cond_rows = []
    for key in order:
        group = [s for s in sources if (s.get("search_key") or "").strip() == key]
        # 该路检索的接口通道（深知深度搜索/深知可信搜索）：取组内多数通道
        chan_counts: Dict[str, int] = {}
        for s in group:
            ch = (s.get("channel") or "").strip()
            if ch:
                chan_counts[ch] = chan_counts.get(ch, 0) + 1
        channel = max(chan_counts, key=chan_counts.get) if chan_counts else ""
        # 每路调用增量（1.6.0）：merge 的 search_meta.calls 按标签对齐到分组行，
        # 过程条展示『该路新增 N 篇 · 补充 K 段』——补搜的实际贡献不被分组统计吞掉
        delta = ""
        if calls:
            matched = next((c for c in calls if str(c.get("label") or "").strip() == key), None)
            if matched is None:
                matched = next((c for c in calls
                                if str(c.get("label") or "").strip()
                                and key.startswith(str(c.get("label")).strip()[:12])), None)
            if matched:
                delta = f"新增 {matched.get('new_articles', 0)} 篇 · 补充 {matched.get('added_paragraphs', 0)} 段"
        cond_rows.append({
            "key": key,
            "total": len(group),
            "used": sum(1 for s in group if s.get("used", True)),
            "channel": channel,
            "delta": delta,
        })
    n_searches = len(cond_rows) or (1 if sources else 0)
    # 深度/可信互斥计数（2026-10-16 修复）：多数通道为拼接值（"深知深度搜索、深知可信搜索"）
    # 的组同时含两个关键词，若不互斥会被两边各计一次——WB 实测"补搜 10 次"被虚报成 13 次，
    # 与过程条明细行（if/else 口径）自相矛盾。此处与明细行同口径：含"深度"优先归深度。
    deep_routes = sum(1 for r in cond_rows if "深度" in r.get("channel", ""))
    trusted_routes = sum(1 for r in cond_rows if "可信" in r.get("channel", "") and "深度" not in r.get("channel", ""))
    used_count = sum(1 for s in sources if s.get("used", True))
    unused_count = len(sources) - used_count
    external_materials = sum(1 for s in sources if s.get("unofficial") or s.get("pending"))
    n_cite_marks = len(re.findall(r"\[(\d+)\]", answer))
    return {
        "conds": cond_rows,
        "n_searches": n_searches,
        "deep_routes": deep_routes,
        "trusted_routes": trusted_routes,
        "external_materials": external_materials,
        "has_cond_detail": bool(cond_rows),
        "n_materials": len(sources),
        "used_count": used_count,
        "unused_count": unused_count,
        "n_cite_marks": n_cite_marks,
    }


def render_inline_markdown(text: str, citation_repl) -> str:
    body = esc(text)
    body = re.sub(r"`([^`]+)`", r"<code>\1</code>", body)
    body = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", body)
    body = re.sub(r"__(.+?)__", r"<strong>\1</strong>", body)
    body = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", body)
    body = re.sub(r"(?<!_)_([^_\n]+_)(?!_)", r"<em>\1</em>", body)
    body = re.sub(r"\[(\d+)\]", citation_repl, body)
    return body


def is_markdown_table_separator(line: str) -> bool:
    stripped = line.strip().strip("|")
    if not stripped:
        return False
    cells = [cell.strip() for cell in stripped.split("|")]
    return all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)


def split_markdown_table_row(line: str) -> List[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def render_markdown_table(lines: List[str], citation_repl) -> str:
    header = split_markdown_table_row(lines[0])
    body_lines = lines[2:] if len(lines) > 1 and is_markdown_table_separator(lines[1]) else lines[1:]
    head_html = "".join(f"<th>{render_inline_markdown(cell, citation_repl)}</th>" for cell in header)
    rows = []
    for line in body_lines:
        cells = split_markdown_table_row(line)
        rows.append("<tr>" + "".join(f"<td>{render_inline_markdown(cell, citation_repl)}</td>" for cell in cells) + "</tr>")
    return f'<div class="tbl-wrap"><table class="data-tbl"><thead><tr>{head_html}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def _safe_url(url: str) -> str:
    """外链协议白名单（1.6.0）：仅允许 http/https，其余（javascript:/data: 等）置空不渲染。"""
    value = str(url or "").strip()
    if value.lower().startswith(("http://", "https://")):
        return value
    return ""


def sanitize_table_html(text: str) -> str:
    """清洗接口表格 HTML：仅保留 table/thead/tbody/tr/td/th/br，去脚本样式与属性。"""
    cleaned = re.sub(r"(?is)<script.*?</script>", "", text)
    cleaned = re.sub(r"(?is)<style.*?</style>", "", cleaned)
    cleaned = re.sub(r"\s+on\w+\s*=\s*(['\"]).*?\1", "", cleaned)
    cleaned = re.sub(r"\s+(href|src)\s*=\s*(['\"]).*?\2", "", cleaned)
    allowed = {"table", "thead", "tbody", "tr", "td", "th", "br"}

    def tag_repl(match: re.Match[str]) -> str:
        closing, name = match.group(1), match.group(2).lower()
        if name not in allowed:
            return ""
        return f"<{closing}{name}>"

    cleaned = re.sub(r"<\s*(/?)\s*([a-zA-Z0-9]+)(?:\s+[^>]*)?>", tag_repl, cleaned)
    # thead 修复（1.6.0，对齐公文写作 3.9.0）：接口偶发把数据行整片包在 thead 里，
    # 清洗后若直接透传会全部渲染成表头底色。逐表处理：表内任意 thead 含 ≥2 个 <tr>
    # 时，按文档顺序取全部行重建为「首行 thead + 其余 tbody」，行内容不变。
    def fix_table(m_t: re.Match[str]) -> str:
        block = m_t.group(0)
        rows = re.findall(r"(?is)<tr>.*?</tr>", block)
        thead_rows = re.findall(r"(?is)<tr>.*?</tr>", 
                                (re.search(r"(?is)<thead>(.*?)</thead>", block) or re.match(r"", "")).group(1)
                                if re.search(r"(?is)<thead>(.*?)</thead>", block) else "")
        if len(thead_rows) <= 1 or len(rows) <= 1:
            return block
        return "<table><thead>" + rows[0] + "</thead><tbody>" + "".join(rows[1:]) + "</tbody></table>"

    return re.sub(r"(?is)<table>.*?</table>", fix_table, cleaned)


def render_excerpt_html(text: str) -> str:
    value = str(text or "")
    if "<table" not in value.lower():
        return f'<div class="sc-excerpt plain">{esc(value)}</div>'
    return f'<div class="sc-excerpt rich">{sanitize_table_html(value)}</div>'


def parse_answer_blocks(answer: str, valid_ids: set, chip_map: Optional[Dict[str, str]] = None,
                         strip_cites: bool = False) -> Tuple[List[Dict[str, Any]], set]:
    """把正文 Markdown 解析为结构化块；同时收集全部角标。

    角标渲染为原型式 sup.cite 上标胶囊；表格内的角标不再落进单元格，
    统一在表下"表内依据"出处行用正常胶囊呈现。
    """

    def jb_html(cid: str) -> str:
        jb = chip_map.get(cid)
        if not jb:
            return ""
        if jb.get("url"):
            btn_txt = "查看全文" if jb.get("url") else "查看存档全文"
            _u = _safe_url(jb["url"])
            link = (f'<a class="jb-src" href="{esc(_u)}" target="_blank" rel="noopener noreferrer">'
                    f'{ARROW_SVG}<span>{btn_txt}</span></a>') if _u else ""
        else:
            link = ""
        # 原文直达区展示标题链（多段分块，各段带链——快速人工核验的核心抓手）
        segs = jb.get("segments") or []
        if segs:
            quote = ""
            seg_idx = -1
            for seg in segs:
                text = (seg.get("text") or "").strip()
                if not text:
                    continue
                seg_idx += 1
                if "<table" in text.lower():
                    # 表格不能静态写进 span（解析器会拆散）：此处留占位，
                    # 表格数据由 render_html 汇总注入页尾 JSON，展开时 JS 填充
                    tbl_key = f"{cid}-{seg_idx}"
                    jb.setdefault("_tables", {})[tbl_key] = sanitize_table_html(text)
                    body_txt = f'<span class="sc-excerpt rich tbl-holder" data-tbl="{esc(tbl_key)}"></span>'
                else:
                    body_txt = f'<span class="sc-excerpt">{esc(text)}</span>'
                inner = f'<i class="jb-no">{esc(cid)}</i>{body_txt}'
                item = f'<span class="jb-quote" role="button" tabindex="0">{inner}</span>'
                quote += render_crumb(seg.get("chain") or []) + item
        elif jb["excerpt"]:
            inner = f'<i class="jb-no">{esc(cid)}</i><span>{esc(jb["excerpt"])}</span>'
            quote = f'<span class="jb-quote" role="button" tabindex="0">{inner}</span>'
        else:
            quote = ""
        site_html = (f'<span class="jb-site"><span class="dot"></span>{esc(jb.get("site") or "")}</span>'
                     if (jb.get("site") or "").strip() else "")
        if jb.get("unofficial"):
            nature = jb.get("source_nature") or "未知"
            site_html = (f'<span class="jb-unofficial" title="外部公开材料（{esc(nature)}），仅供参考，建议以官方口径复核">'
                         f'外部公开材料 · {esc(nature)}</span>' + site_html)
        return (
            f'<span class="jb" data-cite="{esc(cid)}">'
            f'<button class="jb-name" type="button" aria-expanded="false">{CARET_SVG}'
            f'<i class="jb-id">{esc(cid)}</i>'
            f'<span class="jb-txt">{esc(jb["title"])}</span></button>'
            f'<span class="jb-body"><span class="jb-head"><span class="jb-label">{SRC_ICO_SVG}溯源原文：</span>{link}</span>'
            f'{site_html}'
            f'{quote}</span></span>'
        )

    def make_block_repl(block_text: str):
        """按块构造角标替换器：同段同材料只保留最后一次出现的角标（前处整体删除），
        最后一处挂数字角标 + 引文胶囊——一段中同一材料只出现一次。
        正文页（strip_cites=True）直接删掉全部角标，输出干净正文。"""
        if strip_cites:
            return lambda match: ""
        remaining: Dict[str, int] = {}
        for cid in re.findall(r"\[(\d+)\]", block_text):
            remaining[cid] = remaining.get(cid, 0) + 1

        def repl(match: re.Match[str]) -> str:
            cid = match.group(1)
            remaining[cid] = max(0, remaining.get(cid, 1) - 1)
            if remaining[cid] > 0:
                return ""
            if cid in chip_map:
                return jb_html(cid)
            # 未绑定角标（无对应材料）：红色数字警示，绝不按位置猜测
            return f'<sup class="cite unresolved" data-cite="{esc(cid)}" title="核验依据 [{esc(cid)}?]">{esc(cid)}?</sup>'

        return repl

    blocks: List[Dict[str, Any]] = []
    lines = answer.split("\n")
    idx = 0
    while idx < len(lines):
        block = lines[idx].strip()
        if not block:
            idx += 1
            continue
        # 引文胶囊位置规范：角标与后随标点换位——标点紧跟文字，胶囊放标点之后
        # （避免胶囊把句号挤到下一行孤悬，对齐深知晓原型"…内容。～出处"形态）
        # 连续角标序列须整体换位（如 [13][14]；），否则标点被夹在两个胶囊中间
        block = re.sub(r"((?:\[\d+\])+)([。；，、！？：；,.])", r"\2\1", block)
        # Markdown 引用块（2026-11-04）：法条原文常写成 “> 第四十七条 …”。
        # 解析器原先不认 “>”，会把它当普通段落、把大于号原样显示；这里收成 quote 块。
        if block.startswith(">"):
            quote_lines: List[str] = []
            while idx < len(lines) and lines[idx].strip().startswith(">"):
                quote_lines.append(re.sub(r"^>\s?", "", lines[idx].strip()))
                idx += 1
            quote_text = "\n".join(quote_lines).strip()
            if quote_text:
                repl_q = make_block_repl(quote_text)
                ids_q = [] if strip_cites else citation_ids(quote_text)
                html_q = "<br>".join(
                    render_inline_markdown(line, repl_q) for line in quote_lines if line.strip()
                )
                blocks.append({"kind": "quote", "html": html_q, "cites": ids_q})
            continue
        ids = [] if strip_cites else citation_ids(block)
        repl = make_block_repl(block)
        heading_match = re.match(r"^(#{1,4})\s+(.+)$", block)
        if heading_match:
            blocks.append({"kind": "heading", "level": len(heading_match.group(1)),
                           "text": heading_match.group(2).strip(), "cites": ids, "repl": repl})
            idx += 1
        elif "|" in block and idx + 1 < len(lines) and is_markdown_table_separator(lines[idx + 1]):
            table_lines = [block, lines[idx + 1].strip()]
            idx += 2
            while idx < len(lines) and "|" in lines[idx].strip() and lines[idx].strip():
                table_lines.append(lines[idx].strip())
                idx += 1
            # 表格单元格内不放角标：设计稿（reference/sample_trace_report.html）里
            # 引用只有"句后 jb 胶囊→展开原文"一种形态，表格内没有对应交互；
            # 2026-11-04 曾用紧凑上标补丁，实测在报告页只是一个点不动的裸数字。
            # 现在统一：单元格内角标去掉，表格下一行出"表内依据"出处行，用正常 jb 胶囊。
            def _table_cite(match: re.Match[str]) -> str:
                return ""

            table_ids = [] if strip_cites else citation_ids("\n".join(table_lines))
            blocks.append({"kind": "table", "html": render_markdown_table(table_lines, _table_cite),
                           "cites": table_ids})
            if table_ids:
                basis = " ".join(jb_html(cid) for cid in table_ids if cid in (chip_map or {}))
                if basis:
                    blocks.append({"kind": "table_basis", "html": basis, "cites": table_ids})
        elif block in {"---", "***"}:
            blocks.append({"kind": "hr", "html": '<hr class="doc-divider">', "cites": []})
            idx += 1
        elif re.match(r"^[-*]\s+", block):
            body = render_inline_markdown(re.sub(r"^[-*]\s+", "", block), repl)
            blocks.append({"kind": "list_item", "numbered": False, "html": body, "cites": ids})
            idx += 1
        elif re.match(r"^\d+[.)]\s+", block):
            number = re.match(r"^(\d+)[.)]\s+", block).group(1)
            body = render_inline_markdown(re.sub(r"^\d+[.)]\s+", "", block), repl)
            blocks.append({"kind": "list_item", "numbered": True, "number": number, "html": body, "cites": ids})
            idx += 1
        else:
            kind = "para"
            # 引用出处行（2026-11-05）：法条引用块后常单起一行“《法名》第X条 [n]”标注出处。
            # 原先按普通段落渲染，字号颜色与正文相同，读起来像断在段尾的不完整句子。
            # 这里识别“紧跟 quote 块、以《开头、含条/款、无句号”的短行，按引用标注样式输出。
            plain = re.sub(r"\[\d+\]", "", block).strip()
            if (blocks and blocks[-1].get("kind") == "quote"
                    and plain.startswith("《") and "》" in plain
                    and len(plain) <= 160
                    and not any(ch in plain for ch in "。；？！")
                    and ("条" in plain or "款" in plain or "编" in plain)):
                kind = "quote_attr"
            blocks.append({"kind": kind, "html": render_inline_markdown(block, repl), "cites": ids})
            idx += 1
    return blocks, valid_ids


def split_heading_number(text: str) -> Tuple[Optional[str], str]:
    m = re.match(r"^\s*([一二三四五六七八九十]+|\d+)\s*[、.．]\s*(.+)$", text)
    if m:
        return m.group(1), m.group(2)
    return None, text


def group_sections(blocks: List[Dict[str, Any]]) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """按标题层级切分章节卡。返回（报告标题, 章节列表）。

    规则：最浅层级标题若唯一且居文首，视为报告标题提出；其下一级为卡片边界。
    无标题的短公文整篇一卡。
    """
    if not blocks:
        return None, [{"title": None, "blocks": []}]
    heading_indexes = [i for i, b in enumerate(blocks) if b["kind"] == "heading"]
    if not heading_indexes:
        return None, [{"title": None, "blocks": blocks}]

    levels = sorted({blocks[i]["level"] for i in heading_indexes})
    shallow = levels[0]
    shallow_indexes = [i for i in heading_indexes if blocks[i]["level"] == shallow]

    doc_title = None
    boundary = shallow
    if len(shallow_indexes) == 1 and heading_indexes[0] == shallow_indexes[0]:
        doc_title = blocks[shallow_indexes[0]]["text"]
        blocks = blocks[shallow_indexes[0] + 1:]
        if len(levels) > 1:
            boundary = levels[1]

    sections: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {"title": None, "blocks": []}
    for b in blocks:
        if b["kind"] == "heading" and b["level"] <= boundary:
            if current["title"] is not None or current["blocks"]:
                sections.append(current)
            current = {"title": b["text"], "blocks": []}
        else:
            current["blocks"].append(b)
    if current["title"] is not None or current["blocks"]:
        sections.append(current)
    return doc_title, sections


# ============================================================
# 各部分渲染
# ============================================================

def build_chip_data(sources: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    """行内引文胶囊数据：id → {title, site, url, excerpt}。

    角标后渲染原型式 jb（行内小胶囊，点击展开块级卡）。摘录展示完整
    原文原段、不截断——段内去重后重复量可控，核对场景下就地读全文。
    """
    chip_map: Dict[str, Dict[str, str]] = {}
    for source in sources:
        cid = source["id"]
        if cid in chip_map:
            continue
        meta_bits = [v for v in [source.get("agency"), source.get("date")] if v and v != "未知来源"]
        url = source.get("url") if (source.get("url") and source["url"] != "接口未返回") else (source.get("policy_url") or "")
        site_bits = ([source["doc_number"]] if source.get("doc_number") else []) + meta_bits
        chip_map[cid] = {
            "title": short(source.get("title") or "未命名来源文章", 30),
            "site": " · ".join(site_bits) or "来源站点",
            "url": url,
            "snapshot": source.get("snapshot") or "",
            "excerpt": (source.get("excerpt") or "").strip(),
            "segments": source.get("segments") or [],
            "unofficial": bool(source.get("unofficial")),
            "source_nature": source.get("source_nature") or "",
        }
    return chip_map


def render_source_links(url: str, policy_url: str = "", snapshot: str = "") -> str:
    """链接区：原文可回看 / 无源网址但有快照。接口返回的链接原样展示（不做活性探测，
    2026-10-08 起）；快照是接口对原文的存档副本，文案如实标注。"""
    links = []
    if _safe_url(url) and url != "接口未返回":
        links.append(f'<a href="{esc(_safe_url(url))}" target="_blank" rel="noopener">查看全文 ↗</a>')
    # policy_url 是接口另给的官方原文入口（如最高法官网），与商业库镜像并存时单独展示，
    # 避免"数据源写着威科、卡片却没有官方可点链接"。
    if _safe_url(policy_url) and policy_url != url:
        links.append(f'<a class="official" href="{esc(_safe_url(policy_url))}" target="_blank" rel="noopener">官方原文 ↗</a>')
    # 有哪个显示哪个：快照统一展示"查看存档全文"，不做原文失效的状态解释
    if _safe_url(snapshot):
        links.append(f'<a class="snap" href="{esc(_safe_url(snapshot))}" target="_blank" rel="noopener">查看存档全文 ↗</a>')
    # 回看通道只有原网址与快照（2026-09-29 起：外链知识专库属老能力，已移除）
    if not links:
        return ""
    return '<div class="sc-links">' + "".join(f"<span>{link}</span>" for link in links) + "</div>"


def render_verify_panel(v: Dict[str, Any]) -> str:
    """核验报告单：报告级核验结论 + 五项指标。"""
    # 核验明细（逐条"已完成…"文本可能很长）默认折叠，点开才展开——不用悬浮 tooltip（触屏不可用）
    _checks = [str(x) for x in (v.get("manual_checks") or []) if str(x).strip()]
    manual_checks_html = ""
    if _checks:
        _items = "".join(f"<li>{esc(x)}</li>" for x in _checks)
        manual_checks_html = (f'<details class="v-checks"><summary>查看核验明细（{len(_checks)} 项）</summary>'
                              f'<ul>{_items}</ul></details>')
    ov = v["overall"]
    state = "ok" if ov["passed"] else "fail"
    stamp = '<span class="v-stamp">已核验</span>' if ov["passed"] else '<span class="v-stamp bad">核验未通过</span>'
    reasons_html = ""
    if ov["reasons"]:
        reasons_html = '<div class="v-reasons">' + "；".join(esc(r) for r in ov["reasons"]) + "</div>"

    tr = v["traceability"]
    n_no_link = len(tr.get("missing_links") or [])
    if not tr["total"]:
        tr_html = ('<div class="vi"><span class="s fail">✗ 依据溯源 0/0</span>'
                   '<span class="d">未识别到来源文章</span></div>')
    elif tr["passed"] == tr["total"] and not n_no_link:
        tr_html = (f'<div class="vi"><span class="s ok">✓ 依据溯源 {tr["passed"]}/{tr["total"]}</span>'
                   f'<span class="d">每条素材摘录可比对，原文或存档快照可回看</span></div>')
    elif tr["passed"] == tr["total"]:
        # 摘录齐全但有材料没有回看通道：不得照写"原文或存档快照可回看"
        # （此前 missing_links 算出却从未参与结论，属虚假背书）
        tr_html = (f'<div class="vi"><span class="s warn">◐ 依据溯源 {tr["passed"]}/{tr["total"]}</span>'
                   f'<span class="d">摘录可比对，其中 {n_no_link} 条没有原文链接或存档快照、无法回看</span></div>')
    else:
        detail = f'待补摘录 {len(tr.get("missing_excerpts") or [])} 条'
        if n_no_link:
            detail += f'；{n_no_link} 条无原文链接或快照'
        tr_html = (f'<div class="vi"><span class="s warn">◐ 依据溯源 {tr["passed"]}/{tr["total"]}</span>'
                   f'<span class="d">{detail}</span></div>')

    bd = v["binding"]
    if bd.get("no_citation"):
        bd_html = (f'<div class="vi"><span class="s fail">✗ 引用对应 0/0</span>'
                   f'<span class="d">正文里没有来源角标，{v["traceability"]["total"]} 篇来源文章对不上正文</span></div>')
    elif not bd["total"]:
        bd_html = '<div class="vi"><span class="s none">— 引用对应 0/0</span><span class="d">正文里没有来源角标</span></div>'
    elif not bd["unbound"]:
        bd_html = (f'<div class="vi"><span class="s ok">✓ 引用对应 {bd["bound"]}/{bd["total"]}</span>'
                   f'<span class="d">正文每一处引用都已对回来源文章，点开即可核对原文</span></div>')
    else:
        unbound_text = "、".join(f"[{esc(x)}]" for x in bd["unbound"][:8])
        bd_html = (f'<div class="vi"><span class="s fail">✗ 引用对应 {bd["bound"]}/{bd["total"]}</span>'
                   f'<span class="d">对不上的角标 {unbound_text}</span></div>')

    fr = v["freshness"]
    if fr:
        rng = f"{fr['min'][0]}-{fr['min'][1]:02d}～{fr['max'][0]}-{fr['max'][1]:02d}"
        # 2026-09-29 起：去掉"N 条年头较久，按参考口径使用"——对长期有效的
        # 政策法规偏严，且"按参考口径使用"读者无从理解；old_count 仍照常计算留待后续。
        fr_html = f'<div class="vi"><span class="s ok">✓ 材料新旧 已核</span><span class="d">材料日期 {esc(rng)}</span></div>'
    else:
        fr_html = '<div class="vi"><span class="s none">— 材料新旧 未记录</span><span class="d">材料没标发布日期</span></div>'

    # 材料构成：材料类型四分类（政策依据型/数据支撑型/…）非本检索接口返回字段
    # → 没有类型数据时**整行不显示**，不再渲染"材料没标类型"这种永远为空的占位行（2026-09-28 修复）。
    cov = v["coverage"]
    parts = [f"{KIND_CATALOG[k][0]} {cov[k]}" for k in ("policy", "data", "case", "reference") if cov.get(k)]
    cov_html = (f'<div class="vi"><span class="s ok">✓ 材料构成</span>'
                f'<span class="d">{esc(" · ".join(parts))}</span></div>') if parts else ""

    uq = v.get("unmatched_quotes") or []
    uq_html = ""
    if uq:
        uq_html = (f'<div class="vi"><span class="s warn">◐ 引文待核对 {len(uq)} 处</span>'
                   f'<span class="d">正文引用块未在本次材料中找到原文：{esc("；".join(uq[:2]))}</span></div>')

    ext = v.get("external") or []
    ext_html = ""
    if ext:
        bits = "；".join(f"{x.get('title')}{(' ' + x['value']) if x.get('value') else ''}"
                         f"（{x.get('source') or '来源未标'} {x.get('date') or ''}）".replace(" ）", "）").strip()
                         for x in ext[:3])
        more = f" 等 {len(ext)} 项" if len(ext) > 3 else ""
        ext_html = (f'<div class="vi"><span class="s warn">◐ 外部数据 {len(ext)} 项</span>'
                    f'<span class="d">{esc(bits)}{esc(more)} · 来源已标注，未计入深知材料核验</span></div>')

    sc = v["self_check"]
    selfcheck_notes_html = ""
    if sc["status"] == "pass":
        item_names = "、".join(sc["items"].keys()) if sc["items"] else "、".join(label for _, label in SELF_CHECK_ITEMS)
        unrecorded = sc["total"] - sc["passed"] - sc.get("failed", 0)
        sc_head = f'✓ 交付前检查 {sc["passed"]}/{sc["total"]}' if not unrecorded else \
            f'✓ 交付前检查 通过（{unrecorded} 项未记录）'
        sc_html = (f'<div class="vi"><span class="s ok">{sc_head}</span>'
                   f'<span class="d">{esc(item_names)}</span></div>')
        # 逐项说明默认折叠（触屏可用），不再用鼠标悬浮 tooltip。
        # 版本评价子句被清洗掉后说明可能为空，用"已核对"占位，保证五项齐全。
        note_items = [(label, note or "已核对") for label, (status, note) in sc["items"].items()]
        if note_items:
            _li = "".join(f"<li><b>{esc(label)}</b>：{esc(note)}</li>" for label, note in note_items)
            selfcheck_notes_html = (f'<details class="v-checks"><summary>查看交付前检查说明（{len(note_items)} 项）</summary>'
                                    f'<ul>{_li}</ul></details>')
    elif sc["status"] == "fail":
        failed_parts = []
        for label, (status, note) in sc["items"].items():
            if status == "fail":
                suffix = f"（{note[:40]}…）" if len(note) > 40 else (f"（{note}）" if note else "")
                failed_parts.append(label + suffix)
        sc_html = (f'<div class="vi"><span class="s fail">✗ 交付前检查 {sc["passed"]}/{sc["total"]}</span>'
                   f'<span class="d">没过的项：{esc("、".join(failed_parts))}</span></div>')
    else:
        sc_html = '<div class="vi"><span class="s none">— 交付前检查 未记录</span><span class="d">本次溯源 JSON 没写入检查结果</span></div>'

    # "现行效力"人工复核提示行已移除（2026-09-19 起）：
    # 政策是否现行有效无法自动判定，此提示对用户无操作价值；policy_count 仅保留在计算层不再展示。
    manual = ""

    return f"""
    <div class="verify {state}">
      <div class="v-head"><span class="v-shield">{'✓' if ov['passed'] else '!'}</span>{esc(ov['label'])}{stamp}</div>
      {reasons_html}
      <div class="v-grid">
        {tr_html}{bd_html}{fr_html}{cov_html}{sc_html}{uq_html}{ext_html}{manual}
      </div>
      <div class="v-note">AI 已完成自验收，正文依据可逐条点开原文复核。{selfcheck_notes_html}{manual_checks_html}</div>
    </div>"""


SRC_ICO_SVG = ('<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" '
               'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
               '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>'
               '<path d="M9 13h6M9 17h4"/></svg>')
ARROW_SVG = ('<svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2.2" '
             'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 17 17 7M9 7h8v8"/></svg>')
CARET_SVG = ('<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.4" '
             'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>')


_CN_DIGITS = {"〇": "0", "零": "0", "一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
              "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}


def _norm_heading(text: Any) -> str:
    return re.sub(r"[\s、，,。.：:；;（）()\[\]【】]+", "", str(text or ""))


def _cn_to_digit(text: str) -> str:
    return _CN_DIGITS.get(text.strip(), text.strip())


def resolve_chart_anchor(sections: List[Dict[str, Any]], anchor: Any) -> int:
    """把图表的 section 锚点解析为章节序号（1-based）；解析不到返回 0。

    锚点容错：可写章节号（`二` / `2` / `二、`）、章节标题（`一次性奖励金额对比`）、
    或带序号的完整标题（`二、一次性奖励金额对比`）——统一去空白与顿号后按
    「序号相等」或「标题互相包含」匹配。
    """
    raw = _norm_heading(anchor)
    if not raw:
        return 0
    want_num = _cn_to_digit(raw[0]) if raw and _cn_to_digit(raw[0]).isdigit() else ""
    for idx, sec in enumerate(sections, 1):
        number, title_text = split_heading_number(sec["title"] or "")
        if want_num and number and _cn_to_digit(_norm_heading(number)) == want_num and len(raw) == 1:
            return idx
        title_norm = _norm_heading(title_text)
        if title_norm and (title_norm in raw or raw in title_norm):
            return idx
    return 0


def render_section_cards(sections: List[Dict[str, Any]], sources: List[Dict[str, str]],
                         charts_by_section: Optional[Dict[int, str]] = None,
                         id_prefix: str = "sec") -> str:
    """正文渲染（原型复刻）：chapter（h2）+ lead/para 段落，引用走段内角标 + 知识专库材料卡。

    溯源卡按段内角标顺序输出；同一材料在同段只出一张，跨段重复出现标记 dup-card（灰化）。
    charts_by_section：{章节序号: 图表 HTML}——图表**跟着它展示的数据所在的章节走**
    （1.4.0：不再固定堆在报告末尾），插在该章节正文之后。
    """
    parts: List[str] = []
    first_para = True
    source_ids = {s["id"] for s in sources}
    charts_by_section = charts_by_section or {}
    for sec_idx, sec in enumerate(sections, 1):
        number, title_text = split_heading_number(sec["title"] or "")
        chapter_title = f"{number}、{title_text}" if (number and title_text) else (title_text or "")
        sec_cites: List[str] = []
        for b in sec["blocks"]:
            for cid in b.get("cites", []):
                if cid not in sec_cites:
                    sec_cites.append(cid)
        if chapter_title:
            badge_html = ""
            if sec_cites:
                unbound = sum(1 for cid in sec_cites if cid not in source_ids)
                state = "bad" if unbound else ""
                text = f"本章引用 {len(sec_cites)} 处" + (f" · {unbound} 处未绑定" if unbound else " · 已核验")
                badge_html = f'<span class="sec-badge {state}">{esc(text)}</span>'
            parts.append(f'<section class="chapter" id="{id_prefix}-{sec_idx}">'
                         f'<header class="ch-head"><h2>{esc(chapter_title)}</h2>{badge_html}</header>')
        for b in sec["blocks"]:
            if b["kind"] == "heading":
                parts.append(f'<p class="para"><b class="kw">{esc(b["text"])}</b></p>')
                first_para = False
                continue
            cls = "lead" if first_para else "para"
            first_para = False
            if b["kind"] == "list_item":
                marker = f'{esc(b.get("number", "•"))}.' if b.get("numbered") else "•"
                parts.append(f'<p class="{cls}"><b class="kw">{marker}</b> {b["html"]}</p>')
            elif b["kind"] == "hr":
                parts.append('<hr class="doc-divider">')
            elif b["kind"] == "quote":
                parts.append(f'<blockquote class="doc-quote">{b["html"]}</blockquote>')
            elif b["kind"] == "quote_attr":
                # 引用出处标注：附着在上一段引用块下方的小字出处行，不是正文句子
                parts.append(f'<p class="para q-attr">{b["html"]}</p>')
            elif b["kind"] == "table_basis":
                # 表格依据行：单元格内角标去掉后，引用的材料以正常胶囊列在表下一行
                parts.append(f'<p class="para tbl-basis">表内依据：{b["html"]}</p>')
            else:
                parts.append(f'<p class="{cls}">{b["html"]}</p>')
        if chapter_title:
            if sec_idx in charts_by_section:
                parts.append(charts_by_section[sec_idx])
            parts.append("</section>")
    return "\n".join(parts)


def strip_leading_chain(text: str, chain: List[str]) -> str:
    """剥掉段落文本开头与标题链各级重复的前缀。

    接口部分材料的"内容"字段自带段落标题前缀（个别还重复两遍），标题链已承载
    位置信息，摘录开头再出现同级文本即冗余；逐级最长匹配剥离，无重复则原样返回。
    """
    t = (text or "").strip()
    cands = set()
    for lvl in chain:
        lvl = (lvl or "").strip()
        if lvl:
            cands.add(lvl)
            # 粘连标题（接口未给分隔符，如"建设交通强省5.民航和低空"）拆出编号尾部子串
            parts = re.split(r"(?<=[\u4e00-\u9fff])(?=\d+[.、])", lvl)
            if len(parts) > 1 and parts[-1].strip():
                cands.add(parts[-1].strip())
    levels = sorted(cands, key=len, reverse=True)
    changed = True
    while changed and t:
        changed = False
        for lvl in levels:
            if t.startswith(lvl):
                t = t[len(lvl):].lstrip(" \n\r\t、。；;，,").strip()
                changed = True
                break
    return t


def render_crumb(chain: List[str]) -> str:
    """面包屑标题链：文章 › 章 › 节（标题链是模型生成的结构化位置，核验核心抓手）。
    段落本身无章节层级（链上只有文章名）时不显示——材料卡标题已是文章名，
    单独一行重复文章名对定位无增量（2026-09-19 反馈）。"""
    parts = [esc(level) for level in chain if level]
    if len(parts) < 2:
        return ""
    return '<span class="crumb">' + ' <i>›</i> '.join(parts) + "</span>"


def render_segments(source: Dict[str, Any]) -> str:
    """多段分块摘录：每段独立区块，各带自己的标题链——段落结构与位置直接可见。"""
    segments = source.get("segments") or []
    if not segments:
        return render_excerpt_html(source.get("excerpt") or "接口返回中未识别到可展示的摘录。")
    blocks = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        blocks.append(f'<div class="seg-block">{render_crumb(seg.get("chain") or [])}'
                      f'{render_excerpt_html(text)}</div>')
    return "".join(blocks) if blocks else render_excerpt_html(source.get("excerpt") or "接口返回中未识别到可展示的摘录。")


def render_source_card(source: Dict[str, str], for_print: bool = False) -> str:
    if not source.get("used", True):
        # 未引用召回材料：不标"已核验"（未进入正文核验流程），只标可否查看
        vk = ('<span class="sc-vk" style="color:var(--muted)">可查看全文</span>' if source.get("has_link")
              else '<span class="sc-vk warn">待补链接</span>')
        note_html = ""
    elif source.get("verified") and source.get("has_link"):
        note = source.get("verify_note") or "摘录可比对，原文或存档快照可回看"
        # 2026-11-05 定稿：交付物不评价数据层的版本状态，数据返回即按生效使用。
        # 徽标只表示"摘录+原文链接可回看"，不承载版本结论。
        vk = f'<span class="sc-vk ok" title="{esc(note)}">✓ 已核验</span>'
        note_html = f'<div class="sc-vnote">{esc(short(note, 90))}</div>' if source.get("verify_note") else ""
    elif source.get("verified"):
        # 摘录可比对，但接口没给原文链接/快照：不能打“已核验”绿标，回看通道缺失要显性提示。
        vk = '<span class="sc-vk warn">◐ 待补原文链接</span>'
        note_html = ""
    else:
        reason = "待补原文链接" if not source.get("has_link") else "待补摘录"
        vk = f'<span class="sc-vk warn">◐ {reason}</span>'
        note_html = ""
    links = render_source_links(source.get("url"), source.get("policy_url", ""), source.get("snapshot", ""))
    # 关键性行：有文号（接口 policyFiles 匹配）时"文号 · 数据源 · 日期"，否则"数据源 · 日期"。
    # 文号必须是标准格式——政府公文"〔年份〕序号"（杭政函〔2022〕81号）、公告/令类"第X号"
    # （财政部税务总局公告2023年第19号、主席令第三十五号、国务院令第765号，含汉字数字）；
    # 描述性文字（"XX印发"类自造描述）不显示，当无文号处理。
    _dn = source.get("doc_number") or ""
    _dn = _dn if re.search(r"〔\d{4}〕\s*\d+\s*号|第\s*(?:\d+|[〇零一二三四五六七八九十百千]+)\s*号", _dn) else ""
    meta_parts = [v for v in [_dn, source.get("agency"), source.get("date"), source.get("area")]
                  if v and v != "未知来源"]
    meta = " | ".join(meta_parts)
    # 高可信徽标：仅"发布日期可信度=高"（模型治理入库、标题模型精抽）的材料；"较高"（门户抓取）不标。
    conf_badge = ""
    if source.get("conf") == "高":
        conf_badge = ('<span class="sc-conf" title="发布日期可信度：高。内容经模型治理入库，'
                      '标题为模型从原文动态抽取，非规则提取">高可信</span>')
    # 已引用材料显示角标编号；未引用召回材料显示"未引用"灰标（不占正文角标号）
    id_html = f'<span class="sc-id">[{esc(source["id"])}]</span>' if source.get("used", True) else '<span class="sc-unused">未引用</span>'
    # 外部公开材料徽标：库外材料按来源性质标注，不再笼统写"非官方来源"
    nature = source.get("source_nature") or "未知"
    unofficial_badge = (
        f'<span class="sc-unofficial" title="外部公开材料（{esc(nature)}），仅供参考，建议以官方口径复核">'
        f'外部公开材料 · {esc(nature)}</span>'
        if source.get("unofficial") else ""
    )
    body_html = (f'<div class="sc-head">{id_html}'
                 f'<span class="sc-type">{esc(source["type_label"])}</span>{conf_badge}{unofficial_badge}{vk}</div>'
                 f'<h4>{esc(source.get("title"))}</h4>'
                 f'<div class="sc-meta">{esc(meta)}</div>'
                 f'{note_html}'
                 f'{render_segments(source)}'
                 f'{links}')
    if for_print:
        # 打印附录版：无交互属性，避免与专库卡片 id 冲突
        return f'<article class="scard print-only {source["type_css"]}">{body_html}</article>'
    unused_attr = "" if source.get("used", True) else ' data-unused="1"'
    return (
        f'<article class="scard {source["type_css"]}" id="src-{esc(source["id"])}" data-type="{esc(source["type_key"])}" '
        f'data-cite-id="{esc(source["id"])}" data-search="{esc(source.get("search_key", ""))}"{unused_attr}>{body_html}</article>'
    )


def render_process_bar(stats: Dict[str, Any], verification: Dict[str, Any]) -> str:
    """过程回顾条：静态回放真实流程。无思考流数据，不做"深度思考"步骤。"""
    ov = verification["overall"]
    tr = verification["traceability"]
    first_query = stats["conds"][0]["key"] if stats["conds"] else ""
    # 步骤一标题按接口通道拆分（深度搜索与可信搜索是两个接口，不混计成一个数）；
    # 无通道信息（历史 JSON）时退回"深知检索 N 路"
    deep_n = stats.get("deep_routes", 0)
    trusted_n = stats.get("trusted_routes", 0)
    if deep_n and trusted_n:
        step1_title = f"深度搜索 {deep_n} 路 · 可信补搜 {trusted_n} 路"
    elif deep_n:
        step1_title = f"深知深度搜索 {deep_n} 路"
    elif trusted_n:
        step1_title = f"深知税务检索 {trusted_n} 路"
    else:
        step1_title = f"深知检索 {stats['n_searches']} 路"
    detail_rows = "".join(
        f'<div class="pd-row"><b>{esc(row["key"])}'
        + (f'（{"深度搜索" if "深度" in row.get("channel", "") else "税务检索"}）' if row.get("channel") else "")
        + f'</b><span>召回 {row["total"]} 条 · 正文采用 {row["used"]} 条'
        + (f' · {esc(row["delta"])}' if row.get("delta") else '')
        + '</span></div>'
        for row in stats["conds"]
    ) or '<div class="pd-row"><span>本次溯源 JSON 未记录各次检索条件</span></div>'
    detail_hint = f'{esc(short(first_query, 26))}…' if (stats["n_searches"] > 1 and first_query) else "查看检索明细"
    if stats["n_searches"] > 1:
        step1_sub = f"共 {stats['n_searches']} 路检索 · {detail_hint}"
    elif first_query:
        step1_sub = esc(short(first_query, 26))
    else:
        step1_sub = "深知税务检索"
    step4_state = "done" if ov["passed"] else "bad"
    step4_icon = "✓" if ov["passed"] else "!"
    step4_label = "核验完成" if ov["passed"] else "核验未完全通过"
    step4_sub = (
        "结论：正文依据逐条对过来源（外部公开材料已标注来源性质）"
        if ov["passed"] and stats.get("external_materials")
        else "结论：正文依据逐条对过原文" if ov["passed"]
        else esc(short("；".join(ov["reasons"]) or "见核验报告单", 30))
    )
    # 研究资料统计（1.5.0）：--research-notes-file 传入时在步骤 2 体现（事实/口径行数）；
    # 未传不显示（如实，不虚构）
    rn = stats.get("research_notes") or {}
    rn_bits = ""
    if rn.get("facts") is not None:
        rn_bits = f"研究资料 {rn['facts']} 项事实 · {rn.get('calibers', 0)} 项口径 ｜ "

    return f"""
    <section class="process" aria-label="AI 自验收">
      <div class="p-head"><b>AI 自验收</b><span>交付前由 AI 自动完成，数字来自本次任务的真实记录</span></div>
      <ol class="p-steps">
        <li class="p-step expandable" id="p-step-search" role="button" tabindex="0" title="展开各路检索明细">
          <span class="p-no">1</span>
          <div class="p-txt"><b>{esc(step1_title)}</b><i>{step1_sub}</i></div>
        </li>
        <li class="p-arrow" aria-hidden="true">›</li>
        <li class="p-step">
          <span class="p-no">2</span>
          <div class="p-txt"><b>来源文章入库 {stats['n_materials']} 篇</b><i>{rn_bits}正文采用 {stats['used_count']} · 召回未采用 {stats['unused_count']}</i></div>
        </li>
        <li class="p-arrow" aria-hidden="true">›</li>
        <li class="p-step">
          <span class="p-no">3</span>
          <div class="p-txt"><b>逐条比对原文</b><i>依据溯源 {tr['passed']}/{tr['total']} · 摘录可比对</i></div>
        </li>
        <li class="p-arrow" aria-hidden="true">›</li>
        <li class="p-step {step4_state}">
          <span class="p-no">{step4_icon}</span>
          <div class="p-txt"><b>{esc(step4_label)}</b><i>{step4_sub}</i></div>
        </li>
      </ol>
      <div class="p-detail" id="p-detail">{detail_rows}</div>
    </section>"""


def normalize_external_data(raw: Any) -> List[Dict[str, str]]:
    """外部公开数据（LPR、汇率、统计口径等）条目规范化（2026-11-05 产品口径）。

    skill 允许联网取公开数据，但必须标注来源，并在报告里单列——不得冒充深知材料、
    不占正文法条角标、不计入“依据溯源”与“引用对应”。
    """
    if isinstance(raw, dict):
        raw = raw.get("外部数据") or raw.get("externalData") or raw.get("items") or []
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        row = {
            "title": first_str(item.get("名称"), item.get("title"), item.get("指标")),
            "value": first_str(item.get("数值"), item.get("value"), item.get("取值")),
            "source": first_str(item.get("来源"), item.get("source"), item.get("发布机构")),
            "date": first_str(item.get("公布日期"), item.get("date"), item.get("发布日期")),
            "url": first_str(item.get("链接"), item.get("url"), item.get("源网址")),
            "note": first_str(item.get("说明"), item.get("note")),
        }
        if row["title"] or row["value"]:
            out.append(row)
    return out


def render_external_cards(items: List[Dict[str, str]]) -> str:
    cards = []
    for i, it in enumerate(items, 1):
        meta = " | ".join(x for x in (it.get("value"), it.get("source"), it.get("date")) if x)
        link = (f'<div class="sc-links"><span><a href="{esc(_safe_url(it["url"]))}" target="_blank" '
                f'rel="noopener">查看来源 ↗</a></span></div>') if _safe_url(it.get("url") or "") else ""
        note = f'<div class="sc-vnote">{esc(it["note"])}</div>' if it.get("note") else ""
        cards.append(
            f'<article class="scard ext" id="ext-{i}" data-type="external" data-search="外部数据">'
            f'<div class="sc-head"><span class="sc-id">外部</span><span class="sc-type">公开数据</span>'
            f'<span class="sc-vk warn" title="来自外部公开渠道，未计入深知材料核验">◐ 外部来源 · 未计入核验</span></div>'
            f'<h4>{esc(it.get("title") or "外部公开数据")}</h4>'
            f'<div class="sc-meta">{esc(meta)}</div>{note}{link}</article>'
        )
    return "".join(cards)


def render_library_view(sources: List[Dict[str, str]], doc_title: str = "",
                        external: Optional[List[Dict[str, str]]] = None) -> str:
    """知识专库全屏视图：大搜索 + 检索分组 tabs + 材料卡列表。"""
    external = external or []
    if not sources and not external:
        return ('<section class="view" id="view-library" aria-label="知识专库">'
                '<div class="lib-empty">接口返回中未识别到可展示的来源文章。</div></section>')
    used_sources = [s for s in sources if s.get("used", True)]
    unused_sources = [s for s in sources if not s.get("used", True)]

    # tabs = 检索分组（全部 / 各路检索 / 未引用），数字真实统计
    conds: List[Tuple[str, int]] = []
    for s in sources:
        key = (s.get("search_key") or "").strip()
        if not key:
            continue
        for i, (name, count) in enumerate(conds):
            if name == key:
                conds[i] = (name, count + 1)
                break
        else:
            conds.append((key, 1))
    tabs = [f'<button class="on" data-cond="" type="button">全部（{len(sources) + len(external)}）</button>']
    # 分组过多时折叠（2026-10-14）：多轮检索+补搜会产生 10+ 个分组 tab 平铺拥挤；
    # 按材料数降序保留前 6 组，其余收进"更多分组（N）"展开区（筛选功能不变）
    shown, folded = conds, []
    if len(conds) > 6:
        ranked = sorted(range(len(conds)), key=lambda i: -conds[i][1])
        keep = set(ranked[:6])
        shown = [c for i, c in enumerate(conds) if i in keep]
        folded = [c for i, c in enumerate(conds) if i not in keep]
    for name, count in shown:
        tabs.append(f'<button data-cond="{esc(name)}" type="button">{esc(name)}（{count}）</button>')
    if folded:
        fold_btns = "".join(f'<button data-cond="{esc(name)}" type="button">{esc(name)}（{count}）</button>'
                            for name, count in folded)
        tabs.append(f'<button class="tabs-toggle" type="button" aria-expanded="false">更多分组（{len(folded)}）</button>'
                    f'<span class="tabs-fold">{fold_btns}</span>')
    # 「未引用（N）」筛选胶囊已删（3.8.1 起整行占位、信息由卡片"未引用"灰标自表达）；
    # JS 的 __unused__ 过滤分支保留为兼容死代码

    cards_html = "".join(render_source_card(s) for s in used_sources)
    cards_html += "".join(render_source_card(s) for s in unused_sources)
    cards_html += render_external_cards(external)
    if external:
        tabs.append(f'<button data-cond="外部数据" type="button">外部数据（{len(external)}）</button>')

    lib_title = f"知识专库：{doc_title}" if doc_title.strip() else "知识专库"
    return f"""
    <section class="view" id="view-library" aria-label="知识专库">
      <div class="lib-head">
        <div class="lib-title"><b>{esc(lib_title)}</b></div>
        <div class="lib-searchWrap">
          <span class="lib-searchIcon" aria-hidden="true">⌕</span>
          <input class="lib-search" type="search" placeholder="搜索标题 / 来源 / 摘录…" aria-label="搜索来源文章">
        </div>
        <div class="lib-tabs" role="tablist" aria-label="按检索分组筛选">{"".join(tabs)}</div>
      </div>
      <div class="lib-list" id="lib-list">{cards_html}</div>
      <div class="lib-empty hide" id="lib-empty">没有符合当前筛选的来源文章。</div>
      <div class="lib-foot">来源：深知税务助手 · 每段摘录均取自原文原段</div>
    </section>"""


def render_toc(sections: List[Dict[str, Any]], extra: str = "") -> str:
    """章节目录（滚动 spy）：长报告（≥6 个**有标题**的章节）显示，桌面端左侧浮动。

    无标题节（正文开头的导语段）跳过——此前兜底成「第 N 节」占位项，且该锚点
    #sec-i 在 render_section_cards 里根本不生成（死链接），点它没反应。
    extra 为附加条目 HTML（图表独立呈现时）；门槛按有标题章节数计。
    """
    items = []
    for i, sec in enumerate(sections, 1):
        title = (sec.get("title") or "").strip()
        if not title:
            continue  # 导语内容照常在正文展示，只是不占目录条目
        number, title_text = split_heading_number(title)
        label = f"{number} {title_text}" if (number and title_text) else title_text
        items.append(f'<a href="#sec-{i}" data-sec="{i}">{esc(short(label, 16))}</a>')
    if len(items) < 6 and not extra:
        return ""
    items.append(extra)
    return f'<nav class="toc" aria-label="章节目录">{"".join(items)}</nav>'


def render_print_appendix(sources: List[Dict[str, str]]) -> str:
    """打印归档附录：全部材料卡全展开（屏幕不显示，仅打印）。"""
    if not sources:
        return ""
    cards = "".join(render_source_card(s, for_print=True) for s in sources)
    return (f'<section class="print-appendix" aria-label="来源文章附录（打印归档）">'
            f'<h3>来源文章（全 {len(sources)} 篇）</h3>{cards}</section>')


def safe_output_filename(question: str, timestamp: datetime, fallback: str = "dknowc_search_trace", suffix_ext: str = ".html") -> str:
    raw = question.strip() or fallback
    # 清理对话指令性措辞（1.4.0）：文件名用主题本身，不保留"帮我梳理一下…做个系统"这类口吻
    # （实测：WB 交付物文件名直接带用户原话的"帮我梳理一下…做个系统"，冗长且不像正式交付名）
    for _ in range(3):  # 反复剥离直到无变化（如"请帮我…一下吧"）
        before = raw
        raw = re.sub(r"^(请|麻烦|帮我|帮忙|给我|我想|想问下|请问|你能|帮我看看|帮我看下)+", "", raw)
        # 只剥离明确不是主题词的整理类动词（"分析/对比"等可能是主题的一部分，如"分析化学"，不剥离）
        raw = re.sub(r"^(梳理|整理|汇总|总结|归纳|罗列)(一下)?", "", raw)
        raw = re.sub(r"(一下|吧|谢谢|多谢|可以吗|好吗|行吗|呢)+$", "", raw)
        raw = re.sub(r"(做个?系统(对比|比较|梳理)?|系统对比|系统梳理|对比一下|整理一下|汇总一下|总结一下)$", "", raw)
        raw = raw.strip(" ，,。.、！!？?~～")
        if raw == before:
            break
    raw = raw or question.strip() or fallback
    normalized = re.sub(r"\s+", "_", raw)
    normalized = re.sub(r"[\\/:*?\"<>|#%&{}$!@`+=;'，。、？！：；“”‘’（）()【】《》\[\]]+", "", normalized)
    normalized = normalized.strip("._-")
    if not normalized:
        normalized = fallback
    # 1.5.0：产物名即《标题.html》（无"_溯源核验报告"后缀、无时间戳）；同题重跑的
    # _v2/_v3 版本化由 unique_output_path 的同名检测负责，不依赖时间戳
    stem = normalized[:32].strip("._-") or fallback
    return f"{stem}{suffix_ext}"


# ============================================================
# 样式与脚本（独立常量，避免模板转义）
# ============================================================

PAGE_CSS = """
:root{
  --navy:#20242c; --navy-2:#3a4152;
  --ink:#1f2328; --muted:#6b7280; --line:#e5e7eb; --line-strong:#cbd2dd;
  --brand:#6512ad; --brand-2:#8b5cf6; --brand-soft:#ede9fe;
  --grad:linear-gradient(135deg,#6512ad,#8b5cf6);
  --policy:#0f9d6e; --policy-soft:#e3f5ee;
  --case:#9a6700; --case-soft:#fdf3dc;
  --ref:#4b5563; --ref-soft:#f0f1f4;
  --warn:#9a6700; --danger:#e5484d; --ok:#0f9d6e;
  --shadow-1:0 1px 3px rgba(24,20,40,.04),0 8px 30px rgba(24,20,40,.08);
  --shadow-2:0 3px 9px rgba(101,18,173,.22),0 14px 36px rgba(24,20,40,.14);
  --primary-bright:#8b5cf6; --tint:#f3edfc; --tint-2:#faf7ff; --tint-bd:#e9dff9;
  --tint-strong:#e6d9f9; --tint-bd-strong:#d3bef0; --body-c:#3b4152; --card-bd:#e8e6f0;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,"PingFang SC","HarmonyOS Sans SC","Microsoft YaHei",sans-serif;
  color:var(--ink);background:#f4f5f7;line-height:1.75;font-size:14.5px}
a{color:var(--brand)}

/* ===== 数据可视化（1.4.0 一体化：图表并入核验报告，不再另出独立报告） ===== */
/* 主形态：图表跟着它展示的数据所在章节走（.chart-inline 插在该章节正文之后） */
.chart-inline{margin:18px 0 4px;padding-top:14px;border-top:1px dashed var(--line)}
.chart-h3{margin:0 0 4px;font-size:14px;font-weight:600;color:var(--ink)}
/* 退化形态：锚点缺失/匹配不上时，作为独立章节排在核验报告单之后、正文之前 */
.chart-section{background:#fff;border-radius:14px;box-shadow:var(--shadow-1);padding:22px 26px 18px;margin:0 0 16px}
.chart-h2{margin:0 0 6px;font-size:16px;line-height:1.4}
.chart-note{margin:0 0 14px;color:var(--muted);font-size:12px}
.chart-section .card,.chart-inline .card{box-shadow:none;padding:0;border:0;background:transparent}
.chart-section .viz-panel h3,.chart-inline .viz-panel h3{margin:0 0 6px;font-size:13.5px;font-weight:600;color:var(--ink)}
.viz-duo{display:grid;grid-template-columns:1fr 1fr;gap:8px 18px;align-items:start}
@media(max-width:900px){.viz-duo{grid-template-columns:1fr}}

/* ===== 顶栏 ===== */
.banner{position:sticky;top:0;z-index:50;background:rgba(255,255,255,.94);backdrop-filter:blur(10px);
  border-bottom:1px solid var(--line);padding:8px 22px 9px}
.banner-bar{display:flex;align-items:center;gap:14px;max-width:1080px;margin:0 auto}
.banner-bar .tb-title{flex:0 1 auto;min-width:0;max-width:30%;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap;color:var(--muted);font-size:12.5px}
.banner-bar .view-switch{margin:0 auto}
.banner-bar .tb-tools{flex:0 0 auto}
.banner-bar .view-switch{border-color:#d9c9f4;background:#fff;box-shadow:0 1px 3px rgba(24,20,40,.04)}
.banner-bar .view-switch button{color:#70678a;padding:6px 18px;font-size:13px}
.banner-bar .view-switch button.on{background:var(--grad);color:#fff}
.banner .orig-q{max-width:1080px;margin:7px auto 0;color:var(--ink);font-size:13.5px;line-height:1.6;text-align:center}
/* 长题干改左对齐：居中文本换行断口像句子被切坏（WorkBuddy 实测反馈） */
.banner .orig-q.long{text-align:left;max-width:900px}
.banner .orig-q b{color:var(--brand);margin-right:2px}
.banner .meta{max-width:1080px;margin:3px auto 0;color:var(--muted);font-size:11.5px;letter-spacing:.3px;text-align:center}
  vertical-align:middle;margin:0 6px}
.view-switch{display:inline-flex;border:1px solid var(--line);border-radius:999px;overflow:hidden;background:#fff}
.view-switch button{border:0;background:transparent;color:var(--muted);font-size:12.5px;font-weight:700;
  padding:5px 14px;cursor:pointer}
.view-switch button.on{background:var(--grad);color:#fff}
.tb-tools{display:flex;gap:6px}
.tb-tools button{border:1px solid var(--line);border-radius:8px;background:#fff;color:#3b3550;
  font-size:12.5px;font-weight:700;padding:5px 11px;cursor:pointer}
.tb-tools button:hover{border-color:var(--brand-2);color:var(--brand)}
.tb-tools button[aria-pressed="true"]{background:var(--grad);border-color:var(--brand);color:#fff}
.print-menu{position:relative;display:inline-flex}
.print-drop{position:absolute;top:calc(100% + 6px);right:0;z-index:70;display:flex;flex-direction:column;gap:4px;
  min-width:190px;padding:6px;background:#fff;border:1px solid var(--tint-bd);border-radius:10px;
  box-shadow:var(--shadow-2);text-align:left}
.print-drop[hidden]{display:none}
.print-drop button{border:0;background:none;border-radius:7px;color:var(--ink);font-size:12.5px;font-weight:600;
  padding:8px 12px;cursor:pointer;text-align:left;font-family:inherit;white-space:nowrap}
.print-drop button:hover{background:var(--tint);color:var(--brand)}
.progress{position:absolute;left:0;right:0;bottom:-1px;height:2px;background:transparent}
.progress i{display:block;height:100%;width:0;background:linear-gradient(90deg,#6512ad,#8b5cf6)}


/* ===== 容器与视图 ===== */
.container{max-width:1080px;margin:0 auto;padding:0 18px}
#view-body,#view-report,#view-library{display:none}
.app[data-view="body"] #view-body{display:block}
.app[data-view="report"] #view-report{display:block}
.app[data-view="library"] #view-library{display:block}
#view-body{padding-bottom:26px}
.body-external-note{font-size:12px;line-height:1.65;color:#92400e;background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:8px 11px;margin:0 0 16px}
/* 文头标题（正文页/报告页各自成档的居中标题） */
.paper-title{margin:14px 0 18px;font-size:20px;font-weight:800;color:var(--ink);text-align:center;line-height:1.55;letter-spacing:.3px}
@media (max-width:680px){.paper-title{font-size:17.5px;margin-bottom:16px}}

/* ===== 过程回顾条 ===== */
.process{background:#fff;border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow-1);
  padding:15px 20px 13px;margin:0 auto 16px;position:relative}
.p-head{display:flex;align-items:baseline;gap:10px;margin-bottom:10px}
.p-head b{font-size:14.5px;color:var(--navy);letter-spacing:1px}
.p-head span{font-size:11.5px;color:var(--muted)}
.p-steps{list-style:none;display:flex;align-items:stretch;gap:8px;margin:0;padding:0;flex-wrap:wrap}
.p-step{display:flex;gap:9px;align-items:center;min-width:0;flex:1 1 150px;
  border:1px solid var(--line);border-radius:10px;padding:8px 11px;background:#fafbfc}
.p-no{flex:none;width:24px;height:24px;border-radius:50%;background:var(--grad);color:#fff;
  display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:800}
.p-txt{min-width:0}
.p-txt b{display:block;font-size:12.8px;color:var(--navy);line-height:1.5}
.p-txt i{display:block;font-style:normal;font-size:11px;color:var(--muted);line-height:1.5;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.p-step.done{border-color:#bfe8da;background:#f2faf7}
.p-step.done .p-no{background:var(--ok)}
.p-step.bad{border-color:#f6c9cb;background:#fffafa}
.p-step.bad .p-no{background:var(--danger)}
.p-step.expandable{cursor:pointer}
.p-step.expandable:hover{border-color:var(--brand)}
.p-arrow{align-self:center;color:#b9c6d9;font-size:16px;font-weight:700;flex:none}
.p-detail{display:none;margin-top:10px;border-top:1px dashed var(--line-strong);padding-top:9px}
.p-detail.show{display:block}
.pd-row{display:flex;justify-content:space-between;gap:14px;padding:3px 2px;font-size:12.3px;flex-wrap:wrap}
.pd-row b{color:var(--navy);font-weight:700;min-width:0}
.pd-row span{color:var(--muted)}

/* ===== 核验报告视图 ===== */
#view-report{padding-bottom:26px}
.warn-box{margin:0 0 16px;padding:13px 16px;border:1.5px solid var(--danger);border-radius:10px;
  background:#fdf3f3;color:#8f2626;font-size:13.5px;line-height:1.7}
.verify{margin:0 0 16px;background:#fff;border:1px solid #bfe8da;border-left:4px solid var(--ok);
  border-radius:14px;padding:16px 20px;box-shadow:var(--shadow-1)}
.verify.fail{border-color:#f6c9cb;border-left-color:var(--danger);background:#fffafa}
.v-head{display:flex;align-items:center;gap:9px;font-size:15px;font-weight:800;color:var(--ok)}
.verify.fail .v-head{color:var(--danger)}
.v-shield{display:inline-flex;width:22px;height:22px;border-radius:50%;background:var(--ok);color:#fff;
  align-items:center;justify-content:center;font-size:12px;flex:none}
.verify.fail .v-shield{background:var(--danger)}
.v-stamp{margin-left:auto;font-size:11px;border:1.5px solid var(--ok);color:var(--ok);border-radius:5px;
  padding:1px 8px;letter-spacing:2px;flex:none}
.v-stamp.bad{border-color:var(--danger);color:var(--danger)}
.v-reasons{margin-top:6px;font-size:12.5px;color:var(--danger)}
.v-grid{display:grid;grid-template-columns:1fr 1fr;gap:4px 20px;margin-top:10px}
.vi{display:flex;gap:7px;align-items:baseline;font-size:12.5px;color:#3b3550;line-height:1.7;min-width:0}
.vi .s{font-weight:800;flex:none}
.vi .s.ok{color:var(--ok)}
.vi .s.warn{color:var(--warn)}
.vi .s.fail{color:var(--danger)}
.vi .s.man{color:var(--case)}
.vi .s.none{color:var(--muted)}
.vi .d{color:var(--muted);min-width:0}
.v-note{margin-top:11px;padding-top:9px;border-top:1px dashed var(--line);font-size:11.5px;color:var(--muted);line-height:1.7}
.v-checks{margin-top:9px}
.v-checks summary{cursor:pointer;color:var(--brand);font-weight:700;font-size:12.5px;list-style:none;display:inline-flex;align-items:center;gap:5px}
.v-checks summary::-webkit-details-marker{display:none}
.v-checks summary::before{content:"＋";font-weight:700;font-size:12px}
.v-checks[open] summary::before{content:"－"}
.v-checks ul{margin:7px 0 0 4px;padding-left:16px}
.v-checks li{font-size:12.5px;color:var(--sub);line-height:1.72;margin:5px 0}

/* 正文（原型复刻）：章节 / 段落 / 角标 / 句后溯源卡 */
.doc-paper{background:#fff;border-radius:14px;box-shadow:var(--shadow-1);padding:26px 34px 22px;margin:0 0 16px}
.chapter{margin:40px 0 0}
.chapter:first-child{margin-top:6px}
.ch-head{display:flex;align-items:center;gap:14px;margin-bottom:18px;scroll-margin-top:86px}
.ch-head h2{font-size:19.5px;font-weight:700;color:var(--ink);letter-spacing:.2px;line-height:1.4;flex:1;min-width:0}
.ch-head::after{content:"";flex-basis:110px;height:1px;background:linear-gradient(90deg,#e9dff9,transparent);order:3;flex-grow:0;flex-shrink:0}
.ch-head .sec-badge{order:4;flex:none;font-size:11.5px;color:var(--ok);background:var(--policy-soft);border-radius:6px;padding:2px 9px;font-weight:700}
.ch-head .sec-badge.bad{color:var(--danger);background:#fdecec}
@media(min-width:1000px){.ch-head::after{flex-basis:200px}}
.lead{font-size:15.5px;line-height:1.95;color:var(--body-c);margin:14px 0;padding:0 2px;word-break:break-word}
.para{font-size:15.5px;line-height:1.95;color:var(--body-c);margin:14px 0;padding:0 2px;word-break:break-word}
.para b.kw,.lead b.kw{font-weight:600;color:var(--ink)}
.doc-quote{margin:14px 0;padding:12px 16px;border-left:3px solid #c9d6e8;background:#f7f9fc;border-radius:0 8px 8px 0;color:#33445a;font-size:15.5px;line-height:1.9;word-break:break-word}
/* 引用出处标注行：《法名》条号 —— 小字灰色，贴在引用块下方 */
.q-attr{font-size:12.5px;color:#8a94a6;margin:-8px 0 14px;line-height:1.6}
.q-unmatched{display:inline-block;margin:0 0 6px;padding:1px 7px;border-radius:5px;background:#fdf3e6;color:#a86412;font-size:11.5px;font-weight:700}
.q-attr::before{content:"—— "}
.q-attr .jb-site{font-size:11px}
.tbl-basis{font-size:12.5px;color:#8a94a6;margin:6px 0 16px;line-height:1.9}
.tbl-basis .jb{margin:2px 6px 2px 0}
.doc-quote b.kw{font-weight:600;color:var(--ink)}
.doc-divider{border:0;border-top:1px solid var(--line);margin:18px 0}
code{padding:1px 5px;border-radius:4px;background:#f3f4f6;color:#3f3d52;
  font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px}
.tbl-wrap{max-width:100%;overflow-x:auto;margin:8px 0}
.data-tbl{width:100%;border-collapse:collapse;border:1px solid var(--line);font-size:13px}
.data-tbl th,.data-tbl td{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top;line-height:1.65}
.data-tbl th{background:#f5f6f8;font-weight:700;color:#3f3d52}

/* 角标 */
.cite{display:inline-flex;align-items:center;justify-content:center;min-width:19px;height:18px;padding:0 5px;margin:0 2px 2px 3px;font-size:10.5px;font-weight:700;font-variant-numeric:tabular-nums;color:var(--brand);background:var(--tint);border:1px solid var(--tint-bd);border-radius:5px;cursor:pointer;vertical-align:super;line-height:1;transition:.14s;position:relative;top:-1px;user-select:none;font-family:inherit}
.cite:hover{background:var(--brand);border-color:var(--brand);color:#fff}
.cite.flash{background:var(--primary-bright);border-color:var(--primary-bright);color:#fff}
.cite.unresolved{color:var(--danger);border-color:#f6c9cb;background:#fdf7f7}

/* 段落级证据 chips（引文卡） */
/* 行内引文 jb（原型复刻）：角标后小胶囊，点击展开块级卡（溯源原文+引文摘录） */
.jb{display:inline-block;vertical-align:top;max-width:100%;margin:2px 4px 2px 0;position:relative}
.jb.active{display:block;margin:12px 0 2px;max-width:none}
.jb-name{display:inline-flex;align-items:center;gap:6px;max-width:380px;min-height:26px;padding:4px 13px;border-radius:13px;border:1px solid var(--tint-bd);background:var(--tint);color:#540e8f;font-family:inherit;font-size:12px;font-weight:600;line-height:18px;cursor:pointer;transition:.16s;white-space:nowrap}
.jb-name:hover{background:#fff;border-color:var(--brand)}
.jb-name .jb-id{flex:none;width:18px;height:18px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-style:normal;font-size:10.5px;font-weight:800;font-variant-numeric:tabular-nums;color:#fff;background:linear-gradient(135deg,#6512ad,#8b5cf6);box-shadow:0 1px 3px rgba(101,18,173,.28)}
.jb-name .jb-txt{overflow:hidden;text-overflow:ellipsis}
.jb-name svg{flex:none;transition:transform .2s}
.jb.active .jb-name{max-width:100%;white-space:normal;line-height:20px;color:var(--ink);background:#fff;font-size:13.5px;font-weight:700;text-align:left}
.jb.active .jb-name svg{transform:rotate(180deg)}
.jb-src{display:inline-flex;align-items:center;gap:5px;min-height:26px;padding:4px 13px;border-radius:13px;background:linear-gradient(135deg,#6512ad,#8b5cf6);color:#fff;font-size:11px;font-weight:600;text-decoration:none;box-shadow:0 2px 8px rgba(101,18,173,.22);transition:.15s;flex-shrink:0}
.jb-src:hover{filter:brightness(1.1)}
.jb-src span{max-width:210px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.jb-body{display:none}
.jb.active .jb-body{position:relative;display:block;margin-top:13px;background:#fff;border:1px solid var(--card-bd);border-radius:12px;padding:13px 15px;box-shadow:var(--shadow-1)}
.jb-head{display:flex;align-items:center;gap:9px;flex-wrap:wrap}
.jb-label{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;font-weight:700;color:var(--brand);letter-spacing:.5px}
.jb-label svg{flex:none}
.jb-unofficial{display:inline-flex;align-items:center;font-size:10.5px;font-weight:700;color:#9a3412;background:#fef3c7;border:1px solid #fcd34d;border-radius:6px;padding:0 7px;margin-right:6px;white-space:nowrap}
.sc-unofficial{display:inline-flex;align-items:center;font-size:10.5px;font-weight:700;color:#9a3412;background:#fef3c7;border:1px solid #fcd34d;border-radius:6px;padding:0 7px;white-space:nowrap}
.jb-site{display:inline-flex;align-items:center;gap:6px;font-size:11.5px;color:#70678a;background:#f6f4fa;
  border:1px solid var(--line);border-radius:999px;padding:3.5px 10px;max-width:100%;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap;margin:0 0 2px}
.jb-site .dot{width:6px;height:6px;border-radius:50%;background:linear-gradient(135deg,#6512ad,#8b5cf6);flex-shrink:0}
.jb-quote{display:flex;gap:9px;align-items:flex-start;margin-top:9px;padding:10px 12px;background:#faf9fd;border:1px solid var(--line);border-radius:9px;text-decoration:none;transition:.15s;cursor:pointer}
.jb-quote{cursor:pointer}
.jb-quote:hover{border-color:var(--brand);background:#f7f4fc}
.jb-no{flex:none;width:17px;height:17px;margin-top:4px;border-radius:4px;background:var(--tint);border:1px solid var(--tint-bd);color:var(--brand);font-size:10px;font-weight:700;font-style:normal;display:flex;align-items:center;justify-content:center}
.jb-quote span{font-size:12.5px;line-height:1.95;color:#4b4658;word-break:break-word;text-align:justify}
.jb-quote .sc-excerpt{flex:1;min-width:0;display:block}
a.jb-quote{text-decoration:none}
.jb.flash{animation:cardFlash 1.6s ease}
.ev-title{font-weight:700;font-size:13.5px;margin-bottom:4px;color:var(--ink)}
.ev-meta{color:var(--muted);font-size:12px;margin-bottom:6px}
.ev-chip summary{display:inline-flex;align-items:center;gap:5px;max-width:100%;min-height:26px;padding:4px 13px;
  border-radius:13px;color:#fff;background:var(--grad);cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  list-style:none;font-size:11px;font-weight:600;box-shadow:0 2px 8px rgba(101,18,173,.22);transition:.15s}
.ev-chip summary:hover{filter:brightness(1.12)}
.ev-chip summary::-webkit-details-marker{display:none}
.ev-chip summary b{color:#fff;margin-right:2px;font-weight:700}

.ev-title{font-weight:700;font-size:13.5px;margin-bottom:4px;color:var(--navy)}
.ev-meta{color:var(--muted);font-size:12px;margin-bottom:6px}
.ev-panel p{margin:0 0 8px;color:#3f3d52;font-size:12.8px;line-height:1.7}
.sc-links{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}
.sc-links span{display:inline-flex}
.sc-links a{display:inline-flex;align-items:center;min-height:24px;padding:3px 9px;border-radius:6px;
  background:var(--brand-soft);color:var(--brand);font-weight:700;text-decoration:none;font-size:12px}

/* ===== 知识专库视图 ===== */
#view-library{padding:26px 0 30px}
.lib-head{max-width:860px;margin:0 auto 16px;text-align:center}
.lib-title{margin-bottom:14px}
.lib-title b{font-size:16px;color:var(--navy);letter-spacing:.5px;line-height:1.5}
.lib-searchWrap{position:relative;max-width:620px;margin:0 auto}
.lib-searchIcon{position:absolute;left:14px;top:50%;transform:translateY(-50%);color:#a6adbd;font-size:16px;font-weight:700}
.lib-search{width:100%;padding:11px 16px 11px 38px;border:1.5px solid var(--line-strong);border-radius:999px;
  font-size:14px;background:#fff;box-shadow:var(--shadow-1);outline:none}
.lib-search:focus{border-color:var(--brand-2);box-shadow:0 0 0 3px rgba(139,92,246,.18)}
.lib-tabs{display:flex;flex-wrap:wrap;justify-content:center;gap:6px;margin-top:14px}
.lib-tabs button{border:1px solid var(--line);border-radius:999px;background:#fff;color:var(--muted);
  padding:4px 13px;font-size:12.3px;cursor:pointer}
.lib-tabs button.on{background:var(--grad);border-color:var(--brand);color:#fff;font-weight:700}
.lib-list{max-width:860px;margin:0 auto;display:grid;grid-template-columns:minmax(0,1fr);gap:14px}
.lib-empty{max-width:860px;margin:30px auto;text-align:center;color:var(--muted);font-size:13.5px}
.lib-empty.hide{display:none}
.lib-foot{text-align:center;color:var(--muted);font-size:11.5px;padding:18px 0 0;line-height:1.8}

/* ===== 材料卡 ===== */
.scard{min-width:0;border:1px solid var(--line);border-left-width:3px;border-radius:12px;padding:14px 18px;
  background:#fff;box-shadow:var(--shadow-1);transition:box-shadow .25s}
.scard:hover{box-shadow:var(--shadow-2)}
.scard.pol{border-left-color:var(--policy)}
.scard.dat{border-left-color:var(--brand-2)}
.scard.cas{border-left-color:var(--case)}
.scard.ref,.scard.mat{border-left-color:var(--ref)}
.scard.ext{border-left-color:#b07a2a;background:linear-gradient(0deg,rgba(176,122,42,.04),rgba(176,122,42,.04)),var(--card)}
.scard.hl{box-shadow:0 0 0 3px rgba(139,92,246,.35),var(--shadow-2)}
.scard.hide{display:none}
.sc-head{display:flex;align-items:center;gap:7px;margin-bottom:6px}
.sc-id{font-family:monospace;font-weight:800;font-size:11px;color:#fff;background:var(--grad);
  border-radius:5px;padding:1px 8px}
.sc-type{font-size:11px;font-weight:700;border-radius:4px;padding:1px 8px;background:var(--ref-soft);color:var(--ref)}
.scard.pol .sc-type{background:var(--policy-soft);color:var(--policy)}
.scard.dat .sc-type{background:var(--brand-soft);color:var(--brand)}
.scard.cas .sc-type{background:var(--case-soft);color:var(--case)}
.sc-vk{margin-left:auto;font-size:11px;font-weight:800;color:var(--ok)}
.sc-vk.warn{color:var(--warn)}
.sc-unused{font-size:10.5px;font-weight:800;color:var(--muted);background:#efedf4;border-radius:4px;
  padding:1px 7px;flex:none}
.sc-conf{font-size:10.5px;font-weight:800;color:#8a5a00;background:var(--case-soft);border:1px solid #e6cf8f;
  border-radius:4px;padding:0 7px;flex:none}
.scard h4{margin:0 0 5px;font-size:14.5px;color:var(--ink);line-height:1.55}
.sc-meta{font-size:11.5px;color:var(--muted)}
/* 标题链面包屑（模型生成的结构化位置，核验核心抓手）与多段分块 */
.crumb{font-size:11.5px;color:var(--brand);margin:10px 0 4px;font-weight:600;line-height:1.6;
  padding:3px 9px;background:var(--tint);border-radius:7px;display:inline-block;max-width:100%;
  overflow-wrap:break-word}
.crumb i{font-style:normal;color:#c9b3ec;margin:0 2px;font-weight:400}
.seg-block{margin-top:8px}
.seg-block:first-child{margin-top:2px}
.seg-block .sc-excerpt{margin-top:5px}
.sc-vnote{margin-top:5px;font-size:11.3px;color:var(--ok);line-height:1.6}
.sc-excerpt{margin:8px 0 0;padding:10px 12px;border:1px solid #eceaf2;border-radius:9px;
  background:#faf9fd;color:#4a4260;font-size:12.3px;line-height:1.75}
.sc-excerpt.rich{overflow-x:auto}
.sc-excerpt.rich table{width:max-content;min-width:100%;border-collapse:collapse;background:#fff;font-size:12px}
.sc-excerpt.rich td,.sc-excerpt.rich th{min-width:92px;max-width:220px;padding:7px 8px;border:1px solid var(--line);
  vertical-align:top;word-break:break-word}
.sc-excerpt.rich thead td,.sc-excerpt.rich th{background:#f3f4f6;color:#3f3d52;font-weight:700}
.scard .sc-links a{font-size:12px}
.scard .sc-links{margin-top:4px}
.no-link{font-size:11.5px;color:var(--muted)}
.sc-links a.snap{background:#faf5ff;border-color:#d9c9f4;color:#5b21b6}

/* ===== 章节目录（spy，长报告） ===== */
.toc{position:fixed;left:calc((100vw - 1080px)/2 - 168px);top:120px;width:140px;max-height:60vh;overflow:auto;
  display:flex;flex-direction:column;gap:2px;font-size:12px}
.toc a{color:var(--muted);text-decoration:none;padding:4px 10px;border-left:2px solid var(--line);
  line-height:1.5;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.toc a.on{color:var(--brand);border-left-color:var(--brand);font-weight:700}
/* 知识专库视图下隐藏章节目录（2026-09-29 起）：.toc 渲染在 .app 之外，
   视图切换只由 .app[data-view] 驱动，此前无任何规则处理 .toc，专库视图下目录仍挂在左侧 */
.app[data-view="library"] ~ .toc,.app[data-view="library"] .toc{display:none}
@media (max-width:1460px){.toc{display:none}}

.foot{text-align:center;color:var(--muted);font-size:11.5px;padding:16px 0 4px;line-height:1.8}


/* ===== 打印附录 ===== */
.print-appendix{display:none}

/* ===== 移动端 ===== */
.sheet-mask{display:none}
.sheet{display:none}
@media (max-width:680px){
  body{font-size:14px;line-height:1.8}
  .banner{padding:6px 10px 7px}
  .banner-bar{flex-wrap:wrap;justify-content:center;gap:7px}
  .banner-bar .tb-title{display:none}
  .banner-bar .view-switch{margin:0}
  .banner-bar .view-switch button{padding:5px 11px;font-size:12px}
  .tb-tools button{font-size:11.5px;padding:4px 8px}
  .ch-head{gap:8px;margin-bottom:14px;flex-wrap:nowrap}
  .ch-head h2{font-size:17px;line-height:1.45}
  .ch-head::after{display:none}
  .ch-head .sec-badge{font-size:10.5px;padding:2px 7px;white-space:nowrap}
  .jb-name{max-width:calc(100vw - 72px)}
  .banner .meta{font-size:11px;line-height:1.6}
  .banner .orig-q{font-size:12.5px}
  .process{padding:12px 12px 11px}
  .p-step{flex:1 1 100%}
  .p-arrow{display:none}
  .verify{padding:13px 14px}
  .v-head{font-size:14px}
  .v-grid{grid-template-columns:1fr;gap:2px 0}
  .vi{flex-wrap:wrap;gap:4px 8px}
  .vi .d{min-width:0}
  .warn-box{font-size:12.5px;padding:11px 12px}
  .doc-paper{padding:16px 14px 10px;border-radius:10px}
  .sec-head{gap:7px;padding-bottom:8px;margin-bottom:8px}
  .sec-head h3{font-size:15px}
  .sec-badge{margin-left:0;font-size:11px}
  .doc-block p,.doc-item p{font-size:15px;line-height:1.95}
  .doc-sub{font-size:14px;margin:12px 0 6px}
  .data-tbl{font-size:12px}
  .data-tbl th,.data-tbl td{padding:6px 7px;line-height:1.55}
  .cite{font-size:11px;padding:0 4px}
  .ev-chip summary{font-size:11px}
  #view-library{padding:18px 0 24px}
  .lib-search{padding:10px 14px 10px 34px;font-size:13.5px}
  .lib-tabs{justify-content:flex-start;flex-wrap:nowrap;overflow-x:auto;padding-bottom:4px;
    -webkit-overflow-scrolling:touch;scrollbar-width:none}
  .lib-tabs::-webkit-scrollbar{display:none}
  .lib-tabs button{flex:none}
  .lib-list{grid-template-columns:minmax(0,1fr);gap:10px}
  .scard{padding:10px 11px}
  .crumb{font-size:11px}
  .sc-excerpt{font-size:11.5px}
  /* 移动端材料底部弹层：点角标就地弹出材料卡，不跳转打断阅读 */
  .sheet-mask{display:block;position:fixed;inset:0;background:rgba(11,31,58,.45);z-index:99;opacity:0;
    pointer-events:none;transition:opacity .2s}
  .sheet-mask.show{opacity:1;pointer-events:auto}
  .sheet{display:block;position:fixed;left:0;right:0;bottom:0;z-index:100;background:#fff;
    border-radius:14px 14px 0 0;box-shadow:0 -8px 30px rgba(11,31,58,.25);
    max-height:68vh;overflow-y:auto;-webkit-overflow-scrolling:touch;
    padding:10px 16px 22px;transform:translateY(105%);transition:transform .25s ease}
  .sheet.show{transform:translateY(0)}
  .sheet-grab{width:38px;height:4px;border-radius:2px;background:#c9d4e2;margin:2px auto 8px}
  .sheet-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
  .sheet-head b{font-size:13.5px;color:var(--navy)}
  .sheet-close{border:1px solid var(--line);background:#f5f3fa;border-radius:8px;color:#3b4a61;
    font-size:12.5px;font-weight:700;padding:5px 14px;cursor:pointer}
  .sheet .scard{box-shadow:none;margin-bottom:0}
  .sheet .sc-excerpt{display:block;-webkit-line-clamp:unset;cursor:auto}
  /* 正文表述 ↔ 原文原段 对照区（弹层顶部） */
  .cmp{margin:0 0 10px;border:1px solid var(--line);border-radius:10px;overflow:hidden}
  .cmp-tag{font-size:11px;font-weight:800;padding:3px 10px}
  .cmp-side{padding:9px 12px;font-size:12.8px;line-height:1.7}
  .cmp-side p{margin:0}
  .cmp-ai{background:#fbfaff;color:#3f3d52}
  .cmp-ai .cmp-tag{background:#eef1f6;color:var(--ref)}
  .cmp-src{background:#f4faf7;color:#2f4a3e;border-top:1px dashed var(--line-strong)}
  .cmp-src .cmp-tag{background:var(--policy-soft);color:#0b6e4f}
  .cmp-src .sc-excerpt{display:block;-webkit-line-clamp:unset;background:#fff;cursor:auto;font-size:12px;padding:8px 10px;margin:0}
}

/* ===== 打印归档 ===== */
@media print{
  .banner-bar,.process .p-detail,.lib-head,.toc,.sheet,.sheet-mask,
  .progress{display:none!important}
  .banner{position:static;background:none;border:0;padding:0 0 6px}
  .banner .orig-q{text-align:left;font-size:13px}
  .banner .meta{color:var(--muted);text-align:left}
  /* 完整归档：三页顺序打印（正文 → 溯源核验报告 → 知识专库）+ 来源附录；
     仅正文模式（body.print-body-only）只保留 #view-body */
  #view-body,#view-report,#view-library{display:block!important}
  .app[data-view] #view-body,.app[data-view] #view-report,.app[data-view] #view-library{display:block!important}
  body.print-body-only #view-report,body.print-body-only #view-library,body.print-body-only .print-appendix,
  body.print-body-only .jb,body.print-body-only .foot{display:none!important}
  #view-body .doc-paper,#view-report .doc-paper{break-after:page}

  *{-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .process{box-shadow:none;margin:6px 0 12px}
  .verify{border-color:#bbb;box-shadow:none;break-inside:avoid}
  .doc-paper{box-shadow:none;border-radius:0;padding:0}
  body{background:#fff;font-size:12.5px}
  .sc-excerpt{display:block;-webkit-line-clamp:unset;cursor:auto}
  .sc-excerpt.rich table,.print-appendix .sc-excerpt.rich table{width:100%!important;min-width:0}
  .scard{break-inside:avoid}
  .cite{background:none!important;color:#333!important;text-decoration:none!important}
  .cite::before{content:"["}.cite::after{content:"]"}
  .jb{display:inline!important}
  .jb .jb-name{border:0;background:none;padding:0;color:#333;font-weight:600}
  .jb .jb-name .jb-id{color:#333;background:none;border:1px solid #999;border-radius:3px}
  .jb .jb-body{display:none!important}
  .jb.active{break-inside:avoid}
  .jb.active .jb-body{display:block!important}
  .jb.active .jb-body .jb-quote{break-inside:avoid}
  .print-appendix{display:block;break-before:page}
  body.print-body-only .verify,body.print-body-only .process,body.print-body-only .print-appendix,
  body.print-body-only .jb,body.print-body-only .foot{display:none!important}
  .print-appendix h3{font-size:15px;color:var(--navy);border-bottom:1px solid #999;padding-bottom:6px;margin:0 0 12px}
  .print-appendix .scard{margin-bottom:10px}
}
"""

PAGE_JS = """
(function () {
  "use strict";
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  var app = $(".app");
  var isMobile = function () { return window.matchMedia("(max-width:680px)").matches; };

  /* ===== 1. 三页切换（正文 / 溯源核验报告 / 知识专库；保存/恢复各自滚动位置） ===== */
  var savedScroll = { body: 0, report: 0, library: 0 };
  var viewChangeHook = null; /* 切页后重算目录锚点等 */
  function setView(view) {
    if (!app || app.getAttribute("data-view") === view) return;
    savedScroll[app.getAttribute("data-view") || "report"] = window.scrollY;
    app.setAttribute("data-view", view);
    $$(".view-switch button").forEach(function (b) {
      b.classList.toggle("on", b.getAttribute("data-view") === view);
    });
    window.scrollTo(0, Math.max(0, savedScroll[view] || 0));
    if (viewChangeHook) viewChangeHook(view);
  }
  $$(".view-switch button").forEach(function (b) {
    b.addEventListener("click", function () { setView(b.getAttribute("data-view")); });
  });

  /* ===== 2. 阅读进度条 ===== */
  var progress = $(".progress i");
  function updateProgress() {
    if (!progress) return;
    var h = document.documentElement;
    var max = h.scrollHeight - h.clientHeight;
    progress.style.width = (max > 0 ? Math.min(100, (h.scrollTop / max) * 100) : 0) + "%";
  }
  window.addEventListener("scroll", updateProgress, { passive: true });
  updateProgress();

  /* ===== 3. 复制全文（从正文页取：章节标题 + 段落 + 表格，干净无角标） ===== */
  var copyBtn = $("#btn-copy");
  if (copyBtn) {
    copyBtn.addEventListener("click", function () {
      var parts = [];
      /* 按文档流顺序收集章节标题/段落/表格；克隆后剔除引文胶囊与角标，
         只复制正文本身（胶囊标题/展开摘录/编号数字均不带出） */
      var nodes = $$("#view-body .ch-head h2, #view-body .lead, #view-body .para, #view-body .tbl-wrap");
      nodes.sort(function (a, b) { return (a.compareDocumentPosition(b) & 4) ? -1 : 1; });
      nodes.forEach(function (el) {
        var clone = el.cloneNode(true);
        clone.querySelectorAll(".jb, sup.cite").forEach(function (x) { x.remove(); });
        var t = clone.textContent.replace(/[ \t]+/g, " ").trim();
        if (t) parts.push(t);
      });
      var text = parts.filter(Boolean).join("\\n\\n");
      function done(ok) {
        var old = copyBtn.textContent;
        copyBtn.textContent = ok ? "已复制 ✓" : "复制失败";
        setTimeout(function () { copyBtn.textContent = old; }, 1600);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(fallback(text)); });
      } else {
        done(fallback(text));
      }
      function fallback(value) {
        try {
          var ta = document.createElement("textarea");
          ta.value = value;
          ta.style.position = "fixed";
          ta.style.opacity = "0";
          document.body.appendChild(ta);
          ta.select();
          var ok = document.execCommand("copy");
          document.body.removeChild(ta);
          return ok;
        } catch (e) { return false; }
      }
    });
  }

  /* ===== 5. 导出：正文 Markdown / PDF（浏览器打印另存为 PDF） ===== */
  var exportBtn = $("#btn-export");
  var exportDrop = $("#export-drop");
  function docTitleForFile() {
    var t = $(".tb-title");
    var name = (t ? t.textContent.trim() : "") || document.title || "文稿";
    return name.replace(/[\\/:*?"<>|]+/g, "_").trim() || "文稿";
  }
  function exportMarkdown() {
    var el = document.getElementById("doc-export");
    var data = { title: docTitleForFile(), markdown: "" };
    if (el) { try { data = JSON.parse(el.textContent) || data; } catch (err) {} }
    var blob = new Blob([data.markdown || ""], { type: "text/markdown;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = (data.title || docTitleForFile()) + ".md";
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(url); if (a.parentNode) a.parentNode.removeChild(a); }, 800);
  }
  function printBy(mode) {
    if (mode === "body") document.body.classList.add("print-body-only");
    if (exportDrop) exportDrop.hidden = true;
    window.print();
  }
  if (exportBtn && exportDrop) {
    exportBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      exportDrop.hidden = !exportDrop.hidden;
    });
    exportDrop.addEventListener("click", function (e) {
      e.stopPropagation();
      var t = e.target.closest("button");
      if (!t) return;
      if (t.id === "export-md") { exportMarkdown(); exportDrop.hidden = true; return; }
      printBy(t.id === "export-pdf-body" ? "body" : "full");
    });
    document.addEventListener("click", function () { exportDrop.hidden = true; });
    /* 打印结束移除临时模式（浏览器打印窗口关闭后触发） */
    window.addEventListener("afterprint", function () { document.body.classList.remove("print-body-only"); });
  }

  /* ===== 6. 材料卡索引（专库列表内，不含打印附录） ===== */
  var cards = $$("#lib-list .scard");
  var byId = {};
  cards.forEach(function (c) {
    var id = c.getAttribute("data-cite-id");
    if (id) byId[id] = c;
  });

  /* 移动端底部弹层：正文表述 ↔ 原文原段 对照 + 材料卡 */
  var sheet = $(".sheet");
  var mask = $(".sheet-mask");
  function escHtml(s) {
    var d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }
  function sentenceOf(el) {
    var para = el && el.closest ? el.closest(".doc-block,.doc-item") : null;
    return para && para.querySelector("p") ? para.querySelector("p").innerText.trim() : "";
  }
  function openSheet(card, sentence) {
    if (!sheet) return;
    var body = sheet.querySelector(".sheet-body");
    body.innerHTML = "";
    if (sentence) {
      var excerpt = card.querySelector(".sc-excerpt");
      var cmp = document.createElement("div");
      cmp.className = "cmp";
      cmp.innerHTML =
        '<div class="cmp-side cmp-ai"><div class="cmp-tag">正文表述</div><p>' + escHtml(sentence) + '</p></div>' +
        '<div class="cmp-side cmp-src"><div class="cmp-tag">原文原段</div>' +
        '<div class="sc-excerpt">' + (excerpt ? excerpt.innerHTML : "") + '</div></div>';
      body.appendChild(cmp);
    }
    var clone = card.cloneNode(true);
    clone.removeAttribute("id");
    clone.classList.remove("hide");
    clone.classList.add("open");
    body.appendChild(clone);
    sheet.classList.add("show");
    mask.classList.add("show");
    document.body.style.overflow = "hidden";
    sheet.scrollTop = 0;
  }
  function closeSheet() {
    if (!sheet) return;
    sheet.classList.remove("show");
    mask.classList.remove("show");
    document.body.style.overflow = "";
  }
  if (sheet && mask) {
    mask.addEventListener("click", closeSheet);
    var closeBtn = sheet.querySelector(".sheet-close");
    if (closeBtn) closeBtn.addEventListener("click", closeSheet);
  }

  /* 行内引文 jb（原型行为）：点小胶囊 toggle 展开卡；点角标展开对应 jb 并 flash。
     未绑定角标红色警示，绝不按位置猜测。 */
  var JB_TABLES = {};
  try {
    var jbTablesEl = document.getElementById("jb-tables");
    if (jbTablesEl) JB_TABLES = JSON.parse(jbTablesEl.textContent || "{}");
  } catch (e) { JB_TABLES = {}; }
  function fillTableHolders(jb) {
    jb.querySelectorAll(".tbl-holder[data-tbl]").forEach(function (h) {
      if (h.getAttribute("data-filled")) return;
      var html = JB_TABLES[h.getAttribute("data-tbl")];
      if (html) h.innerHTML = html;
      h.setAttribute("data-filled", "1");
    });
  }
  function toggleJb(jb, forceOpen) {
    var open = forceOpen === true ? true : !jb.classList.contains("active");
    document.querySelectorAll(".jb.active").forEach(function (x) { if (x !== jb) x.classList.remove("active"); });
    jb.classList.toggle("active", open);
    if (open) fillTableHolders(jb);
    var name = jb.querySelector(".jb-name");
    if (name) name.setAttribute("aria-expanded", open ? "true" : "false");
    return open;
  }
  document.querySelectorAll(".jb-name").forEach(function (name) {
    name.addEventListener("click", function () { toggleJb(name.closest(".jb")); });
  });

  /* 引文条目点击 → 知识专库定位对应卡：库内导航看完整材料；
     外部原文跳转只保留 jb-head 的"查看全文"按钮，动线分离 */
  function jumpToLibrary(id) {
    var card = byId[id];
    if (!card) return;
    setView("library");
    card.classList.remove("hide", "open");
    card.classList.add("hl", "open");
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { card.scrollIntoView({ block: "center", behavior: "smooth" }); });
    });
    setTimeout(function () { card.classList.remove("hl"); }, 2200);
  }
  document.querySelectorAll(".jb-quote").forEach(function (q) {
    function go() {
      var jbEl = q.closest(".jb");
      var id = jbEl && jbEl.getAttribute("data-cite");
      if (id) jumpToLibrary(id);
    }
    q.addEventListener("click", go);
    q.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); }
    });
  });
  document.querySelectorAll("sup.cite").forEach(function (btn) {
    /* 仅剩未绑定角标（红色数字）走到这里：点击控制台留痕 */
    btn.addEventListener("click", function () {
      if (console.error) console.error("[核验] 未绑定角标:", btn.getAttribute("data-cite"));
    });
  });

  /* 材料卡摘录直接全文展开（句后胶囊已承载即点即看，专库不再折叠） */

  /* 胶囊点击：桌面开关对照气泡（同一气泡再点收起）；手机端弹出底部材料弹层 */
  document.querySelectorAll(".ev-chip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      var id = chip.getAttribute("data-cite");
      if (isMobile()) {
        var card = byId[id];
        if (card) openSheet(card, sentenceOf(chip));
        return;
      }
      togglePop(chip, id);
    });
  });

  /* ===== 7. 知识专库：tabs + 搜索 + 热词 ===== */
  var cond = "";
  var kw = "";
  function applyFilter() {
    var visible = 0;
    cards.forEach(function (c) {
      var okCond = !cond;
      if (cond === "__unused__") okCond = c.getAttribute("data-unused") === "1";
      else if (cond) okCond = c.getAttribute("data-search") === cond;
      var okKw = !kw || (c.textContent || "").toLowerCase().indexOf(kw) !== -1;
      var show = okCond && okKw;
      c.classList.toggle("hide", !show);
      if (show) visible++;
    });
    var empty = $("#lib-empty");
    if (empty) empty.classList.toggle("hide", visible !== 0);
  }
  $$(".lib-tabs button").forEach(function (b) {
    b.addEventListener("click", function () {
      $$(".lib-tabs button").forEach(function (x) { x.classList.remove("on"); });
      b.classList.add("on");
      cond = b.getAttribute("data-cond") || "";
      applyFilter();
    });
  });
  var search = $(".lib-search");
  if (search) search.addEventListener("input", function () { kw = search.value.trim().toLowerCase(); applyFilter(); });

  /* ===== 8. 过程回顾条：检索步骤展开 ===== */
  var pStep = $("#p-step-search");
  var pDetail = $("#p-detail");
  if (pStep && pDetail) {
    function toggleDetail() { pDetail.classList.toggle("show"); }
    pStep.addEventListener("click", toggleDetail);
    pStep.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleDetail(); }
    });
  }

  /* ===== 9. 章节目录（spy） ===== */
  var toc = $(".toc");
  if (toc) {
    var links = $$("a", toc);
    /* 正文页锚 sec-N / 报告页锚 rsec-N：href 只是兜底，实际按当前视图前缀定位 */
    function tocPrefix() {
      var v = app ? app.getAttribute("data-view") : "";
      return v === "report" ? "rsec" : (v === "body" ? "sec" : "");
    }
    function tocSecs() {
      var pfx = tocPrefix();
      if (!pfx) return [];
      return links.map(function (a) { return document.getElementById(pfx + "-" + a.getAttribute("data-sec")); });
    }
    var secs = tocSecs();
    links.forEach(function (a) {
      a.addEventListener("click", function (e) {
        e.preventDefault();
        var pfx = tocPrefix();
        var target = pfx ? document.getElementById(pfx + "-" + a.getAttribute("data-sec")) : null;
        if (!target) return;
        /* 手动定位而非 scrollIntoView({block:"start"})：后者把标题顶到视口 y=0，
           会被 sticky 顶栏盖住。偏移量与目录吸顶位置同一基准（顶栏高 + 20px）。 */
        var bar = document.querySelector(".banner");
        var offset = (bar ? bar.offsetHeight : 0) + 20;
        var y = target.getBoundingClientRect().top + window.scrollY - offset;
        window.scrollTo({ top: Math.max(0, y), behavior: "smooth" });
      });
    });
    function spy() {
      var pos = window.scrollY + 130;
      var current = -1;
      secs.forEach(function (s, i) { if (s && s.offsetTop <= pos) current = i; });
      links.forEach(function (a, i) { a.classList.toggle("on", i === current); });
    }
    window.addEventListener("scroll", spy, { passive: true });

    /* 目录纵向定位（2026-09-29 起）：此前 CSS 写死 top:120px，目录顶部与页头
       齐平、离正文很远。改为——直接跟随正文首节，只保留"不低于顶栏下方"的下限；首屏看不到
       目录属正常，向下滚动后自然吸附在顶栏下方。目录过长由 CSS max-height:60vh+overflow:auto
       内部滚动兜底。 */
    var bannerEl = document.querySelector(".banner");
    function placeToc() {
      var first = secs[0];
      if (!first) return;
      var stick = (bannerEl ? bannerEl.offsetHeight : 0) + 20;
      var want = Math.round(first.getBoundingClientRect().top);
      toc.style.top = Math.max(stick, want) + "px";
    }
    window.addEventListener("scroll", placeToc, { passive: true });
    window.addEventListener("resize", placeToc);
    /* 切页时重算锚点集合与高亮（正文页 sec-N / 报告页 rsec-N；专库页隐藏目录） */
    viewChangeHook = function () { secs = tocSecs(); spy(); placeToc(); };
    placeToc();
    spy();
  }
})();
"""


def _norm_for_match(text: str) -> str:
    """比对用归一化：去全部空白与标点（中英文、全半角），只留字词与数字。"""
    return re.sub(r"[\W_]+", "", str(text or ""))


_ART_NUM_RE = re.compile(r"第[零一二三四五六七八九十百千〇]+条")
# 段落裁剪的节选匹配窗口：法条原文连续 16 字出现在答案里即视为被引用
# （24 字会漏掉短引用——Q3 引第四十六条第（四）项只引了 21 字一行；16 字仍远高于
#  通用法律短语的偶然重合长度，误留的代价只是多展示一段，远小于漏掉被引段落）
_QUOTE_WINDOW = 16


def trim_uncited_segments(sources: List[Dict[str, Any]], answer: str) -> None:
    """材料只展示被正文引用的段落（2026-11-05，WorkBuddy 实测反馈）。

    检索可以宽松（--articles 多拉防漏），展示只给核验需要的。保留规则（任一命中即留）：
    ① 段落标题的条号在答案正文中被点名（如"第一百四十八条"）；
    ② 段落原文（归一化后）整体出现在答案中，或答案引用块是段落的节选（款级引用）。
    一段都匹配不上时整篇保留——答案可能高度改写，宁可多展示不可让材料卡变空。
    """
    ans = answer or ""
    ans_norm = _norm_for_match(ans)
    for source in sources:
        segs = source.get("segments") or []
        if len(segs) <= 1:
            continue
        keep = []
        for seg in segs:
            chain = seg.get("chain") or []
            tail = chain[-1] if chain else ""
            text_norm = _norm_for_match(seg.get("text") or "")
            hit = bool(tail) and bool(_ART_NUM_RE.search(tail)) and tail in ans
            # 节选匹配（2026-11-05 Q3 实测）：正文常是"……"式的款级节选，整段包含判断
            # 永远不成立；旧逻辑只认 `>` 引用块，导致第十一条/第十二条/第四十六条这些
            # 明明被引用的段落被裁掉。改为滑动窗口：段落里任一 24 字连续片段出现在
            # 答案中即视为被引用（法条原文 24 字连续重合，误判概率极低）。
            if not hit and len(text_norm) >= _QUOTE_WINDOW:
                hit = any(text_norm[i:i + _QUOTE_WINDOW] in ans_norm
                          for i in range(0, len(text_norm) - _QUOTE_WINDOW + 1, 8))
            if hit:
                keep.append(seg)
        if 0 < len(keep) < len(segs):
            # 小材料或多数段落都相关时不裁（2026-11-05 Q6 实测）：材料只有 3 段、正文
            # 引用了其中 2 段并另引了第 7 条（转述、未点名条号），第 7 条被裁掉，读者点
            # 角标看不到误工费依据。裁一段的收益很小，漏掉被引段落的代价很大。
            if len(segs) <= 4 or len(keep) * 2 > len(segs):
                continue
            print(f"段落裁剪：{str(source.get('title') or '')[:24]} {len(segs)}→{len(keep)} 段（未引用段落不展示）")
            source["segments"] = keep
        elif not keep:
            print(f"段落裁剪：{str(source.get('title') or '')[:24]} 未匹配到被引段落，保留全部 {len(segs)} 段")


def _quote_found(norm: str, targets: List[str]) -> bool:
    """引文是否能在本次材料段落里找到（16 字连续重合即算找到）。"""
    if len(norm) < 20:
        return True
    w = _QUOTE_WINDOW
    return any(norm[i:i + w] in t for i in range(0, len(norm) - w + 1, 8) for t in targets if t)


def mark_unmatched_quotes(blocks: List[Dict[str, Any]], seg_texts: List[str]) -> List[str]:
    """标出"材料里找不到原文"的引用块（2026-11-05 Q6 实测）。

    Q6 正文把一段"根据法律法规有关规定……不认定为工伤"写成引用块并挂了角标，
    但本次取回的意见（三）只有第六、七项，材料里根本没有这句话——引用对应仍算
    "已绑定"，读者点开却找不到原文。这里逐块比对，找不到就显性标出并计入核验面板。
    """
    bad: List[str] = []
    for b in blocks:
        if b.get("kind") != "quote":
            continue
        # 引用块里的 [n] 会被渲染成 jb 胶囊，胶囊内含整段材料原文；不先摘掉的话，
        # 任何引文都会"匹配"到自己的胶囊，核对等于没做。
        raw_html = re.sub(r'<span class="jb".*?</span></span></span>', "", b.get("html") or "", flags=re.S)
        text = html.unescape(re.sub(r"<[^>]+>", "", raw_html))
        norm = _norm_for_match(text)
        if _quote_found(norm, seg_texts):
            continue
        b["html"] = ('<span class="q-unmatched" title="该引文未出现在本次取回的材料段落中">'
                     '未在材料中找到该句原文</span>') + b["html"]
        bad.append(short(" ".join(text.split()), 32))
    return bad


def render_html(payload: Dict[str, Any], title: str, answer_override: str = "", question_override: str = "",
                generated_at: Optional[datetime] = None,
                skip_link_check: bool = False, snapshot_enabled: bool = True,
                charts_data: Optional[Dict[str, Any]] = None,
                research_notes: Optional[Dict[str, int]] = None,
                trim_uncited: bool = True,
                external_data: Optional[List[Dict[str, str]]] = None) -> str:
    # search_meta.calls（每路调用增量）在 unwrap 前捕获——unwrap 会把 content 外层剥掉（1.6.0）
    _calls_meta = payload.get("search_meta") if isinstance(payload.get("search_meta"), dict) else {}
    payload = unwrap(payload)
    answer = normalize_citations(answer_override) if answer_override.strip() else extract_answer(payload)
    # 无 markdown 标题的答案：首个非空行若为短标题形态（≤60 字、非列表/表格/标题语法、
    # 不以句读结尾），升格为 `# 标题` 行——文头标题、章节卡、TOC、图表锚点全链路随 heading
    # 自然工作，标题行不再在正文重复渲染（2026-10-14 修复：实测纯文本首行答案的报告页
    # 文头显示"溯源核验报告：溯源核验报告"、图表锚点随之失配）
    if not re.search(r"(?m)^#{1,4}\s", answer):
        _first = next((ln.strip() for ln in answer.splitlines() if ln.strip()), "")
        if (_first and len(_first) <= 60 and not re.match(r"^[-*>|#\d|\|]", _first)
                and not _first.endswith(("。", "；", "！", "？", "!", "?", ".", ";"))):
            _rest = answer[answer.index(_first) + len(_first):].lstrip("\n")
            answer = f"# {_first}\n{_rest}"
    sources = align_sources_to_answer(answer, extract_sources(payload, skip_link_check=skip_link_check, snapshot_enabled=snapshot_enabled))
    # 角标按首次出现顺序重排为 1..N（含材料卡同步重编号与未引用分组），WorkBuddy 实测反馈要求
    answer, sources, cite_map = renumber_citations(answer, sources)
    # 引文核对要用裁剪前的段落（裁剪后段落可能被拿掉，误报"找不到原文"）
    _all_seg_texts = [_norm_for_match(seg.get("text") or "")
                      for s0 in sources for seg in (s0.get("segments") or [])]
    # 只展示被引段落（2026-11-05）：答案定型后裁掉未引用段落，检索侧可继续宽松多拉
    if trim_uncited:
        trim_uncited_segments(sources, answer)
    used = citation_ids(answer)
    generated_at = generated_at or datetime.now()
    generated = generated_at.strftime("%Y-%m-%d %H:%M")

    verification = compute_verification(answer, sources, payload, generated_at)
    if external_data:
        verification["external"] = external_data
    # 自检说明里的材料编号跟着重排后的角标走（2026-11-05 Q3 实测：模型按合并 JSON 的
    # 原始编号写自检，报告重排后编号全对不上，甚至出现不存在的 [6][7]）。
    remap_selfcheck_numbers(verification, cite_map)
    process_stats = compute_process_stats(sources, answer, calls=_calls_meta.get('calls'))
    if research_notes:
        process_stats["research_notes"] = research_notes
    citation_warning = ""
    if sources and not used:
        citation_warning = (
            '<div class="warn-box"><b>生成检查未通过：正文没有来源角标。</b>'
            '本报告无法建立"结论-素材"核验对应，仅作素材清单参考。'
            '请修正最终答案（--answer-file）：在关键结论后标注 [1]、[2] 等角标并逐条对应来源文章，'
            '然后重新运行本脚本生成核验报告。</div>'
        )
    chip_map = build_chip_data(sources)
    blocks, _ = parse_answer_blocks(answer, {s["id"] for s in sources}, chip_map)
    verification["unmatched_quotes"] = mark_unmatched_quotes(blocks, _all_seg_texts)
    if verification["unmatched_quotes"]:
        # 引用块在材料里找不到原文，等于正文出现了没有出处的"条文"——不能照打已核验
        _ov = verification["overall"]
        _n_uq = len(verification["unmatched_quotes"])
        _ov["passed"] = False
        _ov["label"] = f"核验未通过：正文有 {_n_uq} 处引用块在材料中找不到原文"
        _ov["reasons"].append(f"有 {_n_uq} 处引用块未在本次材料中找到原文")
    # 胶囊内表格数据汇总（span 内静态表格会被解析器拆散，改为页尾 JSON + 展开时 JS 注入）
    jb_tables: Dict[str, str] = {}
    for cid, jb in chip_map.items():
        for key, html in (jb.pop("_tables", {}) or {}).items():
            jb_tables[key] = html
    doc_title, sections = group_sections(blocks)
    display_title = doc_title or title
    # 正文页：同一份正文去掉全部角标/引文胶囊，输出干净正式内容（核验内容归"溯源核验报告"页）
    clean_blocks, _ = parse_answer_blocks(answer, {s["id"] for s in sources}, chip_map, strip_cites=True)
    _, clean_sections = group_sections(clean_blocks)
    # 原问题行（2026-10-08 起）：只显示 --question 显式传入的原始问题，
    # 不用文档标题冒充（标题是答案的成稿名，不是用户原话）；为空或与标题相同时不显示
    question_text = (question_override or "").strip()
    hero_question = (
        f'<div class="orig-q{" long" if len(question_text) > 60 else ""}" title="{esc(question_text)}"><b>原问题</b>：{esc(question_text)}</div>'
        if question_text and question_text != display_title else ""
    )

    # 注入 JSON 转义（1.6.0，对齐公文写作 3.9.0）：< > & 全量转 \uXXXX 转义——既防
    # </script> 提前闭合，也防 <!-- / <script 序列触发怪异解析；JSON.parse 原生可逆。
    def _json_for_html(obj: Any) -> str:
        return (json.dumps(obj, ensure_ascii=False)
                .replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e"))

    jb_tables_json = _json_for_html(jb_tables)
    jb_tables_script = (f'<script type="application/json" id="jb-tables">{jb_tables_json}</script>\n'
                        if jb_tables else "")
    # 导出用正文 Markdown（去角标，干净正文），供顶部"导出 ▾ → 导出 Markdown（正文）"下载
    export_payload = {"title": display_title, "markdown": strip_citation_markers(answer)}
    export_json = _json_for_html(export_payload)
    export_script = f'<script type="application/json" id="doc-export">{export_json}</script>\n' 

    meta_bits = []
    if process_stats["n_searches"]:
        # 检索计数按接口通道拆分显示（深度搜索与可信搜索是两个接口来源）
        _deep_n = process_stats.get("deep_routes", 0)
        _trusted_n = process_stats.get("trusted_routes", 0)
        if _deep_n and _trusted_n:
            meta_bits.append(f"深度搜索 {_deep_n} 路 · 可信补搜 {_trusted_n} 路")
        elif _deep_n:
            meta_bits.append(f"深知深度搜索 {_deep_n} 路")
        elif _trusted_n:
            meta_bits.append(f"深知税务检索 {_trusted_n} 路")
        else:
            meta_bits.append(f"深知检索 {process_stats['n_searches']} 路")
    if sources:
        meta_bits.append(f"知识专库文章 {len(sources)} 篇")
    if process_stats["n_cite_marks"]:
        meta_bits.append(f"正文实际引用 {process_stats['n_cite_marks']} 处")
    meta_bits.append(f"生成于 {generated}")
    meta_line = " · ".join(meta_bits)
    # 来源＝材料实际使用的检索通道（深知税务检索，动态汇总）；只保留产品名，
    # 过滤内部通道标记（联网/可信联网/宿主 WebSearch）——2026-11-10 对齐可信搜索 1.7.2。
    _channels: List[str] = []
    for s in sources:
        for _tok in re.split(r"[、·]", (s.get("channel") or "").strip()):
            _tok = _tok.strip()
            if not _tok or _tok in ("联网", "可信联网", "宿主 WebSearch"):
                continue
            if _tok not in _channels:
                _channels.append(_tok)
    has_external_any = any(s.get("unofficial") or s.get("pending") for s in sources)
    source_line = (" · ".join(_channels) if _channels
                   else ("深知税务助手（含公开网络材料）" if has_external_any else "深知税务助手"))

    # 正文页来源性质提示（2026-11-10 口径确认）：引用了公开网络材料时给用户一个
    # 可见、统一的标记；逐条标记仍在溯源核验报告的材料卡与引文胶囊上。
    cited_external = any((s.get("pending") or s.get("unofficial")) and s.get("used", True)
                         for s in sources)
    body_external_note = (
        '<div class="body-external-note">说明：本页部分材料为外部公开材料，'
        '已在溯源核验报告中标注来源性质（政府网站/官方媒体/次级媒体/未知），请以官方口径复核。</div>'
        if cited_external else ""
    )

    # 图表并入核验报告（1.4.0 一体化）：有图表数据且包内 ECharts 可用时，
    # 图表并入核验报告（1.4.0 一体化）——交付物始终是**一个** HTML，不再另出独立图表报告。
    # 位置按 metadata.section 锚点插进对应章节（图表跟着它展示的数据走）；锚点缺失或不匹配
    # 才退化为核验报告单之后的独立"数据可视化"章节。资源缺失或数据不可用则整块不渲染
    # （不出现空白图，也不阻断报告生成）。
    charts_html = ""
    charts_script = ""
    chart_toc = ""
    charts_by_section: Dict[int, str] = {}
    if charts_data:
        echarts_src = chart_embed.load_echarts_source()
        if not echarts_src:
            print(f"提示：未找到 {chart_embed.ECHARTS_RESOURCE}，本次不生成图表章节（报告其余部分不受影响）。",
                  file=sys.stderr)
        charts = chart_embed.build_charts(charts_data) if echarts_src else []
        if echarts_src and not charts:
            print("提示：图表数据不足以成图（需 ≥2 个数据点/系列），本次不生成图表章节。", file=sys.stderr)
        if charts:
            chart_meta = charts_data.get("metadata") or {}
            chart_title = str(chart_meta.get("title") or "").strip() or "数据可视化"
            note = '<p class="chart-note">图表由已核验材料数据生成，点击图例或数据项可跳转对应来源原文。</p>'
            blocks = chart_embed.render_blocks(charts)
            # 图表跟着它展示的数据所在的章节走（1.4.0）：metadata.section 指定章节号/标题，
            # 命中就插进该章节正文之后；未指定或匹配不上，才退化为独立的"数据可视化"章节
            # （放在核验报告单之后、正文之前，作为总体摘要，不再堆到报告最末尾）。
            anchor_idx = resolve_chart_anchor(sections, chart_meta.get("section"))
            if anchor_idx:
                charts_by_section[anchor_idx] = (
                    f'<div class="chart-inline" aria-label="数据可视化">'
                    f'<h3 class="chart-h3">{esc(chart_title)}</h3>{note}{blocks}</div>'
                )
            else:
                charts_html = (
                    f'<section class="chart-section" id="chart-block" aria-label="数据可视化">'
                    f'<h2 class="chart-h2">{esc(chart_title)}</h2>{note}{blocks}</section>'
                )
                chart_toc = f'<a href="#chart-block">{esc(short(chart_title, 16))}</a>'
                if chart_meta.get("section"):
                    print(f"提示：图表锚点「{chart_meta.get('section')}」在正文里找不到对应章节，"
                          f"已改为独立章节呈现。", file=sys.stderr)
            charts_script = chart_embed.render_script(charts, echarts_src)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(display_title)}</title>
<style>{PAGE_CSS}</style>
</head>
<body>

<header class="banner">
  <div class="banner-bar">
    <span class="tb-title">{esc(display_title)}</span>
    <div class="view-switch" role="tablist" aria-label="页面切换">
      <button data-view="body" type="button">正文（去索引）</button>
      <button class="on" data-view="report" type="button">溯源核验报告</button>
      <button data-view="library" type="button">知识专库（{len(sources)}）</button>
    </div>
    <div class="tb-tools">
      <button id="btn-copy" type="button" title="复制正文纯文本">复制全文</button>
      <span class="print-menu">
        <button id="btn-export" type="button" aria-haspopup="true" title="导出正文 Markdown 或 PDF">导出 ▾</button>
        <span class="print-drop" id="export-drop" hidden>
          <button id="export-md" type="button">导出 Markdown（正文）</button>
          <button id="export-pdf-body" type="button">导出 PDF（正文）</button>
          <button id="export-pdf-full" type="button">导出 PDF（溯源核验报告）</button>
        </span>
      </span>
    </div>
  </div>
  {hero_question}
  <div class="meta">{esc(meta_line)} ｜ 来源：{esc(source_line)}</div>
  <div class="progress" aria-hidden="true"><i></i></div>
</header>

<div class="app container" data-view="report">

  <main class="view" id="view-body" aria-label="正文">
    <h2 class="paper-title">{esc(display_title)}</h2>
    <div class="doc-paper">
    {body_external_note}
    {render_section_cards(clean_sections, sources, id_prefix="sec")}
    </div>
    <div class="foot">深知税务助手 · 正文 ｜ 内容由 AI 生成，仅供参考</div>
  </main>

  <main class="view" id="view-report" aria-label="溯源核验报告">
    <h2 class="paper-title">溯源核验报告：{esc(display_title)}</h2>
    {citation_warning}
    {render_process_bar(process_stats, verification)}
    {render_verify_panel(verification)}
    {charts_html}
    <div class="doc-paper">
    {render_section_cards(sections, sources, charts_by_section, id_prefix="rsec")}
    </div>
    <div class="foot">深知税务助手 · 溯源核验报告 ｜ 内容由 AI 生成，仅供参考</div>
  </main>

  {render_library_view(sources, display_title, external_data)}
  {render_print_appendix(sources)}
</div>

{render_toc(sections, chart_toc)}

<div class="ev-panel" id="ev-pop" hidden></div>
{export_script}{jb_tables_script}<div class="sheet-mask" aria-hidden="true"></div>
<div class="sheet" role="dialog" aria-label="来源文章">
  <div class="sheet-grab"></div>
  <div class="sheet-head"><b>依据对照</b><button class="sheet-close" type="button">收起</button></div>
  <div class="sheet-body"></div>
</div>

<script>{PAGE_JS}</script>
{charts_script}
</body>
</html>"""


def remap_selfcheck_numbers(verification: Dict[str, Any], mapping: Dict[str, str]) -> None:
    """把自检说明里的 [n] / “材料 n” 映射到重排后的编号。"""
    sc = (verification or {}).get("self_check") or {}
    items = sc.get("items") or {}
    if not mapping or not items:
        return
    def _map(m: re.Match[str]) -> str:
        old = m.group(2)
        return f"{m.group(1)}{mapping.get(old, old)}"
    for label, (status, note) in list(items.items()):
        if not note:
            continue
        note = re.sub(r"(\[)(\d+)(\])", lambda m: f"[{mapping.get(m.group(2), m.group(2))}]", note)
        note = re.sub(r"(材料\s*)(\d+)", _map, note)
        items[label] = (status, note)


def renumber_citations(answer: str, sources: List[Dict[str, str]]) -> Tuple[str, List[Dict[str, str]], Dict[str, str]]:
    """把答案角标按首次出现顺序重排为 [1][2][3]…，材料卡同步重编号。

    被引用的材料按新编号排在前面（编号与正文角标一一对应，used=True）；
    未引用召回材料移入"未引用素材"分组（used=False，不占角标编号，锚点用独立递增号）。
    """
    cited_order = citation_ids(answer)
    if not cited_order:
        for s in sources:
            s["used"] = False
        return answer, sources, {}
    mapping = {old: str(new) for new, old in enumerate(cited_order, start=1)}
    answer = re.sub(r"\[(\d+)\]", lambda m: "[" + mapping.get(m.group(1), m.group(1)) + "]", answer)
    by_old: Dict[str, Dict[str, str]] = {}
    for s in sources:
        by_old.setdefault(s["id"], s)
    cited_sorted: List[Dict[str, str]] = []
    for old in cited_order:
        s = by_old.get(old)
        if s is None:
            continue
        s2 = dict(s)
        s2["id"] = mapping[old]
        s2["used"] = True
        cited_sorted.append(s2)
    next_panel = len(mapping)
    rest: List[Dict[str, str]] = []
    for s in sources:
        if s["id"] in mapping:
            continue
        next_panel += 1
        s2 = dict(s)
        s2["used"] = False
        # 未引用材料 id 一并改为面板锚点号，避免旧编号与重排后的角标空间撞号
        s2["id"] = str(next_panel)
        rest.append(s2)
    return answer, cited_sorted + rest, mapping


def align_sources_to_answer(answer: str, sources: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """不再按位置给材料重编号。

    修复历史实现缺陷：原实现会在"正文角标与素材 id 完全不相交"时按顺序把素材改号
    迎合角标——正文写 [7] 而只有 1 篇来源文章时，会被洗成"✓ 引用对应 1/1"，与
    "未绑定角标绝不按位置猜测"的核验诚实性原则相反。现如实返回原素材，由核验单报未绑定。
    角标 1..N 的连续重排由 renumber_citations 独立完成（按首现顺序，1.1.5 用户要求）。
    """
    return sources


def resolve_charts_data(value: str) -> Optional[Dict[str, Any]]:
    """解析 --charts-json：支持直接内联 JSON，也支持 official-docs/search-results/ 内的文件名。

    非法/为空一律返回 None（图表章节不渲染），绝不因此阻断核验报告生成——
    报告的核验正文是主交付，图表是附加视图。
    """
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        if raw.startswith("{"):
            data = json.loads(raw)
        else:
            data = json.loads(_safe_input_path(raw, {".json"}).read_text(encoding="utf-8"))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"提示：图表数据无法读取（{exc}），本次不生成图表章节。", file=sys.stderr)
        return None
    return data if isinstance(data, dict) else None


def _next_version_path(path: Path) -> Path:
    """输出文件已存在时不覆盖（1.4.0 起）：自动改为 原名_v2 / _v3 … 另存。

    追加图表/修改答案后重跑渲染时，旧版本保留、新版本号递增——不覆盖已交付内容，
    也不会再靠宿主目录里的 "名字 (2)" 兜底。命名与 deliver_outputs.py 的重名规则一致。
    """
    if not path.exists():
        return path
    for index in range(2, 100):
        candidate = path.with_name(f"{path.stem}_v{index}{path.suffix}")
        if not candidate.exists():
            print(f"提示：{path.name} 已存在，本次输出改为 {candidate.name}（不覆盖旧版，1.4.0 起）。")
            return candidate
    raise SystemExit(f"错误：{path.name} 的版本号 _v2~_v99 均已占用，请清理 {path.parent} 后重试。")


def parse_research_notes(text: str) -> Dict[str, int]:
    """统计研究资料 Markdown 的两张表行数：核心事实总表 / 数据口径表。
    按二级/三级标题分节识别，表格行以 | 开头（跳过表头与 --- 分隔行）；未识别到相应节时计 0。"""
    facts = 0
    calibers = 0
    current: Optional[str] = None
    lines = (text or "").splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            head = stripped.lstrip("#").strip()
            if "事实" in head:
                current = "facts"
            elif "口径" in head or "数据" in head:
                current = "calibers"
            else:
                current = None
            continue
        if not (current and stripped.startswith("|")):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{2,}:?", c or "") for c in cells):
            continue  # 表头分隔行
        prev = lines[i - 1].strip() if i > 0 else ""
        if prev.startswith("|") and i >= 2 and all(
            re.fullmatch(r":?-{2,}:?", c or "") for c in [x.strip() for x in prev.strip("|").split("|")]
        ):
            continue  # 分隔行的前一行＝表头行，不计数据
        if any(cells):
            if current == "facts":
                facts += 1
            else:
                calibers += 1
    return {"facts": facts, "calibers": calibers}


def main() -> None:
    parser = argparse.ArgumentParser(description="生成溯源核验报告 HTML（深知税务助手 public 版）")
    parser.add_argument("input_json", help="tax_search.py 的 --json-only 输出 JSON")
    parser.add_argument("--output", help="输出 HTML 文件名（official-docs/output/，形如《标题.html》）；不传时按问题自动生成《标题.html》。同题重跑自动 _v2 另存")
    parser.add_argument("--title", default=DEFAULT_TITLE, help="页面标题（不传时按输出文件名推断）")
    parser.add_argument("--answer-file", help="最终答案文件（关键结论带 [1][2] 角标）。复杂任务综合后必须传入，确保 HTML 展示的答案与交付一致。")
    parser.add_argument("--question", default="", help="用户原始问题，用于自动生成文件名。")
    parser.add_argument("--question-file", help="用户原始问题全文文件（official-docs/search-results/ 内文件名或绝对路径）；多行/长问题必须用本参数传全文，禁止只传首行（1.6.0）")
    parser.add_argument("--self-check-file", help="答案自检结果 JSON（五项：fact_basis/binding/consistency/freshness/no_gap，值写 通过/未通过：原因）；未传时核验单如实显示'未记录'。")
    parser.add_argument("--skip-link-check", action="store_true", help="（兼容 no-op）链接活性检测已于 2026-10-08 移除，接口返回的链接原样进报告")
    parser.add_argument("--no-snapshot", action="store_true", help="关闭存档快照兜底展示（默认启用：原文失效时以 /A/ 修订后的存档快照回看）")
    parser.add_argument("--charts-json", help="图表数据：official-docs/search-results/ 内的 JSON 文件名，或直接内联 JSON。传入后图表并入本报告（一体化，不另出独立 HTML）。")
    parser.add_argument("--research-notes-file", help="研究资料 Markdown（核心事实总表 + 数据口径表）；传入后 AI 自验收过程条体现整理规模，未传不显示该统计。")
    parser.add_argument("--no-trim-uncited", action="store_true", help="关闭未引用段落裁剪（默认：材料卡与溯源面板只展示被正文引用的段落）")
    parser.add_argument("--external-data", help="外部公开数据 JSON（LPR、汇率等）：列表，字段 名称/数值/来源/公布日期/链接/说明。"
                                               "允许联网取公开数据，但必须在此登记来源，报告单列、不计入深知材料核验")
    args = parser.parse_args()

    input_path = _safe_input_path(args.input_json, {".json"})
    payload = load_json(input_path)
    answer_override = ""
    if args.answer_file:
        answer_override = _safe_input_path(args.answer_file, {".txt", ".md"}).read_text(encoding="utf-8")

    # 答案自检结果注入（写入 unwrap 后的根级，供 compute_verification 读取）
    if args.self_check_file:
        check_path = _safe_input_path(args.self_check_file, {".json"})
        check_data = json.loads(check_path.read_text(encoding="utf-8"))
        if isinstance(check_data, dict):
            unwrap(payload)["selfCheck"] = check_data

    snapshot_enabled = not args.no_snapshot
    unwrapped = unwrap(payload)
    final_answer = normalize_citations(answer_override) if answer_override.strip() else extract_answer(unwrapped)

    # 生成前硬校验：核验报告必须以可交付状态产出——无角标或角标未绑定材料均拒绝生成
    preview_sources = extract_sources(unwrapped, skip_link_check=True, snapshot_enabled=snapshot_enabled)
    preview_cited = citation_ids(final_answer)
    if preview_sources and not preview_cited:
        print(
            "错误：生成检查未通过——已召回 "
            f"{len(preview_sources)} 篇来源文章，但答案中没有 [1]、[2] 等来源角标，无法建立\"结论-来源文章\"核验对应。\n"
            "请修正最终答案（--answer-file）：在关键结论后标注角标并逐条对应来源文章，然后重新运行本脚本。",
            file=sys.stderr,
        )
        raise SystemExit(1)
    preview_ids = {s["id"] for s in preview_sources}
    unbound_preview = [cid for cid in preview_cited if cid not in preview_ids]
    if unbound_preview:
        shown = "、".join(f"[{c}]" for c in unbound_preview[:8])
        print(
            f"错误：生成检查未通过——答案角标 {shown} 未绑定到任何来源文章"
            f"（共召回 {len(preview_sources)} 条，可绑定编号 {min(preview_ids) if preview_ids else '-'}~{max(preview_ids) if preview_ids else '-'}）。\n"
            "请修正最终答案：角标必须逐条对应实际引用的来源文章，然后重新运行本脚本。",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if args.question_file:
        _qf = Path(args.question_file).expanduser()
        if not _qf.is_absolute():
            _qf = (SEARCH_RESULTS_DIR / _qf.name).resolve()
        args.question = _qf.read_text(encoding="utf-8").strip()
    question = args.question.strip() or extract_question(unwrapped)
    generated_at = datetime.now()
    if args.output:
        output = _safe_output_path(args.output, {".html", ".htm"}, ".html")
    else:
        output = _safe_output_path(safe_output_filename(question, generated_at), {".html", ".htm"}, ".html")

    output = _next_version_path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # 页面标题：显式 --title 优先；没传（仍是默认值）时按输出文件名推断，避免
    # "溯源核验报告：溯源核验报告" 这种重复抬头（2026-11-05 Q1 复测发现）。
    title = args.title
    if title == DEFAULT_TITLE:
        stem = re.sub(r"_v\d+$", "", output.stem).strip()
        if stem and stem != DEFAULT_TITLE:
            title = stem
    external_data = []
    if args.external_data:
        _ext_path = _safe_input_path(args.external_data, {".json"})
        external_data = normalize_external_data(json.loads(_ext_path.read_text(encoding="utf-8")))
    research_notes = None
    if args.research_notes_file:
        _rn_path = _safe_input_path(args.research_notes_file, {".md", ".txt"})
        research_notes = parse_research_notes(_rn_path.read_text(encoding="utf-8"))
        print(f"研究资料统计：{research_notes['facts']} 项事实 · {research_notes['calibers']} 项口径")
    output.write_text(
        render_html(payload, title, answer_override=answer_override, question_override=args.question,
                    generated_at=generated_at, skip_link_check=args.skip_link_check,
                    snapshot_enabled=snapshot_enabled, charts_data=resolve_charts_data(args.charts_json),
                    research_notes=research_notes, trim_uncited=not args.no_trim_uncited,
                    external_data=external_data),
        encoding="utf-8")
    print(f"已生成：{output}")


if __name__ == "__main__":
    main()
