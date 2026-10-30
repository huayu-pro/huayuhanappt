"""六个图片来源的统一协议与实现。

v2.0.0 相对原版的四点变化：

1. 新增两个国内可达、免密钥的来源（Bing 图片、Wikimedia Commons），
   把原来的四级链扩成六级。原版"四级兜底"里四个接口全都要密钥，
   新手一个都没配时四层全空转——现在至少有两个免密钥接口能出图。
2. 每个 provider 声明自己需要哪些密钥变量，未配置时直接跳过，
   不再像原版那样拿着 "YOUR_PEXELS_API_KEY_HERE" 占位符去发无效请求。
3. 401/403 明确区分"密钥无效"与"网络异常"，并把密钥标记为 invalid，
   同一轮里不再重复试同一个废密钥。
4. 统一返回 (urls, failure) 二元组，失败原因向上传递。

只申请需要的网络访问：所有 provider 都走 https，无上传、无第三方转发。
"""

from typing import List, Optional, Tuple

from ..config import IMAGE_PROVIDER_ORDER

# 默认优先级：先免密钥国内可达，再按质量排序。
# 唯一定义在 ppt_skill/config.py 的 IMAGE_PROVIDER_ORDER（避免循环导入），
# 这里转出给外部使用。
PROVIDER_ORDER = list(IMAGE_PROVIDER_ORDER)

PROVIDER_LABELS = {
    "pexels": "Pexels（高质量摄影，需密钥）",
    "baidu": "百度图片（中文关键词，需密钥）",
    "unsplash": "Unsplash（顶级图库，需密钥）",
    "pixabay": "Pixabay（覆盖面广，需密钥）",
    "bing": "Bing 图片（国内可达，免密钥）",
    "wikimedia": "Wikimedia Commons（免密钥，知识共享配图）",
}


class Provider:
    """图片来源基类。"""

    name = "base"
    label = ""
    needs_keys: Tuple[str, ...] = ()

    def __init__(self, config):
        self.config = config

    def ready(self) -> bool:
        """免密钥接口恒可用；需密钥的接口必须已配好且未被判废。"""
        state = self.config.key_states.get(self.name)
        if not state:
            return False
        if not self.needs_keys:
            return True
        return state.status == "set"

    def search(self, keyword: str, limit: int = 3) -> Tuple[List[str], Optional[str]]:
        """返回 (图片URL列表, 失败原因)。成功时失败原因为 None。"""
        raise NotImplementedError

    # 供子类使用的统一请求入口
    def _get(self, session, url, **kwargs):
        kwargs.setdefault("timeout", 15)
        return session.get(url, **kwargs)

    def _json(self, resp, provider_name):
        """安全解析 JSON。

        接口返回 200 但内容是 HTML（反爬页、网关错误页）时，
        resp.json() 会抛 ValueError。若不接住，这个异常会一路冒到
        CLI 兜底，把"这一个关键词没图"放大成"整个生成失败"。
        """
        try:
            payload = resp.json()
        except ValueError:
            return None, "返回内容不是 JSON（可能被反爬拦截或网关错误）"
        if not isinstance(payload, dict):
            return None, "返回的 JSON 结构不符合预期"
        return payload, None

    @staticmethod
    def _dict_list(payload, key):
        """取出 payload[key] 里所有 dict 元素，跳过 None 等脏数据。"""
        items = payload.get(key)
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]


class PexelsProvider(Provider):
    name = "pexels"
    label = PROVIDER_LABELS["pexels"]
    needs_keys = ("PEXELS_API_KEY",)

    def search(self, keyword, limit=3):
        key = self.config.secret("PEXELS_API_KEY")
        if not key:
            return [], "未配置 PEXELS_API_KEY"
        url = "https://api.pexels.com/v1/search"
        params = {"query": keyword, "per_page": limit,
                  "orientation": "landscape", "size": "large"}
        try:
            resp = self._get(self.session, url, params=params,
                             headers={"Authorization": key})
        except Exception as exc:
            return [], f"网络异常：{type(exc).__name__}"

        if resp.status_code == 200:
            payload, error = self._json(resp, self.name)
            if error:
                return [], error
            urls = []
            for photo in self._dict_list(payload, "photos"):
                src = photo.get("src")
                if not isinstance(src, dict):
                    continue
                for size in ("original", "large2x", "large"):
                    if src.get(size):
                        urls.append(src[size])
                        break
            return urls[:limit], None
        if resp.status_code in (401, 403):
            self.config.mark_key_invalid("pexels", "密钥被拒绝")
            return [], "密钥无效（401/403），请检查 PEXELS_API_KEY"
        if resp.status_code == 429:
            return [], "触发速率限制（429），稍后再试或换密钥"
        return [], f"接口返回 HTTP {resp.status_code}"


class BaiduProvider(Provider):
    name = "baidu"
    label = PROVIDER_LABELS["baidu"]
    needs_keys = ("BAIDU_API_KEY", "BAIDU_SECRET_KEY")

    def search(self, keyword, limit=3):
        api_key = self.config.secret("BAIDU_API_KEY")
        secret = self.config.secret("BAIDU_SECRET_KEY")
        if not api_key or not secret:
            return [], "未配置 BAIDU_API_KEY / BAIDU_SECRET_KEY"
        try:
            resp = self._get(
                self.session,
                "https://image.baidu.com/search/acjson",
                params={"tn": "resultjson_com", "word": keyword,
                        "pn": 0, "rn": limit, "ie": "utf-8", "oe": "utf-8"},
                headers={"Referer": "https://image.baidu.com/"},
            )
        except Exception as exc:
            return [], f"网络异常：{type(exc).__name__}"

        if resp.status_code != 200:
            if resp.status_code in (401, 403):
                self.config.mark_key_invalid("baidu", "密钥被拒绝")
                return [], "密钥无效，请检查 BAIDU_API_KEY / BAIDU_SECRET_KEY"
            return [], f"接口返回 HTTP {resp.status_code}"
        # 与其他五家共用 _json 防线：200 但内容是 HTML/数组时
        # 返回可读原因，绝不抛 AttributeError（那会把"一个关键词没图"
        # 放大成"整个生成失败"）
        data, error = self._json(resp, self.name)
        if error:
            return [], error

        urls = []
        for item in self._dict_list(data, "data"):
            img = item.get("middleURL") or item.get("thumbURL")
            if img:
                urls.append(img)
            if len(urls) >= limit:
                break
        return urls, None


class UnsplashProvider(Provider):
    name = "unsplash"
    label = PROVIDER_LABELS["unsplash"]
    needs_keys = ("UNSPLASH_ACCESS_KEY",)

    def search(self, keyword, limit=3):
        key = self.config.secret("UNSPLASH_ACCESS_KEY")
        if not key:
            return [], "未配置 UNSPLASH_ACCESS_KEY"
        url = "https://api.unsplash.com/search/photos"
        params = {"query": keyword, "per_page": limit,
                  "orientation": "landscape", "content_filter": "high"}
        try:
            resp = self._get(self.session, url, params=params,
                             headers={"Authorization": f"Client-ID {key}"})
        except Exception as exc:
            return [], f"网络异常：{type(exc).__name__}"

        if resp.status_code == 200:
            payload, error = self._json(resp, self.name)
            if error:
                return [], error
            urls = []
            for item in self._dict_list(payload, "results"):
                urls_obj = item.get("urls")
                raw = urls_obj.get("raw") if isinstance(urls_obj, dict) else None
                if raw:
                    urls.append(f"{raw}&w=1920&h=1080&fit=crop")
            return urls[:limit], None
        if resp.status_code in (401, 403):
            self.config.mark_key_invalid("unsplash", "密钥被拒绝")
            return [], "密钥无效（401/403），请检查 UNSPLASH_ACCESS_KEY"
        if resp.status_code == 429:
            return [], "触发速率限制（429）"
        return [], f"接口返回 HTTP {resp.status_code}"


class PixabayProvider(Provider):
    name = "pixabay"
    label = PROVIDER_LABELS["pixabay"]
    needs_keys = ("PIXABAY_API_KEY",)

    def search(self, keyword, limit=3):
        key = self.config.secret("PIXABAY_API_KEY")
        if not key:
            return [], "未配置 PIXABAY_API_KEY"
        url = "https://pixabay.com/api/"
        params = {"key": key, "q": keyword, "per_page": limit,
                  "image_type": "photo", "orientation": "horizontal",
                  "min_width": 1920, "safesearch": "true"}
        try:
            resp = self._get(self.session, url, params=params)
        except Exception as exc:
            return [], f"网络异常：{type(exc).__name__}"

        if resp.status_code == 200:
            payload, error = self._json(resp, self.name)
            if error:
                return [], error
            urls = []
            for hit in self._dict_list(payload, "hits"):
                for size in ("fullHD", "largeImage", "webformatURL"):
                    if hit.get(size):
                        urls.append(hit[size])
                        break
            return urls[:limit], None
        if resp.status_code in (400, 401, 403):
            self.config.mark_key_invalid("pixabay", "密钥被拒绝")
            return [], "密钥无效，请检查 PIXABAY_API_KEY"
        if resp.status_code == 429:
            return [], "触发速率限制（429）"
        return [], f"接口返回 HTTP {resp.status_code}"


class BingProvider(Provider):
    """Bing 图片搜索：国内可达、免密钥。

    作为兜底主力——新手一个密钥都没配时，靠它也能出图。
    解析 HTML 中的 murl（原图地址）字段。
    """

    name = "bing"
    label = PROVIDER_LABELS["bing"]
    needs_keys = ()

    def search(self, keyword, limit=3):
        import json
        import re

        url = "https://www.bing.com/images/search"
        params = {"q": keyword, "form": "HDRSC2", "first": "1"}
        try:
            resp = self._get(self.session, url, params=params,
                             headers={"Accept-Language": "zh-CN,zh;q=0.9"})
        except Exception as exc:
            return [], f"网络异常：{type(exc).__name__}"

        if resp.status_code != 200:
            return [], f"接口返回 HTTP {resp.status_code}"

        # m="{...json...}" 里带 murl 原图地址
        found = re.findall(r'm="(\{[^"]*?murl[^"]*?\})"', resp.text)
        urls = []
        for blob in found:
            try:
                payload = json.loads(blob.replace("&quot;", '"'))
            except ValueError:
                continue
            murl = payload.get("murl")
            if murl and murl.startswith("http"):
                urls.append(murl)
            if len(urls) >= limit:
                break
        return urls, None


class WikimediaProvider(Provider):
    """Wikimedia Commons 搜索：免密钥，知识共享许可，适合学术配图。"""

    name = "wikimedia"
    label = PROVIDER_LABELS["wikimedia"]
    needs_keys = ()

    API = "https://commons.wikimedia.org/w/api.php"

    def search(self, keyword, limit=3):
        params = {
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": f"filetype:bitmap {keyword}", "gsrnamespace": "6",
            "gsrlimit": limit, "prop": "imageinfo", "iiprop": "url",
            "iiurlwidth": "1920",
        }
        try:
            resp = self._get(self.session, self.API, params=params)
        except Exception as exc:
            return [], f"网络异常：{type(exc).__name__}"

        if resp.status_code != 200:
            return [], f"接口返回 HTTP {resp.status_code}"
        payload, error = self._json(resp, self.name)
        if error:
            return [], error

        urls = []
        query = payload.get("query")
        pages = (query.get("pages") if isinstance(query, dict) else None) or {}
        if not isinstance(pages, dict):
            return [], None
        for page in pages.values():
            if not isinstance(page, dict):
                continue
            for info in page.get("imageinfo") or []:
                if not isinstance(info, dict):
                    continue
                thumb = info.get("thumburl") or info.get("url")
                if thumb:
                    urls.append(thumb)
                if len(urls) >= limit:
                    break
        return urls, None


PROVIDER_CLASSES = {
    "pexels": PexelsProvider,
    "baidu": BaiduProvider,
    "unsplash": UnsplashProvider,
    "pixabay": PixabayProvider,
    "bing": BingProvider,
    "wikimedia": WikimediaProvider,
}


def build_providers(config, session, order=None):
    """按优先级构造可用 provider 列表，并注入共享 session。"""
    providers = []
    for name in (order or PROVIDER_ORDER):
        cls = PROVIDER_CLASSES.get(name)
        if cls is None:
            continue
        provider = cls(config)
        provider.session = session
        if provider.ready():
            providers.append(provider)
    return providers
