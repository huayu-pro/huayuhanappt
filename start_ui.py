#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""启动华予&Hanako PPT 的本地网页界面。

用法：
    python start_ui.py                # 默认 127.0.0.1:8765 并自动打开浏览器
    python start_ui.py --port 9000    # 换端口
    python start_ui.py --no-browser   # 只起服务，不自动打开

网页界面做什么：
    1. 粘贴文稿，预览自动拆分的页面大纲
    2. 选主题、设页数、填演示信息
    3. 可视化配置配图密钥（写入本机 .env，权限 0600）
    4. 一键生成 PPT，并列出每页类型、图表/配图标记与失败原因

所有请求只在本机处理，不向外部发送任何数据。
"""

import argparse
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE_ROOT))

# 界面本身只用标准库，但点「生成」时会走 ppt_skill，那里需要
# python-pptx 与 requests。缺依赖时在启动阶段就说明白，
# 而不是等用户填完文稿点生成才看到 traceback。
REQUIRED = [("pptx", "python-pptx"), ("requests", "requests")]


def _check_dependencies():
    missing = [package for module, package in REQUIRED
               if not _importable(module)]
    if missing:
        print(f"""
❌ 缺少必要的依赖：{'、'.join(missing)}

   请先安装：

       pip install python-pptx requests Pillow

   国内网络慢的话用镜像源：

       pip install python-pptx requests Pillow \\
           -i https://pypi.tuna.tsinghua.edu.cn/simple

   装好后重新启动界面。
""")
        return False
    return True


def _importable(module_name):
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


def main():
    parser = argparse.ArgumentParser(description="华予&Hanako PPT 本地网页界面")
    parser.add_argument("--host", default="127.0.0.1",
                        help="监听地址，默认 127.0.0.1（仅本机可达）")
    parser.add_argument("--port", type=int, default=8765, help="端口，默认 8765")
    parser.add_argument("--no-browser", action="store_true",
                        help="不自动打开浏览器")
    parser.add_argument("--env", default=None, help=".env 路径，默认包内 .env")
    args = parser.parse_args()

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("⚠️  警告：监听非本机地址会让同一网络的其他设备访问本服务。")
        print("    本服务没有鉴权，请仅在可信网络使用。")

    if not _check_dependencies():
        return 10

    from ppt_skill.ui_server import serve
    return serve(host=args.host, port=args.port,
                 open_browser=not args.no_browser, env_path=args.env)


if __name__ == "__main__":
    sys.exit(main())
