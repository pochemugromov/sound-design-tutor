from __future__ import annotations

import httpx

from app.config import Settings
from app.services.telemetry import Telemetry


class LLMNotConfigured(RuntimeError):
    pass


class OpenAICompatibleClient:
    def __init__(self, settings: Settings, telemetry: Telemetry | None = None) -> None:
        self.settings = settings
        self.telemetry = telemetry

    def _headers(self) -> dict[str, str]:
        if not self.settings.has_api_key:
            raise LLMNotConfigured(f"{self.settings.api_key_env_name} не задан.")
        return {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": self.settings.embedding_model, "input": texts}
        telemetry_input = {
            "texts_count": len(texts),
            "total_chars": sum(len(text) for text in texts),
            "avg_chars": round(sum(len(text) for text in texts) / len(texts)),
        }
        with self._telemetry_observation(
            "llm.embedding",
            as_type="embedding",
            model=self.settings.embedding_model,
            input=telemetry_input,
            metadata={"provider": self._provider_name()},
        ) as observation:
            try:
                async with httpx.AsyncClient(timeout=120) as client:
                    response = await client.post(
                        f"{self.settings.openai_base_url}/embeddings",
                        headers=self._headers(),
                        json=payload,
                    )
                    response.raise_for_status()
                data = response.json()["data"]
                ordered_data = sorted(data, key=lambda item: item["index"]) if all("index" in item for item in data) else data
                embeddings = [item["embedding"] for item in ordered_data]
                self._telemetry_update(
                    observation,
                    output={
                        "embeddings_count": len(embeddings),
                        "dimensions": len(embeddings[0]) if embeddings else 0,
                    },
                )
                return embeddings
            except Exception as exc:
                self._telemetry_update(observation, level="ERROR", status_message=str(exc)[:500])
                raise

    async def chat(
        self,
        messages: list[dict],
        max_tokens: int = 32768,
        continue_on_length: bool = True,
        model: str | None = None,
    ) -> str:
        active_model = (model or self.settings.chat_model).strip() or self.settings.chat_model
        with self._telemetry_observation(
            "llm.chat",
            as_type="generation",
            model=active_model,
            input={"messages": messages, "temperature": 0.2, "max_tokens": max_tokens},
            metadata={"provider": self._provider_name(), "endpoint": "chat/completions"},
        ) as observation:
            try:
                messages_for_request = list(messages)
                answer_parts = []
                finish_reasons = []
                usage = {}
                max_attempts = 4 if continue_on_length else 1
                async with httpx.AsyncClient(timeout=180) as client:
                    for attempt in range(max_attempts):
                        payload = {
                            "model": active_model,
                            "messages": messages_for_request,
                            "temperature": 0.2,
                            "max_tokens": max_tokens,
                        }
                        response = await client.post(
                            f"{self.settings.openai_base_url}/chat/completions",
                            headers=self._headers(),
                            json=payload,
                        )
                        response.raise_for_status()
                        data = response.json()
                        choice = data["choices"][0]
                        answer_part = self._message_content(choice).strip()
                        finish_reason = choice.get("finish_reason", "")
                        finish_reasons.append(finish_reason)
                        usage = data.get("usage") or usage
                        if answer_part:
                            answer_parts.append(answer_part)
                        if finish_reason != "length" or attempt == max_attempts - 1:
                            break
                        messages_for_request.extend(
                            [
                                {"role": "assistant", "content": answer_part},
                                {
                                    "role": "user",
                                    "content": (
                                        "Продолжай ответ строго с того места, где он был обрезан. "
                                        "Не повторяй уже написанное, не добавляй вступительных фраз, "
                                        "не пиши никаких meta-комментариев (Correction, Continuation и т.п.) — "
                                        "просто продолжай текст ответа."
                                    ),
                                },
                            ]
                        )
                answer = "\n\n".join(answer_parts).strip()
                self._telemetry_update(
                    observation,
                    output=answer,
                    usage_details=self._usage_details(usage),
                    metadata={
                        "finish_reasons": finish_reasons,
                        "continuation_attempts": max(0, len(finish_reasons) - 1),
                    },
                )
                return answer
            except Exception as exc:
                self._telemetry_update(observation, level="ERROR", status_message=str(exc)[:500])
                raise

    async def smoke_test(self) -> dict:
        answer = await self.chat(
            [
                {"role": "system", "content": "Ответь одним словом: OK"},
                {"role": "user", "content": "ping"},
            ],
            max_tokens=128,
            continue_on_length=False,
        )
        return {"ok": True, "answer": answer}

    async def rewrite_search_query(self, query: str) -> str:
        answer = await self.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Ты преобразуешь вопросы пользователя в поисковые запросы для RAG по базе знаний Ableton Live, "
                        "саунд-дизайна и музыкального образования. Не отвечай на вопрос. "
                        "Верни только одну строку поисковых терминов. "
                        "Сохрани русские ключевые слова и добавь английские термины Ableton/DAW, если они уместны. "
                        "Раскрывай транслитерацию, сокращения и разговорные формулировки: например, "
                        "ретюрн трек -> return track send return, сайдчейн -> sidechain compressor, "
                        "браузер -> browser library packs, дорожка -> track channel."
                    ),
                },
                {"role": "user", "content": query[:4000]},
            ],
            max_tokens=160,
            continue_on_length=False,
        )
        return " ".join(answer.replace("`", "").split())[:1200]

    def _provider_name(self) -> str:
        if "generativelanguage.googleapis.com" in self.settings.openai_base_url:
            return "google-gemini-openai-compatible"
        if "api.openai.com" in self.settings.openai_base_url:
            return "openai"
        return "openai-compatible"

    def _usage_details(self, usage: dict) -> dict[str, int]:
        details = {}
        if usage.get("prompt_tokens") is not None:
            details["input_tokens"] = int(usage["prompt_tokens"])
        if usage.get("completion_tokens") is not None:
            details["output_tokens"] = int(usage["completion_tokens"])
        if usage.get("total_tokens") is not None:
            details["total_tokens"] = int(usage["total_tokens"])
        return details

    def _message_content(self, choice: dict) -> str:
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            if parts:
                return "\n".join(parts)
        if isinstance(choice.get("text"), str):
            return choice["text"]
        raise RuntimeError(f"LLM response does not contain text content. Message keys: {list(message.keys())}")

    def _telemetry_observation(self, *args, **kwargs):
        if self.telemetry is None:
            from contextlib import nullcontext

            return nullcontext()
        return self.telemetry.observation(*args, **kwargs)

    def _telemetry_update(self, observation, **kwargs) -> None:
        if self.telemetry is not None:
            self.telemetry.update(observation, **kwargs)
