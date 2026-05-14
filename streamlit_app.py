import streamlit as st
import pandas as pd
import snowflake.connector
import requests
import pydeck as pdk
from datetime import datetime



# -----------------------------
# CONFIG
# -----------------------------
BASE_URL = "https://snowflake-accelerator-demo.onrender.com/"

def get_connection():
    return snowflake.connector.connect(
        user='NIKITA2411',
        password='Nikitamahajan2411**',
        account='NCGTNVJ-UF51495',
        warehouse='COMPUTE_WH',
        database='LOGISTICS_DB1',
        schema='LOGISTICS_SCHEMA1'
    )

st.set_page_config(layout="wide")

col1, col2 = st.columns([6, 2])
with col1:
    st.title("🚚Enterprise Logistics Control Tower")
    st.markdown("✨Real-time visibility. Smarter logistics.")

with col2:
    now = datetime.now()
    st.title(f"🕒{now.strftime('%I:%M %p')}")
    st.markdown(f"📅{now.strftime('%d %b %Y')}")

st.divider()

# -----------------------------
# SAFE API
# -----------------------------
def safe_get(endpoint, params=None):
    try:
        res = requests.get(f"{BASE_URL}{endpoint}", params=params)
        if res.status_code != 200:
            return None
        return res.json()
    except:
        return None

# -----------------------------
# LOAD LOCATIONS
# -----------------------------
@st.cache_data(ttl=300)
def load_locations():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT CITY FROM LOCATIONS ORDER BY CITY")
    data = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return data

# -----------------------------
# LOAD HUBS FOR A CITY
# -----------------------------
@st.cache_data(ttl=300)
def load_hubs_for_city(city):
    """Return list of hub names for a given city."""
    if not city:
        return []
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT HUB_ID, HUB_NAME
        FROM HUBS
        WHERE LOWER(CITY) = LOWER(%s)
        ORDER BY HUB_NAME
    """, (city,))
    data = [(r[0], r[1]) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return data  # list of (hub_id, hub_name)

locations = load_locations()

# -----------------------------
# SIDEBAR — CASCADING FILTERS
# -----------------------------
st.sidebar.header("🔍 Route Filters")

# STEP 1: Source City
source = st.sidebar.selectbox(
    "📍 Source City",
    [""] + locations,
    key="source_city"
)

# STEP 2: Source Hub (depends on source city)
source_hub_id = None
source_hub_name = None

if source:
    source_hubs = load_hubs_for_city(source)
    if source_hubs:
        hub_labels = [h[1] for h in source_hubs]
        selected_src_hub_label = st.sidebar.selectbox(
            "🏭 Source Hub",
            [""] + hub_labels,
            key="source_hub"
        )
        if selected_src_hub_label:
            matched = [h for h in source_hubs if h[1] == selected_src_hub_label]
            if matched:
                source_hub_id = matched[0][0]
                source_hub_name = matched[0][1]
    else:
        st.sidebar.info(f"No hubs found in {source}")
else:
    st.sidebar.selectbox("🏭 Source Hub", ["— select source city first —"], disabled=True, key="source_hub_disabled")

# STEP 3: Destination City (only shown after source hub is selected)
destination = None
if source_hub_id:
    destination = st.sidebar.selectbox(
        "🏁 Destination City",
        [""] + [loc for loc in locations if loc != source],
        key="dest_city"
    )
else:
    st.sidebar.selectbox("🏁 Destination City", ["— select source hub first —"], disabled=True, key="dest_city_disabled")

# STEP 4: Destination Hub (depends on destination city)
dest_hub_id = None
dest_hub_name = None

if destination:
    dest_hubs = load_hubs_for_city(destination)
    if dest_hubs:
        hub_labels_dest = [h[1] for h in dest_hubs]
        selected_dest_hub_label = st.sidebar.selectbox(
            "🏭 Destination Hub",
            [""] + hub_labels_dest,
            key="dest_hub"
        )
        if selected_dest_hub_label:
            matched_dest = [h for h in dest_hubs if h[1] == selected_dest_hub_label]
            if matched_dest:
                dest_hub_id = matched_dest[0][0]
                dest_hub_name = matched_dest[0][1]
    else:
        st.sidebar.info(f"No hubs found in {destination}")
elif source_hub_id:
    st.sidebar.selectbox("🏭 Destination Hub", ["— select destination city first —"], disabled=True, key="dest_hub_disabled")

# Analyze button — enabled only when all 4 selections are complete
analyze_btn = st.sidebar.button(
    "🚀 Analyze Route",
    disabled=not (source and source_hub_id and destination and dest_hub_id)
)

# Show a friendly progress hint in the sidebar
st.sidebar.divider()
steps_done = sum([bool(source), bool(source_hub_id), bool(destination), bool(dest_hub_id)])
st.sidebar.progress(steps_done / 4, text=f"Step {steps_done} of 4 complete")

# -----------------------------
# ROUTE ANALYSIS
# -----------------------------
def analyze_route(source, destination, source_hub_id=None, dest_hub_id=None):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT ROUTE_ID, SOURCE_CITY, DESTINATION_CITY, DISTANCE, ESTIMATED_TIME
        FROM ROUTES
        WHERE LOWER(SOURCE_CITY)=LOWER(%s)
        AND LOWER(DESTINATION_CITY)=LOWER(%s)
    """, (source, destination))

    data = cur.fetchone()
    if not data:
        return None

    route_id, src, dest, distance, time = data

    cur.execute("""
        SELECT FROM_CITY, TO_CITY
        FROM ROUTE_SEGMENTS
        WHERE ROUTE_ID=%s
        ORDER BY SEQUENCE
    """, (route_id,))

    segs = cur.fetchall()

    path = [s[0] for s in segs]
    if segs:
        path.append(segs[-1][1])

    intermediate = list(dict.fromkeys(path[1:-1]))

    hubs = []
    seen = set()

    for city in intermediate:
        cur.execute("""
            SELECT H.HUB_ID, H.HUB_NAME, H.CITY,
                   COALESCE(I.AVAILABLE_QUANTITY,0)
            FROM HUBS H
            LEFT JOIN INVENTORY I ON H.HUB_ID = I.HUB_ID
            WHERE LOWER(H.CITY)=LOWER(%s)
        """, (city,))

        for h in cur.fetchall():
            hub_id, name, city_name, inv = h

            if hub_id in seen:
                continue
            seen.add(hub_id)

            cur.execute("""
                SELECT COUNT(*),
                       SUM(CASE WHEN STATUS='AVAILABLE' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN STATUS='INUSE' THEN 1 ELSE 0 END)
                FROM VEHICLES
                WHERE HUB_ID=%s
            """, (hub_id,))

            total, available, inuse = cur.fetchone()

            hubs.append({
                "Hub": name,
                "City": city_name,
                "Inventory": inv,
                "Vehicles": total,
                "Available": available,
                "In Use": inuse
            })

    # Fetch source hub details
    source_hub_info = None
    if source_hub_id:
        cur.execute("""
            SELECT H.HUB_ID, H.HUB_NAME, H.CITY,
                   COALESCE(I.AVAILABLE_QUANTITY, 0)
            FROM HUBS H
            LEFT JOIN INVENTORY I ON H.HUB_ID = I.HUB_ID
            WHERE H.HUB_ID = %s
        """, (source_hub_id,))
        row = cur.fetchone()
        if row:
            hub_id, name, city_name, inv = row
            cur.execute("""
                SELECT COUNT(*),
                       SUM(CASE WHEN STATUS='AVAILABLE' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN STATUS='INUSE' THEN 1 ELSE 0 END)
                FROM VEHICLES WHERE HUB_ID=%s
            """, (hub_id,))
            total, available, inuse = cur.fetchone()
            source_hub_info = {
                "Hub": name, "City": city_name, "Inventory": inv,
                "Vehicles": total, "Available": available, "In Use": inuse
            }

    # Fetch destination hub details
    dest_hub_info = None
    if dest_hub_id:
        cur.execute("""
            SELECT H.HUB_ID, H.HUB_NAME, H.CITY,
                   COALESCE(I.AVAILABLE_QUANTITY, 0)
            FROM HUBS H
            LEFT JOIN INVENTORY I ON H.HUB_ID = I.HUB_ID
            WHERE H.HUB_ID = %s
        """, (dest_hub_id,))
        row = cur.fetchone()
        if row:
            hub_id, name, city_name, inv = row
            cur.execute("""
                SELECT COUNT(*),
                       SUM(CASE WHEN STATUS='AVAILABLE' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN STATUS='INUSE' THEN 1 ELSE 0 END)
                FROM VEHICLES WHERE HUB_ID=%s
            """, (hub_id,))
            total, available, inuse = cur.fetchone()
            dest_hub_info = {
                "Hub": name, "City": city_name, "Inventory": inv,
                "Vehicles": total, "Available": available, "In Use": inuse
            }

    # MAP DATA
    cur.execute("SELECT CITY, LATITUDE, LONGITUDE FROM LOCATIONS")
    loc_df = pd.DataFrame(cur.fetchall(), columns=["City", "lat", "lon"])

    route_map = loc_df[loc_df["City"].isin(path)].copy()
    route_map["type"] = "Route"

    hub_map = loc_df[loc_df["City"].isin(intermediate)].copy()
    hub_map["type"] = "Hub"

    final_map = pd.concat([route_map, hub_map])

    cur.close()
    conn.close()

    return {
        "route": f"{src} → {dest}",
        "distance": distance,
        "time": time,
        "hubs": hubs,
        "path": path,
        "map": final_map,
        "source_hub": source_hub_info,
        "dest_hub": dest_hub_info,
    }

# -----------------------------
# HELPER: Render a hub card
# -----------------------------
def render_hub_card(hub, badge=""):
    with st.container(border=True):
        st.markdown(f"### {badge} {hub['Hub']}")
        st.caption(f"📍 {hub['City']}")
        st.divider()
        col1, col2 = st.columns(2)
        col1.metric("Inventory", hub["Inventory"])
        col2.metric("Total Vehicles", hub["Vehicles"])
        col3, col4 = st.columns(2)
        col3.success(f"✅ Available: {hub['Available']}")
        col4.error(f"🔴 In Use: {hub['In Use']}")

# -----------------------------
# MAIN PANEL
# -----------------------------
result = None

if analyze_btn and source and source_hub_id and destination and dest_hub_id:
    result = analyze_route(source, destination, source_hub_id, dest_hub_id)

    if result:
        # ---- ROUTE METRICS ----
        with st.container(border=True):
            c1, c2, c3 = st.columns(3)
            c1.metric("📍 Route", result["route"])
            c2.metric("📏 Distance", f"{result['distance']} km")
            c3.metric("⏱ Time", f"{result['time']} hrs")

        # ---- ROUTE PATH ----
        st.subheader("🛣 Route Path")
        with st.container(border=True):
            st.success(" → ".join(result["path"]))

        # ---- SOURCE & DESTINATION HUB CARDS ----
        st.subheader("🔰 Selected Source & Destination Hubs")
        src_col, dest_col = st.columns(2)

        with src_col:
            if result["source_hub"]:
                render_hub_card(result["source_hub"], badge="🟢 Source Hub")
            else:
                st.info("Source hub details not available")

        with dest_col:
            if result["dest_hub"]:
                render_hub_card(result["dest_hub"], badge="🟠 Destination Hub")
            else:
                st.info("Destination hub details not available")

        # ---- INTERMEDIATE HUB CARDS ----
        st.subheader("🏢 Intermediate Hubs")

        if result["hubs"]:
            cols = st.columns(3)
            for i, hub in enumerate(result["hubs"]):
                with cols[i % 3]:
                    render_hub_card(hub, badge="📦")
        else:
            st.info("No intermediate hubs on this route")

# -----------------------------
# 🗺 PYDECK MAP
# -----------------------------
st.subheader("🗺 Smart Route Visualization")

if result:
    map_df = result["map"]

    if not map_df.empty:

        def assign_color(row):
            if row["City"] == result["path"][0]:
                return [0, 200, 0]       # Source — Green
            elif row["City"] == result["path"][-1]:
                return [255, 165, 0]     # Destination — Orange
            elif row["type"] == "Hub":
                return [255, 0, 0]       # Intermediate Hub — Red
            else:
                return [0, 128, 255]     # Route waypoint — Blue

        map_df = map_df.copy()
        map_df["color"] = map_df.apply(assign_color, axis=1)

        def assign_radius(row):
            if row["City"] in [result["path"][0], result["path"][-1]]:
                return 80000
            return 50000

        map_df["radius"] = map_df.apply(assign_radius, axis=1)

        # Build ordered line coords
        ordered_coords = []
        for city in result["path"]:
            row = map_df[map_df["City"] == city]
            if not row.empty:
                ordered_coords.append([row.iloc[0]["lon"], row.iloc[0]["lat"]])

        line_data = pd.DataFrame({"path": [ordered_coords]})

        scatter = pdk.Layer(
            "ScatterplotLayer",
            data=map_df,
            get_position='[lon, lat]',
            get_color='color',
            get_radius='radius',
            pickable=True
        )

        line = pdk.Layer(
            "PathLayer",
            data=line_data,
            get_path="path",
            get_color=[0, 128, 255],
            width_scale=20,
            width_min_pixels=2
        )

        view = pdk.ViewState(
            latitude=map_df["lat"].mean(),
            longitude=map_df["lon"].mean(),
            zoom=5,
            pitch=30
        )

        tooltip = {
            "html": "<b>City:</b> {City}<br/><b>Type:</b> {type}",
            "style": {"backgroundColor": "black", "color": "white"}
        }

        st.pydeck_chart(pdk.Deck(
            layers=[scatter, line],
            initial_view_state=view,
            tooltip=tooltip
        ))

    else:
        st.warning("No map data available")

# -----------------------------
# KPI DASHBOARD
# -----------------------------
st.subheader("📊 KPI Dashboard")

dashboard = safe_get("/dashboard_data")
orders = safe_get("/active_orders")

# -------- MAIN LAYOUT --------
left, right = st.columns([1, 2])

# -----------------------------
# LEFT SIDE → KPI (CONTAINERS)
# -----------------------------
with left:
    if dashboard:
        with st.container(border=True):
         st.markdown("### 📈 KPIs")

         pending = (
             dashboard["status"]["PLACED"] +
             dashboard["status"]["PROCESSING"] +
             dashboard["status"]["READY_FOR_DISPATCH"]
         )

        # Row 1
         r1c1, r1c2 = st.columns(2)
         with r1c1:
             with st.container(border=True):
                 st.metric("Total Orders", dashboard["total"])

         with r1c2:
             with st.container(border=True):
                 st.metric("In Transit", dashboard["status"]["IN_TRANSIT"])

        # Row 2
         r2c1, r2c2 = st.columns(2)
         with r2c1:
             with st.container(border=True):
                 st.metric("Delivered", dashboard["status"]["DELIVERED"])

         with r2c2:
             with st.container(border=True):
                 st.metric("Pending", pending)

    else:
        st.info("No KPI data")

# -----------------------------
# RIGHT SIDE → ACTIVE ORDERS
# -----------------------------
with right:
 
    with st.container(border=True):
 
        st.markdown("### 📦 Active Orders")
 
        if orders:
 
            # -------------------------------
            # CREATE DATAFRAME
            # -------------------------------
            df = pd.DataFrame(orders)
 
            # -------------------------------
            # PERFECT COLUMN ORDER
            # -------------------------------
            column_order = [
                "id",
                "status",
                "source",
                "destination",
                "base_load",
                "extra_load",
                "extra_load_hubs",
                "total_reached"
            ]
 
            # -------------------------------
            # KEEP ONLY EXISTING COLUMNS
            # -------------------------------
            existing_columns = [
                col for col in column_order
                if col in df.columns
            ]
 
            df = df[existing_columns]
 
            # -------------------------------
            # RENAME HEADERS
            # -------------------------------
            df = df.rename(columns={
                "id": "Order ID",
                "status": "Status",
                "source": "Source",
                "destination": "Destination",
                "base_load": "Base Load",
                "extra_load": "Extra Load",
                "extra_load_hubs": "Extra Load Taken From",
                "total_reached": "Total Reached Destination"
            })
 
            # -------------------------------
            # SHOW TABLE
            # -------------------------------
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True
            )
 
        else:
            st.info("No active orders")  

# -----------------------------
# CHARTS
# -----------------------------
st.subheader("📈 Analytics")

if dashboard:
    status_df = pd.DataFrame(
        list(dashboard["status"].items()),
        columns=["Status", "Count"]
    )

    hub_df = pd.DataFrame(dashboard["hubs"])

    col1, col2 = st.columns(2)

    with col1:
        st.write("Order Status")
        st.bar_chart(status_df.set_index("Status"))

    with col2:
        st.write("Hub Inventory")
        if not hub_df.empty:
            st.bar_chart(hub_df.set_index("hub"))
        else:
            st.info("No hub data")
