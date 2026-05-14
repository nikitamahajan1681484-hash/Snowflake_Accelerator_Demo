from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
import snowflake.connector
import uuid
from datetime import datetime, timedelta
import math
from flask import redirect




app = Flask(__name__)
CORS(app)


# -------------------------------
# SNOWFLAKE CONNECTION
# -------------------------------
def get_connection():
    return snowflake.connector.connect(
        user='NIKITA2411',
        password='Nikitamahajan2411**',
        account='NCGTNVJ-UF51495',
        warehouse='COMPUTE_WH',
        database='LOGISTICS_DB1',
        schema='LOGISTICS_SCHEMA1'
    )

# -------------------------------
# PAGES
# -------------------------------
@app.route('/')
def home():
    conn = get_connection()
    cursor = conn.cursor()
 
    # HUBS
    cursor.execute("""
    SELECT HUB_ID, HUB_NAME, CITY
    FROM HUBS
""")
 
    hubs = []
 
    for row in cursor.fetchall():
        hubs.append({
        "id": row[0],
        "name": row[1],
        "city": row[2]
    })
 
# INVENTORY
    cursor.execute("""
    SELECT HUB_ID, SUM(AVAILABLE_QUANTITY)
    FROM INVENTORY
    GROUP BY HUB_ID
""")
 
    inventory_rows = cursor.fetchall()
 
    inventory_map = {}
    for row in inventory_rows:
        inventory_map[row[0]] = row[1]
 
    return render_template(
    "home.html",
    hubs=hubs,
    inventory_map=inventory_map
)

@app.route('/create')
def create_page():
    return render_template('create.html')
 
@app.route('/orders')
def orders_page():
    return render_template('orders.html')
 
@app.route('/process/<order_id>')
def process_page(order_id):
    return render_template('process.html', order_id=order_id)
 
@app.route('/inventory/<order_id>')
def inventory_page(order_id):
    return render_template('inventory.html', order_id=order_id)
 
# ✅ Tracking with Order ID
@app.route('/tracking/<order_id>')
def tracking_with_id(order_id):
    return render_template('tracking.html', order_id=order_id)
 
 
# ✅ Tracking without ID (from navbar)
@app.route('/tracking')
def tracking_without_id():
    return render_template('tracking.html', order_id=None)
 
 
@app.route('/dashboard')
def dashboard_page():
     return redirect("https://dashboardlogisticsystem.streamlit.app/")
 
 
# -------------------------------
# CREATE ORDER
# -------------------------------
@app.route('/create_order', methods=['POST'])
def create_order():
    try:
        data = request.json

        source = data['source'].strip().upper()
        destination = data['destination'].strip().upper()

        conn = get_connection()
        cursor = conn.cursor()

        # Validate source location
        cursor.execute("""
            SELECT COUNT(*) 
            FROM LOCATIONS 
            WHERE UPPER(CITY) = %s
        """, (source,))
        
        source_exists = cursor.fetchone()[0]

        # Validate destination location
        cursor.execute("""
            SELECT COUNT(*) 
            FROM LOCATIONS 
            WHERE UPPER(CITY) = %s
        """, (destination,))
        
        destination_exists = cursor.fetchone()[0]

        # If source or destination invalid
        if source_exists == 0:
            cursor.close()
            conn.close()
            return jsonify({
                "success": False,
                "error": f"Invalid source location: {data['source']}"
            }), 400

        if destination_exists == 0:
            cursor.close()
            conn.close()
            return jsonify({
                "success": False,
                "error": f"Invalid destination location: {data['destination']}"
            }), 400

        # Create order only if validation passed
        order_id = "ORD_" + str(uuid.uuid4())[:8]

        cursor.execute("""
            INSERT INTO ORDERS (
                ORDER_ID,
                ORG_ID,
                SOURCE_LOCATION,
                DESTINATION_LOCATION,
                LOAD_QUANTITY,
                DELIVERY_DATE,
                PRIORITY,
                ORDER_STATUS,
                CREATED_AT
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            order_id,
            data['org_id'],
            source,
            destination,
            int(data['load']),
            data['date'],
            data['priority'],
            "PLACED",
            datetime.now()
        ))

        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({
            "success": True,
            "order_id": order_id
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
   
 
# -------------------------------
# GET ORDERS
# -------------------------------
@app.route('/get_orders')
def get_orders():
    try:
        conn = get_connection()
        cursor = conn.cursor()
 
        cursor.execute("""
            SELECT
                O.ORDER_ID,
                O.SOURCE_LOCATION,
                O.DESTINATION_LOCATION,
                O.LOAD_QUANTITY,
                COALESCE(SUM(M.LOAD), 0) AS ADDED_LOAD,
                O.LOAD_QUANTITY + COALESCE(SUM(M.LOAD), 0) AS TOTAL_LOAD,
                O.ORDER_STATUS
            FROM ORDERS O
            LEFT JOIN MID_ROUTE_LOADS M
                ON O.ORDER_ID = M.ORDER_ID
            GROUP BY
                O.ORDER_ID,
                O.SOURCE_LOCATION,
                O.DESTINATION_LOCATION,
                O.LOAD_QUANTITY,
                O.ORDER_STATUS,
                O.CREATED_AT
            ORDER BY O.CREATED_AT DESC
        """)
        rows = cursor.fetchall()
 
        orders = []
        for row in rows:
            orders.append({
                "ORDER_ID": row[0],
                "SOURCE": row[1],
                "DESTINATION": row[2],
                "ORIGINAL_LOAD": row[3],
                "ADDED_LOAD": row[4],
                "LOAD": row[5],
                "STATUS": row[6]
            })
 
        cursor.close()
        conn.close()
 
        return jsonify(orders)
 
    except Exception as e:
        return jsonify({"error": str(e)})
 
# -------------------------------
# PROCESS ORDER
# -------------------------------
@app.route('/process_order/<order_id>')
def process_order(order_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
 
        # ORDER
        cursor.execute("""
            SELECT SOURCE_LOCATION, DESTINATION_LOCATION, LOAD_QUANTITY
            FROM ORDERS WHERE ORDER_ID = %s
        """, (order_id,))
        order = cursor.fetchone()
 
        if not order:
            return jsonify({"error": "Order not found"})
 
        source, destination, base_quantity = order
 
        cursor.execute("""
            SELECT COALESCE(SUM(LOAD), 0)
            FROM MID_ROUTE_LOADS
            WHERE ORDER_ID=%s
        """, (order_id,))
        added_load = cursor.fetchone()[0] or 0
        quantity = base_quantity + added_load
 
        # ROUTE
        cursor.execute("""
            SELECT ROUTE_ID, DISTANCE, ESTIMATED_TIME
            FROM ROUTES
            WHERE SOURCE_CITY = %s AND DESTINATION_CITY = %s
            LIMIT 1
        """, (source, destination))
        route = cursor.fetchone()
 
        if not route:
            return jsonify({"error": "No route found"})
 
        route_id, distance, time = route
 
        # HUB
        cursor.execute("""
         SELECT H.HUB_ID, H.HUB_NAME, COALESCE(I.AVAILABLE_QUANTITY, 0)
FROM HUBS H
LEFT JOIN INVENTORY I ON H.HUB_ID = I.HUB_ID
WHERE LOWER(H.CITY) = LOWER(%s)
""", (source,))
        hubs = cursor.fetchall()
        if not hubs:
            return jsonify({"error": f"No hubs found for city {source}"})
 
# ✅ prioritize FULL → then highest inventory
        full_hubs = [h for h in hubs if h[2] >= quantity]
 
        if full_hubs:
            selected = max(full_hubs, key=lambda x: x[2])
        else:
            selected = max(hubs, key=lambda x: x[2])
 
        hub_id, hub_name, inventory = selected
 
        # INVENTORY
        cursor.execute("""
            SELECT AVAILABLE_QUANTITY FROM INVENTORY WHERE HUB_ID=%s
        """, (hub_id,))
        inv = cursor.fetchone()
        inventory = inv[0] if inv else 0
 
        # PREDICTION
        incoming = quantity
 
        # DECISION (correct)
        if inventory >= incoming:
            decision = "FULL"
            deducted = incoming
        elif inventory > 0:
            decision = "PARTIAL"
            deducted = inventory
        else:
            decision = "WAIT"
            deducted = 0
 
        if deducted > 0:
            cursor.execute("""
            UPDATE INVENTORY
            SET AVAILABLE_QUANTITY = AVAILABLE_QUANTITY - %s
            WHERE HUB_ID = %s
           AND AVAILABLE_QUANTITY >= %s
           """, (deducted, hub_id, deducted))
           
        total_available = inventory - incoming
 
        selected_vehicle = select_available_vehicle(cursor, hub_id, 1)
        if not selected_vehicle:
            cursor.execute("""
                UPDATE ORDERS
                SET ORDER_STATUS='PLACED'
                WHERE ORDER_ID=%s
            """, (order_id,))
            conn.commit()
            cursor.close()
            conn.close()
            return jsonify({"error": "No vehicle available at source hub"})
 
        selected_vehicle_id, _vehicle_capacity, _vehicle_load, remaining_capacity = selected_vehicle
        vehicles_required = 1
 
        # STATUS UPDATE
        status = "READY_FOR_DISPATCH" if decision == "FULL" else "PARTIAL"
 
        cursor.execute("""
            UPDATE ORDERS SET ORDER_STATUS=%s WHERE ORDER_ID=%s
        """, (status, order_id))
 
        conn.commit()
        cursor.close()
        conn.close()
 
        return jsonify({
            "route_id": route_id,
            "route": f"{source} → {destination}",
            "distance": distance,
            "time": time,
            "hub_name": hub_name,
            "inventory": inventory,
            "incoming": incoming,
            "total_available": total_available,
            "decision": decision,
            "vehicles_required": vehicles_required,
            "vehicle_id": selected_vehicle_id,
            "vehicle_remaining_capacity": remaining_capacity
        })
 
    except Exception as e:
        return jsonify({"error": str(e)})
 
@app.route('/get_inventory/<order_id>')
def get_inventory(order_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
 
        # Get order
        cursor.execute("""
            SELECT SOURCE_LOCATION, DESTINATION_LOCATION, LOAD_QUANTITY
            FROM ORDERS WHERE ORDER_ID = %s
        """, (order_id,))
        order = cursor.fetchone()
 
        if not order:
            return jsonify({"error": "Order not found"})
 
        source, destination, base_quantity = order
 
        cursor.execute("""
            SELECT COALESCE(SUM(LOAD), 0)
            FROM MID_ROUTE_LOADS
            WHERE ORDER_ID=%s
        """, (order_id,))
        added_load = cursor.fetchone()[0] or 0
        quantity = base_quantity + added_load
 
        # Get hub
        cursor.execute("""
         SELECT H.HUB_ID, H.HUB_NAME, COALESCE(I.AVAILABLE_QUANTITY, 0)
         FROM HUBS H
         LEFT JOIN INVENTORY I ON H.HUB_ID = I.HUB_ID
         WHERE LOWER(H.CITY) = LOWER(%s)
        """, (destination,))
        hubs = cursor.fetchall()
        if not hubs:
            return jsonify({"error": f"No hubs found for city {destination}"})
 
# ✅ prioritize FULL → then highest inventory
        full_hubs = [h for h in hubs if h[2] >= quantity]
 
        if full_hubs:
            selected = max(full_hubs, key=lambda x: x[2])
        else:
            selected = max(hubs, key=lambda x: x[2])
 
        hub_id, hub_name, inventory = selected
 
       
        # Get inventory
        cursor.execute("""
            SELECT AVAILABLE_QUANTITY FROM INVENTORY WHERE HUB_ID=%s
        """, (hub_id,))
        inv = cursor.fetchone()
 
        inventory = inv[0] if inv else 0
 
        # Prediction
        incoming = quantity
 
        total = inventory + incoming
 
        decision = "FULL" if total >= quantity else "PARTIAL"
 
        cursor.close()
        conn.close()
 
        return jsonify({
            "order_id": order_id,
            "source": source,
            "destination": destination,
            "hub": hub_name,
            "required": quantity,
            "base_load": base_quantity,
            "added_load": added_load,
            "available": inventory,
            "incoming": incoming,
            "total": total,
            "decision": decision
        })
 
    except Exception as e:
        return jsonify({"error": str(e)})
 
# -------------------------------
# DISPATCH
# -------------------------------
@app.route('/dispatch/<order_id>')
def dispatch_order(order_id):
    conn = get_connection()
    cursor = conn.cursor()
 
    cursor.execute("""
        SELECT SOURCE_LOCATION, DESTINATION_LOCATION, LOAD_QUANTITY
        FROM ORDERS WHERE ORDER_ID=%s
    """, (order_id,))
    order = cursor.fetchone()
    if not order:
        cursor.close()
        conn.close()
        return jsonify({"error": "Order not found"})
 
    source, destination, quantity = order
 
    cursor.execute("""
        SELECT ROUTE_ID FROM ROUTES
        WHERE SOURCE_CITY=%s AND DESTINATION_CITY=%s
        LIMIT 1
    """, (source, destination))
    route = cursor.fetchone()
    if not route:
        cursor.close()
        conn.close()
        return jsonify({"error": "No route found"})
 
    route_id = route[0]
 
    source_hub = find_hub_for_city(cursor, source)
    if not source_hub:
        cursor.close()
        conn.close()
        return jsonify({"error": f"No hubs found for city {source}"})
 
    source_hub_id, source_hub_name = source_hub
    vehicle = select_available_vehicle(cursor, source_hub_id, 1)
    if not vehicle:
        cursor.execute("""
            UPDATE ORDERS
            SET ORDER_STATUS='PLACED'
            WHERE ORDER_ID=%s
        """, (order_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"error": "No vehicle available at source hub"})
 
    vehicle_id, _capacity, _current_load, remaining_capacity = vehicle
    assigned_load = min(quantity, remaining_capacity)
 
    start_time = datetime.now() + timedelta(minutes=1)
    assign_time = start_time + timedelta(seconds=10)
 
    dispatch_id = "DSP_" + str(uuid.uuid4())[:6]
 
    cursor.execute("""
        INSERT INTO DISPATCH
        (DISPATCH_ID, ORDER_ID, STATUS, CREATED_AT, START_TIME, ROUTE_ID, VEHICLE_ASSIGN_TIME, VEHICLE_ID)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        dispatch_id,
        order_id,
        "SCHEDULED",
        datetime.now(),
        start_time,
        route_id,
        assign_time,
        vehicle_id
    ))
 
    mark_vehicle_in_use(cursor, vehicle_id, assigned_load, source_hub_name)
    cursor.execute("""
        UPDATE ORDERS
        SET ORDER_STATUS='ASSIGNED'
        WHERE ORDER_ID=%s
    """, (order_id,))
 
    conn.commit()
    cursor.close()
    conn.close()
 
    return jsonify({
        "message": f"Vehicle {vehicle_id} assigned from {source_hub_name}",
        "vehicle_id": vehicle_id,
        "source_hub": source_hub_name
    })
 
 
SEGMENT_TIME_SECONDS = 80
LOADING_DELAY_SECONDS = 5
ARRIVAL_PHASE = 0.95
 
 
def get_table_columns(cursor, table_name):
    cursor.execute("""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = CURRENT_SCHEMA()
          AND TABLE_NAME = %s
    """, (table_name.upper(),))
    return {row[0].upper() for row in cursor.fetchall()}
 
 
def find_hub_for_city(cursor, city):
    cursor.execute("""
        SELECT H.HUB_ID, H.HUB_NAME
        FROM HUBS H
        LEFT JOIN INVENTORY I ON H.HUB_ID = I.HUB_ID
        WHERE LOWER(H.CITY)=LOWER(%s)
        ORDER BY COALESCE(I.AVAILABLE_QUANTITY, 0) DESC, H.HUB_NAME
        LIMIT 1
    """, (city,))
    return cursor.fetchone()
 
 
def vehicle_tie_break_column(cursor):
    columns = get_table_columns(cursor, "VEHICLES")
    for column in ("LAST_USED_AT", "LAST_USED", "UPDATED_AT", "CREATED_AT"):
        if column in columns:
            return column
    return None
 
 
def select_available_vehicle(cursor, hub_id, min_capacity=1):
    tie_column = vehicle_tie_break_column(cursor)
    tie_order = f", {tie_column} ASC NULLS FIRST" if tie_column else ""
    cursor.execute(f"""
        SELECT VEHICLE_ID, CAPACITY, COALESCE(CURRENT_LOAD, 0),
               CAPACITY - COALESCE(CURRENT_LOAD, 0) AS REMAINING_CAPACITY
        FROM VEHICLES
        WHERE HUB_ID=%s
          AND STATUS='AVAILABLE'
          AND CAPACITY - COALESCE(CURRENT_LOAD, 0) >= %s
        ORDER BY REMAINING_CAPACITY DESC{tie_order}, VEHICLE_ID ASC
        LIMIT 1
    """, (hub_id, min_capacity))
    return cursor.fetchone()
 
 
def mark_vehicle_in_use(cursor, vehicle_id, load, location):
    cursor.execute("""
        UPDATE VEHICLES
        SET STATUS='IN_USE',
            CURRENT_LOAD=COALESCE(CURRENT_LOAD, 0) + %s,
            CURRENT_LOCATION=%s
        WHERE VEHICLE_ID=%s
    """, (load, location, vehicle_id))
 
 
def reserve_inventory(cursor, hub_id, load):
    cursor.execute("""
        UPDATE INVENTORY
        SET AVAILABLE_QUANTITY = AVAILABLE_QUANTITY - %s
        WHERE HUB_ID = %s
          AND AVAILABLE_QUANTITY >= %s
    """, (load, hub_id, load))
    return cursor.rowcount > 0
 
 
def add_inventory(cursor, hub_id, load):
    if load <= 0:
        return
 
    cursor.execute("""
        UPDATE INVENTORY
        SET AVAILABLE_QUANTITY = AVAILABLE_QUANTITY + %s
        WHERE HUB_ID = %s
    """, (load, hub_id))
 
    if cursor.rowcount == 0:
        cursor.execute("""
            INSERT INTO INVENTORY (HUB_ID, AVAILABLE_QUANTITY)
            VALUES (%s, %s)
        """, (hub_id, load))
 
 
def build_path(segments):
    if not segments:
        return []
 
    path = [segments[0][0]]
    for segment in segments:
        path.append(segment[1])
    return path
 
 
def get_mid_route_loads(cursor, order_id):
    cursor.execute("""
        SELECT ID, VEHICLE_ID, LOAD, PICKUP_HUB, STATUS, LOADING_TIME
        FROM MID_ROUTE_LOADS
        WHERE ORDER_ID=%s
        ORDER BY LOADING_TIME NULLS FIRST, ID
    """, (order_id,))
    return cursor.fetchall()
 
 
def loading_delay_seconds(load_rows, now):
    delay = 0
    for _mid_id, _vid, _load, _hub, status, loading_time in load_rows:
        if status in ("WAITING", "COMPLETED") and loading_time:
            waited = max((now - loading_time).total_seconds(), 0)
            delay += min(waited, LOADING_DELAY_SECONDS)
    return delay
 
 
def movement_state(assign_time, now, segments, load_rows):
    total_segments = len(segments)
    if total_segments == 0:
        return 0, 1, 1, 0
 
    raw_elapsed = max((now - assign_time).total_seconds(), 0)
    effective_elapsed = max(raw_elapsed - loading_delay_seconds(load_rows, now), 0)
    index = int(effective_elapsed // SEGMENT_TIME_SECONDS)
    progress = min(effective_elapsed / (SEGMENT_TIME_SECONDS * total_segments), 1)
 
    if index >= total_segments:
        return index, 1, progress, effective_elapsed
 
    phase = (effective_elapsed % SEGMENT_TIME_SECONDS) / SEGMENT_TIME_SECONDS
    return index, phase, progress, effective_elapsed
 
 
def stops_for_path(path, active_index):
    stops = []
    for i, city in enumerate(path):
        if i < active_index:
            status = "completed"
        elif i == active_index:
            status = "active"
        else:
            status = ""
        stops.append({"city": city, "status": status})
    return stops
 
 
# ---------------------------
# TRACK API (FINAL)
# ---------------------------
@app.route('/track/<order_id>')
def track_order(order_id):

    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        # --------------------------------
        # ORDER
        # --------------------------------
        cursor.execute("""
            SELECT SOURCE_LOCATION,
                   DESTINATION_LOCATION,
                   LOAD_QUANTITY,
                   ORDER_STATUS
            FROM ORDERS
            WHERE ORDER_ID=%s
        """, (order_id,))

        order = cursor.fetchone()

        if not order:
            return jsonify({"error": "Order not found"})

        source, destination, base_quantity, order_status = order

        # --------------------------------
        # ROUTE
        # --------------------------------
        cursor.execute("""
            SELECT ROUTE_ID
            FROM ROUTES
            WHERE SOURCE_CITY=%s
              AND DESTINATION_CITY=%s
            LIMIT 1
        """, (source, destination))

        route = cursor.fetchone()

        if not route:
            return jsonify({"error": "No route found"})

        route_id = route[0]

        # --------------------------------
        # SEGMENTS
        # --------------------------------
        cursor.execute("""
            SELECT FROM_CITY, TO_CITY
            FROM ROUTE_SEGMENTS
            WHERE ROUTE_ID=%s
            ORDER BY SEQUENCE
        """, (route_id,))

        segments = cursor.fetchall()

        path = build_path(segments)

        if not path:
            return jsonify({"error": "Route has no segments"})

        # --------------------------------
        # DISPATCH
        # --------------------------------
        cursor.execute("""
            SELECT START_TIME,
                   VEHICLE_ASSIGN_TIME,
                   VEHICLE_ID
            FROM DISPATCH
            WHERE ORDER_ID=%s
            ORDER BY CREATED_AT DESC
            LIMIT 1
        """, (order_id,))

        dispatch = cursor.fetchone()

        if not dispatch:
            return jsonify({
                "status": "READY_TO_DISPATCH",
                "current_location": f"At {source}",
                "progress_percent": 0,
                "events": [],
                "stops": [
                    {"city": c, "status": ""}
                    for c in path
                ]
            })

        start_time, assign_time, vehicle_id = dispatch

        now = datetime.now()

        # --------------------------------
        # WAITING
        # --------------------------------
        if now < start_time:

            return jsonify({
                "status": "WAITING_FOR_DISPATCH",
                "current_location": f"At {source}",
                "progress_percent": 0,
                "events": [],
                "stops": [
                    {
                        "city": c,
                        "status": "active" if i == 0 else ""
                    }
                    for i, c in enumerate(path)
                ]
            })

        # --------------------------------
        # ASSIGNING
        # --------------------------------
        elif start_time <= now < assign_time:

            return jsonify({
                "status": "ASSIGNING_VEHICLE",
                "current_location": f"At {source}",
                "progress_percent": 5,
                "events": [],
                "stops": [
                    {
                        "city": c,
                        "status": "active" if i == 0 else ""
                    }
                    for i, c in enumerate(path)
                ]
            })

        # --------------------------------
        # INITIAL DISPATCH
        # --------------------------------
        elif now >= assign_time and now < assign_time + timedelta(seconds=5):

            # INITIAL SOURCE LOAD
            cursor.execute("""
                UPDATE VEHICLES
                SET STATUS='IN_USE',
                    CURRENT_LOAD=%s,
                    CURRENT_LOCATION=%s
                WHERE VEHICLE_ID=%s
            """, (base_quantity, source, vehicle_id))

            conn.commit()

            return jsonify({
                "status": "DISPATCHED",
                "current_location": f"Leaving {source}",
                "progress_percent": 10,
                "events": [],
                "stops": [
                    {
                        "city": c,
                        "status": "active" if i == 0 else ""
                    }
                    for i, c in enumerate(path)
                ]
            })

        # --------------------------------
        # LOAD ROWS
        # --------------------------------
        events = []

        load_rows = get_mid_route_loads(cursor, order_id)

        # --------------------------------
        # COMPLETE EXTRA LOAD
        # --------------------------------
        for mid_id, vid, load, hub, status, loading_time in load_rows:

            if (
                status == "WAITING"
                and loading_time
                and now >= loading_time + timedelta(seconds=LOADING_DELAY_SECONDS)
            ):

                # COMPLETE ONLY ONCE
                cursor.execute("""
                    UPDATE MID_ROUTE_LOADS
                    SET STATUS='COMPLETED'
                    WHERE ID=%s
                      AND STATUS='WAITING'
                """, (mid_id,))

                if cursor.rowcount > 0:

                    # ADD EXTRA LOAD ONLY ONCE
                    cursor.execute("""
                        UPDATE VEHICLES
                        SET CURRENT_LOAD = CURRENT_LOAD + %s
                        WHERE VEHICLE_ID=%s
                    """, (load, vid))

                    conn.commit()

                    events.append({
                        "type": "LOADED",
                        "message": f"Extra load collected at {hub}"
                    })

        if events:
            load_rows = get_mid_route_loads(cursor, order_id)

        # --------------------------------
        # MOVEMENT
        # --------------------------------
        index, phase, progress, effective_elapsed = movement_state(
            assign_time,
            now,
            segments,
            load_rows
        )

        # --------------------------------
        # DELIVERY
        # --------------------------------
        if index >= len(segments):

            # CHECK LATEST ORDER STATUS
            cursor.execute("""
                SELECT ORDER_STATUS
                FROM ORDERS
                WHERE ORDER_ID=%s
            """, (order_id,))

            latest_status_row = cursor.fetchone()

            latest_status = latest_status_row[0] if latest_status_row else ""

            # RUN ONLY FIRST TIME
            if latest_status != "DELIVERED":

                # TOTAL EXTRA LOAD
                cursor.execute("""
                    SELECT COALESCE(SUM(LOAD), 0)
                    FROM MID_ROUTE_LOADS
                    WHERE ORDER_ID=%s
                      AND STATUS='COMPLETED'
                """, (order_id,))

                extra_load = cursor.fetchone()[0] or 0

                total_load = base_quantity + extra_load

                # DESTINATION HUB
                destination_hub = find_hub_for_city(cursor, destination)

                if destination_hub:

                    destination_hub_id, destination_hub_name = destination_hub

                    # CHECK INVENTORY EXISTS
                    cursor.execute("""
                        SELECT AVAILABLE_QUANTITY
                        FROM INVENTORY
                        WHERE HUB_ID=%s
                    """, (destination_hub_id,))

                    inventory_row = cursor.fetchone()

                    # UPDATE INVENTORY
                    if inventory_row:

                        cursor.execute("""
                            UPDATE INVENTORY
                            SET AVAILABLE_QUANTITY =
                                AVAILABLE_QUANTITY + %s
                            WHERE HUB_ID=%s
                        """, (total_load, destination_hub_id))

                    # INSERT INVENTORY
                    else:

                        cursor.execute("""
                            INSERT INTO INVENTORY
                            (HUB_ID, AVAILABLE_QUANTITY)
                            VALUES (%s, %s)
                        """, (destination_hub_id, total_load))

                # ORDER DELIVERED
                cursor.execute("""
                    UPDATE ORDERS
                    SET ORDER_STATUS='DELIVERED'
                    WHERE ORDER_ID=%s
                """, (order_id,))

                # RESET VEHICLE
                if vehicle_id:

                    cursor.execute("""
                        UPDATE VEHICLES
                        SET STATUS='AVAILABLE',
                            CURRENT_LOAD=0,
                            CURRENT_LOCATION=%s
                        WHERE VEHICLE_ID=%s
                    """, (source, vehicle_id))

                conn.commit()

            return jsonify({
                "status": "DELIVERED",
                "current_location": f"Reached {destination}",
                "progress_percent": 100,
                "vehicle": vehicle_id,
                "events": events,
                "stops": [
                    {"city": c, "status": "completed"}
                    for c in path
                ]
            })

        # --------------------------------
        # CURRENT SEGMENT
        # --------------------------------
        from_city, to_city = segments[index]

        # --------------------------------
        # PLANNED -> WAITING
        # --------------------------------
        for mid_id, _vid, _load, hub, status, _loading_time in load_rows:

            if (
                hub == to_city
                and status == "PLANNED"
                and phase >= ARRIVAL_PHASE
            ):

                cursor.execute("""
                    UPDATE MID_ROUTE_LOADS
                    SET STATUS='WAITING',
                        LOADING_TIME=%s
                    WHERE ID=%s
                      AND STATUS='PLANNED'
                """, (now, mid_id))

                conn.commit()

                events.append({
                    "type": "WAITING_LOAD",
                    "message": f"Vehicle waiting at {hub}"
                })

        # --------------------------------
        # LOCATION
        # --------------------------------
        waiting_hub = None

        for _mid_id, _vid, _load, hub, status, loading_time in load_rows:

            if (
                status == "WAITING"
                and loading_time
                and now < loading_time + timedelta(seconds=LOADING_DELAY_SECONDS)
            ):
                waiting_hub = hub
                break

        if waiting_hub:

            loc = f"Reached {waiting_hub}"
            status = "LOADING"

        elif phase < 0.2:

            loc = f"At {from_city}"
            status = "IN_TRANSIT"

        elif phase < 0.8:

            loc = f"Between {from_city} -> {to_city}"
            status = "IN_TRANSIT"

        elif phase < ARRIVAL_PHASE:

            loc = f"Near {to_city}"
            status = "IN_TRANSIT"

        else:

            loc = f"Reached {to_city}"
            status = "IN_TRANSIT"

        # --------------------------------
        # VEHICLE LOCATION
        # --------------------------------
        cursor.execute("""
            UPDATE VEHICLES
            SET STATUS='IN_USE',
                CURRENT_LOCATION=%s
            WHERE VEHICLE_ID=%s
        """, (loc, vehicle_id))

        # --------------------------------
        # ORDER STATUS
        # --------------------------------
        cursor.execute("""
            UPDATE ORDERS
            SET ORDER_STATUS='IN_TRANSIT'
            WHERE ORDER_ID=%s
              AND ORDER_STATUS <> 'DELIVERED'
        """, (order_id,))

        conn.commit()

        active_stop_index = min(index, len(path)-1)

        return jsonify({
            "status": status,
            "current_location": loc,
            "progress_percent": round(progress * 100, 2),
            "vehicle": vehicle_id,
            "events": events,
            "stops": stops_for_path(path, active_stop_index)
        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        })

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()
 
@app.route('/get_coordinates_by_city')
def get_coordinates_by_city():
    city = request.args.get('city')
 
    conn = get_connection()
    cursor = conn.cursor()
 
    cursor.execute("""
        SELECT LATITUDE, LONGITUDE
        FROM LOCATIONS
        WHERE LOWER(CITY)=LOWER(%s)
    """, (city,))
 
    row = cursor.fetchone()
 
    return jsonify({
        "lat": float(row[0]),
        "lng": float(row[1])
    })
 
 
@app.route('/get_coordinates/<order_id>')
def get_coordinates(order_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
 
        # Get order cities
        cursor.execute("""
            SELECT SOURCE_LOCATION, DESTINATION_LOCATION
            FROM ORDERS WHERE ORDER_ID=%s
        """, (order_id,))
        order = cursor.fetchone()
 
        if not order:
            return jsonify({"error": "Order not found"})
 
        source, dest = order
 
        # 🔥 Case-insensitive match (VERY IMPORTANT)
        cursor.execute("""
            SELECT LATITUDE, LONGITUDE
            FROM LOCATIONS
            WHERE LOWER(CITY) = LOWER(%s)
        """, (source,))
        src = cursor.fetchone()
 
        cursor.execute("""
            SELECT LATITUDE, LONGITUDE
            FROM LOCATIONS
            WHERE LOWER(CITY) = LOWER(%s)
        """, (dest,))
        dst = cursor.fetchone()
 
        # 🔥 Handle missing locations
        if not src or not dst:
            return jsonify({"error": "Location not found in LOCATIONS table"})
 
        return jsonify({
            "source": [float(src[0]), float(src[1])],
            "destination": [float(dst[0]), float(dst[1])]
        })
 
    except Exception as e:
        return jsonify({"error": str(e)})
 
 
# ---------------------------
# ADD LOAD (MID ROUTE)
# ---------------------------
@app.route('/assign_mid_route/<order_id>', methods=['POST'])
def assign_mid_route(order_id):
 
    conn = get_connection()
    cursor = conn.cursor()
 
    try:
        load = int(request.json.get("load_quantity"))
 
        cursor.execute("""
            SELECT ROUTE_ID, START_TIME, VEHICLE_ASSIGN_TIME, VEHICLE_ID
            FROM DISPATCH
            WHERE ORDER_ID=%s
            ORDER BY CREATED_AT DESC
            LIMIT 1
        """, (order_id,))
        dispatch = cursor.fetchone()
 
        if not dispatch:
            return jsonify({"error": "Dispatch has not been scheduled"})
 
        route_id, _start_time, assign_time, dispatch_vehicle_id = dispatch
        now = datetime.now()
 
        if now < assign_time + timedelta(seconds=5):
            return jsonify({"error": "Vehicle has not started yet"})
 
        cursor.execute("""
            SELECT FROM_CITY, TO_CITY
            FROM ROUTE_SEGMENTS
            WHERE ROUTE_ID=%s
            ORDER BY SEQUENCE
        """, (route_id,))
        segs = cursor.fetchall()
        path = build_path(segs)
 
        if len(path) < 3:
            return jsonify({"error": "No intermediate hub available on this route"})
 
        load_rows = get_mid_route_loads(cursor, order_id)
        index, phase, _progress, _effective_elapsed = movement_state(assign_time, now, segs, load_rows)
 
        waiting_hub = None
        for _mid_id, _vid, _load, hub, status, loading_time in load_rows:
            if status == "WAITING" and loading_time and now < loading_time + timedelta(seconds=LOADING_DELAY_SECONDS):
                waiting_hub = hub
                break
 
        if waiting_hub and waiting_hub in path:
            first_candidate = path.index(waiting_hub) + 1
        elif index >= len(segs):
            return jsonify({"error": "Vehicle has already completed the route"})
        elif phase >= ARRIVAL_PHASE:
            first_candidate = index + 2
        else:
            first_candidate = index + 1
 
        active_pickups = {
            hub for _mid_id, _vid, _load, hub, status, _loading_time in load_rows
            if status in ("PLANNED", "WAITING")
        }
 
        pickup_hub = None
        for candidate_index in range(first_candidate, len(path) - 1):
            candidate = path[candidate_index]
            if candidate not in active_pickups:
                pickup_hub = candidate
                break
 
        if not pickup_hub:
            return jsonify({"error": "No upcoming intermediate hub available for this load"})
 
        if dispatch_vehicle_id:
            cursor.execute("""
                SELECT VEHICLE_ID, CAPACITY, CURRENT_LOAD
                FROM VEHICLES
                WHERE VEHICLE_ID=%s
                  AND STATUS IN ('IN_USE', 'RETURNING')
            """, (dispatch_vehicle_id,))
        else:
            cursor.execute("""
                SELECT VEHICLE_ID, CAPACITY, CURRENT_LOAD
                FROM VEHICLES
                WHERE STATUS='IN_USE'
                LIMIT 1
            """)
 
        vehicle = cursor.fetchone()
 
        if not vehicle:
            return jsonify({"error": "No vehicle running"})
 
        vid, cap, curr = vehicle
        curr = curr or 0
        pending_load = sum(
            mid_load for _mid_id, row_vid, mid_load, _hub, status, _loading_time in load_rows
            if row_vid == vid and status in ("PLANNED", "WAITING")
        )
 
        mid_id = "MID_" + str(uuid.uuid4())[:6]
        pickup_hub_row = find_hub_for_city(cursor, pickup_hub)
        if not pickup_hub_row:
            return jsonify({"error": f"No hub found for {pickup_hub}"})
 
        pickup_hub_id, pickup_hub_name = pickup_hub_row
        if not reserve_inventory(cursor, pickup_hub_id, load):
            return jsonify({"error": f"No inventory available at {pickup_hub}"})
 
        if curr + pending_load + load <= cap:
            cursor.execute("""
                INSERT INTO MID_ROUTE_LOADS
                (ID, ORDER_ID, VEHICLE_ID, LOAD, PICKUP_HUB, STATUS)
                VALUES (%s,%s,%s,%s,%s,'PLANNED')
            """, (mid_id, order_id, vid, load, pickup_hub))
            message = f"Load will be picked from upcoming hub: {pickup_hub}"
            result_status = "PLANNED"
            assigned_vehicle = vid
        else:
            new_vehicle = select_available_vehicle(cursor, pickup_hub_id, load)
            if not new_vehicle:
                cursor.execute("""
                    INSERT INTO MID_ROUTE_LOADS
                    (ID, ORDER_ID, VEHICLE_ID, LOAD, PICKUP_HUB, STATUS)
                    VALUES (%s,%s,%s,%s,%s,'QUEUED')
                """, (mid_id, order_id, None, load, pickup_hub))
                conn.commit()
                return jsonify({
                    "status": "QUEUED",
                    "message": f"No vehicle available at {pickup_hub}; load queued",
                    "pickup_hub": pickup_hub
                })
 
            new_vid, _new_cap, _new_curr, _new_remaining = new_vehicle
            mark_vehicle_in_use(cursor, new_vid, load, pickup_hub_name)
            cursor.execute("""
                INSERT INTO MID_ROUTE_LOADS
                (ID, ORDER_ID, VEHICLE_ID, LOAD, PICKUP_HUB, STATUS)
                VALUES (%s,%s,%s,%s,%s,'COMPLETED')
            """, (mid_id, order_id, new_vid, load, pickup_hub))
            message = f"Vehicle {new_vid} assigned from {pickup_hub_name}"
            result_status = "ASSIGNED"
            assigned_vehicle = new_vid
 
        conn.commit()
 
        return jsonify({
            "status": result_status,
            "message": message,
            "vehicle_id": assigned_vehicle,
            "pickup_hub": pickup_hub
        })
 
    except Exception as e:
        return jsonify({"error": str(e)})
 
    finally:
        cursor.close()
        conn.close()
 
# -------------------------------
# ROUTE ANALYZER (NEW)
# -------------------------------
@app.route('/get_locations')
def get_locations():
    conn = get_connection()
    cursor = conn.cursor()
 
    cursor.execute("SELECT DISTINCT CITY FROM LOCATIONS")
    locations = [r[0] for r in cursor.fetchall()]
 
    cursor.close()
    conn.close()
 
    return jsonify(locations)
 
#----------------------------------------------------------
 
#----------------------------------------------------------
@app.route('/analyze_route')
def analyze_route():
    try:
        source = request.args.get('source')
        destination = request.args.get('destination')
 
        conn = get_connection()
        cursor = conn.cursor()
 
        routes = []
 
        # -----------------------
        # 1️⃣ GET ROUTE FROM ROUTES TABLE
        # -----------------------
        cursor.execute("""
            SELECT ROUTE_ID, SOURCE_CITY, DESTINATION_CITY, DISTANCE, ESTIMATED_TIME
            FROM ROUTES
            WHERE LOWER(SOURCE_CITY)=LOWER(%s)
            AND LOWER(DESTINATION_CITY)=LOWER(%s)
        """, (source, destination))
 
        route_data = cursor.fetchone()
 
        if not route_data:
            return jsonify({
                "routes": [],
                "hubs": [],
                "distance": 0,
                "time": "N/A"
            })
 
        route_id, src, dest, distance, time = route_data
 
        routes.append({
            "type": "Best Route",
            "route": f"{src} → {dest}",
            "distance": distance,
            "time": time
        })
 
        # -----------------------
        # 2️⃣ GET FULL PATH FROM ROUTE_SEGMENTS
        # -----------------------
        cursor.execute("""
            SELECT FROM_CITY, TO_CITY
            FROM ROUTE_SEGMENTS
            WHERE ROUTE_ID=%s
            ORDER BY SEQUENCE
        """, (route_id,))
 
        segments = cursor.fetchall()
 
        # -----------------------
        # 3️⃣ EXTRACT ONLY INTERMEDIATE HUBS
        # -----------------------
        path = []
 
        for seg in segments:
            path.append(seg[0])
        if segments:
            path.append(segments[-1][1])
 
        # remove source & destination
        intermediate_cities = path[1:-1] if len(path) > 2 else []
 
        # remove duplicates but keep order
        intermediate_cities = list(dict.fromkeys(intermediate_cities))
 
        # -----------------------
        # 4️⃣ FETCH HUB DETAILS
        # -----------------------
        hubs = []
        seen_hubs = set()
 
        for city in intermediate_cities:
 
            cursor.execute("""
                SELECT
                    H.HUB_ID,
                    H.HUB_NAME,
                    H.CITY,
                    COALESCE(I.AVAILABLE_QUANTITY,0)
                FROM HUBS H
                LEFT JOIN INVENTORY I ON H.HUB_ID = I.HUB_ID
                WHERE LOWER(H.CITY)=LOWER(%s)
            """, (city,))
 
            for h in cursor.fetchall():
                hub_id, name, city_name, inventory = h
 
                if hub_id in seen_hubs:
                    continue
                seen_hubs.add(hub_id)
 
                # -----------------------
                # VEHICLE STATS
                # -----------------------
                cursor.execute("""
                    SELECT
                        COUNT(*) AS TOTAL,
                        SUM(CASE WHEN STATUS='AVAILABLE' THEN 1 ELSE 0 END),
                        SUM(CASE WHEN STATUS='INUSE' THEN 1 ELSE 0 END)
                    FROM VEHICLES
                    WHERE HUB_ID=%s
                """, (hub_id,))
 
                total, available, inuse = cursor.fetchone()
 
                hubs.append({
                    "name": name,
                    "city": city_name,
                    "inventory": inventory or 0,
                    "total_vehicles": total or 0,
                    "available_vehicles": available or 0,
                    "inuse_vehicles": inuse or 0
                })
 
        cursor.close()
        conn.close()
 
        return jsonify({
            "routes": routes,
            "hubs": hubs,
            "distance": distance,
            "time": time
        })
 
    except Exception as e:
        return jsonify({"error": str(e)})
# -------------------------------
 
# DASHBOARD DATA
# -------------------------------
@app.route('/dashboard_data')
def dashboard_data():
    conn = get_connection()
    cursor = conn.cursor()
 
    cursor.execute("SELECT COUNT(*) FROM ORDERS")
    total = cursor.fetchone()[0]
 
    status = {
        "PLACED": 0,
        "PROCESSING": 0,
        "READY_FOR_DISPATCH": 0,
        "IN_TRANSIT": 0,
        "DELIVERED": 0
    }
 
    cursor.execute("""
        SELECT ORDER_STATUS, COUNT(*)
        FROM ORDERS
        GROUP BY ORDER_STATUS
    """)
 
    for s, c in cursor.fetchall():
        if s in status:
            status[s] = c
 
    cursor.execute("""
        SELECT H.HUB_NAME, I.AVAILABLE_QUANTITY
        FROM HUBS H
        JOIN INVENTORY I ON H.HUB_ID = I.HUB_ID
    """)
 
    hubs = [{"hub": h, "inventory": q} for h, q in cursor.fetchall()]
 
    cursor.close()
    conn.close()
 
    return jsonify({
        "total": total,
        "status": status,
        "hubs": hubs
    })
 
 
# -------------------------------
# ALERTS
# -------------------------------
@app.route('/alerts')
def alerts():
    conn = get_connection()
    cursor = conn.cursor()
 
    alerts = []
 
    cursor.execute("""
        SELECT HUB_ID, AVAILABLE_QUANTITY
        FROM INVENTORY
        WHERE AVAILABLE_QUANTITY < 60
    """)
 
    for hub, qty in cursor.fetchall():
        alerts.append(f"⚠ Low inventory at {hub} ({qty})")
 
    cursor.execute("""
        SELECT ORDER_ID, LOAD_QUANTITY
        FROM ORDERS
        WHERE LOAD_QUANTITY > 70
    """)
 
    for oid, load in cursor.fetchall():
        alerts.append(f"⚠ High load order {oid} ({load} tons)")
 
    cursor.close()
    conn.close()
 
    return jsonify(alerts)
 
 
# -------------------------------
# ACTIVE ORDERS
# -------------------------------
# ACTIVE ORDERS
@app.route('/active_orders')
def active_orders():
 
    conn = get_connection()
    cursor = conn.cursor()
 
    cursor.execute("""
        SELECT
            ORDER_ID,
            SOURCE_LOCATION,
            DESTINATION_LOCATION,
            LOAD_QUANTITY,
            ORDER_STATUS
        FROM ORDERS
        ORDER BY CREATED_AT DESC
        LIMIT 5
    """)
 
    data = []
 
    for row in cursor.fetchall():
 
        order_id = row[0]
        base_load = row[3]
 
        # -------------------------------
        # EXTRA LOAD DETAILS
        # -------------------------------
        cursor.execute("""
            SELECT
                PICKUP_HUB,
                LOAD
            FROM MID_ROUTE_LOADS
            WHERE ORDER_ID=%s
        """, (order_id,))
 
        extra_rows = cursor.fetchall()
 
        total_extra_load = 0
        extra_hubs = []
 
        for hub, load in extra_rows:
 
            total_extra_load += load
 
            extra_hubs.append(f"{hub} (+{load})")
 
        # -------------------------------
        # DISPLAY FORMAT
        # -------------------------------
        if not extra_hubs:
            extra_load_hubs = "No Extra Load Added"
        else:
            extra_load_hubs = ", ".join(extra_hubs)
 
        # -------------------------------
        # TOTAL LOAD
        # -------------------------------
        total_load = base_load + total_extra_load
 
        data.append({
 
    # 1. ORDER
    "id": order_id,
 
    # 2. STATUS
    "status": row[4],
 
    # 3. ROUTE
    "source": row[1],
    "destination": row[2],
 
    # 4. LOAD DETAILS
    "base_load": base_load,
    "extra_load": total_extra_load,
 
    # 5. EXTRA LOAD HUBS
    "extra_load_hubs": extra_load_hubs,
 
    # 6. FINAL LOAD
    "total_reached": total_load
})
 
    cursor.close()
    conn.close()
 
    return jsonify(data)
 
 
# -------------------------------
# RUN
# -------------------------------
if __name__ == '__main__':
    app.run(debug=True)
 
