# 记忆漩涡 MemoryVortex

一款情侣 / 个人记忆管理应用——把你们的日常瞬间、纪念日、成长轨迹记录下来，编织成专属的回忆漩涡。

## 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/<你的用户名>/memory-vortex.git
cd memory-vortex/backend

# 2. 创建虚拟环境 + 安装依赖
python -m venv ../venv
source ../venv/bin/activate    # Windows: ..\venv\Scripts\activate
pip install -r requirements.txt

# 3. 启动
python main.py

# 4. 打开浏览器
# 访问 http://localhost:8000
```

> Python 3.10+ 即可运行。首次启动会自动创建数据库并导入演示数据。

## 功能一览

| 模块 | 说明 |
|---|---|
| 记忆记录 | 按场景（个人 / 情侣 / 友情 / 成长）创建记忆卡片，支持照片/视频上传 |
| 纪念日倒计时 | 记录重要日期，自动计算倒计时或已过天数，卡片背景用关联记忆的照片 |
| 成长追踪 | 记录宝宝/宠物的成长里程碑，按年龄自动聚合时间轴 |
| 共建时间线 | 情侣/友情双人共建时间线，节点可回链记忆 |
| 登录注册 | 账号体系 + Bearer 会话鉴权，数据按用户隔离 |
| 首页仪表盘 | 精选记忆、纪念日提醒、时间轴 Hub 一页概览 |

## 技术栈

- **后端**：Python 3.10+ / FastAPI / SQLAlchemy / SQLite
- **前端**：单文件 HTML（原生 JS，零构建步骤）
- **存储**：SQLite 数据库 + 本地磁盘文件上传（结构对齐 OSS，可一键升级对象存储）

## 项目结构

```
memory-vortex/
├── backend/
│   ├── main.py              # FastAPI 应用入口
│   ├── db.py                # 数据库模型与操作
│   ├── uploads.py           # 文件上传（本地磁盘实现）
│   ├── requirements.txt     # Python 依赖
│   ├── data/
│   │   └── test_data.json   # 演示种子数据
│   └── static/
│       ├── memory-vortex-prototype-v2-api.html  # 前端页面（含 PWA 改造）
│       ├── localdb.js       # IndexedDB 数据层 + fetch 拦截（PWA 核心）
│       ├── manifest.json    # PWA 清单
│       ├── sw.js             # Service Worker
│       ├── icon.svg          # SVG 图标
│       └── test_data.json    # 种子模板（PWA 运行时加载）
├── docs/                    # GitHub Pages 部署目录
│   ├── index.html           # PWA 入口
│   ├── localdb.js
│   ├── manifest.json
│   ├── sw.js
│   ├── icon-192.png / icon-512.png / icon.svg
│   └── test_data.json
└── deploy/
    └── setup.sh             # 服务器一键部署脚本（可选）
```

## 本地开发

```bash
cd backend
python -m venv ../venv
source ../venv/bin/activate
pip install -r requirements.txt
python main.py
# 热重载开发模式：
# uvicorn main:app --reload --port 8000
```

API 文档：启动后访问 `http://localhost:8000/docs`（Swagger UI）。

详细技术文档见 [`backend/README.md`](backend/README.md)。

## 部署到服务器（可选）

见 [`deploy/setup.sh`](deploy/setup.sh)，支持 Ubuntu + Nginx + systemd 一键部署。

## 手机 App 体验（PWA 纯前端模式 · v0.9.3）

无需后端服务器，数据全部存在浏览器 IndexedDB 中，可「添加到主屏幕」像原生 App 一样使用。

### GitHub Pages 部署（推荐，免费）

1. 把仓库推送到 GitHub（`gh auth login` → `git push`）
2. 仓库 Settings → Pages → Source 选 **`main` branch / `/docs` folder**
3. 等待 1-2 分钟，访问 `https://<你的用户名>.github.io/<仓库名>/`
4. 手机浏览器打开上面的地址 → 浏览器菜单 → **添加到主屏幕**

### 本地体验

直接用浏览器打开 `backend/static/memory-vortex-prototype-v2-api.html` 即可。
PWA 模式下数据自动从 IndexedDB 加载，不需要启动 Python 后端。

### PWA 文件说明

| 文件 | 作用 |
|---|---|
| `docs/index.html` | PWA 入口（从 `backend/static/` 复制） |
| `docs/localdb.js` | IndexedDB 数据层 + fetch 全局拦截 + API 路由器 |
| `docs/manifest.json` | PWA 清单（名称/图标/显示模式） |
| `docs/sw.js` | Service Worker（离线缓存 app shell） |
| `docs/icon-192.png` / `icon-512.png` | 应用图标 |
| `docs/test_data.json` | 种子模板数据 |

> Python 后端模式（`backend/main.py`）仍然完整保留，两者可独立运行。

## License

MIT
