# 09 · Web 控制台

> 位置：`web/`（服务端 + 纯手写前端）。**零第三方依赖**，只用 Python 标准库；前端无 CDN、无外部字体，离线可用。
> 默认地址：`http://127.0.0.1:8770/`。只读 `projects/` 与 `out/`，唯一会写的是 `out/<project>/run.log`（启动头 + runner 的 stdout/stderr）。

---

## 1. 怎么启动

```powershell
# 仓库根目录 novel-lab/ 下执行（必须用这个解释器绝对路径，别用 python）
& 'C:\Users\30264\.dsh\dsh-runtimes\dsh-next-primary-runtime\dependencies\python\python.exe' web/server.py --port 8770
```

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--host` | `127.0.0.1` | 监听地址。只本机使用，别改成 `0.0.0.0`（无鉴权） |
| `--port` | `8770` | 端口；被占用时打印原因并以退出码 2 结束 |
| `--quiet` | 关 | 不打印每个请求的访问日志 |

启动后控制台会打印仓库根目录、Python 路径、静态目录，以及 `src/runner.py` 是否就绪。
`Ctrl+C` 只关闭 HTTP 服务，**已经启动的 runner 进程不会被连带杀掉**（这是故意的：关掉控制台不该中断写作）。

浏览器打开 `http://127.0.0.1:8770/` 即可。前端支持 URL 深链：

- `http://127.0.0.1:8770/#quality` —— 直接打开某个视图（`#projects` / `#reader` / `#quality` / `#logs`）
- `http://127.0.0.1:8770/?project=demo_web#reader` —— 直接指定项目；即使该项目没有 `projects/*.toml`，只要有 `out/<project>/manifest.json` 也能看（演示数据就是这么用的）

---

## 2. 文件与数据来源

```
web/
├── server.py              纯标准库 HTTP 服务（本文件，约 600 行）
└── static/
    ├── index.html         单页骨架（4 个视图 + 运行弹窗 + toast 容器）
    ├── app.js             全部交互逻辑（原生 JS，无框架）
    └── style.css          深色主题、高信息密度

projects/*.toml            → 项目列表（只读，缺失时返回空数组）
out/<project>/manifest.json→ 进度与质量数据（只读，缺失时 404）
out/<project>/chapters/00001.txt → 正文（只读，5 位补零）
out/<project>/run.log      → 运行日志（runner 输出追加写）
```

`src/runner.py` 不存在时，`POST /api/run` 返回 `500 {"error": "runner 不存在: ..."}`，服务不会崩。

---

## 3. API

所有 JSON 响应都是 `Content-Type: application/json; charset=utf-8`，UTF-8 编码、`ensure_ascii=False`（中文不转义）。错误统一 `{"error": "..."}` + 合适状态码（400 / 404 / 409 / 500）。

### `GET /api/projects`

扫描 `projects/*.toml`（`tomllib`），并合并对应 `out/<name>/manifest.json` 的进度。

```json
{"projects": [{
  "name": "sijie", "title": "四界", "genre": "仙侠",
  "chapters": 5000, "words_per_chapter": 3400,
  "style": "webnovel", "model": "agy-cli/gemini-4-hydrogen",
  "written": 37, "total": 5000,
  "logline": "一句话前提", "running": true
}]}
```

- `projects/` 不存在或没有 `*.toml` → `{"projects": []}`（200，不报错）
- 单个 TOML 写坏 → 该条仍返回，带 `error` 字段，其余项目不受影响
- 缺字段一律容错：`title` 回退到 `name`，数值字段缺失为 `null`，`written` 缺失为 `0`
- `written` / `total` 优先取 manifest；`title` 若 manifest 里有则用 manifest 的

### `GET /api/manifest/<project>`

原样返回 `out/<project>/manifest.json`（解析后重新序列化，字段不增不减）。

- 文件不存在 → `404 {"error": "找不到 manifest: out/xxx/manifest.json（流水线还没写这个项目）"}`
- 文件不是合法 JSON → `500 {"error": "manifest.json 不是合法 JSON: ..."}`

### `GET /api/chapter/<project>/<no>`

读 `out/<project>/chapters/00001.txt`（章号 5 位补零，`\r\n` 统一成 `\n`）。

```json
{"no": 1, "text": "第一章 ……"}
```

- 文件不存在 → `404`；章号非正整数 → `400`；项目名不合法 → `400`

### `GET /api/log/<project>?tail=200`

读 `out/<project>/run.log` 末尾 N 行（默认 200，限制在 1–5000；最多读约 `max(256KB, tail×2KB)` 的尾部，避免几 MB 日志全量读入）。

```json
{"lines": ["2026-11-26 10:01:12 [info] 载入项目 ……"]}
```

日志文件还没生成时返回 `200 {"lines": []}`（前端显示「暂无数据」）。`tail` 不是整数 → `400`。

### `POST /api/run`

请求：`{"project": "sijie", "from": 1, "to": 50}`（`from` 可省略，默认 1；`to` 必填且 `>= from`）

行为：以 `Popen` 启动

```
<python> <repo>/src/runner.py --project sijie --from 1 --to 50
```

- `cwd` 固定为仓库根目录
- stdout/stderr 追加写 `out/<project>/run.log`，并在开头写一行 `[web] 时间 启动 project=... from=... to=...`
- 子进程环境强制 `PYTHONIOENCODING=utf-8`，保证 Windows 下日志也是 UTF-8（否则接口会读出乱码）
- Windows 用 `CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`，POSIX 用 `start_new_session=True`：**服务退出后 runner 继续跑**
- 成功 → `200 {"pid": 1234, "project": "sijie", "from": 1, "to": 50, "log": "out/sijie/run.log"}`
- 同一 project 已有本服务启动的 runner 在跑 → `409 {"error": "already running"}`
- `src/runner.py` 缺失 → `500 {"error": "runner 不存在: ...（等 src/runner.py 就绪后再启动）"}`
- 参数不合法 → `400`

### `POST /api/stop`

请求：`{"project": "sijie"}`。先 `terminate()`，3 秒内没退出再 `kill()`。

- 成功 → `200 {"stopped": true, "pid": 1234}`
- 没有在跑（或已自己跑完）→ `404 {"error": "not running"}`
- 只停止**本服务启动**的进程；服务重启后进程表是空的（见限制）

### 静态文件

`GET /` → `web/static/index.html`；其余路径按相对路径映射到 `web/static/`。

- 解析时 `resolve()` 后必须仍在 `static/` 目录内，`..`、URL 编码穿越、绝对路径一律 404
- 带正确的 `Content-Type`（HTML/JS/CSS 都是 UTF-8）；不存在的文件 404
- 只支持 GET/HEAD（POST 只给 `/api/run`、`/api/stop`）

---

## 4. `manifest.json` 字段含义

由 `src/runner.py` 写，Web 端**只读且缺字段全部容错**（缺失显示 `—` /「暂无数据」，不会崩）。

| 字段 | 含义 |
|---|---|
| `project` / `title` | 项目标识 / 中文书名 |
| `total` / `written` | 计划总章数 / 已写章数 |
| `target_words` | 单章目标字数区间，如 `[3000, 4000]` |
| `model` / `style` | 使用的模型 / 文风档位 |
| `updated` | manifest 最后更新时间（ISO 字符串） |
| `stats.avg_chars` | 已写章节平均字数 |
| `stats.avg_score` | 平均文体评分（满分 100） |
| `stats.below_target` | 字数低于目标下限的章数 |
| `stats.errors` | 运行期错误数 |
| `running.pid` | runner 进程号（空闲时为 `null`） |
| `running.from` / `running.to` | 本轮区间 |
| `running.done` / `running.todo` | 本轮已完成 / 待完成章数（用来画运行进度条） |
| `running.eta_sec` | 预计剩余秒数（前端格式化为「x 小时 y 分」） |
| `running.phase` | 当前阶段（如 `prose`），显示在状态胶囊里 |
| `chapters[].no` | 章号 |
| `chapters[].chars` | 该章字数 |
| `chapters[].score` | 该章文体评分（≥75 绿 / 60–75 黄 / <60 红） |
| `chapters[].retries` | 重试次数 |
| `chapters[].issues` | 问题列表（字符串数组；也兼容 `{label, value}` 对象） |
| `lint_targets` | 每个文体指标的 `[下限, 上限]`；`null` 表示该边不设限（如 `[null, 0.016]`） |

**可选扩展**：如果 manifest 额外提供 `lint_values`（或 `lint_current` / `lint` / `metrics`）对象，前端会在目标区间条形图上画一根「当前值」竖线（绿色=在区间内，红色=越界）。没有这些字段时只画目标带，不影响使用。

---

## 5. 前端四个视图

| 视图 | 内容 |
|---|---|
| **项目** | 卡片列表：书名、`name`、题材/风格徽章、章数、每章字数、模型、已写进度条；运行中额外显示 `from–to`、`done/todo`、ETA、阶段和「停止」按钮；「开始写作」弹窗填 `from`/`to` 后 POST `/api/run`（默认从「已写+1」起、写 50 章） |
| **正文阅读** | 章号输入 + 上一章/下一章/最新章；等宽字体按纯文本显示正文；顶部显示字数（优先 manifest 的 `chars`，否则按实际字符数）与评分胶囊（≥75 绿 / 60–75 黄 / <60 红）、重试次数、问题数 |
| **文体质量** | 5 个指标块（已写/总章数、平均字数、平均评分、低于目标章数、错误数）；`lint_targets` 目标区间横向条形图（div 宽度实现，绿色带 = 健康区间，竖线 = 当前值）；「待修章节」表格列出评分最低的 20 章（章号、字数、评分、重试、问题），点「阅读」跳转正文 |
| **日志** | 等宽显示 `run.log` 末尾 N 行（100/300/1000 可选，默认 300），3 秒轮询；可暂停/立即刷新；自动滚到底部（用户往上翻时不会强制跳） |

交互约定：

- 所有 `fetch` 都有 `try/catch`，失败时在页面顶部/视图内显示错误，并弹 toast（轮询失败同一错误只提示一次，避免每 3 秒刷屏）
- 没有数据时显示「暂无数据」而不是空白；manifest 不存在属于正常状态（第一次运行前）
- 每 3 秒轮询：项目页拉 `/api/projects`，其它页拉当前项目的 manifest 更新进度；日志页额外拉 `/api/log`
- 当前项目、视图、章号记在 `localStorage`，刷新页面不丢
- 服务端返回的数据全部用 `textContent` 渲染，不拼 `innerHTML`（无 XSS 面）
- 浏览器要求：支持 ES2020 的现代浏览器（Chrome/Edge 90+）

---

## 6. 自测数据（`out/demo_web/`）

为了在没有 `projects/*.toml`、没有真实流水线产物时也能验证接口，仓库里留了一份**假数据**：

- `out/demo_web/manifest.json` —— 3 章已写 / 总 120 章，含评分、问题、`lint_targets` 与可选的 `lint_values`
- `out/demo_web/chapters/00001.txt ~ 00003.txt` —— 三章中文假正文
- `out/demo_web/run.log` —— 15 行中文假日志

用法：`http://127.0.0.1:8770/?project=demo_web#reader`（`demo_web` 没有 TOML，所以不会出现在项目列表里，用 URL 参数指定）。删除 `out/demo_web/` 不影响任何真实项目。

---

## 7. 已知限制

1. **无鉴权、无 CSRF 防护。** 设计为「本机单用户」，默认只绑 `127.0.0.1`；不要 `--host 0.0.0.0` 暴露到局域网/公网。
2. **服务重启后停不掉之前启动的 runner。** 进程表在内存里，重启后 `/api/stop` 只会返回 `404 not running`；需要手动结束进程（任务管理器 / `taskkill`）。manifest 里的 `running.pid` 可作参考，但服务端不会据此杀进程（避免 PID 复用误杀）。
3. **只管理直接子进程。** 如果 runner 自己再派生 worker，停止主进程后它们可能残留；runner 应自己处理信号/清理。Windows 上 `terminate()` 是硬终止（`TerminateProcess`），不会给 runner 收尾机会，关键状态应由 runner 及时落盘。
4. **没有真正的并发控制。** 同一 project 的重复启动由 `409` 兜底，但两个不同 project 可以同时跑；manifest 的写入正确性由 runner 负责，Web 端不做加锁。
5. **日志只读末尾。** `/api/log` 不返回完整日志；需要全量请直接看 `out/<project>/run.log`。超大单行日志会被截断到读取窗口内。
6. **manifest 写入是 runner 的事。** Web 端不修改 `manifest.json`；如果 runner 写坏 JSON，接口返回 500 并显示错误，但不会尝试修复。
7. **`lint_targets` 只有区间。** 目标条形图默认只画「健康区间」；要画当前值需要 manifest 提供 `lint_values` 之类的可选字段（见第 4 节）。
8. **正文按纯文本显示。** 不解析 Markdown/HTML；超长章节一次性加载（5000 章 × 3000+ 字的量级下建议一次只读一章，当前实现正是如此）。
9. **`projects/` 缺失时项目列表为空。** `out/` 下的产物不会自动出现在列表里，除非有对应 `projects/<name>.toml`，或通过 `?project=` 深链指定。

---

## 8. 自测覆盖（2026-11-26）

- 接口/静态：68 项通过（projects、manifest 200/404/坏 JSON、chapter 200/404/400、log tail/缺文件/非法参数、run 409/500/400、stop 404、静态 200、5 种路径穿越、非法项目名、非法 JSON 等）
- 前端逻辑：25 项通过（Node + 最小 DOM 垫片跑真实 `app.js`，覆盖四个视图渲染、评分颜色、弹窗默认值、URL 深链、无错误 toast）
- 浏览器截图未能执行：本机沙箱禁止 Chromium 启动（crashpad/mojo 被拒），因此**视觉布局未经真实浏览器验证**，仅验证了 DOM 结构与数据渲染。
