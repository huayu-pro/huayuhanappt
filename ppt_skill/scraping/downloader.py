"""图片下载与批量爬取编排。

相对原版的改进：
  - 下载有指数退避，且非 200 也退避（原版非 200 立即重试，等于打空枪）
  - Content-Length 超限直接拒收，避免下到一个巨型文件撑爆磁盘
  - 流式响应确保关闭
  - 每页返回 ScrapeResult（图片 + 失败明细），不再把失败信息 print 完就丢
"""

import time
from pathlib import Path
from typing import Optional

from .base import ImageFailure, ScrapeResult
from .providers import build_providers

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


class ImageScraper:
    """多源学术配图爬取器。"""

    def __init__(self, config, session_factory=None):
        self.config = config
        self.session = (session_factory or _default_session)()
        self.providers = build_providers(config, self.session)
        self.max_bytes = config_limits().get("max_download_bytes", 20 * 1024 * 1024)
        self.stats = {"searched": 0, "downloaded": 0, "failed": 0, "skipped_pages": 0}

    # ---- 单页爬取 ----
    def scrape_for_page(self, slide, image_dir: Path) -> ScrapeResult:
        result = ScrapeResult()
        if not slide.image_keywords:
            self.stats["skipped_pages"] += 1
            return result

        max_per_page = config_limits().get("max_images_per_slide", 2)
        # 页内自增序号做文件名后缀：同页重复关键词、或两个关键词
        # 截断后同前缀时，后一张不再覆盖前一张（stats 也不再虚报）
        seq = 0
        for keyword in slide.image_keywords:
            if len(result.images) >= max_per_page:
                break
            outcome = self._search_keyword(keyword)
            if outcome.failure:
                result.failures.append(ImageFailure(
                    page_num=slide.page_num, keyword=keyword,
                    reason=outcome.failure,
                    hint="可换一个更具体的配图关键词，或在 Web 界面关闭自动配图",
                ))
                continue
            for url in outcome.urls:
                if len(result.images) >= max_per_page:
                    break
                path = self._download(url, image_dir, slide.page_num,
                                      keyword, seq)
                seq += 1
                if path:
                    result.images.append(path)
            time.sleep(0.3)
        return result

    def _search_keyword(self, keyword: str):
        """按优先级尝试各来源，返回第一个有结果的。"""
        from .base import ScrapeResult as _R
        outcome = _R()
        if not self.providers:
            outcome.failure = "没有可用的图片来源（检查网络或密钥配置）"
            return outcome
        for provider in self.providers:
            self.stats["searched"] += 1
            urls, reason = provider.search(keyword)
            if urls:
                outcome.urls = urls
                outcome.provider = provider.name
                return outcome
            if reason and "未配置" not in reason:
                outcome.last_reason = reason
        outcome.failure = (getattr(outcome, "last_reason", None)
                           or "所有图片来源都没有返回结果")
        return outcome

    # ---- 下载 ----
    def _download(self, url: str, image_dir: Path, page_num: int, keyword: str,
                  index: int = 0) -> Optional[Path]:
        from ..text_utils import sanitize_filename

        # 同页同关键词可能被请求多次，用序号区分，避免后一张覆盖前一张
        filename = f"p{page_num:02d}_{sanitize_filename(keyword, 20)}_{index}.jpg"
        save_path = image_dir / filename
        delays = [1, 2, 4]

        for attempt in range(3):
            try:
                resp = self.session.get(url, timeout=30, stream=True)
            except Exception:
                self.stats["failed"] += 1
                time.sleep(delays[min(attempt, len(delays) - 1)])
                continue

            if resp.status_code != 200:
                # stream=True 打开的连接必须关闭，否则重试期间连接泄漏
                try:
                    resp.close()
                except Exception:
                    pass
                self.stats["failed"] += 1
                time.sleep(delays[min(attempt, len(delays) - 1)])
                continue

            declared = resp.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > self.max_bytes:
                # 超大图直接拒收，不落盘
                try:
                    resp.close()
                except Exception:
                    pass
                self.stats["failed"] += 1
                return None

            try:
                with open(save_path, "wb") as handle:
                    written = 0
                    for chunk in resp.iter_content(chunk_size=8192):
                        written += len(chunk)
                        if written > self.max_bytes:
                            handle.close()
                            save_path.unlink(missing_ok=True)
                            self.stats["failed"] += 1
                            return None
                        handle.write(chunk)
            except Exception:
                save_path.unlink(missing_ok=True)
                self.stats["failed"] += 1
                time.sleep(delays[min(attempt, len(delays) - 1)])
                continue
            finally:
                try:
                    resp.close()
                except Exception:
                    pass

            if self._is_valid_image(save_path):
                self.stats["downloaded"] += 1
                return save_path
            save_path.unlink(missing_ok=True)
            self.stats["failed"] += 1

        return None

    def _is_valid_image(self, path: Path) -> bool:
        """校验下载到的是真图片。Pillow 缺失时退化为大小检查。"""
        try:
            from PIL import Image
        except ImportError:
            return path.stat().st_size > 2048
        try:
            with Image.open(path) as img:
                img.verify()
            return path.stat().st_size > 2048
        except Exception:
            return False

    # ---- 批量 ----
    def scrape_all(self, slides, image_dir: Path) -> ScrapeResult:
        total = ScrapeResult()
        for slide in slides:
            # 无关键词页的 skipped_pages 计数在 scrape_for_page 内完成，
            # 这里不再重复累计（会翻倍）
            page_result = self.scrape_for_page(slide, image_dir)
            total.merge(page_result)
        return total


def config_limits():
    from ..config import LIMITS
    return LIMITS


def _default_session():
    import requests
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    return session
