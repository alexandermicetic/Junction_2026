"""MCP interface for Valio Aimo's trusted trade gateway."""

from mcp.server.fastmcp import FastMCP

from main import check_inventory_reorder, create_order, create_quote, get_inventory_rules, patch_inventory_rule
from schemas import InventoryRulePatch, OrderCreateRequest, QuoteItemRequest, QuoteRequest


mcp = FastMCP("Valio Aimo Trusted Trade Gateway")


@mcp.tool()
async def request_verified_quote(
    buyer_id: str,
    product_query: str,
    quantity: float,
    unit: str,
    max_delivery_date: str,
) -> dict:
    """Request a signed quote for a buyer and product.

    The gateway searches the catalog, retrieves customer-specific price and
    availability data, and returns a cryptographically signed quote token.
    External agents must preserve this token and submit it unchanged when
    placing an order; the gateway verifies its signature and expiration.
    """
    request = QuoteRequest(
        buyer_id=buyer_id,
        items=[QuoteItemRequest(product_query=product_query, quantity=quantity, unit=unit, max_delivery_date=max_delivery_date)],
    )
    response = await create_quote(request)
    return response.model_dump()


@mcp.tool()
async def submit_guarded_order(buyer_id: str, signed_quote_token: str) -> dict:
    """Submit a signed quote for guarded order processing.

    The gateway cryptographically verifies that the quote belongs to the
    buyer and is still valid, then evaluates autonomous guardrail limits such
    as maximum spend, forbidden allergens, and substitution policy. Orders
    that pass are confirmed automatically; blocked orders are held for human
    approval with the reasons recorded in the audit trail.
    """
    request = OrderCreateRequest(buyer_id=buyer_id, signed_quote_token=signed_quote_token)
    response = await create_order(request)
    return response.model_dump()


@mcp.tool()
def get_inventory_status() -> list[dict]:
    """Inspect inventory levels, reorder thresholds, quantities, and auto-reorder settings."""
    return [item.model_dump() for item in get_inventory_rules()]


@mcp.tool()
def update_reorder_settings(
    sku: str,
    reorder_quantity: int | None = None,
    min_threshold: int | None = None,
    auto_reorder_enabled: bool | None = None,
) -> dict:
    """Update an item's reorder quantity, stock threshold, or automatic reorder setting."""
    request = InventoryRulePatch(
        reorder_quantity=reorder_quantity,
        min_threshold=min_threshold,
        auto_reorder_enabled=auto_reorder_enabled,
    )
    return patch_inventory_rule(sku, request).model_dump()


@mcp.tool()
async def run_auto_reorder_check() -> dict:
    """Scan inventory and submit signed, guardrail-checked orders for eligible low-stock items."""
    return (await check_inventory_reorder()).model_dump()


if __name__ == "__main__":
    mcp.run()
