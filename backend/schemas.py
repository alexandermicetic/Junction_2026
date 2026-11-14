from typing import Literal

from pydantic import BaseModel, Field


class QuoteItemRequest(BaseModel):
    product_query: str
    quantity: float = Field(gt=0)
    unit: str
    max_delivery_date: str


class QuoteRequest(BaseModel):
    buyer_id: str
    items: list[QuoteItemRequest] = Field(min_length=1)


class QuotedProduct(BaseModel):
    sku: str
    name: str
    package_size: str
    quantity: int
    unit_price_eur: float
    total_price_eur: float
    in_stock: bool
    allergens: list[str]
    sustainability_labels: list[str]
    is_substitution: bool
    substitution_reason: str | None


class QuoteResponse(BaseModel):
    quote_id: str
    valid_until: str
    items: list[QuotedProduct]
    total_eur: float
    signed_quote_token: str


class OrderCreateRequest(BaseModel):
    buyer_id: str
    signed_quote_token: str


class AuditLogEntry(BaseModel):
    timestamp: str
    actor: str
    action: str
    reasoning: str


class OrderResponse(BaseModel):
    order_id: str
    status: Literal["CONFIRMED", "PENDING_APPROVAL", "REJECTED"]
    total_eur: float
    blocked_reasons: list[str]
    items: list[QuotedProduct]
    audit_trail: list[AuditLogEntry]


class OrderDecisionRequest(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    approver_name: str
    comment: str | None = None


class GuardrailsConfig(BaseModel):
    max_autonomous_spend_eur: float = Field(gt=0)
    forbidden_allergens: list[str]
    allow_substitutions: bool
