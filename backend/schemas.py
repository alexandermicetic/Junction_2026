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


class InventoryRule(BaseModel):
    sku: str
    name: str
    product_query: str
    unit: str = "PCS"
    current_stock: int = Field(ge=0)
    min_threshold: int = Field(ge=0)
    reorder_quantity: int = Field(gt=0)
    auto_reorder_enabled: bool = True
    buyer_id: str = "BUYER-TEST-001"


class InventoryRulePatch(BaseModel):
    reorder_quantity: int | None = Field(default=None, gt=0)
    min_threshold: int | None = Field(default=None, ge=0)
    current_stock: int | None = Field(default=None, ge=0)
    auto_reorder_enabled: bool | None = None


class InventoryReorderResult(BaseModel):
    sku: str
    status: str
    message: str
    order: OrderResponse | None = None


class InventoryConsumeResponse(BaseModel):
    item: InventoryRule
    reorder_result: InventoryReorderResult | None = None


class InventoryReorderCheckResponse(BaseModel):
    results: list[InventoryReorderResult]


class ClaudePurchaseRequest(BaseModel):
    buyer_id: str = Field(min_length=1)
    request_text: str = Field(min_length=3, max_length=2000)
    max_delivery_date: str | None = None


class ClaudePurchaseResponse(BaseModel):
    status: Literal["needs_clarification", "no_available_product", "duplicate_skipped", "already_processing", "CONFIRMED", "PENDING_APPROVAL"]
    message: str
    selected_product: QuotedProduct | None = None
    order: OrderResponse | None = None
