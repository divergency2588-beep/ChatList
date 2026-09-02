"""Отправка промта в нейросети (OpenAI-совместимый Chat Completions)."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from db import OPENROUTER_URL
from models import Model

OPENROUTER_NAME_MAP = {
    "gpt-4o-mini": "openai/gpt-4o-mini",
    "deepseek-chat": "deepseek/deepseek-chat",
    "llama-3.3-70b-versatile": "meta-llama/llama-3.3-70b-instruct",
}


class NetworkError(Exception):
    pass


def _resolve_endpoint(model: Model) -> tuple[str, str, str]:
    """Возвращает (ключ, url, имя модели для API)."""
    api_key = os.getenv(model.api_id, "").strip()
    if api_key:
        return api_key, model.api_url, model.name

    fallback = os.getenv("OPENROUTER_API_KEY", "").strip()
    if fallback:
        mapped = OPENROUTER_NAME_MAP.get(model.name, model.name)
        return fallback, OPENROUTER_URL, mapped

    raise NetworkError(
        f"Не задана переменная окружения {model.api_id}. "
        "Добавьте ключ в .env / .env.local или укажите OPENROUTER_API_KEY."
    )


def _extract_text(payload: dict) -> str:
    try:
        return str(payload["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise NetworkError(f"Неожиданный формат ответа API: {payload}") from exc


def send_prompt(
    model: Model,
    prompt: str,
    timeout: float = 60.0,
    temperature: float = 0.7,
) -> str:
    api_key, api_url, model_id = _resolve_endpoint(model)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if "openrouter.ai" in api_url.lower():
        headers["HTTP-Referer"] = "https://github.com/chatlist"
        headers["X-Title"] = "ChatList"
    body = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }

    try:
        response = requests.post(
            api_url,
            json=body,
            headers=headers,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise NetworkError(f"Сеть: {exc}") from exc

    if response.status_code >= 400:
        detail = response.text.strip()
        raise NetworkError(f"HTTP {response.status_code}: {detail[:500]}")

    try:
        data = response.json()
    except ValueError as exc:
        raise NetworkError("Ответ API не является JSON.") from exc

    return _extract_text(data)


def send_to_models(
    models: list[Model],
    prompt: str,
    timeout: float = 60.0,
    temperature: float = 0.7,
) -> list[tuple[str, str, bool]]:
    """Параллельно опрашивает модели.

    Возвращает список (имя модели, текст или ошибка, успех).
    """
    results: list[tuple[str, str, bool]] = []

    def _job(item: Model) -> tuple[str, str, bool]:
        try:
            text = send_prompt(item, prompt, timeout=timeout, temperature=temperature)
            return item.name, text, True
        except Exception as exc:  # noqa: BLE001 — ошибка уходит в строку результата
            return item.name, str(exc), False

    workers = min(8, max(1, len(models)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_job, item) for item in models]
        for future in as_completed(futures):
            results.append(future.result())
    return results
