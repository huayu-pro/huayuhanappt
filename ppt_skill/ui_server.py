"""本地 Web 界面服务端：内容生成、密钥配置、产物预览。

只用 Python 标准库 http.server，不引入 Flask/ FastAPI——
用户机器上未必有这些包，而"打开浏览器就能用"是这个界面存在的全部理由。

安全边界（T 维）：
  - 只监听 127.0.0.1，不对局域网开放
  - 不转发任何数据到外部；所有请求都在本机处理
  - 密钥写入 .env 后设 0600 权限；GET 接口永不回传密钥值
"""

import json
import os
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from .config import (IMAGE_PROVIDER_ORDER, LIMITS, MORANDI_PALETTES,
                     PROVIDER_KEYS, load_dotenv)
from .errors import SkillError
from .pipeline import generate_ppt, validate_content
from .text_utils import detect_chart_type_from_table

PACKAGE_ROOT = Path(__file__).resolve().parent.parent

# 每个密钥变量的申请地址，配置面板直接展示
KEY_SOURCES = {
    "PEXELS_API_KEY": "https://www.pexels.com/api/",
    "BAIDU_API_KEY": "https://console.bce.baidu.com/ai/",
    "BAIDU_SECRET_KEY": "https://console.bce.baidu.com/ai/",
    "UNSPLASH_ACCESS_KEY": "https://unsplash.com/developers",
    "PIXABAY_API_KEY": "https://pixabay.com/service/about/api/",
}

PROVIDER_LABELS_CN = {
    "bing": "Bing 图片（免密钥，国内可达）",
    "wikimedia": "Wikimedia Commons（免密钥）",
    "pexels": "Pexels（高质量摄影）",
    "baidu": "百度图片（中文关键词）",
    "unsplash": "Unsplash（顶级图库）",
    "pixabay": "Pixabay（覆盖面广）",
}


class UIState:
    """保存最近一次生成的结果，供预览接口读取。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.last_report = None
        self.last_slides = None

    def set(self, report, slides):
        with self.lock:
            self.last_report = report
            self.last_slides = slides


STATE = UIState()

# .env 是 read-modify-write，多个请求同时保存会互相覆盖。
# 加一把锁，配合原子写，保证并发下不丢配置。
ENV_LOCK = threading.Lock()


def _parse_pages(raw):
    """解析页数参数。返回 (页数, 错误信息)。"""
    if raw is None or raw == "":
        return 25, None
    if isinstance(raw, float) and not raw.is_integer():
        return 0, "页数必须是整数"
    try:
        pages = int(raw)
    except (TypeError, ValueError):
        return 0, "页数必须是整数"
    if not (LIMITS["min_pages"] <= pages <= LIMITS["max_pages"]):
        return 0, (f"页数需在 {LIMITS['min_pages']}-{LIMITS['max_pages']} 之间"
                   f"（推荐 {LIMITS['recommended_pages'][0]}-"
                   f"{LIMITS['recommended_pages'][1]}）")
    return pages, None


def make_handler(env_path):
    class UIHandler(BaseHTTPRequestHandler):
        server_version = f"HuayuHanakoPPT/{__version__}"

        # ---- 基础设施 ----
        def log_message(self, fmt, *args):
            # 安静一点：只在调试时打印
            pass

        def _send_json(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _fail(self, message, details=None):
            """统一的失败响应，并清掉上一次成功的 STATE。

            不清 STATE 的话，一次失败请求之后 /api/preview 还会返回
            上一次的产物路径，用户会以为刚才是成功的。
            """
            STATE.set(None, None)
            payload = {"ok": False, "error": message}
            if details:
                payload["details"] = details
            self._send_json(payload, status=400)

        def _send_html(self, html, status=200):
            body = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_body(self):
            """读取 JSON 请求体。返回 (dict, 错误信息)。"""
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return {}, "Content-Length 不是数字"
            if length <= 0:
                return {}, "请求体是空的"
            if length > 8 * 1024 * 1024:
                return {}, "请求体超过 8MB 上限"
            try:
                raw = self.rfile.read(length)
            except OSError as exc:
                return {}, f"读取请求体失败：{exc}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                return {}, f"请求体不是合法 JSON：{exc}"
            if not isinstance(payload, dict):
                return {}, "请求体必须是 JSON 对象"
            return payload, None

        # ---- 路由 ----
        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._send_html(render_page())
            elif path == "/api/config":
                self._handle_get_config()
            elif path == "/api/themes":
                self._handle_get_themes()
            elif path == "/api/preview":
                self._handle_get_preview()
            elif path == "/api/examples":
                self._handle_get_examples()
            else:
                self._send_json({"error": "not found"}, status=404)

        def do_POST(self):
            path = urlparse(self.path).path
            if path == "/api/keys":
                self._handle_save_keys()
            elif path == "/api/generate":
                self._handle_generate()
            elif path == "/api/outline":
                self._handle_outline()
            else:
                self._send_json({"error": "not found"}, status=404)

        # ---- GET /api/config ----
        def _handle_get_config(self):
            values = load_dotenv(env_path)
            # 按「实际尝试顺序」展示（免密钥的一号优先级排最前），
            # 不按 PROVIDER_KEYS 的字典序——展示序与尝试序不一致会误导
            providers = []
            for provider in IMAGE_PROVIDER_ORDER:
                variables = PROVIDER_KEYS.get(provider, [])
                if not variables:
                    providers.append({
                        "provider": provider,
                        "label": PROVIDER_LABELS_CN.get(provider, provider),
                        "needs_key": False,
                        "configured": True,
                        "variables": [],
                        "sources": [],
                    })
                    continue
                configured = all(
                    _looks_filled(values.get(v)) for v in variables)
                providers.append({
                    "provider": provider,
                    "label": PROVIDER_LABELS_CN.get(provider, provider),
                    "needs_key": True,
                    "configured": configured,
                    "variables": variables,
                    "sources": [KEY_SOURCES.get(v, "") for v in variables],
                })
            self._send_json({
                "version": __version__,
                "env_path": str(env_path),
                "providers": providers,
                "limits": LIMITS,
            })

        # ---- GET /api/themes ----
        def _handle_get_themes(self):
            themes = [
                {"name": name, "display": info["display"], "scene": info["scene"],
                 "preview": _theme_preview(info)}
                for name, info in MORANDI_PALETTES.items()
            ]
            self._send_json({"themes": themes})

        # ---- GET /api/examples ----
        def _handle_get_examples(self):
            examples, templates = [], []
            for folder, bucket in (("examples", examples), ("templates", templates)):
                directory = PACKAGE_ROOT / "assets" / folder
                if not directory.is_dir():
                    continue
                for path in sorted(directory.glob("*.json")):
                    data = None
                    try:
                        loaded = json.loads(path.read_text(encoding="utf-8"))
                        if isinstance(loaded, dict):
                            data = loaded
                    except (ValueError, OSError):
                        data = None
                    slides = data.get("slides") if data else None
                    bucket.append({
                        "name": path.stem,
                        "pages": len(slides) if isinstance(slides, list) else 0,
                        "title": ((data.get("meta") or {}).get("title", "")
                                  if isinstance(data.get("meta"), dict) else ""),
                    })
            self._send_json({"examples": examples, "templates": templates})

        # ---- POST /api/keys ----
        def _handle_save_keys(self):
            body, read_error = self._read_body()
            if read_error:
                self._send_json({"ok": False, "error": read_error}, status=400)
                return
            keys = body.get("keys") or {}
            if not isinstance(keys, dict):
                self._send_json({"ok": False, "error": "keys 必须是对象"}, status=400)
                return

            allowed = {v for vs in PROVIDER_KEYS.values() for v in vs}
            with ENV_LOCK:
                path = Path(env_path)
                existing = {}
                if path.is_file():
                    for line in path.read_text(encoding="utf-8-sig").splitlines():
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, _, v = line.partition("=")
                            existing[k.strip()] = v.strip()

                written = []
                for name, value in keys.items():
                    if name not in allowed:
                        continue
                    value = str(value or "").strip()
                    # 拒绝换行：否则「abc\nEVIL=1」会被写进 .env，
                    # 回读时多出一行不相干的配置——这是 .env 注入。
                    if not value or "\n" in value or "\r" in value:
                        continue
                    existing[name] = value
                    written.append(name)

                lines = ["# 由华予&Hanako PPT 网页配置面板生成",
                         "# 请勿提交到公开仓库", ""]
                for name in sorted(existing):
                    lines.append(f"{name}={existing[name]}")
                lines.append("")

                # 原子写：先写临时文件再替换，避免并发或中断留下半截 .env
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_text("\n".join(lines), encoding="utf-8")
                os.replace(tmp, path)
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass  # Windows 上无此概念，忽略

            self._send_json({
                "ok": True,
                "written": written,
                "message": f"已写入 {len(written)} 项配置到 {path}",
            })

        # ---- POST /api/outline ----
        def _handle_outline(self):
            """从文稿生成页面大纲（不写文件，仅供预览确认）。"""
            body, read_error = self._read_body()
            if read_error:
                self._send_json({"ok": False, "error": read_error}, status=400)
                return
            text = str(body.get("text") or "")
            pages, page_error = _parse_pages(body.get("pages"))
            if page_error:
                self._send_json({"ok": False, "error": page_error}, status=400)
                return
            if not text.strip():
                self._send_json({"ok": False, "error": "请先粘贴文稿"}, status=400)
                return
            if len(text) > LIMITS["max_input_chars"]:
                self._send_json({
                    "ok": False,
                    "error": f"文稿超过 {LIMITS['max_input_chars']} 字上限",
                }, status=400)
                return

            from .outline import build_outline
            try:
                slides = build_outline(text, pages)
            except SkillError as exc:
                self._send_json({"ok": False, "error": exc.render()}, status=400)
                return

            # 保留上一次成功生成的记录：预览只是看大纲，不该让
            # /api/preview 的产物记录失效（否则"刚生成成功"却 404）
            STATE.set(STATE.last_report, slides)
            self._send_json({
                "ok": True,
                "slides": [_slide_brief(s) for s in slides],
                "count": len(slides),
            })

        # ---- POST /api/generate ----
        def _handle_generate(self):
            body, read_error = self._read_body()
            if read_error:
                self._fail(read_error)
                return
            text = str(body.get("text") or "")
            pages, page_error = _parse_pages(body.get("pages"))
            theme = str(body.get("theme") or "morandi_blue")
            skip_images = bool(body.get("skip_images"))
            meta = body.get("meta") or {}
            if not isinstance(meta, dict):
                meta = {}

            if page_error:
                self._send_json({"ok": False, "error": page_error}, status=400)
                return
            if not text.strip():
                self._send_json({"ok": False, "error": "请先粘贴文稿"}, status=400)
                return
            if len(text) > LIMITS["max_input_chars"]:
                self._send_json({
                    "ok": False,
                    "error": f"文稿超过 {LIMITS['max_input_chars']} 字上限",
                }, status=400)
                return

            from .config import Config
            from .outline import build_outline

            config = Config(env_path=env_path, load_env_file=True)
            try:
                config.set_theme(theme)
            except SkillError as exc:
                self._fail(exc.render())
                return
            config.skip_images = skip_images
            # 产物默认落到用户主目录，不要写进包安装位置
            config.output_dir = Path.home() / "学术PPT输出"

            try:
                slides = build_outline(text, pages)
            except SkillError as exc:
                self._fail(exc.render())
                return

            errors = validate_content(slides)
            if errors:
                self._fail("内容校验未通过", [e.render() for e in errors])
                return

            try:
                image_map, image_failures = ({}, [])
                if not skip_images:
                    image_map, image_failures = _scrape(slides, config)
            except SkillError as exc:
                self._fail(exc.render())
                return

            # meta.title 可能是数字等非字符串——先收敛，否则 int + str TypeError
            # 会让连接直接断掉（前端只看到"请求失败"）
            filename = (str(meta.get("title") or "") or slides[0].title
                        or "学术汇报") + ".pptx"
            config.filename = filename

            try:
                report = generate_ppt(
                    slides, config, meta=_full_meta(meta, slides),
                    image_map=image_map, image_failures=image_failures)
            except SkillError as exc:
                self._fail(exc.render())
                return

            if not report.ok:
                self._fail("内容校验未通过",
                           [e.render() for e in report.validation_errors])
                return

            STATE.set(report, slides)
            self._send_json({
                "ok": True,
                "output": str(report.output_path),
                "pages": report.total_pages,
                "theme": report.theme,
                "images": report.images_used,
                "elapsed": report.elapsed_seconds,
                "warnings": report.warnings,
                "image_failures": report.image_failures,
                "slides": [_slide_brief(s) for s in slides],
            })

        # ---- GET /api/preview ----
        def _handle_get_preview(self):
            """返回最近一次生成的页面清单与产物路径。"""
            report, slides = STATE.last_report, STATE.last_slides
            if report is None or not slides:
                self._send_json({"ok": False, "error": "还没有生成记录"}, status=404)
                return
            self._send_json({
                "ok": True,
                "output": str(report.output_path),
                "pages": report.total_pages,
                "theme": report.theme,
                "images": report.images_used,
                "warnings": report.warnings,
                "image_failures": report.image_failures,
                "slides": [_slide_brief(s) for s in slides],
            })

    return UIHandler


def _looks_filled(value):
    if value is None:
        return False
    v = str(value).strip()
    if not v:
        return False
    return not re.match(r"^(your|在这里|请填写|example|sample)", v, re.IGNORECASE)


def _theme_preview(info):
    return {
        "primary": "#%02X%02X%02X" % info["primary"],
        "accent": "#%02X%02X%02X" % info["accent"],
        "bg": "#%02X%02X%02X" % info["bg"],
        "title": "#%02X%02X%02X" % info["title"],
    }


def _slide_brief(slide):
    # chart_type 留空时渲染层会自动推断——大纲预览按同一规则标注，
    # 否则含数据的页面在大纲里显示"无图表"，生成日志却说"推断为饼图"
    chart_type = slide.chart_type
    if slide.table_data and not chart_type:
        chart_type = detect_chart_type_from_table(slide.table_data, [slide.title])
    return {
        "page": slide.page_num,
        "type": slide.slide_type,
        "title": slide.title,
        "bullets": len(slide.bullet_points),
        "has_chart": bool(slide.table_data and chart_type),
        "has_image": bool(slide.image_keywords),
    }


def _full_meta(meta, slides):
    return {
        "title": str(meta.get("title") or slides[0].title or ""),
        "presenter": str(meta.get("presenter") or ""),
        "institution": str(meta.get("institution") or ""),
        "date": str(meta.get("date") or ""),
    }


def _scrape(slides, config):
    from .scraping.downloader import ImageScraper

    image_dir = Path(config.output_dir) / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    # 免密钥来源（bing/wikimedia）恒可用，available_providers() 理论上
    # 永不为空；真为空（未来来源配置改动）时列出全部关键词，不截断
    if not config.available_providers():
        return {}, [{
            "page_num": s.page_num, "keyword": k,
            "reason": "没有可用的图片来源",
            "hint": "检查网络连接，或关闭自动配图",
        } for s in slides for k in s.image_keywords]
    scraper = ImageScraper(config)
    result = scraper.scrape_all(slides, image_dir)
    image_map = {}
    for slide in slides:
        paths = [p for p in result.images
                 if p.name.startswith(f"p{slide.page_num:02d}_")]
        if paths:
            image_map[slide.page_num] = paths
    return image_map, [f.as_dict() for f in result.failures]


def render_page():
    """读取前端页面模板。"""
    template = PACKAGE_ROOT / "assets" / "ui.html"
    if template.is_file():
        return template.read_text(encoding="utf-8")
    return "<html><body><h1>缺少 assets/ui.html</h1></body></html>"


def serve(host="127.0.0.1", port=8765, open_browser=True, env_path=None):
    """启动本地服务。"""
    env_path = Path(env_path or (PACKAGE_ROOT / ".env"))
    handler = make_handler(env_path)
    try:
        server = ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        print(f"\n❌ 无法在 {host}:{port} 启动服务：{exc}")
        if "in use" in str(exc) or "Address already" in str(exc):
            print(f"   → 端口 {port} 已被占用，换一个端口重试："
                  f"python start_ui.py --port {port + 1}")
        else:
            print("   → 检查监听地址是否正确，或换一个端口重试")
        return 10
    # --port 0 时由系统随机分配端口，banner 必须用绑定后的真实值
    real_port = server.server_address[1]
    url = f"http://{host}:{real_port}"
    print(f"""
=====================================================================
   华予&Hanako PPT · 本地网页界面 已启动
=====================================================================

   在浏览器打开：  {url}

   • 所有数据只在本机处理，不会外传
   • 密钥写入 {env_path}（权限 0600）
   • 按 Ctrl+C 停止服务

""")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()
    return 0
