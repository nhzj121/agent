# M2 / M3：内存研究队列与并发配额

当前后端采用单进程内存管理，同时执行 **3 个研究主题**，最多 **7 个等待**。
启动时只运行一个 Uvicorn worker。等待项按提交顺序进入，容量满时返回 429，
不会创建额外研究或覆盖已有研究。取消中的研究完成清理前仍占运行位置。

每项研究最多同时执行 **5 个子任务**；额外子任务保留并在该研究内部排队。
全局 LLM 请求、搜索工具调用分别最多 **15 个并发**。模型配额覆盖完整响应流，
搜索配额覆盖完整工具调用（包括内部回退和抓取）；等待配额时可以取消。
这些限制是并发数量限制，不是每分钟请求/Token 配额，也不保证上游 API 不会限流。

配置从环境变量读取，默认值如下，修改后重启后端生效：

| 环境变量 | 默认值 |
| --- | --- |
| `MAX_CONCURRENT_RESEARCHES` | 3 |
| `MAX_PENDING_RESEARCHES` | 7 |
| `MAX_TASK_WORKERS` | 5 |
| `MAX_LLM_CONCURRENCY` | 15 |
| `MAX_SEARCH_CONCURRENCY` | 15 |

新研究的笔记位于 `<NOTES_WORKSPACE>/<research_id>/`，不迁移或读取旧的共享目录笔记。
同研究的笔记操作加锁，索引与 Markdown 写入不会互相覆盖；笔记 ID 不能跨目录访问。
搜索 SDK 客户端按工作线程隔离。研究提示词保持原样，原有 3～5 个任务要求未改动。

研究执行不依赖 SSE 订阅；关闭浏览器或断开连接不会取消后台研究。
取消必须调用取消接口。排队研究立即取消；运行中的研究经过
`RUNNING → CANCELLING → CANCELLED`，当前外部请求可能需要等待返回或超时。
所有子任务退出后才释放执行位置；已完成的结果保留，不再生成后续总结或报告。
取消不会回滚此前已经完成的笔记写入。

研究登记、事件和快照仅保存在内存。后端退出后不恢复、不续跑；
研究笔记文件保留；多研究界面和历史持久化不在 M3 范围内。

## 接口

可在后端 `/docs` 页面操作以下接口：

| 接口 | 用途 |
| --- | --- |
| `POST /researches` | 传入 `topic` 和可选 `search_api`，返回 202 与 `research_id` |
| `GET /researches` | 返回当前进程中的研究列表 |
| `GET /researches/{research_id}` | 查询任务、总结、来源、日志、工具调用、报告和状态快照 |
| `GET /researches/{research_id}/events?after=0` | SSE 订阅或回放，支持 `Last-Event-ID` |
| `POST /researches/{research_id}/cancel` | 幂等取消，不影响其他研究 |
| `GET /researches/{research_id}/report` | 查询最终报告；尚无报告返回 409 |

状态：`PENDING / RUNNING / CANCELLING / COMPLETED / PARTIAL / FAILED / CANCELLED`。
研究快照包含 `snapshot_seq`；先获取快照，再从 `after=snapshot_seq` 订阅，
可避免重复累计之前的总结片段。事件具有研究内递增的 `seq`、`research_id` 和 UTC `timestamp`。
本次进程不存在的研究返回 404；超出当前事件范围的游标返回 409。

旧 `POST /research`、`POST /research/stream` 仍可用，均经过同一管理器排队。
旧流式接口保留 data-only 帧格式，并通过 `X-Research-ID` 响应头返回研究编号。
现有页面的取消按钮调用后台接口；新研究按钮先提交旧研究的取消请求，再返回输入页面。

## 简单手动验证

1. 通过 `/docs` 连续提交研究，确认最多 3 项运行、7 项等待，第 11 项返回 429。
2. 取消排队研究，确认它不会启动；重复取消不应改变终态。
3. 取消运行中研究，确认先显示取消中，清理完成后下一项才运行。
4. 关闭事件连接后查询研究，应继续运行；使用事件序号可重新获取后续事件。
5. 确认报告、任务及笔记目录属于对应研究。重启后列表应为空，旧研究不会自动恢复。

本地简单回归：在 backend 目录运行 `.venv/bin/python -m unittest discover -s tests -v`。
测试使用隔离替身及临时笔记目录，不调用真实模型、搜索或生产笔记。
