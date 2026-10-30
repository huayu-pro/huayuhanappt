# 配图来源配置指引

六个来源按优先级依次尝试，任一级成功就不再往下走：

```
bing → pexels → baidu → unsplash → wikimedia → pixabay
 ↑免密钥   ↑需密钥    ↑需密钥    ↑需密钥      ↑免密钥    ↑需密钥
```

把免密钥的排在最前是刻意的：新手一个密钥都没配时也能出图，而不是四级全空转。

## 各来源对照

| 来源 | 密钥变量 | 限额 | 特点 |
|---|---|---|---|
| Bing 图片 | 无 | 无明确限制 | 国内可达，中文关键词友好，兜底主力 |
| Pexels | `PEXELS_API_KEY` | 200 次/小时 | 高质量摄影图，学术场景最稳 |
| 百度图片 | `BAIDU_API_KEY` + `BAIDU_SECRET_KEY` | 按百度配额 | 中文关键词优势，国内主题命中率高 |
| Unsplash | `UNSPLASH_ACCESS_KEY` | 50 次/小时 | 顶级免费图库，高分辨率 |
| Wikimedia Commons | 无 | 无明确限制 | 知识共享许可，适合历史/科学类主题 |
| Pixabay | `PIXABAY_API_KEY` | 按 Pixabay 配额 | 覆盖面广，最后兜底 |

## 申请地址

| 变量 | 申请入口 |
|---|---|
| `PEXELS_API_KEY` | https://www.pexels.com/api/ |
| `BAIDU_API_KEY` / `BAIDU_SECRET_KEY` | https://console.bce.baidu.com/ai/ |
| `UNSPLASH_ACCESS_KEY` | https://unsplash.com/developers |
| `PIXABAY_API_KEY` | https://pixabay.com/service/about/api/ |

## 配置方式

**方式一：网页面板（推荐新手）**

```bash
python start_ui.py
```
在「配图密钥配置」卡片里填密钥，点「保存密钥到 .env」。文件写入包目录下的 `.env`，权限自动设为 0600（仅本人可读）。

**方式二：手动编辑**

```bash
cp .env.example .env
```
然后填入密钥。格式是 `变量名=值`，一行一个，`#` 开头是注释。

**方式三：环境变量**

```bash
export PEXELS_API_KEY="你的密钥"
python huayu_hanako_ppt.py --content 汇报.json
```
环境变量优先于 `.env` 文件，适合 CI 或临时使用。

## 一个密钥都不配会怎样

照样能生成 PPT。此时只用 Bing 与 Wikimedia 两个免密钥来源；再加 `--skip-images` 则完全离线，只做文字排版。

## 密钥状态怎么看

网页界面的「配图密钥配置」卡片会显示每个来源的状态：免密钥 / 已配置 / 未配置。

命令行下没配密钥的来源会被直接跳过，不会拿着占位符去发无效请求——这是 v1.0.1 的修复点之一。

## 安全说明

- 密钥只写本机 `.env`，服务只监听 127.0.0.1，不向任何第三方转发
- `.env` 已按惯例加入忽略清单，但**仍不要把它提交到公开仓库**
- 密钥疑似泄露时，去对应平台控制台吊销重建

## 版权提示

配图来自公网图库，授权条款各不相同（Pexels/Unsplash/Pixabay 是免费许可，百度图片搜索结果的版权归原站点）。
**用于公开发布、答辩存档或商业用途前，请自行核实每张图的授权范围。**

学术场景下更稳妥的做法：把 `image_keywords` 指向 Wikimedia Commons 收录的知识共享图片（如历史人物、科学图示），或用自己的实验/田野照片。
