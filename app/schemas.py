"""Pydantic 请求/响应模型（同时生成 OpenAPI 文档）。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    max_items: int | None = Field(
        default=None, ge=1, le=100, description="本次测验最多作答题数；默认取服务端配置"
    )
    exposure_cap: int | None = Field(
        default=None, ge=1, le=10_000, description="单题曝光上限；默认取服务端配置"
    )


class OptionOut(BaseModel):
    index: int
    text: str


class ItemBrief(BaseModel):
    item_id: str
    stem: str
    options: list[OptionOut]


class SessionCreated(BaseModel):
    session_id: str
    status: Literal["in_progress", "finished"]
    theta: float
    answered_count: int
    max_items: int
    exposure_cap: int
    current_item: ItemBrief | None
    finish_reason: str | None
    created_at: str


class SubmitResponseRequest(BaseModel):
    response_id: str = Field(min_length=1, description="客户端生成的幂等键；重复提交返回首次结果")
    selected_index: int = Field(ge=0, le=3, description="所选选项下标（0 起）")


class SubmitResult(BaseModel):
    replayed: bool
    response_id: str
    item_id: str
    selected_index: int
    answer_index: int
    correct: bool
    score: int
    probability: float
    theta_before: float
    theta_after: float
    answered_count: int
    next_item: ItemBrief | None
    status: Literal["in_progress", "finished"]
    finish_reason: str | None


class Progress(BaseModel):
    session_id: str
    status: Literal["in_progress", "finished"]
    theta: float
    answered_count: int
    max_items: int
    remaining: int
    exposure_cap: int
    current_item: ItemBrief | None
    finish_reason: str | None
    created_at: str
    updated_at: str


class ResponseRecord(BaseModel):
    response_id: str
    item_id: str
    selected_index: int
    answer_index: int
    score: int
    correct: bool
    probability: float
    theta_before: float
    theta_after: float
    created_at: str


class ResponseHistory(BaseModel):
    session_id: str
    count: int
    responses: list[ResponseRecord]


class ItemBankRow(BaseModel):
    item_id: str
    a: float
    b: float
    exposure: int
    exposure_remaining: int
    administered: bool


class ItemBank(BaseModel):
    exposure_cap: int
    count: int
    items: list[ItemBankRow]


class Health(BaseModel):
    status: str
    items: int
    sessions: int
