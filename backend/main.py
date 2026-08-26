# -*- coding: utf-8 -*-
"""
记忆漩涡 MemoryVortex · 后端服务（v0.9 · 登录注册体系）
================================================
演进（与 backend-arch-prompt.md 对齐）：
    v0.1  静态 JSON 数据源 → /api/app/bootstrap
    v0.2  AI 生成链路（llm.py，当前休眠，前端不触发）
    v0.4  SQLite 数据库持久化 + 记忆真实增删
    v0.5  ★ 安全闭环 + 性能基线 + 多视角/留言
    v0.6  ★ 纪念日模块入库
    v0.7  ★ 成长追踪模块入库
    v0.8  ★ 共建时间线/邀请入库 + 媒体上传（本版本）
    v0.8.1  创建记忆页（S05）支持多选照片/视频/实况导入
    v0.8.2  记忆记录卡片 + 详情 hero 默认展示第一张媒体（cover）
    v0.8.3  编辑记忆支持增删媒体（PATCH media 全量替换）+ 首页封面同步
    v0.8.4  创建记忆未写感受自动填「无」，不拦截保存
    v0.8.5  S03 聚合视图「全部/个人/情侣/友情/成长」场景 tab 切换修复
    v0.8.6  主页「记录」由底部弹窗改为常驻全屏页面（S04：导航栏 + 场景网格 + 底部 tab 栏，可自由返回）
    v0.9   ★ 登录注册体系（users/sessions 表 + Bearer 会话鉴权）

v0.9 变更：
- 新增接口：POST /api/auth/register（注册）、POST /api/auth/login（登录）、
  POST /api/auth/logout（登出）、GET/PUT/DELETE /api/auth/me（我的资料/改资料/注销）；
- 鉴权升级：写操作同时接受 Authorization: Bearer <token>（登录会话）与旧版
  X-API-Token（游客/本地模式）；中间件把当前用户解析到 request.state；
- 数据隔离：登录用户数据归属 owner=user:{id}，游客为 local；bootstrap 与各
  list 接口按当前 owner 过滤（seed 共享演示数据对所有人可见）；
- bootstrap 缓存改为按 owner 分桶，meta 新增 auth 字段（loggedIn + 用户资料），
  前端据此渲染「我的」页与登录态；
- 登录/注册时自动 adopt 游客阶段数据（db.adopt_local_data），数据不丢。

v0.8 变更：
- 新表 timeline_nodes + invite_members：情侣/友情时间线节点与共建成员真实入库；
- bootstrap 的 coupleTimeline/friendTimeline 节点、invites 成员、timelineHub
  卡片全部改为数据库派生（节点回链记忆时，视角/留言计数实时聚合）；
- 媒体上传：预签名直传（POST /api/v1/uploads/presign → PUT → 关联记忆），
  本地磁盘存储实现，结构对齐 OSS（替换见 uploads.py）；
- memories 新增 media 字段；接口 /api/v1/memories/{id}/media 关联已传文件；
- 前端 S11 节点回链记忆可进详情，S10 成员可移除，S07 详情展示/添加照片。

v0.7 变更：
- 新表 growth_subjects + growth_milestones（里程碑可选回链记忆）；
- bootstrap 的 growth 模块改为数据库派生：年龄（宝宝 · 2岁3个月）、
  「最近里程碑 · N天前」、时间轴副标题全部实时计算；
- 接口：/api/v1/growth/subjects 与 /subjects/{id}/milestones 的增删改查；
  删除主体时级联软删其里程碑；
- 前端 S13 新增/删除主体，S14 记录/删除里程碑，点击主体直达对应时间轴。

v0.6 变更：
- 新表 anniversaries + CRUD（GET/POST/PATCH/DELETE /api/v1/anniversaries）；
- bootstrap 的 anniversaries 模块改为数据库派生：倒计时/「已过N天」实时计算，
  公历月/日为锚点（农历仅展示标签，不参与计算）；
- 前端 S08 标记表单真实入库，S09 列表/下一个纪念日走真实数据。

v0.5 变更：
- 安全：写操作（POST/PUT/PATCH/DELETE /api/*）须携带 X-API-Token（401 拦截）；
        写接口按 IP 滑动窗口限流（30 次/分钟，429 拦截）；CORS 收窄到本机来源；
        删除按 owner_id 校验所有权（IDOR 防护的本地版）。
- 性能：memories 建索引；bootstrap 结果内存缓存（TTL 10s，写操作即失效）；
        记忆列表支持 limit/before_id 游标分页。
- 功能：多视角（perspectives）与留言（comments）真实入库；
        GET /api/v1/memories/{id} 返回详情（含视角与留言）；
        时间线卡片 meta 动态显示「N条多视角 · M条留言」。

数据流：
    /api/app/bootstrap = 静态模板模块 + 数据库派生模块（home.timeline /
    home.sceneView / otd）+ meta.apiToken（游客模式写令牌）+ meta.auth（登录态；
    多用户阶段鉴权走 Authorization: Bearer 登录会话，中间件层已就绪）
    记忆 CRUD 走 /api/v1/memories（统一响应包 {code, message, data}）

启动方式：
    python -m pip install -r requirements.txt
    python main.py     （或双击 start-server.bat）

数据库：
    SQLite 文件 data/memory_vortex.db；旧库自动迁移（补 owner_id 列 + 索引），
    升级 PostgreSQL：改 db.py 的 DATABASE_URL 一行即可。
"""

import json
import logging
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import db
import llm
import uploads

# ---------------------------------------------------------------------------
# 配置（后续迁移到环境变量 / pydantic-settings）
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "test_data.json"
STATIC_DIR = BASE_DIR / "static"          # 托管前端原型页面
HOST = "127.0.0.1"
PORT = 8000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("memory-vortex")

SCENE_NAMES = {
    "personal": "个人博物馆",
    "couple": "情侣空间",
    "friend": "友情空间",
    "growth": "成长追踪",
}


# ---------------------------------------------------------------------------
# 写操作令牌：环境变量 MC_API_TOKEN > auth_token.txt > 进程内随机生成
# （本地单用户阶段的桥接方案：令牌经同源 bootstrap 下发给前端；多用户后
#   替换为登录会话/JWT，中间件校验层保持不变）
# ---------------------------------------------------------------------------
def _load_or_create_token() -> str:
    tok = os.environ.get("MC_API_TOKEN", "").strip()
    if tok:
        return tok
    f = BASE_DIR / "auth_token.txt"
    if f.exists():
        tok = f.read_text(encoding="utf-8").strip()
        if tok:
            return tok
    tok = secrets.token_urlsafe(16)
    try:
        f.write_text(tok, encoding="utf-8")
        f.chmod(0o600)
        logger.info("已自动生成并保存 API 令牌 → %s", f)
    except OSError:
        logger.warning("未配置 MC_API_TOKEN / auth_token.txt，本次启动使用临时令牌（重启后变化）：%s", tok)
    return tok


API_TOKEN = _load_or_create_token()


# ---------------------------------------------------------------------------
# 限流器：内存滑动窗口（零依赖；多实例部署时换 Redis 令牌桶，接口不变）
# ---------------------------------------------------------------------------
class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_s: float) -> None:
        self.max_events = max_events
        self.window_s = window_s
        self._events: Dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._events[key]
            while q and q[0] <= now - self.window_s:
                q.popleft()
            if len(q) >= self.max_events:
                return False
            q.append(now)
            return True


WRITE_LIMITER = SlidingWindowLimiter(max_events=30, window_s=60.0)   # 30 次写/分钟/IP
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


# ---------------------------------------------------------------------------
# 静态模板加载（结构模板 + 非记忆模块的数据源 + llm 兜底数据）
# ---------------------------------------------------------------------------
class TemplateRepository:
    """静态模板：进程内缓存，支持热重载。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._cache: Dict[str, Any] | None = None

    def load(self, force_reload: bool = False) -> Dict[str, Any]:
        if self._cache is None or force_reload:
            if not self._path.exists():
                raise FileNotFoundError(f"数据文件不存在: {self._path}")
            with open(self._path, encoding="utf-8") as f:
                self._cache = json.load(f)
            logger.info("已加载模板文件: %s（%d 个模块）",
                        self._path.name, len(self._cache))
        return self._cache


template_repo = TemplateRepository(DATA_FILE)


# ---------------------------------------------------------------------------
# bootstrap 缓存（Cache-Aside：TTL 10s；任何写操作立即失效）
# v0.9：按 owner 分桶——不同登录用户/游客看到各自的数据视图
# ---------------------------------------------------------------------------
_BOOTSTRAP_CACHE: Dict[str, Dict[str, Any]] = {}
BOOTSTRAP_TTL_S = 10.0


def invalidate_bootstrap_cache() -> None:
    _BOOTSTRAP_CACHE.clear()


# ---------------------------------------------------------------------------
# 数据库 → 前端契约的派生逻辑（仓库层核心）
# ---------------------------------------------------------------------------
def _fmt_date(d: datetime) -> str:
    return f"{d.year}年{d.month}月{d.day}日"


def _fmt_hm(d: datetime) -> str:
    return f"{d.hour:02d}:{d.minute:02d}"


def _time_label(m: db.Memory, now: datetime) -> str:
    """展示用时间标签（详情页/卡片共用）。"""
    if m.precise_at is None:
        return m.fuzzy_label or "记不清的时间"
    if m.precise_at.year == now.year:
        return f"{m.precise_at.month}月{m.precise_at.day}日 {_fmt_hm(m.precise_at)}"
    return f"{m.precise_at.year}年{m.precise_at.month}月{m.precise_at.day}日 {_fmt_hm(m.precise_at)}"


def _memory_meta(m: db.Memory, pcount: int = 0, ccount: int = 0) -> str:
    """时间线卡片的 meta 行：种子用原始文案，用户数据按字段生成。"""
    if m.meta_override:
        return m.meta_override
    parts: list[str] = []
    if m.timestamp_type == "fuzzy":
        parts.append("模糊时间")
        if m.fuzzy_label:
            parts.append(m.fuzzy_label)
    else:
        parts.append("自定义时间戳" if m.source == "user" else "")
    if m.emotions:
        parts.append(" · ".join(m.emotions))
    # 互动计数（多视角/留言）
    engage: list[str] = []
    if pcount > 1:
        engage.append(f"{pcount}条多视角")
    if ccount > 0:
        engage.append(f"{ccount}条留言")
    if engage:
        parts.append(" · ".join(engage))
    return " · ".join(p for p in parts if p)


def _first_cover(m: db.Memory) -> dict | None:
    """记忆的首个媒体（封面）：照片/视频/实况取 media[0]，无媒体返回 None。

    v0.8.2：记忆记录卡片与详情页 hero 默认展示「传入的第一张媒体」，
    cover 直接复用媒体项 {key, url, kind}，kind 为扩展名（png/mov/…）。
    """
    media = m.media or []
    return media[0] if media else None


def _first_image_cover(m: db.Memory) -> dict | None:
    """记忆的首张图片媒体（跳过视频/音频/实况）；无图片返回 None。

    v0.9.4：纪念日卡片背景只用图片——若首个媒体是视频，背景会空白，
    故取 media 中第一个图片类型（png/jpg/jpeg/gif/webp）。
    """
    for item in (m.media or []):
        kind = (item.get("kind") or "").lower()
        if kind in ("png", "jpg", "jpeg", "gif", "webp"):
            return item
    return None


def _timeline_item(m: db.Memory, now: datetime,
                   pcount: int = 0, ccount: int = 0) -> dict:
    if m.precise_at is None:
        date_label = m.fuzzy_label or "记不清的时间"
    elif m.precise_at.year == now.year:
        date_label = f"{m.precise_at.month}月{m.precise_at.day}日 {_fmt_hm(m.precise_at)}"
    else:
        date_label = (f"{m.precise_at.year}年{m.precise_at.month}月"
                      f"{m.precise_at.day}日 {_fmt_hm(m.precise_at)}")
    return {
        "mid": m.id,
        "scene": m.scene,
        "time": _fmt_hm(m.precise_at) if m.precise_at else (m.fuzzy_note or m.fuzzy_label or ""),
        "feel": m.feel,
        "meta": _memory_meta(m, pcount, ccount),
        "dateLabel": date_label,
        "cover": _first_cover(m),
    }


def build_timeline(memories: list[db.Memory], now: datetime,
                   pcounts: dict[int, int] | None = None,
                   ccounts: dict[int, int] | None = None) -> list[dict]:
    """首页时间轴：按日期倒序分组；模糊时间记忆按标签归组，排在末尾。"""
    pcounts = pcounts or {}
    ccounts = ccounts or {}
    groups: list[dict] = []
    fuzzy: dict[str, list[dict]] = {}

    for m in memories:
        if m.timestamp_type == "fuzzy" or m.precise_at is None:
            label = m.fuzzy_label or "记不清的时间"
            fuzzy.setdefault(label, []).append(
                _timeline_item(m, now, pcounts.get(m.id, 0), ccounts.get(m.id, 0)))
            continue
        title = _fmt_date(m.precise_at)
        if (m.precise_at.year, m.precise_at.month, m.precise_at.day) == \
                (now.year, now.month, now.day):
            title += " · 今天"
        item = _timeline_item(m, now, pcounts.get(m.id, 0), ccounts.get(m.id, 0))
        if groups and groups[-1]["date"] == title:     # 已按时间倒序，同日期条目相邻
            groups[-1]["items"].append(item)
        else:
            groups.append({"date": title, "items": [item]})

    for label in sorted(fuzzy, reverse=True):
        groups.append({"date": label, "items": fuzzy[label]})
    return groups


def build_scene_view(memories: list[db.Memory], now: datetime,
                     pcounts: dict[int, int] | None = None,
                     ccounts: dict[int, int] | None = None) -> dict:
    """场景视图（记忆卡）：全部场景记忆倒序卡片，前端按「全部/个人/情侣/友情/成长」tab 过滤。"""
    pcounts = pcounts or {}
    ccounts = ccounts or {}
    cards = []
    for m in memories:
        time_str = (_fmt_hm(m.precise_at) if m.precise_at else (m.fuzzy_label or ""))
        if m.precise_at and (m.precise_at.year, m.precise_at.month, m.precise_at.day) == \
                (now.year, now.month, now.day):
            time_str = "今晚 " + time_str
        elif m.precise_at:
            time_str = f"{m.precise_at.month}月{m.precise_at.day}日 {time_str}"
        if m.precise_at is None:
            date_label = m.fuzzy_label or "记不清的时间"
        elif m.precise_at.year == now.year:
            date_label = f"{m.precise_at.month}月{m.precise_at.day}日 {_fmt_hm(m.precise_at)}"
        else:
            date_label = (f"{m.precise_at.year}年{m.precise_at.month}月"
                          f"{m.precise_at.day}日 {_fmt_hm(m.precise_at)}")
        cards.append({
            "mid": m.id,
            # v0.8.2：带媒体（照片/视频/实况）或语音才用带图卡片，否则纯文字卡
            "type": "media" if (m.media or m.voice) else "text",
            "time": time_str,
            "dateLabel": date_label,
            "scene": m.scene,
            "feel": m.feel,
            "voice": m.voice,
            "emotions": list(m.emotions or []),
            "cover": _first_cover(m),
            "meta": m.meta_override or (
                f"{ccounts.get(m.id, 0)}条留言" if ccounts.get(m.id, 0) else
                (m.fuzzy_label if m.timestamp_type == "fuzzy" else None)),
        })
    return {"groupTitle": f"{now.year}年{now.month}月", "cards": cards}


def build_otd(template_otd: dict, memories: list[db.Memory], now: datetime) -> dict:
    """往年今日：仅展示数据库中同月同日（往年）的真实记忆。

    v0.9.3：不再把模板里的演示卡片（婚礼前夜/搬来上海/大学聚会等假数据）
    拼进响应——新用户看到的是真实的空状态。
    """
    otd = deepcopy(template_otd)
    cards = []
    for m in memories:
        if (m.precise_at is None or m.precise_at.year >= now.year
                or m.precise_at.month != now.month or m.precise_at.day != now.day):
            continue
        years_ago = now.year - m.precise_at.year
        cards.append({
            "scene": m.scene,
            "date": m.precise_at.strftime("%Y.%m.%d"),
            "feel": m.feel,
            "meta": f"{years_ago}年前 · " + (" · ".join(m.emotions) if m.emotions else SCENE_NAMES.get(m.scene, m.scene)),
        })
    otd["cards"] = cards
    otd["title"] = f"{now.month}月{now.day}日 · 往年今日"
    return otd


def _anniv_date(year: int, month: int, day: int) -> datetime | None:
    """构造某年的周年日；2月29日在非闰年顺延到3月1日。"""
    try:
        return datetime(year, month, day)
    except ValueError:
        if month == 2 and day == 29:
            return datetime(year, 3, 1)
        return None      # 非法月/日（接口层已校验，此处兜底）


def _anniv_cover_map(annivs: list[db.Anniversary]) -> dict[int, dict | None]:
    """纪念日 → 关联记忆封面映射（{mid: cover}）；关联记忆已删/无媒体 → None。

    v0.9.2：纪念日卡片背景用「该纪念日里的照片」，即关联记忆的首个媒体。
    """
    cmap: dict[int, dict | None] = {}
    for a in annivs:
        if a.linked_memory_id:
            m = db.get_memory(a.linked_memory_id)
            cmap[a.linked_memory_id] = _first_image_cover(m) if m else None
    return cmap


def build_anniversaries(annivs: list[db.Anniversary], now: datetime,
                        cover_map: dict[int, dict | None] | None = None) -> dict:
    """纪念日视图：下一个纪念日 + 全量列表（倒计时实时计算）。

    规则（公历月/日锚点）：
    - 每年重复：取未来最近一次周年日，daysLeft = 距今天数（0 = 今天）；
    - 一次性：今年周年日未到 → daysLeft 倒计时；已过 → daysLeft 置空、note 记「已过 N 天」；
    - 列表排序：未过的在前（daysLeft 升序），已过的一次性在后；
      next 取第一个未过的条目，全都已经过则取列表第一项（展示「已过」）。
    """
    items: list[dict] = []
    today = now.date()
    for a in annivs:
        this_year = _anniv_date(now.year, a.month, a.day)
        nxt: datetime | None = None
        if this_year is not None and this_year.date() >= today:
            nxt = this_year
        elif a.is_recurring:
            nxt = _anniv_date(now.year + 1, a.month, a.day)
        if nxt is not None:
            days_left = (nxt.date() - today).days
            suffix = "就是今天" if days_left == 0 else f"还有 {days_left} 天"
            note = f"每年重复 · {suffix}" if a.is_recurring else suffix
        else:
            days_left = None
            passed = (today - this_year.date()).days if this_year else 0
            note = f"已过 {passed} 天"
        if nxt is not None:
            date_label = f"{nxt.year}年{nxt.month}月{nxt.day}日"
        else:
            date_label = f"{this_year.year}年{this_year.month}月{this_year.day}日" if this_year else ""
        if a.lunar_label:
            date_label += f" · {a.lunar_label}"
        elif a.is_lunar:
            date_label += " · 农历"
        items.append({
            "id": a.id,
            "mid": a.linked_memory_id,
            "day": str(a.day),
            "month": f"{a.month}月",
            "name": a.name,
            "note": note,
            "daysLeft": days_left,
            "recurring": a.is_recurring,
            "dateLabel": date_label,
            "date": date_label,          # 兼容 next.date 契约
            "cover": (cover_map or {}).get(a.linked_memory_id)
                     if a.linked_memory_id is not None else None,
        })
    items.sort(key=lambda x: (x["daysLeft"] is None,
                              x["daysLeft"] if x["daysLeft"] is not None else 10 ** 6))
    next_item = next((x for x in items if x["daysLeft"] is not None), None)
    if next_item is None and items:
        next_item = items[0]             # 全部已过：仍展示最近一条（「已过 N 天」）
    if next_item is not None:
        next_view = {"name": next_item["name"],
                     "daysLeft": next_item["daysLeft"] if next_item["daysLeft"] is not None else 0,
                     "date": next_item["dateLabel"],
                     "cover": next_item["cover"]}   # v0.9.2：下一个纪念日大卡背景照片
    else:
        next_view = {"name": "还没有纪念日", "daysLeft": 0, "date": "点击右上角 + 标记第一条"}
    return {"next": next_view, "count": len(items), "list": items}


# ---------------------------------------------------------------------------
# 成长追踪视图派生
# ---------------------------------------------------------------------------
GROWTH_KIND_NAMES = {"baby": "宝宝", "pet": "宠物", "other": "成长主体"}
GROWTH_KIND_ICONS = {"baby": "baby", "pet": "pet", "other": "baby"}   # 前端图标键


def _age_label(birthday: date, today: date) -> str:
    """年龄展示：2岁3个月 / 1岁 / 8个月 / 12天（出生不久）。"""
    if birthday > today:
        return "刚记录"
    years = today.year - birthday.year
    months = today.month - birthday.month - (1 if today.day < birthday.day else 0)
    if months < 0:
        years -= 1
        months += 12
    if years > 0:
        return f"{years}岁{months}个月" if months > 0 else f"{years}岁"
    if months > 0:
        return f"{months}个月"
    days = (today - birthday).days
    return f"{days}天" if days > 0 else "今天出生"


def _days_rel_label(days: int) -> str:
    """相对时间：今天 / 昨天 / N天前（超过一年不标注，返回空串）。"""
    if days <= 0:
        return "今天"
    if days == 1:
        return "昨天"
    if days <= 365:
        return f"{days}天前"
    return ""


def _fmt_cn_date(d: date) -> str:
    return f"{d.year}年{d.month}月{d.day}日"


def _growth_milestone_view(ms: db.GrowthMilestone, today: date) -> dict:
    date_label = ms.happened_on.strftime("%Y.%m.%d")
    rel = _days_rel_label((today - ms.happened_on).days)
    if rel:
        date_label += f" · {rel}"
    return {
        "id": ms.id,
        "mid": ms.memory_id,
        "date": date_label,
        "title": ms.title,
        "desc": ms.content or "",
        "major": ms.is_major,
        "pic": ms.has_pic,
        "go": ms.memory_id is not None,     # 有回链记忆才可点进详情
    }


def build_growth(desc: str, subjects: list[db.GrowthSubject],
                 milestones: list[db.GrowthMilestone], now: datetime) -> dict:
    """成长追踪视图：主体卡片（meta/最近里程碑）+ 各主体时间轴（实时派生）。

    - meta：类型 · 备注(品种) · 年龄（年龄由 birthday 实时算，模板静态值作废）；
    - milestone 行：最近一条里程碑标题 + 相对时间；
    - timelines 以主体名分组（前端切换器契约）；排序由 SQL（日期倒序）保证。
    """
    today = now.date()
    by_subject: dict[int, list[db.GrowthMilestone]] = {}
    for ms in milestones:
        by_subject.setdefault(ms.subject_id, []).append(ms)

    subj_views: list[dict] = []
    timelines: dict[str, dict] = {}
    for s in subjects:
        age = _age_label(s.birthday, today) if s.birthday else None
        kind_name = GROWTH_KIND_NAMES.get(s.kind, "成长主体")
        meta_parts = [kind_name] + ([s.note] if s.note else []) + ([age] if age else [])
        ms_list = by_subject.get(s.id, [])

        latest = ms_list[0] if ms_list else None      # 列表已按日期倒序
        if latest is not None:
            rel = _days_rel_label((today - latest.happened_on).days) or "很久以前"
            milestone_str = f"最近里程碑：{latest.title} · {rel}"
        else:
            milestone_str = "还没有里程碑，记录第一条吧"

        subj_views.append({
            "id": s.id,
            "name": s.name,
            "icon": GROWTH_KIND_ICONS.get(s.kind, "baby"),
            "kind": s.kind,
            "meta": " · ".join(meta_parts),
            "milestone": milestone_str,
        })

        if s.birthday and s.birth_label:
            subtitle = f"{age} · {s.birth_label}"
        elif s.birthday:
            subtitle = f"{age} · 出生于 {_fmt_cn_date(s.birthday)}"
        else:
            subtitle = s.birth_label or s.name
        timelines[s.name] = {
            "id": s.id,
            "subtitle": subtitle,
            "milestones": [_growth_milestone_view(ms, today) for ms in ms_list],
        }
    return {"desc": desc, "subjects": subj_views, "timelines": timelines}


# ---------------------------------------------------------------------------
# 共建时间线 / 邀请 / 时间线枢纽视图派生
# ---------------------------------------------------------------------------
def _timeline_node_view(n: db.TimelineNode,
                        pcounts: dict[int, int],
                        ccounts: dict[int, int]) -> dict:
    """单个节点视图：d = 日期 [+ 视角/留言计数]。

    有回链记忆时用 perspectives/comments 实时计数（真实数据）；
    无回链时回退到模板 badge_hint（演示计数）。
    """
    parts: list[str] = []
    if n.date_str:
        parts.append(n.date_str)
    if n.memory_id is not None:
        pc = pcounts.get(n.memory_id, 0)
        cc = ccounts.get(n.memory_id, 0)
        hints = []
        if pc > 1:
            hints.append(f"{pc}视角")
        if cc > 0:
            hints.append(f"{cc}留言")
        if hints:
            parts.append(" · ".join(hints))
    elif n.badge_hint:
        parts.append(n.badge_hint)
    return {
        "k": n.node_key,
        "mid": n.memory_id,
        "icon": n.icon,
        "n": n.title,
        "d": " · ".join(parts),
        "s": n.desc or "",
        "node": [n.node_x, n.node_y],
        "label": [n.label_x, n.label_y],
        "latest": n.is_latest,
    }


def build_timeline_view(tpl: dict, nodes: list[db.TimelineNode], now: datetime,
                        pcounts: dict[int, int] | None = None,
                        ccounts: dict[int, int] | None = None) -> dict:
    """情侣/友情共建时间线：保留模板的 pair/group 头卡与徽章装饰坐标，
    节点替换为数据库真实数据（含实时视角/留言计数与回链 mid）。"""
    view = deepcopy(tpl)
    pcounts = pcounts or {}
    ccounts = ccounts or {}
    view["nodes"] = [_timeline_node_view(n, pcounts, ccounts) for n in nodes]
    return view


def build_invites(tpl: dict, members: list[db.InviteMember]) -> dict:
    """共建邀请：成员列表（情侣待接受 + 友情成员）走数据库，邀请码/容量保留模板。"""
    inv = deepcopy(tpl)
    couple = [m for m in members if m.space == "couple"]
    friend = [m for m in members if m.space == "friend"]
    inv["couple"]["pending"] = [_invite_member_view(m) for m in couple]
    inv["friend"]["members"] = [_invite_member_view(m) for m in friend]
    return inv


def _invite_member_view(m: db.InviteMember) -> dict:
    return {
        "id": m.id,
        "name": m.name,
        "avatar": m.avatar or m.name[:1],
        "bg": m.bg,
        "state": m.state,
        "note": m.note,
    }


def build_timeline_hub(tpl_hub: dict, couple_tpl: dict, friend_tpl: dict,
                       couple_nodes: list[db.TimelineNode],
                       friend_nodes: list[db.TimelineNode],
                       memories: list[db.Memory],
                       growth_subjects: list | None = None,
                       growth_milestones: list | None = None,
                       now: datetime | None = None) -> dict:
    """时间线枢纽：couple/friend/growth 卡的记忆数、最近节点、里程碑实时派生，其余保留模板。"""
    hub = deepcopy(tpl_hub)
    couple_count = sum(1 for m in memories if m.scene == "couple")
    friend_count = sum(1 for m in memories if m.scene == "friend")
    pair = couple_tpl.get("pair") or {}
    group = friend_tpl.get("group") or {}
    latest_c = max(couple_nodes, key=lambda n: n.sort_order) if couple_nodes else None
    latest_f = max(friend_nodes, key=lambda n: n.sort_order) if friend_nodes else None
    # growth 卡：主体数 + 最近里程碑
    g_subs = growth_subjects or []
    g_ms = growth_milestones or []
    latest_ms = max(g_ms, key=lambda m: m.created_at) if g_ms else None
    for card in hub.get("cards", []):
        if card.get("type") == "couple":
            card["meta"] = f"情侣时间轴 · {couple_count} 条记忆 · 1对1共建"
            card["last"] = (f"最近：{latest_c.title} · 今天" if latest_c
                            else "最近：暂无节点")
        elif card.get("type") == "friend":
            card["meta"] = f"友情时间轴 · 1人共建 · {friend_count} 条记忆"
            card["last"] = (f"最近：{latest_f.title} · 今天" if latest_f
                            else "最近：暂无节点")
        elif card.get("type") == "growth":
            card["meta"] = f"成长时间轴 · {len(g_subs)} 个独立主体"
            card["last"] = (f"最近里程碑：{latest_ms.title}" if latest_ms
                            else "最近里程碑：暂无")
    return hub


def compose_bootstrap(owner: str = db.LOCAL_OWNER,
                      user: db.User | None = None,
                      force: bool = False) -> dict:
    """聚合启动数据：静态模板 + 数据库派生，结构与 test_data 契约对齐（按 owner 分桶缓存）。"""
    now_mono = time.monotonic()
    bucket = _BOOTSTRAP_CACHE.get(owner)
    if (not force and bucket is not None
            and now_mono - bucket["ts"] < BOOTSTRAP_TTL_S):
        return bucket["data"]

    data = deepcopy(template_repo.load())
    now = datetime.now()
    memories = db.list_memories(owner=owner)
    pcounts, ccounts = db.engagement_counts()

    data["home"]["timeline"] = build_timeline(memories, now, pcounts, ccounts)
    data["home"]["sceneView"] = build_scene_view(memories, now, pcounts, ccounts)
    data["otd"] = build_otd(data.get("otd", {}), memories, now)
    annivs = db.list_anniversaries(owner=owner)
    data["anniversaries"] = build_anniversaries(annivs, now, cover_map=_anniv_cover_map(annivs))
    data["growth"] = build_growth(
        (data.get("growth") or {}).get("desc", "为宝宝和宠物分别建立独立成长时间轴，系统自动归类里程碑"),
        db.list_growth_subjects(owner=owner), db.list_growth_milestones(owner=owner), now)
    # 共建时间线：节点走数据库（含实时视角/留言计数），pair/group 与徽章坐标保留模板
    tl_nodes = db.list_timeline_nodes(owner=owner)
    couple_nodes = [n for n in tl_nodes if n.kind == "couple"]
    friend_nodes = [n for n in tl_nodes if n.kind == "friend"]
    data["coupleTimeline"] = build_timeline_view(
        data.get("coupleTimeline", {}), couple_nodes, now, pcounts, ccounts)
    data["friendTimeline"] = build_timeline_view(
        data.get("friendTimeline", {}), friend_nodes, now, pcounts, ccounts)
    # 共建邀请：成员走数据库，邀请码/容量保留模板
    data["invites"] = build_invites(data.get("invites", {}), db.list_invite_members(owner=owner))
    # 时间线枢纽：couple/friend/growth 卡记忆数、最近节点、里程碑实时派生
    g_subs = db.list_growth_subjects(owner=owner)
    g_ms = db.list_growth_milestones(owner=owner)
    data["timelineHub"] = build_timeline_hub(
        data.get("timelineHub", {}), data.get("coupleTimeline", {}),
        data.get("friendTimeline", {}), couple_nodes, friend_nodes, memories,
        g_subs, g_ms, now)
    # v0.9.3：清除模板演示假数据 —— 共建时间线的 pair/group 头卡换成中性占位，
    # 螺旋上的多视角/留言徽章坐标清空（真实计数已由节点 d 字段实时派生）
    if isinstance(data.get("coupleTimeline"), dict):
        data["coupleTimeline"]["pair"] = {
            "left": {"name": "我", "avatar": "我"},
            "right": {"name": "待邀请", "avatar": "邀", "bg": "#F2EBE3"},
            "title": "情侣时间线", "sub": "邀请一位伙伴，共建专属时间线", "badge": "待共建",
        }
        data["coupleTimeline"]["multiViewBadges"] = []
        data["coupleTimeline"]["commentBadges"] = []
    if isinstance(data.get("friendTimeline"), dict):
        data["friendTimeline"]["group"] = {
            "avatars": [{"t": "我"}], "more": 0,
            "title": "友情时间线", "sub": "邀请最多 5 位好友，共建群组记忆线", "badge": "待共建",
        }
        data["friendTimeline"]["multiViewBadges"] = []
        data["friendTimeline"]["commentBadges"] = []
    # v0.9.3：时间设置 —— "现在"标签与滚轮默认值都取服务器当前时间，
    # 年份数组动态生成（近 8 年，含今年），不再使用模板写死的 2026/8/24
    ts = data.setdefault("timeSettings", {})
    ts.setdefault("now", {})["label"] = f"现在 · {now.month}月{now.day}日 {now.hour:02d}:{now.minute:02d}"
    wheels = ts.setdefault("wheels", {})
    wheels["years"] = [str(y) for y in range(now.year - 7, now.year + 1)]
    wheels.setdefault("dayCount", 31)
    wheels["default"] = {
        "year": str(now.year), "month": f"{now.month}月", "day": str(now.day),
        "hour": f"{now.hour:02d}:00", "minute": f"{now.minute:02d}",
    }
    data["meta"]["note"] = f"真实数据模式 · SQLite 数据库 · {len(memories)} 条记忆"
    data["meta"]["apiToken"] = API_TOKEN      # 游客/本地模式写令牌
    data["meta"]["auth"] = {
        "loggedIn": user is not None,
        "owner": owner,
        "user": _user_brief(user) if user else None,
    }
    data["meta"]["version"] = "3.3"   # v0.9.3：登录引导/种子清除/真录音/100MB/时间修复

    _BOOTSTRAP_CACHE[owner] = {"data": data, "ts": now_mono}
    return data


# ---------------------------------------------------------------------------
# 应用生命周期：建库 + 迁移 + 种子导入
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        db.init_db(template_repo.load())
        logger.info("服务启动完成，数据库就绪")
    except Exception as exc:
        logger.error("数据库初始化失败: %s", exc)
        raise
    yield
    logger.info("服务关闭")


app = FastAPI(
    title="MemoryVortex API",
    version="0.8.0",
    description="记忆漩涡后端 · 安全与性能基线 + 多视角/留言 + 纪念日 + 成长追踪 + 共建时间线 + 媒体上传",
    lifespan=lifespan,
)

# CORS：收窄到本机来源（同源托管页面实际不触发 CORS；"null" 兼容 file:// 直开）
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000", "http://localhost:8000",
        "http://127.0.0.1:8778", "http://localhost:8778",
        "null",
    ],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Token", "Authorization"],
)


# ---------------------------------------------------------------------------
# 身份解析：Authorization: Bearer <会话令牌> → 登录用户；否则游客/本地模式
# ---------------------------------------------------------------------------
def _resolve_auth(request: Request) -> tuple[str, db.User | None]:
    """解析当前请求身份，返回 (owner, user|None)。

    - 有效会话 → (user:{id}, User)：登录用户，数据隔离；
    - 无/无效令牌 → (local, None)：游客/本地模式（兼容旧版 X-API-Token）。
    结果挂到 request.state，供各端点依赖 current_owner 读取（避免重复解析）。
    """
    request.state.user = None
    request.state.owner = db.LOCAL_OWNER
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        user = db.get_session_user(token)
        if user is not None:
            request.state.user = user
            request.state.owner = db.user_owner_id(user.id)
    return request.state.owner, request.state.user


def current_owner(request: Request) -> str:
    """FastAPI 依赖：取中间件解析好的当前数据所有者标识。"""
    return getattr(request.state, "owner", db.LOCAL_OWNER)


def _memory_visible(mid: int, owner: str) -> db.Memory | None:
    """返回当前身份可见的记忆（存在 + 未删 + 属主为 seed 或 owner），否则 None。

    用于详情/视角/留言/媒体等按 id 访问的接口，统一封死 IDOR 越权。
    """
    mem = db.get_memory(mid)
    if mem is None or mem.owner_id not in (db.SEED_OWNER, owner):
        return None
    return mem


# 公开接口：注册/登录无需令牌（其余写操作仍需鉴权）
PUBLIC_WRITE_PATHS = {"/api/auth/register", "/api/auth/login"}


# ---------------------------------------------------------------------------
# 安全中间件：写操作鉴权（Bearer 会话 或 旧版 X-API-Token）+ 按 IP 限流
# ---------------------------------------------------------------------------
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    path = request.url.path
    is_api = path.startswith("/api/")
    if is_api:
        owner, user = _resolve_auth(request)   # 顺便为端点准备身份
    if request.method in WRITE_METHODS and is_api:
        ip = request.client.host if request.client else "unknown"
        if not WRITE_LIMITER.allow(ip):
            logger.warning("限流触发：%s %s 来自 %s", request.method, path, ip)
            return JSONResponse(
                {"code": 429, "message": "请求过于频繁，请稍后再试"},
                status_code=429)
        # 鉴权：登录会话（Bearer）或 游客/本地模式（X-API-Token）任一有效即可；
        # 注册/登录为公开接口，跳过令牌校验（仍受限流保护，防暴力尝试）
        if path not in PUBLIC_WRITE_PATHS:
            has_bearer = getattr(request.state, "user", None) is not None
            has_legacy = request.headers.get("x-api-token") == API_TOKEN
            if not (has_bearer or has_legacy):
                return JSONResponse(
                    {"code": 401, "message": "未授权：请先登录或携带有效的 X-API-Token"},
                    status_code=401)
    return await call_next(request)


# ---------------------------------------------------------------------------
# 统一响应包：{code, message, data}
# 注意：/api/app/bootstrap 返回裸数据，与前端 loadAppData() 契约对齐
# ---------------------------------------------------------------------------
def ok(data: Any, status: int = 200) -> JSONResponse:
    return JSONResponse({"code": 0, "message": "ok", "data": data}, status_code=status)


# ---------------------------------------------------------------------------
# 基础路由
# ---------------------------------------------------------------------------
@app.get("/health")
async def health() -> Dict[str, str]:
    """健康检查（容器/K8s 就绪探针预留）。"""
    return {"status": "up"}


@app.get("/api/app/bootstrap")
async def app_bootstrap(request: Request) -> Dict[str, Any]:
    """应用启动数据：静态模板模块 + 数据库派生模块（结构对齐 test_data 契约）。

    v0.9：按当前登录态（Authorization: Bearer 会话）返回对应 owner 的数据视图，
    meta.auth 携带登录用户资料。
    """
    owner, user = _resolve_auth(request)
    try:
        return compose_bootstrap(owner=owner, user=user)
    except FileNotFoundError as exc:
        logger.error("启动数据不可用: %s", exc)
        raise HTTPException(status_code=503, detail="启动数据不可用") from exc


@app.post("/api/app/reload")
async def reload_data() -> JSONResponse:
    """开发辅助：热重载模板 JSON（仅本地开发用，上线前移除）。"""
    try:
        template_repo.load(force_reload=True)
        invalidate_bootstrap_cache()
        return ok({"reloaded": True})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"重载失败: {exc}") from exc


# ---------------------------------------------------------------------------
# 登录注册体系（v0.9）：注册 / 登录 / 登出 / 我的资料
# 密码安全：PBKDF2-HMAC-SHA256 + 随机盐（db.hash_password，零第三方依赖）
# 会话：Bearer token（db.sessions 表，登出吊销、30 天过期）
# ---------------------------------------------------------------------------
USERNAME_RE = re.compile(r"^[\w\u4e00-\u9fa5]{3,32}$")


class RegisterIn(BaseModel):
    """注册入参。"""

    username: str = Field(description="登录账号（3-32 位中英文/数字/下划线）")
    password: str = Field(min_length=6, max_length=64, description="密码（至少 6 位）")
    nickname: str | None = Field(default=None, max_length=32, description="昵称（缺省取账号名）")
    avatar: str | None = Field(default=None, max_length=4, description="头像字（单字，可选）")


class LoginIn(BaseModel):
    """登录入参。"""

    username: str = Field(min_length=1, max_length=32, description="登录账号")
    password: str = Field(min_length=1, max_length=64, description="密码")


class ProfileUpdate(BaseModel):
    """更新我的资料（PATCH 语义）。"""

    nickname: str | None = Field(default=None, min_length=1, max_length=32, description="昵称")
    avatar: str | None = Field(default=None, max_length=4, description="头像字（单字；传空串清除）")


def _user_brief(u: db.User) -> dict:
    """用户序列化（不含任何敏感字段）。"""
    return {
        "id": u.id,
        "username": u.username,
        "nickname": u.nickname or u.username,
        "avatar": u.avatar,
        "createdAt": u.created_at.strftime("%Y-%m-%d"),
    }


def _require_login(request: Request) -> db.User:
    """取当前登录用户；未登录抛 401。"""
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    return user


@app.post("/api/auth/register", status_code=201)
async def auth_register(req: RegisterIn) -> JSONResponse:
    """注册新账号：校验 → 建号 → 游客数据归属迁移 → 签发会话。"""
    username = req.username.strip()
    if not USERNAME_RE.match(username):
        raise HTTPException(
            status_code=422,
            detail="账号仅支持 3-32 位中英文、数字、下划线")
    if db.get_user_by_username(username) is not None:
        raise HTTPException(status_code=409, detail="该账号已被注册")
    user = db.create_user(username, req.password, nickname=req.nickname, avatar=req.avatar)
    adopted = db.adopt_local_data(user.id)
    token = db.create_session(user.id)
    invalidate_bootstrap_cache()
    logger.info("新用户注册：%s（id=%d，接手游客数据 %d 条）", username, user.id, adopted)
    return ok({"token": token, "user": _user_brief(user)}, status=201)


@app.post("/api/auth/login")
async def auth_login(req: LoginIn) -> JSONResponse:
    """登录：校验密码 → 游客数据归属迁移 → 签发会话。"""
    user = db.get_user_by_username(req.username.strip())
    if user is None or not db.verify_password(req.password, user.salt, user.password_hash):
        # 统一错误文案，不泄露「账号是否存在」
        raise HTTPException(status_code=401, detail="账号或密码错误")
    adopted = db.adopt_local_data(user.id)
    token = db.create_session(user.id)
    invalidate_bootstrap_cache()
    logger.info("用户登录：%s（id=%d，接手游客数据 %d 条）", user.username, user.id, adopted)
    return ok({"token": token, "user": _user_brief(user)})


@app.post("/api/auth/logout")
async def auth_logout(request: Request) -> JSONResponse:
    """登出：吊销当前会话令牌（幂等，未登录也返回成功）。"""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        db.delete_session(auth[7:].strip())
        logger.info("用户登出，会话已吊销")
    return ok({"loggedOut": True})


@app.get("/api/auth/me")
async def auth_me(request: Request) -> JSONResponse:
    """我的资料（登录态校验；前端启动时用它验证会话有效性）。"""
    return ok(_user_brief(_require_login(request)))


@app.put("/api/auth/me")
async def auth_update_me(request: Request, req: ProfileUpdate) -> JSONResponse:
    """更新我的资料（昵称/头像字）。"""
    user = _require_login(request)
    patch: dict[str, Any] = {}
    if req.nickname is not None:
        nickname = req.nickname.strip()
        if not nickname:
            raise HTTPException(status_code=422, detail="昵称不能为空")
        patch["nickname"] = nickname
    if req.avatar is not None:
        avatar = req.avatar.strip()
        if len(avatar) > 4:
            raise HTTPException(status_code=422, detail="头像字最多 4 个字符")
        patch["avatar"] = avatar or None
    updated = db.update_user(user.id, **patch)
    if updated is None:
        raise HTTPException(status_code=404, detail="账号不存在或已注销")
    invalidate_bootstrap_cache()
    logger.info("更新资料：%s（字段：%s）", user.username, ",".join(patch.keys()))
    return ok(_user_brief(updated))


@app.delete("/api/auth/me")
async def auth_delete_me(request: Request) -> JSONResponse:
    """注销账号：软删除用户 + 吊销全部会话 + 清空各视图缓存。"""
    user = _require_login(request)
    db.soft_delete_user(user.id)
    invalidate_bootstrap_cache()
    logger.info("账号注销：%s（id=%d）", user.username, user.id)
    return ok({"deleted": True})


# ---------------------------------------------------------------------------
# 记忆 CRUD（阶段③：真实数据；阶段⑤：鉴权/限流/分页/详情）
# ---------------------------------------------------------------------------
class MediaItemIn(BaseModel):
    """创建记忆时携带的媒体项（文件已通过预签名直传落盘）。"""

    file_key: str = Field(description="上传返回的 fileKey")


class MemoryCreate(BaseModel):
    """新建记忆入参（对应前端 S05/S06 创建表单）。"""

    scene: str = Field(description="场景: personal/couple/friend/growth")
    feel: str = Field(min_length=1, max_length=2000, description="感受文字")
    emotion: str | None = Field(default=None, description="情绪标签（单选）")
    time_mode: str = Field(default="now", description="时间模式: now/custom/fuzzy")
    custom_date: str | None = Field(default=None, description="自定义日期 YYYY-MM-DD")
    custom_time: str | None = Field(default=None, description="自定义时刻 HH:MM")
    fuzzy_label: str | None = Field(default=None, description="模糊时间预设，如 去年夏天")
    fuzzy_note: str | None = Field(default=None, description="模糊时间补充描述")
    voice: str | None = Field(default=None, description="语音时长展示（暂为占位）")
    media: list[MediaItemIn] | None = Field(default=None, description="随记忆携带的媒体附件（照片/视频/实况）")


@app.get("/api/v1/memories")
async def list_memories_api(scene: str | None = Query(default=None),
                            limit: int = Query(default=100, ge=1, le=500),
                            before_id: int | None = Query(default=None),
                            owner: str = Depends(current_owner)) -> JSONResponse:
    """记忆列表（未删除；可按场景过滤；limit/before_id 游标分页；按当前身份隔离）。"""
    if scene is not None and scene not in db.SCENES:
        raise HTTPException(status_code=422, detail=f"非法场景: {scene}")
    memories = db.list_memories(scene, owner=owner, limit=limit, before_id=before_id)
    pcounts, ccounts = db.engagement_counts()
    return ok([_memory_brief(m, pcounts.get(m.id, 0), ccounts.get(m.id, 0))
               for m in memories])


@app.get("/api/v1/memories/{mid}")
async def get_memory_api(mid: int,
                         owner: str = Depends(current_owner)) -> JSONResponse:
    """记忆详情：本体 + 多视角 + 留言（前端 S07 详情页数据源；越权访问按不存在处理）。"""
    mem = _memory_visible(mid, owner)
    if mem is None:
        raise HTTPException(status_code=404, detail=f"记忆不存在: {mid}")
    now = datetime.now()
    perspectives = db.list_perspectives(mid)
    comments = db.list_comments(mid)
    detail = _memory_brief(mem, len(perspectives), len(comments))
    detail.update({
        "timeLabel": _time_label(mem, now),
        "perspectives": [_perspective_brief(p) for p in perspectives],
        "comments": [_comment_brief(c) for c in comments],
    })
    return ok(detail)


@app.post("/api/v1/memories", status_code=201)
async def create_memory_api(req: MemoryCreate,
                            owner: str = Depends(current_owner)) -> JSONResponse:
    """新建记忆：精确/模糊双时间戳按 time_mode 归一化落库（归属当前身份）。"""
    if req.scene not in db.SCENES:
        raise HTTPException(status_code=422, detail=f"非法场景: {req.scene}")
    if req.time_mode not in db.TIME_MODES:
        raise HTTPException(status_code=422, detail=f"非法时间模式: {req.time_mode}")

    kw: dict[str, Any] = {
        "scene": req.scene,
        "feel": req.feel.strip(),
        "emotions": [req.emotion] if req.emotion else [],
        "voice": req.voice,
        "source": "user",
        "owner_id": owner,
    }

    try:
        if req.time_mode == "fuzzy":
            kw.update(timestamp_type="fuzzy",
                      precise_at=None,
                      fuzzy_label=req.fuzzy_label or "记不清了",
                      fuzzy_note=(req.fuzzy_note or "").strip() or None)
        else:
            # now / custom 统一归一化为精确时间
            if req.time_mode == "now":
                dt = datetime.now()
            else:
                date_s = req.custom_date or datetime.now().strftime("%Y-%m-%d")
                time_s = req.custom_time or datetime.now().strftime("%H:%M")
                dt = datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H:%M")
            kw.update(timestamp_type="precise", precise_at=dt,
                      fuzzy_label=None, fuzzy_note=None)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"时间格式非法: {exc}") from exc

    # 随记忆携带的媒体：逐个校验 fileKey（与 attach 接口同一防线），构造 {key, url, kind}
    media_items: list[dict[str, Any]] = []
    for item in (req.media or []):
        key = item.file_key.strip()
        if not re.fullmatch(r"[0-9a-f]{24}\.[a-z0-9]+", key):
            raise HTTPException(status_code=422, detail=f"非法文件标识: {key}")
        media_items.append({"key": key, "url": uploads.resolve_url(key),
                            "kind": key.rsplit(".", 1)[-1]})
    if media_items:
        kw["media"] = media_items

    mem = db.create_memory(**kw)
    invalidate_bootstrap_cache()
    logger.info("新建记忆 #%d（场景 %s，模式 %s，媒体 %d 项）",
                mem.id, mem.scene, req.time_mode, len(media_items))
    return ok(_memory_brief(mem), status=201)


@app.delete("/api/v1/memories/{mid}")
async def delete_memory_api(mid: int,
                            owner: str = Depends(current_owner)) -> JSONResponse:
    """删除记忆（软删除 + 所有权校验，符合数据合规的先软删后清除策略）。"""
    if not db.soft_delete_memory(mid, owner=owner):
        raise HTTPException(status_code=404, detail=f"记忆不存在: {mid}")
    invalidate_bootstrap_cache()
    logger.info("删除记忆 #%d（软删除）", mid)
    return ok({"id": mid, "deleted": True})


class MemoryUpdate(BaseModel):
    """编辑记忆入参（PATCH 语义：仅传入的字段会被更新）。

    time_mode 传入时会按与新建相同的规则归一化精确/模糊时间戳；
    time_mode 不传则保持原时间戳不变。
    """

    scene: str | None = Field(default=None, description="场景")
    feel: str | None = Field(default=None, min_length=1, max_length=2000, description="感受文字")
    emotion: str | None = Field(default=None, description="情绪标签（单选，传空串清空）")
    time_mode: str | None = Field(default=None, description="时间模式: now/custom/fuzzy")
    custom_date: str | None = Field(default=None, description="自定义日期 YYYY-MM-DD")
    custom_time: str | None = Field(default=None, description="自定义时刻 HH:MM")
    fuzzy_label: str | None = Field(default=None, description="模糊时间预设")
    fuzzy_note: str | None = Field(default=None, description="模糊时间补充描述")
    media: list[MediaItemIn] | None = Field(default=None, description="媒体全量替换（传完整数组；空数组=清空全部媒体；不传=保持不变）")


@app.patch("/api/v1/memories/{mid}")
async def update_memory_api(mid: int, req: MemoryUpdate,
                            owner: str = Depends(current_owner)) -> JSONResponse:
    """编辑记忆（部分更新；鉴权 + 所有权校验 + 缓存失效）。"""
    # 校验
    if req.scene is not None and req.scene not in db.SCENES:
        raise HTTPException(status_code=422, detail=f"非法场景: {req.scene}")
    if req.time_mode is not None and req.time_mode not in db.TIME_MODES:
        raise HTTPException(status_code=422, detail=f"非法时间模式: {req.time_mode}")

    patch: dict[str, Any] = {}
    if req.scene is not None:
        patch["scene"] = req.scene
    if req.feel is not None:
        patch["feel"] = req.feel.strip()
    if req.emotion is not None:
        patch["emotions"] = [req.emotion] if req.emotion else []

    # 媒体全量替换：客户端传完整数组（保持与详情页所见一致）；空数组=清空全部媒体
    if req.media is not None:
        media_items: list[dict[str, Any]] = []
        for item in req.media:
            key = item.file_key.strip()
            if not re.fullmatch(r"[0-9a-f]{24}\.[a-z0-9]+", key):
                raise HTTPException(status_code=422, detail=f"非法文件标识: {key}")
            media_items.append({"key": key, "url": uploads.resolve_url(key),
                                "kind": key.rsplit(".", 1)[-1]})
        patch["media"] = media_items

    # 时间戳归一化（与新建同规则）
    if req.time_mode is not None:
        try:
            if req.time_mode == "fuzzy":
                patch.update(timestamp_type="fuzzy", precise_at=None,
                             fuzzy_label=req.fuzzy_label or "记不清了",
                             fuzzy_note=(req.fuzzy_note or "").strip() or None)
            else:
                if req.time_mode == "now":
                    dt = datetime.now()
                else:
                    date_s = req.custom_date or datetime.now().strftime("%Y-%m-%d")
                    time_s = req.custom_time or datetime.now().strftime("%H:%M")
                    dt = datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H:%M")
                patch.update(timestamp_type="precise", precise_at=dt,
                             fuzzy_label=None, fuzzy_note=None)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"时间格式非法: {exc}") from exc

    if not patch:
        raise HTTPException(status_code=422, detail="未提供任何可更新字段")

    mem = db.update_memory(mid, owner=owner, **patch)
    if mem is None:
        raise HTTPException(status_code=404, detail=f"记忆不存在或无权编辑: {mid}")
    invalidate_bootstrap_cache()
    logger.info("编辑记忆 #%d（字段：%s）", mid, ",".join(patch.keys()))
    return ok(_memory_brief(mem))


# ---------------------------------------------------------------------------
# 多视角（阶段⑤：解锁「2条多视角」核心卖点）
# ---------------------------------------------------------------------------
class PerspectiveCreate(BaseModel):
    """新增视角入参（共建成员对同一条记忆写下自己的感受）。"""

    author_name: str = Field(default="我", max_length=50, description="作者昵称")
    author_avatar: str | None = Field(default=None, max_length=4, description="头像字")
    author_bg: str | None = Field(default=None, max_length=16, description="头像背景色")
    feel: str = Field(min_length=1, max_length=2000, description="该视角的感受")


@app.get("/api/v1/memories/{mid}/perspectives")
async def list_perspectives_api(mid: int,
                                owner: str = Depends(current_owner)) -> JSONResponse:
    """某条记忆的多视角列表。"""
    if _memory_visible(mid, owner) is None:
        raise HTTPException(status_code=404, detail=f"记忆不存在: {mid}")
    return ok([_perspective_brief(p) for p in db.list_perspectives(mid)])


@app.post("/api/v1/memories/{mid}/perspectives", status_code=201)
async def create_perspective_api(mid: int, req: PerspectiveCreate,
                                 owner: str = Depends(current_owner)) -> JSONResponse:
    """新增多视角。"""
    if _memory_visible(mid, owner) is None:
        raise HTTPException(status_code=404, detail=f"记忆不存在: {mid}")
    p = db.create_perspective(
        mid, author_name=req.author_name.strip() or "我",
        author_avatar=(req.author_avatar or req.author_name.strip()[:1] or "我"),
        author_bg=req.author_bg, feel=req.feel.strip())
    invalidate_bootstrap_cache()
    logger.info("新增视角 #%d（记忆 #%d，作者 %s）", p.id, mid, p.author_name)
    return ok(_perspective_brief(p), status=201)


@app.delete("/api/v1/perspectives/{pid}")
async def delete_perspective_api(pid: int) -> JSONResponse:
    """删除多视角（软删除）。"""
    if not db.soft_delete_perspective(pid):
        raise HTTPException(status_code=404, detail=f"视角不存在: {pid}")
    invalidate_bootstrap_cache()
    logger.info("删除视角 #%d（软删除）", pid)
    return ok({"id": pid, "deleted": True})


# ---------------------------------------------------------------------------
# 留言（阶段⑤：解锁「N条留言」核心卖点）
# ---------------------------------------------------------------------------
class CommentCreate(BaseModel):
    """新增留言入参。"""

    author_name: str = Field(default="我", max_length=50, description="作者昵称")
    author_avatar: str | None = Field(default=None, max_length=4, description="头像字")
    author_bg: str | None = Field(default=None, max_length=16, description="头像背景色")
    content: str = Field(min_length=1, max_length=1000, description="留言内容")


@app.get("/api/v1/memories/{mid}/comments")
async def list_comments_api(mid: int,
                            owner: str = Depends(current_owner)) -> JSONResponse:
    """某条记忆的留言列表。"""
    if _memory_visible(mid, owner) is None:
        raise HTTPException(status_code=404, detail=f"记忆不存在: {mid}")
    return ok([_comment_brief(c) for c in db.list_comments(mid)])


@app.post("/api/v1/memories/{mid}/comments", status_code=201)
async def create_comment_api(mid: int, req: CommentCreate,
                             owner: str = Depends(current_owner)) -> JSONResponse:
    """新增留言。"""
    if _memory_visible(mid, owner) is None:
        raise HTTPException(status_code=404, detail=f"记忆不存在: {mid}")
    c = db.create_comment(
        mid, author_name=req.author_name.strip() or "我",
        author_avatar=(req.author_avatar or req.author_name.strip()[:1] or "我"),
        author_bg=req.author_bg, content=req.content.strip())
    invalidate_bootstrap_cache()
    logger.info("新增留言 #%d（记忆 #%d，作者 %s）", c.id, mid, c.author_name)
    return ok(_comment_brief(c), status=201)


@app.delete("/api/v1/comments/{cid}")
async def delete_comment_api(cid: int) -> JSONResponse:
    """删除留言（软删除）。"""
    if not db.soft_delete_comment(cid):
        raise HTTPException(status_code=404, detail=f"留言不存在: {cid}")
    invalidate_bootstrap_cache()
    logger.info("删除留言 #%d（软删除）", cid)
    return ok({"id": cid, "deleted": True})


# ---------------------------------------------------------------------------
# 纪念日（v0.6：标记 → 倒计时 → 列表全链路入库）
# ---------------------------------------------------------------------------
def _parse_anniv_date(date_s: str) -> tuple[int, int]:
    """YYYY-MM-DD → (month, day)；非法日期（含2月30日）抛 422。"""
    try:
        dt = datetime.strptime(date_s, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"日期格式非法（应为 YYYY-MM-DD）: {date_s}") from exc
    return dt.month, dt.day


class AnniversaryCreate(BaseModel):
    """新建纪念日入参（对应前端 S08 标记表单）。"""

    name: str = Field(min_length=1, max_length=100, description="纪念日名称")
    date: str = Field(description="日期 YYYY-MM-DD（公历锚点）")
    is_lunar: bool = Field(default=False, description="农历纪念日（展示标记）")
    is_recurring: bool = Field(default=True, description="每年重复")
    remind_days_before: int = Field(default=3, ge=0, le=60, description="提前提醒天数")
    note: str | None = Field(default=None, max_length=500, description="备注")
    linked_memory_id: int | None = Field(default=None, description="来源记忆 id（可选）")


@app.get("/api/v1/anniversaries")
async def list_anniversaries_api(owner: str = Depends(current_owner)) -> JSONResponse:
    """纪念日列表（含实时计算的倒计时/已过天数视图字段；按当前身份隔离）。"""
    annivs = db.list_anniversaries(owner=owner)
    view = build_anniversaries(annivs, datetime.now(), cover_map=_anniv_cover_map(annivs))
    return ok(view["list"])


@app.post("/api/v1/anniversaries", status_code=201)
async def create_anniversary_api(req: AnniversaryCreate,
                                 owner: str = Depends(current_owner)) -> JSONResponse:
    """新建纪念日（标记一条记忆的重要日期）。"""
    month, day = _parse_anniv_date(req.date)
    if (req.linked_memory_id is not None
            and _memory_visible(req.linked_memory_id, owner) is None):
        raise HTTPException(status_code=422, detail=f"关联记忆不存在: {req.linked_memory_id}")
    ann = db.create_anniversary(
        name=req.name.strip(),
        month=month, day=day,
        is_lunar=req.is_lunar, is_recurring=req.is_recurring,
        remind_days_before=req.remind_days_before,
        note=(req.note or "").strip() or None,
        linked_memory_id=req.linked_memory_id,
        source="user", owner_id=owner,
    )
    invalidate_bootstrap_cache()
    logger.info("新建纪念日 #%d（%s，%d月%d日）", ann.id, ann.name, month, day)
    return ok(_anniv_brief(ann), status=201)


class AnniversaryUpdate(BaseModel):
    """编辑纪念日入参（PATCH 语义：仅传入的字段会被更新）。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    date: str | None = Field(default=None, description="日期 YYYY-MM-DD（改锚点）")
    is_lunar: bool | None = Field(default=None)
    is_recurring: bool | None = Field(default=None)
    remind_days_before: int | None = Field(default=None, ge=0, le=60)
    note: str | None = Field(default=None, max_length=500)
    linked_memory_id: int | None = Field(default=None)


@app.patch("/api/v1/anniversaries/{aid}")
async def update_anniversary_api(aid: int, req: AnniversaryUpdate,
                                 owner: str = Depends(current_owner)) -> JSONResponse:
    """编辑纪念日（部分更新；鉴权 + 所有权校验 + 缓存失效）。"""
    patch: dict[str, Any] = {}
    if req.name is not None:
        patch["name"] = req.name.strip()
    if req.date is not None:
        month, day = _parse_anniv_date(req.date)
        patch.update(month=month, day=day)
    if req.is_lunar is not None:
        patch["is_lunar"] = req.is_lunar
    if req.is_recurring is not None:
        patch["is_recurring"] = req.is_recurring
    if req.remind_days_before is not None:
        patch["remind_days_before"] = req.remind_days_before
    if req.note is not None:
        patch["note"] = req.note.strip() or None
    if req.linked_memory_id is not None:
        if _memory_visible(req.linked_memory_id, owner) is None:
            raise HTTPException(status_code=422, detail=f"关联记忆不存在: {req.linked_memory_id}")
        patch["linked_memory_id"] = req.linked_memory_id
    if not patch:
        raise HTTPException(status_code=422, detail="未提供任何可更新字段")

    ann = db.update_anniversary(aid, owner=owner, **patch)
    if ann is None:
        raise HTTPException(status_code=404, detail=f"纪念日不存在或无权编辑: {aid}")
    invalidate_bootstrap_cache()
    logger.info("编辑纪念日 #%d（字段：%s）", aid, ",".join(patch.keys()))
    return ok(_anniv_brief(ann))


@app.delete("/api/v1/anniversaries/{aid}")
async def delete_anniversary_api(aid: int,
                                 owner: str = Depends(current_owner)) -> JSONResponse:
    """删除纪念日（软删除 + 所有权校验）。"""
    if not db.soft_delete_anniversary(aid, owner=owner):
        raise HTTPException(status_code=404, detail=f"纪念日不存在: {aid}")
    invalidate_bootstrap_cache()
    logger.info("删除纪念日 #%d（软删除）", aid)
    return ok({"id": aid, "deleted": True})


# ---------------------------------------------------------------------------
# 成长追踪（v0.7：主体 + 里程碑全链路入库）
# ---------------------------------------------------------------------------
def _parse_date_field(s: str | None, field: str = "日期") -> date:
    """YYYY-MM-DD → date；非法值（含 2 月 30 日）抛 422。"""
    try:
        return datetime.strptime(s or "", "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"{field}格式非法（应为 YYYY-MM-DD）: {s}") from exc


class SubjectCreate(BaseModel):
    """新增主体入参（对应前端 S13「新增主体」）。"""

    name: str = Field(min_length=1, max_length=50, description="主体名称")
    kind: str = Field(default="baby", description="类型: baby/pet/other")
    birthday: str | None = Field(default=None, description="生日/开始日期 YYYY-MM-DD（可选）")
    note: str | None = Field(default=None, max_length=100, description="备注（如品种 金毛）")


@app.get("/api/v1/growth/subjects")
async def list_growth_subjects_api(owner: str = Depends(current_owner)) -> JSONResponse:
    """主体列表（含实时派生的 meta / 最近里程碑；按当前身份隔离）。"""
    view = build_growth("", db.list_growth_subjects(owner=owner),
                        db.list_growth_milestones(owner=owner), datetime.now())
    return ok(view["subjects"])


@app.post("/api/v1/growth/subjects", status_code=201)
async def create_growth_subject_api(req: SubjectCreate,
                                    owner: str = Depends(current_owner)) -> JSONResponse:
    """新增成长主体。"""
    if req.kind not in db.GROWTH_KINDS:
        raise HTTPException(status_code=422, detail=f"非法类型: {req.kind}")
    birthday = _parse_date_field(req.birthday, "生日") if req.birthday else None
    birth_label = f"出生于 {_fmt_cn_date(birthday)}" if birthday else None
    sub = db.create_growth_subject(
        name=req.name.strip(), kind=req.kind, birthday=birthday,
        birth_label=birth_label, note=(req.note or "").strip() or None,
        source="user", owner_id=owner,
    )
    invalidate_bootstrap_cache()
    logger.info("新增成长主体 #%d（%s，%s）", sub.id, sub.name, sub.kind)
    return ok(_subject_brief(sub), status=201)


class SubjectUpdate(BaseModel):
    """编辑主体入参（PATCH 语义）。"""

    name: str | None = Field(default=None, min_length=1, max_length=50)
    kind: str | None = Field(default=None)
    birthday: str | None = Field(default=None, description="生日 YYYY-MM-DD")
    note: str | None = Field(default=None, max_length=100)


@app.patch("/api/v1/growth/subjects/{sid}")
async def update_growth_subject_api(sid: int, req: SubjectUpdate,
                                    owner: str = Depends(current_owner)) -> JSONResponse:
    """编辑主体（部分更新；鉴权 + 所有权校验 + 缓存失效）。"""
    patch: dict[str, Any] = {}
    if req.name is not None:
        patch["name"] = req.name.strip()
    if req.kind is not None:
        if req.kind not in db.GROWTH_KINDS:
            raise HTTPException(status_code=422, detail=f"非法类型: {req.kind}")
        patch["kind"] = req.kind
    if req.birthday is not None:
        birthday = _parse_date_field(req.birthday, "生日")
        patch["birthday"] = birthday
        patch["birth_label"] = f"出生于 {_fmt_cn_date(birthday)}"
    if req.note is not None:
        patch["note"] = req.note.strip() or None
    if not patch:
        raise HTTPException(status_code=422, detail="未提供任何可更新字段")

    sub = db.update_growth_subject(sid, owner=owner, **patch)
    if sub is None:
        raise HTTPException(status_code=404, detail=f"主体不存在或无权编辑: {sid}")
    invalidate_bootstrap_cache()
    logger.info("编辑主体 #%d（字段：%s）", sid, ",".join(patch.keys()))
    return ok(_subject_brief(sub))


@app.delete("/api/v1/growth/subjects/{sid}")
async def delete_growth_subject_api(sid: int,
                                    owner: str = Depends(current_owner)) -> JSONResponse:
    """删除主体（软删除 + 级联软删其里程碑 + 所有权校验）。"""
    if not db.soft_delete_growth_subject(sid, owner=owner):
        raise HTTPException(status_code=404, detail=f"主体不存在: {sid}")
    invalidate_bootstrap_cache()
    logger.info("删除主体 #%d（软删除，含里程碑）", sid)
    return ok({"id": sid, "deleted": True})


class MilestoneCreate(BaseModel):
    """新增里程碑入参（对应前端 S14「记录里程碑」）。"""

    title: str = Field(min_length=1, max_length=200, description="里程碑标题")
    date: str = Field(description="发生日期 YYYY-MM-DD")
    desc: str | None = Field(default=None, max_length=2000, description="补充描述")
    is_major: bool = Field(default=False, description="重要里程碑")
    memory_id: int | None = Field(default=None, description="来源记忆 id（可选）")


@app.get("/api/v1/growth/subjects/{sid}/milestones")
async def list_growth_milestones_api(sid: int,
                                     owner: str = Depends(current_owner)) -> JSONResponse:
    """某主体的里程碑列表（含实时派生的日期标签）。"""
    sub = db.get_growth_subject(sid)
    if sub is None or sub.owner_id not in (db.SEED_OWNER, owner):
        raise HTTPException(status_code=404, detail=f"主体不存在: {sid}")
    today = datetime.now().date()
    return ok([_growth_milestone_view(m, today)
               for m in db.list_growth_milestones(sid, owner=owner)])


@app.post("/api/v1/growth/subjects/{sid}/milestones", status_code=201)
async def create_growth_milestone_api(sid: int, req: MilestoneCreate,
                                      owner: str = Depends(current_owner)) -> JSONResponse:
    """新增里程碑。"""
    sub = db.get_growth_subject(sid)
    if sub is None or sub.owner_id not in (db.SEED_OWNER, owner):
        raise HTTPException(status_code=404, detail=f"主体不存在: {sid}")
    if req.memory_id is not None and _memory_visible(req.memory_id, owner) is None:
        raise HTTPException(status_code=422, detail=f"关联记忆不存在: {req.memory_id}")
    m = db.create_growth_milestone(
        subject_id=sid,
        title=req.title.strip(),
        content=(req.desc or "").strip() or None,
        happened_on=_parse_date_field(req.date),
        is_major=req.is_major,
        memory_id=req.memory_id,
        source="user", owner_id=owner,
    )
    invalidate_bootstrap_cache()
    logger.info("新增里程碑 #%d（主体 #%d，%s）", m.id, sid, m.title)
    return ok(_milestone_brief(m), status=201)


class MilestoneUpdate(BaseModel):
    """编辑里程碑入参（PATCH 语义）。"""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    date: str | None = Field(default=None, description="发生日期 YYYY-MM-DD")
    desc: str | None = Field(default=None, max_length=2000)
    is_major: bool | None = Field(default=None)
    memory_id: int | None = Field(default=None)


@app.patch("/api/v1/growth/milestones/{mid}")
async def update_growth_milestone_api(mid: int, req: MilestoneUpdate,
                                      owner: str = Depends(current_owner)) -> JSONResponse:
    """编辑里程碑（部分更新；鉴权 + 所有权校验 + 缓存失效）。"""
    patch: dict[str, Any] = {}
    if req.title is not None:
        patch["title"] = req.title.strip()
    if req.date is not None:
        patch["happened_on"] = _parse_date_field(req.date)
    if req.desc is not None:
        patch["content"] = req.desc.strip() or None
    if req.is_major is not None:
        patch["is_major"] = req.is_major
    if req.memory_id is not None:
        if _memory_visible(req.memory_id, owner) is None:
            raise HTTPException(status_code=422, detail=f"关联记忆不存在: {req.memory_id}")
        patch["memory_id"] = req.memory_id
    if not patch:
        raise HTTPException(status_code=422, detail="未提供任何可更新字段")

    m = db.update_growth_milestone(mid, owner=owner, **patch)
    if m is None:
        raise HTTPException(status_code=404, detail=f"里程碑不存在或无权编辑: {mid}")
    invalidate_bootstrap_cache()
    logger.info("编辑里程碑 #%d（字段：%s）", mid, ",".join(patch.keys()))
    return ok(_milestone_brief(m))


@app.delete("/api/v1/growth/milestones/{mid}")
async def delete_growth_milestone_api(mid: int,
                                      owner: str = Depends(current_owner)) -> JSONResponse:
    """删除里程碑（软删除 + 所有权校验）。"""
    if not db.soft_delete_growth_milestone(mid, owner=owner):
        raise HTTPException(status_code=404, detail=f"里程碑不存在: {mid}")
    invalidate_bootstrap_cache()
    logger.info("删除里程碑 #%d（软删除）", mid)
    return ok({"id": mid, "deleted": True})


# ---------------------------------------------------------------------------
# 共建时间线节点（v0.8：情侣/友情记忆螺旋真实化）
# ---------------------------------------------------------------------------
class TimelineNodeCreate(BaseModel):
    """新增时间线节点入参。"""

    kind: str = Field(description="空间: couple/friend")
    node_key: str = Field(default="", max_length=40, description="节点键（同空间唯一）")
    icon: str = Field(default="heart", max_length=20, description="图标键")
    title: str = Field(min_length=1, max_length=100, description="节点名称")
    desc: str | None = Field(default=None, max_length=1000, description="节点描述")
    date_str: str | None = Field(default=None, max_length=30, description="展示日期，如 2022.06")
    memory_id: int | None = Field(default=None, description="回链记忆 id（可选）")
    node_x: float = Field(default=0, description="螺旋节点 x")
    node_y: float = Field(default=0, description="螺旋节点 y")
    label_x: float = Field(default=0, description="标签 x")
    label_y: float = Field(default=0, description="标签 y")
    is_latest: bool = Field(default=False, description="最新节点标记")


@app.get("/api/v1/timeline/nodes")
async def list_timeline_nodes_api(kind: str | None = Query(default=None),
                                  owner: str = Depends(current_owner)) -> JSONResponse:
    """时间线节点列表（可按空间过滤；含实时视角/留言计数与回链 mid；按身份隔离）。"""
    if kind is not None and kind not in ("couple", "friend"):
        raise HTTPException(status_code=422, detail=f"非法空间: {kind}")
    pcounts, ccounts = db.engagement_counts()
    nodes = db.list_timeline_nodes(kind, owner=owner)
    return ok([_timeline_node_view(n, pcounts, ccounts) for n in nodes])


@app.post("/api/v1/timeline/nodes", status_code=201)
async def create_timeline_node_api(req: TimelineNodeCreate,
                                   owner: str = Depends(current_owner)) -> JSONResponse:
    """新增时间线节点。"""
    if req.kind not in ("couple", "friend"):
        raise HTTPException(status_code=422, detail=f"非法空间: {req.kind}")
    if req.memory_id is not None and _memory_visible(req.memory_id, owner) is None:
        raise HTTPException(status_code=422, detail=f"关联记忆不存在: {req.memory_id}")
    if not req.node_key:
        req.node_key = f"n{int(time.time() * 1000) % 1000000}"
    node = db.create_timeline_node(
        kind=req.kind, node_key=req.node_key.strip(), icon=req.icon,
        title=req.title.strip(), desc=(req.desc or "").strip() or None,
        date_str=(req.date_str or "").strip() or None,
        memory_id=req.memory_id,
        node_x=req.node_x, node_y=req.node_y,
        label_x=req.label_x, label_y=req.label_y,
        is_latest=req.is_latest,
        sort_order=len(db.list_timeline_nodes(req.kind, owner=owner)),
        source="user", owner_id=owner,
    )
    invalidate_bootstrap_cache()
    logger.info("新增时间线节点 #%d（%s/%s，%s）", node.id, node.kind, node.node_key, node.title)
    return ok(_timeline_node_brief(node), status=201)


class TimelineNodeUpdate(BaseModel):
    """编辑时间线节点入参（PATCH 语义）。"""

    node_key: str | None = Field(default=None, max_length=40)
    icon: str | None = Field(default=None, max_length=20)
    title: str | None = Field(default=None, min_length=1, max_length=100)
    desc: str | None = Field(default=None, max_length=1000)
    date_str: str | None = Field(default=None, max_length=30)
    memory_id: int | None = Field(default=None)
    node_x: float | None = Field(default=None)
    node_y: float | None = Field(default=None)
    label_x: float | None = Field(default=None)
    label_y: float | None = Field(default=None)
    is_latest: bool | None = Field(default=None)


@app.patch("/api/v1/timeline/nodes/{nid}")
async def update_timeline_node_api(nid: int, req: TimelineNodeUpdate,
                                   owner: str = Depends(current_owner)) -> JSONResponse:
    """编辑时间线节点（部分更新；鉴权 + 所有权校验 + 缓存失效）。"""
    patch: dict[str, Any] = {}
    for f in ("node_key", "icon", "title", "desc", "date_str",
              "node_x", "node_y", "label_x", "label_y", "is_latest"):
        v = getattr(req, f)
        if v is not None:
            patch[f] = v.strip() if isinstance(v, str) else v
    if req.memory_id is not None:
        if _memory_visible(req.memory_id, owner) is None:
            raise HTTPException(status_code=422, detail=f"关联记忆不存在: {req.memory_id}")
        patch["memory_id"] = req.memory_id
    if not patch:
        raise HTTPException(status_code=422, detail="未提供任何可更新字段")

    node = db.update_timeline_node(nid, owner=owner, **patch)
    if node is None:
        raise HTTPException(status_code=404, detail=f"节点不存在或无权编辑: {nid}")
    invalidate_bootstrap_cache()
    logger.info("编辑时间线节点 #%d（字段：%s）", nid, ",".join(patch.keys()))
    return ok(_timeline_node_brief(node))


@app.delete("/api/v1/timeline/nodes/{nid}")
async def delete_timeline_node_api(nid: int,
                                   owner: str = Depends(current_owner)) -> JSONResponse:
    """删除时间线节点（软删除 + 所有权校验）。"""
    if not db.soft_delete_timeline_node(nid, owner=owner):
        raise HTTPException(status_code=404, detail=f"节点不存在: {nid}")
    invalidate_bootstrap_cache()
    logger.info("删除时间线节点 #%d（软删除）", nid)
    return ok({"id": nid, "deleted": True})


# ---------------------------------------------------------------------------
# 共建空间成员（v0.8：邀请列表真实化）
# ---------------------------------------------------------------------------
class InviteMemberCreate(BaseModel):
    """新增成员入参。"""

    space: str = Field(description="空间: couple/friend")
    name: str = Field(min_length=1, max_length=50, description="成员昵称")
    state: str = Field(default="待接受", description="已加入/待接受")
    note: str | None = Field(default=None, max_length=100, description="展示串")


@app.get("/api/v1/invites/members")
async def list_invite_members_api(space: str | None = Query(default=None),
                                  owner: str = Depends(current_owner)) -> JSONResponse:
    """共建空间成员列表（可按空间过滤；按身份隔离）。"""
    if space is not None and space not in ("couple", "friend"):
        raise HTTPException(status_code=422, detail=f"非法空间: {space}")
    return ok([_invite_member_view(m) for m in db.list_invite_members(space, owner=owner)])


@app.post("/api/v1/invites/members", status_code=201)
async def create_invite_member_api(req: InviteMemberCreate,
                                   owner: str = Depends(current_owner)) -> JSONResponse:
    """新增成员（模拟邀请接受/加入）。"""
    if req.space not in ("couple", "friend"):
        raise HTTPException(status_code=422, detail=f"非法空间: {req.space}")
    if req.state not in ("已加入", "待接受"):
        raise HTTPException(status_code=422, detail="state 应为 已加入/待接受")
    m = db.create_invite_member(
        space=req.space, name=req.name.strip(), avatar=req.name.strip()[:1],
        state=req.state, note=(req.note or "").strip() or None,
        sort_order=len(db.list_invite_members(req.space, owner=owner)),
        source="user", owner_id=owner,
    )
    invalidate_bootstrap_cache()
    logger.info("新增共建成员 #%d（%s/%s）", m.id, m.space, m.name)
    return ok(_invite_member_view(m), status=201)


@app.delete("/api/v1/invites/members/{mid}")
async def delete_invite_member_api(mid: int,
                                   owner: str = Depends(current_owner)) -> JSONResponse:
    """移除成员（软删除 + 所有权校验）。"""
    if not db.soft_delete_invite_member(mid, owner=owner):
        raise HTTPException(status_code=404, detail=f"成员不存在: {mid}")
    invalidate_bootstrap_cache()
    logger.info("移除共建成员 #%d（软删除）", mid)
    return ok({"id": mid, "deleted": True})


# ---------------------------------------------------------------------------
# 媒体上传（v0.8：预签名直传，本地磁盘实现，契约对齐 OSS）
# ---------------------------------------------------------------------------
class PresignRequest(BaseModel):
    """申请预签名上传凭据入参。"""

    filename: str = Field(description="文件名（带扩展名，用于类型白名单）")
    contentType: str | None = Field(default=None, description="MIME 类型")


@app.post("/api/v1/uploads/presign", status_code=201)
async def presign_upload_api(req: PresignRequest) -> JSONResponse:
    """申请预签名上传凭据：客户端随后 PUT 到 uploadUrl 直传文件。"""
    try:
        cred = uploads.presign(req.filename, req.contentType)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    logger.info("申请预签名上传：%s → %s", req.filename, cred["fileKey"])
    return ok(cred, status=201)


@app.put("/api/v1/uploads/{file_key}")
async def upload_file_api(file_key: str, request: Request) -> JSONResponse:
    """预签名直传端点（本地实现：接收文件字节落盘）。

    真实 OSS 时此端点不再需要——客户端直传 OSS，本服务只留 presign 与关联。
    """
    try:
        data = await request.body()
        uploads.save_file(file_key, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    logger.info("文件上传完成：%s（%d 字节）", file_key, len(data))
    return ok({"fileKey": file_key, "url": uploads.resolve_url(file_key)})


class MediaAttach(BaseModel):
    """把已上传的媒体关联到记忆。"""

    file_key: str = Field(description="上传返回的 fileKey")


@app.post("/api/v1/memories/{mid}/media", status_code=201)
async def attach_media_api(mid: int, req: MediaAttach,
                           owner: str = Depends(current_owner)) -> JSONResponse:
    """把已上传的媒体附加到记忆（memories.media JSON 数组追加）。"""
    if _memory_visible(mid, owner) is None:
        raise HTTPException(status_code=404, detail=f"记忆不存在: {mid}")
    key = req.file_key.strip()
    if not re.fullmatch(r"[0-9a-f]{24}\.[a-z0-9]+", key):
        raise HTTPException(status_code=422, detail="非法文件标识")
    item = {
        "key": key,
        "url": uploads.resolve_url(key),
        "kind": key.rsplit(".", 1)[-1],
    }
    mem = db.append_memory_media(mid, item, owner=owner)
    if mem is None:
        raise HTTPException(status_code=404, detail=f"记忆不存在或无权编辑: {mid}")
    invalidate_bootstrap_cache()
    logger.info("记忆 #%d 关联媒体：%s", mid, key)
    return ok({"memoryId": mid, "media": list(mem.media or [])}, status=201)


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------
def _memory_brief(m: db.Memory, pcount: int = 0, ccount: int = 0) -> dict:
    return {
        "id": m.id,
        "scene": m.scene,
        "feel": m.feel,
        "emotions": list(m.emotions or []),
        "voice": m.voice,
        "timestampType": m.timestamp_type,
        "preciseAt": m.precise_at.strftime("%Y-%m-%d %H:%M") if m.precise_at else None,
        "fuzzyLabel": m.fuzzy_label,
        "fuzzyNote": m.fuzzy_note,
        "media": list(m.media or []),
        "source": m.source,
        "ownerId": m.owner_id,
        "perspectiveCount": pcount,
        "commentCount": ccount,
        "createdAt": m.created_at.strftime("%Y-%m-%d %H:%M"),
    }


def _perspective_brief(p: db.Perspective) -> dict:
    return {
        "id": p.id,
        "memoryId": p.memory_id,
        "name": p.author_name,
        "avatar": p.author_avatar or p.author_name[:1],
        "bg": p.author_bg,
        "feel": p.feel,
        "time": p.created_at.strftime("%m月%d日 %H:%M"),
    }


def _comment_brief(c: db.Comment) -> dict:
    return {
        "id": c.id,
        "memoryId": c.memory_id,
        "name": c.author_name,
        "avatar": c.author_avatar or c.author_name[:1],
        "bg": c.author_bg,
        "content": c.content,
        "time": c.created_at.strftime("%m月%d日 %H:%M"),
    }


def _anniv_brief(a: db.Anniversary) -> dict:
    return {
        "id": a.id,
        "name": a.name,
        "month": a.month,
        "day": a.day,
        "isLunar": a.is_lunar,
        "lunarLabel": a.lunar_label,
        "isRecurring": a.is_recurring,
        "remindDaysBefore": a.remind_days_before,
        "note": a.note,
        "linkedMemoryId": a.linked_memory_id,
        "source": a.source,
        "ownerId": a.owner_id,
        "createdAt": a.created_at.strftime("%Y-%m-%d %H:%M"),
    }


def _subject_brief(s: db.GrowthSubject) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "kind": s.kind,
        "birthday": s.birthday.strftime("%Y-%m-%d") if s.birthday else None,
        "birthLabel": s.birth_label,
        "note": s.note,
        "source": s.source,
        "ownerId": s.owner_id,
        "createdAt": s.created_at.strftime("%Y-%m-%d %H:%M"),
    }


def _milestone_brief(m: db.GrowthMilestone) -> dict:
    return {
        "id": m.id,
        "subjectId": m.subject_id,
        "memoryId": m.memory_id,
        "title": m.title,
        "desc": m.content,
        "happenedOn": m.happened_on.strftime("%Y-%m-%d"),
        "isMajor": m.is_major,
        "hasPic": m.has_pic,
        "source": m.source,
        "ownerId": m.owner_id,
        "createdAt": m.created_at.strftime("%Y-%m-%d %H:%M"),
    }


def _timeline_node_brief(n: db.TimelineNode) -> dict:
    return {
        "id": n.id,
        "kind": n.kind,
        "nodeKey": n.node_key,
        "icon": n.icon,
        "title": n.title,
        "desc": n.desc,
        "dateStr": n.date_str,
        "badgeHint": n.badge_hint,
        "memoryId": n.memory_id,
        "node": [n.node_x, n.node_y],
        "label": [n.label_x, n.label_y],
        "isLatest": n.is_latest,
        "sortOrder": n.sort_order,
        "source": n.source,
        "ownerId": n.owner_id,
        "createdAt": n.created_at.strftime("%Y-%m-%d %H:%M"),
    }


# ---------------------------------------------------------------------------
# AI 生成接口（v0.2 遗留，当前休眠——前端未接入调用入口）
# ---------------------------------------------------------------------------
class GenerateRequest(BaseModel):
    scene: str = "personal"
    note: str | None = None


@app.post("/api/app/generate")
async def app_generate(req: GenerateRequest) -> Dict[str, Any]:
    if req.scene not in llm.SCENE_NAMES:
        raise HTTPException(status_code=422, detail=f"非法场景: {req.scene}")
    base = template_repo.load()
    try:
        return await llm.generate_dataset(base, req.scene, {"note": req.note})
    except Exception as exc:  # noqa: BLE001
        logger.error("AI 生成失败（场景 %s）：%s", req.scene, exc)
        raise HTTPException(status_code=502, detail=f"AI 生成失败: {exc}") from exc


@app.get("/api/app/llm-status")
async def llm_status() -> Dict[str, Any]:
    return llm.status()


# ---------------------------------------------------------------------------
# 静态资源：上传文件 + 前端原型页面（同源访问，避免 file:// 跨域问题）
# ---------------------------------------------------------------------------
uploads.upload_dir().mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads.upload_dir()), name="uploads")

STATIC_DIR.mkdir(exist_ok=True)

# 根路径重定向到主页面（StaticFiles html=True 只认 index.html，文件名不匹配会 404）
@app.get("/", include_in_schema=False)
async def _root_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/memory-vortex-prototype-v2-api.html", status_code=302)

app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    # 直接传 app 对象（而非 "main:app" 字符串），避免模块被重复导入执行
    uvicorn.run(app, host=HOST, port=PORT, reload=False)
