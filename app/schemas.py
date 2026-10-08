from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LogEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    severity: Literal["trace", "debug", "info", "warning", "error", "critical"]
    service: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1)
    environment: str | None = Field(default=None, min_length=1, max_length=120)
    attributes: dict[str, object] | None = None

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value

    @field_validator("service", "environment", "message")
    @classmethod
    def text_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("value must not be blank")
        return value

    @field_validator("message")
    @classmethod
    def message_must_fit_database_limit(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 262_144:
            raise ValueError("message exceeds 256 KB")
        return value