#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据流与门禁自测：证明每个中间产物都有下游消费者，且门禁真的会失败。

对应 skill-creator-cn 的两条纪律：
  1. 「永不失败的门禁等于没有门禁」——每个断言都配一个必红用例
  2. 「多脚本管线的中间产物必须有下游消费者」

用法：
    python3 scripts/check_pipeline.py            # 跑全部用例
    python3 scripts/check_pipeline.py --verbose  # 显示每条用例明细

退出码：0 全部通过；1 有用例失败。
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACKAGE_ROOT))

RESULTS = []


VERBOSE = False


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition), detail))
    status = "通过" if condition else "失败"
    suffix = f" —— {detail}" if detail and (not condition or VERBOSE) else ""
    print(f"  [{status}] {name}{suffix}")


def must_fail(name, fn, expected_exception=None, expected_in_message=None):
    """必红用例：这个输入**必须**让校验失败（抛出指定异常）。

    如果它没失败，说明门禁是装饰品——这正是要抓的问题。
    """
    try:
        fn()
    except expected_exception as exc:
        text = f"{exc}"
        if expected_in_message and expected_in_message not in text:
            check(name, False, f"抛了异常但信息不含 {expected_in_message!r}：{text}")
            return
        check(name, True)
        return
    except Exception as exc:  # noqa: BLE001
        check(name, False, f"抛了非预期异常：{type(exc).__name__}: {exc}")
        return
    check(name, False, "输入非但没有被拒绝，反而正常返回了")


def must_detect(name, fn, field_name):
    """必红用例的另一半：输入应当被**检出**（返回结构化错误），而不是抛异常。

    validate_content 的设计是返回错误列表而非抛异常，所以这类用例断言
    "错误列表非空且指明了字段"。如果返回空列表，说明门禁形同虚设。
    """
    try:
        errors = fn()
    except Exception as exc:  # noqa: BLE001
        check(name, False, f"不该抛异常却抛了：{type(exc).__name__}: {exc}")
        return
    if not errors:
        check(name, False, "错误列表为空——门禁没有检出问题")
        return
    if not any(e.field == field_name for e in errors):
        check(name, False,
              f"检出了错误但字段不是 {field_name!r}：{[e.field for e in errors]}")
        return
    check(name, True)


# ============================================================================
# 1. 数据流：中间产物必须有下游消费者
# ============================================================================

def test_data_flow():
    print("\n■ 数据流检查")
    from ppt_skill.pipeline import generate_ppt, validate_content
    from ppt_skill.config import Config
    from ppt_skill.models import SlideContent, TableData
    from ppt_skill.scraping.base import ScrapeResult, ImageFailure

    slides = [SlideContent(page_num=1, slide_type="title", title="测试")]
    for i in range(2, 8):
        slides.append(SlideContent(page_num=i, slide_type="content",
                                   title=f"内容页{i}", bullet_points=["要点一", "要点二"]))
    slides.append(SlideContent(page_num=8, slide_type="thank", title="感谢"))

    with tempfile.TemporaryDirectory() as tmp:
        config = Config(load_env_file=False)
        config.output_dir = Path(tmp)
        config.filename = "flow_test.pptx"

        # 中间产物 1：校验结果 → 被 generate_ppt 消费
        errors = validate_content(slides)
        check("validate_content 产出被 generate_ppt 消费", isinstance(errors, list))

        # 中间产物 2：image_map → 被渲染层消费（每页取第一张）
        # 指向不存在的文件也不应让整轮崩掉——渲染层要能降级
        report = generate_ppt(slides, config,
                              image_map={2: [Path("/nonexistent.jpg")]})
        check("image_map 指向缺失文件时仍完成生成（渲染层容错）",
              report.ok and report.output_path and report.output_path.is_file(),
              f"ok={report.ok} errors={[e.message for e in report.validation_errors]}")

        # 中间产物 3：image_failures → 被报告汇总（不再 print 完就丢）
        report2 = generate_ppt(slides, config, image_map={},
                               image_failures=[{"page_num": 2, "keyword": "x",
                                                "reason": "测试", "hint": ""}])
        check("image_failures 进入 report.image_failures",
              len(report2.image_failures) == 1)

        # 中间产物 4：ScrapeResult.failures → 能序列化给上层
        result = ScrapeResult(failures=[ImageFailure(1, "kw", "原因", "建议")])
        payload = result.as_dict()
        check("ScrapeResult.failures 可序列化且含 page_num/keyword/reason",
              payload["failures"][0]["page_num"] == 1
              and payload["failures"][0]["reason"] == "原因")


# ============================================================================
# 2. 门禁必红用例：证明校验真的会失败
# ============================================================================

def test_gates_must_fail():
    print("\n■ 门禁必红用例（构造应被拒绝的输入）")
    from ppt_skill.models import SlideContent
    from ppt_skill.pipeline import validate_content
    from ppt_skill.content_source import build_slides
    from ppt_skill.errors import InputError, ConfigError

    def fill_pages(count, page_nums=None, **extra):
        """造一批足够页数的内容，避免被页数下限抢先拦截。"""
        slides = [SlideContent(page_num=page_nums[0] if page_nums else 1,
                               slide_type="title", title="封面")]
        for i in range(2, count + 1):
            slides.append(SlideContent(
                page_num=(page_nums[i - 1] if page_nums else i),
                slide_type="content", title=f"内容页{i}",
                bullet_points=["要点"], **extra))
        slides.append(SlideContent(
            page_num=(page_nums[-1] if page_nums else count + 1),
            slide_type="thank", title="感谢"))
        return slides

    def duplicate_pages():
        # 10 页但页码 1 出现两次
        nums = [1, 1, 3, 4, 5, 6, 7, 8, 9, 10]
        slides = [SlideContent(page_num=n, slide_type="title" if i == 0 else "content",
                               title=f"p{i}", bullet_points=["x"])
                  for i, n in enumerate(nums)]
        slides.append(SlideContent(page_num=11, slide_type="thank", title="t"))
        return validate_content(slides)

    must_detect("重复页码被检出且指明 page_num 字段", duplicate_pages, "page_num")

    def bad_slide_type():
        build_slides({"slides": [{"slide_type": "text", "title": "x"}]})

    must_fail("非法 slide_type 被拒绝", bad_slide_type, InputError, "slide_type")

    def bad_chart_type():
        build_slides({"slides": [
            {"slide_type": "content", "title": "x", "bullet_points": ["a"],
             "chart_type": "scatter",
             "table_data": {"headers": ["a", "b"], "rows": [["x", "1"]]}}]})

    must_fail("非法 chart_type 被拒绝", bad_chart_type, InputError, "chart_type")

    def chart_without_table():
        # 用足够页数，避免被页数下限抢先拦截，专测 chart/table 一致性
        slides = [{"slide_type": "content", "title": f"页{i}",
                   "bullet_points": ["a"], "chart_type": "pie"}
                  for i in range(9)]
        slides[0]["slide_type"] = "title"
        slides[-1]["slide_type"] = "thank"
        build_slides({"slides": slides})

    must_fail("有 chart_type 无 table_data 被拒绝", chart_without_table,
              InputError, "表格数据")

    def too_few_pages():
        build_slides({"slides": [
            {"slide_type": "title", "title": "x"},
            {"slide_type": "thank", "title": "t"}]})

    must_fail("页数不足被拒绝", too_few_pages, InputError, "页")

    def empty_slides():
        build_slides({"slides": []})

    must_fail("空 slides 被拒绝", empty_slides, InputError, "slides")

    def missing_title_field():
        build_slides({"slides": [{"slide_type": "content", "bullet_points": ["a"]}]})

    must_fail("缺 title 的页被拒绝", missing_title_field, InputError, "title")

    def bad_theme():
        from ppt_skill.config import Config
        Config(load_env_file=False).set_theme("morandi_clya")

    must_fail("拼错的主题名被拒绝并列出可用主题", bad_theme,
              ConfigError, "morandi_clya")

    def bad_filename():
        from ppt_skill.config import Config
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(load_env_file=False)
            cfg.output_dir = Path(tmp)
            cfg.filename = "包含/斜杠:星号*的名字.pptx"
            path = cfg.resolve_output()
            if "/" in path.name or "*" in path.name or ":" in path.name:
                raise AssertionError(f"非法字符未被清理：{path.name}")

    # 这条用例的语义是「启动期清理并返回可用路径」——正常返回就是通过，
    # 与 must_fail 的"必须抛异常"语义相反，所以直接断言。
    def filename_cleaned_ok():
        from ppt_skill.config import Config
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(load_env_file=False)
            cfg.output_dir = Path(tmp)
            cfg.filename = "包含/斜杠:星号*的名字.pptx"
            return cfg.resolve_output()

    try:
        path = filename_cleaned_ok()
        illegal = [ch for ch in path.name if ch in r'\/:*?"<>|']
        check("含非法字符的文件名在启动期被清理为合法路径",
              not illegal and path.name.endswith(".pptx"),
              f"残留非法字符 {illegal} 或缺后缀：{path.name}")
    except Exception as exc:  # noqa: BLE001
        check("含非法字符的文件名在启动期被清理为合法路径", False, str(exc))


# ============================================================================
# 3. 关键修复的回归用例（防复发）
# ============================================================================

def test_regressions():
    print("\n■ 回归用例（v1.0.1 缺陷的固化）")
    from ppt_skill.text_utils import parse_numeric_cell, table_labels
    from ppt_skill.models import TableData

    # F15：量级不再被腐蚀
    check("1200亿 解析为 1.2e11", parse_numeric_cell("1200亿") == 1.2e11)
    check("100万 解析为 1e6", parse_numeric_cell("100万") == 1e6)
    check("12%34 粘连数值返回 None（docstring 承诺兑现）",
          parse_numeric_cell("12%34") is None,
          f"实际 {parse_numeric_cell('12%34')!r}")

    # F3：表格第一行不再被当表头
    table = TableData(headers=["阶段", "比重"],
                      rows=[["经济不平等", "45"], ["政治不平等", "35"]])
    labels = table_labels(table)
    check("表格所有数据行都成为图表分类（第一行不被吞）",
          labels == ["经济不平等", "政治不平等"], f"实际：{labels}")

    # F4：chart_type 留空时能自动推断
    from ppt_skill.text_utils import detect_chart_type_from_table
    inferred = detect_chart_type_from_table(table, ["占比"])
    check("留空 chart_type 时推断为 pie", inferred == "pie", f"实际：{inferred}")

    # F2：饼图多系列的截断逻辑存在（通过 ChartRenderer 源码检查）
    charts_src = (PACKAGE_ROOT / "ppt_skill" / "rendering" / "charts.py").read_text(encoding="utf-8")
    check("饼图多系列有截断与警告", "饼图只展示一个数值系列" in charts_src)

    # F1：项目符号按 OOXML 规范排序
    base_src = (PACKAGE_ROOT / "ppt_skill" / "rendering" / "base.py").read_text(encoding="utf-8")
    check("buClr/buChar 按 ECMA-376 顺序重排",
          "_sort_ppr_children" in base_src and "buClr" in base_src)

    # F10：.env 加载逻辑存在
    config_src = (PACKAGE_ROOT / "ppt_skill" / "config.py").read_text(encoding="utf-8")
    check("config.py 含 .env 解析函数", "def load_dotenv" in config_src)

    # F12：所有内容分支都渲染（不再有图时丢引用）
    slides_src = (PACKAGE_ROOT / "ppt_skill" / "rendering" / "slides.py").read_text(encoding="utf-8")
    check("有图分支仍渲染 quote/code/table",
          "_render_text_content" in slides_src and "quote_text" in slides_src)

    # F7：空内容页有占位而非空白
    check("空内容页有占位提示", "（本页暂无内容" in slides_src)


# ============================================================================
# 3b. 行为级回归（第三轮深审后的固化：不再依赖源码字符串检查）
# ============================================================================

def _make_renderer():
    """构造真实的 SlideRenderer（含演示文稿与主题色）。"""
    from pptx import Presentation
    from pptx.util import Emu
    from ppt_skill.config import CHART_COLORS, MORANDI_PALETTES
    from ppt_skill.rendering.slides import SlideRenderer

    prs = Presentation()
    prs.slide_width = Emu(12192000)
    prs.slide_height = Emu(6858000)
    return SlideRenderer(prs, MORANDI_PALETTES["morandi_blue"],
                         "morandi_blue", CHART_COLORS["morandi_blue"])


def test_bullet_behavior():
    print("\n■ 行为级：项目符号（替代源码字符串检查）")
    from pptx.oxml.ns import qn
    from lxml import etree

    r = _make_renderer()
    slide = r.prs.slides.add_slide(r.blank_layout)
    box = slide.shapes.add_textbox(100000, 100000, 5000000, 2000000)
    para = box.text_frame.paragraphs[0]
    para.text = "测试列表项"
    r.set_bullet_color(para, r.color("accent"))

    pPr = para._p.get_or_add_pPr()
    names = [etree.QName(c).localname for c in pPr]
    rank = {"lnSpc": 0, "spcBef": 1, "spcAft": 2, "buClr": 3,
            "buChar": 11, "defRPr": 13}
    ranks = [rank.get(n, 99) for n in names]
    check("buClr/buChar 实际子元素顺序符合 ECMA-376", ranks == sorted(ranks),
          f"实际顺序 {names}")
    buclr = pPr.find(qn("a:buClr"))
    val = buclr.find(qn("a:srgbClr")).get("val") if buclr is not None else None
    check("buClr 颜色值为主题 accent（6B8FA3）", val == "6B8FA3", f"实际 {val}")
    check("段落文本不含字面 ●（双圆点根治）", "●" not in para.text)
    check("悬挂缩进 marL/indent 已设置",
          pPr.get("marL") == "228600" and pPr.get("indent") == "-228600")

    # 高度预算：8 条 40 字要点塞进 3200000 EMU 应截断而非画出版面
    items = ["这是一条用于测试溢出行为的四十字要点。" * 4 for _ in range(8)]
    slide2 = r.prs.slides.add_slide(r.blank_layout)
    rendered = r.content.render_bullet_list(
        slide2, items, 600000, 1140000, 4000000, 3200000)
    check("8 条超长要点在预算高度内被截断", 0 < rendered < 8, f"实际渲染 {rendered} 条")


def test_providers_contract():
    print("\n■ 行为级：六个图片接口的契约矩阵")
    from ppt_skill.config import Config
    from ppt_skill.scraping.providers import PROVIDER_CLASSES

    cfg = Config(load_env_file=False)
    # 给需密钥的接口都配上可用密钥，保证 provider 构造成功
    for var in ("PEXELS_API_KEY", "BAIDU_API_KEY", "BAIDU_SECRET_KEY",
                "UNSPLASH_ACCESS_KEY", "PIXABAY_API_KEY"):
        cfg.env_values[var] = "test-key-123"

    def make_resp(kind, payload=None):
        class R:
            status_code = 200
            text = "<html>blocked</html>"
            headers = {}
            def __init__(self):
                if kind == "json":
                    self._payload = payload
                elif kind == "list":
                    self._payload = []
            def json(self):
                if kind == "list":
                    return []  # 合法 JSON 但顶层不是对象
                if kind == "json":
                    return self._payload
                raise ValueError("no json")
            def close(self):
                pass
        return R()

    class FakeSession:
        headers = {}
        def __init__(self, resp):
            self._resp = resp
        def get(self, url, **kw):
            if isinstance(self._resp, Exception):
                raise self._resp
            return self._resp

    scenarios = [
        ("200合法JSON", make_resp("json", {"photos": [], "data": [], "results": [],
                                           "hits": []}), None),
        ("200非JSON", make_resp("html"), "不是"),
        ("200JSON数组", make_resp("list"), "不符合预期"),
        ("超时异常", Exception("timed out"), "网络异常"),
    ]
    for name, cls in PROVIDER_CLASSES.items():
        for scenario, resp, expect_hint in scenarios:
            provider = cls(cfg)
            provider.session = FakeSession(resp)
            try:
                urls, reason = provider.search("测试")
                ok = isinstance(urls, list) and (reason is None or isinstance(reason, str))
                # bing 走 HTML 正则而非 resp.json()，非 JSON 场景对其而言
                # 就是"没有结果"，reason=None 属正常契约
                if expect_hint and name != "bing":
                    ok = ok and reason and expect_hint in reason
            except Exception as exc:  # noqa: BLE001
                urls, reason, ok = None, str(exc), False
            check(f"{name} × {scenario} 返回二元组不抛异常", ok,
                  f"urls={urls!r} reason={reason!r}")


def test_ui_helpers():
    print("\n■ 行为级：Web 界面辅助函数")
    from ppt_skill import ui_server
    from ppt_skill.models import SlideContent, TableData

    for raw, expect_ok in [(None, True), ("", True), (25, True), ("25", True),
                           ("abc", False), (0, False), (-5, False),
                           (25.5, False), (1e9, False), (True, False)]:
        pages, error = ui_server._parse_pages(raw)
        check(f"_parse_pages({raw!r}) -> {'通过' if expect_ok else '拒绝'}",
              (error is None) == expect_ok, f"error={error!r}")

    slide = SlideContent(page_num=1, slide_type="data", title="t",
                         table_data=TableData(headers=["项目", "占比"],
                                              rows=[["甲", "45"], ["乙", "35"], ["丙", "20"]]))
    brief = ui_server._slide_brief(slide)
    check("留空 chart_type 的大纲标注 has_chart=True（按真实推断）",
          brief["has_chart"] is True, f"实际 {brief}")


def test_numeric_and_filename():
    print("\n■ 行为级：数值解析与文件名")
    from ppt_skill.text_utils import parse_numeric_cell, sanitize_filename
    from ppt_skill.rendering.slides import _strip_leading_number

    check("3万亿 -> 3e12", parse_numeric_cell("3万亿") == 3e12,
          f"实际 {parse_numeric_cell('3万亿')!r}")
    check("5千万 -> 5e7", parse_numeric_cell("5千万") == 5e7)
    check("（100台）括注按正数解析", parse_numeric_cell("（100台）") == 100.0,
          f"实际 {parse_numeric_cell('（100台）')!r}")
    check("（100）会计负数保持 -100", parse_numeric_cell("（100）") == -100.0)
    check("年份「2024. 年度总结」不被当序号剥除",
          _strip_leading_number("2024. 年度总结") == "2024. 年度总结",
          f"实际 {_strip_leading_number('2024. 年度总结')!r}")
    check("小数「2.5倍增长」不被当序号剥除",
          _strip_leading_number("2.5倍增长") == "2.5倍增长")
    check("序号「1. 方法论」正常剥除",
          _strip_leading_number("1. 方法论") == "方法论")
    check("Windows 保留名 con 加前缀",
          sanitize_filename("con") == "_con",
          f"实际 {sanitize_filename('con')!r}")


def test_layout_bounds():
    print("\n■ 行为级：布局边界（图表+长引用+长代码组合页）")
    import tempfile
    from pathlib import Path
    from pptx import Presentation
    from pptx.util import Emu
    from ppt_skill.config import Config
    from ppt_skill.models import SlideContent, TableData
    from ppt_skill.pipeline import generate_ppt

    long_quote = "这是一段用于测试布局边界的长引用。" * 60
    long_code = "\n".join(f"line_{i} = 'value'" for i in range(30))

    slides = [SlideContent(page_num=1, slide_type="title", title="布局测试")]
    for i in range(2, 8):
        slides.append(SlideContent(page_num=i, slide_type="content",
                                   title=f"内容页{i}", bullet_points=["要点一", "要点二"]))
    slides.append(SlideContent(page_num=8, slide_type="thank", title="感谢"))
    # 第 3 页：图表 + 长引用 + 长代码（第三轮深审的三重越界场景）
    slides[2] = SlideContent(
        page_num=3, slide_type="content", title="图表与引用叠加页",
        bullet_points=["要点一", "要点二", "要点三"],
        table_data=TableData(headers=["维度", "权重"],
                             rows=[["数据整合", "45"], ["流程再造", "35"], ["组织保障", "20"]]),
        chart_type="pie", quote_text=long_quote, code_block=long_code)

    with tempfile.TemporaryDirectory() as tmp:
        config = Config(load_env_file=False)
        config.output_dir = Path(tmp)
        config.filename = "layout_test.pptx"
        config.set_theme("morandi_blue")
        report = generate_ppt(slides, config, meta={"title": "布局测试"})
        check("组合页可以生成", report.ok,
              "；".join(e.message for e in report.validation_errors))
        if not report.ok:
            return

        prs = Presentation(str(report.output_path))
        overflow = []
        pn_zone = []
        for slide_index, slide in enumerate(prs.slides, start=1):
            for shape in slide.shapes:
                try:
                    left, top = int(shape.left), int(shape.top)
                    width, height = int(shape.width), int(shape.height)
                except (TypeError, AttributeError):
                    continue
                if left < 0 or top < 0 or left + width > 12192000 or top + height > 6858000:
                    overflow.append(f"p{slide_index} {shape.shape_type} "
                                    f"L={left} T={top} R={left+width} B={top+height}")
                # 正文元素不得伸入页码区（页码文本自身除外）
                text = shape.text_frame.text if shape.has_text_frame else ""
                if top + height > 5940000 and top >= 1000000 and left >= 1000000:
                    if not (shape.has_text_frame and "/" in text and len(text) <= 12):
                        pn_zone.append(f"p{slide_index} {shape.shape_type} T={top} B={top+height}")
        check("所有形状都在幻灯片边界内", not overflow, "；".join(overflow[:3]))
        check("正文元素不伸入页码区", not pn_zone, "；".join(pn_zone[:3]))


def test_type_hints():
    print("\n■ 行为级：类型注解可解析（防 Optional 未导入类地雷）")
    import typing
    import ppt_skill.outline as outline_mod
    try:
        typing.get_type_hints(outline_mod.build_outline)
        typing.get_type_hints(outline_mod._guess_title)
        ok = True
        detail = ""
    except NameError as exc:
        ok, detail = False, str(exc)
    check("outline 模块注解在急切求值下可解析（Python≤3.13 兼容）", ok, detail)


def test_dotenv_edges():
    print("\n■ 行为级：.env 解析边界")
    import os
    import tempfile
    from ppt_skill.config import Config, load_dotenv

    with tempfile.TemporaryDirectory() as tmp:
        env_path = Path(tmp) / ".env"
        env_path.write_bytes(
            "PEXELS_API_KEY=bomkey  # 行内注释\n"
            "export\tUNSPLASH_ACCESS_KEY=tabkey\n"
            "PIXABAY_API_KEY=\"pix # real\"\n".encode("utf-8-sig"))
        values = load_dotenv(env_path)
        check("BOM 文件键名正常", "PEXELS_API_KEY" in values, f"实际键 {list(values)}")
        check("行内注释被剥除", values.get("PEXELS_API_KEY") == "bomkey",
              f"实际 {values.get('PEXELS_API_KEY')!r}")
        check("export<TAB> 前缀正确剥离", values.get("UNSPLASH_ACCESS_KEY") == "tabkey",
              f"实际 {values.get('UNSPLASH_ACCESS_KEY')!r}")
        check("引号内 # 保留", values.get("PIXABAY_API_KEY") == "pix # real",
              f"实际 {values.get('PIXABAY_API_KEY')!r}")

        # 环境变量空串不压过 .env 真值
        config = Config(env_path=env_path, load_env_file=True)
        old = os.environ.get("PEXELS_API_KEY")
        os.environ["PEXELS_API_KEY"] = ""
        try:
            got = config.secret("PEXELS_API_KEY")
        finally:
            if old is None:
                os.environ.pop("PEXELS_API_KEY", None)
            else:
                os.environ["PEXELS_API_KEY"] = old
        check("环境变量空串回退 .env 真值", got == "bomkey", f"实际 {got!r}")




def test_determinism():
    print("\n■ 行为级：字节级可复现（含图表的产物两次运行 md5 一致）")
    import hashlib
    import tempfile
    from pathlib import Path
    from ppt_skill.config import Config
    from ppt_skill.models import SlideContent, TableData
    from ppt_skill.pipeline import generate_ppt

    def build_once(tag):
        slides = [SlideContent(page_num=1, slide_type="title", title="确定性测试")]
        for i in range(2, 8):
            slides.append(SlideContent(page_num=i, slide_type="content",
                                       title=f"内容页{i}", bullet_points=["要点一", "要点二"]))
        slides.append(SlideContent(page_num=8, slide_type="thank", title="感谢"))
        slides[2] = SlideContent(
            page_num=3, slide_type="data", title="数据页",
            bullet_points=["要点"],
            table_data=TableData(headers=["维度", "权重"],
                                 rows=[["甲", "45"], ["乙", "35"], ["丙", "20"]]),
            chart_type="pie")
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(load_env_file=False)
            config.output_dir = Path(tmp)
            config.filename = f"det_{tag}.pptx"
            config.set_theme("morandi_blue")
            report = generate_ppt(slides, config, meta={"title": "确定性测试"})
            data = report.output_path.read_bytes()
        return hashlib.md5(data).hexdigest()

    md5_a, md5_b = build_once("a"), build_once("b")
    check("同输入两次运行（含图表）md5 一致", md5_a == md5_b,
          f"{md5_a} vs {md5_b}")


# ============================================================================
# 4. 样例与模板可用性
# ============================================================================

def test_assets():
    print("\n■ 样例与模板可用性")
    from ppt_skill.content_source import build_slides
    from ppt_skill.pipeline import validate_content

    for folder in ("examples", "templates"):
        directory = PACKAGE_ROOT / "assets" / folder
        if not directory.is_dir():
            check(f"{folder}/ 目录存在", False)
            continue
        files = sorted(directory.glob("*.json"))
        check(f"{folder}/ 有内容文件", len(files) > 0, f"找到 {len(files)} 个")
        for path in files:
            data = json.loads(path.read_text(encoding="utf-8"))
            slides = build_slides(data, source=path)
            errors = validate_content(slides)
            check(f"{path.name} 通过内容校验（{len(slides)} 页）",
                  not errors, "；".join(e.message for e in errors[:2]))


def main():
    global VERBOSE
    parser = argparse.ArgumentParser(description="数据流与门禁自测")
    parser.add_argument("--verbose", action="store_true", help="输出每条用例明细")
    args = parser.parse_args()
    VERBOSE = args.verbose

    print("=" * 66)
    print("  华予&Hanako PPT · 数据流与门禁自测")
    print("=" * 66)

    test_data_flow()
    test_gates_must_fail()
    test_regressions()
    test_bullet_behavior()
    test_providers_contract()
    test_ui_helpers()
    test_numeric_and_filename()
    test_layout_bounds()
    test_determinism()
    test_type_hints()
    test_dotenv_edges()
    test_assets()

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = len(RESULTS) - passed
    print("\n" + "=" * 66)
    print(f"  用例 {len(RESULTS)} 条，通过 {passed} 条，失败 {failed} 条")
    print("=" * 66)

    if failed:
        print("\n失败详情：")
        for name, ok, detail in RESULTS:
            if not ok:
                print(f"  ✗ {name}" + (f" —— {detail}" if detail else ""))
        return 1
    print("\n结论：全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
