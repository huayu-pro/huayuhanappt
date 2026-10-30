"""六种页面类型的渲染。

相对原版的关键修复：

M11 非确定性渲染：原版"有配图"分支只渲染 bullet_points，
     quote_text / code_block / table_data 被静默丢弃——同一份内容
     有没有爬到大图，输出版式完全不同。现在所有分支都渲染全部内容元素。
M3  封面/章节/致谢页原本接收 image_path 却完全不用，配图白爬。
     现在三个页型都把 image_path 用上（章节页为半透明遮罩）。
H6  空 bullet_points 不再渲染出"只有标题的空白页"，
     改为明确占位文字并计入告警。
F17 章节号正则支持「第一部分：」「一、」「01.」三种写法。
"""

import re

from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Pt

from ..text_utils import detect_chart_type_from_table
from .base import Renderer, to_rgb
from .charts import ChartRenderer
from .content import ContentRenderer

# 章节号：中文"第一部分" / "一、" / "01." 都认
SECTION_NUM_RE = re.compile(
    r"^\s*(?:第[一二三四五六七八九十百0-9]+[部分篇章节]|[一二三四五六七八九十]+|0\d?)\s*[、.．:：]")

EMPTY_PLACEHOLDER = "（本页暂无内容，请在内容文件中补充要点）"

# 条目形如「1. 」「2、」「3) 」——按有序列表渲染。
# 限定 1-2 位数字且点后不能紧跟数字：年份「2024.」与小数「2.5倍」
# 是内容不是序号，剥掉它们等于静默丢数据。
ORDERED_ITEM_RE = re.compile(r"^\s*\d{1,2}\s*(?:[、)）]|\.(?!\d))\s*")


def _looks_ordered(items):
    """全部条目都以小序号开头（且至少两条）时判定为有序列表。

    宁可漏判（按圆点渲染也不难看），不可误判——把普通要点渲染成
    编号圆圈会显得很刻意。
    """
    filled = [str(i) for i in items if str(i).strip()]
    if len(filled) < 2:
        return False
    return all(ORDERED_ITEM_RE.match(item) for item in filled)


def _strip_leading_number(text):
    """剥掉「1. 」这类小序号前缀。年份与小数形态不匹配，原样保留。"""
    return ORDERED_ITEM_RE.sub("", str(text), count=1).strip()


class SlideRenderer(Renderer):
    """按 slide_type 分发生成各页面。"""

    def __init__(self, presentation, palette, palette_name, chart_colors, meta=None):
        super().__init__(presentation, palette, palette_name, chart_colors)
        self.content = ContentRenderer(self)
        self.charts = ChartRenderer(self)
        self.meta = meta or {}
        self.warnings = []

    # ---- 入口 ----
    def add_slide(self, slide_content, image_path, total_pages):
        st = slide_content.slide_type
        if st == "title":
            self.add_title_slide(slide_content, image_path)
        elif st == "section":
            self.add_section_slide(slide_content, image_path)
        elif st == "data":
            self.add_data_slide(slide_content, image_path, total_pages)
        elif st == "reference":
            self.add_reference_slide(slide_content, total_pages)
        elif st == "thank":
            self.add_thank_slide(slide_content, image_path)
        else:
            self.add_content_slide(slide_content, image_path, total_pages)

    # ---- 封面 ----
    def add_title_slide(self, sc, image_path=None):
        slide = self.prs.slides.add_slide(self.blank_layout)
        self.add_background(slide)
        self.add_decorations(slide)

        if image_path:
            self._add_cover_image(slide, image_path)

        vline = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Emu(457000), Emu(1480000),
            Emu(69000), Emu(1820000))
        vline.fill.solid()
        vline.fill.fore_color.rgb = self.color("accent")
        vline.line.fill.background()
        vline.shadow.inherit = False

        self.add_textbox(
            slide, Emu(800000), Emu(1480000), Emu(9690000), Emu(1600000),
            sc.title, font_size=Pt(40),
            font_color=self.color("title"), bold=True)

        if sc.subtitle:
            self.add_textbox(
                slide, Emu(800000), Emu(3420000), Emu(9120000), Emu(914000),
                sc.subtitle, font_size=Pt(18), font_color=self.color("text"))

        hline = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Emu(800000), Emu(4790000),
            Emu(2850000), Emu(34000))
        hline.fill.solid()
        hline.fill.fore_color.rgb = self.color("secondary")
        hline.line.fill.background()
        hline.shadow.inherit = False

        info = self._presenter_lines()
        self.add_multiline_textbox(
            slide, Emu(800000), Emu(5130000), Emu(9120000), Emu(1370000),
            info, font_size=Pt(14), font_color=self.color("accent"),
            alignment=PP_ALIGN.CENTER, line_spacing=1.8)

    def _add_cover_image(self, slide, image_path):
        """封面右侧配图（原版完全没用这张图）。"""
        try:
            pic = slide.shapes.add_picture(
                str(image_path), Emu(8100000), Emu(1500000),
                Emu(3600000), Emu(2700000))
            # 半透明遮罩，让图不抢标题
            self._apply_transparency(pic, 25)
        except Exception as exc:
            print(f"    ⚠️  封面配图插入失败：{exc}")

    def _apply_transparency(self, picture, alpha_percent):
        """给图片加一层半透明遮罩（python-pptx 无原生 API，走 XML）。"""
        try:
            from pptx.oxml.ns import qn
            from lxml import etree
            sp = picture._element
            blipFill = sp.find(qn("p:blipFill"))
            if blipFill is None:
                return
            blip = blipFill.find(qn("a:blip"))
            if blip is None:
                return
            alpha = etree.SubElement(blip, qn("a:alphaModFix"))
            alpha.set("amt", str(int((100 - alpha_percent) * 1000)))
        except Exception:
            pass

    def _presenter_lines(self):
        lines = []
        presenter = self.meta.get("presenter") or ""
        institution = self.meta.get("institution") or ""
        date = self.meta.get("date") or ""
        if presenter:
            lines.append(f"汇报人：{presenter}")
        if institution:
            lines.append(institution)
        if date:
            lines.append(date)
        return lines or [""]

    # ---- 章节过渡 ----
    def add_section_slide(self, sc, image_path=None):
        slide = self.prs.slides.add_slide(self.blank_layout)
        self.add_background(slide)
        self.add_decorations(slide)

        num_text, title_text = self._split_section_number(sc.title)

        if image_path:
            self._add_section_image(slide, image_path)

        stripe = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Emu(2850000), Emu(2740000),
            Emu(914000), Emu(914000))
        stripe.fill.solid()
        stripe.fill.fore_color.rgb = self.color("primary")
        stripe.line.fill.background()
        stripe.shadow.inherit = False

        self.add_textbox(
            slide, Emu(3190000), Emu(2620000), Emu(7530000), Emu(1140000),
            title_text, font_size=Pt(28),
            font_color=self.color("title"), bold=True)

        if num_text:
            self.add_textbox(
                slide, Emu(3190000), Emu(2050000), Emu(3420000), Emu(570000),
                num_text, font_size=Pt(16), font_color=self.color("accent"))

        if sc.subtitle:
            self.add_textbox(
                slide, Emu(3190000), Emu(3900000), Emu(7530000), Emu(570000),
                sc.subtitle, font_size=Pt(15), font_color=self.color("text"))

    def _split_section_number(self, title):
        match = SECTION_NUM_RE.match(title or "")
        if match:
            return match.group().strip(), title[match.end():].strip()
        return "", title

    def _add_section_image(self, slide, image_path):
        """章节页右侧配图 + 半透明遮罩（SKILL.md 宣传的"半透明遮罩"）。"""
        try:
            pic = slide.shapes.add_picture(
                str(image_path), Emu(8600000), Emu(2400000),
                Emu(3100000), Emu(2000000))
            self._apply_transparency(pic, 45)
        except Exception as exc:
            print(f"    ⚠️  章节页配图插入失败：{exc}")

    def _add_thank_image(self, slide, image_path):
        """致谢页右上角配图 + 半透明遮罩（兑现 CHANGELOG F13 承诺）。"""
        try:
            pic = slide.shapes.add_picture(
                str(image_path), Emu(9300000), Emu(280000),
                Emu(2400000), Emu(1500000))
            self._apply_transparency(pic, 45)
        except Exception as exc:
            print(f"    ⚠️  致谢页配图插入失败：{exc}")

    # ---- 正文页 ----
    def add_content_slide(self, sc, image_path=None, total_pages=0):
        slide = self.prs.slides.add_slide(self.blank_layout)
        self.add_background(slide)
        self.add_decorations(slide)
        self.add_slide_header(slide, sc.title)

        chart_type = self._resolve_chart_type(sc)
        has_chart = bool(chart_type and sc.table_data)

        if has_chart:
            self._render_chart_content(slide, sc, chart_type)
        else:
            self._render_text_content(slide, sc, image_path)

        self.add_page_number(slide, sc.page_num, total_pages)

    def _render_chart_content(self, slide, sc, chart_type):
        """图表 + 左侧要点，外加引用/代码块（按剩余空间动态布局）。

        引用与代码块排在图表下方——原版在"有图表"分支把它们整个丢掉，
        等于同一份内容两次运行版式不同。v2.0.1 起坐标按图表实际底边
        动态计算，且各元素高度受页码区上沿约束——修掉固定 y=4500000
        导致的"引用压图表、代码块出幻灯片"三重越界。
        """
        has_extras = bool(sc.quote_text or sc.code_block)
        text_width = Emu(4000000) if sc.bullet_points else Emu(0)
        if sc.bullet_points:
            bullet_height = Emu(3200000) if has_extras else self.CONTENT_HEIGHT
            self._render_bullets_with_budget(
                slide, sc, self.MARGIN_LEFT, self.CONTENT_TOP,
                text_width, bullet_height)
            chart_left = self.MARGIN_LEFT + text_width + Emu(200000)
            chart_width = self.CONTENT_WIDTH - text_width - Emu(200000)
        else:
            chart_left = self.MARGIN_LEFT
            chart_width = self.CONTENT_WIDTH

        # 页面同时有引用/代码时收缩图表，给下方留出可用空间
        chart_height = Emu(2800000) if has_extras else Emu(4300000)

        ok = self.charts.add_chart(
            slide, chart_type, sc.table_data,
            chart_left, self.CONTENT_TOP, chart_width, chart_height)

        if not ok:
            # 真实降级：画表格，而不是像原版那样只 return None
            self.content.render_table(
                slide, sc.table_data.headers or [], sc.table_data.rows,
                chart_left, self.CONTENT_TOP,
                chart_width, chart_height, page_num=sc.page_num)

        if has_extras:
            self._render_extras(slide, sc,
                                start_y=self.CONTENT_TOP + chart_height + Emu(100000))

    def _render_extras(self, slide, sc, start_y):
        """在 start_y 与页码区上沿之间渲染引用块与代码块。

        空间不足的元素整体跳过并记 warning——宁可少渲染并说明，
        不可把内容画到幻灯片外或盖住页码。
        """
        inner = Emu(400000)
        width = self.CONTENT_WIDTH - inner * 2
        y = start_y
        if sc.quote_text:
            available = self.CONTENT_SAFE_BOTTOM - y
            height = self.content.render_quote(
                slide, sc.quote_text,
                self.MARGIN_LEFT + inner, y, width,
                max_height=int(available) if available > 0 else 0)
            if height > 0:
                y += height + Emu(150000)
            else:
                self.warnings.append(
                    f"第 {sc.page_num} 页引用块因版面空间不足未渲染，"
                    f"建议缩短引用或移除本页图表")
        if sc.code_block:
            available = self.CONTENT_SAFE_BOTTOM - y
            height = self.content.render_code_block(
                slide, sc.code_block,
                self.MARGIN_LEFT + inner, y, width,
                max_height=int(available) if available > 0 else 0)
            if height <= 0:
                self.warnings.append(
                    f"第 {sc.page_num} 页代码块因版面空间不足未渲染，"
                    f"建议缩短代码或拆分为两页")

    def _render_bullets_with_budget(self, slide, sc, left, top, width, height):
        """渲染要点列表并对截断记 warning。返回实际渲染条数。

        有序判定成立走编号圆圈；否则走圆点路径，并按项剥除小序号前缀
        （正则保证「2024.」年份与「2.5倍」小数不匹配、原样保留），
        避免「● 1. 甲」双重标记。
        """
        total = len([b for b in sc.bullet_points if str(b).strip()])
        if _looks_ordered(sc.bullet_points):
            items = [_strip_leading_number(b) for b in sc.bullet_points]
            rendered = self.content.render_ordered_list(
                slide, items, left, top, width, height)
        else:
            items = [(_strip_leading_number(b) if ORDERED_ITEM_RE.match(str(b))
                      else str(b))
                     for b in sc.bullet_points if str(b).strip()]
            rendered = self.content.render_bullet_list(
                slide, items, left, top, width, height)
        if isinstance(rendered, int) and 0 < rendered < total:
            self.warnings.append(
                f"第 {sc.page_num} 页要点过多，仅展示前 {rendered} 条（共 {total} 条），"
                f"建议拆分为两页")
        return rendered

    def _render_text_content(self, slide, sc, image_path):
        """文字 + 引用 + 代码 + 配图，任何组合都完整渲染（修 M11）。

        每个元素渲染前检查剩余空间：y 超过页码区上沿就跳过并告警，
        高度参数永不传负值——长引用叠长代码不再把要点挤进页脚。
        """
        inner = Emu(400000)
        width = self.CONTENT_WIDTH - inner * 2
        y = self.CONTENT_TOP

        if sc.quote_text:
            available = self.CONTENT_SAFE_BOTTOM - y
            height = self.content.render_quote(
                slide, sc.quote_text,
                self.MARGIN_LEFT + inner, y, width,
                max_height=int(available) if available > 0 else 0)
            if height > 0:
                y += height + Emu(200000)
            else:
                self.warnings.append(
                    f"第 {sc.page_num} 页引用块因版面空间不足未渲染")

        if sc.code_block:
            available = self.CONTENT_SAFE_BOTTOM - y
            height = self.content.render_code_block(
                slide, sc.code_block,
                self.MARGIN_LEFT + inner, y, width,
                max_height=int(available) if available > 0 else 0)
            if height > 0:
                y += height + Emu(200000)
            else:
                self.warnings.append(
                    f"第 {sc.page_num} 页代码块因版面空间不足未渲染")

        available_height = max(0, int(self.CONTENT_SAFE_BOTTOM - y))
        self._render_bullets_with_budget(
            slide, sc, self.MARGIN_LEFT + inner, y, width, Emu(available_height))

        if not sc.bullet_points and not sc.quote_text and not sc.code_block:
            # 空内容页不再只有标题（修 H6）
            self.add_textbox(
                slide, self.MARGIN_LEFT + inner, self.CONTENT_TOP,
                width, Emu(600000),
                EMPTY_PLACEHOLDER, font_size=Pt(14),
                font_color=self.color("secondary"), italic=True)
            self.warnings.append(f"第 {sc.page_num} 页「{sc.title}」没有任何要点文字")

        if image_path:
            self._add_corner_image(slide, image_path)

    def _add_corner_image(self, slide, image_path):
        """文字页右下角配图，尺寸收敛不遮挡正文。"""
        try:
            slide.shapes.add_picture(
                str(image_path), Emu(9200000), Emu(4700000),
                Emu(2600000), Emu(1500000))
        except Exception as exc:
            print(f"    ⚠️  配图插入失败：{exc}")

    # ---- 数据页 ----
    def add_data_slide(self, sc, image_path=None, total_pages=0):
        slide = self.prs.slides.add_slide(self.blank_layout)
        self.add_background(slide)
        self.add_decorations(slide)
        self.add_slide_header(slide, sc.title)

        chart_type = self._resolve_chart_type(sc)
        has_chart = bool(chart_type and sc.table_data)

        if has_chart:
            # 有要点：左栏编号数据点 + 右侧图表；无要点：图表用全宽，
            # 不再让左侧 1/3 永久空白。
            if sc.bullet_points:
                self._render_data_points(slide, sc, Emu(4000000))
                chart_left = self.MARGIN_LEFT + Emu(4200000)
                chart_width = self.CONTENT_WIDTH - Emu(4200000)
            else:
                chart_left = self.MARGIN_LEFT
                chart_width = self.CONTENT_WIDTH
            ok = self.charts.add_chart(
                slide, chart_type, sc.table_data,
                chart_left, self.CONTENT_TOP, chart_width, Emu(4500000))
            if not ok:
                self.content.render_table(
                    slide, sc.table_data.headers or [], sc.table_data.rows,
                    chart_left, self.CONTENT_TOP,
                    chart_width, Emu(4300000), page_num=sc.page_num)
        else:
            drawn = self._render_data_points(slide, sc, Emu(0), full_width=True)
            # 没有要点也不该让这一页只剩标题：有表格就画表格，
            # 什么都没有才退到配图或占位提示（并记 warning）。
            if not drawn:
                if sc.table_data and sc.table_data.rows:
                    self.content.render_table(
                        slide, sc.table_data.headers or [], sc.table_data.rows,
                        self.MARGIN_LEFT + Emu(200000), self.CONTENT_TOP,
                        self.CONTENT_WIDTH - Emu(400000), Emu(4300000),
                        page_num=sc.page_num)
                    drawn = True
                elif image_path:
                    self._add_corner_image(slide, image_path)
                    drawn = True
            if not drawn:
                self.add_textbox(
                    slide, self.MARGIN_LEFT + Emu(200000), self.CONTENT_TOP,
                    self.CONTENT_WIDTH - Emu(400000), Emu(600000),
                    EMPTY_PLACEHOLDER, font_size=Pt(14),
                    font_color=self.color("secondary"), italic=True)
                self.warnings.append(
                    f"第 {sc.page_num} 页「{sc.title}」没有任何要点或表格数据")

        self.add_page_number(slide, sc.page_num, total_pages)

    def _render_data_points(self, slide, sc, text_width, full_width=False):
        """左侧编号数据点。返回实际渲染条数（0 = 没画）。

        只有整列都是「1. 」这类小序号时才剥前缀（编号徽章会重复）——
        「2024. 年度总结」里的年份是内容，无条件剥除等于静默丢数据。
        单条「1. 甲」保留前缀：宁要冗余不要丢数据。
        """
        points = [str(p).strip() for p in sc.bullet_points if str(p).strip()]
        if not points:
            return 0
        if _looks_ordered(points):
            points = [_strip_leading_number(p) for p in points]

        y = self.CONTENT_TOP
        width = (self.CONTENT_WIDTH - Emu(400000)) if full_width else text_width
        for index, point in enumerate(points):
            if y > Emu(5700000):
                self.warnings.append(
                    f"第 {sc.page_num} 页要点过多，仅展示前 {index} 条")
                break
            badge = slide.shapes.add_shape(
                MSO_SHAPE.ROUNDED_RECTANGLE, self.MARGIN_LEFT, y,
                Emu(342000), Emu(400000))
            badge.fill.solid()
            badge.fill.fore_color.rgb = self.color("primary")
            badge.line.fill.background()
            badge.shadow.inherit = False

            tf = badge.text_frame
            p = tf.paragraphs[0]
            p.text = str(index + 1)
            p.font.size = Pt(14)
            p.font.color.rgb = to_rgb((0xFF, 0xFF, 0xFF))
            p.font.bold = True
            p.alignment = PP_ALIGN.CENTER

            self.add_textbox(
                slide, self.MARGIN_LEFT + Emu(430000), y + Emu(57000),
                width - Emu(450000), Emu(400000),
                point, font_size=Pt(13),
                font_color=self.color("text"))
            y += Emu(480000)
        return True

    # ---- 参考文献 ----
    def add_reference_slide(self, sc, total_pages=0):
        slide = self.prs.slides.add_slide(self.blank_layout)
        self.add_background(slide)
        self.add_decorations(slide)
        self.add_slide_header(slide, sc.title)

        if sc.bullet_points:
            self.add_multiline_textbox(
                slide, self.MARGIN_LEFT + Emu(100000), Emu(1140000),
                self.CONTENT_WIDTH - Emu(200000), Emu(4900000),
                sc.bullet_points, font_size=Pt(11),
                font_color=self.color("text"), line_spacing=1.4)
        else:
            self.add_textbox(
                slide, self.MARGIN_LEFT, Emu(1140000),
                self.CONTENT_WIDTH, Emu(500000),
                EMPTY_PLACEHOLDER, font_size=Pt(12),
                font_color=self.color("secondary"), italic=True)

        self.add_page_number(slide, sc.page_num, total_pages)

    # ---- 致谢 ----
    def add_thank_slide(self, sc, image_path=None):
        """致谢页：居中大字 + 装饰色块 + 半透明配图。

        image_path 真正被消费——v2.0.0 曾接收参数却不用，
        爬到的图被静默丢弃（CHANGELOG F13 声明与代码不符）。
        """
        slide = self.prs.slides.add_slide(self.blank_layout)
        self.add_background(slide)
        self.add_decorations(slide)

        if image_path:
            self._add_thank_image(slide, image_path)

        center_top = Emu(2050000)
        center_height = Emu(3190000)
        banner = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Emu(2280000), center_top,
            Emu(9250000), center_height)
        banner.fill.solid()
        banner.fill.fore_color.rgb = self.color("primary")
        banner.line.fill.background()
        banner.shadow.inherit = False

        top_line = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Emu(3420000), center_top + Emu(342000),
            Emu(5700000), Emu(46000))
        top_line.fill.solid()
        top_line.fill.fore_color.rgb = to_rgb((0xFF, 0xFF, 0xFF))
        top_line.line.fill.background()
        top_line.shadow.inherit = False

        self.add_textbox(
            slide, Emu(2500000), center_top + Emu(450000),
            Emu(8800000), Emu(1140000),
            sc.title, font_size=Pt(32),
            font_color=to_rgb((0xFF, 0xFF, 0xFF)), bold=True,
            alignment=PP_ALIGN.CENTER)

        if sc.subtitle:
            self.add_textbox(
                slide, Emu(2500000), center_top + Emu(1700000),
                Emu(8800000), Emu(685000),
                sc.subtitle, font_size=Pt(18),
                font_color=to_rgb((0xE8, 0xEE, 0xF5)),
                alignment=PP_ALIGN.CENTER)

        bottom_line = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Emu(3420000),
            center_top + center_height - Emu(390000),
            Emu(5700000), Emu(46000))
        bottom_line.fill.solid()
        bottom_line.fill.fore_color.rgb = to_rgb((0xFF, 0xFF, 0xFF))
        bottom_line.line.fill.background()
        bottom_line.shadow.inherit = False

        footer = "  |  ".join(part for part in (
            self.meta.get("presenter") or "",
            self.meta.get("institution") or "",
            self.meta.get("date") or "") if part)
        if footer:
            self.add_textbox(
                slide, self.MARGIN_LEFT, Emu(5930000),
                self.CONTENT_WIDTH, Emu(685000),
                footer, font_size=Pt(12),
                font_color=self.color("accent"),
                alignment=PP_ALIGN.CENTER)

    # ---- 图表类型解析 ----
    def _resolve_chart_type(self, sc):
        """chart_type 留空时按数据自动推断（接进 detect_chart_type_from_table）。"""
        if sc.chart_type:
            return sc.chart_type
        if sc.table_data:
            inferred = detect_chart_type_from_table(sc.table_data, [sc.title])
            if inferred:
                print(f"    🔎 第 {sc.page_num} 页未指定图表类型，按数据推断为 {inferred}")
            return inferred
        return ""
