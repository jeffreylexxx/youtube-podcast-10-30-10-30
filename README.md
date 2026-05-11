# 华语 YouTube 长视频播客对话节目研究仪表盘

这是一个可以直接上传到 GitHub 的静态数据项目，用来跟踪中文语言为主、面向华人群体的 YouTube 长视频播客/访谈/圆桌节目。页面会展示频道规模、视频播放、播放增长、爆款视频、时长分布、话题分类、嘉宾行业分布、P50/P90、方差、散点图、曲线图和你的频道竞争力建议。

## 研究对象

项目默认关注 10 分钟以上、以视频形式出现、两人或多人坐着谈话为主的中文播客节目。采集脚本会优先从 `config/research_config.json` 的种子频道出发，再通过关键词发现新的相关长视频。

默认种子包括出海相对论、半球观察、蜉蝣天地 Meanders、Dashu Mandarin Podcast、Money Manta、Chinese Podcast With Shenglan、Stan 的聊政事兒頻道、西雅图中文电台时事三人谈等。你可以继续补充频道名、YouTube handle 或搜索词。

## 本地运行

```bash
python scripts/update_data.py --force-demo
python -m http.server 8000 --directory site
```

然后打开 `http://localhost:8000`。

Windows PowerShell 也可以直接运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\serve_local.ps1
```

如果你本地有 YouTube Data API key：

```bash
set YOUTUBE_API_KEY=你的key
python scripts/update_data.py --write-history
python -m http.server 8000 --directory site
```

PowerShell 可用：

```powershell
$env:YOUTUBE_API_KEY="你的key"
python scripts/update_data.py --write-history
python -m http.server 8000 --directory site
```

## 部署到 GitHub Pages

1. 新建 GitHub 仓库并上传本项目。
2. 在仓库 `Settings -> Secrets and variables -> Actions` 添加 secret：`YOUTUBE_API_KEY`。
3. 在 `Settings -> Pages` 中选择 `GitHub Actions` 作为发布源。
4. 打开 `Actions`，手动运行一次 `Update YouTube podcast dashboard`。
5. 之后工作流会每天 UTC 18:30 自动执行一次。按北京时间约为次日 02:30。

如果没有配置 `YOUTUBE_API_KEY`，工作流仍会生成带有明确标注的 demo 快照，页面结构可正常预览，但不代表真实最新数据。

## 数据方法

脚本使用 YouTube Data API：

- `search.list`：发现频道和长视频。
- `channels.list`：获取频道订阅数、总播放、视频数。
- `videos.list`：获取视频播放、点赞、评论和 ISO 8601 时长。

筛选逻辑：

- 只保留 10 分钟以上视频。
- 标题或简介包含“播客、podcast、对谈、对话、访谈、采访、圆桌、聊天、interview”等信号。
- 话题和嘉宾行业用 `config/research_config.json` 中的关键词分类。
- 爆款视频定义为样本播放 P90 以上，或高于本频道样本中位播放 3 倍。
- 增长数据来自最近两次 `site/data/history/*.json` 快照对比。

## 重要限制

YouTube 官方 API 不直接判断“是否一直坐着谈话”，也不提供所有频道的历史订阅曲线。因此本项目把“坐谈类播客”作为可迭代的启发式分类：先通过标题、描述、频道种子和长视频时长过滤，再由你逐步补充或剔除频道。若需要更高精度，可以把人工标注字段加入配置文件，或接入字幕/画面识别流程。

## 主要文件

- `site/index.html`：GitHub Pages 页面。
- `site/app.js`：图表和页面渲染。
- `site/styles.css`：仪表盘样式。
- `scripts/update_data.py`：采集、分类、统计、生成快照。
- `config/research_config.json`：种子频道、搜索词、分类体系和你的频道定位。
- `.github/workflows/update-dashboard.yml`：每日自动更新和部署。

## 参考来源

- [YouTube Data API search.list](https://developers.google.com/youtube/v3/docs/search/list)
- [YouTube Data API quota cost](https://developers.google.cn/youtube/v3/determine_quota_cost?hl=en)
- [GitHub Pages custom workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
