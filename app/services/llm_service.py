import time

import httpx

from app.logging_config import get_logger


logger = get_logger("deepseek")


class DeepSeekService:
    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 4096,
        *,
        thinking: bool = True,
        reasoning_effort: str = "high",
        json_mode: bool = False,
    ) -> str:
        if not self.api_key:
            raise RuntimeError("DeepSeek API Key 未配置")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "thinking": {"type": "enabled" if thinking else "disabled"},
        }
        if thinking:
            payload["reasoning_effort"] = reasoning_effort
        else:
            payload["temperature"] = temperature
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        started = time.perf_counter()
        input_chars = sum(len(str(message.get("content", ""))) for message in messages)
        logger.info(
            "请求开始 | model=%s thinking=%s effort=%s max_tokens=%s json=%s input_chars=%s",
            self.model, thinking, reasoning_effort if thinking else "-", max_tokens, json_mode, input_chars,
        )
        try:
            timeout = httpx.Timeout(connect=20, read=300, write=30, pool=30)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()
                content = result["choices"][0]["message"]["content"].strip()
                usage = result.get("usage", {})
                logger.info(
                    "请求完成 | elapsed=%.1fs output_chars=%s prompt_tokens=%s completion_tokens=%s",
                    time.perf_counter() - started,
                    len(content),
                    usage.get("prompt_tokens", "?"),
                    usage.get("completion_tokens", "?"),
                )
                if not content:
                    raise RuntimeError("DeepSeek 返回了空内容，请重试或降低推理强度")
                return content
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:300]
            logger.error(
                "请求失败 | elapsed=%.1fs status=%s detail=%s",
                time.perf_counter() - started, exc.response.status_code, detail,
            )
            raise RuntimeError(f"DeepSeek 请求失败（HTTP {exc.response.status_code}）：{detail}") from exc
        except httpx.HTTPError as exc:
            logger.error("连接失败 | elapsed=%.1fs error=%s", time.perf_counter() - started, exc)
            raise RuntimeError(f"无法连接 DeepSeek：{exc}") from exc
