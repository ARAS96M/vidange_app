import sqlite3
import hashlib
import json
from datetime import datetime
import pandas as pd

DB_PATH = "vidange.db"

# ---------------- Base de données ----------------
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # Utilisateurs
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)

    # Véhicules
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vehicles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            make TEXT NOT NULL,
            model TEXT NOT NULL,
            plate TEXT NOT NULL,
            mileage INTEGER,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
    """)

    # Catalogue de services
    cur.execute("""
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            base_price_da INTEGER NOT NULL,
            duration_min INTEGER DEFAULT 45,
            category TEXT DEFAULT 'Entretien',
            active INTEGER DEFAULT 1
        );
    """)

    # Paramètres
    cur.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)

    # Techniciens
    cur.execute("""
        CREATE TABLE IF NOT EXISTS technicians (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            active INTEGER DEFAULT 1
        );
    """)

    # Réservations
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            vehicle_id INTEGER NOT NULL,
            service_ids TEXT NOT NULL,         -- JSON list of service IDs
            total_price_da INTEGER NOT NULL,
            booking_type TEXT NOT NULL,        -- 'atelier' | 'domicile'
            address TEXT,
            latitude REAL,
            longitude REAL,
            scheduled_at TEXT NOT NULL,
            status TEXT DEFAULT 'planifié',     -- planifié | en_cours | terminé | annulé
            technician_id INTEGER,
            payment_mode TEXT DEFAULT 'sur_place',
            rating INTEGER,                     -- 1-5
            notes TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE,
            FOREIGN KEY(technician_id) REFERENCES technicians(id) ON DELETE SET NULL
        );
    """)

    conn.commit()

    # Seed config si vide
    cur.execute("SELECT COUNT(*) FROM config;")
    if cur.fetchone()[0] == 0:
        cur.executemany("INSERT INTO config(key,value) VALUES(?,?)", [
            ("domicile_surcharge_da", "3000"),
            ("brand", "LuxeVidange")
        ])

    # Seed services si vide
    cur.execute("SELECT COUNT(*) FROM services;")
    if cur.fetchone()[0] == 0:
        cur.executemany(
            "INSERT INTO services(name, base_price_da, duration_min, category, active) VALUES(?,?,?,?,1)",
            [
                ("Vidange simple", 12000, 45, "Vidange"),
                ("Filtre huile", 4000, 15, "Filtres"),
                ("Filtre air", 3000, 15, "Filtres"),
                ("Filtre carburant", 5000, 25, "Filtres"),
                ("Filtre habitacle", 3500, 20, "Filtres"),
                ("Lavage extérieur", 1500, 20, "Confort"),
                ("Check-up rapide", 2000, 20, "Diagnostic"),
            ]
        )

    conn.commit()
    conn.close()

# ---------------- Paramètres & Services ----------------
def get_config(key: str, default=None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM config WHERE key=?", (key,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else default

def set_config(key: str, value: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO config(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value;",
        (key, value)
    )
    conn.commit()
    conn.close()

def get_services(active_only=True) -> pd.DataFrame:
    conn = get_conn()
    q = "SELECT id, name, base_price_da, duration_min, category, active FROM services"
    if active_only:
        q += " WHERE active=1"
    df = pd.read_sql_query(q, conn)
    conn.close()
    return df

def services_lookup() -> dict:
    df = get_services(active_only=False)
    return {int(r.id): f"{r.name} ({r.base_price_da} DA)" for _, r in df.iterrows()}

def get_service_names(ids):
    lookup = services_lookup()
    return [lookup.get(int(i), f"#{i}") for i in ids]

# ---------------- Utilisateurs & Véhicules ----------------
def get_user_by_email(email: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, email, phone, password_hash FROM users WHERE email=?", (email,))
    row = cur.fetchone()
    conn.close()
    return row

def create_user(name, email, phone, password):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""INSERT INTO users(name, email, phone, password_hash, created_at)
                   VALUES(?,?,?,?,?)""",
                (name, email, phone, hash_pw(password), datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def authenticate(email, password):
    row = get_user_by_email(email)
    if not row:
        return None
    uid, name, em, phone, pw_hash = row
    if pw_hash == hash_pw(password):
        return {"id": uid, "name": name, "email": em, "phone": phone}
    return None

def get_user_vehicles(user_id) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM vehicles WHERE user_id=?", conn, params=(user_id,))
    conn.close()
    return df

def upsert_vehicle(user_id, make, model, plate, mileage, vehicle_id=None):
    conn = get_conn()
    cur = conn.cursor()
    if vehicle_id:
        cur.execute("""UPDATE vehicles SET make=?, model=?, plate=?, mileage=?
                       WHERE id=? AND user_id=?""", (make, model, plate, mileage, vehicle_id, user_id))
    else:
        cur.execute("""INSERT INTO vehicles(user_id, make, model, plate, mileage)
                       VALUES(?,?,?,?,?)""", (user_id, make, model, plate, mileage))
    conn.commit()
    conn.close()

# ---------------- Devis & Réservations ----------------
def calc_quote(selected_service_ids, booking_type):
    df = get_services(active_only=True)
    df_sel = df[df["id"].isin(selected_service_ids)]
    base = int(df_sel["base_price_da"].sum()) if not df_sel.empty else 0
    surcharge = int(get_config("domicile_surcharge_da", "3000")) if booking_type == "domicile" else 0
    return base + surcharge, base, surcharge

def create_booking(user_id, vehicle_id, service_ids, total_price_da, booking_type,
                   address, latitude, longitude, scheduled_dt, payment_mode="sur_place"):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""INSERT INTO bookings(
            user_id, vehicle_id, service_ids, total_price_da, booking_type,
            address, latitude, longitude, scheduled_at, status, payment_mode, created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, vehicle_id, json.dumps(service_ids), total_price_da, booking_type,
         address, latitude, longitude, scheduled_dt.isoformat(), "planifié", payment_mode, datetime.utcnow().isoformat())
    )
    conn.commit()
    bid = cur.lastrowid
    conn.close()
    return bid

def list_bookings(user_id=None) -> pd.DataFrame:
    conn = get_conn()
    if user_id:
        df = pd.read_sql_query("SELECT * FROM bookings WHERE user_id=? ORDER BY datetime(created_at) DESC", conn, params=(user_id,))
    else:
        df = pd.read_sql_query("SELECT * FROM bookings ORDER BY datetime(created_at) DESC", conn)
    conn.close()
    return df
