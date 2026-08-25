# 记忆漩涡 · Python 后端（v0.9.3 · PWA 纯前端化 + 后端保留）

**v0.9.3 PWA 纯前端化**：新增 `localdb.js`（IndexedDB 数据层 + `window.fetch` 全局拦截 + API 路由器），让前端可以脱离 Python 后端独立运行——所有数据存入浏览器 IndexedDB，通过 `manifest.json` + `sw.js` 实现「添加到主屏幕」的 PWA 体验。Python 后端完整保留，两种模式可独立运行。
**纪念日卡片背景图**：当纪念日 `linked_memory_id` 关联的记忆存在照片（png/jpeg/gif/webp）时，
后端 `_anniv_cover_map()` 把首媒体派生为 `cover` 字段，前端通过 CSS 变量 `--cov-url` 给**列表卡片与
「下一个纪念日」大卡**套上深色渐变遮罩背景；无关联记忆或首媒体非图片时保持原浅色卡片。
**S07 移除「照片」快捷按钮**：媒体只在编辑模式经「+ 添加」格子追加，非编辑态不再调用立即关联接口。
**v0.9 多用户登录/注册**：新增 `users`/`sessions` 表、PBKDF2 密码哈希、Bearer 会话与 owner 数据隔离。

**共建时间线 + 邀请成员 + 媒体预签名直传 + 创建记忆媒体导入**：新增 `timeline_nodes`、`invite_members` 两张表，
`coupleTimeline` / `friendTimeline` / `invites` / `timelineHub` 全部改为数据库派生（节点回链记忆时
实时聚合视角/留言计数）；新增 `memories.media` JSON 列与 `uploads.py` 媒体存储层，
支持「预签名直传」三步（presign → PUT → 关联记忆）。
**v0.8.1** 让 S05「创建记忆」页面支持多选照片/视频/iOS 实况（`.mov`），保存时随记忆一起入库；
S07 详情对实况文件渲染 `LIVE 实况` 徽标。
**v0.8.2** 让「记忆记录」（S03 时间线/场景视图卡片）与「记忆详情 hero」默认展示传入的第一张照片/视频/实况；
无媒体或首张为音频时保持相机占位图标。封面由后端 bootstrap 一次性派生为 `cover` 字段，前端按 `kind` 渲染
`img` / `video` / 实况 `LIVE` 徽标，避免额外请求。
**v0.8.3** 让 S07「编辑」支持**增删媒体**（移除任意照片/视频/实况、补充新媒体），保存时以 `PATCH media`
**全量替换**入库；编辑保存与「照片」上传后均重新拉取 bootstrap，**首页时间线/场景封面即时同步**。
**v0.8.4** 让创建记忆（S05/S06 引导）在**未写下感受时自动写入「无」**，不再拦截保存（后端
`feel` 字段 `min_length=1` 亦满足）；保存后首页时间线显示「无」。
**v0.8.5** 修复 S03 聚合视图「全部/个人/情侣/友情/成长」场景 tab 切换：`home.sceneView` 改为派生
**全部场景**记忆卡（原来只收 personal），前端点击 tab 时按 `scene` 过滤重渲染 + 同步 chip 高亮，
空场景显示「还没有记忆」空态；「全部」仍展示跨场景时间线。
**v0.8.6** 把主页「记录」（S04 场景选择器）从**底部弹窗**改为**常驻全屏页面**：顶部导航栏
（返回箭头 → 时间轴主页）+ 场景网格 + 底部四个主 tab 栏，可随时自由返回/切换；`show()` 统一同步
tab 高亮，任意入口（proto-nav / hash / 返回）进入主页面时底部 tab 高亮均正确。

> **AI 生成功能未启用**（v0.3 起）：`llm.py` 与相关接口保留（休眠），见文末。

## 启动

```bash
cd backend
python -m pip install -r requirements.txt   # fastapi / uvicorn / httpx / sqlalchemy
python main.py
```

或直接双击 `start-server.bat`。服务运行在 http://127.0.0.1:8000

首次启动自动建库并把 test_data 中的**记忆 + 多视角/留言演示 + 纪念日 + 成长追踪 +
时间线节点 + 邀请成员**导入为**种子数据**（source=seed），保证界面初始不为空；
**旧库自动迁移**（补列 + 索引，不丢用户数据），要清空重来删掉 `data/memory_vortex.db` 重启即可。

## v0.5 安全机制（本地单用户阶段）

| 机制 | 说明 |
|---|---|
| **写操作鉴权** | POST/PUT/PATCH/DELETE `/api/*` 须携带 `X-API-Token` 头，否则 401。令牌来源：环境变量 `MC_API_TOKEN` > `backend/auth_token.txt` > 进程内随机生成（重启后变化）。令牌经同源 `/api/app/bootstrap` 的 `meta.apiToken` 下发给前端；多用户后替换为登录会话/JWT，中间件层不变。 |
| **限流** | 写接口按 IP 滑动窗口限流（30 次/分钟，超出 429）。内存实现零依赖，多实例时换 Redis 令牌桶，接口不变。 |
| **CORS 收窄** | 仅允许本机来源（127.0.0.1/localhost:8000/8778 + `null` 兼容 file:// 直开）。 |
| **删除所有权校验** | 删除记忆按 `owner_id` 校验（IDOR 防护本地版）：local 所有者可管理 local + seed 数据；多用户时 owner 换为登录用户 id。 |
| **上传文件标识** | 文件标识 `fileKey` 由服务端生成（24 位 hex + 白名单扩展名），落盘前正则二次校验，防止路径穿越。 |

> 令牌未配置时启动日志会打印临时令牌并 `WARNING` 提示；建议配置
> `MC_API_TOKEN` 环境变量或 `backend/auth_token.txt` 固化令牌。

## v0.9 多用户登录/注册（Bearer 会话）

| 机制 | 说明 |
|---|---|
| **注册/登录** | `POST /api/auth/register`（用户名 3-32 位 `\w`/中文、密码 ≥6 位，201 + 自动登录）、`POST /api/auth/login`（200 + token；账号/密码错误统一返回「账号或密码错误」防枚举） |
| **密码存储** | PBKDF2-HMAC-SHA256 + 128 位随机盐 + 200k 迭代；`hmac.compare_digest` 防时序侧信道；绝不明文/可逆存储 |
| **会话** | `sessions` 表：token 为主键（secrets 生成 64 位 hex），30 天过期，登出/注销即时吊销（软删除） |
| **鉴权双通道** | 登录用户：`Authorization: Bearer <token>`；游客：旧版 `X-API-Token`（向后兼容，无 token 的读接口放行）。`PUBLIC_WRITE_PATHS` 白名单仅注册/登录 |
| **数据隔离** | 数据按 `owner_id` 分桶：`local`=游客、`seed`=共享演示数据、`user:{id}`=登录用户。列表查询 `owner_id IN (seed, 当前owner)`；bootstrap 缓存按 owner 分桶，不同身份互不可见 |
| **数据承接** | 注册/登录时 `adopt_local_data()` 把游客 `local` 数据自动归入登录用户名下，游客体验不丢失 |
| **IDOR 防护** | `_memory_visible(mid, owner)` 封死按 id 访问的越权（详情/编辑/删除/留言/视角） |
| **软删除合规** | `users`/`sessions` 沿用 `deleted_at` 软删除标记（PIPL 合规），登录校验排除已删账号 |
| **前端** | S12「我的」动态渲染（登录态：昵称/账号/记忆数/登出；游客态：登录入口）；S17 登录/注册页（tab 切换、游客继续）；会话持久化到 `localStorage.mc_token`，boot 时带 Bearer 拉 bootstrap 由 `meta.auth.loggedIn` 判定；401 自动清 token 回登录页 |

## 接口清单

| 方法 | 路径 | 说明 | 鉴权 |
|---|---|---|---|
| GET | `/health` | 健康检查 | 否 |
| POST | `/api/auth/register` | 注册账号（username/password/nickname → 201 + Bearer token） | 否 |
| POST | `/api/auth/login` | 登录（校验密码 → Bearer token + 用户信息；统一错误文案） | 否 |
| POST | `/api/auth/logout` | 退出登录（吊销当前会话，幂等） | Bearer |
| GET | `/api/auth/me` | 当前登录用户信息 | Bearer |
| PUT | `/api/auth/me` | 更新昵称/头像 | Bearer |
| DELETE | `/api/auth/me` | 注销账号（软删除用户 + 吊销其全部会话） | Bearer |
| GET | `/api/app/bootstrap` | 启动数据（静态模板 + 数据库派生 + meta.auth + meta.apiToken；按 owner 分桶缓存） | 否 |
| POST | `/api/app/reload` | 热重载模板（仅开发用） | 是 |
| GET | `/api/v1/memories?scene=&limit=&before_id=` | 记忆列表（可按场景过滤 + 游标分页） | 否 |
| GET | `/api/v1/memories/{id}` | **记忆详情**（本体 + 多视角 + 留言 + 媒体） | 否 |
| POST | `/api/v1/memories` | 新建记忆 | 是 |
| PATCH | `/api/v1/memories/{id}` | 编辑记忆（部分更新；支持 feel/emotion/scene/时间/**media 全量替换**） | 是 |
| DELETE | `/api/v1/memories/{id}` | 删除记忆（软删除 + 所有权校验） | 是 |
| GET | `/api/v1/memories/{id}/perspectives` | 多视角列表 | 否 |
| POST | `/api/v1/memories/{id}/perspectives` | 新增多视角 | 是 |
| DELETE | `/api/v1/perspectives/{id}` | 删除多视角（软删除） | 是 |
| GET | `/api/v1/memories/{id}/comments` | 留言列表 | 否 |
| POST | `/api/v1/memories/{id}/comments` | 新增留言 | 是 |
| DELETE | `/api/v1/comments/{id}` | 删除留言（软删除） | 是 |
| GET | `/api/v1/anniversaries` | **纪念日列表**（含实时倒计时/已过天数视图字段 + 关联记忆首媒体 `cover`） | 否 |
| POST | `/api/v1/anniversaries` | 新建纪念日（名称/公历锚点/农历标记/重复/关联记忆） | 是 |
| PATCH | `/api/v1/anniversaries/{id}` | 编辑纪念日（部分更新；所有权校验） | 是 |
| DELETE | `/api/v1/anniversaries/{id}` | 删除纪念日（软删除 + 所有权校验） | 是 |
| GET | `/api/v1/growth/subjects` | **成长主体列表**（含实时派生的年龄/最近里程碑） | 否 |
| POST | `/api/v1/growth/subjects` | 新增成长主体（宝宝/宠物/其他 + 生日锚点） | 是 |
| PATCH | `/api/v1/growth/subjects/{id}` | 编辑成长主体 | 是 |
| DELETE | `/api/v1/growth/subjects/{id}` | 删除成长主体（软删除 + 级联软删其里程碑） | 是 |
| GET | `/api/v1/growth/subjects/{id}/milestones` | 某主体里程碑列表 | 否 |
| POST | `/api/v1/growth/subjects/{id}/milestones` | 记录里程碑（标题/日期/重要度/可选回链记忆） | 是 |
| PATCH | `/api/v1/growth/milestones/{id}` | 编辑里程碑 | 是 |
| DELETE | `/api/v1/growth/milestones/{id}` | 删除里程碑（软删除 + 所有权校验） | 是 |
| GET | `/api/v1/timeline/nodes?kind=` | 时间线节点列表（couple/friend；含实时计数与回链 mid） | 否 |
| POST | `/api/v1/timeline/nodes` | 新增节点（支持回链记忆） | 是 |
| PATCH | `/api/v1/timeline/nodes/{id}` | 编辑节点 | 是 |
| DELETE | `/api/v1/timeline/nodes/{id}` | 删除节点（软删除） | 是 |
| GET | `/api/v1/invites/members?space=` | 邀请成员列表（couple/friend） | 否 |
| POST | `/api/v1/invites/members` | 新增成员 | 是 |
| DELETE | `/api/v1/invites/members/{id}` | 移除成员（软删除） | 是 |
| POST | `/api/v1/uploads/presign` | 申请预签名上传凭据 | 是 |
| PUT | `/api/v1/uploads/{file_key}` | 预签名直传（本地实现：接收字节落盘） | 是 |
| POST | `/api/v1/memories/{id}/media` | 把已上传媒体关联到记忆 | 是 |
| POST | `/api/app/generate` · GET `/api/app/llm-status` | AI 生成（**暂未启用**） | generate 是 |

统一响应包 `{code, message, data}`；`/api/app/bootstrap` 返回裸数据对齐前端契约。
接口文档：http://127.0.0.1:8000/docs

## 新建记忆入参（POST /api/v1/memories）

```json
{
  "scene": "personal",
  "feel": "写下此刻的感受",
  "emotion": "幸福",
  "time_mode": "custom",
  "custom_date": "2026-08-25",
  "custom_time": "20:15",
  "fuzzy_label": "去年夏天",
  "fuzzy_note": "大理旅行的那几天",
  "media": [
    {"file_key": "aabbcc...112233.png"},
    {"file_key": "aabbcc...112233.mov"}
  ]
}
```

> **编辑媒体（v0.8.3）**：`PATCH /api/v1/memories/{id}` 传 `media` 数组即**全量替换**——传完整数组 = 替换为这些媒体；
> 传 `[]` = 清空全部媒体；**不传** `media` = 保持不变（PATCH 部分更新语义）。

## 媒体上传流程（v0.8 预签名直传）

```
客户端                服务端                存储
  |                    |                    |
  |-- POST /uploads/presign {filename,contentType} ->
  |                    |-- 生成 fileKey + Content-Type headers
  |<- {fileKey, uploadUrl, method:PUT, headers} --|
  |-- PUT uploadUrl（原始字节） ->
  |                    |-- save_file() 校验 key + 5MB 落盘 data/uploads/
  |<- {fileKey, url} --|
  |-- POST /memories/{id}/media {file_key} ->
  |                    |-- 追加 memories.media JSON 数组
  |<- ok --|
```

- 替换真实 OSS 时只改 `uploads.py`：`presign()` 返回 OSS 预签名 URL，`save_file()` 可空/废弃，
  `resolve_url()` 返回 OSS 访问 URL。路由与前端不变。
- 本地通过 `app.mount("/uploads", StaticFiles(...))` 静态托管 `data/uploads/`。

## 数据流（bootstrap 聚合）

```
/api/app/bootstrap
  = 静态模板模块（meta/scenes/emotions/timeSettings/anniversaries/growth）
  + 数据库派生模块：
      home.timeline      ← memories 按日期倒序分组；模糊时间按标签归组置底
      home.sceneView     ← 全部场景记忆卡（含 scene 字段，前端按 tab 过滤）
      otd（往年今日）     ← 模板演示卡片 + 库中往年同月同日的真实记忆
      anniversaries      ← anniversaries 表实时计算「下一个纪念日」+ 倒计时/已过天数
      growth             ← growth_subjects + growth_milestones 实时派生年龄/最近里程碑/N天前/时间轴
      coupleTimeline     ← timeline_nodes (kind=couple) 派生；回链记忆时实时显示「N视角 · M留言」
      friendTimeline     ← timeline_nodes (kind=friend) 派生
      invites            ← invite_members 派生（couple.pending / friend.members）
      timelineHub        ← 实时派生 couple/friend 记忆数 + 最近节点，growth/all 卡保留模板
```

前端交互（页面末尾「真实数据链路」脚本）：

- S05 写感受/选情绪 → **「拍照 / 相册·实况」多选媒体 → 实时预览缩略图（照片/视频/实况）** → S06 选时间模式
  → **「保存记忆」** → 客户端先预签名直传所有媒体 → POST 创建记忆（携带 media）→
  重新拉取 bootstrap → 重渲染 → 回首页时间轴（新记忆置顶）；保存成功后清空 S05 选择；
  **未写下感受时自动填「无」，不阻碍保存**；
- S03 时间线/场景视图卡片**默认展示该记忆的第一张媒体**作为封面（照片/视频/实况），无媒体或首张为音频时回退相机占位；
- S03 顶部「全部 / 个人 / 情侣 / 友情 / 成长」tab：**「全部」展示跨场景时间线**；其余按 `scene` 过滤 `sceneView.cards` 重渲染记忆卡并同步 chip 高亮，空场景显示空态提示；
- 点击任意时间线/场景卡片 → S07 渲染**这条记忆**的详情，hero 大图区同样默认展示**第一张媒体**；
- S07「编辑」：feel 内联编辑 + 媒体**增删**（缩略图/首图右上角 × 移除，`+ 添加` 或「照片」多选补充），保存时 `PATCH {feel, media}` 全量替换；
- 编辑保存 / 「照片」上传后：先刷新 bootstrap（首页时间线封面同步），再重拉当前记忆详情（避免被模板 memoryDetail 覆盖）；
- 记忆卡片右上角 **×** → 确认 → DELETE → 刷新重渲染；
- S07「标记纪念日」→ S08 填写名称/日期/开关 → **「完成标记」** → POST →
  刷新重渲染 → S09 列表展示倒计时/已过天数；
- 纪念日卡片右上角 **×** → 确认 → DELETE → 刷新重渲染；
- S13「成长追踪」→ 新增主体 → 输入名称/类型/生日/备注 → POST → S13 列表实时更新；
- 点击成长主体 → S14 展示该主体的成长时间轴；S14「记录里程碑」→ POST →
  时间轴即时刷新；里程碑卡片 **×** → DELETE → 刷新重渲染；
- 主体卡片右上角 **×** → DELETE → 级联软删其所有里程碑；
- S10「共建邀请」：情侣/友情成员列表真实渲染，成员卡片右上角 **×** → 确认 → DELETE → 刷新重渲染；
- S11「共建时间线」：情侣/友情螺旋节点来自 DB，回链记忆的节点显示**实时「N视角 · M留言」**，
  点击节点弹窗 → **「回看那段记忆」** → 跳转 S07 该记忆详情；
- S07「照片」→ 选择文件 → 客户端预签名直传（presign/PUT/关联）→ 媒体区实时刷新并展示；
  对 `.mov` 实况文件额外渲染 `LIVE 实况` 徽标。

## 升级 PostgreSQL

只改 `db.py` 一行：`DATABASE_URL = "postgresql+psycopg://user:pass@host/dbname"`，
`pip install psycopg[binary]`，重启即自动建表（种子导入逻辑复用）。

## 目录结构

```
backend/
├── main.py              # FastAPI 应用（安全中间件 + bootstrap 聚合 + 全部业务接口）
├── db.py                # SQLAlchemy 模型 / 建库 / 轻量迁移 / 种子导入 / CRUD
├── uploads.py           # 媒体存储层（预签名 + 本地落盘；替换 OSS 只改此文件）
├── llm.py               # AI 生成（休眠）
├── requirements.txt
├── data/
│   ├── test_data.json   # 静态模板（结构契约 + 非记忆模块数据源）
│   ├── memory_vortex.db# SQLite 数据库（真实数据，删文件即重置）
│   └── uploads/         # 本地上传文件（静态托管 /uploads）
└── static/
    ├── memory-vortex-prototype-v2-api.html   # 前端页面（含 PWA 改造 + 全部交互）
    ├── localdb.js           # IndexedDB 数据层 + fetch 拦截（PWA 核心，~900 行）
    ├── manifest.json        # PWA 清单
    ├── sw.js                # Service Worker（app shell 预缓存）
    ├── icon.svg             # SVG 图标
    ├── icon-192.png         # PNG 图标 192×192
    ├── icon-512.png         # PNG 图标 512×512
    └── test_data.json       # 种子模板（PWA 运行时 fetch 加载）
```

## 前端接入说明

- 原型页已在服务端托管，浏览器直接打开上面的页面地址即可（同源，无跨域问题）。
- 若用本地双击打开 HTML（file://），也支持：CORS 已全放开，但需把页面里 `API_BASE` 改为 `'http://127.0.0.1:8000'`。
- 数据流转：`boot()` → `loadAppData()` → fetch `/api/app/bootstrap` → `initApp(D)` 渲染 16 屏；失败则显示「数据加载失败」遮罩。

## AI 生成链路（暂未启用）

> v0.3 起前端拦截已移除，能力保留在服务端（休眠），前端不触发即不运行。

```
用户在 S01 选择场景 → 点击「进入记忆漩涡」
  → POST /api/app/generate {scene: "couple"}
  → 服务端：用户数据 + test_data 模板 → 提示词 → 大模型（流式接收）
  → 模型输出 JSON → 自动修复常见瑕疵 + deep_merge 包装成 test_data 同构数据
  → 前端循环播放漩涡动画，收到数据后重渲染 16 屏再进入下一屏
```

### 工程要点（踩坑记录）

- **必须流式（stream=True）**：非流式长生成时连接 ~40s 无数据会被服务端掐断
  （`Server disconnected without sending a response`），流式每数百毫秒有数据块到达，稳定。
- **max_tokens 截断检测**：finish_reason == "length" 时主动报错重试，不浪费解析。
- **JSON 容错**：免费模型偶发尾逗号/中文引号/markdown 包裹，`extract_json`
  会自动修复；仍失败则整体重试（最多 2 次生成）。
- **精简输出**：提示词要求紧凑 JSON + 条目精简 + 只生成核心模块，
  缺失模块由 deep_merge 自动回填模板值，结构完整性不受影响。

### 大模型配置（免费测试）

默认使用**智谱 GLM-4-Flash**（免费模型，OpenAI 兼容协议）：Key 存
`backend/llm_api_key.txt` 或环境变量 `LLM_API_KEY`，重启后 `/api/app/llm-status`
显示 `llm` 即生效。切换其他 OpenAI 兼容服务设 `LLM_BASE_URL` / `LLM_MODEL`。

## 演进路径（对齐 backend-arch-prompt.md）

1. ✅ 静态 JSON 数据源
2. ✅ 数据库持久化（SQLite，可一行升级 PostgreSQL）
3. ✅ 记忆真实增删（新建/展示/删除，含精确与模糊双时间戳）
4. ✅ **安全闭环**（写操作鉴权 + 限流 + CORS 收窄 + 所有权校验）—— v0.5
5. ✅ **性能基线**（索引 + bootstrap 缓存 + 游标分页）—— v0.5
6. ✅ **多视角/留言**（perspectives + comments 两张表，真实入库）—— v0.5
7. ✅ **编辑记忆**（PATCH 部分更新，含 feel/emotion/scene/时间；S07 内联编辑）—— v0.5
8. ✅ **纪念日入库**（anniversaries 表 + 公历月日锚点倒计时 + S08/S09 真实数据）—— v0.6
9. ✅ **成长追踪入库**（growth_subjects + growth_milestones + 年龄/N天前实时派生 + S13/S14 真实数据）—— v0.7
10. ✅ **共建时间线/邀请成员入库**（timeline_nodes + invite_members + S10/S11 真实数据）—— v0.8
11. ✅ **媒体上传预签名直传**（uploads.py + S07 编辑态媒体管理 + **S05 创建记忆导入照片/视频/实况**）—— v0.8 / v0.8.1  
12. ✅ **记录卡片/详情默认首媒体封面**（bootstrap 派生 `cover` + S03 封面渲染 + S07 hero 首媒体）—— v0.8.2  
13. ✅ **编辑记忆增删媒体 + 首页封面同步**（PATCH media 全量替换 + S07 编辑态媒体管理 + 保存后 bootstrap 刷新）—— v0.8.3  
14. ✅ **创建记忆未写感受自动填「无」**（不再拦截保存，后端 min_length=1 亦满足）—— v0.8.4  
15. ✅ **S03 聚合视图场景 tab 修复**（sceneView 派生全部场景 + 前端按 tab 过滤/高亮/空态）—— v0.8.5  
16. ✅ **「记录」由底部弹窗改为常驻全屏页面**（S04 导航栏返回 + 场景网格 + 底部 tab 栏，可自由返回）—— v0.8.6  
17. ✅ **多用户登录/注册**（users/sessions 表 + PBKDF2 密码哈希 + Bearer 会话 + owner 数据隔离 + S12 动态「我的」/ S17 登录注册页）—— v0.9  / ⬜ 推送
18. ✅ **S07 移除「照片」快捷按钮**（媒体只在编辑模式经「+ 添加」格子追加，PATCH 全量替换；非编辑态立即关联接口前端不再调用）—— v0.9.1
19. ✅ **纪念日卡片背景用关联记忆照片**（`_anniv_cover_map()` 把首媒体派生为 `cover`，列表卡片 + 下一个纪念日大卡均用 CSS 变量背景 + 深色渐变遮罩，无图保持原样式）—— v0.9.2
20. ✅ **PWA 纯前端化**（`localdb.js` IndexedDB 数据层 + `window.fetch` 全局拦截 `/api/*` → `localApiRouter` + `local-upload:*` → `localUploadRouter`；12 个 object store 对齐 12 张表；`manifest.json` + `sw.js` app shell 预缓存 + `display:standalone` 可添加到主屏幕 + standalone CSS 全屏；`docs/` 目录适配 GitHub Pages 部署）—— v0.9.3
