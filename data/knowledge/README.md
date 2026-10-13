# 主题知识产物

每个主题一个目录：`topics/<topic_id>/`。按 `timeline/`、`logic/`、`inferences/`、`relations/`、`summaries/` 保存有版本的材料，并在数据库 `artifacts` 表登记产物路径、版本和输入指纹。

Gemini → Codex 的主题整理将上述部分合并在一个有引用的 JSON/Markdown 中，保存在各主题的 `summaries/` 下，按输入指纹保留版本。只有校验通过的内容进入此目录；候选稿、原证据包和日志留在 `data/runs/`。博客使用整理结果前核验原证据和校验证明，详见 [主题整理](../../docs/topic-summaries.md)。
