"""English Streamlit purchasing UI, chat quote flow, and reorder-rule prototype."""
from __future__ import annotations

from datetime import date, timedelta
from statistics import median

import streamlit as st
import plotly.express as px

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
from llm_service import LLMServiceError, get_chat_response, select_catalog_product

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
                "Quantity",
                min_value=max(1, int(lot_step)),
                value=max(1, int(lot_step)),
                step=1,
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
                    product_id=str(selected["id"]),
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
        "Claude handles conversation and extracts quote requests. Product matching and "
        "quotes still use the local catalog and synthetic backend; this chat cannot place orders."
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
            reply = "I could not process that message. Please try again."
            try:
                assistant_result = get_chat_response(
                    st.session_state["chat_messages"], today=date.today().isoformat()
                )
                reply = str(assistant_result.get("reply") or "How can I help with your purchasing request?")
                if assistant_result["intent"] == "quote":
                    quantity = assistant_result.get("quantity")
                    unit = assistant_result.get("unit")
                    product_query = assistant_result.get("product_query")
                    if not (type(quantity) is int and 1 <= quantity <= 1_000_000):
                        reply = "Please provide a positive whole-number quantity."
                    elif not isinstance(unit, str) or not unit.strip():
                        reply = reply or "Which unit should I use for that quantity?"
                    elif not isinstance(product_query, str) or not product_query.strip():
                        reply = reply or "Which product would you like a quote for?"
                    else:
                        unit = unit.strip()[:40]
                        product_query = product_query.strip()[:200]
                        raw_due_date = assistant_result.get("delivery_date")
                        try:
                            due_date = date.fromisoformat(raw_due_date) if raw_due_date else date.today() + timedelta(days=3)
                        except (TypeError, ValueError):
                            due_date = date.today() - timedelta(days=1)
                        if due_date < date.today():
                            reply = "Please provide a delivery date that is today or later."
                        else:
                            try:
                                matches = get_products(product_query, limit=12, requested_unit=unit)
                            except (OSError, ValueError) as exc:
                                matches = []
                                reply = f"I could not search the product catalog: {exc}"

                            if not matches:
                                if catalog_error:
                                    reply = f"The product catalog is unavailable: {catalog_error}"
                                else:
                                    reply = (
                                        f'I could not find a catalog match for "{product_query}". '
                                        "Try a shorter product name or a product ID."
                                    )
                            else:
                                try:
                                    selection = select_catalog_product(
                                        product_query=product_query,
                                        quantity=quantity,
                                        unit=unit,
                                        candidates=matches,
                                    )
                                    selected_id = selection["product_id"]
                                    selected_product = next(
                                        (product for product in matches if str(product.get("id")) == selected_id),
                                        None,
                                    )
                                    if selected_id == "__none__" or selected_product is None:
                                        reply = (
                                            f'I found catalog records related to "{product_query}", but none '
                                            "could be confirmed as the requested product and unit. Please refine the product name."
                                        )
                                    else:
                                        quote = create_quote(
                                            buyer_id="restaurant-001",
                                            product_query=selected_product["displayName"],
                                            quantity=quantity,
                                            unit=unit,
                                            max_delivery_date=due_date.isoformat(),
                                            product_id=selected_id,
                                        )
                                        st.session_state["chat_quote"] = quote
                                        st.session_state["chat_quote_context"] = {
                                            "query": product_query,
                                            "quantity": quantity,
                                            "unit": unit,
                                            "date": due_date.isoformat(),
                                            "selected_product": selected_product["displayName"],
                                        }
                                        reply = (
                                            f'Claude matched "{selected_product["displayName"]}" to your request. '
                                            f'{quote_summary(quote)}'
                                        )
                                except DataServiceError as exc:
                                    reply = f"I could not retrieve a quote: {exc}"
                                except LLMServiceError as exc:
                                    reply = str(exc)
            except LLMServiceError as exc:
                reply = str(exc)

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
        "lets you configure a rule and simulate a stock update; it cannot monitor stock while the app is closed. "
        "The quote endpoint uses the selected local catalog product ID."
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
                    "Reorder quantity",
                    min_value=max(1, int(rule_step)),
                    value=max(1, int(rule_step)),
                    step=1,
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
    st.subheader("Product sustainability")
    st.caption(
        "Compare product carbon footprints with delivery reliability to spot options that balance lower impact "
        "and dependable supply. Lower CO₂e and higher delivery reliability are preferable."
    )

    comparison = get_comparison_data()
    if comparison:
        carbon_values = [
            row["carbonKgCo2EqPerKg"]
            for row in comparison
            if row["carbonKgCo2EqPerKg"] is not None
        ]
        reliability_values = [
            row["deliveryReliability"]
            for row in comparison
            if row["deliveryReliability"] is not None
        ]
        carbon_midpoint = median(carbon_values) if carbon_values else None
        reliability_midpoint = median(reliability_values) if reliability_values else None

        classified_rows = []
        for row in comparison:
            carbon = row["carbonKgCo2EqPerKg"]
            reliability = row["deliveryReliability"]
            if carbon is None or reliability is None:
                performance_class = "Insufficient data"
            else:
                lower_footprint = carbon_midpoint is not None and carbon <= carbon_midpoint
                higher_reliability = reliability_midpoint is not None and reliability >= reliability_midpoint
                if lower_footprint and higher_reliability:
                    performance_class = "Optimal"
                elif lower_footprint or higher_reliability:
                    performance_class = "Balanced"
                else:
                    performance_class = "Needs improvement"
            classified_rows.append(
                {
                    **row,
                    "performanceClass": performance_class,
                    "deliveryReliabilityPct": reliability * 100 if reliability is not None else None,
                }
            )

        include_missing_carbon = bool(
            st.session_state.get("sustainability_include_missing_carbon", False)
        )
        product_search = str(st.session_state.get("sustainability_search", "")).strip().casefold()

        visible_rows = [
            row
            for row in classified_rows
            if (include_missing_carbon or row["carbonKgCo2EqPerKg"] is not None)
            and (
                not product_search
                or product_search in str(row["productName"]).casefold()
                or product_search in str(row["productId"]).casefold()
            )
        ]
        visible_carbon = [
            row["carbonKgCo2EqPerKg"]
            for row in visible_rows
            if row["carbonKgCo2EqPerKg"] is not None
        ]
        visible_reliability = [
            row["deliveryReliability"]
            for row in visible_rows
            if row["deliveryReliability"] is not None
        ]
        optimal_count = sum(row["performanceClass"] == "Optimal" for row in visible_rows)

        kpis = st.columns(4)
        kpis[0].metric("Products", f"{len(visible_rows):,}")
        kpis[1].metric(
            "Average CO₂e",
            f"{sum(visible_carbon) / len(visible_carbon):.2f} kg CO₂e/kg"
            if visible_carbon
            else "—",
        )
        kpis[2].metric(
            "Average delivery reliability",
            f"{sum(visible_reliability) / len(visible_reliability):.1%}" if visible_reliability else "—",
        )
        kpis[3].metric(
            "Optimal products",
            f"{optimal_count:,}",
            help=(
                "Products with CO₂e at or below the full-dataset median and delivery reliability "
                "at or above its median."
            ),
        )
        st.caption(
            "KPIs and the table follow the active filters. Classes use full-dataset medians: Optimal meets both "
            "benchmarks, Balanced meets one, and Needs improvement meets neither."
        )

        filter_cols = st.columns([1, 1.8])
        filter_cols[0].checkbox(
            "Include products without CO₂e data",
            key="sustainability_include_missing_carbon",
        )
        filter_cols[1].text_input(
            "Search products", placeholder="Product name or ID", key="sustainability_search"
        )

        chart_rows = [
            row for row in visible_rows
            if row["carbonKgCo2EqPerKg"] is not None and row["deliveryReliability"] is not None
        ]
        if chart_rows:
            chart = px.scatter(
                chart_rows,
                x="carbonKgCo2EqPerKg",
                y="deliveryReliabilityPct",
                color="performanceClass",
                color_discrete_map={
                    "Optimal": "#10B981",
                    "Balanced": "#3B82F6",
                    "Needs improvement": "#F97316",
                },
                hover_name="productName",
                hover_data={
                    "productId": True,
                    "carbonKgCo2EqPerKg": ":.2f",
                    "deliveryReliabilityPct": ":.1f",
                    "performanceClass": True,
                },
                labels={
                    "carbonKgCo2EqPerKg": "Carbon footprint (kg CO₂e / kg)",
                    "deliveryReliabilityPct": "Delivery reliability (%)",
                    "performanceClass": "Performance class",
                    "productId": "Product ID",
                },
            )
            chart.update_traces(
                marker={"size": 11, "opacity": 0.85, "line": {"width": 1, "color": "white"}}
            )
            chart.update_xaxes(showgrid=True, gridcolor="rgba(148, 163, 184, 0.18)", zeroline=False)
            chart.update_yaxes(
                range=[0, 100],
                tick0=0,
                dtick=20,
                ticksuffix="%",
                showgrid=True,
                gridcolor="rgba(148, 163, 184, 0.18)",
                zeroline=False,
            )
            chart.update_layout(
                height=460,
                plot_bgcolor="rgba(0, 0, 0, 0)",
                paper_bgcolor="rgba(0, 0, 0, 0)",
                margin={"l": 16, "r": 16, "t": 24, "b": 12},
                legend_title_text="Performance class",
            )
            st.plotly_chart(chart, use_container_width=True, config={"displayModeBar": False})
        elif visible_rows:
            st.info("No visible products have both a CO₂e value and delivery reliability for the chart.")
        else:
            st.info("No products match these filters.")

        st.markdown("#### Product indicators")
        indicator_rows = [
            {
                "Product": row["productName"],
                "Performance class": row["performanceClass"],
                "kg CO₂-eq / kg": row["carbonKgCo2EqPerKg"],
                "Delivery reliability": (
                    row["deliveryReliabilityPct"] if row["deliveryReliabilityPct"] is not None else None
                ),
            }
            for row in visible_rows
        ]
        st.dataframe(
            indicator_rows,
            column_order=["Product", "Performance class", "kg CO₂-eq / kg", "Delivery reliability"],
            column_config={
                "Product": st.column_config.TextColumn("Product", width="large"),
                "Performance class": st.column_config.TextColumn("Class", width="medium"),
                "kg CO₂-eq / kg": st.column_config.NumberColumn(
                    "kg CO₂e / kg", format="%.2f", width="small"
                ),
                "Delivery reliability": st.column_config.ProgressColumn(
                    "Delivery reliability", min_value=0, max_value=100, format="%.0f%%", width="medium"
                ),
            },
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.warning("No product records are available for the sustainability comparison.")
