"""错误五分类与固定退出码。

每类错误都带「原因 + 下一步该做什么」，避免模糊报错。
退出码语义（references/troubleshooting.md 的对照表与此处一一对应）：

    0  成功
    10 配置类错误 CONFIG   —— 密钥缺失/无效、主题名拼错、输出目录不可写、
                                缺少 python-pptx/requests 依赖
    11 输入类错误 INPUT   —— 内容文件缺失/格式错、页数越界、页码重复
    12 接口类错误 API     —— 图片接口全部失败、被限流、密钥被拒
    13 渲染类错误 RENDER  —— python-pptx 生成或保存失败
    14 超时类错误 TIMEOUT —— 整体生成超过时限
"""


class SkillError(Exception):
    """所有技能错误的基类。子类必须给出 exit_code 与 remedy（下一步操作）。"""

    exit_code = 1
    category = "UNKNOWN"

    def __init__(self, message, remedy=""):
        super().__init__(message)
        self.message = message
        self.remedy = remedy

    def render(self):
        """渲染成用户可读的两行：原因 + 下一步。"""
        lines = [f"[{self.category}] {self.message}"]
        if self.remedy:
            lines.append(f"  → 下一步：{self.remedy}")
        return "\n".join(lines)


class ConfigError(SkillError):
    exit_code = 10
    category = "CONFIG"


class InputError(SkillError):
    exit_code = 11
    category = "INPUT"


class APIError(SkillError):
    exit_code = 12
    category = "API"


class RenderError(SkillError):
    exit_code = 13
    category = "RENDER"


class TimeoutError(SkillError):
    exit_code = 14
    category = "TIMEOUT"
