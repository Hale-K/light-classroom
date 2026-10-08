"""课件文本生成：提示词组装 + 流式调用（模型可替换，业务不感知具体服务商）。"""
from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.ai.model.chat import ChatEndpoint, stream_chat

GENERATE_TIMEOUT = 600
GENERATE_MAX_TOKENS = 16384
GENERATE_SYSTEM = "你是资深的互动课件开发者，为中小学教师制作可直接在浏览器打开的单文件 HTML 课件。"


@dataclass(frozen=True)
class CoursewareGenerationRequest:
    """一次课件生成请求（来自工作台表单）。"""

    title: str
    stage: str = ""
    grade_name: str = ""
    subject_name: str = ""
    textbook_version: str = ""
    chapter: str = ""
    requirement: str = ""


def build_generation_prompt(req: CoursewareGenerationRequest) -> str:
    parts = [f"请为「{req.stage or '中小学'}·{req.grade_name or ''}·{req.subject_name or '综合'}」"
             f"制作一堂课的沉浸式互动网页课件，课题：《{req.title}》。"]
    if req.textbook_version:
        parts.append(f"教材版本：{req.textbook_version}。")
    if req.chapter:
        parts.append(f"对准章节：{req.chapter}。")
    parts += [
        "技术要求：",
        "1. 输出一个完整可运行的单文件 HTML，所有 CSS/JS 内联；如需 3D/沉浸式场景用 Three.js"
        "（<script src=\"https://unpkg.com/three@0.128.0/build/three.min.js\">，控制器 "
        "https://unpkg.com/three@0.128.0/examples/js/controls/OrbitControls.js），"
        "低学段也可以用纯 HTML/CSS/JS 做卡片式互动；禁止引用任何外部图片/模型/音频，视觉全部用代码程序化生成",
        "2. 围绕本课核心知识点设计 3-5 个交互式知识热点，点击弹出中文知识卡片，每张卡片配 1 道选择题并即时判定",
        "3. 支持 OrbitControls 拖拽旋转缩放或页面内交互，手机触屏可用，全中文 UI",
        "4. 页面顶部有课题标题与任务清单（知识点收集进度），集齐后弹出「本课小结」",
        "5. 代码带中文注释，结构清晰，控制在 800 行以内",
    ]
    if req.requirement.strip():
        parts.append(f"教师的额外要求：{req.requirement.strip()}")
    parts.append("只输出完整 HTML 代码，不要任何解释文字或代码围栏。")
    return "\n".join(parts)


def strip_fences(text: str) -> str:
    """截取模型输出中真正的 HTML 文档（去掉围栏与前后杂文）。"""
    start = re.search(r"<!DOCTYPE html|<html", text, re.IGNORECASE)
    if start:
        text = text[start.start():]
    tail = text.lower().rfind("</html>")
    if tail != -1:
        text = text[: tail + 7]
    return text.strip()


def is_valid_courseware_html(text: str) -> bool:
    return "<html" in text.lower()


async def stream_courseware_html(endpoint: ChatEndpoint, req: CoursewareGenerationRequest) -> AsyncIterator[str]:
    """按所选服务商端点流式产出课件 HTML 片段。"""
    async for piece in stream_chat(
        base_url=endpoint.base_url,
        api_key=endpoint.api_key,
        model=endpoint.model,
        timeout=GENERATE_TIMEOUT,
        temperature=0.5,
        max_tokens=GENERATE_MAX_TOKENS,
        messages=[
            {"role": "system", "content": GENERATE_SYSTEM},
            {"role": "user", "content": build_generation_prompt(req)},
        ],
    ):
        yield piece
