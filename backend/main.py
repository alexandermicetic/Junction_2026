from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from schemas import (
    AuditLogEntry,
    GuardrailsConfig,
    OrderCreateRequest,
    OrderDecisionRequest,
    OrderResponse,
    QuoteRequest,
    QuoteResponse,
    QuotedProduct,
)

app = FastAPI(
    title="Valio Aimo Trusted Trade Gateway",
    description="Synthetic B2B foodservice trade interface for the Junction 2026 prototype.",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

guardrails = GuardrailsConfig(
    max_autonomous_spend_eur=500.0,
    forbidden_allergens=["lactose"],
    allow_substitutions=True,
)
orders: dict[str, OrderResponse] = {}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sample_items() -> list[QuotedProduct]:
    return [
        QuotedProduct(
            sku="VALIO-MILK-1L",
            name="Valio Eila® lactose-free milk drink",
            package_size="1 L",
            quantity=500,
            unit_price_eur=1.15,
            total_price_eur=575.0,
            in_stock=True,
            allergens=["milk"],
            sustainability_labels=["Finnish milk", "carbon-neutral production target"],
            is_substitution=False,
            substitution_reason=None,
        ),
        QuotedProduct(
            sku="VALIO-MILK-10L-TAP",
            name="Valio Eila® lactose-free milk drink bag-in-box",
            package_size="10 L",
            quantity=50,
            unit_price_eur=11.50,
            total_price_eur=575.0,
            in_stock=True,
            allergens=["milk"],
            sustainability_labels=["Finnish milk", "recyclable transport packaging"],
            is_substitution=False,
            substitution_reason=None,
        ),
    ]


def initial_audit(reasoning: str) -> list[AuditLogEntry]:
    return [AuditLogEntry(timestamp=now_iso(), actor="external-agent", action="ORDER_REQUESTED", reasoning=reasoning)]


@app.post("/api/quote", response_model=QuoteResponse, tags=["Quotes"])
def create_quote(request: QuoteRequest) -> QuoteResponse:
    """Create a synthetic customer quote for the requested foodservice products."""
    items = sample_items()
    return QuoteResponse(
        quote_id=f"Q-{uuid4().hex[:10].upper()}",
        valid_until=(datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat(),
        items=items,
        total_eur=1150.0,
        signed_quote_token="eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.dummy-quote-signature",
    )


@app.post("/api/orders", response_model=OrderResponse, tags=["Orders"])
def create_order(request: OrderCreateRequest) -> OrderResponse:
    """Create an order from a signed quote and request approval when guardrails require it."""
    items = sample_items()
    order_id = f"O-{uuid4().hex[:10].upper()}"
    total = sum(item.total_price_eur for item in items)
    reasons = [f"Total {total:.2f} EUR exceeds autonomous limit {guardrails.max_autonomous_spend_eur:.2f} EUR"]
    order = OrderResponse(
        order_id=order_id,
        status="PENDING_APPROVAL",
        total_eur=total,
        blocked_reasons=reasons,
        items=items,
        audit_trail=initial_audit("Quote token accepted; human approval required because spend exceeds guardrail."),
    )
    orders[order_id] = order
    return order


@app.get("/api/orders", response_model=list[OrderResponse], tags=["Orders"])
def list_orders() -> list[OrderResponse]:
    """List the synthetic order history, including confirmed and approval-pending examples."""
    if not orders:
        items = sample_items()
        orders["O-DEMO-CONFIRMED"] = OrderResponse(
            order_id="O-DEMO-CONFIRMED", status="CONFIRMED", total_eur=230.0, blocked_reasons=[], items=items[:1],
            audit_trail=initial_audit("Within autonomous spend limit.") + [AuditLogEntry(timestamp=now_iso(), actor="system", action="CONFIRMED", reasoning="Guardrails passed.")],
        )
        orders["O-DEMO-PENDING"] = OrderResponse(
            order_id="O-DEMO-PENDING", status="PENDING_APPROVAL", total_eur=1150.0,
            blocked_reasons=["Spend exceeds autonomous limit."], items=items,
            audit_trail=initial_audit("Human approval required for high-value order."),
        )
    return list(orders.values())


@app.post("/api/orders/{order_id}/decision", response_model=OrderResponse, tags=["Orders"])
def decide_order(order_id: str, request: OrderDecisionRequest) -> OrderResponse:
    """Approve or reject a pending order and append the human decision to its audit trail."""
    order = orders.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status != "PENDING_APPROVAL":
        raise HTTPException(status_code=409, detail="Only pending orders can receive a decision")
    order.status = "CONFIRMED" if request.decision == "APPROVE" else "REJECTED"
    order.blocked_reasons = [] if request.decision == "APPROVE" else [request.comment or "Rejected by approver"]
    order.audit_trail.append(AuditLogEntry(timestamp=now_iso(), actor=request.approver_name, action=request.decision, reasoning=request.comment or "No comment provided."))
    return order


@app.get("/api/guardrails", response_model=GuardrailsConfig, tags=["Guardrails"])
def get_guardrails() -> GuardrailsConfig:
    """Return the current in-memory purchasing guardrails."""
    return guardrails


@app.put("/api/guardrails", response_model=GuardrailsConfig, tags=["Guardrails"])
def update_guardrails(config: GuardrailsConfig) -> GuardrailsConfig:
    """Replace the in-memory purchasing guardrails for subsequent order decisions."""
    global guardrails
    guardrails = config
    return guardrails
