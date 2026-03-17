# autoPapers

`autoPapers` 是一个面向 Obsidian 的本地论文抓取工具。它会定时从 `arXiv` / `OpenReview` 拉取新论文，按关键词过滤，调用大模型生成中文结构化笔记，并写入你的知识库。

## 它是怎么工作的

一次完整运行的流程如下：

1. 从配置好的论文源抓取最近时间窗口内的新论文
2. 按标题和来源 ID 去重
3. 用 `include_keywords` / `exclude_keywords` 过滤标题和摘要
4. 调用 `MiniMax` / `OpenAI` / `rule_based` 生成研究笔记
5. 写入 Obsidian 的 `01 Literature` 和 `02 Concepts`
6. 把已处理论文和最近成功时间写入 `.autopapers/state/state.json`

## 项目结构

- `autopapers/cli.py`：命令行入口，提供 `doctor` / `backfill` / `run-daily`
- `autopapers/pipeline.py`：抓取、过滤、去重、生成、写入的总流程
- `autopapers/fetchers/`：`arXiv` 和 `OpenReview` 抓取器
- `autopapers/llm.py`：大模型适配层，目前支持 `minimax`、`openai`、`rule_based`
- `autopapers/obsidian.py`：Markdown 写入逻辑
- `tests/`：单元测试
- `config.yaml`：你的实际运行配置
- `.env`：API key，不进版本控制

## 快速开始

1. 复制配置文件：

```bash
cp config.example.yaml config.yaml
```

2. 在项目根目录创建 `.env`：

```bash
echo 'MINIMAX_API_KEY=你的_key' > .env
```

3. 先做环境检查：

```bash
python3 -m autopapers.cli doctor --config config.yaml
```

4. 补抓最近 3 天：

```bash
python3 -m autopapers.cli backfill --config config.yaml --days 3
```

5. 日常运行：

```bash
python3 -m autopapers.cli run-daily --config config.yaml
```

## 配置参数说明

### 1. 路径与时间

- `obsidian_root`：Obsidian 论文库根目录
- `literature_dir`：单篇论文笔记目录，通常是 `01 Literature`
- `concepts_dir`：概念卡目录，通常是 `02 Concepts`
- `state_dir`：本地状态目录
- `timezone`：时区，例如 `Asia/Shanghai`
- `schedule`：计划执行时间。当前主要是说明字段，真正自动执行时间以 `cron` 为准

### 2. 大模型配置

- `llm.provider`：支持 `minimax`、`openai`、`rule_based`
- `llm.model`：模型名。当前推荐 MiniMax 使用 `MiniMax-M2.5`
- `llm.api_key_env`：从环境变量读取 key，例如 `MINIMAX_API_KEY`
- `llm.base_url`：兼容接口地址
- `llm.timeout_seconds`：单次模型调用超时秒数

### 3. 关键词过滤

- `filters.include_keywords`：只保留标题或摘要里包含这些关键词的论文
- `filters.exclude_keywords`：排除包含这些关键词的论文
- `filters.concepts_max_per_paper`：每篇论文最多生成多少个概念卡

关键点：

- 当前匹配规则是“大小写不敏感的子串匹配”
- 它不是语义检索，也不会自动做同义词扩展
- 如果关键词太宽，会进很多噪声
- 如果关键词太死，会漏掉很多相关论文

例如：

```yaml
filters:
  include_keywords: ["gaussian splatting", "vision-language-action", "vla"]
  exclude_keywords: ["survey", "benchmark"]
  concepts_max_per_paper: 5
```

### 4. 每天抓取多少篇

抓取上限由各个来源自己的参数控制：

- `sources.arxiv.queries[].max_results`
- `sources.openreview.venues[].limit`

注意：

- 这只是“候选抓取上限”，不是最终一定写入的篇数
- 最终写入量还会受去重、关键词过滤、历史状态影响
- 如果你开了 3 个 arXiv 查询，分别是 `4 / 4 / 3`，那每次任务最多会尝试处理 11 篇候选论文

### 5. 论文来源

`arXiv` 使用原生查询语法，例如：

```yaml
sources:
  arxiv:
    enabled: true
    queries:
      - name: multimodal-core
        search_query: all:"vision-language" OR all:vlm OR all:"vision-language-action"
        max_results: 4
```

`OpenReview` 使用 venue invitation，例如：

```yaml
sources:
  openreview:
    enabled: true
    venues:
      - name: iclr-2026
        invitation: ICLR.cc/2026/Conference/-/Submission
        limit: 20
```

如果某个来源当前不可用，可以直接关掉：

```yaml
sources:
  openreview:
    enabled: false
```

## 当前推荐配置策略

如果你的目标是“每天收到少量高相关的多模态 / 3D / Embodied / Alignment 论文”，推荐用现在这类“精选流”配置：

- `multimodal-core`：抓 `vision-language`、`VLM`、`VLA`
- `vision-3d`：抓 `gaussian splatting`、`3DGS`、`NeRF`、`neural rendering`
- `embodied-alignment`：抓 `open x-embodiment`、`preference optimization`、`alignment data synthesis`

对应思路：

- 不再用一个特别宽的 `cs.AI/cs.CL/cs.LG` 大查询
- 改成多个更聚焦的小查询
- 抓取上限控制在 `4 / 4 / 3`
- 用 `exclude_keywords` 去掉 `survey`、`benchmark`、`active matter`、`knots` 这类噪声

## 如何调参

### 如果每天抓到太多论文

- 降低 `max_results`，例如从 `4 / 4 / 3` 调到 `3 / 3 / 2`
- 删除宽词，比如 `alignment`、`preference`、`embodied`
- 增加 `exclude_keywords`

### 如果每天几乎抓不到论文

- 增加每个 query 的 `max_results`
- 给关键词补同义表达，例如同时写 `vision-language-action` 和 `vla`
- 不要只写过长短语，适当加入更常见写法

### 如果抓到了很多噪声论文

- 优先检查 `include_keywords` 里是否有过宽的词
- 再检查 query 是否太宽
- 最后用 `exclude_keywords` 做定点清洗

## 常见配置示例

### 示例 1：多模态 / 3D / Embodied 精选流

```yaml
filters:
  include_keywords: ["vision-language-action", "gaussian splatting", "nerf", "open x-embodiment"]
  exclude_keywords: ["survey", "benchmark"]

sources:
  arxiv:
    enabled: true
    queries:
      - name: multimodal-core
        search_query: all:"vision-language" OR all:vlm OR all:"vision-language-action"
        max_results: 4
      - name: vision-3d
        search_query: all:"gaussian splatting" OR all:3DGS OR all:nerf
        max_results: 4
      - name: embodied-alignment
        search_query: all:"open x-embodiment" OR all:"preference optimization"
        max_results: 3
  openreview:
    enabled: false
```

### 示例 2：高召回模式

```yaml
filters:
  include_keywords: []
  exclude_keywords: []

sources:
  arxiv:
    enabled: true
    queries:
      - name: broad-ai
        search_query: cat:cs.CV OR cat:cs.AI OR cat:cs.CL OR cat:cs.RO
        max_results: 20
```

### 示例 3：低成本试运行

```yaml
sources:
  arxiv:
    enabled: true
    queries:
      - name: test
        search_query: all:"vision-language-action"
        max_results: 2
```

## 自动运行

当前项目已经可以通过 `cron` 自动执行。示例：

```cron
CRON_TZ=Asia/Shanghai
0 8 * * * /usr/bin/flock -n /tmp/autopapers.lock /bin/bash -lc 'cd /home/scotterrzen/autoPapers && /usr/bin/python3 -m autopapers.cli run-daily --config /home/scotterrzen/autoPapers/config.yaml >> /home/scotterrzen/autoPapers/autopapers.log 2>&1'
```

含义：

- 每天早上 `08:00` 执行
- 使用 `flock` 防止重复并发
- 日志追加到 `autopapers.log`

## 常用命令

```bash
python3 -m autopapers.cli doctor --config config.yaml
python3 -m autopapers.cli backfill --config config.yaml --days 3
python3 -m autopapers.cli run-daily --config config.yaml
```

## 排错

### `Missing environment variable: MINIMAX_API_KEY`

- 检查 `.env` 是否和 `config.yaml` 同目录
- 检查变量名是否真的是 `MINIMAX_API_KEY`

### `OpenReview` 返回 403

- 当前 venue 可能是私有 invitation
- 暂时把 `openreview.enabled` 设为 `false`

### 抓取很慢

- 说明 query 太多或 `max_results` 太高
- 也可能是 `timeout_seconds` 偏大
- 先把抓取量压下来，再逐步放开

### 一个方向总是抓不到

- 优先检查 query 本身是否覆盖该方向
- 再检查关键词是不是只写了很少见的表达

## 说明

- 如果 `.env` 与 `config.yaml` 同目录，程序会自动加载其中的环境变量
- MiniMax 当前使用 OpenAI 兼容的 `chat/completions` 接口
- 相对路径会相对于 `config.yaml` 所在目录解析
