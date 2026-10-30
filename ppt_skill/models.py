"""PPT 内容数据结构。

字段语义在 v2.0.0 统一（原版两处矛盾：TableData.headers 从未被读取，
而 rows[0] 被当成表头，导致每张表丢掉第一行数据）：

    TableData.headers  表头文字，长度必须等于每行的列数
    TableData.rows     数据行；第一列是分类标签，其余列是数值

即原版示例中
    headers=["阶段","核心特征","关键机制","比重"]
    rows=[["经济不平等（私有制）","贫富分化","自然差异被制度化放大","45%"], ...]
现在三个数据行都会进入图表，"经济不平等（私有制）"不再被当表头吞掉。
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TableData:
    """表格数据，用于自动生成图表。"""

    headers: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)


@dataclass
class SlideContent:
    """单页幻灯片的数据结构。

    slide_type 取值：title / section / content / data / reference / thank
    chart_type  取值：pie / bar / line / ''（留空时按数据自动推断）
    """

    page_num: int
    slide_type: str
    title: str
    subtitle: str = ""
    bullet_points: List[str] = field(default_factory=list)
    image_keywords: List[str] = field(default_factory=list)
    table_data: Optional[TableData] = field(default=None)
    chart_type: str = ""
    code_block: str = ""
    quote_text: str = ""

    def is_valid_type(self):
        return self.slide_type in VALID_SLIDE_TYPES


VALID_SLIDE_TYPES = ("title", "section", "content", "data", "reference", "thank")
VALID_CHART_TYPES = ("pie", "bar", "line", "")
