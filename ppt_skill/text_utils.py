"""文本与数值工具。

parse_numeric_cell 在 v2.0.0 修正了原版的量级腐蚀：
    "1200亿" 原版 -> 1200.0（"亿"被当干扰字符删掉）
    现在        -> 1.2e11
    "100万"  原版 -> 100.0
    现在        -> 1e6
    "12%34"  原版 -> 1234.0（两个数值粘连被拼成一个数）
    现在        -> None（明显的脏数据，不进图表）
    "（100台）" 原版 -> -100.0（括注被当会计负数）
    现在        -> 100.0（只有括号内是纯数字才按会计负数取负）
"""

import math
import re
from typing import List, Optional, Tuple

from .models import TableData

# 数量级后缀：按中文习惯乘算，不再删除。匹配时按键长降序，
# 保证 "3万亿" 命中 "万亿"（1e12）而不是 "万"（1e4）。
MAGNITUDE = {"万亿": 1e12, "亿": 1e8, "千万": 1e7, "百万": 1e6,
             "万": 1e4, "千": 1e3, "w": 1e4, "k": 1e3, "m": 1e6}

# 纯装饰性字符，删掉不影响数值大小
DECORATION_RE = re.compile(r"[,，\s￥¥$€£₩元个份人次件台套组]")

# 百分比与正负号
PERCENT_RE = re.compile(r"%|％")
NUMBER_RE = re.compile(r"[+-]?\d+(?:\.\d+)?")

# 「数字+百分号」整体形态：30% / 45.5％ 合法，12%34 这类粘连是脏数据
PERCENT_VALUE_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?\s*[%％]$")

# Windows 保留设备名（带不带扩展名都非法）
WINDOWS_RESERVED_RE = re.compile(
    r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", re.IGNORECASE)


def sanitize_filename(text: str, max_len: int = 60) -> str:
    """清理文件名中的非法字符（跨平台安全）。

    除了文件系统非法字符，也去掉首尾的中英文标点——
    标题常以「。」「，」「.」结尾，直接拿来当文件名会很奇怪；
    Windows 保留设备名（con/nul/com1…）加前缀绕开。
    """
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", str(text))
    cleaned = cleaned.strip().strip(".").strip(
        "。，、；：？！…—·\"'""''（）()[]【】{}")
    if WINDOWS_RESERVED_RE.match(cleaned):
        cleaned = "_" + cleaned
    return (cleaned or "未命名")[:max_len]


def _split_magnitude(text: str) -> Tuple[float, str]:
    """按最长量级后缀切分。返回 (系数, 剩余文本)。"""
    lowered = text.lower()
    for suffix in sorted(MAGNITUDE, key=len, reverse=True):
        if lowered.endswith(suffix):
            return MAGNITUDE[suffix], text[: -len(suffix)]
    return 1.0, text


def _is_pure_number(text: str) -> bool:
    """剥掉量级后缀与千分位后是不是纯数字（供会计负数判定）。

    "（100）" 内是 100 -> 会计负数；"（100台）" 内含单位 -> 括注，不取负。
    """
    _, rest = _split_magnitude(text.strip())
    return bool(NUMBER_RE.fullmatch(rest.replace(",", "").strip()))


def parse_numeric_cell(raw) -> Optional[float]:
    """解析表格单元格中的数值，支持 万/亿 量级与常见货币符号。

    返回 None 表示这不是一个干净的数字（调用方应跳过该单元格，
    而不是像原版那样替换成 0——那会把"缺失"伪装成"真的是 0"）。
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        return value if math.isfinite(value) else None

    original = str(raw).strip()
    if not original:
        return None

    # 含百分号的串必须整体形如「数字+%」，否则视为脏数据：
    # "30%" -> 30.0；"12%34" -> None（粘连，不进图表）
    if PERCENT_RE.search(original):
        cleaned = DECORATION_RE.sub("", original).strip()
        if PERCENT_VALUE_RE.match(cleaned):
            try:
                value = float(PERCENT_RE.sub("", cleaned))
                return value if math.isfinite(value) else None
            except (ValueError, TypeError):
                return None
        return None

    # 括号负数是会计约定：（100）-> -100、（1,200）-> -1200。
    # 但「（100台）」是「100 台」的括注——先在原始文本上判定，
    # 括号内含单位（非纯数字）就不取负，按普通正数解析。
    negative = False
    text = original
    if text.startswith("（") and text.endswith("）"):
        inner = text[1:-1]
        negative = _is_pure_number(inner)
        text = inner
    elif text.startswith("(") and text.endswith(")"):
        inner = text[1:-1]
        negative = _is_pure_number(inner)
        text = inner

    text = DECORATION_RE.sub("", text).strip()
    magnitude, text = _split_magnitude(text)
    text = text.replace(",", "").strip()
    if not NUMBER_RE.fullmatch(text):
        return None

    try:
        value = float(text) * magnitude
    except (ValueError, TypeError):
        return None

    if negative:
        value = -value
    return value if math.isfinite(value) else None


CHART_RULES = [
    ("pie", ["饼图", "饼状图", "占比", "比例", "份额", "构成", "组成", "百分比",
             "比重", "pie", "proportion", "share"]),
    ("line", ["折线", "折线图", "趋势", "增长", "变化", "走势", "曲线",
              "时间", "月度", "季度", "年度", "line", "trend"]),
    ("bar", ["柱状", "柱状图", "柱形", "排名", "top", "对比", "比较", "分布",
             "销售额", "金额", "数量", "业绩", "产量", "营收", "收入",
             "bar", "column", "chart"]),
]


def detect_chart_type_from_table(table: TableData, context_hints: List[str]) -> str:
    """智能检测表格数据适合的图表类型。返回 'pie' / 'bar' / 'line' / ''。

    v2.0.0 起这个函数真正接进了调用链：chart_type 留空时由它推断，
    修掉原版"定义了但无调用点"的死代码问题。
    """
    if not table or not table.rows:
        return ""

    hints = " ".join(str(h) for h in (context_hints or [])).lower()
    if table.headers:
        hints += " " + " ".join(str(h) for h in table.headers).lower()

    for ctype, keys in CHART_RULES:
        if any(k in hints for k in keys):
            return ctype

    # 无关键字时按数据形态推断
    numeric_cols = _numeric_columns(table)
    if not numeric_cols:
        return ""
    first_vals = numeric_cols[0][1]
    total = sum(v for v in first_vals if v is not None)
    count = len(first_vals)

    if 2 <= count <= 12 and 80 <= total <= 120 and all(v >= 0 for v in first_vals):
        return "pie"
    if count >= 2:
        return "bar"
    return ""


def _numeric_columns(table: TableData):
    """抽出完全可解析为数值的列，返回 [(列名, [值...]), ...]。

    有任何一个单元格解析失败，整列放弃——避免把脏数据混进图表。
    """
    if not table.rows:
        return []
    width = len(table.rows[0])
    columns = []
    for col_idx in range(1, width):
        name = (table.headers[col_idx]
                if table.headers and col_idx < len(table.headers)
                else f"系列{col_idx}")
        values = []
        complete = True
        for row in table.rows:
            if col_idx >= len(row):
                complete = False
                break
            value = parse_numeric_cell(row[col_idx])
            if value is None:
                complete = False
                break
            values.append(value)
        if complete and values:
            columns.append((name, values))
    return columns


def table_labels(table: TableData):
    """分类标签取每一行的第一列（不再把第一行当表头吞掉）。"""
    labels = []
    for row in table.rows:
        label = str(row[0]).strip() if row else ""
        labels.append(label or f"项目{len(labels) + 1}")
    return labels


def estimate_lines(text: str, chars_per_line: int) -> int:
    """估算一段文字在给定每行字数下占几行（含自动换行）。"""
    total = 0
    for line in str(text).split("\n"):
        if not line:
            total += 1
            continue
        width = sum(2 if ord(c) > 0x2E7F else 1 for c in line)
        total += max(1, math.ceil(width / max(1, chars_per_line)))
    return max(1, total)
