from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def normalize_category(value: str | None) -> str:
    value = (value or "").strip().lower().replace(" ", "_")
    value = re.sub(r"[^a-z0-9_-]", "", value)[:40]
    return value or "umum"


def validate_date(value: str | None) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    if not _DATE_RE.match(value):
        raise ValueError("Tanggal harus berformat YYYY-MM-DD.")
    return value


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8, max_length=72)


class UrlDocIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    title: str | None = Field(default=None, max_length=300)
    category: str = "akademik"
    effective_date: str | None = None

    @field_validator("effective_date")
    @classmethod
    def _date(cls, v):
        return validate_date(v)


class ManualDocIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    markdown: str = Field(min_length=1)
    category: str = "akademik"
    effective_date: str | None = None
    source_url: str | None = Field(default=None, max_length=2000)

    @field_validator("effective_date")
    @classmethod
    def _date(cls, v):
        return validate_date(v)


class DocUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    category: str | None = None
    effective_date: str | None = None
    source_url: str | None = Field(default=None, max_length=2000)
    markdown: str | None = None
    downloadable: bool | None = None

    @field_validator("effective_date")
    @classmethod
    def _date(cls, v):
        return validate_date(v) if v is not None else None


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    category: str | None = None
    user_ref: str | None = Field(default=None, max_length=64)
    channel: str = Field(default="api", max_length=20)


class FeedbackIn(BaseModel):
    query_id: int
    rating: int
    comment: str | None = Field(default=None, max_length=1000)

    @field_validator("rating")
    @classmethod
    def _rating(cls, v):
        if v not in (1, -1):
            raise ValueError("rating harus 1 atau -1.")
        return v
