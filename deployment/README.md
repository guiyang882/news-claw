# 服务部署与模型权限

Go engine 管理时间计划与 task_runs；news-claw.service 托管常驻进程。旧网站 service 保留执行入口，每日博客直接运行 workflows.daily_blog。 常规任务调优运行 make init；初次迁移脚本不用于重载网站或重新启用已停用的博客流程。

网站已迁移到 Nginx → Next.js（quant-next-web，3000）→ Python 内容/API 服务（quant-web，8000）。旧采集 service 是内容任务的执行入口，不能作为整个网站的重启入口。内容发布仍只原子更新本地状态；前端构建、内容服务重载与入口重载按 [网站协议](../docs/website-workflow.md#网站检查与分别维护) 分别处理。网站源码与完整构建切换说明位于 stocks-quant 的 `deployment/NEXTJS.md`；不在运行中的前端目录直接构建，不将内部桥接凭据写入任务配置或日志。

## 本机已部署的 full 权限

2026-10-10 用户明确要求所有 Codex 和 agy 调用使用 full 权限，不因交互授权中断任务。

- Codex：--dangerously-bypass-approvals-and-sandbox。
- agy：--dangerously-skip-permissions；纯写稿另用 --disable-slash-commands，避免展开规划指令。
- root 的 Codex 默认配置：approval_policy=never、sandbox_mode=danger-full-access。
- engine 及旧模型 service 的 zz-full-access.conf：ProtectHome=false、ProtectSystem=false、PrivateTmp=false、NoNewPrivileges=false，并清除 bind/read-write 路径限制。

[news-claw-full-access.conf](news-claw-full-access.conf) 已安装到 /etc/systemd/system/news-claw.service.d/zz-full-access.conf，按文件名字母顺序排在已有 agy.conf、blog.conf 之后。旧模型 service 同样安装此覆盖配置。Go 代码无需权限专用分支。

```bash
mkdir -p /etc/systemd/system/news-claw.service.d
cp deployment/news-claw-full-access.conf /etc/systemd/system/news-claw.service.d/zz-full-access.conf
systemctl daemon-reload
systemctl restart news-claw.service
make init
```

重启前等 engine 中当前运行结束。CLI 仍使用原本机登录，不复制凭据。网站五处 Codex 调用及部署覆盖文件保存在 stocks-quant repo；那里同时记录相关专项测试。

## 旧 Codex service 的配置快照

四项活跃 Codex 任务和原博客草稿模板的模型设置已移到 JSON 的 workflow.codex。适配器将本轮队列快照写到 data/runs/service-inputs/&lt;unit&gt;.json（0600），service 通过 [news-claw-codex-input.conf](news-claw-codex-input.conf) 的 NEWS_CLAW_TASK_CONFIG_PATH 读取；不同 service 使用不同文件。缺少覆盖配置时适配器停止，避免静默使用默认参数。Go 调度器无需增加模型专用逻辑。

```bash
for unit in quant-news-analysis quant-tech-history-review quant-company-pulses-review quant-optimus-supply-review quant-blog-compose; do
  mkdir -p "/etc/systemd/system/$unit.service.d"
  cp deployment/news-claw-codex-input.conf "/etc/systemd/system/$unit.service.d/news-claw-input.conf"
done
systemctl daemon-reload
make init
```

%n 由 systemd 展开为完整 service 名。其他机器需调整覆盖文件中的 repo 路径。无需启动旧 timer 或提前调用模型；下轮任务读取同步后的参数。模板与实际任务分别维护，修改模板不会覆盖已启用定义。参数入口见 [网站任务说明](../docs/website-workflow.md#codex-参数配置)。

## agy 安装位置与先前路径映射

/root/.local/bin/agy 是正常安装位置。之前基础 unit 的 ProtectHome=true 会遮住 /root，因此无法直接执行；原因是服务隔离，不是安装路径。原 [news-claw-agy.conf](news-claw-agy.conf) 将二进制和全局配置只读映射，profile/cache 映射为读写；[news-claw-blog.conf](news-claw-blog.conf) 另映射 Codex profile 与博客运行目录。

这两个文件保留为部署选项。当前机器使用 full 覆盖配置，按用户要求不再限制 home、代码目录或模型阶段的文件系统。基础 news-claw.service 保留原定义，当前实际权限以最后加载的覆盖配置为准。

## 本机检查

[check_agy_runtime.py](../scripts/check_agy_runtime.py) 检查程序、设置、登录文件可读及 profile/cache 可写，再执行 agy --help。登录文件仅打开并关闭，不读取或输出内容。该离线检查不保证模型供应方联网可用。

```bash
task_engine_pid=$(systemctl show news-claw.service --property=MainPID --value)
nsenter --target "$task_engine_pid" --mount -- \
  /usr/bin/python3 /mnt/quant/news-claw/scripts/check_agy_runtime.py
systemctl show news-claw.service --property=ProtectHome --property=ProtectSystem
```

脚本的 --require-isolation 用于选择旧路径映射方案的环境，不在本机当前 full 模式下使用。

每日博客使用 stocks-quant/web/.venv 的既有网站依赖。make test-blog 在临时目录验证选题与大纲先于写稿、大纲来源与预算、正文约二十分钟的阅读量、一次纠错与再复核、拒绝时停止、事实与引用校验、哈希、防重复、knowledge 索引和网站双语页面、Feed、Sitemap。供应方状态及实际模型响应由受控试跑另行验证。

频率、模型与输入配置见 [每日博客](../docs/daily-blog.md)。原始材料、各模型响应与诊断日志保存在忽略目录 data/runs/；Git 保存配置、代码、SQLite 索引和精选 knowledge。

## 科技史任务暂停（2026-10-14）

网站已无对应科技史内容入口，按运营者要求暂停 `stocks-quant-tech-history-review`
及其资料主题 `technology-history-stories`；两份配置的 `enabled` 均为 `false`。
运行 `make init` 同步后，Go engine 下次轮询会清除下一次执行时间并取消尚未执行的排队任务。
旧 `quant-tech-history-review.timer` 保持 disabled / inactive，不重新启用。

历史素材、已发布快照、失败记录和来源拒绝熔断保留；本次暂停不表示来源访问已恢复。
其他新闻采集、公司研究与每日博客任务保持原状态。未来恢复前须重新确认网站用途和来源访问条件，
再启用任务与主题配置并运行 `make init`；仍由 news-claw 调度，无需启动旧 timer。
