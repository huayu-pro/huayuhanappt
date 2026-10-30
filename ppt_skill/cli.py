"""命令行入口：参数解析、错误五分类、退出码。

退出码语义（与 errors.py 一致，对照表见 references/troubleshooting.md）：

    0  成功
    10 配置类错误 CONFIG   —— 密钥缺失/无效、主题名拼错、输出目录不可写、
                                缺少 python-pptx/requests 依赖（入口脚本同码）
    11 输入类错误 INPUT   —— 内容文件缺失/格式错、页数越界、页码重复
    12 接口类错误 API     —— 图片接口全部失败、被限流、密钥被拒
    13 渲染类错误 RENDER  —— python-pptx 生成或保存失败
    14 超时类错误 TIMEOUT —— 整体生成超过时限
"""

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import Config, LIMITS, MORANDI_PALETTES
from .content_source import extract_meta, load_content
from .errors import SkillError
from .pipeline import generate_ppt

BANNER = f"""
=====================================================================
   华予&Hanako PPT —— 学术全自动PPT生成器  v{__version__}
   Huayu & Hanako Academic PPT Generator
=====================================================================
"""

USAGE_EXAMPLES = """
用法示例：
  # 用内置样例生成（最省事，先看效果）
  python huayu_hanako_ppt.py --example minimal_8

  # 用自己的内容文件生成
  python huayu_hanako_ppt.py --content 我的汇报.json --theme morandi_blue

  # 不爬配图，纯排版（离线/赶时间）
  python huayu_hanako_ppt.py --content 我的汇报.json --skip-images

  # 只有文稿没有内容文件：粘贴进 txt，自动拆页
  python huayu_hanako_ppt.py --text-file 讲稿.txt --pages 25

  # 查看所有主题
  python huayu_hanako_ppt.py --list-themes

  # 打开本地网页界面（推荐新手）
  python start_ui.py
"""


def build_parser():
    parser = argparse.ArgumentParser(
        prog="huayu_hanako_ppt.py",
        description="华予&Hanako PPT —— 学术全自动PPT生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=USAGE_EXAMPLES,
    )
    parser.add_argument("--content", "-c", metavar="文件",
                        help="内容文件（JSON 或 YAML）；assets/examples/ 下有样例")
    parser.add_argument("--text-file", "-w", metavar="文稿",
                        help="纯文稿（txt/md），由大纲引擎自动拆页；"
                             "配合 --pages 设定目标页数")
    parser.add_argument("--example", "-e", metavar="名称",
                        help="使用内置样例：minimal_8 / medium_15 / full_30")
    parser.add_argument("--template", "-t", metavar="名称",
                        help="使用空白模板：defense / project_report / journal_club / generic")
    parser.add_argument("--theme", default="morandi_blue",
                        help=f"主题名，默认 morandi_blue；可选：{' / '.join(sorted(MORANDI_PALETTES))}")
    parser.add_argument("--pages", "-p", type=int, default=25, metavar="页数",
                        help=f"目标页数，默认 25；范围 "
                             f"{LIMITS['min_pages']}-{LIMITS['max_pages']}"
                             f"（仅在用文稿自动生成大纲时生效）")
    parser.add_argument("--output", "-o", metavar="目录", default="学术PPT输出",
                        help="输出目录，默认 学术PPT输出")
    parser.add_argument("--filename", "-f", metavar="文件名", default=None,
                        help="输出文件名，默认取内容标题")
    parser.add_argument("--skip-images", action="store_true",
                        help="跳过配图爬取，只做排版")
    parser.add_argument("--clean", action="store_true",
                        help="生成前清空输出目录里的旧配图")
    parser.add_argument("--list-themes", action="store_true",
                        help="列出所有主题后退出")
    parser.add_argument("--check", action="store_true",
                        help="只校验内容文件，不生成")
    parser.add_argument("--env", metavar="文件", default=".env",
                        help=".env 路径，默认 .env")
    parser.add_argument("--version", action="version",
                        version=f"huayu-hanako-ppt {__version__}")
    return parser


def list_themes():
    print("\n可用主题：")
    for name, info in MORANDI_PALETTES.items():
        print(f"  {name:16s} {info['display']}  （适合：{info['scene']}）")
    print()


def resolve_builtin(kind, name, package_root):
    """定位 assets/ 下的内置样例或模板。"""
    from .errors import InputError

    folder = "examples" if kind == "example" else "templates"
    label = "样例" if kind == "example" else "模板"
    if not name:
        return None
    candidates = [
        package_root / "assets" / folder / f"{name}.json",
        package_root / "assets" / folder / f"{name}.yaml",
    ]
    for path in candidates:
        if path.is_file():
            return path
    available = []
    folder_path = package_root / "assets" / folder
    if folder_path.is_dir():
        available = sorted(p.stem for p in folder_path.glob("*.json"))
    raise InputError(
        f"找不到{label}：{name}",
        f"可用的{label}有：{'、'.join(available) or '无'}",
    )


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    print(BANNER)

    if args.list_themes:
        list_themes()
        return 0

    package_root = Path(__file__).resolve().parent.parent

    # ---- 定位内容来源 ----
    content_path = None
    if args.text_file:
        content_path = Path(args.text_file)
    elif args.content:
        content_path = Path(args.content)
        if not content_path.is_absolute() and not content_path.exists():
            # 也允许只写文件名，从 assets 的 examples 与 templates 里找
            for folder in ("examples", "templates"):
                alt = package_root / "assets" / folder / args.content
                if alt.is_file():
                    content_path = alt
                    break
    elif args.example:
        content_path = resolve_builtin("example", args.example, package_root)
    elif args.template:
        content_path = resolve_builtin("template", args.template, package_root)
    else:
        # 默认用最小样例，保证开箱能跑
        content_path = resolve_builtin("example", "minimal_8", package_root)

    # ---- 配置 ----
    config = Config(env_path=args.env, load_env_file=True)
    config.skip_images = args.skip_images
    config.clean = args.clean
    config.output_dir = Path(args.output)
    config.set_theme(args.theme)

    print(f"🎨 主题：{config.theme}（{config.palette['display']}）")
    print(f"🖼️  配图：{'跳过' if args.skip_images else '启用'}")

    # ---- 加载内容 ----
    if args.text_file:
        from .outline import build_outline
        try:
            text = content_path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            from .errors import InputError
            raise InputError(f"文稿读取失败：{content_path}（{exc}）",
                             "检查文件路径与权限")
        print(f"📄 文稿：{content_path}（{len(text)} 字）")
        print(f"📋 目标页数：{args.pages}（由大纲引擎自动拆页）")
        slides = build_outline(text, args.pages)
        data = {}
    else:
        print(f"📄 内容文件：{content_path}")
        slides, data = load_content(content_path)
        print(f"📋 共 {len(slides)} 页")
    meta = extract_meta(data) if data else {}

    # ---- 校验 ----
    from .pipeline import validate_content
    errors = validate_content(slides)
    if errors:
        print("\n❌ 内容校验未通过：")
        for err in errors:
            print(err.render())
        print("\n请按上面的提示修改内容文件后重试。")
        return 11
    print("  ✅ 内容校验通过")

    if args.check:
        print("\n--check 模式：仅校验，不生成。")
        return 0

    # ---- 配图 ----
    image_map = {}
    if not args.skip_images:
        image_map = _scrape_images(slides, config, args.output)

    # ---- 文件名 ----
    if not args.filename:
        args.filename = (meta.get("title") or slides[0].title or "学术汇报") + ".pptx"
    config.filename = args.filename

    # ---- 生成 ----
    image_failures = config.last_image_failures
    report = generate_ppt(slides, config, meta=meta, image_map=image_map,
                          image_failures=image_failures)

    print("\n" + "=" * 62)
    if not report.ok:
        print("❌ 生成失败：")
        for err in report.validation_errors:
            print(err.render())
        return 11

    print("🎉 生成完成")
    print("=" * 62)
    print(f"  📍 文件：{report.output_path}")
    print(f"  📄 页数：{report.total_pages}")
    print(f"  🎨 主题：{report.theme}")
    print(f"  🖼️  配图：{report.images_used} 张")
    print(f"  ⏱️  耗时：{report.elapsed_seconds} 秒")

    if report.image_failures:
        print(f"\n  ⚠️  {len(report.image_failures)} 个关键词没找到配图：")
        for failure in report.image_failures[:10]:
            print(f"    - 第 {failure['page_num']} 页「{failure['keyword']}」：{failure['reason']}")
        if len(report.image_failures) > 10:
            print(f"    ……另有 {len(report.image_failures) - 10} 条")
        print("  → 这些页已按无图版式渲染，不影响 PPT 完整性。")

    if report.warnings:
        print("\n  ⚠️  提醒：")
        for warning in report.warnings[:10]:
            print(f"    - {warning}")

    print()
    return 0


def _scrape_images(slides, config, output_dir):
    """爬取配图，返回 {page_num: [Path]}。

    全部失败时不让整个任务失败——无图也能出 PPT，但要把原因讲清楚。
    """
    from .scraping.downloader import ImageScraper

    image_dir = Path(output_dir) / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    if config.clean:
        for old in image_dir.glob("*.jpg"):
            old.unlink(missing_ok=True)
        for old in image_dir.glob("*.png"):
            old.unlink(missing_ok=True)

    if not config.available_providers():
        print("\n  ⚠️  没有可用的图片来源，跳过配图。")
        print("     → 配密钥：复制 .env.example 为 .env 填入；或直接用 start_ui.py 网页配置")
        print("     → Bing 与 Wikimedia 免密钥但需联网；完全离线可加 --skip-images")
        return {}

    print(f"\n🖼️  开始爬取配图（可用来源：{'、'.join(config.available_providers())}）")
    scraper = ImageScraper(config)
    result = scraper.scrape_all(slides, image_dir)

    image_map = {}
    for slide in slides:
        paths = [p for p in result.images if p.name.startswith(f"p{slide.page_num:02d}_")]
        if paths:
            image_map[slide.page_num] = paths

    stats = scraper.stats
    print(f"  📊 搜索 {stats['searched']} 次，下载 {stats['downloaded']} 张，"
          f"失败 {stats['failed']} 次"
          + (f"，跳过 {stats['skipped_pages']} 页（无配图关键词）"
             if stats["skipped_pages"] else ""))

    if result.failures:
        # 失败明细挂到环境变量供上层报告——但更直接的是打印
        print(f"  ⚠️  {len(result.failures)} 个关键词未获取到配图（详见生成结束后的汇总）")
        config.last_image_failures = [f.as_dict() for f in result.failures]

    return image_map


def run(argv=None):
    """带错误分类的入口。返回退出码。"""
    try:
        return main(argv)
    except SkillError as exc:
        print(f"\n❌ {exc.render()}")
        return exc.exit_code
    except KeyboardInterrupt:
        print("\n已取消。")
        return 130
    except Exception as exc:
        print(f"\n❌ 未预期的错误：{type(exc).__name__}: {exc}")
        print("  → 把完整报错贴到 issues，或加 --check 先排查内容文件")
        return 1


if __name__ == "__main__":
    sys.exit(run())
