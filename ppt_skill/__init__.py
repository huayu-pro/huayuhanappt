"""华予&Hanako PPT —— 学术全自动PPT生成器（v2.0.0 模块化版）。

公开接口：
    generate_ppt(slides, options) -> GenerationReport
    load_content(path) -> List[SlideContent]
"""

__version__ = "2.1.0"

from .errors import SkillError, ConfigError, InputError, APIError, RenderError, TimeoutError
from .models import SlideContent, TableData

__all__ = [
    "__version__",
    "SkillError", "ConfigError", "InputError", "APIError", "RenderError", "TimeoutError",
    "SlideContent", "TableData",
]
