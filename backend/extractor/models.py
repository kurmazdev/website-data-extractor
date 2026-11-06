import re
from typing import List, Literal, Optional
from urllib.parse import urlsplit

import soupsieve
from pydantic import BaseModel, Field, field_validator, model_validator

DEMO_URL = "https://demo.website-extractor.test/catalog"


def validate_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        if (
            len(value) > 2048
            or parts.scheme not in ("http", "https")
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.port not in (None, 80, 443)
            or any(ord(c) < 33 for c in value)
            or "\\" in value
        ):
            raise ValueError()
        parts.hostname.encode("idna")
    except (ValueError, UnicodeError):
        raise ValueError(
            "Use a public HTTP or HTTPS URL without credentials, on port 80 or 443."
        )
    return value


def selector(value: str) -> str:
    if value:
        try:
            soupsieve.compile(value)
        except Exception:
            raise ValueError("Invalid CSS selector.")
    return value


class ExtractionField(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    selector: str = Field(max_length=300)
    attribute: str = Field(default="", max_length=50)

    @field_validator("name")
    @classmethod
    def valid_name(cls, v):
        v = v.strip()
        if not v or v == "_source":
            raise ValueError("Choose a non-empty field name other than _source.")
        return v

    @field_validator("selector")
    @classmethod
    def valid_selector(cls, v):
        return selector(v)

    @field_validator("attribute")
    @classmethod
    def valid_attribute(cls, v):
        if v and not re.fullmatch(r"[a-zA-Z_][\w:-]*", v):
            raise ValueError("Use an HTML attribute such as href or src.")
        return v


class Config(BaseModel):
    url: str
    row_selector: str = Field(min_length=1, max_length=300)
    fields: List[ExtractionField] = Field(min_length=1, max_length=20)
    next_selector: str = Field(default="", max_length=300)
    max_pages: int = Field(default=3, ge=1, le=50)
    delay: float = Field(default=1, ge=0.5, le=30)
    timeout: float = Field(default=15, ge=2, le=30)
    render_js: bool = False
    deduplicate: bool = True

    @field_validator("url")
    @classmethod
    def valid_url(cls, v):
        return validate_url(v.strip())

    @field_validator("row_selector", "next_selector")
    @classmethod
    def valid_selector(cls, v):
        return selector(v)

    @model_validator(mode="after")
    def unique_names(self):
        if len({f.name.casefold() for f in self.fields}) != len(self.fields):
            raise ValueError("Field names must be unique.")
        return self


class Issue(BaseModel):
    page: str
    message: str
    level: Literal["warning", "error"] = "error"


class Result(BaseModel):
    records: list = Field(default_factory=list)
    issues: List[Issue] = Field(default_factory=list)
    pages: int = 0
    attempted: int = 0
    duplicates: int = 0
    missing: int = 0
    status: str = "running"
    current_url: Optional[str] = None
    stop_reason: str = ""
