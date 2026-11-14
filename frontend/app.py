"""English Streamlit purchasing UI, chat quote flow, and reorder-rule prototype."""
from __future__ import annotations

import re
from datetime import date, timedelta

import streamlit as st

from data_service import (
    DataServiceError,
    create_order,
    create_quote,
    get_comparison_data,
    get_data_status,
    get_guardrails,
    get_products,
    update_guardrails,
)

st.set_page_config(page_title="Valio Aimo | Purchasing", page_icon="🥛", layout="wide")
st.markdown(
    """
    <style>
      .block-container { max-width: 1180px; padding-top: 2rem; padding-bottom: 3rem; }
      [data-testid="stMetric"] {
        background: #f5f8f5; border: 1px solid #e2ebe3; padding: 1rem 1.1rem;
        border-radius: 14px;
      }
      div[data-testid="stMetricValue"] { color: #174c37; }
      .eyebrow { color: #557264; text-transform: uppercase; letter-spacing: .12em;
                 font-size: .75rem; font-weight: 700; }
    </style>
    """,
    unsafe_allow_html=True,
)


def parse_chat_request(message: str) -> tuple[float, str, str, date] | None:
    """Parse a small, explicit subset of natural-language quantity requests."""
    quantity_match = re.search(
        r"(?P<quantity>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>litres?|liters?|l\b|kilograms?|kg\b|cases?|packs?|units?)",
        message,
        re.IGNORECASE,
    )
    if not quantity_match:
        return None

    quantity = float(quantity_match.group("quantity").replace(",", ""))
    raw_unit = quantity_match.group("unit").casefold()
    if raw_unit.startswith(("litre", "liter")) or raw_unit == "l":
        unit = "L"
    elif raw_unit.startswith("kilogram") or raw_unit == "kg":
        unit = "KG"
    elif raw_unit.startswith("case"):
        unit = "CASE"
    elif raw_unit.startswith("pack"):
        unit = "PACK"
    else:
        unit = "unit"

    product_match = re.search(
        r"\bof\s+(.+?)(?=\s+\b(?:by|before|on)\b|[?.!,]|$)",
        message,
        re.IGNORECASE,
    )
    if product_match:
        product_query = product_match.group(1).strip()
    else:
        product_query = re.sub(
            r"\b(?:i need|please find|find|order)\b",
            "",
            message,
            flags=re.IGNORECASE,
        )
        product_query = re.sub(quantity_match.group(0), "", product_query).strip(" .,?!")

    due_match = re.search(
        r"\bby\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        message,
        re.IGNORECASE,
    )
    if due_match:
        weekday_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        target_weekday = weekday_names.index(due_match.group(1).casefold())
        days_ahead = (target_weekday - date.today().weekday()) % 7
        due_date = date.today() + timedelta(days=days_ahead or 7)
    else:
        due_date = date.today() + timedelta(days=3)

    if not product_query:
        return None
    return quantity, unit, product_query, due_date


def quote_summary(quote: dict) -> str:
    items = quote.get("items", [])
    names = ", ".join(item.get("name", "Unnamed item") for item in items)
    total = quote.get("total_eur")
    total_text = f"€{total:,.2f}" if total is not None else "no total returned"
    return f"Quote {quote.get('quote_id', '')}: {names}. Total: {total_text}."


st.markdown('<p class="eyebrow">Valio Aimo · Junction 2026</p>', unsafe_allow_html=True)
st.title("Purchasing overview")
st.caption("Search products, request quotes, chat about a purchase, and configure a mock reorder rule.")

status = get_data_status()
with st.expander("Data sources", expanded=False):
    cols = st.columns(len(status))
    for col, (label, exists) in zip(cols, status.items()):
        col.metric(label, "Available" if exists else "Missing")
    st.caption(
        "Product and sustainability information come from repository mock data. "
        "Quote, order, and guardrail actions use the synthetic FastAPI backend."
    )

catalog_error = None
try:
    catalog_products = get_products("", limit=1000)
except (OSError, ValueError) as exc:
    catalog_products = []
    catalog_error = str(exc)

search_tab, chat_tab, reorder_tab, compare_tab = st.tabs(
    ["Product search & quote", "Purchasing chat", "Auto-reorder", "Sustainability"]
)

with search_tab:
    st.subheader("Find a product")
    query = st.text_input(
        "Search by product name, brand, supplier, or product ID",
        placeholder="For example: lactose-free milk",
        key="catalog_query",
    )
    if catalog_error:
        st.error(f"Could not read the product catalog: {catalog_error}")
        products = []
    else:
        products = get_products(query, limit=250)

    selected = None
    if products:
        options = {str(product["id"]): product for product in products}
        selected_id = st.selectbox(
            "Matching products",
            list(options),
            format_func=lambda product_id: f'{options[product_id]["displayName"]} · {product_id}',
        )
        selected = options[selected_id]
    elif not status["Product records (JSON)"]:
        st.warning("The product catalog file backend/data/valio_aimo_junction26_product_data.json is missing.")
    else:
        st.info("No products match this search. Try a different name, brand, supplier, or product ID.")

    st.subheader("Request price and availability")
    if selected:
        unit_options = list(
            dict.fromkeys(
                str(unit)
                for unit in (selected.get("salesUnit"), selected.get("baseUnit"))
                if unit
            )
        ) or ["unit"]
        try:
            lot_step = float(selected.get("allowedLotSize") or 1)
            if lot_step <= 0:
                lot_step = 1.0
        except (TypeError, ValueError):
            lot_step = 1.0

        with st.form("catalog_quote_form"):
            form_cols = st.columns([1, 1, 1, 1.2])
            quantity = form_cols[0].number_input(
                "Quantity", min_value=lot_step, value=lot_step, step=lot_step
            )
            unit = form_cols[1].selectbox("Unit", unit_options)
            due_date = form_cols[2].date_input(
                "Required by", value=date.today() + timedelta(days=3), min_value=date.today()
            )
            buyer_id = form_cols[3].text_input("Buyer ID", value="restaurant-001")
            submitted = st.form_submit_button("Get quote", type="primary", use_container_width=True)

        request_key = (str(selected["id"]), float(quantity), unit, due_date.isoformat(), buyer_id.strip())
        if submitted:
            try:
                quote = create_quote(
                    buyer_id=buyer_id.strip(),
                    product_query=selected["displayName"],
                    quantity=quantity,
                    unit=unit,
                    max_delivery_date=due_date.isoformat(),
                )
                st.session_state["catalog_quote"] = quote
                st.session_state["catalog_quote_request_key"] = request_key
            except DataServiceError as exc:
                st.error(str(exc))
                st.session_state.pop("catalog_quote_request_key", None)

        quote = (
            st.session_state.get("catalog_quote")
            if st.session_state.get("catalog_quote_request_key") == request_key
            else None
        )
        if quote:
            st.warning(
                "The current backend returns fixed demo milk items regardless of the requested product. "
                "Review the returned names before relying on this quote."
            )
            quote_cols = st.columns(3)
            quote_cols[0].metric("Quote total", f'€{quote["total_eur"]:,.2f}')
            quote_cols[1].metric(
                "Availability",
                "In stock" if all(item.get("in_stock") for item in quote.get("items", [])) else "Not fully in stock",
            )
            quote_cols[2].metric("Valid until", quote.get("valid_until", "Not provided"))
            st.dataframe(
                [
                    {
                        "Product": item.get("name"),
                        "Package": item.get("package_size"),
                        "Quantity": item.get("quantity"),
                        "Unit price": f'€{item["unit_price_eur"]:,.2f}',
                        "Line total": f'€{item["total_price_eur"]:,.2f}',
                        "In stock": "Yes" if item.get("in_stock") else "No",
                        "Substitution": "Yes" if item.get("is_substitution") else "No",
                    }
                    for item in quote.get("items", [])
                ],
                hide_index=True,
                use_container_width=True,
            )
        elif st.session_state.get("catalog_quote") is not None:
            st.caption("The form values changed. Submit again to request an updated quote.")
    else:
        st.caption("Choose a product from the catalog to request a quote.")

with chat_tab:
    st.subheader("Purchasing assistant")
    st.caption(
        "This frontend prototype parses quantity, unit, product, and weekday from a request, "
        "then searches the catalog and requests a quote. It does not use an LLM."
    )
    if "chat_messages" not in st.session_state:
        st.session_state["chat_messages"] = [
            {
                "role": "assistant",
                "content": "Tell me what you need and when. For example: “I need 1,000 litres of lactose-free milk by Monday.”",
            }
        ]
    for message in st.session_state["chat_messages"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input("Describe the products and quantities you need")
    if prompt:
        st.session_state["chat_messages"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            parsed = parse_chat_request(prompt)
            if parsed is None:
                reply = "Please include a quantity and unit, such as “1,000 litres”."
                st.markdown(reply)
            else:
                quantity, unit, product_query, due_date = parsed
                try:
                    matches = get_products(product_query, limit=5)
                except (OSError, ValueError) as exc:
                    matches = []
                    reply = f"I could not search the product catalog: {exc}"

                if not matches and not catalog_error:
                    reply = (
                        f'I could not find a catalog match for “{product_query}”. '
                        "Try a shorter product name or a product ID."
                    )
                elif matches:
                    try:
                        quote = create_quote(
                            buyer_id="restaurant-001",
                            product_query=product_query,
                            quantity=quantity,
                            unit=unit,
                            max_delivery_date=due_date.isoformat(),
                        )
                        st.session_state["chat_quote"] = quote
                        st.session_state["chat_quote_context"] = {
                            "query": product_query,
                            "quantity": quantity,
                            "unit": unit,
                            "date": due_date.isoformat(),
                            "matches": [item["displayName"] for item in matches],
                        }
                        reply = (
                            f'I found {len(matches)} catalog match(es), including '
                            f'“{matches[0]["displayName"]}”. {quote_summary(quote)} '
                            "The quote endpoint currently returns fixed demo milk items, so check that they match your request."
                        )
                    except DataServiceError as exc:
                        reply = f"I could not retrieve a quote: {exc}"
                elif catalog_error:
                    reply = f"The product catalog is unavailable: {catalog_error}"

                st.markdown(reply)
        st.session_state["chat_messages"].append({"role": "assistant", "content": reply})

    chat_quote = st.session_state.get("chat_quote")
    if chat_quote:
        context = st.session_state.get("chat_quote_context", {})
        st.markdown("#### Latest quote")
        st.caption(
            f'Request: {context.get("quantity")} {context.get("unit")} of {context.get("query")} '
            f'by {context.get("date")}.'
        )
        st.dataframe(
            [
                {
                    "Quoted product": item.get("name"),
                    "Package": item.get("package_size"),
                    "Quantity": item.get("quantity"),
                    "Unit price": f'€{item["unit_price_eur"]:,.2f}',
                    "Line total": f'€{item["total_price_eur"]:,.2f}',
                    "In stock": "Yes" if item.get("in_stock") else "No",
                }
                for item in chat_quote.get("items", [])
            ],
            hide_index=True,
            use_container_width=True,
        )

with reorder_tab:
    st.subheader("Automatic reorder rules")
    st.caption(
        "The backend has no inventory feed or background scheduler yet. This frontend-only prototype "
        "lets you configure a rule and simulate a stock update; it cannot monitor stock while the app is closed."
    )
    try:
        guardrails = get_guardrails()
        guardrails_error = None
    except DataServiceError as exc:
        guardrails = None
        guardrails_error = str(exc)

    if guardrails_error:
        st.error(f"Could not load purchasing limits: {guardrails_error}")
    elif guardrails:
        st.markdown("#### Purchasing limits")
        with st.form("guardrails_form"):
            max_spend = st.number_input(
                "Maximum automatic spend (€)",
                min_value=0.01,
                value=float(guardrails["max_autonomous_spend_eur"]),
                step=50.0,
            )
            forbidden_text = st.text_input(
                "Forbidden allergens (comma-separated)",
                value=", ".join(guardrails.get("forbidden_allergens", [])),
            )
            allow_substitutions = st.checkbox(
                "Allow substitute products", value=bool(guardrails.get("allow_substitutions", False))
            )
            save_limits = st.form_submit_button("Save purchasing limits")
        if save_limits:
            config = {
                "max_autonomous_spend_eur": max_spend,
                "forbidden_allergens": [value.strip() for value in forbidden_text.split(",") if value.strip()],
                "allow_substitutions": allow_substitutions,
            }
            try:
                guardrails = update_guardrails(config)
                st.success("Purchasing limits saved to the mock backend.")
            except DataServiceError as exc:
                st.error(f"Could not save purchasing limits: {exc}")

        st.markdown("#### Reorder rule")
        if not catalog_products:
            st.info("A reorder rule needs product records from the mock catalog.")
        else:
            product_options = {str(product["id"]): product for product in catalog_products}
            with st.form("reorder_rule_form"):
                enabled = st.checkbox("Enable this rule", value=False)
                rule_product_id = st.selectbox(
                    "Product",
                    list(product_options),
                    format_func=lambda product_id: f'{product_options[product_id]["displayName"]} · {product_id}',
                )
                rule_product = product_options[rule_product_id]
                try:
                    rule_step = float(rule_product.get("allowedLotSize") or 1)
                    if rule_step <= 0:
                        rule_step = 1.0
                except (TypeError, ValueError):
                    rule_step = 1.0
                threshold = st.number_input("Reorder when stock is at or below", min_value=0.0, value=1.0, step=rule_step)
                reorder_quantity = st.number_input(
                    "Reorder quantity", min_value=rule_step, value=rule_step, step=rule_step
                )
                rule_buyer = st.text_input("Buyer ID", value="restaurant-001")
                rule_days = st.number_input("Days until required delivery", min_value=0, value=3, step=1)
                save_rule = st.form_submit_button("Save reorder rule")
            if save_rule:
                st.session_state["reorder_rule"] = {
                    "enabled": enabled,
                    "product_id": rule_product_id,
                    "product_name": rule_product["displayName"],
                    "unit": rule_product.get("salesUnit") or rule_product.get("baseUnit") or "unit",
                    "threshold": threshold,
                    "quantity": reorder_quantity,
                    "buyer_id": rule_buyer.strip(),
                    "days": int(rule_days),
                }
                st.session_state["reorder_triggered"] = False
                st.success("Reorder rule saved for this Streamlit session.")

            rule = st.session_state.get("reorder_rule")
            if rule:
                st.write(
                    f'**{"Enabled" if rule["enabled"] else "Disabled"}:** reorder {rule["quantity"]:g} '
                    f'{rule["unit"]} of {rule["product_name"]} when stock is at or below {rule["threshold"]:g}.'
                )
                with st.form("stock_simulation_form"):
                    current_stock = st.number_input(
                        f'Current stock ({rule["unit"]})',
                        min_value=0.0,
                        value=rule["threshold"],
                        step=rule["threshold"] or 1.0,
                    )
                    check_stock = st.form_submit_button("Simulate stock update")
                if check_stock:
                    if not rule["enabled"]:
                        st.info("Enable and save the reorder rule before simulating a stock update.")
                    elif current_stock > rule["threshold"]:
                        st.session_state["reorder_triggered"] = False
                        st.success("Stock is above the reorder threshold. The rule is armed.")
                    elif st.session_state.get("reorder_triggered"):
                        st.warning("This low-stock event has already been handled. Raise stock above the threshold to re-arm the rule.")
                    else:
                        st.warning("Low-stock threshold reached. Checking a quote against the saved purchasing limits.")
                        try:
                            quote = create_quote(
                                buyer_id=rule["buyer_id"],
                                product_query=rule["product_name"],
                                quantity=rule["quantity"],
                                unit=rule["unit"],
                                max_delivery_date=(date.today() + timedelta(days=rule["days"])).isoformat(),
                            )
                            items = quote.get("items", [])
                            reasons = []
                            if not items:
                                reasons.append("The quote contains no items.")
                            if any(not item.get("in_stock", False) for item in items):
                                reasons.append("One or more quoted items are not in stock.")
                            total_value = quote.get("total_eur")
                            if total_value is None:
                                reasons.append("The quote did not include a total.")
                                total = 0.0
                            else:
                                total = float(total_value)
                            if total > float(guardrails["max_autonomous_spend_eur"]):
                                reasons.append(
                                    f'The quote total (€{total:,.2f}) exceeds the automatic spend limit '
                                    f'of €{guardrails["max_autonomous_spend_eur"]:,.2f}.'
                                )
                            forbidden = {item.casefold() for item in guardrails.get("forbidden_allergens", [])}
                            quote_allergens = {
                                allergen.casefold()
                                for item in items
                                for allergen in item.get("allergens", [])
                            }
                            blocked_allergens = forbidden & quote_allergens
                            if blocked_allergens:
                                reasons.append("The quote contains a forbidden allergen: " + ", ".join(sorted(blocked_allergens)))
                            if not guardrails.get("allow_substitutions", False) and any(
                                item.get("is_substitution") for item in items
                            ):
                                reasons.append("The quote includes a substitute, and substitutions are disabled.")

                            if not quote.get("signed_quote_token"):
                                reasons.append("The quote did not include a signed quote token.")
                            if reasons:
                                st.error("No order was submitted. " + " ".join(reasons))
                            else:
                                st.session_state["reorder_triggered"] = True
                                order = create_order(rule["buyer_id"], quote["signed_quote_token"])
                                st.write(f'Order request status: **{order.get("status", "Unknown")}**')
                                st.write(f'Order ID: {order.get("order_id", "Not provided")}')
                                if order.get("status") == "PENDING_APPROVAL":
                                    st.warning(
                                        "The backend requires human approval for this order. "
                                        "It has not been automatically confirmed."
                                    )
                                elif order.get("status") == "CONFIRMED":
                                    st.success("The backend confirmed the order.")
                        except (DataServiceError, KeyError, TypeError, ValueError) as exc:
                            st.session_state["reorder_triggered"] = False
                            st.error(f"Could not complete the reorder check: {exc}")
    else:
        st.info("The backend did not return purchasing limits.")

with compare_tab:
    st.subheader("Carbon footprint and delivery reliability")
    st.caption(
        "This chart joins the two repository CSV files by product ID. Carbon footprint is kg CO₂-equivalent per kg; "
        "delivery reliability is shown as a percentage."
    )
    comparison = get_comparison_data()
    if comparison:
        left, right = st.columns([1.2, 1])
        with left:
            st.markdown("#### Product comparison")
            st.scatter_chart(
                comparison,
                x="carbonKgCo2EqPerKg",
                y="deliveryReliability",
                x_label="Carbon footprint (kg CO₂-eq / kg)",
                y_label="Delivery reliability (0–1)",
                alt="Carbon footprint versus delivery reliability for products with both measurements.",
            )
            st.caption("Lower carbon footprint and higher delivery reliability are preferable.")
        with right:
            st.markdown("#### Product indicators")
            st.dataframe(
                [
                    {
                        "Product": row["productName"],
                        "Product ID": row["productId"],
                        "kg CO₂-eq / kg": row["carbonKgCo2EqPerKg"],
                        "Delivery reliability": f'{row["deliveryReliability"]:.1%}',
                    }
                    for row in comparison
                ],
                hide_index=True,
                use_container_width=True,
            )
    else:
        st.warning("The carbon footprint and delivery reliability datasets have no product IDs in common.")
