# 智能旅行小助手

这是一个可运行的 LangGraph 示例，使用 5 个核心节点完成行程解析、车次信息查询丶模拟天气查询、随行清单生成、冲突检查和物品修正。

## 图形界面

安装依赖后，在项目目录运行：

```powershell
.\run_app.ps1
```

浏览器会打开 `http://localhost:8501`。网页支持真实天气卡片、分类清单、已打包复选框、追加信息、修改记录和 LangGraph 人工中断。

停止后台运行的软件：

```powershell
.\stop_app.ps1
```

## 架构

```text
START -> Parser
Parser -> Weather（首次运行或目的地/日期变化）
Parser -> Revisor（普通追加信息）
Weather -> Generator（成功）
Weather -> Revisor + interrupt（失败，要求手动天气）
Generator -> Checker
Checker -> Generator（普通问题，最多重试 2 次）
Checker -> Revisor + interrupt（严重且修正不明确）
Checker -> END（无问题或达到重试上限）
Revisor -> Checker（增量更新）
```

- `Parser`：DeepSeek 可选增强；未配置或调用失败时自动使用本地规则解析。
- `Weather`：通过 Open-Meteo 查询真实天气，无需 API Key；查询失败时走人工天气 fallback。
- `Generator`：按衣物、电子设备、洗护、证件/文件和其他分类生成。
- `Checker`：检查御寒、正式搭配、袜子数量、充电器等问题。
- `Revisor`：只向已有清单添加或提高数量，并记录差异，不清空重建用户清单。
- `MemorySaver`：默认通过 `thread_id` 保存当前进程内的会话状态，支持连续追加信息。
- `SqliteSaver`：可选启用，支持程序退出后继续同一会话。

## 安装与运行

建议使用 Python 3.10+：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
.\run.ps1 "这周五去上海，待3天，参加行业展会，晚上有同行聚餐。"
```

若系统 PATH 中没有 Python，`run.ps1` 会尝试使用 Codex 自带的 Python 运行时。

需要跨程序重启保存状态时：

```powershell
python -m pip install langgraph-checkpoint-sqlite
.\run.ps1 --sqlite .travel_packing\checkpoints.sqlite --thread-id user-001 "这周五去上海，待3天，参加展会。"
.\run.ps1 --sqlite .travel_packing\checkpoints.sqlite --thread-id user-001 --update "第二天要演讲，需要正装和电脑。"
```

`DEEPSEEK_API_KEY` 是可选项。不要把真实密钥写进源码；`.env` 已加入 `.gitignore`。天气使用免费的 Open-Meteo，不需要天气 API Key，也不需要 Tavily。

运行测试：

```powershell
python -m pytest -q
```

## 增量更新示例

首次输入后，在同一个 CLI 会话中继续输入：

```text
展会第二天我要做演讲，所以需要正装和笔记本电脑。
```

Revisor 会保留现有物品，并新增正装、正式皮鞋、笔记本电脑及充电器、翻页笔、U 盘和投影接口提醒。CLI 使用适合 PyCharm/终端的分类清单输出；代码仍提供 `render_markdown`，供网页或 Markdown 文档使用。
