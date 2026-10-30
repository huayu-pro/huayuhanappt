"""从自由文稿生成 PPT 页面大纲。

这是"不用改代码就能生成 PPT"的另一半：用户只粘贴文稿，
这里按学术结构拆出页面清单。AI 工作流也可以用同一份大纲做底稿，
再按需细化——两条路径产物同构，不会分叉。

设计原则：
  - 按"段 → 主题块 → 页面"三级拆分，不逐段堆页
  - 识别章节标记（一、/1. /第一部分/【】）作为 section 边界
  - 数字密集的段落升级为 data 页并尝试抽出表格
  - 保底：短文稿会把段落二次切分补齐页数；内容真的太少时
    （如只有一句话）由校验给出明确的"页数不足"提示，不编造内容凑数
"""

import re
from typing import List, Optional

from .config import LIMITS
from .errors import InputError
from .models import SlideContent, TableData

# 章节标题：一、/ 1. / 1.1 / 第一部分 / 【标题】 / 第X章
# 数字编号的坑：纯正则很难排除「3.14是圆周率」——`.` 既能当小数点
# 又能当分隔符，回溯会把它拆成编号 3 + 标题「14是圆周率」。
# 所以先用宽松正则抽候选，再在 Python 侧否决小数形态。
HEADING_CANDIDATE_RE = re.compile(
    r"^\s*(?:"
    r"第[一二三四五六七八九十百\d]+[章节部分篇]+\s*[:：]?\s*"
    r"|[一二三四五六七八九十]+\s*[、.．]\s*"
    r"|\d[\d.]*\s*[、.．:：]\s*"
    r"|【[^】]{2,30}】\s*"
    r")(.+)$"
)

# 行首「数字.数字」后直接跟文字（无分隔符、无空白）——这是句子里的小数，
# 不是章节编号。如「3.14是圆周率」「1.5 倍增长」。
# 注意「1.1 子节」这种带空白的层级编号要放过，所以要求点后数字紧贴文字。
DECIMAL_LINE_RE = re.compile(r"^\d+\.\d+\s*\S")


def match_heading(line):
    """判断一行是不是章节标题，返回 (编号, 标题) 或 None。

    小数形态（3.14 / 1.5）一律否决：它们几乎总是正文里的数值，
    误判成章节会把正文从主题块里撕出去。
    """
    stripped = line.strip()
    if DECIMAL_LINE_RE.match(stripped):
        return None

    m = HEADING_CANDIDATE_RE.match(line)
    if not m:
        return None

    title = m.group(1).strip()
    if not title:
        return None

    # 编号取「标题起点之前的全部内容」，避免贪婪匹配吃掉标题首字
    prefix = line[: m.start(1)].strip()
    if not prefix:
        return None
    return prefix, title

SENTENCE_SPLIT_RE = re.compile(r"[。；!?！？;]")


def build_outline(text: str, target_pages: int = 25) -> List[SlideContent]:
    """把文稿转成 SlideContent 列表。"""
    if not text or not text.strip():
        raise InputError("文稿是空的", "请粘贴你的论文、报告或讲稿正文")

    if len(text) > LIMITS["max_input_chars"]:
        raise InputError(
            f"文稿 {len(text)} 字，超过 {LIMITS['max_input_chars']} 字上限",
            "删减到上限以内，或分成几次生成",
        )

    min_pages = LIMITS["min_pages"]
    max_pages = LIMITS["max_pages"]
    target_pages = max(min_pages, min(max_pages, int(target_pages)))

    blocks = _split_into_blocks(text)
    title = _guess_title(text, blocks)
    if not blocks:
        raise InputError(
            "没能从文稿里解析出任何内容段落",
            "确认粘贴的是正文而不是只有标题；每段之间用空行分隔",
        )

    slides: List[SlideContent] = []
    slides.append(SlideContent(
        page_num=1, slide_type="title", title=title,
        subtitle=_guess_subtitle(blocks),
        image_keywords=_keywords_for(title),
    ))

    # 目录：章节过多时合并尾部，避免超出单页要点上限
    section_titles = [b["heading"] for b in blocks if b["heading"]]
    toc = _build_toc(section_titles)
    slides.append(SlideContent(
        page_num=2, slide_type="content", title="目录",
        bullet_points=toc,
    ))

    body_budget = target_pages - 3  # 扣掉封面、目录、致谢
    body_slides = _blocks_to_slides(blocks, body_budget)

    for slide in body_slides:
        slides.append(slide)

    slides.append(SlideContent(
        page_num=len(slides) + 1, slide_type="thank",
        title="感谢聆听", subtitle="欢迎批评指正"))

    # 重新连续编号
    for index, slide in enumerate(slides, start=1):
        slide.page_num = index

    # 短文稿兜底：内容块不足时把长段落二次切分，补齐到最小页数。
    # 没有这一步，build_outline 与 validate_content 的页数契约互相矛盾——
    # 短文稿必然生成失败，而用户什么都没做错。
    if len(slides) < min_pages:
        slides = _pad_to_minimum(slides, min_pages)
        for index, slide in enumerate(slides, start=1):
            slide.page_num = index

    return slides


def _build_toc(section_titles):
    """目录条目，超过单页上限时把尾部合并成一条。

    没有识别到章节时也要给目录几行——空的 bullet_points 会让
    正文页校验报"没有任何内容元素"。
    """
    limit = LIMITS["max_bullets_per_slide"]
    if not section_titles:
        return ["一、研究背景与问题", "二、核心内容分析", "三、结论与讨论"]
    if len(section_titles) <= limit:
        return [f"{i + 1}. {t}" for i, t in enumerate(section_titles)]
    kept = section_titles[: limit - 1]
    rest = len(section_titles) - (limit - 1)
    return ([f"{i + 1}. {t}" for i, t in enumerate(kept)]
            + [f"……另有 {rest} 个章节"])


def _pad_to_minimum(slides, min_pages):
    """把内容页二次切分，直到总页数达到下限。

    短文稿（一两段）本来只该出三四页，但校验要求至少 8 页——
    没有这一步，用户什么都没做错却必然生成失败。这里按要点对半拆，
    拆到只剩一条要点还不够，就把该要点的长句再切成两页。
    """
    result = list(slides)
    guard = 0
    while len(result) < min_pages and guard < 60:
        guard += 1
        # 目录页不参与拆分——把它拆成「目录（续）」很难看，
        # 要拆的是真正承载文稿内容的正文页。
        candidates = [s for s in result
                      if s.slide_type == "content"
                      and s.title != "目录"
                      and not s.title.startswith("目录（续）")
                      and s.bullet_points]
        if candidates:
            target = max(candidates, key=lambda s: len(s.bullet_points))
            index = result.index(target)
            if len(target.bullet_points) >= 2:
                half = len(target.bullet_points) // 2
                first_half = target.bullet_points[:half]
                second_half = target.bullet_points[half:]
                if first_half and second_half:
                    result[index] = SlideContent(
                        page_num=0, slide_type="content",
                        title=target.title, bullet_points=first_half,
                        image_keywords=target.image_keywords,
                        quote_text=target.quote_text,
                        code_block=target.code_block,
                        table_data=target.table_data,
                        chart_type=target.chart_type)
                    result.insert(index + 1, SlideContent(
                        page_num=0, slide_type="content",
                        title=f"{target.title}（续）", bullet_points=second_half))
                    continue

        # 要点拆不动了：把正文页里最长的要点按句子切成两页。
        # 短文稿可能每条要点都不到 40 字，这时按「前半句/后半句」硬切；
        # 12 字阈值恰好卡住的（全部要点恰 ≤12 字）退到 ≥4 字硬切——
        # 兜底不能在最需要它的极短文稿上失效。
        splittable = [s for s in result
                      if s.slide_type == "content"
                      and s.title != "目录"
                      and not s.title.startswith("目录（续）")
                      and s.bullet_points]
        if not splittable:
            break
        target = max(splittable,
                     key=lambda s: max(len(b) for b in s.bullet_points))
        index = result.index(target)
        longest = max(target.bullet_points, key=len)
        sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(longest)
                     if s.strip()]
        replaced = [b for b in target.bullet_points if b != longest]
        if len(sentences) >= 2:
            mid = len(sentences) // 2
            first_page = replaced + ["，".join(sentences[:mid]) + "。"]
            second_page = ["，".join(sentences[mid:]) + "。"]
        elif len(longest) >= 4:
            mid = max(1, len(longest) // 2)
            first_page = replaced + [longest[:mid]]
            second_page = [longest[mid:]]
        else:
            break
        result[index] = SlideContent(
            page_num=0, slide_type="content",
            title=target.title, bullet_points=first_page)
        result.insert(index + 1, SlideContent(
            page_num=0, slide_type="content",
            title=f"{target.title}（续）", bullet_points=second_page))
    return result


# ---- 文本切分 ----
def _split_paragraphs(text: str) -> List[str]:
    paragraphs = []
    for chunk in re.split(r"\n\s*\n|\r\n\s*\r\n", text):
        lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
        if lines:
            paragraphs.append("\n".join(lines))
    return paragraphs


def _split_into_blocks(text: str) -> List[dict]:
    """按章节标题把文稿切成主题块。没有标题时按长度聚合。"""
    paragraphs = _split_paragraphs(text)

    def heading_of(para):
        """单行段落才可能是章节标题；返回标题文字或 None。"""
        lines = para.split("\n")
        if len(lines) != 1:
            return None
        hit = match_heading(lines[0])
        if not hit or not hit[1]:
            return None
        return hit[1][:40]

    # 摘掉文档标题：第一段很短（像题目）且第二段是章节标题时，
    # 第一段就是论文题目，不该变成一页内容。
    if len(paragraphs) >= 2:
        first = paragraphs[0]
        if len(first) <= 40 and heading_of(paragraphs[1]):
            paragraphs = paragraphs[1:]

    blocks = []
    current = {"heading": None, "paras": []}

    for para in paragraphs:
        heading = heading_of(para)
        if heading:
            if current["paras"]:
                blocks.append(current)
            current = {"heading": heading, "paras": []}
        else:
            current["paras"].append(para)

    if current["paras"] or current["heading"]:
        blocks.append(current)

    # 没有识别到章节：按段落聚合成 3-6 个块
    if not any(b["heading"] for b in blocks):
        merged = []
        group, group_len = [], 0
        limit = max(200, sum(len(p) for b in blocks for p in b["paras"]) // 4)
        for block in blocks:
            for para in block["paras"]:
                group.append(para)
                group_len += len(para)
                if group_len >= limit:
                    merged.append({"heading": None, "paras": group})
                    group, group_len = [], 0
        if group:
            merged.append({"heading": None, "paras": group})
        if merged:
            blocks = merged

    return [b for b in blocks if b["paras"]]


def _blocks_to_slides(blocks: List[dict], budget: int) -> List[SlideContent]:
    """把主题块转成正文页，控制总页数在预算内。"""
    slides = []
    per_block = max(1, budget // max(1, len(blocks)))

    for block in blocks:
        if block["heading"]:
            slides.append(SlideContent(
                page_num=0, slide_type="section",
                title=block["heading"],
                subtitle=_first_sentence(block["paras"]),
                image_keywords=_keywords_for(block["heading"])))

        paras = block["paras"]
        chunks = _chunk_paragraphs(paras, per_block)
        for chunk in chunks:
            slides.append(_paragraphs_to_slide(chunk, block["heading"]))

    # 超出预算时合并尾部内容页
    while len(slides) > budget and len(slides) > 2:
        slides.pop()

    return slides


def _paragraphs_to_slide(paras: List[str], heading) -> SlideContent:
    text = "\n".join(paras)
    title = _slide_title(paras, heading)
    bullets = _to_bullets(paras)

    table = _try_extract_table(paras)
    if table:
        return SlideContent(
            page_num=0, slide_type="data", title=title,
            bullet_points=bullets[:4], table_data=table,
            chart_type="", image_keywords=_keywords_for(title))

    quote = _try_extract_quote(paras)
    return SlideContent(
        page_num=0, slide_type="content", title=title,
        bullet_points=bullets, quote_text=quote,
        image_keywords=_keywords_for(title))


def _chunk_paragraphs(paras: List[str], per_block: int) -> List[List[str]]:
    """把一个主题块的段落切成若干页，每页 1-3 段。"""
    chunks = []
    current = []
    for para in paras:
        current.append(para)
        if len(current) >= per_block:
            chunks.append(current)
            current = []
    if current:
        if chunks and len(current) == 1 and len(current[0]) < 60:
            chunks[-1].extend(current)
        else:
            chunks.append(current)
    return chunks or [[]]


# ---- 内容抽取 ----
def _to_bullets(paras: List[str], limit: int = 6) -> List[str]:
    bullets = []
    for para in paras:
        sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(para) if s.strip()]
        if not sentences:
            sentences = [para.strip()]
        for sentence in sentences:
            sentence = sentence.strip("，,、。 ")
            if len(sentence) < 4:
                continue
            if len(sentence) > 60:
                sentence = sentence[:57] + "…"
            bullets.append(sentence)
            if len(bullets) >= limit:
                return bullets
    return bullets


def _slide_title(paras: List[str], heading) -> str:
    """取本页第一句作标题，太长时截断。"""
    first = paras[0].split("\n")[0].strip() if paras else ""
    sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(first) if s.strip()]
    candidate = sentences[0] if sentences else first
    if not candidate:
        candidate = heading or "本节要点"
    if len(candidate) > 24:
        candidate = candidate[:22] + "…"
    return candidate


def _first_sentence(paras: List[str]) -> str:
    if not paras:
        return ""
    text = " ".join(paras)[:200]
    sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]
    return (sentences[0][:50] + "…") if sentences and len(sentences[0]) > 50 else (sentences[0] if sentences else "")


def _try_extract_quote(paras: List[str]) -> str:
    """段中出现引号包裹的短句时，提取为引用块。"""
    for para in paras:
        for match in re.finditer(r"[“\"『「]([^”\"』」]{8,60})[”\"』」]", para):
            return match.group(1)
    return ""


def _try_extract_table(paras: List[str]):
    """尝试从文本里抽出「标签 + 数值」表格。

    认两种形态：
      1. 整行一个：    数据整合能力 45%
      2. 一句里多个：  数据整合能力 45%，流程再造能力 35%
    至少凑够 3 行才认为是数据，避免把普通句子误当表格。
    """
    rows = []
    seen = set()
    for para in paras:
        # 形态 2：按逗号/分号切开再逐段匹配
        segments = re.split(r"[，,；;。]", para)
        for segment in segments:
            match = re.match(
                r"^\s*([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9\s]{1,16}?)"
                r"(?:占|为|是|达|约|达到)?\s*(\d+(?:\.\d+)?)\s*([%％])\s*$",
                segment.strip())
            if not match:
                continue
            label = match.group(1).strip()
            if label in seen or len(label) < 2:
                continue
            seen.add(label)
            rows.append([label, match.group(2)])

    if len(rows) >= 3:
        return TableData(headers=["项目", "占比"], rows=rows)
    return None


def _guess_title(text: str, blocks: Optional[List[dict]] = None) -> str:
    """取题目：优先第一个非章节标题的短行，其次第一个章节标题。

    要跳过章节标题行（「一、绪论」是结构不是题目）和整段正文
    （单段文稿没有换行，第一行就是全部内容，取它的第一句话）。

    只认**第一个非空段**是题目行：它必须不是章节标题、长度像题目
    （≤40 字）。第一个非空段若是章节标题或长正文，说明这篇文稿
    没有独立题目行，直接退到第一个章节标题——章节正文短得也像题目，
    往后找必然认错。
    """
    paragraphs = _split_paragraphs(text)
    for para in paragraphs[:1]:
        first_line = para.split("\n")[0].strip().strip("#").strip()
        if not first_line or match_heading(first_line):
            break
        line = re.sub(r"^(论文|报告|讲稿|文章|题目|标题)[:：]\s*", "", first_line)
        if not line:
            break
        if len(line) <= 40:
            return line
        # 单段长文稿：第一行就是全部正文，取它的第一句话当题目
        sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(line)
                     if s.strip()]
        if sentences and len(sentences[0]) <= 40:
            return sentences[0]
        break

    # 没有独立题目行：退到第一个章节标题
    for block in (blocks or []):
        if block.get("heading"):
            return block["heading"][:40]
    return "学术汇报"


def _guess_subtitle(blocks: List[dict]) -> str:
    for block in blocks:
        sub = _first_sentence(block["paras"])
        if sub:
            return sub[:40]
    return ""


def _keywords_for(text: str) -> List[str]:
    """从标题生成配图关键词：去停用词后取前两个实词。"""
    if not text:
        return []
    stop = {"的", "与", "及", "和", "在", "对", "从", "到", "是", "了", "研究",
            "分析", "探讨", "基于", "一种", "问题", "方法"}
    words = re.findall(r"[\u4e00-\u9fff]{2,4}", text)
    picked = [w for w in words if w not in stop][:2]
    return picked
