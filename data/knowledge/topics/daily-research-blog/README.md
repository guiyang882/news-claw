# 每日研究博客索引

任务 `daily-blog-agy-codex` 先由 Codex 从本地缓存生成候选题和约 20 分钟阅读的大纲，再由 Gemini 按大纲写稿，经 Codex 事实复核、humanizer 修订和最终复核后发布到网站。

发布成功后，`summaries/YYYY-MM-DD.json` 保存中英文标题与摘要、文章 slug、来源 URL、文章和资料包的 SHA256，以及 humanizer skill 的 SHA256。同时保存所选题目、大纲哈希和正文阅读量估算。SQLite 的 `artifacts` 表登记同一份索引。

正文与发布清单位于 `/mnt/quant-state/quant-web/blog`。资料包、候选题、大纲、模型响应和复核过程保存在忽略目录 `data/runs/<run_id>/`；大纲可直接查看其中的 `blog-outline.md`。索引中的来源日期及材料边界以对应资料包为准；没有通过复核的候选稿不进入本目录。

配置和运行说明见 [每日博客](../../../../docs/daily-blog.md)。
