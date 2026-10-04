"""探测 OpenAI 兼容 / Ollama 服务商。"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

PRESETS: dict[str, dict] = {
    "JEV": {"label": "Jev 决策模型", "base": "https://api.typesafe.ai/v1", "models": "/models", "health": "/models", "need_key": True},
    "OLLAMA": {"label": "Ollama（本地）", "base": "http://127.0.0.1:11434", "models": "/api/tags", "health": "/api/version", "need_key": False},
    "OPENAI": {"label": "OpenAI", "base": "https://api.openai.com/v1", "models": "/models", "health": "/models", "need_key": True},
    "DEEPSEEK": {"label": "DeepSeek", "base": "https://api.deepseek.com/v1", "models": "/models", "health": "/models", "need_key": True},
    "MOONSHOT": {"label": "Kimi (Moonshot)", "base": "https://api.moonshot.cn/v1", "models": "/models", "health": "/models", "need_key": True},
    "SILICONFLOW": {"label": "硅基流动", "base": "https://api.siliconflow.cn/v1", "models": "/models", "health": "/models", "need_key": True},
    "ZHIPU": {"label": "智谱 GLM", "base": "https://open.bigmodel.cn/api/paas/v4", "models": "/models", "health": "/models", "need_key": True},
    "HUNYUAN": {"label": "腾讯混元", "base": "https://api.hunyuan.cloud.tencent.com/v1", "models": "/models", "health": "/models", "need_key": True},
}


def preset_of(provider_type: str | None) -> dict:
    key = (provider_type or "OPENAI").upper()
    return PRESETS.get(key, PRESETS["OPENAI"])


def _join(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + path


def _normalize_probe_base(provider_type: str | None, base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    if (provider_type or "").upper() == "JEV" and not base.endswith("/v1"):
        return f"{base}/v1"
    return base


@dataclass
class ProbeError(Exception):
    message: str


async def load_model_ids(provider_type: str | None, base_url: str, api_key: str | None) -> list[str]:
    if not (base_url or "").strip():
        raise ProbeError("请先填写 Base URL")
    spec = preset_of(provider_type)
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    url = _join(_normalize_probe_base(provider_type, base_url), spec["models"])
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise ProbeError(f"加载模型失败：{exc}") from exc
    if resp.status_code < 200 or resp.status_code >= 300:
        raise ProbeError(f"服务商响应异常 HTTP {resp.status_code}：{resp.text[:200]}")
    data = resp.json()
    ids: list[str] = []
    if spec["models"] == "/api/tags":
        for item in data.get("models") or []:
            name = item.get("name")
            if name:
                ids.append(str(name))
    else:
        for item in data.get("data") or []:
            mid = item.get("id")
            if mid:
                ids.append(str(mid))
    return ids


async def test_connection(provider_type: str | None, base_url: str, api_key: str | None) -> bool:
    spec = preset_of(provider_type)
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    url = _join(_normalize_probe_base(provider_type, base_url), spec["health"])
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url, headers=headers)
    return 200 <= resp.status_code < 300
