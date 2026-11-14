"""Valio Aimo Trusted Trade Gateway API."""

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import database
from guardrails import evaluate_order
from schemas import AuditLogEntry, GuardrailsConfig, InventoryConsumeResponse, InventoryReorderCheckResponse, InventoryReorderResult, InventoryRule, InventoryRulePatch, OrderCreateRequest, OrderDecisionRequest, OrderResponse, QuoteItemRequest, QuoteRequest, QuoteResponse, QuotedProduct
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


@app.post("/api/demo/reset", tags=["Demo"])
def reset_demo() -> dict[str, str]:
    """Clear demo state and restore the default purchasing guardrails."""
    database.reset_demo()
    return {"status": "reset_complete"}


async def _try_auto_reorder(rule: InventoryRule, stock_before: int | None = None) -> InventoryReorderResult:
    """Request and submit a signed, guardrail-checked reorder when eligible."""
    if not rule.auto_reorder_enabled:
        return InventoryReorderResult(sku=rule.sku, status="disabled", message="Automatic reordering is disabled for this item.")
    if rule.current_stock > rule.min_threshold:
        return InventoryReorderResult(sku=rule.sku, status="not_needed", message="Current stock is above the reorder threshold.")
    if not database.acquire_reorder_lock(rule.sku):
        return InventoryReorderResult(sku=rule.sku, status="already_processing", message="A reorder check for this SKU is already in progress.")

    try:
        # Refresh after acquiring the lock so concurrent stock/settings changes are respected.
        current_rule = database.get_inventory_rule(rule.sku)
        if current_rule is None:
            return InventoryReorderResult(sku=rule.sku, status="not_found", message="Inventory rule was removed before reorder processing.")
        if not current_rule.auto_reorder_enabled:
            return InventoryReorderResult(sku=rule.sku, status="disabled", message="Automatic reordering is disabled for this item.")
        if current_rule.current_stock > current_rule.min_threshold:
            return InventoryReorderResult(sku=rule.sku, status="not_needed", message="Current stock is above the reorder threshold.")

        existing_order_id = database.find_open_order_for_sku(current_rule.sku)
        if existing_order_id:
            return InventoryReorderResult(sku=rule.sku, status="duplicate_skipped", message=f"Open order {existing_order_id} already contains this SKU.")

        if stock_before is None:
            stock_context = f"The inventory scan found stock at {current_rule.current_stock} {current_rule.unit}, at or below the threshold of {current_rule.min_threshold} {current_rule.unit}."
        else:
            stock_context = f"Stock consumption reduced inventory from {stock_before} to {current_rule.current_stock} {current_rule.unit}; the reorder threshold is {current_rule.min_threshold} {current_rule.unit}."
        reasoning = f"{stock_context} The configured reorder quantity is {current_rule.reorder_quantity} {current_rule.unit}."

        quote_request = QuoteRequest(
            buyer_id=current_rule.buyer_id,
            items=[QuoteItemRequest(
                product_query=current_rule.product_query,
                quantity=float(current_rule.reorder_quantity),
                unit=current_rule.unit,
                max_delivery_date=(date.today() + timedelta(days=2)).isoformat(),
            )],
        )
        quote = await create_quote(quote_request)
        order = await create_order(OrderCreateRequest(buyer_id=current_rule.buyer_id, signed_quote_token=quote.signed_quote_token))
        order.audit_trail.append(AuditLogEntry(timestamp=now_iso(), actor="auto_reorder_agent", action="AUTO_REORDER_TRIGGERED", reasoning=reasoning))
        database.save_order(order, "")
        return InventoryReorderResult(sku=current_rule.sku, status=order.status.lower(), message=reasoning, order=order)
    except HTTPException as exc:
        return InventoryReorderResult(sku=rule.sku, status="failed", message=str(exc.detail))
    finally:
        database.release_reorder_lock(rule.sku)


@app.get("/api/inventory/rules", response_model=list[InventoryRule], tags=["Inventory"])
def get_inventory_rules() -> list[InventoryRule]:
    """List current stock and automatic reorder settings for all inventory items."""
    return database.list_inventory_rules()


@app.patch("/api/inventory/rules/{sku}", response_model=InventoryRule, tags=["Inventory"])
def patch_inventory_rule(sku: str, patch: InventoryRulePatch) -> InventoryRule:
    """Manually update stock, threshold, reorder quantity, or auto-reorder status."""
    updates = patch.model_dump(exclude_unset=True)
    rule = database.update_inventory_rule(sku, updates)
    if rule is None:
        raise HTTPException(status_code=404, detail="Inventory rule not found")
    return rule


@app.post("/api/inventory/consume/{sku}", response_model=InventoryConsumeResponse, tags=["Inventory"])
async def consume_inventory(sku: str, amount: int = Query(default=1, gt=0)) -> InventoryConsumeResponse:
    """Decrease stock and trigger an automatic reorder if the rule threshold is reached."""
    before = database.get_inventory_rule(sku)
    if before is None:
        raise HTTPException(status_code=404, detail="Inventory rule not found")
    after = database.consume_inventory(sku, amount)
    if after is None:
        raise HTTPException(status_code=404, detail="Inventory rule not found")
    reorder_result = None
    if after.auto_reorder_enabled and after.current_stock <= after.min_threshold:
        reorder_result = await _try_auto_reorder(after, stock_before=before.current_stock)
        # Return the latest rule in case inventory settings changed while the request was running.
        after = database.get_inventory_rule(sku) or after
    return InventoryConsumeResponse(item=after, reorder_result=reorder_result)


@app.post("/api/inventory/check-reorder", response_model=InventoryReorderCheckResponse, tags=["Inventory"])
async def check_inventory_reorder() -> InventoryReorderCheckResponse:
    """Scan enabled inventory rules and process any items at or below threshold."""
    results = [await _try_auto_reorder(rule) for rule in database.list_inventory_rules()]
    return InventoryReorderCheckResponse(results=results)
