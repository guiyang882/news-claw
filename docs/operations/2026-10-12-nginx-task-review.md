# 2026-10-12 Nginx 网站维护配置复核

用户将网站入口迁移到 Nginx 后，要求检查网站重启与发布任务并同步调整。

## 现状

本机 Nginx 正在监听 80/443，Caddy 已停用。`quant-web.service` 中的 Gunicorn 继续监听 127.0.0.1:8000；`news-claw.service` 正常运行。网站仓库已提交 Nginx 配置、Certbot 续期钩子与迁移文档。

news-claw 当前 12 项任务定义、10 项启用，没有独立的定时网站重启任务，也没有执行 Caddy 重启命令的任务。每日博客和新闻快照使用运行时文件接口，发布本身无需服务重启。

## 调整

- 每日博客、原批准发布任务及对应模板增加 `workflow.website_runtime`，明确 Nginx 入口、Gunicorn 服务、内容更新无重启、本机健康接口及分层命令。
- 新增 `workflows.website_maintenance`，从指定任务 JSON 或 Go 队列配置快照读取这些字段。支持只检查、显式应用热重载和显式入口热重载，结果兼容已有 result.json / task_runs 协议。
- 应用热重载使用 HUP，仅发送给 Gunicorn 主进程；通过本机安装的 Gunicorn 源码确认其加载配置、启动新 worker 并正常关闭旧 worker 的处理逻辑。
- Nginx 热重载先校验配置，再调用 `systemctl reload nginx.service`。执行前后检查本机 HTTP/HTTPS 与服务状态；失败停止，不循环重启或自动回退 Caddy。
- HTTPS 检查连接回环地址，保留真实域名 SNI 与证书校验，不访问公网或新增外部请求。
- 新增维护模板，默认关闭、只执行健康检查；未同步为新任务，没有新增定时器。只有明确选择重载动作并带 `--execute` 才执行变更。
- 已通过 `make init` 将相关现有任务配置同步到 SQLite。原执行入口、启用状态、模型参数、频率与随机延迟保持原设置。

## 验证

- 9 项维护专项测试通过：预览无命令/请求、应用与入口动作分离、配置和健康失败阻止重载、证书验证、本机连接、无效健康结果拒绝。
- 36 项既有每日博客工作流测试通过。
- 执行了一次 Nginx 配置检查及热重载，前后应用与入口健康接口均返回 200，响应服务分别为 gunicorn 和 nginx。
- 应用重载命令进行了预览检查；本次无需加载网站应用代码，因此没有发送 HUP。
- `bin/news-claw check` 通过；SQLite quick_check 为 ok，foreign_key_check 无异常，仍为 12 项定义、10 项启用。

命令输出及测试日志保存在忽略目录 `data/runs/website-maintenance-2026-10-12/`。网站仓库的未提交策略与部署改动未纳入本次提交。
