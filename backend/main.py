"""Valio Aimo Trusted Trade Gateway API."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import database
from guardrails import evaluate_order
from schemas import AuditLogEntry, GuardrailsConfig, OrderCreateRequest, OrderDecisionRequest, OrderResponse, QuoteRequest, QuoteResponse, QuotedProduct
from trust import sign_quote, verify_quote
from valio_client import ValioClient

app = FastAPI(title="Valio Aimo Trusted Trade Gateway", version="0.2.0", description="A secure interface between external purchasing agents and Valio Aimo services.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
database.init_db()


def now_iso() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


@app.post("/api/quote", response_model=QuoteResponse, tags=["Quotes"])
async def create_quote(request: QuoteRequest) -> QuoteResponse:
    """Create a signed quote using local catalog search and Valio's live APIs."""
    try:
        items = await ValioClient().build_quote(request.items, request.buyer_id)
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=f"Unable to create a live quote: {exc}") from exc
    total = round(sum(item.total_price_eur for item in items), 2)
    quote_id = f"Q-{uuid4().hex[:10].upper()}"
    valid_until = datetime.now(timezone.utc) + timedelta(minutes=15)
    token = sign_quote({"quote_id": quote_id, "buyer_id": request.buyer_id, "items": [item.model_dump() for item in items], "total_eur": total, "valid_until": valid_until.isoformat()})
    return QuoteResponse(quote_id=quote_id, valid_until=valid_until.isoformat(), items=items, total_eur=total, signed_quote_token=token)


@app.post("/api/orders", response_model=OrderResponse, tags=["Orders"])
async def create_order(request: OrderCreateRequest) -> OrderResponse:
    """Verify a signed quote, evaluate guardrails, persist the order, and approve or hold it."""
    claims = verify_quote(request.signed_quote_token)
    if claims.get("buyer_id") != request.buyer_id:
        raise HTTPException(status_code=400, detail="The quote buyer does not match the order buyer")
    items = [QuotedProduct(**item) for item in claims["items"]]
    total = float(claims["total_eur"])
    autonomous, blocked_reasons = evaluate_order(items, total, database.get_guardrails())
    audit = [AuditLogEntry(timestamp=now_iso(), actor="gateway", action="QUOTE_VERIFIED", reasoning="The quote signature and expiration were verified successfully."), AuditLogEntry(timestamp=now_iso(), actor="gateway", action="GUARDRAILS_EVALUATED", reasoning="The order was evaluated against the current purchasing guardrails.")]
    status = "CONFIRMED" if autonomous else "PENDING_APPROVAL"
    audit.append(AuditLogEntry(timestamp=now_iso(), actor="gateway", action="AUTOMATIC_APPROVAL" if autonomous else "APPROVAL_REQUIRED", reasoning="Order approved automatically because all guardrails passed." if autonomous else "Order placed on hold because: " + " ".join(blocked_reasons)))
    order = OrderResponse(order_id=f"O-{uuid4().hex[:10].upper()}", status=status, total_eur=total, blocked_reasons=blocked_reasons, items=items, audit_trail=audit)
    database.save_order(order, request.signed_quote_token)
    return order


@app.get("/api/orders", response_model=list[OrderResponse], tags=["Orders"])
def list_all_orders() -> list[OrderResponse]:
    """Return all persisted orders and their audit trails."""
    return database.list_orders()


@app.post("/api/orders/{order_id}/decision", response_model=OrderResponse, tags=["Orders"])
def decide_order(order_id: str, request: OrderDecisionRequest) -> OrderResponse:
    """Record a human approval decision for a pending order."""
    order = database.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status != "PENDING_APPROVAL":
        raise HTTPException(status_code=409, detail="Only pending orders can receive a human decision")
    order.status = "CONFIRMED" if request.decision == "APPROVE" else "REJECTED"
    order.blocked_reasons = [] if request.decision == "APPROVE" else [request.comment or "The approver rejected the order without a comment."]
    order.audit_trail.append(AuditLogEntry(timestamp=now_iso(), actor=request.approver_name, action="HUMAN_APPROVED" if request.decision == "APPROVE" else "HUMAN_REJECTED", reasoning=request.comment or "No additional comment was provided."))
    database.save_order(order, "")
    return order


@app.get("/api/guardrails", response_model=GuardrailsConfig, tags=["Guardrails"])
def get_guardrails() -> GuardrailsConfig:
    """Return the persisted purchasing guardrails."""
    return database.get_guardrails()


@app.put("/api/guardrails", response_model=GuardrailsConfig, tags=["Guardrails"])
def update_guardrails(config: GuardrailsConfig) -> GuardrailsConfig:
    """Persist updated purchasing guardrails for future order evaluations."""
    return database.save_guardrails(config)
