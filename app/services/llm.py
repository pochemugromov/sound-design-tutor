from __future__ import annotations

import httpx

from app.config import Settings


class LLMNotConfigured(RuntimeError):
    pass


class OpenAICompatibleClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _headers(self) -> dict[str, str]:
        if not self.settings.has_api_key:
            raise LLMNotConfigured("OPENAI_API_KEY не задан.")
        return {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": self.settings.embedding_model, "input": texts}
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.settings.openai_base_url}/embeddings",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
        data = response.json()["data"]
        return [item["embedding"] for item in sorted(data, key=lambda item: item["index"])]

    async def chat(self, messages: list[dict], max_tokens: int = 900) -> str:
        payload = {
            "model": self.settings.chat_model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": max_tokens,
        }
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                f"{self.settings.openai_base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()

    async def smoke_test(self) -> dict:
        answer = await self.chat(
            [
                {"role": "system", "content": "Ответь одним словом: OK"},
                {"role": "user", "content": "ping"},
            ],
            max_tokens=5,
        )
        return {"ok": True, "answer": answer}
