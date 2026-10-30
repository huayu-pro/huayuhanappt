# 内容文件字段说明

内容文件是 JSON（或 YAML），由 `--content` 传入，也是网页界面内部传递的格式。
不写任何代码，只改这个文件就能控制 PPT 的每一页。

## 顶层结构

```json
{
  "meta": { ... },
  "slides": [ { ... }, { ... } ]
}
```

- `meta` 可选，控制封面与致谢页的演示信息
- `slides` 必需，数组的每一项就是一页

## meta 字段

| 字段 | 说明 | 缺省 |
|---|---|---|
| `title` | 演示标题，也用作默认输出文件名 | 第一页标题 |
| `presenter` | 汇报人 | 空（不显示） |
| `institution` | 院校 / 单位 | 空 |
| `date` | 日期 | 空 |
| `template` | 模板标识，仅备注用 | 空 |

## slides 每一项的字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `page_num` | 否 | 页码。**全部省略时脚本按顺序自动编号**，推荐这样做 |
| `slide_type` | 是 | 页型：`title` / `section` / `content` / `data` / `reference` / `thank` |
| `title` | 是 | 页标题 |
| `subtitle` | 否 | 副标题，用于封面、章节页、致谢页 |
| `bullet_points` | 否 | 要点数组，每条建议 30 字以内，单页不超过 8 条 |
| `table_data` | 否 | 表格数据，见下 |
| `chart_type` | 否 | `pie` / `bar` / `line`，**留空则按数据自动推断** |
| `quote_text` | 否 | 引用块文字，会渲染成竖条 + 浅底 + 斜体 |
| `code_block` | 否 | 代码块，深色底 + 等宽字体 |
| `image_keywords` | 否 | 配图搜索关键词，英文通常比中文命中率高 |

## table_data 结构

```json
"table_data": {
  "headers": ["阶段", "比重"],
  "rows": [
    ["经济不平等", "45"],
    ["政治不平等", "35"],
    ["专制暴政", "20"]
  ]
}
```

- `headers` 是表头，第一列之后应当是数值列
- `rows` 的**每一行**第一列是分类标签，其余列是数值
- 所有行都会进入图表，第一行不会被当成表头吞掉
- 某一列只要有任何一个单元格解析不出数值，整列放弃（不会把缺失伪装成 0）

## 六种页型的典型用法

**封面** `title`：只写 `title` + `subtitle`，演示信息由 meta 提供。

**章节过渡** `section`：`title` 写「一、研究背景」这类带编号的标题，编号会自动提取成小节标签；`subtitle` 写一句话点题。

**正文** `content`：`bullet_points` 为主，可叠加 `quote_text`、`code_block`、`table_data`，三者会同时渲染。

**数据** `data`：左侧编号列表 + 右侧图表。`bullet_points` 是左侧要点，`table_data` 是图表数据。

**参考文献** `reference`：把文献逐条写进 `bullet_points`。

**致谢** `thank`：`title` 写「感谢聆听」，`subtitle` 写「欢迎批评指正」。

## 从模板开始改

四套空白模板都在 `assets/templates/`：把括号里的提示文字换成你的内容，
不需要的页整段删掉，不够就复制一个 `content` 块改字段。
推荐从最接近你场景的那套开始：

- 毕业答辩 → `defense.json`（23 页，含文献综述、研究设计、稳健性检验）
- 课题汇报 → `project_report.json`（19 页，含进度对照表、阶段成果）
- 期刊分享 → `journal_club.json`（18 页，含论文概览、识别策略、批评讨论）
- 其他 → `generic.json`（13 页骨架）

## 校验规则

生成前会逐页检查，有问题会告诉你改哪一页：

- 总页数在 8–40 之间
- 必须有且仅有一页 `title` 和一页 `thank`
- 页码从 1 连续编号（省略 `page_num` 时自动满足）
- `slide_type`、`chart_type` 取值合法
- 填了 `chart_type` 就必须有 `table_data`
- 单页 `bullet_points` 不超过 8 条
- `content` 页至少要有一个内容元素（要点/引用/代码/表格）
