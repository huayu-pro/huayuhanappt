"""配图爬取子系统。"""

from .base import ScrapeResult, ImageFailure
from .providers import PROVIDER_ORDER, build_providers
from .downloader import ImageScraper

__all__ = [
    "ScrapeResult", "ImageFailure",
    "PROVIDER_ORDER", "build_providers",
    "ImageScraper",
]
