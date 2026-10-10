# 服务部署与模型权限

Go engine 管理时间计划与 task_runs；news-claw.service 托管常驻进程。旧网站 service 保留执行入口，每日博客直接运行 workflows.daily_blog。

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
