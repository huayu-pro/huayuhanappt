#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""华予&Hanako PPT 生成器入口。

推荐新手用网页界面：python start_ui.py
本文件保留命令行用法，便于脚本化批量生成。

完整参数见 python huayu_hanako_ppt.py --help
"""

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE_ROOT))

# 导入期依赖检查：缺依赖时给中文提示和安装命令，
# 而不是甩一个 ImportError traceback 让用户自己猜。
REQUIRED = [
    ("pptx", "python-pptx"),
    ("requests", "requests"),
]
OPTIONAL = [
    ("PIL", "Pillow"),
]


def _check_dependencies():
    missing = [(module, package) for module, package in REQUIRED
               if not _importable(module)]
    if missing:
        names = "、".join(package for _, package in missing)
        print(f"""
❌ 缺少必要的依赖：{names}

   请先安装：

       pip install python-pptx requests Pillow

   国内网络慢的话用镜像源：

       pip install python-pptx requests Pillow \\
           -i https://pypi.tuna.tsinghua.edu.cn/simple

   装好后重新运行本脚本。
""")
        return False
    return True


def _importable(module_name):
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


def _warn_optional():
    missing = [package for module, package in OPTIONAL if not _importable(module)]
    if missing:
        print(f"⚠️  未安装 {'、'.join(missing)}：将跳过图片完整性校验"
              f"（下载到损坏图片时无法识别）。")
        print(f"    建议安装：pip install {' '.join(missing)}\n")


if __name__ == "__main__":
    if not _check_dependencies():
        sys.exit(10)
    _warn_optional()

    from ppt_skill.cli import run
    sys.exit(run())
