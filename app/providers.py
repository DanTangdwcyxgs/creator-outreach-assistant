from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any


DEFAULT_SETTINGS: dict[str, Any] = {
    "business_name": "New Horizons",
    "provider": "local",
    "base_url": "http://127.0.0.1:1234/v1",
    "model": "gemma-4-12b",
    "api_key": "",
    "remote_redaction": True,
    "fallback_local": True,
}

LOCAL_SETTINGS: dict[str, Any] = {
    **DEFAULT_SETTINGS,
    "provider": "local",
    "base_url": "http://127.0.0.1:1234/v1",
    "model": "gemma-4-12b",
    "api_key": "",
}


class ProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


GROQ_FALLBACK_MODELS = ("openai/gpt-oss-120b",)


def merged_settings(saved: dict[str, Any]) -> dict[str, Any]:
    result = DEFAULT_SETTINGS.copy()
    result.update({key: value for key, value in saved.items() if key in result})
    return result


def public_settings(saved: dict[str, Any]) -> dict[str, Any]:
    result = merged_settings(saved)
    result["has_api_key"] = bool(result.get("api_key"))
    result["api_key"] = ""
    return result


def redact_sensitive(text: str) -> str:
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[邮箱已隐藏]", text)
    text = re.sub(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)", "[电话已隐藏]", text)
    text = re.sub(
        r"(?im)^\s*\d{1,6}\s+[A-Za-z0-9 .'-]{3,60}\s+"
        r"(?:St|Street|Rd|Road|Ave|Avenue|Dr|Drive|Ln|Lane|Blvd|Way|Ct|Court)\b[^\n]*$",
        "[详细地址已隐藏]",
        text,
    )
    return text


def _request(url: str, payload: dict[str, Any] | None, api_key: str, timeout: int) -> Any:
    headers = {
        "Accept": "application/json",
        "User-Agent": "CreatorHub/1.0 (OpenAI-compatible client)",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise ProviderError(f"模型接口返回 {exc.code}: {detail}", exc.code) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ProviderError(f"无法连接模型接口：{exc}") from exc


def list_models(settings: dict[str, Any]) -> list[str]:
    config = merged_settings(settings)
    payload = _request(
        f"{str(config['base_url']).rstrip('/')}/models",
        None,
        str(config.get("api_key", "")),
        8,
    )
    return [str(item.get("id", "")) for item in payload.get("data", []) if item.get("id")]


def chat_completion(
    settings: dict[str, Any],
    messages: list[dict[str, str]],
    temperature: float = 0.35,
    max_tokens: int = 700,
) -> tuple[str, str]:
    config = merged_settings(settings)
    remote_errors: list[ProviderError] = []
    try:
        return _chat_completion(config, messages, temperature, max_tokens)
    except ProviderError as remote_error:
        remote_errors.append(remote_error)
        if config.get("provider") == "local" or not config.get("fallback_local", True):
            raise
        if config.get("provider") == "groq" and _can_try_groq_fallback(remote_error):
            primary_model = str(config.get("model", "")).strip()
            for fallback_model in GROQ_FALLBACK_MODELS:
                if fallback_model == primary_model:
                    continue
                fallback_config = {**config, "model": fallback_model}
                try:
                    content, model = _chat_completion(
                        fallback_config, messages, temperature, max_tokens
                    )
                    return content, f"{model}（Groq 云端备用）"
                except ProviderError as fallback_error:
                    remote_errors.append(fallback_error)
        try:
            content, model = _chat_completion(LOCAL_SETTINGS, messages, temperature, max_tokens)
            return content, f"{model}（云端不可用，已转本机）"
        except ProviderError as local_error:
            cloud_details = "；".join(str(error) for error in remote_errors)
            raise ProviderError(
                f"网络模型不可用：{cloud_details}；本机备用模型也不可用：{local_error}"
            ) from local_error


def _can_try_groq_fallback(error: ProviderError) -> bool:
    if error.status_code in {404, 408, 409, 429, 500, 502, 503, 504}:
        return True
    detail = str(error).casefold()
    return any(
        marker in detail
        for marker in ("rate limit", "quota", "model_not_found", "decommissioned", "unavailable")
    )


def _chat_completion(
    config: dict[str, Any],
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
) -> tuple[str, str]:
    model = str(config.get("model", "")).strip()
    if not model:
        models = list_models(config)
        if not models:
            raise ProviderError("模型接口没有可用模型")
        model = models[0]
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max(100, min(max_tokens, 1200)),
        "stream": False,
    }
    if config.get("provider") == "groq" and model.startswith("qwen/"):
        payload["reasoning_effort"] = "none"
    elif config.get("provider") == "groq" and model.startswith("openai/gpt-oss"):
        payload["reasoning_effort"] = "low"
    result = _request(
        f"{str(config['base_url']).rstrip('/')}/chat/completions",
        payload,
        str(config.get("api_key", "")) or ("lm-studio" if config.get("provider") == "local" else ""),
        180,
    )
    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError("模型返回格式无法识别") from exc
    return str(content), model


def parse_json_response(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned, re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else {"content": value}
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                value = json.loads(cleaned[start : end + 1])
                return value if isinstance(value, dict) else {"content": value}
            except json.JSONDecodeError:
                pass
    return {"content": cleaned}
