# 2026-10-12 已发布博客的呈现修订

用户要求删除公开写作工具说明，补充图像、图表、基础强调和参考资料，并将 `daily-research-2026-10-12` 改为主题地址。

## 发布结果

- 规范地址：`https://growthyoung.com/blog/rocket-lab-orders-shareholder-returns-2026-10-12`。
- 旧文章和旧 Markdown 地址通过 301 跳转，保留 `?lang=en`；运行时清单仍只有一篇文章。
- 中英文都删除“编写与复核 / Writing and review”。内部生成与模型复核证明保留，没有生成或冒用人工批准。
- 添加 Electron 发射 CAPSTONE 的 2022 年历史照片：Yourong F. Wang，CC BY-SA 4.0。原始出处、许可和未修改说明显示在图旁；照片不作为 2026 年经营证据。
- 两张对照表区分 Synspective 执行记录、远期协议，以及 Iridium 的融资、交割和整合；两张 Mermaid 图明确表示分析关系和观察条件，未指定固定收款或工程顺序。
- 少量加粗、斜体和下划线突出判断依据；文末列出五个实际使用的来源及记录日期。
- 仍保留截至 2026-10-08 的材料范围、未重新独立核验链接原文的限制、所有原数字和条件。中文 6,814 阅读单位，约 23 分钟；英文 3,821 词，约 20 分钟。

## 调度与审计

通过现有 Go 队列显式执行 `workflows.revise_blog`，没有新增定时器或表，也没有清除每日防重与供应方熔断。

| 运行 ID | 结果 |
| --- | --- |
| `719a58238e5f9b4ccc9f23a1ba9d8233` | 事实和引用通过；humanizer 指出年份范围的标点和重复措辞，停止发布 |
| `a7eccbff18f4a0e882e9fe39ac96ceb1` | 修正上述措辞后，独立最终复核通过并原子替换文章 |

每次显式修订最多调用一次 Codex，没有重新调用 Gemini。失败记录保留；旧元数据与复核证明保存到网站状态目录的 `revisions/`，新证明为 `automation-reviews/rocket-lab-orders-shareholder-returns-2026-10-12.json`。

最终文章 SHA256：`67c131b669f57883d5b1def837fba18b598bb026565c7a85548aeaa9e82c4cf6`。
资料包 SHA256：`dcfc6a1a6db83142c98d7069a2147df529a8e38421e138eb32e07c32077db86c`。

每日任务及模板已增加 `workflow.presentation`；SQLite 同步后恢复普通每日执行命令。下一轮仍为北京时间 2026-10-13 07:30，加 0 至 420 秒随机延迟。发布索引、现有 artifacts 行和经审核的双语 Markdown 归档均已更新。

## 验证

- news-claw 博客工作流 36 项离线测试通过；网站相关博客测试 11 项通过。
- Chromium 检查中英文、1440px 桌面 / 390px 手机、浅色 / 深色主题：两张图均生成 SVG，图片正常载入，表格独立滚动，页面没有横向溢出或 JavaScript 错误；查看截图核对标签与文字布局。
- 重启网站加载渲染代码后，经已有 Caddy HTTPS 入口和有效域名证书检查：中英文 200、旧地址及 Markdown 301、RSS / sitemap / Markdown 200、图片字节与归档一致。
- 公网 Python HTTP 客户端返回 403 后停止该客户端测试；正常 Chromium 浏览器访问 Cloudflare 公网入口返回 200，显示新版文章标题。
- SQLite `quick_check` 为 `ok`，`foreign_key_check` 无异常；Go 调度器和网站服务均正常运行。

日志、稿件、截图和临时浏览器环境保持在忽略的运行目录，没有把 raw 网页、模型执行日志或临时配置提交进 Git。
