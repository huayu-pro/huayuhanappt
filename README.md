# 华予&Hanako PPT —— 学术全自动PPT生成器

把一段学术文本变成排版完整、带配图和自动图表的 PPTX。**不写代码也能用。**

版本 2.0.0 —— 更新记录见 [CHANGELOG.md](CHANGELOG.md)

## 三十秒上手

```bash
pip install python-pptx requests Pillow
python start_ui.py
```

浏览器会打开本地页面：粘贴文稿 → 预览页面大纲 → 选主题 → 生成 PPT。

不想装依赖？先用命令行确认环境：

```bash
python huayu_hanako_ppt.py --example minimal_8 --skip-images
```

## 三条使用路径

| 路径 | 命令 | 适合 |
|---|---|---|
| 网页界面 | `python start_ui.py` | 不想碰代码（推荐） |
| 命令行 | `python huayu_hanako_ppt.py --content 汇报.json` 或 `--text-file 讲稿.txt` | 脚本化、批量 |
| 样例/模板 | `--example minimal_8` / `--template defense` | 先看效果 |

## 能做什么

- **文稿自动拆分**：粘贴论文或讲稿，按章节标记拆成 8–40 页，`XX 45%` 这类数据自动抽成图表
- **六套主题**：莫兰迪五色 + 商务经典绿，覆盖学术到商务
- **专业排版**：封面竖线、章节色带、标题栏、页码、主题色圆点、编号圆圈、引用竖条、深色代码块、交替行表格
- **自动图表**：饼图 / 柱状图 / 折线图，`chart_type` 留空时按数据形态推断
- **六级配图兜底**：Bing（免密钥）→ Pexels → 百度 → Unsplash → Wikimedia（免密钥）→ Pixabay
- **可视化密钥配置**：网页表单写入本机 `.env`（权限 0600），不经过任何第三方
- **失败可诊断**：五类错误各有固定退出码、中文原因和下一步命令

## 能力边界

| 项 | 上限 |
|---|---|
| 输入文稿 | 200,000 字 |
| 页数 | 8–40（推荐 25–30） |
| 单页要点 | 8 条 |
| 单页配图 | 2 张 |
| 单张图片下载 | 20 MB |
| 配图接口 | 6 个（2 个免密钥） |

一个密钥都不配也能生成——Bing 与 Wikimedia 免密钥，`--skip-images` 则完全离线。
配图来自公网图库，**公开发布前请自行核实版权**。

## 常用命令

```bash
# 列出所有主题
python huayu_hanako_ppt.py --list-themes

# 用自己的内容文件生成，指定主题
python huayu_hanako_ppt.py --content 汇报.json --theme morandi_clay

# 不爬配图（离线、最快）
python huayu_hanako_ppt.py --content 汇报.json --skip-images

# 只校验内容文件，不生成
python huayu_hanako_ppt.py --content 汇报.json --check

# 清掉旧配图再生成
python huayu_hanako_ppt.py --content 汇报.json --clean
```

## 内容文件长什么样

```json
{
  "meta": {
    "title": "数字政府建设的制度逻辑",
    "presenter": "张明",
    "institution": "某大学公共管理学院",
    "date": "2026年10月"
  },
  "slides": [
    {"slide_type": "title", "title": "数字政府建设的制度逻辑",
     "subtitle": "基于三省六市的政策实践考察"},
    {"slide_type": "content", "title": "问题提出",
     "bullet_points": ["要点一", "要点二"]},
    {"slide_type": "data", "title": "制度能力构成",
     "table_data": {"headers": ["维度", "权重"],
                    "rows": [["数据整合", "45"], ["流程再造", "35"]]},
     "chart_type": "pie"}
  ]
}
```

完整字段说明见 [references/templates.md](references/templates.md)。
四套空白模板在 `assets/templates/`，三档样例在 `assets/examples/`。

## 目录结构

```
huayu-hanako-ppt/
├── start_ui.py            网页界面入口
├── huayu_hanako_ppt.py    命令行入口
├── ppt_skill/             生成引擎
│   ├── outline.py          文稿 → 页面大纲
│   ├── errors.py           错误五分类与退出码
│   ├── content_source.py   外部内容加载
│   ├── pipeline.py         编排 + 校验
│   ├── cli.py              命令行 + 错误分类
│   ├── ui_server.py        网页服务端
│   ├── config.py           密钥/主题/输出配置
│   ├── models.py           内容数据结构
│   ├── text_utils.py       数值解析/图表推断
│   ├── scraping/           六个配图来源
│   └── rendering/          排版、装饰、图表
├── assets/
│   ├── ui.html             网页界面
│   ├── examples/           分级样例（8/15/30 页）
│   ├── templates/          四套空白学术模板
│   └── sample_output/      样例成品 pptx
├── references/
│   ├── faq.md              FAQ 踩坑库
│   ├── troubleshooting.md  错误码与排查
│   ├── image-providers.md  配图来源配置
│   └── templates.md        内容文件字段
├── evals/                  触发用例
├── scripts/check_pipeline.py  数据流与门禁自测
└── CHANGELOG.md            更新记录
```

## 排错

命令行用退出码区分失败类型：0 成功、10 配置类、11 输入类、12 配图接口类、13 渲染类、14 超时、1 未预期错误、130 用户取消。网页界面把同样的信息直接显示在页面上。

完整对照表与排查步骤见 [references/troubleshooting.md](references/troubleshooting.md)，
高频问题见 [references/faq.md](references/faq.md)。

## 安全与隐私

- 网页服务只监听 `127.0.0.1`，不向外部发送任何数据
- 密钥只写本机 `.env`（权限 0600），接口响应永不回传密钥值
- `.env` 不在交付文件清单内，但仍不要提交到公开仓库

## 许可

MIT。配图版权归各图库及原作者，使用前请自行核实。
