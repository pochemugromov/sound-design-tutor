from __future__ import annotations

from contextlib import contextmanager
import re
from typing import Any, Iterator

from app.config import Settings


SECRET_PATTERNS = (
    (re.compile(r"AIza[0-9A-Za-z_-]{20,}"), "[REDACTED_GOOGLE_API_KEY]"),
    (re.compile(r"sk-lf-[0-9a-fA-F-]{20,}"), "[REDACTED_LANGFUSE_SECRET_KEY]"),
    (re.compile(r"pk-lf-[0-9a-fA-F-]{20,}"), "[REDACTED_LANGFUSE_PUBLIC_KEY]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE), "Bearer [REDACTED]"),
)

SENSITIVE_KEYS = {"api_key", "authorization", "key", "password", "secret", "token"}


class NoopObservation:
    trace_id: str | None = None
    id: str | None = None

    def update(self, *args: Any, **kwargs: Any) -> None:
        return None

    def end(self) -> None:
        return None


class Telemetry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client: Any | None = None
        self.propagate_attributes: Any | None = None
        self.init_error: str | None = None

        if not settings.langfuse_enabled:
            return

        try:
            from langfuse import get_client, propagate_attributes

            self.client = get_client()
            self.propagate_attributes = propagate_attributes
        except Exception as exc:
            self.init_error = str(exc)
            self.client = None
            self.propagate_attributes = None

    @property
    def enabled(self) -> bool:
        return self.client is not None and self.settings.langfuse_enabled

    @contextmanager
    def observation(
        self,
        name: str,
        *,
        as_type: str = "span",
        input: Any | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        tags: list[str] | None = None,
        trace_name: str | None = None,
    ) -> Iterator[Any]:
        if not self.enabled:
            yield NoopObservation()
            return

        kwargs: dict[str, Any] = {"as_type": as_type, "name": name}
        if model:
            kwargs["model"] = model
        if input is not None and self.settings.langfuse_capture_io:
            kwargs["input"] = self.sanitize(input)
        if metadata:
            kwargs["metadata"] = self.sanitize_metadata(metadata)

        try:
            observation_context = self.client.start_as_current_observation(**kwargs)
        except Exception as exc:
            self.init_error = str(exc)
            yield NoopObservation()
            return

        with observation_context as observation:
            attributes_context = self._attributes_context(
                user_id=user_id,
                session_id=session_id,
                tags=tags,
                trace_name=trace_name or name,
                metadata=metadata,
            )
            with attributes_context:
                yield observation

    def update(
        self,
        observation: Any,
        *,
        input: Any | None = None,
        output: Any | None = None,
        metadata: dict[str, Any] | None = None,
        usage_details: dict[str, int] | None = None,
        level: str | None = None,
        status_message: str | None = None,
    ) -> None:
        if not self.enabled or isinstance(observation, NoopObservation):
            return

        kwargs: dict[str, Any] = {}
        if input is not None and self.settings.langfuse_capture_io:
            kwargs["input"] = self.sanitize(input)
        if output is not None and self.settings.langfuse_capture_io:
            kwargs["output"] = self.sanitize(output)
        if metadata:
            kwargs["metadata"] = self.sanitize_metadata(metadata)
        if usage_details:
            kwargs["usage_details"] = usage_details
        if level:
            kwargs["level"] = level
        if status_message:
            kwargs["status_message"] = self.sanitize(status_message)

        try:
            observation.update(**kwargs)
        except Exception as exc:
            self.init_error = str(exc)

    def flush(self) -> None:
        if not self.enabled:
            return
        try:
            self.client.flush()
        except Exception as exc:
            self.init_error = str(exc)

    def sanitize(self, value: Any, depth: int = 0) -> Any:
        if depth > 8:
            return "[MAX_DEPTH]"
        if isinstance(value, str):
            sanitized = value
            for pattern, replacement in SECRET_PATTERNS:
                sanitized = pattern.sub(replacement, sanitized)
            max_chars = max(1000, self.settings.langfuse_max_field_chars)
            if len(sanitized) > max_chars:
                return sanitized[:max_chars] + "...[TRUNCATED]"
            return sanitized
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                key_text = str(key)
                if any(marker in key_text.lower() for marker in SENSITIVE_KEYS):
                    result[key_text] = "[REDACTED]"
                else:
                    result[key_text] = self.sanitize(item, depth + 1)
            return result
        if isinstance(value, (list, tuple)):
            return [self.sanitize(item, depth + 1) for item in value]
        return value

    def sanitize_metadata(self, metadata: dict[str, Any]) -> dict[str, str]:
        sanitized = self.sanitize(metadata)
        return {str(key): str(value)[:200] for key, value in sanitized.items()}

    @contextmanager
    def _attributes_context(
        self,
        *,
        user_id: str | None,
        session_id: str | None,
        tags: list[str] | None,
        trace_name: str | None,
        metadata: dict[str, Any] | None,
    ) -> Iterator[None]:
        if not self.propagate_attributes:
            yield
            return

        kwargs: dict[str, Any] = {}
        if user_id:
            kwargs["user_id"] = user_id
        if session_id:
            kwargs["session_id"] = session_id
        if tags:
            kwargs["tags"] = tags
        if trace_name:
            kwargs["trace_name"] = trace_name
        if metadata:
            kwargs["metadata"] = self.sanitize_metadata(metadata)

        if not kwargs:
            yield
            return

        with self.propagate_attributes(**kwargs):
            yield
