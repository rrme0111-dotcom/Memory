# -*- coding: utf-8 -*-
"""
记忆漩涡 MemoryVortex · 数据库层（db.py）
================================================
v0.9 变更（登录注册体系，多用户铺路落地）：
- 新表 users（账号）+ sessions（会话令牌）：注册/登录/登出/我的；
- 密码安全：PBKDF2-HMAC-SHA256 + 每用户随机盐（200k 迭代，内置库零依赖）；
- 数据归属：登录用户 owner 为 "user:{id}"，游客仍为 "local"；
  adopt_local_data() 在登录/注册时把游客阶段数据归入该用户名下；
- list_* 系列增加 owner 过滤：返回 seed（共享演示数据）∪ owner 自有数据；
- 会话支持登出吊销与过期（默认 30 天）。

v0.8 变更（共建时间线/邀请入库 + 媒体字段）：
- 新表 timeline_nodes：情侣/友情时间线节点统一存储（kind 区分），
  可选回链记忆（点击节点「回看那段记忆」进详情）；
- 新表 invite_members：共建空间成员（情侣待接受 + 友情成员）；
- memories 新增 media JSON 列（媒体附件 [{key, url, kind}]，配合预签名上传）；
- 种子导入：模板 coupleTimeline/friendTimeline 的 14 个节点 + invites 的 3 名成员；
- 删除节点/成员按 owner_id 校验所有权（与既有模块同一套 IDOR 防护）。

v0.7 变更（成长追踪模块入库）：
- 新表 growth_subjects（主体：宝宝/宠物/其他，生日锚点 + 展示标签）；
- 新表 growth_milestones（里程碑，FK→growth_subjects，可选回链 memories）；
- 种子导入：模板 growth.timelines 的 2 个主体 + 8 条里程碑；
- 删除主体时级联软删其里程碑（一个事务内）。

v0.6 变更（纪念日模块入库）：
- 新表 anniversaries：公历月/日为锚点（农历仅存展示标签，不参与倒计时计算）；
- 种子导入：模板 anniversaries.list 的 3 条演示纪念日；
- CRUD 与 memories 同构：update / soft_delete 均按 owner_id 校验所有权。

v0.5 变更（安全与性能基线 + 多视角/留言）：
- memories 新增 owner_id（数据所有权，多用户铺路；本地阶段 local/seed）；
- 显式索引：scene / precise_at / (scene, deleted_at, precise_at)；
- 新表 perspectives（多视角）、comments（留言），FK 关联 memories，均软删除；
- 轻量迁移：已有库自动补列补索引（不丢用户数据，无需删库）；
- list_memories 支持 limit / before_id 游标分页；
- 种子导入扩展：除记忆外，还导入模板中的多视角与留言演示数据。

设计要点（承 v0.4）：
- 仓储模式：本文件只管「数据怎么存」，不管「接口长什么样」；
- SQLite 起步、可无痛升级 PostgreSQL：换 PG 只改 DATABASE_URL 一行；
- 软删除：deleted_at 标记，与架构提示词（PIPL 数据删除合规）对齐。

表结构：
    users:
        id / username(唯一) / password_hash / salt / nickname / avatar(头像字) /
        created_at / updated_at / deleted_at
    sessions:
        token(主键) / user_id(FK→users.id) / created_at / expires_at
    memories:
        id / scene / feel / emotions(JSON) / voice /
        timestamp_type(precise|fuzzy) / precise_at / fuzzy_label / fuzzy_note /
        meta_override / media(JSON, 媒体附件) / source(seed|user) / owner_id /
        created_at / updated_at / deleted_at
    perspectives:
        id / memory_id(FK→memories.id) / author_name / author_avatar /
        author_bg / feel / created_at / updated_at / deleted_at
    comments:
        id / memory_id(FK→memories.id) / author_name / author_avatar /
        content / created_at / updated_at / deleted_at
    anniversaries:
        id / owner_id / name / month(1-12) / day(1-31) / is_lunar /
        lunar_label(展示用) / is_recurring / remind_days_before / note /
        linked_memory_id(FK→memories.id, 可选) / source / created_at /
        updated_at / deleted_at
    growth_subjects:
        id / owner_id / name / kind(baby|pet|other) / birthday(年龄锚点) /
        birth_label(展示串, 如 出生于2024年5月20日/2023年4月来到家) / note(如 金毛) /
        source / created_at / updated_at / deleted_at
    growth_milestones:
        id / subject_id(FK→growth_subjects.id) / memory_id(FK→memories.id, 可选) /
        title / content / happened_on(日期锚点) / is_major / has_pic /
        owner_id / source / created_at / updated_at / deleted_at
    timeline_nodes:
        id / kind(couple|friend) / node_key(同空间唯一, 如 meet) / icon /
        title / desc / date_str(如 2022.06) / badge_hint(模板视角/留言计数) /
        memory_id(FK→memories.id, 可选回链) / node_x / node_y / label_x /
        label_y(螺旋布局坐标) / is_latest / sort_order / source / owner_id /
        created_at / updated_at / deleted_at
    invite_members:
        id / space(couple|friend) / name / avatar / bg / state(已加入|待接受) /
        note(展示串) / sort_order / source / owner_id / created_at /
        updated_at / deleted_at
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, ForeignKey, create_engine, delete, func, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

logger = logging.getLogger("memory-vortex.db")

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "memory_vortex.db"

# 数据库连接串：升级 PostgreSQL 时只改这一行（并加装驱动 psycopg 或 asyncpg）
DATABASE_URL = f"sqlite:///{DB_PATH}"

SCENES = ("personal", "couple", "friend", "growth")
TIME_MODES = ("now", "custom", "fuzzy")

LOCAL_OWNER = "local"    # 本地单用户阶段的数据所有者（游客/未登录）
SEED_OWNER = "seed"      # 演示种子数据
OWNER_PREFIX = "user:"   # 登录用户的数据所有者前缀：user:{id}

# 密码哈希：PBKDF2-HMAC-SHA256（Python 内置，无第三方依赖）
PBKDF2_ITERATIONS = 200_000

# 会话有效期：默认 30 天
SESSION_TTL_DAYS = 30


# ---------------------------------------------------------------------------
# ORM 模型
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    pass


class Memory(Base):
    """记忆条目（核心实体）。"""

    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scene: Mapped[str] = mapped_column(comment="场景: personal/couple/friend/growth")
    feel: Mapped[str] = mapped_column(comment="感受文字")
    emotions: Mapped[list] = mapped_column(JSON, default=list, comment="情绪标签数组")
    voice: Mapped[str | None] = mapped_column(default=None, comment="语音时长展示, 如 0:30")
    timestamp_type: Mapped[str] = mapped_column(default="precise", comment="precise/fuzzy")
    precise_at: Mapped[datetime | None] = mapped_column(default=None, comment="精确时间")
    fuzzy_label: Mapped[str | None] = mapped_column(default=None, comment="模糊时间预设")
    fuzzy_note: Mapped[str | None] = mapped_column(default=None, comment="模糊时间补充描述")
    meta_override: Mapped[str | None] = mapped_column(default=None, comment="种子数据展示meta")
    media: Mapped[list] = mapped_column(JSON, default=list, comment="媒体附件: [{key, url, kind}]")
    source: Mapped[str] = mapped_column(default="user", comment="seed/user")
    owner_id: Mapped[str] = mapped_column(default=LOCAL_OWNER, comment="数据所有者（多用户铺路）")
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now, onupdate=datetime.now)
    deleted_at: Mapped[datetime | None] = mapped_column(default=None, comment="软删除时间")


class Perspective(Base):
    """多视角：同一条记忆下，不同共建成员各自的感受。"""

    __tablename__ = "perspectives"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    memory_id: Mapped[int] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), index=True, comment="所属记忆")
    author_name: Mapped[str] = mapped_column(default="我", comment="作者昵称")
    author_avatar: Mapped[str | None] = mapped_column(default=None, comment="头像字（单字）")
    author_bg: Mapped[str | None] = mapped_column(default=None, comment="头像背景色")
    feel: Mapped[str] = mapped_column(comment="该视角的感受文字")
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now, onupdate=datetime.now)
    deleted_at: Mapped[datetime | None] = mapped_column(default=None, comment="软删除时间")


class Comment(Base):
    """留言（评论）：共建成员或访客对记忆的评论。"""

    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    memory_id: Mapped[int] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), index=True, comment="所属记忆")
    author_name: Mapped[str] = mapped_column(default="我", comment="作者昵称")
    author_avatar: Mapped[str | None] = mapped_column(default=None, comment="头像字（单字）")
    author_bg: Mapped[str | None] = mapped_column(default=None, comment="头像背景色")
    content: Mapped[str] = mapped_column(comment="留言内容")
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now, onupdate=datetime.now)
    deleted_at: Mapped[datetime | None] = mapped_column(default=None, comment="软删除时间")


class Anniversary(Base):
    """纪念日：公历月/日为锚点，每年（或一次性）周年日。

    农历策略：is_lunar + lunar_label 仅承担「展示标签」（如「农历七月初七」），
    倒计时一律按公历 month/day 计算——避免引入农历库；接入农历换算时只需
    在派生层（main.py）补一个「公历锚点 → 当年农历日」的转换函数，表结构不变。
    """

    __tablename__ = "anniversaries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(default=LOCAL_OWNER, comment="数据所有者（多用户铺路）")
    name: Mapped[str] = mapped_column(comment="纪念日名称")
    month: Mapped[int] = mapped_column(comment="公历月份 1-12")
    day: Mapped[int] = mapped_column(comment="公历日期 1-31")
    is_lunar: Mapped[bool] = mapped_column(default=False, comment="农历纪念日（展示标记）")
    lunar_label: Mapped[str | None] = mapped_column(default=None, comment="农历展示标签，如 农历七月初七")
    is_recurring: Mapped[bool] = mapped_column(default=True, comment="每年重复")
    remind_days_before: Mapped[int] = mapped_column(default=3, comment="提前提醒天数")
    note: Mapped[str | None] = mapped_column(default=None, comment="用户备注")
    linked_memory_id: Mapped[int | None] = mapped_column(
        ForeignKey("memories.id", ondelete="SET NULL"), default=None,
        index=True, comment="来源记忆（可选，删除记忆时置空）")
    source: Mapped[str] = mapped_column(default="user", comment="seed/user")
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now, onupdate=datetime.now)
    deleted_at: Mapped[datetime | None] = mapped_column(default=None, comment="软删除时间")


class GrowthSubject(Base):
    """成长追踪主体：宝宝/宠物等独立时间轴的归属。

    - birthday 是「年龄锚点」：meta（宝宝 · 2岁3个月）与 S14 副标题都由它实时派生；
    - birth_label 承担展示串（如「出生于 2024年5月20日」「2023年4月来到家」），
      生日未知的主体（如领养的宠物）可只填 birth_label，不参与年龄计算。
    """

    __tablename__ = "growth_subjects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(default=LOCAL_OWNER, comment="数据所有者（多用户铺路）")
    name: Mapped[str] = mapped_column(comment="主体名称，如 小橙子/豆豆")
    kind: Mapped[str] = mapped_column(default="baby", comment="类型: baby/pet/other")
    birthday: Mapped[date | None] = mapped_column(default=None, comment="生日/开始日期（年龄锚点）")
    birth_label: Mapped[str | None] = mapped_column(default=None, comment="展示串，如 出生于2024年5月20日")
    note: Mapped[str | None] = mapped_column(default=None, comment="备注（如品种 金毛）")
    source: Mapped[str] = mapped_column(default="user", comment="seed/user")
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now, onupdate=datetime.now)
    deleted_at: Mapped[datetime | None] = mapped_column(default=None, comment="软删除时间")


class GrowthMilestone(Base):
    """成长里程碑：主体时间轴上的节点，可选回链一条记忆（点击查看详情）。"""

    __tablename__ = "growth_milestones"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("growth_subjects.id", ondelete="CASCADE"), index=True,
        comment="所属主体")
    memory_id: Mapped[int | None] = mapped_column(
        ForeignKey("memories.id", ondelete="SET NULL"), default=None,
        index=True, comment="来源记忆（可选，删除记忆时置空）")
    title: Mapped[str] = mapped_column(comment="里程碑标题，如 会叫\"妈妈\"了")
    content: Mapped[str | None] = mapped_column(default=None, comment="补充描述")
    happened_on: Mapped[date] = mapped_column(comment="发生日期（排序锚点）")
    is_major: Mapped[bool] = mapped_column(default=False, comment="重要里程碑（大节点样式）")
    has_pic: Mapped[bool] = mapped_column(default=False, comment="带照片占位（媒体上传前的占位标记）")
    owner_id: Mapped[str] = mapped_column(default=LOCAL_OWNER, comment="数据所有者（多用户铺路）")
    source: Mapped[str] = mapped_column(default="user", comment="seed/user")
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now, onupdate=datetime.now)
    deleted_at: Mapped[datetime | None] = mapped_column(default=None, comment="软删除时间")


class TimelineNode(Base):
    """共建时间线节点：情侣/友情「记忆螺旋」的统一存储。

    - kind 区分空间：couple（情侣）/ friend（友情）；
    - node_key 对应前端螺旋图 data-k（meet/travel/…，同空间内唯一）；
    - date_str 存展示日期（如 2022.06）；badge_hint 存模板里的「N视角/M留言」
      计数——当节点回链记忆（memory_id 非空）时，由派生层用 perspectives/
      comments 的真实计数覆盖，保证徽章实时；
    - memory_id 可选回链：点击节点弹窗「回看那段记忆」进详情；
    - node_x/node_y/label_x/label_y 是螺旋布局的 UI 设计坐标（前端 spiralHtml）。
    """

    __tablename__ = "timeline_nodes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(comment="空间: couple/friend")
    node_key: Mapped[str] = mapped_column(comment="节点键（同空间内唯一，如 meet）")
    icon: Mapped[str] = mapped_column(default="heart", comment="图标键（heart/travel/...）")
    title: Mapped[str] = mapped_column(comment="节点名称，如 初见")
    desc: Mapped[str | None] = mapped_column(default=None, comment="节点描述文案")
    date_str: Mapped[str | None] = mapped_column(default=None, comment="展示日期，如 2022.06")
    badge_hint: Mapped[str | None] = mapped_column(
        default=None, comment="模板视角/留言计数（如 2视角），有回链时由派生层实时覆盖")
    memory_id: Mapped[int | None] = mapped_column(
        ForeignKey("memories.id", ondelete="SET NULL"), default=None,
        index=True, comment="回链记忆（可选，点击进详情）")
    node_x: Mapped[float] = mapped_column(default=0.0, comment="螺旋节点 x")
    node_y: Mapped[float] = mapped_column(default=0.0, comment="螺旋节点 y")
    label_x: Mapped[float] = mapped_column(default=0.0, comment="标签 x")
    label_y: Mapped[float] = mapped_column(default=0.0, comment="标签 y")
    is_latest: Mapped[bool] = mapped_column(default=False, comment="最新节点标记")
    sort_order: Mapped[int] = mapped_column(default=0, comment="排序（旧→新）")
    source: Mapped[str] = mapped_column(default="user", comment="seed/user")
    owner_id: Mapped[str] = mapped_column(default=LOCAL_OWNER, comment="数据所有者（多用户铺路）")
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now, onupdate=datetime.now)
    deleted_at: Mapped[datetime | None] = mapped_column(default=None, comment="软删除时间")


class InviteMember(Base):
    """共建空间成员：情侣待接受 + 友情成员（含待接受）。

    space 区分 couple/friend；state 为「已加入/待接受」展示态；
    note 存展示串（如 已加入 · 3 小时前）；sort_order 保证列表顺序。
    """

    __tablename__ = "invite_members"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    space: Mapped[str] = mapped_column(comment="空间: couple/friend")
    name: Mapped[str] = mapped_column(comment="成员昵称")
    avatar: Mapped[str | None] = mapped_column(default=None, comment="头像字（单字）")
    bg: Mapped[str | None] = mapped_column(default=None, comment="头像背景色")
    state: Mapped[str] = mapped_column(default="待接受", comment="已加入/待接受")
    note: Mapped[str | None] = mapped_column(default=None, comment="展示串，如 已加入 · 3 小时前")
    sort_order: Mapped[int] = mapped_column(default=0, comment="排序（旧→新）")
    source: Mapped[str] = mapped_column(default="user", comment="seed/user")
    owner_id: Mapped[str] = mapped_column(default=LOCAL_OWNER, comment="数据所有者（多用户铺路）")
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now, onupdate=datetime.now)
    deleted_at: Mapped[datetime | None] = mapped_column(default=None, comment="软删除时间")


class User(Base):
    """登录账号（v0.9：多用户体系落地）。

    - username 唯一（软删除的账号仍占名，避免复用引起歧义）；
    - password_hash/salt 由 PBKDF2 派生（见 hash_password / verify_password）；
    - nickname/avatar 供「我的」页展示；avatar 为头像字（单字）。
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(unique=True, index=True, comment="登录账号（唯一）")
    password_hash: Mapped[str] = mapped_column(comment="PBKDF2 密码哈希（hex）")
    salt: Mapped[str] = mapped_column(comment="每用户随机盐（hex）")
    nickname: Mapped[str] = mapped_column(default="", comment="展示昵称")
    avatar: Mapped[str | None] = mapped_column(default=None, comment="头像字（单字）")
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now, onupdate=datetime.now)
    deleted_at: Mapped[datetime | None] = mapped_column(default=None, comment="软删除时间（注销账号）")


class AuthSession(Base):
    """登录会话令牌（v0.9）：登出即吊销，过期自动失效。

    命名 AuthSession 避免与 sqlalchemy.orm.Session 冲突。
    """

    __tablename__ = "sessions"

    token: Mapped[str] = mapped_column(primary_key=True, comment="会话令牌（urlsafe base64）")
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, comment="所属用户")
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    expires_at: Mapped[datetime] = mapped_column(comment="过期时间")


# SQLite + FastAPI(sync endpoint 跑线程池) 需要 check_same_thread=False
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    echo=False,
)


# ---------------------------------------------------------------------------
# 轻量迁移：已有库补列 / 补索引（create_all 不会改已存在的表）
# ---------------------------------------------------------------------------
def _migrate() -> None:
    with engine.begin() as conn:
        # 通用补列：模型里声明了、表里没有的列，自动 ALTER TABLE 补上
        for model in (Memory, Perspective, Comment, Anniversary,
                      GrowthSubject, GrowthMilestone, TimelineNode, InviteMember,
                      User, AuthSession):
            _ensure_columns(conn, model)
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_memories_scene ON memories(scene)")
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_memories_precise ON memories(precise_at)")
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_memories_scene_alive "
            "ON memories(scene, deleted_at, precise_at)")
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_memories_alive "
            "ON memories(deleted_at, precise_at)")
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_anniv_alive "
            "ON anniversaries(deleted_at, month, day)")
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_growth_ms_alive "
            "ON growth_milestones(subject_id, deleted_at, happened_on)")
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_tl_nodes_alive "
            "ON timeline_nodes(kind, deleted_at, sort_order)")
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_invite_alive "
            "ON invite_members(space, deleted_at, sort_order)")
        # 兼容旧库：模板演示数据（source=seed）统一归为共享 seed，
        # 避免「登录时接管 local」把演示数据据为己有（v0.9 多用户隔离前提）
        conn.exec_driver_sql(
            "UPDATE memories SET owner_id='seed' "
            "WHERE source='seed' AND owner_id<>'seed'")
        # v0.9.3：清除历史导入的演示种子（假）数据——新装不再导入种子；
        # 先删挂在种子记忆上的互动（留言/多视角），再删各表的种子行
        conn.exec_driver_sql(
            "DELETE FROM comments WHERE memory_id IN "
            "(SELECT id FROM memories WHERE owner_id='seed')")
        conn.exec_driver_sql(
            "DELETE FROM perspectives WHERE memory_id IN "
            "(SELECT id FROM memories WHERE owner_id='seed')")
        for _table in ("memories", "anniversaries", "growth_milestones",
                       "growth_subjects", "timeline_nodes", "invite_members"):
            conn.exec_driver_sql(f"DELETE FROM {_table} WHERE owner_id='seed'")
        logger.info("迁移检查完成：模型列与索引已对齐（历史种子数据已清除）")


def _ensure_columns(conn, model: type) -> None:
    table = model.__tablename__
    cols = [r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})")]
    if not cols:
        return  # 表尚未创建（首次启动由 create_all 负责）
    for col in model.__table__.columns:
        if col.name in cols:
            continue
        coltype = col.type.compile(engine.dialect)
        default = ""
        if col.default is not None and col.default.is_scalar:
            default = f" DEFAULT {col.default.arg!r}"
        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {col.name} {coltype}{default}")
        logger.info("迁移：%s 补列 %s", table, col.name)


# ---------------------------------------------------------------------------
# 初始化：建表 + 迁移
# ---------------------------------------------------------------------------
def init_db(template: dict[str, Any]) -> None:
    """建表/迁移。

    v0.9.3：不再从模板导入演示种子数据（陈昊/苏苏等假数据），
    全新安装从空库开始；历史库中的种子行由 _migrate() 统一清除。
    template 入参保留以兼容调用方签名（lifespan），当前未使用。
    """
    Base.metadata.create_all(engine)
    _migrate()
    with Session(engine) as session:
        count = session.scalar(select(func.count(Memory.id))) or 0
        logger.info("数据库就绪：memories 表当前 %d 条记忆（%s）", count, DB_PATH.name)


def _parse_hhmm(s: str) -> tuple[int, int]:
    m = re.search(r"(\d{1,2}):(\d{2})", str(s))
    return (int(m.group(1)), int(m.group(2))) if m else (12, 0)


# ---------------------------------------------------------------------------
# CRUD 辅助（仓库层使用）
# ---------------------------------------------------------------------------
def list_memories(scene: str | None = None,
                  owner: str = LOCAL_OWNER,
                  limit: int | None = None,
                  before_id: int | None = None) -> list[Memory]:
    """未删除的记忆；精确时间在前（倒序），模糊时间在后。支持游标分页。

    owner 过滤：仅返回「共享演示数据（seed）+ 当前所有者」的记忆，
    实现多用户数据隔离（v0.9）。
    """
    with Session(engine) as session:
        stmt = (
            select(Memory)
            .where(Memory.deleted_at.is_(None),
                   Memory.owner_id.in_([SEED_OWNER, owner]))
            .order_by(Memory.precise_at.desc().nulls_last(), Memory.created_at.desc())
        )
        if scene:
            stmt = stmt.where(Memory.scene == scene)
        if before_id is not None:
            stmt = stmt.where(Memory.id < before_id)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(session.scalars(stmt))


def get_memory(mid: int) -> Memory | None:
    with Session(engine) as session:
        mem = session.get(Memory, mid)
        return None if (mem is None or mem.deleted_at is not None) else mem


def create_memory(**kw: Any) -> Memory:
    with Session(engine) as session:
        mem = Memory(**kw)
        session.add(mem)
        session.commit()
        session.refresh(mem)
        return mem


def update_memory(mid: int, owner: str = LOCAL_OWNER, **fields: Any) -> Memory | None:
    """部分更新记忆；按 owner 校验所有权（与删除同一套 IDOR 防护）。

    支持更新：scene / feel / emotions / voice / media / timestamp_type / precise_at /
    fuzzy_label / fuzzy_note。仅传入的字段会被改写（PATCH 语义）。
    返回更新后的对象；记忆不存在/已删/越权时返回 None。
    """
    allowed = {"scene", "feel", "emotions", "voice", "media",
               "timestamp_type", "precise_at", "fuzzy_label", "fuzzy_note"}
    patch = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not patch:
        return None
    with Session(engine) as session:
        mem = session.get(Memory, mid)
        if mem is None or mem.deleted_at is not None:
            return None
        if mem.owner_id not in (owner, SEED_OWNER):
            logger.warning("越权编辑拦截：记忆 #%d 属于 %s，请求方 %s", mid, mem.owner_id, owner)
            return None
        for k, v in patch.items():
            setattr(mem, k, v)
        session.commit()
        session.refresh(mem)
        return mem


def soft_delete_memory(mid: int, owner: str = LOCAL_OWNER) -> bool:
    """软删除；按 owner 校验所有权（防越权删除，IDOR 防护的本地版）。

    本地单用户阶段：local 所有者可管理 local + seed 数据；
    多用户阶段：此函数签名不变，owner 换为登录用户 id 即可。
    """
    with Session(engine) as session:
        mem = session.get(Memory, mid)
        if mem is None or mem.deleted_at is not None:
            return False
        if mem.owner_id not in (owner, SEED_OWNER):
            logger.warning("越权删除拦截：记忆 #%d 属于 %s，请求方 %s", mid, mem.owner_id, owner)
            return False
        mem.deleted_at = datetime.now()
        # v0.9.4：级联软删除关联的纪念日（记忆删了，纪念日不该残留成示例）
        for anniv in session.scalars(
                select(Anniversary).where(
                    Anniversary.linked_memory_id == mid,
                    Anniversary.deleted_at.is_(None))):
            anniv.deleted_at = datetime.now()
        session.commit()
        return True


# ---- 多视角 ----
def list_perspectives(memory_id: int) -> list[Perspective]:
    with Session(engine) as session:
        stmt = (select(Perspective)
                .where(Perspective.memory_id == memory_id,
                       Perspective.deleted_at.is_(None))
                .order_by(Perspective.created_at.asc()))
        return list(session.scalars(stmt))


def create_perspective(memory_id: int, **kw: Any) -> Perspective:
    with Session(engine) as session:
        p = Perspective(memory_id=memory_id, **kw)
        session.add(p)
        session.commit()
        session.refresh(p)
        return p


def soft_delete_perspective(pid: int) -> bool:
    with Session(engine) as session:
        p = session.get(Perspective, pid)
        if p is None or p.deleted_at is not None:
            return False
        p.deleted_at = datetime.now()
        session.commit()
        return True


# ---- 留言 ----
def list_comments(memory_id: int) -> list[Comment]:
    with Session(engine) as session:
        stmt = (select(Comment)
                .where(Comment.memory_id == memory_id,
                       Comment.deleted_at.is_(None))
                .order_by(Comment.created_at.asc()))
        return list(session.scalars(stmt))


def create_comment(memory_id: int, **kw: Any) -> Comment:
    with Session(engine) as session:
        c = Comment(memory_id=memory_id, **kw)
        session.add(c)
        session.commit()
        session.refresh(c)
        return c


def soft_delete_comment(cid: int) -> bool:
    with Session(engine) as session:
        c = session.get(Comment, cid)
        if c is None or c.deleted_at is not None:
            return False
        c.deleted_at = datetime.now()
        session.commit()
        return True


# ---- 纪念日 ----
def list_anniversaries(owner: str = LOCAL_OWNER) -> list[Anniversary]:
    """未删除的纪念日，按创建先后（旧→新，与演示列表顺序一致）；owner 过滤。"""
    with Session(engine) as session:
        stmt = (select(Anniversary)
                .where(Anniversary.deleted_at.is_(None),
                       Anniversary.owner_id.in_([SEED_OWNER, owner]))
                .order_by(Anniversary.created_at.asc(), Anniversary.id.asc()))
        return list(session.scalars(stmt))


def create_anniversary(**kw: Any) -> Anniversary:
    with Session(engine) as session:
        a = Anniversary(**kw)
        session.add(a)
        session.commit()
        session.refresh(a)
        return a


def update_anniversary(aid: int, owner: str = LOCAL_OWNER, **fields: Any) -> Anniversary | None:
    """部分更新纪念日（PATCH 语义）；与 update_memory 同一套所有权校验。

    支持更新：name / month / day / is_lunar / lunar_label / is_recurring /
    remind_days_before / note / linked_memory_id。
    """
    allowed = {"name", "month", "day", "is_lunar", "lunar_label",
               "is_recurring", "remind_days_before", "note", "linked_memory_id"}
    patch = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not patch:
        return None
    with Session(engine) as session:
        ann = session.get(Anniversary, aid)
        if ann is None or ann.deleted_at is not None:
            return None
        if ann.owner_id not in (owner, SEED_OWNER):
            logger.warning("越权编辑拦截：纪念日 #%d 属于 %s，请求方 %s", aid, ann.owner_id, owner)
            return None
        for k, v in patch.items():
            setattr(ann, k, v)
        session.commit()
        session.refresh(ann)
        return ann


def soft_delete_anniversary(aid: int, owner: str = LOCAL_OWNER) -> bool:
    """软删除纪念日；与 soft_delete_memory 同一套所有权校验。"""
    with Session(engine) as session:
        ann = session.get(Anniversary, aid)
        if ann is None or ann.deleted_at is not None:
            return False
        if ann.owner_id not in (owner, SEED_OWNER):
            logger.warning("越权删除拦截：纪念日 #%d 属于 %s，请求方 %s", aid, ann.owner_id, owner)
            return False
        ann.deleted_at = datetime.now()
        session.commit()
        return True


# ---- 成长追踪：主体 ----
GROWTH_KINDS = ("baby", "pet", "other")


def list_growth_subjects(owner: str = LOCAL_OWNER) -> list[GrowthSubject]:
    """未删除的主体，按创建先后（与演示列表顺序一致）；owner 过滤。"""
    with Session(engine) as session:
        stmt = (select(GrowthSubject)
                .where(GrowthSubject.deleted_at.is_(None),
                       GrowthSubject.owner_id.in_([SEED_OWNER, owner]))
                .order_by(GrowthSubject.created_at.asc(), GrowthSubject.id.asc()))
        return list(session.scalars(stmt))


def get_growth_subject(sid: int) -> GrowthSubject | None:
    with Session(engine) as session:
        sub = session.get(GrowthSubject, sid)
        return None if (sub is None or sub.deleted_at is not None) else sub


def create_growth_subject(**kw: Any) -> GrowthSubject:
    with Session(engine) as session:
        s = GrowthSubject(**kw)
        session.add(s)
        session.commit()
        session.refresh(s)
        return s


def update_growth_subject(sid: int, owner: str = LOCAL_OWNER,
                          **fields: Any) -> GrowthSubject | None:
    """部分更新主体（PATCH 语义）；与 update_memory 同一套所有权校验。

    支持更新：name / kind / birthday / birth_label / note。
    """
    allowed = {"name", "kind", "birthday", "birth_label", "note"}
    patch = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not patch:
        return None
    with Session(engine) as session:
        sub = session.get(GrowthSubject, sid)
        if sub is None or sub.deleted_at is not None:
            return None
        if sub.owner_id not in (owner, SEED_OWNER):
            logger.warning("越权编辑拦截：主体 #%d 属于 %s，请求方 %s",
                           sid, sub.owner_id, owner)
            return None
        for k, v in patch.items():
            setattr(sub, k, v)
        session.commit()
        session.refresh(sub)
        return sub


def soft_delete_growth_subject(sid: int, owner: str = LOCAL_OWNER) -> bool:
    """软删除主体，同一事务内级联软删其全部里程碑（数据合规：先软删后清除）。"""
    with Session(engine) as session:
        sub = session.get(GrowthSubject, sid)
        if sub is None or sub.deleted_at is not None:
            return False
        if sub.owner_id not in (owner, SEED_OWNER):
            logger.warning("越权删除拦截：主体 #%d 属于 %s，请求方 %s",
                           sid, sub.owner_id, owner)
            return False
        now = datetime.now()
        sub.deleted_at = now
        for m in session.scalars(select(GrowthMilestone).where(
                GrowthMilestone.subject_id == sid,
                GrowthMilestone.deleted_at.is_(None))):
            m.deleted_at = now
        session.commit()
        return True


# ---- 成长追踪：里程碑 ----
def list_growth_milestones(subject_id: int | None = None,
                           owner: str = LOCAL_OWNER) -> list[GrowthMilestone]:
    """未删除的里程碑，按发生日期倒序（新→旧，与时间轴展示一致）；owner 过滤。"""
    with Session(engine) as session:
        stmt = (select(GrowthMilestone)
                .where(GrowthMilestone.deleted_at.is_(None),
                       GrowthMilestone.owner_id.in_([SEED_OWNER, owner]))
                .order_by(GrowthMilestone.happened_on.desc(), GrowthMilestone.id.desc()))
        if subject_id is not None:
            stmt = stmt.where(GrowthMilestone.subject_id == subject_id)
        return list(session.scalars(stmt))


def get_growth_milestone(mid: int) -> GrowthMilestone | None:
    with Session(engine) as session:
        m = session.get(GrowthMilestone, mid)
        return None if (m is None or m.deleted_at is not None) else m


def create_growth_milestone(**kw: Any) -> GrowthMilestone:
    with Session(engine) as session:
        m = GrowthMilestone(**kw)
        session.add(m)
        session.commit()
        session.refresh(m)
        return m


def update_growth_milestone(mid: int, owner: str = LOCAL_OWNER,
                            **fields: Any) -> GrowthMilestone | None:
    """部分更新里程碑（PATCH 语义）；所有权按里程碑自身的 owner_id 校验。"""
    allowed = {"title", "content", "happened_on", "is_major", "has_pic", "memory_id"}
    patch = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not patch:
        return None
    with Session(engine) as session:
        m = session.get(GrowthMilestone, mid)
        if m is None or m.deleted_at is not None:
            return None
        if m.owner_id not in (owner, SEED_OWNER):
            logger.warning("越权编辑拦截：里程碑 #%d 属于 %s，请求方 %s",
                           mid, m.owner_id, owner)
            return None
        for k, v in patch.items():
            setattr(m, k, v)
        session.commit()
        session.refresh(m)
        return m


def soft_delete_growth_milestone(mid: int, owner: str = LOCAL_OWNER) -> bool:
    """软删除里程碑；所有权按里程碑自身的 owner_id 校验。"""
    with Session(engine) as session:
        m = session.get(GrowthMilestone, mid)
        if m is None or m.deleted_at is not None:
            return False
        if m.owner_id not in (owner, SEED_OWNER):
            logger.warning("越权删除拦截：里程碑 #%d 属于 %s，请求方 %s",
                           mid, m.owner_id, owner)
            return False
        m.deleted_at = datetime.now()
        session.commit()
        return True


# ---- 记忆媒体（配合预签名上传）----
def append_memory_media(mid: int, item: dict, owner: str = LOCAL_OWNER) -> Memory | None:
    """把媒体项追加到记忆的 media 数组（memories.media JSON 列）。

    所有权校验与 update_memory 同一套；item 形如 {key, url, kind}。
    """
    with Session(engine) as session:
        mem = session.get(Memory, mid)
        if mem is None or mem.deleted_at is not None:
            return None
        if mem.owner_id not in (owner, SEED_OWNER):
            logger.warning("越权编辑拦截：记忆 #%d 属于 %s，请求方 %s", mid, mem.owner_id, owner)
            return None
        media = list(mem.media or [])
        media.append(item)
        mem.media = media
        session.commit()
        session.refresh(mem)
        return mem


# ---- 共建时间线节点 ----
def list_timeline_nodes(kind: str | None = None,
                        owner: str = LOCAL_OWNER) -> list[TimelineNode]:
    """未删除的节点，按 sort_order 升序（旧→新，与螺旋由内到外一致）；owner 过滤。"""
    with Session(engine) as session:
        stmt = (select(TimelineNode)
                .where(TimelineNode.deleted_at.is_(None),
                       TimelineNode.owner_id.in_([SEED_OWNER, owner]))
                .order_by(TimelineNode.sort_order.asc(), TimelineNode.id.asc()))
        if kind:
            stmt = stmt.where(TimelineNode.kind == kind)
        return list(session.scalars(stmt))


def create_timeline_node(**kw: Any) -> TimelineNode:
    with Session(engine) as session:
        n = TimelineNode(**kw)
        session.add(n)
        session.commit()
        session.refresh(n)
        return n


def update_timeline_node(nid: int, owner: str = LOCAL_OWNER,
                         **fields: Any) -> TimelineNode | None:
    """部分更新时间线节点（PATCH 语义）；与 update_memory 同一套所有权校验。

    支持更新：node_key / icon / title / desc / date_str / badge_hint /
    memory_id / node_x / node_y / label_x / label_y / is_latest / sort_order。
    """
    allowed = {"node_key", "icon", "title", "desc", "date_str", "badge_hint",
               "memory_id", "node_x", "node_y", "label_x", "label_y",
               "is_latest", "sort_order"}
    patch = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not patch:
        return None
    with Session(engine) as session:
        n = session.get(TimelineNode, nid)
        if n is None or n.deleted_at is not None:
            return None
        if n.owner_id not in (owner, SEED_OWNER):
            logger.warning("越权编辑拦截：时间线节点 #%d 属于 %s，请求方 %s",
                           nid, n.owner_id, owner)
            return None
        for k, v in patch.items():
            setattr(n, k, v)
        session.commit()
        session.refresh(n)
        return n


def soft_delete_timeline_node(nid: int, owner: str = LOCAL_OWNER) -> bool:
    """软删除时间线节点；与 soft_delete_memory 同一套所有权校验。"""
    with Session(engine) as session:
        n = session.get(TimelineNode, nid)
        if n is None or n.deleted_at is not None:
            return False
        if n.owner_id not in (owner, SEED_OWNER):
            logger.warning("越权删除拦截：时间线节点 #%d 属于 %s，请求方 %s",
                           nid, n.owner_id, owner)
            return False
        n.deleted_at = datetime.now()
        session.commit()
        return True


# ---- 共建空间成员 ----
def list_invite_members(space: str | None = None,
                        owner: str = LOCAL_OWNER) -> list[InviteMember]:
    """未删除的成员，按 sort_order 升序（与演示列表顺序一致）；owner 过滤。"""
    with Session(engine) as session:
        stmt = (select(InviteMember)
                .where(InviteMember.deleted_at.is_(None),
                       InviteMember.owner_id.in_([SEED_OWNER, owner]))
                .order_by(InviteMember.sort_order.asc(), InviteMember.id.asc()))
        if space:
            stmt = stmt.where(InviteMember.space == space)
        return list(session.scalars(stmt))


def create_invite_member(**kw: Any) -> InviteMember:
    with Session(engine) as session:
        m = InviteMember(**kw)
        session.add(m)
        session.commit()
        session.refresh(m)
        return m


def soft_delete_invite_member(mid: int, owner: str = LOCAL_OWNER) -> bool:
    """软删除成员；与 soft_delete_memory 同一套所有权校验。"""
    with Session(engine) as session:
        m = session.get(InviteMember, mid)
        if m is None or m.deleted_at is not None:
            return False
        if m.owner_id not in (owner, SEED_OWNER):
            logger.warning("越权删除拦截：成员 #%d 属于 %s，请求方 %s",
                           mid, m.owner_id, owner)
            return False
        m.deleted_at = datetime.now()
        session.commit()
        return True


# ---- 聚合计数（避免 N+1：一次分组查询拿全部计数）----
def engagement_counts() -> tuple[dict[int, int], dict[int, int]]:
    """返回 ({memory_id: 多视角数}, {memory_id: 留言数})，仅统计未删除。"""
    with Session(engine) as session:
        pc = dict(session.execute(
            select(Perspective.memory_id, func.count(Perspective.id))
            .where(Perspective.deleted_at.is_(None))
            .group_by(Perspective.memory_id)).all())
        cc = dict(session.execute(
            select(Comment.memory_id, func.count(Comment.id))
            .where(Comment.deleted_at.is_(None))
            .group_by(Comment.memory_id)).all())
        return pc, cc


# ---------------------------------------------------------------------------
# 账号与登录（v0.9）：密码哈希 / 用户 CRUD / 会话令牌 / 数据归属迁移
# ---------------------------------------------------------------------------
def user_owner_id(uid: int) -> str:
    """用户的数据所有者标识（owner_id 列存这个串）。"""
    return f"{OWNER_PREFIX}{uid}"


def hash_password(password: str) -> tuple[str, str]:
    """PBKDF2-HMAC-SHA256 派生，返回 (salt_hex, hash_hex)。

    每用户随机 128 位盐 + 200k 迭代；Python 内置实现，无第三方依赖。
    """
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return salt, digest.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    """常数时间校验密码（hmac.compare_digest 防时序侧信道）。"""
    try:
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"),
            bytes.fromhex(salt_hex), PBKDF2_ITERATIONS)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), hash_hex)


def create_user(username: str, password: str, nickname: str | None = None,
                avatar: str | None = None) -> User:
    """新建账号：密码加盐哈希后落库；昵称缺省取账号名。"""
    salt, pw_hash = hash_password(password)
    with Session(engine) as session:
        u = User(
            username=username.strip(),
            password_hash=pw_hash,
            salt=salt,
            nickname=(nickname or "").strip() or username.strip(),
            avatar=(avatar or "").strip() or None,
        )
        session.add(u)
        session.commit()
        session.refresh(u)
        return u


def get_user_by_username(username: str) -> User | None:
    """按账号名查询（排除已注销/软删除）。"""
    with Session(engine) as session:
        u = session.scalar(select(User).where(
            User.username == username.strip(), User.deleted_at.is_(None)))
        return u


def get_user_by_id(uid: int) -> User | None:
    """按 id 查询（排除已注销/软删除）。"""
    with Session(engine) as session:
        u = session.get(User, uid)
        return None if (u is None or u.deleted_at is not None) else u


def update_user(uid: int, **fields: Any) -> User | None:
    """更新用户资料（PATCH 语义）：nickname / avatar。"""
    allowed = {"nickname", "avatar"}
    patch = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not patch:
        return None
    with Session(engine) as session:
        u = session.get(User, uid)
        if u is None or u.deleted_at is not None:
            return None
        for k, v in patch.items():
            setattr(u, k, (v or "").strip() or None if k == "avatar" else (v or "").strip())
        session.commit()
        session.refresh(u)
        return u


def soft_delete_user(uid: int) -> bool:
    """注销账号（软删除）+ 吊销其全部会话。"""
    with Session(engine) as session:
        u = session.get(User, uid)
        if u is None or u.deleted_at is not None:
            return False
        u.deleted_at = datetime.now()
        session.execute(
            delete(AuthSession).where(AuthSession.user_id == uid))
        session.commit()
        return True


def count_user_memories(uid: int) -> int:
    """统计该用户名下的记忆条数（未删除；不含共享 seed）。"""
    owner = user_owner_id(uid)
    with Session(engine) as session:
        return session.scalar(
            select(func.count(Memory.id)).where(
                Memory.owner_id == owner, Memory.deleted_at.is_(None))) or 0


def create_session(user_id: int) -> str:
    """签发会话令牌（urlsafe base64，32 字节随机）；返回 token 字符串。"""
    token = secrets.token_urlsafe(32)
    with Session(engine) as session:
        session.add(AuthSession(
            token=token, user_id=user_id,
            expires_at=datetime.now() + timedelta(days=SESSION_TTL_DAYS)))
        session.commit()
    return token


def get_session_user(token: str) -> User | None:
    """按令牌取有效会话对应的用户（校验过期 + 用户未注销）。"""
    if not token:
        return None
    with Session(engine) as session:
        s = session.get(AuthSession, token)
        if s is None or s.expires_at < datetime.now():
            return None
        u = session.get(User, s.user_id)
        return None if (u is None or u.deleted_at is not None) else u


def delete_session(token: str) -> bool:
    """吊销会话（登出）。"""
    if not token:
        return False
    with Session(engine) as session:
        s = session.get(AuthSession, token)
        if s is None:
            return False
        session.delete(s)
        session.commit()
        return True


def delete_user_sessions(user_id: int) -> int:
    """吊销某用户的全部会话（改密/注销时使用）；返回吊销条数。"""
    with Session(engine) as session:
        rows = session.execute(
            delete(AuthSession).where(AuthSession.user_id == user_id))
        session.commit()
        return rows.rowcount or 0


def adopt_local_data(user_id: int) -> int:
    """登录/注册时把游客阶段（owner=local）的数据归到该用户名下。

    说明：游客在「本地模式」下写的数据先落 owner=local；一旦登录，
    这些数据视为该用户的个人数据迁移为 user:{id}，保证数据不丢。
    返回迁移的条目总数。
    """
    new_owner = user_owner_id(user_id)
    total = 0
    tables = (Memory, Anniversary, GrowthSubject, GrowthMilestone,
              TimelineNode, InviteMember)
    with Session(engine) as session:
        for model in tables:
            n = session.execute(
                update(model)
                .where(model.owner_id == LOCAL_OWNER)
                .values(owner_id=new_owner))
            total += n.rowcount or 0
        if total:
            session.commit()
            logger.info("登录/注册数据归属迁移：%d 条 local 数据 → %s", total, new_owner)
        else:
            session.rollback()
    return total
