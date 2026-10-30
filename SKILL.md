---
name: huayu-hanako-ppt
description: "学术/学习类PPT全自动生成器。深度理解文本 → 自动生成8-40页完整内容 → 爬取合规配图（Bing/Pexels/百度/Unsplash/Wikimedia/Pixabay 六级兜底）→ 六主题精美排版（莫兰迪5色+商务经典绿）→ 自动图表（饼图/柱状图/折线图）→ 一键输出pptx幻灯片。提供本地网页界面，粘贴文稿即可生成，无需改代码；密钥可视化配置写入本机 .env。Use when 用户要求做PPT、做一份PPT、生成幻灯片、自动生成PPT、学术汇报、课程汇报、开题报告、毕业答辩、课题汇报、期刊分享、课堂展示、组会汇报，或输入论文/报告/讲稿等大段学术文本并涉及PPT制作、幻灯片排版、PPT配图、自动图表时。Exclude 只要翻译、只要总结、只要普通文档、只要画单张图表的场景；也不要用于制作含敏感信息的对外发布物（配图来自公网图库，版权需自行核实）。"
license: MIT
metadata:
  version: "2.1.0"
  author: "华予（内容架构）& Hanako（排版引擎）"
  upstream_inspiration: "ppt-maker 排版布局、skill-creator-cn TRACE 规范、sandiiarov/skill-creator 密钥引用机制"
---

# 华予&Hanako PPT —— 学术全自动PPT生成器

> 学术PPT不是内容的堆砌，而是思想的骨架。每一页都应当是一个独立且唯一的学术论点断面。
> 排版不是花哨的装饰，而是让思想被清晰看见的桥梁。

## 这个技能做什么

把一段学术文本变成一份排版完整、带配图和自动图表的 PPTX 文件。三条使用路径，按场景选：

| 路径 | 适合谁 | 怎么启动 |
|---|---|---|
| 本地网页界面 | 不想碰代码的人（默认推荐） | `python start_ui.py` |
| 命令行 | 脚本化、批量生成 | `python huayu_hanako_ppt.py --content 文件.json` 或 `--text-file 文稿.txt` |
| 内置样例/模板 | 想先看效果再动手 | `--example minimal_8` / `--template defense` |

三条路径共用同一套生成引擎，产物完全一致。

## 快速开始

```bash
# 1. 装依赖（只此一次）
pip install python-pptx requests Pillow

# 2. 打开网页界面，粘贴文稿就能生成
python start_ui.py

# 或者先用命令行跑内置样例，确认环境没问题
python huayu_hanako_ppt.py --example minimal_8 --skip-images
```

`--skip-images` 表示不爬配图，只做排版——离线、最快、也最容易先跑通。

## 工作流程

### 第一步：确定内容来源（三选一）

**A. 直接粘贴文稿**（网页界面或 AI 辅助）
粘贴论文、报告或讲稿正文，脚本按章节标记（`一、`、`1.`、`第一部分`、`【标题`）自动拆分页面，并把 `XX 45%` 这类数据抽成图表。产出可先预览大纲再生成。

**B. 用空白模板**
`assets/templates/` 下有四套：`defense`（毕业答辩）、`project_report`（课题汇报）、`journal_club`（期刊分享）、`generic`（通用）。把每页的 `title` 和 `bullet_points` 换成自己的内容即可，字段说明见 [references/templates.md](references/templates.md)。

**C. 用完整样例改**
`assets/examples/` 下有三档：`minimal_8`（8 页最小可跑）、`medium_15`（15 页含图表与代码块）、`full_30`（30 页完整展示，主题为卢梭《论不平等》哲学导读）。最接近你需求的样例拿来改，比从空白开始快。

### 第二步：选主题与页数

六套主题，用 `--theme` 或界面下拉框切换：

| 主题名 | 风格 | 适用场景 |
|---|---|---|
| morandi_blue | 莫兰迪蓝 — 理性专业 | 社科、政管、法学、理工 |
| morandi_green | 莫兰迪绿 — 温和自然 | 环境、生物、生态、农学 |
| morandi_clay | 莫兰迪陶土 — 温润知性 | 人文、历史、哲学、文学 |
| morandi_mauve | 莫兰迪灰紫 — 典雅沉静 | 艺术、设计、传媒 |
| morandi_gray | 莫兰迪灰 — 极致简约 | 数学、计算机、技术 |
| classic_green | 商务经典绿 — 正式专业 | 商务汇报、正式答辩 |

`--list-themes` 可随时查看带说明的列表。

### 第三步：配置配图密钥（可选）

**不配任何密钥也能生成**：Bing 图片与 Wikimedia Commons 两个来源免密钥，关掉配图则完全离线。

配了密钥则按 `bing → pexels → baidu → unsplash → wikimedia → pixabay` 六级优先级兜底。密钥只写本机 `.env`（权限 0600），不经过任何第三方：

```bash
cp .env.example .env   # 然后填入密钥
```

网页界面的「配图密钥配置」面板可以直接填，不用手动编辑文件。各接口申请地址与限额见 [references/image-providers.md](references/image-providers.md)。

### 第四步：生成与校验

```bash
python huayu_hanako_ppt.py --content 我的汇报.json --theme morandi_blue
```

脚本会先做内容校验（页数范围、页码连续、图表字段完整性），有问题时**逐页指出改哪里**，通过后才开始渲染。生成结束会汇总：产物路径、页数、配图数量、失败的关键词与原因。

## 能力边界

| 项 | 上限 | 说明 |
|---|---|---|
| 输入文稿长度 | 200,000 字 | 超出需拆分 |
| 幻灯片页数 | 8–40 页 | 学术汇报推荐 25–30 页 |
| 单页要点数 | 8 条 | 超出会溢出版面，建议拆页 |
| 单页配图数 | 2 张 |  |
| 单张图片下载 | 20 MB | 超大图直接拒收 |
| 配图接口 | 6 个 | 全部失败时按无图版式渲染，不影响 PPT 完整性 |

**做不到的事**：
- 不能保证每张配图都精准匹配学术语境（关键词决定结果）
- 不能替你把研究内容想出来——它只负责把你的文本排成 PPT
- 配图来自公网图库，**用于公开发布前请自行核实版权与授权**
- 需要 Python 3.8+ 环境

## 输出规范

产物是一个 `.pptx` 文件，页型分布按内容自动决定：

| 页型 | 布局特点 |
|---|---|
| 封面 | 大标题 + 副标题 + 左侧装饰竖线 + 底部横线 + 演示信息 + 右侧半透明配图 |
| 目录 | 编号列表 |
| 章节过渡 | 章节编号 + 大标题 + 左侧色带 + 右侧半透明配图 |
| 正文 | 顶部主题色条 + 标题栏浅色底 + 装饰线 + 要点/引用/代码块 + 配图 + 页码 |
| 数据 | 左栏编号数据点 + 右栏图表（图表失败自动降级为表格） |
| 参考文献 | 小字号列表 |
| 致谢 | 居中大字 + 装饰色块 + 上下装饰线 |

内容元素渲染样式：主题色圆点无序列表、编号圆圈有序列表、左侧竖条引用块、深色等宽代码块、表头主题色表格。

## 自动图表

表格数据会自动转成饼图 / 柱状图 / 折线图。`chart_type` 留空时按数据形态推断：含「占比/比例」等字样优先饼图，数值总和在 80–120 之间判为占比数据，否则默认柱状图。数值支持 `45%`、`¥250`、`1,200`、`1200亿` 等格式（`亿`/`万` 会按量级换算）。

饼图只展示一个数值系列——传多个系列时会保留第一个并打印警告，不会静默丢数据。

## 常见问题

完整的踩坑库在 [references/faq.md](references/faq.md)，错误码对照表在 [references/troubleshooting.md](references/troubleshooting.md)。最高频的三个：

**Q: 配图全部失败，PPT 还能出来吗？**
能。配图是增值项，失败时该页按无图版式渲染，生成结束后会列出每个失败关键词的原因。

**Q: 一个密钥都没配，能用吗？**
能。Bing 与 Wikimedia 免密钥；加 `--skip-images` 则完全离线。

**Q: 主题色圆点没变色 / 图表不见了？**
这两类问题在 v1.0.1 是真实 bug（项目符号 XML 结构非法、饼图多系列丢数据），v2.0.0 已修复。若你用的是旧版本，请升级。

## 文件结构

```
huayu-hanako-ppt/
├── SKILL.md                   ← 本文件
├── huayu_hanako_ppt.py        ← 命令行入口（含导入期依赖检查）
├── start_ui.py                ← 网页界面入口
├── CHANGELOG.md               ← 更新记录
├── README.md                  ← 快速上手
├── .env.example               ← 密钥配置模板（复制为 .env 使用）
├── ppt_skill/                 ← 生成引擎（模块化）
│   ├── __init__.py            包入口与版本号
│   ├── config.py              密钥/.env/主题/输出配置
│   ├── models.py              内容数据结构
│   ├── errors.py              错误五分类与退出码
│   ├── text_utils.py          数值解析/文件名/图表推断
│   ├── outline.py             文稿 → 页面大纲
│   ├── content_source.py      外部 JSON/YAML 加载
│   ├── pipeline.py            编排 + 内容校验
│   ├── cli.py                 命令行 + 错误五分类
│   ├── ui_server.py           网页服务端
│   ├── scraping/              六个配图来源（providers/downloader）
│   └── rendering/             排版、装饰、图表（base/content/charts/slides）
├── assets/
│   ├── ui.html                网页界面
│   ├── examples/              分级样例（8/15/30 页）
│   ├── templates/             四套空白学术模板
│   └── sample_output/         样例成品 pptx
├── evals/trigger_cases.json   触发用例（正例/负例/近邻）
├── scripts/check_pipeline.py  数据流与门禁自测
└── references/                FAQ、排错、配图接口、模板字段说明
```

## 给 AI 协作者的工作流

当用户带着文稿来而不指定路径时，按这个顺序走：

1. 先读文稿，判断页数规模（8 页以下信息量不足，40 页以上建议拆分）
2. 用 `ppt_skill.outline.build_outline(text, target_pages)` 生成初版大纲，**把大纲给用户确认**
3. 用户确认后，让用户选主题；默认 `morandi_blue`
4. 询问是否需要配图（要则引导到网页面板配密钥，或 `--skip-images` 跳过）
5. 生成后汇报：产物路径、页数、配图数、失败关键词

不要把大纲直接变成最终 PPT——学术内容的分页取舍应该由用户拍板。

内容文件的完整字段说明见 [references/templates.md](references/templates.md)；生成失败时的错误码与排查步骤见 [references/troubleshooting.md](references/troubleshooting.md)。
