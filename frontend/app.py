"""English Streamlit dashboard for the Valio Aimo mock purchasing API."""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from data_service import (
    DataServiceError,
    create_quote,
    get_comparison_data,
    get_data_status,
    get_products,
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

st.markdown('<p class="eyebrow">Valio Aimo · Junction 2026</p>', unsafe_allow_html=True)
st.title("Purchasing overview")
st.caption("Search the synthetic product catalog, request a quote, and compare sustainability indicators.")

with st.expander("Data sources", expanded=False):
    status = get_data_status()
    cols = st.columns(len(status))
    for col, (label, exists) in zip(cols, status.items()):
        col.metric(label, "Available" if exists else "Missing")
    st.caption(
        "Product information and sustainability indicators are read from the repository's mock datasets. "
        "Price and availability are returned by the synthetic FastAPI quote endpoint."
    )

st.subheader("1 · Find a product")
query = st.text_input(
    "Search by product name, brand, supplier, or product ID",
    placeholder="For example: lactose-free milk",
)
try:
    products = get_products(query, limit=250)
except (OSError, ValueError) as exc:
    products = []
    st.error(f"Could not read the product catalog: {exc}")

selected = None
if products:
    options = {str(product["id"]): product for product in products}
    selected_id = st.selectbox(
        "Matching products",
        list(options),
        format_func=lambda product_id: f'{options[product_id]["displayName"]} · {product_id}',
    )
    selected = options[selected_id]
else:
    st.warning(
        "No matching product records were found. Check that "
        "backend/data/valio_aimo_junction26_product_data.json is present and that the search is not too specific."
    )

st.subheader("2 · Request price and availability")
quote = None
if selected:
    sales_unit = str(selected.get("salesUnit") or "")
    base_unit = str(selected.get("baseUnit") or "")
    unit_options = list(dict.fromkeys(unit for unit in (sales_unit, base_unit) if unit)) or ["unit"]

    with st.form("quote_form"):
        form_cols = st.columns([1, 1, 1, 1.3])
        try:
            lot_step = float(selected.get("allowedLotSize") or 1)
            if lot_step <= 0:
                lot_step = 1.0
        except (TypeError, ValueError):
            lot_step = 1.0
        quantity = form_cols[0].number_input("Quantity", min_value=lot_step, value=lot_step, step=lot_step)
        unit = form_cols[1].selectbox("Unit", unit_options)
        delivery_date = form_cols[2].date_input(
            "Required by",
            value=date.today() + timedelta(days=3),
            min_value=date.today(),
        )
        buyer_id = form_cols[3].text_input("Buyer ID", value="restaurant-001")
        submitted = st.form_submit_button("Get quote", type="primary", use_container_width=True)

    quote_request_key = (
        str(selected["id"]),
        float(quantity),
        unit,
        delivery_date.isoformat(),
        buyer_id.strip(),
    )

    if submitted:
        try:
            quote = create_quote(
                buyer_id=buyer_id.strip(),
                product_query=selected["displayName"],
                quantity=quantity,
                unit=unit,
                max_delivery_date=delivery_date.isoformat(),
            )
            st.session_state["last_quote"] = quote
            st.session_state["last_quote_request_key"] = quote_request_key
            st.session_state["last_quote_request"] = {
                "quantity": quantity,
                "unit": unit,
                "delivery_date": delivery_date.isoformat(),
                "product_name": selected["displayName"],
            }
        except DataServiceError as exc:
            st.error(str(exc))

    if st.session_state.get("last_quote_request_key") == quote_request_key:
        quote = st.session_state.get("last_quote")
    elif st.session_state.get("last_quote") is not None:
        st.caption("The current selections differ from the last quote. Submit a new request to refresh it.")

    if quote:
        request_info = st.session_state.get("last_quote_request", {})
        st.info(
            "The current backend is a walking skeleton: its quote endpoint returns fixed demo milk items "
            "regardless of the requested product. Review the returned item names before relying on this quote."
        )
        quoted_items = quote.get("items", [])
        total = quote.get("total_eur")
        all_in_stock = bool(quoted_items) and all(item.get("in_stock") for item in quoted_items)
        any_in_stock = any(item.get("in_stock") for item in quoted_items)

        metric_cols = st.columns(3)
        metric_cols[0].metric("Quote total", f"€{total:,.2f}" if total is not None else "Not provided")
        metric_cols[1].metric(
            "Availability",
            "In stock" if all_in_stock else ("Partially available" if any_in_stock else "Unavailable"),
        )
        metric_cols[2].metric("Quote valid until", quote.get("valid_until", "Not provided"))

        st.markdown("#### Quoted items")
        st.dataframe(
            [
                {
                    "Product": item.get("name"),
                    "Package": item.get("package_size"),
                    "Quantity": item.get("quantity"),
                    "Unit price": f'€{item["unit_price_eur"]:,.2f}' if item.get("unit_price_eur") is not None else "—",
                    "Line total": f'€{item["total_price_eur"]:,.2f}' if item.get("total_price_eur") is not None else "—",
                    "In stock": "Yes" if item.get("in_stock") else "No",
                    "Substitution": "Yes" if item.get("is_substitution") else "No",
                }
                for item in quoted_items
            ],
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            f'Requested: {request_info.get("quantity", "—")} {request_info.get("unit", "")} of '
            f'{request_info.get("product_name", "the selected product")}, by '
            f'{request_info.get("delivery_date", "the selected date")}. '
            f'Quote ID: {quote.get("quote_id", "not provided")}.'
        )
        with st.expander("Quote details"):
            st.write("The signed quote token is available to the application for a future order flow.")
            st.code(quote.get("signed_quote_token", "No token returned"), language="text")
            st.write("This screen only requests and reviews a quote. It does not submit an order.")
else:
    st.caption("Choose a product from the catalog to request a quote.")

st.subheader("3 · Carbon footprint and delivery reliability")
st.caption(
    "The chart joins the two repository CSV files by product ID. Carbon footprint is kg CO₂-equivalent per kg; "
    "delivery reliability is shown as a percentage."
)
comparison = get_comparison_data()
if comparison:
    chart_col, table_col = st.columns([1.2, 1])
    with chart_col:
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
    with table_col:
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
