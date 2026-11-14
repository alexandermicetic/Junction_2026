"""Streamlit dashboard for the Junction 2026 Valio Aimo mock data."""
from __future__ import annotations

import streamlit as st

from data_service import (
    DataSourceUnavailable,
    get_availability,
    get_carbon_footprint,
    get_comparison_data,
    get_data_status,
    get_delivery_reliability,
    get_price,
    get_products,
)

st.set_page_config(page_title="Valio Aimo | Ostamisen näkymä", page_icon="🥛", layout="wide")

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
st.title("Hankinnan tuotevertailu")
st.caption("Mock-dataan perustuva näkymä tuotteiden, saatavuuden, hinnan ja toimitusvastuun tarkasteluun.")

with st.expander("Tietolähteiden tila", expanded=False):
    status = get_data_status()
    cols = st.columns(len(status))
    for col, (label, exists) in zip(cols, status.items()):
        col.metric(label, "Löytyy" if exists else "Puuttuu")
    st.caption(
        "Repo sisältää hiilijalanjälki- ja toimitusvarmuus-CSV:t sekä tuotetietojen skeeman. "
        "Varsinaiset tuotetietueet, hinta- ja varastosaatavuustiedostot puuttuvat. "
        "Niitä ei päätellä muista tiedoista."
    )

st.subheader("1 · Etsi tuote")
query = st.text_input("Tuotteen nimi, brändi, toimittaja tai tuotetunnus", placeholder="Esim. maito tai 460000")
try:
    products = get_products(query, limit=200)
except (OSError, ValueError) as exc:
    products = []
    st.error(f"Tuotetietojen lukeminen epäonnistui: {exc}")

selected = None
quantity = 1.0
if products:
    options = {str(product["id"]): product for product in products}
    selected_id = st.selectbox(
        "Hakutulokset",
        list(options),
        format_func=lambda product_id: f'{options[product_id]["displayName"]} · {product_id}',
    )
    selected = options[selected_id]
    lot_size = selected.get("allowedLotSize")
    try:
        step = float(lot_size) if lot_size and float(lot_size) > 0 else 1.0
    except (TypeError, ValueError):
        step = 1.0
    quantity = st.number_input(
        f'Määrä ({selected.get("salesUnit", "myyntiyksikkö")})',
        min_value=step,
        value=step,
        step=step,
        help="Määrän askel perustuu tuotetietueen allowedLotSize-arvoon.",
    )
else:
    st.info(
        "Tuotehakua ei voi täyttää, koska branchissa ei ole tuotetietojen JSON-tiedostoa. "
        "Lisää tiedosto polkuun backend/data/valio_aimo_junction26_product_data.json."
    )

st.subheader("2 · Hinta ja saatavuus")
if selected:
    left, right = st.columns(2)
    price = get_price(str(selected["id"]), quantity)
    availability = get_availability(str(selected["id"]), quantity)
    left.metric("Hinta", "Ei saatavilla")
    left.caption(price["message"])
    right.metric("Saatavuus", "Ei tarkistettavissa")
    right.caption(availability["message"])
else:
    st.caption("Valitse tuote, kun tuotetietueet ovat saatavilla.")

st.subheader("3 · Hiilijalanjälki ja toimitusvarmuus")
if selected:
    product_id = str(selected["id"])
    carbon = get_carbon_footprint(product_id)
    reliability = get_delivery_reliability(product_id)
    metric_cols = st.columns(2)
    metric_cols[0].metric(
        "Hiilijalanjälki",
        f"{carbon:.3f} kg CO₂-ekv / kg" if carbon is not None else "Ei tuotekohtaista tietoa",
        help="CSV:n yksikkö on kilogrammaa CO₂-ekvivalenttia tuotteen kilogrammaa kohti.",
    )
    metric_cols[1].metric(
        "Toimitusvarmuus",
        f"{reliability:.1%}" if reliability is not None else "Ei tuotekohtaista tietoa",
        help="Arvo esitetään toimitusvarmuus-CSV:ssä murtolukuna välillä 0–1.",
    )
else:
    st.caption("Vertailu käyttää CSV-aineistojen yhteistä tuotejoukkoa tuotetunnuksen perusteella.")

comparison = get_comparison_data()
if comparison:
    chart_col, table_col = st.columns([1.2, 1])
    with chart_col:
        st.markdown("#### Vertailukaavio")
        st.scatter_chart(
            comparison,
            x="carbonKgCo2EqPerKg",
            y="deliveryReliability",
            color="productId",
            x_label="Hiilijalanjälki (kg CO₂-ekv / kg)",
            y_label="Toimitusvarmuus (0–1)",
        )
        st.caption("Yksi piste vastaa tuotetunnusta. Pienempi hiilijalanjälki ja suurempi toimitusvarmuus ovat suotuisia.")
    with table_col:
        st.markdown("#### Tuotekohtaiset tiedot")
        st.dataframe(
            [
                {
                    "Tuote": row["productName"],
                    "Tunnus": row["productId"],
                    "kg CO₂-ekv / kg": row["carbonKgCo2EqPerKg"],
                    "Toimitusvarmuus": f'{row["deliveryReliability"]:.1%}',
                }
                for row in comparison
            ],
            hide_index=True,
            use_container_width=True,
        )
else:
    st.warning("Hiilijalanjäljen ja toimitusvarmuuden CSV-aineistoissa ei ole yhteisiä tuoterivejä.")

if selected:
    with st.expander("Lähdetiedot ja rajaukset"):
        st.write(
            f'Valittu tuote: **{selected["displayName"]}** (tunnus {selected["id"]}). '
            f'Pyydetty määrä: **{quantity:g} {selected.get("salesUnit", "")}**.'
        )
        st.write(
            "Tämä näkymä vertailee toimitusvarmuutta ja hiili-intensiteettiä. "
            "Se ei laske tilauksen kokonaishiilijalanjälkeä, koska datasetin yhteensopivia "
            "tuotepainoja ei ole luotettavasti yhdistetty tilausyksikköön."
        )
        try:
            get_price(str(selected["id"]), quantity)
            get_availability(str(selected["id"]), quantity)
        except DataSourceUnavailable as exc:
            st.info(str(exc))
