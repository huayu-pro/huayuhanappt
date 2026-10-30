"""爬取结果的数据结构。

原版 scrape_for_page 只返回 List[Path]，失败信息全部 print 完就丢，
上层拿不到"哪些页没图、为什么没图"。这里改成带失败明细的结果对象，
pipeline 结束时汇总报告——这是 R 维「异常给明确反馈，不静默失败」的落点。

ScrapeResult 同时承担两个角色：
  - 面向 pipeline 的 images / failures（最终交付用）
  - 面向 provider 搜索过程的 urls / failure / provider（内部传递用）
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class ImageFailure:
    """一次配图失败的记录。"""

    page_num: int
    keyword: str
    reason: str          # 人类可读的原因
    hint: str = ""       # 下一步建议

    def as_dict(self):
        return {
            "page_num": self.page_num,
            "keyword": self.keyword,
            "reason": self.reason,
            "hint": self.hint,
        }


@dataclass
class ScrapeResult:
    """爬取结果。"""

    images: List[Path] = field(default_factory=list)
    failures: List[ImageFailure] = field(default_factory=list)
    urls: List[str] = field(default_factory=list)
    failure: Optional[str] = None
    provider: Optional[str] = None
    last_reason: Optional[str] = None

    def merge(self, other):
        self.images.extend(other.images)
        self.failures.extend(other.failures)
        return self

    def as_dict(self):
        return {
            "images": [str(p) for p in self.images],
            "failures": [f.as_dict() for f in self.failures],
        }
