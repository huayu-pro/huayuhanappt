"""内容来源：从外部 JSON / YAML 文件加载 PPT 内容清单。

这是"不用改代码就能生成 PPT"的关键一环：用户编辑 assets/templates/ 下的
JSON 模板，或用 Web 界面导出 JSON，都不必碰 Python。

JSON 结构：
{
  "meta": {"title": "...", "presenter": "...", "institution": "...", "date": "..."},
  "slides": [
    {"page_num": 1, "slide_type": "title", "title": "...", "subtitle": "..."},
    {"page_num": 4, "slide_type": "data", "title": "...",
     "bullet_points": ["..."],
     "table_data": {"headers": ["阶段", "比重"],
                    "rows": [["经济不平等", "45"], ["政治不平等", "35"]]},
     "chart_type": "pie"}
  ]
}

page_num 可省略，按顺序自动编号。
"""

import json
from pathlib import Path
from typing import List

from .errors import InputError
from .models import SlideContent, TableData, VALID_CHART_TYPES, VALID_SLIDE_TYPES


def load_content(path):
    """读取 JSON 或 YAML 内容文件。

    返回 (slides, data) 二元组：slides 是校验过的 SlideContent 列表，
    data 是原始字典（调用方取 meta 段用）。单返回值会让调用方再写一份
    文件读取逻辑，两套实现的错误口径会分叉。
    """
    p = Path(path)
    if not p.is_file():
        raise InputError(
            f"找不到内容文件：{p}",
            "检查路径是否正确；模板在 assets/templates/ 下，样例在 assets/examples/ 下",
        )
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise InputError(f"内容文件读取失败：{p}（{exc}）", "检查文件权限与编码（需为 UTF-8）")

    suffix = p.suffix.lower()
    if suffix in (".yaml", ".yml"):
        data = _parse_yaml(text, p)
    else:
        data = _parse_json(text, p)

    return build_slides(data, source=p), data


def _parse_json(text, path):
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(
            f"内容文件不是合法 JSON：{path} 第 {exc.lineno} 行第 {exc.colno} 列（{exc.msg}）",
            "用 JSON 校验工具定位语法错误；注意字符串里的引号要转义",
        )


def _parse_yaml(text, path):
    try:
        import yaml
    except ImportError:
        raise InputError(
            f"读取 YAML 需要 PyYAML：{path}",
            "pip install pyyaml，或把内容文件改成 .json 格式",
        )
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise InputError(f"内容文件不是合法 YAML：{path}（{exc}）", "检查缩进与冒号后的空格")


def build_slides(data, source=None) -> List[SlideContent]:
    """把字典结构转成 SlideContent 列表，带结构化校验。"""
    where = f"（来自 {source}）" if source else ""
    if not isinstance(data, dict):
        raise InputError(f"内容文件的顶层必须是对象{where}", "参考 assets/examples/minimal_8.json 的结构")
    if "slides" not in data or not isinstance(data["slides"], list):
        raise InputError(f"内容文件缺少 slides 数组{where}", "在顶层加 \"slides\": [ ... ]")

    slides = []
    for index, raw in enumerate(data["slides"], start=1):
        if not isinstance(raw, dict):
            raise InputError(f"第 {index} 页不是对象{where}", "每一页都要写成 {\"slide_type\": ..., \"title\": ...}")
        slide = _build_one(raw, index, where)
        slides.append(slide)

    if not slides:
        raise InputError(f"slides 数组是空的{where}", "至少写一页内容")

    _check_page_consistency(slides, where)
    return slides


def _check_page_consistency(slides, where):
    """跨页一致性检查。

    这些检查放在加载层而不是只放在 pipeline 层，是因为 Web 界面的
    outline 预览等路径也走 build_slides——只在一处拦会被别的路径绕过。
    """
    from .config import LIMITS

    min_pages = LIMITS["min_pages"]
    max_pages = LIMITS["max_pages"]
    if len(slides) < min_pages or len(slides) > max_pages:
        raise InputError(
            f"共 {len(slides)} 页，超出 {min_pages}-{max_pages} 页范围{where}",
            f"增减内容使总页数落在 {min_pages}-{max_pages} 页；学术汇报推荐 "
            f"{LIMITS['recommended_pages'][0]}-{LIMITS['recommended_pages'][1]} 页",
        )

    for slide in slides:
        if slide.chart_type and not slide.table_data:
            raise InputError(
                f"第 {slide.page_num} 页指定了 chart_type="
                f"{slide.chart_type!r} 但没有表格数据{where}",
                "补上 table_data（headers + rows），或把 chart_type 留空让脚本自动推断",
            )


def _build_one(raw, index, where):
    slide_type = str(raw.get("slide_type", "content")).strip()
    if slide_type not in VALID_SLIDE_TYPES:
        raise InputError(
            f"第 {index} 页 slide_type 非法：{slide_type!r}{where}",
            f"只能是：{' / '.join(VALID_SLIDE_TYPES)}",
        )
    title = str(raw.get("title", "")).strip()
    if not title:
        raise InputError(f"第 {index} 页缺少 title{where}", "每一页都要有标题文字")

    chart_type = str(raw.get("chart_type", "") or "").strip()
    if chart_type not in VALID_CHART_TYPES:
        raise InputError(
            f"第 {index} 页 chart_type 非法：{chart_type!r}{where}",
            "只能是 pie / bar / line，或留空让脚本自动推断",
        )

    page_num = raw.get("page_num")
    if page_num is None:
        page_num = index
    if isinstance(page_num, float) and not page_num.is_integer():
        raise InputError(
            f"第 {index} 页 page_num 是小数：{page_num!r}{where}",
            "page_num 写 1、2、3 这样的整数；小数会制造重复页码",
        )
    try:
        page_num = int(page_num)
    except (TypeError, ValueError):
        raise InputError(f"第 {index} 页 page_num 不是整数：{page_num!r}{where}", "page_num 写 1、2、3 这样的整数")

    table_data = None
    raw_table = raw.get("table_data")
    if raw_table:
        if not isinstance(raw_table, dict):
            raise InputError(f"第 {index} 页 table_data 必须是对象{where}", "写成 {\"headers\": [...], \"rows\": [[...]]}")
        table_data = TableData(
            headers=_as_str_list(raw_table.get("headers", []), index, "headers", where),
            rows=_as_row_list(raw_table.get("rows", []), index, where),
        )

    bullets = _as_str_list(raw.get("bullet_points") or [], index, "bullet_points", where)
    keywords = _as_str_list(raw.get("image_keywords") or [], index, "image_keywords", where)

    return SlideContent(
        page_num=page_num,
        slide_type=slide_type,
        title=title,
        subtitle=str(raw.get("subtitle", "") or ""),
        bullet_points=bullets,
        image_keywords=keywords,
        table_data=table_data,
        chart_type=chart_type,
        code_block=str(raw.get("code_block", "") or ""),
        quote_text=str(raw.get("quote_text", "") or ""),
    )


def _as_str_list(value, index, field, where):
    """把字段收敛为字符串列表，非列表类型显式报错。

    原实现 `"abc"` 会被按字符拆成 ['a','b','c']、`5` 抛裸 TypeError
    （exit 1）——两者都不是用户能看懂的失败方式。
    """
    if value is None:
        return []
    if isinstance(value, str) or not hasattr(value, "__iter__"):
        raise InputError(
            f"第 {index} 页 {field} 必须是数组{where}",
            f'写成 ["条目一", "条目二"]；当前值 {value!r} 会被按字符拆散或崩溃',
        )
    return [str(item) for item in value]


def _as_row_list(value, index, where):
    """表格行收敛：每行都必须是数组，None 等脏值给可读报错。"""
    if value is None:
        return []
    if not hasattr(value, "__iter__") or isinstance(value, (str, dict)):
        raise InputError(
            f"第 {index} 页 table_data.rows 必须是二维数组{where}",
            '写成 [["标签", "数值"], ...]',
        )
    rows = []
    for row_index, row in enumerate(value, start=1):
        if row is None or not hasattr(row, "__iter__") or isinstance(row, (str, dict)):
            raise InputError(
                f"第 {index} 页 table_data.rows 第 {row_index} 行不是数组{where}",
                f"每一行都要写成 [\"单元格\", ...]；当前是 {row!r}",
            )
        rows.append([str(cell) for cell in row])
    return rows


def extract_meta(data) -> dict:
    """取出 meta 段（标题/汇报人/院校/日期），缺省给空串。"""
    meta = data.get("meta") if isinstance(data, dict) else None
    if not isinstance(meta, dict):
        return {"title": "", "presenter": "", "institution": "", "date": ""}
    return {
        "title": str(meta.get("title", "") or ""),
        "presenter": str(meta.get("presenter", "") or ""),
        "institution": str(meta.get("institution", "") or ""),
        "date": str(meta.get("date", "") or ""),
    }
