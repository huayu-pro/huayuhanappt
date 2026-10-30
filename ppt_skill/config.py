"""配置加载：.env 解析、密钥三态、主题与输出设置。

不依赖 python-dotenv（用户环境未必装了），自己解析 .env：
  KEY=VALUE          常规
   export KEY=VALUE  带 export 前缀
   # comment          注释与空行跳过
   值两侧引号          去除

密钥三态是 T 维「配置流程友好」的核心：
    MISSING  未配置 —— 不发请求，直接跳过该接口
    SET      已配置 —— 正常请求
    INVALID  已配置但被服务端拒绝（401/403）—— 汇总报告，提醒更换
"""

import os
import re
from pathlib import Path

from .errors import ConfigError

# 每个接口的密钥变量名。留空列表表示该接口无需密钥。
PROVIDER_KEYS = {
    "pexels": ["PEXELS_API_KEY"],
    "baidu": ["BAIDU_API_KEY", "BAIDU_SECRET_KEY"],
    "unsplash": ["UNSPLASH_ACCESS_KEY"],
    "pixabay": ["PIXABAY_API_KEY"],
    "bing": [],
    "wikimedia": [],
}

# 占位符特征：原版默认值 YOUR_PEXELS_API_KEY_HERE 永不为假，
# 导致未配置时仍发起无效请求。这里把这些默认值一律视为未配置。
# 用整串集合 + 严格尾缀匹配，不用宽松前缀——「sample-project-key」
# 这种真实测试密钥不该被误判成占位符而静默降级。
PLACEHOLDER_EXACT = {
    "", "example", "sample", "placeholder", "changeme", "todo", "none", "null",
    "xxx", "xxxx", "xxxxx", "your_key", "your_api_key", "your_api_key_here",
    "your_pexels_api_key", "your_pexels_api_key_here", "your_baidu_api_key",
    "your_baidu_secret_key", "your_unsplash_access_key",
    "your_pixabay_api_key", "在这里输入密钥", "请填写密钥", "替换成你的密钥",
}
PLACEHOLDER_RE = re.compile(
    r"^(your[_-].*(?:key|api|here|id)|placeholder.*|xxx+|<[^>]+>)$", re.IGNORECASE
)

# 配图来源的尝试顺序。定义为 config 而不是 scraping.providers，
# 因为 providers 要 import config（读密钥），反过来会成环。
# 免密钥的排在最前：新手一个密钥都没配时也能出图。
IMAGE_PROVIDER_ORDER = [
    "bing", "pexels", "baidu", "unsplash", "wikimedia", "pixabay",
]

MORANDI_PALETTES = {
    "morandi_blue": {
        "display": "莫兰迪蓝 — 理性专业",
        "scene": "社科、政管、法学、理工",
        "primary": (0x8B, 0xA7, 0xC7), "secondary": (0xB8, 0xC9, 0xD6),
        "accent": (0x6B, 0x8F, 0xA3), "bg": (0xF5, 0xF7, 0xFA),
        "text": (0x3D, 0x4A, 0x55), "title": (0x2C, 0x3E, 0x4F),
        "light": (0xE2, 0xEB, 0xF3), "lighter": (0xEE, 0xF3, 0xF8),
    },
    "morandi_green": {
        "display": "莫兰迪绿 — 温和自然",
        "scene": "环境、生物、生态、农学",
        "primary": (0x9B, 0xB8, 0xA8), "secondary": (0xC4, 0xD4, 0xC8),
        "accent": (0x7A, 0x9E, 0x8A), "bg": (0xF4, 0xF8, 0xF5),
        "text": (0x3D, 0x4E, 0x44), "title": (0x2C, 0x40, 0x34),
        "light": (0xDE, 0xEC, 0xE2), "lighter": (0xEB, 0xF3, 0xEE),
    },
    "morandi_clay": {
        "display": "莫兰迪陶土 — 温润知性",
        "scene": "人文、历史、哲学、文学",
        "primary": (0xC4, 0xA8, 0x82), "secondary": (0xD6, 0xC4, 0xB0),
        "accent": (0xB8, 0x92, 0x6E), "bg": (0xFA, 0xF6, 0xF0),
        "text": (0x4E, 0x45, 0x3D), "title": (0x40, 0x35, 0x2C),
        "light": (0xF0, 0xE8, 0xDC), "lighter": (0xF6, 0xF0, 0xE8),
    },
    "morandi_mauve": {
        "display": "莫兰迪灰紫 — 典雅沉静",
        "scene": "艺术、设计、传媒",
        "primary": (0xB8, 0xA9, 0xC4), "secondary": (0xD0, 0xC6, 0xD6),
        "accent": (0x9E, 0x8D, 0xB0), "bg": (0xF7, 0xF5, 0xFA),
        "text": (0x44, 0x3D, 0x4E), "title": (0x34, 0x2C, 0x40),
        "light": (0xE8, 0xE2, 0xF0), "lighter": (0xF0, 0xEC, 0xF5),
    },
    "morandi_gray": {
        "display": "莫兰迪灰 — 极致简约",
        "scene": "数学、计算机、技术",
        "primary": (0xB8, 0xB8, 0xB8), "secondary": (0xD4, 0xD4, 0xD4),
        "accent": (0x9A, 0x9A, 0x9A), "bg": (0xF8, 0xF8, 0xF8),
        "text": (0x4A, 0x4A, 0x4A), "title": (0x33, 0x33, 0x33),
        "light": (0xE8, 0xE8, 0xE8), "lighter": (0xF0, 0xF0, 0xF0),
    },
    "classic_green": {
        "display": "商务经典绿 — 正式专业",
        "scene": "商务汇报、正式答辩",
        "primary": (0x05, 0x96, 0x69), "secondary": (0x10, 0xB9, 0x81),
        "accent": (0x04, 0x78, 0x57), "bg": (0xFF, 0xFF, 0xFF),
        "text": (0x4B, 0x55, 0x63), "title": (0x1F, 0x29, 0x37),
        "light": (0xEC, 0xFD, 0xF5), "lighter": (0xF0, 0xFD, 0xF4),
    },
}

# 图表配色（十六进制字符串，rendering/charts.py 转 RGBColor）
CHART_COLORS = {
    "morandi_blue":  ["8BA7C7", "6B8FA3", "B8C9D6", "A3B8CC", "7B9BB5", "9BB3C9"],
    "morandi_green": ["9BB8A8", "7A9E8A", "C4D4C8", "A8C0B4", "8DAE9A", "B3C8BA"],
    "morandi_clay":  ["C4A882", "B8926E", "D6C4B0", "CDB69C", "BFA080", "D0BDA6"],
    "morandi_mauve": ["B8A9C4", "9E8DB0", "D0C6D6", "C4B8CE", "AD9DBD", "CBBED6"],
    "morandi_gray":  ["B8B8B8", "9A9A9A", "D4D4D4", "C6C6C6", "A8A8A8", "CCCCCC"],
    "classic_green": ["059669", "10B981", "34D399", "6EE7B7", "047857", "065F46"],
}

# 能力边界（SKILL.md 与 Web UI 都以此为准，避免用户预期偏差）
LIMITS = {
    "min_pages": 8,
    "max_pages": 40,
    "recommended_pages": (25, 30),
    "max_input_chars": 200000,
    "max_bullets_per_slide": 8,
    "max_images_per_slide": 2,
    "max_download_bytes": 20 * 1024 * 1024,
}


def load_dotenv(path):
    """读取 .env 到 dict。文件不存在时返回空 dict（不报错，交由密钥三态提示）。

    几个容易踩的坑在这里处理掉：
      - utf-8-sig：Windows 记事本另存的 .env 带 BOM，用 utf-8 读会让
        第一个键名变成 '\ufeffPEXELS_API_KEY'，密钥永远读不到
      - 行内注释：`KEY=abc  # 备注` 里的 `# 备注` 要剥掉，
        否则整个字符串会被当成密钥发给接口
      - `export<TAB>KEY=v`：只按空格剥 export 前缀会把 tab 留在键名里
    """
    result = {}
    p = Path(path)
    if not p.is_file():
        return result
    try:
        text = p.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return result
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export"):
            line = line[len("export"):].lstrip(" \t")
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = _strip_inline_comment(value.strip())
        if value[:1] in ('"', "'") and len(value) >= 2 and value[-1] != value[0]:
            print(f"  ⚠️  .env 中 {key} 的引号未闭合，值按原样读取")
        value = value.strip().strip('"').strip("'")
        if key:
            result[key] = value
    return result


def _strip_inline_comment(value):
    """剥掉未加引号值尾部的行内注释。

    引号包裹的值整串保留（`KEY="a # b"` 里的 # 是内容），
    未加引号的值遇到 ' #' 或 '\\t#' 即截断。
    """
    if value[:1] in ('"', "'"):
        quote = value[0]
        end = value.find(quote, 1)
        if end != -1:
            return value[: end + 1]
        return value
    for marker in (" #", "\t#"):
        pos = value.find(marker)
        if pos != -1:
            return value[:pos]
    return value


def is_placeholder(value):
    """判断密钥值是否是占位符（未真正填写）。"""
    if value is None:
        return True
    v = str(value).strip()
    if not v:
        return True
    if v.lower() in PLACEHOLDER_EXACT:
        return True
    return bool(PLACEHOLDER_RE.match(v))


class KeyState:
    """单个接口的密钥状态。

    status: 'missing' 未配置 / 'set' 已配置 / 'invalid' 被服务端拒绝
    """

    def __init__(self, provider, variables):
        self.provider = provider
        self.variables = variables
        self.status = "missing"
        self.reject_reason = ""

    def as_dict(self):
        return {
            "provider": self.provider,
            "variables": list(self.variables),
            "status": self.status,
            "reject_reason": self.reject_reason,
        }


class Config:
    """一次生成任务的完整配置。"""

    def __init__(self, env_path=None, load_env_file=True):
        self.env_values = {}
        if load_env_file:
            self.env_values = load_dotenv(env_path or ".env")
        # 爬取阶段的失败明细，由 _scrape_images 写入、main 读取后汇总报告
        self.last_image_failures = []
        self.theme = "morandi_blue"
        self.presenter = ""
        self.institution = ""
        self.date = ""
        self.output_dir = Path("学术PPT输出")
        self.filename = "学术汇报.pptx"
        self.skip_images = False
        self.clean = False
        # 与 scraping.providers.PROVIDER_ORDER 同一份顺序（此处为唯一定义，
        # providers 反向引用），否则 available_providers() 打印的来源顺序
        # 会和实际尝试顺序不符。
        self.image_providers = list(IMAGE_PROVIDER_ORDER)
        self.key_states = {}
        self._resolve_keys()

    # ---- 密钥 ----
    def _get_secret(self, var):
        """环境变量优先，其次 .env。占位符一律返回空串。

        环境变量为空串不算"设置了"——shell 里 `export KEY=` 很常见，
        不能让它压过 .env 里的真值。
        """
        value = os.environ.get(var)
        if value is None or not value.strip():
            value = self.env_values.get(var)
        if is_placeholder(value):
            return ""
        return value.strip()

    def _resolve_keys(self):
        for provider, variables in PROVIDER_KEYS.items():
            state = KeyState(provider, variables)
            if not variables:
                state.status = "set"  # 免密钥接口
            elif all(self._get_secret(v) for v in variables):
                state.status = "set"
            self.key_states[provider] = state

    def secret(self, var):
        return self._get_secret(var)

    def available_providers(self):
        """可参与本次爬取的接口：免密钥的、以及密钥已配好的。

        missing 状态的接口不在此列——它们会在 provider 内部直接跳过，
        列出来只会让日志出现无意义的"未配置"噪音。
        """
        return [p for p in self.image_providers
                if self.key_states[p].status == "set"]

    def mark_key_invalid(self, provider, reason):
        state = self.key_states.get(provider)
        if state and state.status != "invalid":
            state.status = "invalid"
            state.reject_reason = reason

    # ---- 主题 ----
    def set_theme(self, name):
        if name not in MORANDI_PALETTES:
            available = "、".join(sorted(MORANDI_PALETTES))
            raise ConfigError(
                f"主题名不存在：{name!r}",
                f"可用主题有：{available}；用 --list-themes 查看带说明的列表",
            )
        self.theme = name
        return MORANDI_PALETTES[name]

    @property
    def palette(self):
        return MORANDI_PALETTES[self.theme]

    @property
    def chart_colors(self):
        return CHART_COLORS[self.theme]

    # ---- 输出 ----
    def resolve_output(self):
        """把输出目录与文件名收敛成绝对路径，并做早期校验。

        原版的坑：文件名没走 sanitize，含 '/' 时要在 30 页全部渲染完后
        才在 prs.save() 崩溃，全部工作丢失。这里启动期就拦。
        """
        from .text_utils import sanitize_filename

        base = Path(self.output_dir).expanduser()
        if not base.is_absolute():
            base = Path.cwd() / base
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ConfigError(
                f"输出目录不可创建：{base}（{exc}）",
                "换一个可写目录，或用 --output 指定其他路径",
            )
        if not os.access(base, os.W_OK):
            raise ConfigError(
                f"输出目录不可写：{base}",
                "检查目录权限，或用 --output 指定其他路径",
            )

        raw_name = self.filename or "学术汇报.pptx"
        # 先拆扩展名再清理：对「标题.pptx」整体清理时，尾部标点
        # 被后缀隔开剥不掉（「题目）.pptx」→「题目）.pptx」）
        stem, dot, ext = raw_name.rpartition(".")
        if dot and ext.lower() == "pptx":
            safe_name = sanitize_filename(stem) + ".pptx"
        else:
            safe_name = sanitize_filename(raw_name)
            if not safe_name.lower().endswith(".pptx"):
                safe_name += ".pptx"
        if safe_name != raw_name:
            # 不静默改写：告诉用户改成了什么，避免产物名出乎意料
            print(f"  ⚠️  文件名含非法字符，已改为：{safe_name}")
        return base / safe_name
