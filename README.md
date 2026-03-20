# autoPapers

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](./pyproject.toml)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)
[![Provider](https://img.shields.io/badge/LLM-MiniMax-orange)](./config.example.yaml)
[![Obsidian](https://img.shields.io/badge/Output-Obsidian-7C3AED)](https://obsidian.md/)

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

### 先决条件

- Python `3.12+`
- 可用的 `pip`
- 一个可写的 Obsidian 目录
- 一个可用的 `MiniMax` 或 `OpenAI` API key

### 新设备首次部署

1. 克隆仓库并进入目录：

```bash
git clone <your-repo-url>
cd autoPapers
```

2. 创建虚拟环境并安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -U pip
python3 -m pip install -e .
```

3. 直接启动配置向导：

```bash
python3 -m autopapers.cli --settings --config config.yaml
```

建议首次部署优先走向导，而不是手动编辑 `config.yaml`。向导会：

- 生成或更新 `config.yaml`
- 引导你填写 `obsidian_root`、时区、计划时间、抓取来源和关键词
- 选择 `MiniMax` / `OpenAI` / `rule_based`
- 按供应商自动带出推荐的 `model`、`api_key_env`、`base_url`
- 直接把 API key 写入与 `config.yaml` 同目录的 `.env`
- 在最终校验失败时，只重问出错字段
- 以事务方式提交 `config.yaml` 和 `.env`

4. 首次填写时建议这样配置：

- `obsidian_root`：改成你机器上的真实 Obsidian 目录
- `llm.provider`：先选你当前有 key 的供应商
- `sources.openreview.enabled`：首次部署建议先设成 `false`
- `sources.arxiv.queries[].max_results`：先用 `2` 或 `3` 做低成本试运行

原因：

- 某些 OpenReview invitation 可能返回 `403`
- 先确保 `arXiv -> LLM -> Obsidian` 主链路能跑通，再逐步打开额外来源
- 小抓取量更容易快速验证配置是否正确

5. 完成向导后，先做环境检查：

```bash
python3 -m autopapers.cli doctor --config config.yaml
```

6. 建议先做一次低成本试运行，例如补抓最近 1 到 3 天：

```bash
python3 -m autopapers.cli backfill --config config.yaml --days 1
```

7. 确认输出正常后，再切换到日常运行：

```bash
python3 -m autopapers.cli run-daily --config config.yaml
```

如果你使用虚拟环境，后续执行命令前也需要先：

source .venv/bin/activate
```

### 手动配置方式

如果你不想走交互式向导，也可以手动准备配置：

```bash
cp config.example.yaml config.yaml
echo 'MINIMAX_API_KEY=你的_key' > .env
```

`config.example.yaml` 是一个偏保守的试运行模板：

- 默认只开 `arXiv`
- 默认关闭 `OpenReview`
- 默认只抓一个小查询，`max_results: 2`

然后手动修改 `config.yaml` 里的 `obsidian_root`，再执行：

```bash
python3 -m autopapers.cli doctor --config config.yaml
```

## 配置参数说明

### 1. 路径与时间

- `obsidian_root`：Obsidian 论文库根目录
- `literature_dir`：单篇论文笔记目录，通常是 `01 Literature`
- `concepts_dir`：概念卡目录，通常是 `02 Concepts`
- `state_dir`：本地状态目录
- `timezone`：时区，例如 `Asia/Shanghai`
- `schedule`：计划执行时间。当前主要是说明字段，真正自动执行时间以 `cron` 为准
- `incremental_overlap_hours`：`run-daily` 重新回看的小时数，用来覆盖源站延迟入库或边界时间漏抓

部署到新设备时，最容易出错的是 `obsidian_root`。  
这个值必须是你的本机真实目录，例如：

```yaml
obsidian_root: /Users/yourname/Documents/Obsidian/Papers
```

### 2. 大模型配置

- `llm.provider`：支持 `minimax`、`openai`、`rule_based`
- `llm.model`：模型名。当前推荐 MiniMax 使用 `MiniMax-M2.5`
- `llm.api_key_env`：从环境变量读取 key，例如 `MINIMAX_API_KEY`
- `llm.base_url`：兼容接口地址
- `llm.timeout_seconds`：单次模型调用超时秒数

如果你使用 `--settings`，向导会先让你选供应商，再引导你决定是否把 API key 写入 `.env`。

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

- 这表示每个查询或 venue 的总抓取预算，不再局限于单页
- 抓取器会自动分页，直到拿满预算或遇到时间窗口外的旧结果
- 这只是“候选抓取上限”，不是最终一定写入的篇数
- 最终写入量还会受去重、关键词过滤、历史状态影响
- `run-daily` 会按 `incremental_overlap_hours` 回看一段时间，然后靠状态去重，避免严格边界漏抓
- 如果你开了 3 个 arXiv 查询，分别是 `20 / 20 / 20`，那每次任务最多会尝试处理 60 篇候选论文；如果进一步调到 `60 / 60 / 60`，则会明显增加运行时长和 LLM 成本

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

如果你的目标是“每天尽量不要漏掉符合关键词的论文”，当前更推荐这类“宽抓取 + 关键词收敛”策略：

- `multimodal-core`：按 `cs.CV / cs.CL / cs.AI` 抓 `vision-language`、`VLM`、`VLA`
- `vision-3d`：按 `cs.CV / cs.RO` 抓 `gaussian splatting`、`3DGS`、`NeRF`、`3d reconstruction`
- `robotics-agents`：按 `cs.RO / cs.AI / cs.CL` 抓 `embodied`、`robot manipulation`、`video world model`

对应思路：

- source query 先放宽，避免论文根本进不了候选集
- 每个 query 用较高的 `max_results`，再靠分页抓取把预算拿满
- `include_keywords` 和 `exclude_keywords` 负责真正的收敛
- `run-daily` 通过 `incremental_overlap_hours` 回看重叠窗口，降低边界漏抓

## 如何调参

### 如果每天抓到太多论文

- 降低 `max_results`，例如从 `60 / 60 / 60` 调到 `20 / 20 / 20`
- 删除宽词，比如 `multimodal`、`embodied`、`video understanding`
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
  include_keywords: ["vision-language-action", "gaussian splatting", "nerf", "robot manipulation"]
  exclude_keywords: ["survey", "benchmark", "leaderboard"]

sources:
  arxiv:
    enabled: true
    queries:
      - name: multimodal-core
        search_query: (cat:cs.CV OR cat:cs.CL OR cat:cs.AI) AND (all:"vision-language" OR all:vlm OR all:"vision-language-action")
        max_results: 20
      - name: vision-3d
        search_query: (cat:cs.CV OR cat:cs.RO) AND (all:"gaussian splatting" OR all:3DGS OR all:nerf OR all:"3d reconstruction")
        max_results: 20
      - name: robotics-agents
        search_query: (cat:cs.RO OR cat:cs.AI OR cat:cs.CL) AND (all:"vision-language-action" OR all:embodied OR all:"robot manipulation")
        max_results: 20
  openreview:
    enabled: false
```

### 示例 2：高召回模式

```yaml
incremental_overlap_hours: 12

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
0 8 * * * /usr/bin/flock -n /tmp/autopapers.lock /bin/bash -lc 'cd /path/to/autoPapers && /usr/bin/python3 -m autopapers.cli run-daily --config /path/to/autoPapers/config.yaml >> /path/to/autoPapers/autopapers.log 2>&1'
```

含义：

- 每天早上 `08:00` 执行
- 使用 `flock` 防止重复并发
- 日志追加到 `autopapers.log`

注意：

- 你必须把 `/path/to/autoPapers` 替换成自己机器上的真实绝对路径
- 如果你使用虚拟环境，建议改成虚拟环境里的 Python，例如：
- `backfill` 和 `run-daily` 都会更新状态文件；日常定时任务建议只用 `run-daily`

```cron
CRON_TZ=Asia/Shanghai
0 8 * * * /usr/bin/flock -n /tmp/autopapers.lock /bin/bash -lc 'cd /path/to/autoPapers && /path/to/autoPapers/.venv/bin/python -m autopapers.cli run-daily --config /path/to/autoPapers/config.yaml >> /path/to/autoPapers/autopapers.log 2>&1'
```

## 常用命令

```bash
python3 -m autopapers.cli --settings --config config.yaml
python3 -m autopapers.cli doctor --config config.yaml
python3 -m autopapers.cli backfill --config config.yaml --days 3
python3 -m autopapers.cli run-daily --config config.yaml
```

## 配置向导

如果你不想手动编辑 YAML，可以直接启动交互式配置向导：

```bash
python3 -m autopapers.cli --settings --config config.yaml
```

新设备首次部署时，推荐优先使用这个向导。

向导会：

- 读取现有 `config.yaml` 作为默认值
- 逐项提示你输入路径、时区、计划时间、模型、供应商、API key、关键词和数据源参数
- 在写入前校验配置格式，并在失败时定向重问对应字段
- 当供应商是 `openai` 或 `minimax` 时，可直接写入 `.env`
- 以事务方式暂存并提交 `config.yaml` 和 `.env`
- 如果提交中途失败，会自动回滚到旧版本

补充说明：

- 输入过程中不会实时改文件；改动先保存在内存中
- 只有最终校验通过后，才会统一提交到磁盘
- 正常异常路径下，`config.yaml` 和 `.env` 会一起提交或一起回滚

## 排错

### `Missing environment variable: MINIMAX_API_KEY`

- 检查 `.env` 是否和 `config.yaml` 同目录
- 检查变量名是否真的是 `MINIMAX_API_KEY`

### `OpenReview` 返回 403

- 当前 venue 可能是私有 invitation
- 暂时把 `openreview.enabled` 设为 `false`

### `No module named autopapers` 或缺少依赖

- 通常说明你还没执行 `python3 -m pip install -e .`
- 或者当前 shell 没有激活正确的虚拟环境

### `Missing obsidian_root`

- 说明 `config.yaml` 里的 `obsidian_root` 不存在
- 先改成你机器上的真实 Obsidian 目录，再执行 `doctor`

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
