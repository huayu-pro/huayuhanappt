"""底层绘图工具与装饰元素。

关键修复（原版 H1）：原 _set_bullet_color 把 a:buClr 建成 a:buChar 的子元素，
违反 OOXML 规范（CT_TextParagraphProperties 要求 buClr 是 pPr 的直接子元素，
且必须排在 buChar 之前）。结果主题色圆点永不生效，异常还被 except 吞掉。
这里按正确顺序构造：buClr 在前，buChar 在后。
"""

from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt


def to_rgb(color):
    """把 (r, g, b) 三元组或 RGBColor 统一转成 RGBColor。

    RGBColor 本身是 tuple 子类但没有 .red 属性，原版用
    color.red 取属性会 AttributeError——统一走索引访问最稳。
    """
    if isinstance(color, RGBColor):
        return color
    r, g, b = color
    return RGBColor(int(r), int(g), int(b))


def hex_to_rgb(value):
    return RGBColor(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


class Renderer:
    """共享底层绘图能力。SlideRenderer 继承它。"""

    SLIDE_WIDTH = Emu(12192000)    # 13.33 英寸，16:9
    SLIDE_HEIGHT = Emu(6858000)    # 7.5 英寸
    MARGIN_LEFT = Emu(600000)
    CONTENT_WIDTH = Emu(10992000)
    TOP_BAR_HEIGHT = Emu(137000)   # 0.15 英寸
    TITLE_BAR_TOP = Emu(170000)
    TITLE_BAR_HEIGHT = Emu(1140000)
    CONTENT_TOP = Emu(1140000)
    CONTENT_HEIGHT = Emu(4800000)
    # 内容安全下沿：页码区（top=6040000）之上留 100000 余量。
    # 任何正文元素都不得越过这条线——越线就会压住页码或画出幻灯片。
    CONTENT_SAFE_BOTTOM = Emu(5940000)

    def __init__(self, presentation, palette, palette_name, chart_colors):
        self.prs = presentation
        self.palette = palette
        self.palette_name = palette_name
        self.chart_colors = chart_colors
        self.blank_layout = self.prs.slide_layouts[6]

    # ---- 颜色便捷访问 ----
    def color(self, key):
        return to_rgb(self.palette[key])

    # ---- 背景与装饰 ----
    def add_background(self, slide):
        fill = slide.background.fill
        fill.solid()
        fill.fore_color.rgb = self.color("bg")

    def add_top_accent_bar(self, slide):
        bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Emu(0), Emu(0),
            self.SLIDE_WIDTH, self.TOP_BAR_HEIGHT)
        bar.fill.solid()
        bar.fill.fore_color.rgb = self.color("accent")
        bar.line.fill.background()
        bar.shadow.inherit = False

    def add_left_sidebar(self, slide):
        bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Emu(0), Emu(0),
            Emu(114000), self.SLIDE_HEIGHT)
        bar.fill.solid()
        bar.fill.fore_color.rgb = self.color("accent")
        bar.line.fill.background()
        bar.shadow.inherit = False

    def add_decorations(self, slide):
        self.add_top_accent_bar(slide)
        self.add_left_sidebar(slide)

    def add_title_bar_bg(self, slide):
        bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Emu(0), self.TITLE_BAR_TOP,
            self.SLIDE_WIDTH, self.TITLE_BAR_HEIGHT)
        bar.fill.solid()
        bar.fill.fore_color.rgb = self.color("light")
        bar.line.fill.background()
        bar.shadow.inherit = False

    def add_title_underline(self, slide, left=None):
        """标题下短装饰线。

        原版把 Pt(2) 当 height 传给 add_shape（期望 EMU），
        画出来是 0.02 英寸的粗线而非细线——这里显式用 Emu。
        """
        if left is None:
            left = self.MARGIN_LEFT
        line = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, left, Emu(935000),
            Emu(685000), Emu(18000))
        line.fill.solid()
        line.fill.fore_color.rgb = self.color("primary")
        line.line.fill.background()
        line.shadow.inherit = False

    def add_page_number(self, slide, page_num, total_pages):
        self.add_textbox(
            slide, Emu(9690000), Emu(6040000),
            Emu(1480000), Emu(285000),
            f"{page_num} / {total_pages}",
            font_size=Pt(9), font_color=self.color("secondary"),
            alignment=PP_ALIGN.RIGHT)

    def add_slide_header(self, slide, title):
        """内容页通用头部：浅色标题栏 + 标题 + 装饰线。"""
        self.add_title_bar_bg(slide)
        self.add_textbox(
            slide, self.MARGIN_LEFT, Emu(342000),
            self.CONTENT_WIDTH, Emu(570000),
            title, font_size=Pt(24),
            font_color=self.color("title"), bold=True)
        self.add_title_underline(slide)

    # ---- 文本 ----
    def add_textbox(self, slide, left, top, width, height, text,
                    font_size=Pt(14), font_color=None, bold=False, italic=False,
                    alignment=PP_ALIGN.LEFT, font_name="Arial"):
        if font_color is None:
            font_color = self.color("text")
        box = slide.shapes.add_textbox(left, top, width, height)
        tf = box.text_frame
        tf.word_wrap = True
        tf.auto_size = MSO_AUTO_SIZE.NONE
        tf.vertical_anchor = MSO_ANCHOR.TOP
        p = tf.paragraphs[0]
        p.text = text
        p.font.size = font_size
        p.font.color.rgb = to_rgb(font_color)
        p.font.bold = bold
        p.font.italic = italic
        p.font.name = font_name
        p.alignment = alignment
        return box

    def add_multiline_textbox(self, slide, left, top, width, height, lines,
                              font_size=Pt(14), font_color=None, bold=False,
                              alignment=PP_ALIGN.LEFT, line_spacing=1.5,
                              font_name="Arial"):
        if font_color is None:
            font_color = self.color("text")
        box = slide.shapes.add_textbox(left, top, width, height)
        tf = box.text_frame
        tf.word_wrap = True
        tf.auto_size = MSO_AUTO_SIZE.NONE
        for index, line in enumerate(lines):
            p = tf.paragraphs[0] if index == 0 else tf.add_paragraph()
            p.text = line
            p.font.size = font_size
            p.font.color.rgb = to_rgb(font_color)
            p.font.bold = bold
            p.font.name = font_name
            p.alignment = alignment
            p.space_after = Pt(font_size.pt * (line_spacing - 1))
        return box

    def add_shape(self, slide, shape_type, left, top, width, height, fill_color=None):
        shape = slide.shapes.add_shape(shape_type, left, top, width, height)
        if fill_color is not None:
            shape.fill.solid()
            shape.fill.fore_color.rgb = to_rgb(fill_color)
        shape.line.fill.background()
        shape.shadow.inherit = False
        return shape

    def insert_image(self, slide, image_path, left, top, width, height=None):
        try:
            if height is None:
                return slide.shapes.add_picture(str(image_path), left, top, width)
            return slide.shapes.add_picture(str(image_path), left, top, width, height)
        except Exception as exc:
            print(f"    ⚠️  图片插入失败：{exc}")
            return None

    # ---- 项目符号颜色（修复 H1）----
    # CT_TextParagraphProperties 的子元素有严格顺序要求（ECMA-376）：
    # lnSpc, spcBef, spcAft, buClrTx|buClr, buSzTx|..., buFontTx|buFont,
    # buNone|buAutoNum|buChar, tabLst, defRPr, extLst
    # 顺序错了 PowerPoint 会静默忽略整个 pPr 的项目符号设置。
    _PPR_ORDER = [
        "lnSpc", "spcBef", "spcAft",
        "buClrTx", "buClr", "buSzTx", "buSzPct", "buSzPts",
        "buFontTx", "buFont", "buNone", "buAutoNum", "buChar",
        "tabLst", "defRPr", "extLst",
    ]

    def set_bullet_color(self, paragraph, color):
        """把段落项目符号染成主题色，并按规范重排 pPr 子元素。

        原版有两处错：把 a:buClr 建成 a:buChar 的子元素（结构非法），
        且插入位置不受控，导致 defRPr 跑到 buChar 前面——PowerPoint
        直接忽略，主题色圆点因此从未生效。这里构造后统一按规范排序。
        同时设置 marL/indent 悬挂缩进，让折行文字与首行文字对齐
        （文本不再手写 ● 前缀，圆点完全由 buChar 提供，避免双圆点）。
        """
        try:
            rgb = to_rgb(color)
            pPr = paragraph._p.get_or_add_pPr()

            # 悬挂缩进：0.25 英寸符号位，折行与首行对齐
            pPr.set("marL", "228600")
            pPr.set("indent", "-228600")

            buClr = pPr.find(qn("a:buClr"))
            if buClr is None:
                buClr = pPr.makeelement(qn("a:buClr"), {})
                pPr.append(buClr)
            for child in list(buClr):
                buClr.remove(child)
            srgb = buClr.makeelement(qn("a:srgbClr"), {"val": str(rgb)})
            buClr.append(srgb)

            buChar = pPr.find(qn("a:buChar"))
            if buChar is None:
                buChar = pPr.makeelement(qn("a:buChar"), {"char": "●"})
                pPr.append(buChar)

            self._sort_ppr_children(pPr)
        except Exception as exc:
            print(f"    ⚠️  项目符号颜色设置失败，使用默认色：{exc}")

    def _sort_ppr_children(self, pPr):
        """按 ECMA-376 规定顺序重排 pPr 子元素（稳定排序，未知元素沉到最后）。"""
        from lxml import etree

        order = {name: index for index, name in enumerate(self._PPR_ORDER)}
        children = list(pPr)
        children.sort(key=lambda el: order.get(
            etree.QName(el).localname, len(order)))
        for child in children:
            pPr.append(child)  # append 已存在的节点等于移动到末尾
