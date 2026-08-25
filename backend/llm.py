# -*- coding: utf-8 -*-
"""
记忆漩涡 · 大模型生成模块
================================================
职责：把用户数据（场景选择等）整合成提示词 → 调用大模型 →
把返回结果包装成与 test_data.json 完全一致的结构。

免费大模型（测试用，OpenAI 兼容协议）：
    智谱 GLM-4-Flash（免费）：https://open.bigmodel.cn  注册后获取 API Key
    环境变量配置：
        LLM_API_KEY   = 你的 Key（不配置则自动走本地模拟模式）
        LLM_BASE_URL  = https://open.bigmodel.cn/api/paas/v4   （默认）
        LLM_MODEL     = glm-4-flash                            （默认，免费）
    也可切换其他 OpenAI 兼容服务（如 SiliconFlow 免费模型），改 BASE_URL/MODEL 即可。
"""

import json
import logging
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("memory-vortex.llm")

# ---------------------------------------------------------------------------
# 配置（环境变量优先；也可把 Key 存到 backend/llm_api_key.txt 文件，免设环境变量）
# ---------------------------------------------------------------------------
def _load_api_key() -> str:
    key = os.environ.get("LLM_API_KEY", "").strip()
    if key:
        return key
    key_file = Path(__file__).resolve().parent / "llm_api_key.txt"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    return ""


API_KEY = _load_api_key()
BASE_URL = os.environ.get("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
MODEL = os.environ.get("LLM_MODEL", "glm-4-flash")
TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "120"))
MAX_RETRIES = 2

SCENE_NAMES = {
    "personal": "个人博物馆",
    "couple": "情侣空间",
    "friend": "友情空间",
    "growth": "成长追踪",
}

# 返回结构必须包含的顶层模块（与 test_data.js 对齐）
REQUIRED_KEYS = [
    "meta", "scenes", "home", "emotions", "timeSettings", "memoryDetail",
    "anniversaries", "invites", "coupleTimeline", "friendTimeline",
    "growth", "otd", "timelineHub",
]


# ---------------------------------------------------------------------------
# 提示词构建：用户数据 + 数据模板 → messages
# ---------------------------------------------------------------------------
def build_messages(base_data: dict, scene: str, user_data: dict) -> list:
    scene_name = SCENE_NAMES.get(scene, scene)
    # 紧凑 JSON 注入，减少 token 消耗与生成时长
    template_json = json.dumps(base_data, ensure_ascii=False, separators=(",", ":"))

    system = (
        "你是「记忆漩涡 MemoryVortex」App 的记忆数据生成引擎。"
        "你的任务是根据用户信息，生成一套精炼的 App 演示数据。"
        "你必须只输出一个 JSON 对象，不要输出任何解释、markdown 代码块标记或其他文字。"
    )
    user_prompt = f"""请为「记忆漩涡」App 生成演示数据。

## 用户信息
- 用户选择的场景：{scene}（{scene_name}）
- 用户附言：{user_data.get("note") or "无"}

## 输出要求（务必严格遵守，这直接决定解析成败）
1. 只输出一个 JSON 对象，紧凑格式（不要换行、不要缩进、不要空格美化），只包含下面列出的模块；
2. 只需生成这些顶层模块：meta、scenes、home、anniversaries、coupleTimeline、friendTimeline、growth、otd；
3. 各模块的字段名、嵌套结构必须与【数据模板】中对应模块完全一致（参考模板中同名模块的形状）；
4. 条目数量精简（这是硬性要求，防止输出被截断）：home.timeline 3 个日期组、每组 1 条记忆；coupleTimeline.nodes 5 个；friendTimeline.nodes 4 个；anniversaries.list 3 条；growth 2 个主体、每个 3 条 milestones；otd 3 条；
5. 所有内容围绕「{scene_name}」重新创作，真实、有生活质感、有情感温度，中文语境；日期在 2019-2026 年间；人名用常见中文名或昵称；
6. meta 只需包含 note 和 tagline 两个文本字段（note 写一句创作说明）。

## 数据模板（仅供参考字段名与结构，不要照抄内容）
{template_json}"""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]


# ---------------------------------------------------------------------------
# 大模型调用（OpenAI 兼容 chat/completions，流式接收）
# ---------------------------------------------------------------------------
async def _chat_once(messages: list) -> str:
    """单次调用大模型（流式）。异常直接抛出，由上层重试。"""
    url = f"{BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.8,
        "max_tokens": 8192,
        "stream": True,
    }

    chunks: list[str] = []
    finish_reason: str | None = None
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    choice = json.loads(data)["choices"][0]
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                piece = choice.get("delta", {}).get("content")
                if piece:
                    chunks.append(piece)
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]
    content = "".join(chunks)
    if not content:
        raise RuntimeError("流式响应内容为空")
    if finish_reason == "length":
        logger.warning("输出被 max_tokens 截断（%d 字符），JSON 大概率不完整", len(content))
        raise RuntimeError("输出被 max_tokens 截断，请精简生成内容")
    logger.info("大模型调用成功（模型 %s，%d 字符，finish=%s）",
                MODEL, len(content), finish_reason)
    return content


# ---------------------------------------------------------------------------
# 结果解析与包装
# ---------------------------------------------------------------------------
def _repair_json_text(s: str) -> str:
    """修复模型输出 JSON 的常见小瑕疵（免费模型偶发）：尾逗号、中文引号。"""
    s = re.sub(r",\s*([}\]])", r"\1", s)          # 尾逗号: ,} 或 ,]
    s = s.replace("“", '"').replace("”", '"')      # 中文双引号
    return s


def extract_json(text: str) -> dict | None:
    """从模型输出中提取 JSON 对象（容忍 markdown 代码块包裹，带一次自动修复）。"""
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    snippet = cleaned[start:end + 1]
    for candidate in (snippet, _repair_json_text(snippet)):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


def deep_merge(base: dict, override: dict) -> dict:
    """深度合并：override 覆盖 base；数组整体替换；缺失字段回退到模板值。"""
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], val)
        else:
            base[key] = val
    return base


def wrap_as_app_data(base_data: dict, llm_output: dict, scene: str) -> dict:
    """把模型输出包装成与 test_data 完全一致的结构。"""
    merged = deep_merge(deepcopy(base_data), llm_output)
    # 结构兜底：任一必需模块缺失则整体回退到模板值
    for key in REQUIRED_KEYS:
        if key not in merged or merged[key] in (None, {}, []):
            merged[key] = deepcopy(base_data.get(key))
    merged["meta"]["note"] = f"AI 生成 · 模型 {MODEL} · 场景 {SCENE_NAMES.get(scene, scene)}"
    return merged


# ---------------------------------------------------------------------------
# 本地模拟模式（未配置 API Key 时，保证全链路可测）
# ---------------------------------------------------------------------------
def mock_generate(base_data: dict, scene: str, user_data: dict) -> dict:
    scene_name = SCENE_NAMES.get(scene, scene)
    data = deepcopy(base_data)
    data["meta"]["note"] = f"AI 演示数据（本地模拟模式，未配置 LLM_API_KEY）· 场景：{scene_name}"
    data["meta"]["tagline"] = f"AI 正在为「{scene_name}」编织专属回忆"

    # 选中场景置顶并标记推荐
    scenes = data.get("scenes", [])
    sel = [s for s in scenes if s.get("key") == scene]
    rest = [s for s in scenes if s.get("key") != scene]
    if sel:
        sel[0]["rec"] = True
        data["scenes"] = sel + rest

    # 首条时间线感受打标，便于肉眼确认走的是生成接口
    try:
        first = data["home"]["timeline"][0]["items"][0]
        first["feel"] = f"【{scene_name} · AI 生成】" + first["feel"]
    except (KeyError, IndexError):
        pass
    return data


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------
async def generate_dataset(base_data: dict, scene: str, user_data: dict) -> dict:
    """主流程：用户数据 → 提示词 → 大模型 → test_data 同构数据。

    网络失败与 JSON 解析失败都计入重试（免费模型偶发输出瑕疵）。
    """
    if not API_KEY:
        logger.info("未配置 LLM_API_KEY，走本地模拟模式（场景 %s）", scene)
        return mock_generate(base_data, scene, user_data)

    messages = build_messages(base_data, scene, user_data)
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            raw = await _chat_once(messages)
            parsed = extract_json(raw)
            if parsed is None:
                raise RuntimeError("大模型输出无法解析为 JSON")
            return wrap_as_app_data(base_data, parsed, scene)
        except Exception as exc:  # noqa: BLE001 网络失败/截断/解析失败统一重试
            last_err = exc
            logger.warning("第 %d 次生成失败：%s", attempt, exc)
    raise RuntimeError(f"AI 生成失败（已重试 {MAX_RETRIES} 次）：{last_err}") from last_err


def status() -> dict:
    """当前 LLM 配置状态（供调试）。"""
    return {
        "mode": "llm" if API_KEY else "mock",
        "model": MODEL if API_KEY else None,
        "base_url": BASE_URL if API_KEY else None,
    }
