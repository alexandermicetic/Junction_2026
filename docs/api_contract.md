# Valio Aimo Trusted Trade Gateway – API Contract

The walking skeleton uses synthetic B2B foodservice wholesale data. The server runs at `http://127.0.0.1:8000`, and Swagger UI is available at `/docs`.

## POST `/api/quote`

Creates a buyer-specific quote. Example request:

```json
{"buyer_id":"restaurant-001","items":[{"product_query":"lactose-free milk","quantity":1000,"unit":"L","max_delivery_date":"2026-11-20"}]}
```

The response contains two package sizes (500 × 1 L and 50 × 10 L), totalling EUR 1,150, plus a dummy signed quote token for the frontend.

## POST `/api/orders`

Creates an order using the quote token. Orders above EUR 500 remain pending approval.

```json
{"buyer_id":"restaurant-001","signed_quote_token":"eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.dummy-quote-signature"}
```

The response is an `OrderResponse`, for example `{"status":"PENDING_APPROVAL","total_eur":1150.0,"blocked_reasons":["Total 1150.00 EUR exceeds autonomous limit 500.00 EUR"]}`, together with product details and an audit trail.

## GET `/api/orders`

Returns a list of `OrderResponse` objects. The first call includes one `CONFIRMED` and one `PENDING_APPROVAL` example order.

## POST `/api/orders/{order_id}/decision`

Records an approver's decision for a pending order:

```json
{"decision":"APPROVE","approver_name":"Aino Manager","comment":"Budjetti tarkistettu."}
```

`APPROVE` changes the status to `CONFIRMED`, while `REJECT` changes it to `REJECTED`. The decision is appended to the audit trail.

## GET `/api/guardrails`

Returns the current in-memory guardrails. The default is:

```json
{"max_autonomous_spend_eur":500.0,"forbidden_allergens":["lactose"],"allow_substitutions":true}
```

## PUT `/api/guardrails`

Updates the guardrails with the following JSON body:

```json
{"max_autonomous_spend_eur":750.0,"forbidden_allergens":["lactose","peanut"],"allow_substitutions":false}
```

## POST `/api/claude/purchase`

Asks Claude to interpret one product request, compare live quoted options, select one SKU, and submit only that selected product through the signed quote and existing order guardrails. Requests for multiple products or missing/ambiguous quantities return `needs_clarification` without creating an order. A guardrail-blocked order is returned as `PENDING_APPROVAL` for the normal human decision endpoint.

```json
{"buyer_id":"BUYER-TEST-001","request_text":"Order 12 cases of lactose-free milk","max_delivery_date":"2026-11-17"}
```

Configure `ANTHROPIC_API_KEY` in the ignored `backend/.env` file. `ANTHROPIC_MODEL` defaults to `claude-sonnet-5`; use `ANTHROPIC_WORKSPACE_ID` when the key is not scoped to a single workspace. Claude's short product selection summary is recorded in the order audit trail as `claude_purchase_agent`; the signed quote and guardrail evaluation remain server-side.

All responses use JSON. An invalid request returns a FastAPI validation error (HTTP 422), an unknown order returns HTTP 404, and an order that has already been decided returns HTTP 409.
