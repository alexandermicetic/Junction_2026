"""MCP interface for Valio Aimo's trusted trade gateway."""

from mcp.server.fastmcp import FastMCP

from main import create_order, create_quote
from schemas import OrderCreateRequest, QuoteItemRequest, QuoteRequest


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


if __name__ == "__main__":
    mcp.run()
