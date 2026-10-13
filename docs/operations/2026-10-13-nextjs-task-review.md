# 2026-10-13 网站迁移后的存量任务复核

## 实际变化

网站仓库已发布 `cc18a61`：Nginx 的公开上游从 8000 改为 3000，`quant-next-web.service` 运行 Next.js 原生页面；`quant-web.service` 继续运行 Python 内容/API 服务。Python 对已迁移的 HTML 地址只提供公开前端重定向，不再维护第二套页面。Nginx 禁止公开访问 `/internal/`，Next.js 用服务环境中的共享 token 读取本机内容桥接。

网站的 `deployment/NEXTJS.md` 要求前端在独立候选目录构建和 smoke 验证，保留旧 chunks，停止前端后原子安装 `.next`、检查文件权限，再启动并核验。直接覆盖运行中的构建或仅将 Nginx 改回 8000 均不符合当前发布/回退流程。

## 配置修正

- 全部 12 项任务和 6 类模板更新 `website_runtime` 与 `website_delivery`，明确前端、内容服务和入口的职责。
- 本地线索与待审稿不直接发布网页。已审核博客和运行时快照继续使用原路径，由内容服务校验后交给 Next.js；不重启或构建前端。
- Python 内容代码更新使用 `reload-content`；已安装的 Next.js 构建重启使用 `restart-frontend`；Nginx 配置使用 `reload-proxy`。旧 `reload-application` 被拒绝，防止误操作整个网站。
- JSON 显式包含三层服务、端口、命令、就绪等待时间、候选 build / smoke 示例与发布步骤；候选目录需由操作者指定，维护脚本不自动执行构建或替换产物。
- 检查 Python 健康状态、Next.js 实际博客 SSR 和本机 HTTPS 的同一页面；仅检查 Python 健康接口不能证明前端可用。请求不访问外部数据源，不读取或输出共享 token。
- 原迁移脚本改为合并已有 workflow，保留网站职责、模型和交付设置，不重新生成并覆盖它们。常规调优使用 make init，无需再次执行初次迁移。
- 任务 ID、启用状态、调度时间、随机延迟、实际执行命令、来源预算、模型参数与原有输出保持原设置。SQLite 已同步，仍为 12 项定义、10 项启用，没有新增定时重启。

## 兼容发布路径修复

真实检查发现旧 Markdown 地址经 Next.js 返回 500。Next.js 日志记录 `ERR_INVALID_URL`，输入为后端返回的相对 Location。将 Python Markdown 别名路由的 301 Location 改为公开完整地址；仅热重载 Python 内容服务，没有修改或重建运行中的 Next.js 产物。

修复后，3000 和 Nginx HTTPS 两个入口均验证：旧网页地址 308、旧 Markdown 地址 301（完整规范地址且保留 lang=en）、规范 Markdown 200。原运行时正文、slug 别名和发布时间未修改。

## 验证结果

- 17 项维护测试通过，包括三层服务、前端独立重启、旧动作拒绝、候选构建规则、受限就绪等待和原迁移配置保留。
- 36 项每日博客测试通过。旧 Flask HTML 渲染断言改为认证内容桥接断言，覆盖中英文正文、未认证拒绝、证明信息不进入前端数据和发布后目录更新。
- 网站运行时博客 8 项测试通过，覆盖完整规范地址的 Markdown 跳转。
- 三层真实检查返回 200。Python 内容服务热重载后检查仍通过；Next.js 重启仅预览。
- 所有任务 JSON 与 SQLite config_json 一致；quick_check 为 ok，foreign_key_check 无异常。

日志保存在忽略目录 `data/runs/nextjs-task-review-2026-10-13/`。原始内容、模型日志、凭据、前端构建产物和网站仓库其他未提交改动不进入本次提交。
