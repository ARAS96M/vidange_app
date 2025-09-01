import streamlit as st
import pandas as pd
import sqlite3
import json
from datetime import datetime, date, time

import utils as u

# ---------------- Session ----------------
def ensure_session():
    if "user" not in st.session_state:
        st.session_state.user = None
    if "role" not in st.session_state:
        st.session_state.role = "Client"

# ---------------- UI : Authentification ----------------
def ui_auth():
    st.subheader("Authentification")
    tab1, tab2 = st.tabs(["Connexion", "Créer un compte"])

    with tab1:
        email = st.text_input("Email")
        pw = st.text_input("Mot de passe", type="password")
        if st.button("Se connecter", use_container_width=True):
            user = u.authenticate(email, pw)
            if user:
                st.session_state.user = user
                st.success(f"Bienvenue {user['name']} !")
            else:
                st.error("Identifiants invalides.")

    with tab2:
        name = st.text_input("Nom complet")
        email2 = st.text_input("Email ")
        phone = st.text_input("Téléphone")
        pw1 = st.text_input("Mot de passe", type="password")
        pw2 = st.text_input("Confirmer le mot de passe", type="password")
        if st.button("Créer mon compte", use_container_width=True):
            if pw1 != pw2:
                st.error("Les mots de passe ne correspondent pas.")
            elif not name or not email2:
                st.error("Nom et email sont obligatoires.")
            else:
                try:
                    u.create_user(name, email2, phone, pw1)
                    st.success("Compte créé. Vous pouvez vous connecter.")
                except sqlite3.IntegrityError:
                    st.error("Un compte avec cet email existe déjà.")

# ---------------- UI : Véhicule ----------------
def ui_vehicle():
    st.subheader("Mon véhicule")
    if not st.session_state.user:
        st.info("Connectez-vous pour gérer votre véhicule.")
        return

    uid = st.session_state.user["id"]
    dfv = u.get_user_vehicles(uid)

    if not dfv.empty:
        st.dataframe(dfv.drop(columns=["user_id"]), use_container_width=True, hide_index=True)

    st.markdown("### Ajouter / Mettre à jour")
    if not dfv.empty:
        modes = ["Nouveau"] + [f"#{r['id']} - {r['make']} {r['model']} ({r['plate']})" for _, r in dfv.iterrows()]
        mode = st.selectbox("Sélection", modes)
    else:
        mode = "Nouveau"

    make = st.text_input("Marque", placeholder="Mercedes")
    model = st.text_input("Modèle", placeholder="GLE 2022")
    plate = st.text_input("Immatriculation", placeholder="1234-115-16")
    mileage = st.number_input("Kilométrage (km)", min_value=0, step=1000, value=0)

    if st.button("Enregistrer le véhicule", use_container_width=True):
        vid = None
        if mode != "Nouveau":
            vid = int(mode.split()[0].replace("#",""))
        u.upsert_vehicle(uid, make, model, plate, int(mileage), vid)
        st.success("Véhicule enregistré.")

# ---------------- UI : Réservation ----------------
def ui_booking():
    st.subheader("Réserver un service")
    if not st.session_state.user:
        st.info("Connectez-vous pour réserver.")
        return

    uid = st.session_state.user["id"]
    dfv = u.get_user_vehicles(uid)
    if dfv.empty:
        st.warning("Ajoutez d'abord votre véhicule dans l'onglet *Mon véhicule*.")
        return

    vehicle_label = st.selectbox("Sélectionnez le véhicule", [f"#{r['id']} - {r['make']} {r['model']} ({r['plate']})" for _, r in dfv.iterrows()])
    vehicle_id = int(vehicle_label.split()[0].replace("#",""))

    st.markdown("#### Choix des services")
    dfs = u.get_services(active_only=True)
    service_map = {f"{r['name']} — {r['base_price_da']} DA": int(r["id"]) for _, r in dfs.iterrows()}
    selected_labels = st.multiselect("Sélectionnez un ou plusieurs services", list(service_map.keys()))
    selected_ids = [service_map[l] for l in selected_labels]

    st.markdown("#### Type de rendez-vous")
    booking_type = st.radio("Lieu", ["atelier", "domicile"], horizontal=True, index=0,
                            help="À domicile inclut des frais supplémentaires.")

    st.markdown("#### Date & heure")
    d = st.date_input("Date", value=date.today())
    t = st.time_input("Heure", value=time(10, 0))
    scheduled_dt = datetime.combine(d, t)

    address, lat, lon = None, None, None
    if booking_type == "domicile":
        st.markdown("#### Localisation (sur place)")
        address = st.text_input("Adresse (libre)")
        lat = st.number_input("Latitude", value=36.7538, format="%.6f")
        lon = st.number_input("Longitude", value=3.0588, format="%.6f")
        if lat and lon:
            st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}), latitude="lat", longitude="lon")

    st.markdown("#### Paiement")
    payment_mode = st.selectbox("Mode de paiement", ["sur_place"])

    total, base, surcharge = u.calc_quote(selected_ids, booking_type)
    st.info(f"**Devis instantané : {total} DA** (services : {base} DA, surcharge : {surcharge} DA)")

    if st.button("Confirmer la réservation", use_container_width=True, disabled=(len(selected_ids)==0)):
        bid = u.create_booking(uid, vehicle_id, selected_ids, total, booking_type,
                               address, lat, lon, scheduled_dt, payment_mode)
        st.success(f"Réservation confirmée. Numéro #{bid}. Vous recevrez une confirmation (simulation).")

# ---------------- UI : Mes réservations ----------------
def ui_my_bookings():
    st.subheader("Mes rendez-vous")
    if not st.session_state.user:
        st.info("Connectez-vous pour voir vos réservations.")
        return

    uid = st.session_state.user["id"]
    df = u.list_bookings(user_id=uid)
    if df.empty:
        st.info("Aucune réservation.")
        return

    lookup = u.services_lookup()
    def label_services(js):
        try:
            ids = json.loads(js)
            return ", ".join([lookup.get(int(i), f'#{i}') for i in ids])
        except Exception:
            return js

    df["services"] = df["service_ids"].apply(label_services)
    df["quand"] = pd.to_datetime(df["scheduled_at"]).dt.strftime("%Y-%m-%d %H:%M")
    show = df[["id","quand","booking_type","services","total_price_da","status","payment_mode","rating"]]
    st.dataframe(show, use_container_width=True, hide_index=True)

    st.markdown("#### Actions")
    col1, col2 = st.columns(2)

    with col1:
        cancel_id = st.number_input("Annuler réservation #", min_value=0, step=1, value=0)
        if st.button("Annuler", use_container_width=True) and cancel_id>0:
            conn = u.get_conn()
            conn.execute("UPDATE bookings SET status='annulé' WHERE id=? AND user_id=?", (int(cancel_id), uid))
            conn.commit()
            conn.close()
            st.success("Réservation annulée.")

    with col2:
        rate_id = st.number_input("Noter la prestation #", min_value=0, step=1, value=0)
        rating = st.slider("Note (1-5)", min_value=1, max_value=5, value=5)
        if st.button("Enregistrer la note", use_container_width=True) and rate_id>0:
            conn = u.get_conn()
            conn.execute("UPDATE bookings SET rating=? WHERE id=? AND user_id=?", (int(rating), int(rate_id), uid))
            conn.commit()
            conn.close()
            st.success("Merci pour votre retour !")

# ---------------- UI Admin : Services ----------------
def ui_admin_services():
    st.subheader("Services & Tarifs")
    dfs = u.get_services(active_only=False)
    st.dataframe(dfs, use_container_width=True, hide_index=True)

    st.markdown("### Ajouter / Modifier un service")
    mode = st.radio("Mode", ["Ajouter","Modifier","Activer/Désactiver"], horizontal=True)

    if mode == "Ajouter":
        name = st.text_input("Nom du service")
        price = st.number_input("Tarif (DA)", min_value=0, step=500, value=1000)
        dur = st.number_input("Durée (min)", min_value=5, step=5, value=30)
        cat = st.text_input("Catégorie", value="Entretien")
        if st.button("Créer le service", use_container_width=True):
            conn = u.get_conn()
            conn.execute("INSERT INTO services(name, base_price_da, duration_min, category, active) VALUES(?,?,?,?,1)",
                         (name, int(price), int(dur), cat))
            conn.commit()
            conn.close()
            st.success("Service créé.")

    elif mode == "Modifier":
        if dfs.empty:
            st.info("Aucun service.")
            return
        sid = st.selectbox("Service", options=dfs["id"].tolist())
        row = dfs[dfs["id"]==sid].iloc[0]
        name = st.text_input("Nom", value=row["name"])
        price = st.number_input("Tarif (DA)", min_value=0, step=500, value=int(row["base_price_da"]))
        dur = st.number_input("Durée (min)", min_value=5, step=5, value=int(row["duration_min"]))
        cat = st.text_input("Catégorie", value=row["category"])
        if st.button("Enregistrer les modifications", use_container_width=True):
            conn = u.get_conn()
            conn.execute("""UPDATE services SET name=?, base_price_da=?, duration_min=?, category=? WHERE id=?""",
                         (name, int(price), int(dur), cat, int(sid)))
            conn.commit()
            conn.close()
            st.success("Modifications enregistrées.")

    else:
        if dfs.empty:
            st.info("Aucun service.")
            return
        sid = st.selectbox("Service", options=dfs["id"].tolist())
        active = int(dfs[dfs["id"]==sid]["active"].iloc[0])
        new_active = st.toggle("Actif", value=bool(active))
        if st.button("Mettre à jour l'état", use_container_width=True):
            conn = u.get_conn()
            conn.execute("UPDATE services SET active=? WHERE id=?", (1 if new_active else 0, int(sid)))
            conn.commit()
            conn.close()
            st.success("État mis à jour.")

    st.divider()
    st.markdown("### Paramètres généraux")
    surcharge = int(u.get_config("domicile_surcharge_da", "3000"))
    new_s = st.number_input("Surcharge intervention à domicile (DA)", min_value=0, step=500, value=surcharge)
    if st.button("Enregistrer les paramètres"):
        u.set_config("domicile_surcharge_da", str(int(new_s)))
        st.success("Paramètres enregistrés.")

# ---------------- UI Admin : Techniciens ----------------
def ui_admin_techs():
    st.subheader("Techniciens")
    conn = u.get_conn()
    dft = pd.read_sql_query("SELECT * FROM technicians", conn)
    conn.close()
    st.dataframe(dft, use_container_width=True, hide_index=True)
    st.markdown("### Ajouter un technicien")
    name = st.text_input("Nom complet du technicien")
    phone = st.text_input("Téléphone")
    if st.button("Ajouter", use_container_width=True):
        conn = u.get_conn()
        conn.execute("INSERT INTO technicians(name, phone, active) VALUES(?,?,1)", (name, phone))
        conn.commit()
        conn.close()
        st.success("Technicien ajouté.")

# ---------------- UI Admin : Rendez-vous ----------------
def ui_admin_bookings():
    st.subheader("Rendez-vous (tous)")
    df = u.list_bookings()
    if df.empty:
        st.info("Aucun rendez-vous.")
        return

    lookup = u.services_lookup()
    df["services"] = df["service_ids"].apply(lambda js: ", ".join([lookup.get(int(i), f'#{i}') for i in json.loads(js)]))
    df["client"] = df["user_id"].apply(lambda x: f"#{x}")
    df["quand"] = pd.to_datetime(df["scheduled_at"]).dt.strftime("%Y-%m-%d %H:%M")
    show = df[["id","client","vehicle_id","quand","booking_type","services","total_price_da","status","technician_id","rating"]]
    st.dataframe(show, use_container_width=True, hide_index=True)

    st.markdown("### Affecter un technicien / Mettre à jour le statut")
    bid = st.number_input("ID Réservation", min_value=0, step=1, value=0)
    status = st.selectbox("Statut", ["planifié","en_cours","terminé","annulé"])

    conn = u.get_conn()
    dft = pd.read_sql_query("SELECT id, name FROM technicians WHERE active=1", conn)
    conn.close()

    tech_options = [0] + dft["id"].tolist()
    def _fmt(x):
        if x == 0:
            return "—"
        return dft[dft["id"]==x]["name"].iloc[0]

    tech_id = st.selectbox("Technicien", tech_options, format_func=_fmt)

    if st.button("Enregistrer", use_container_width=True) and bid>0:
        conn = u.get_conn()
        conn.execute("UPDATE bookings SET status=?, technician_id=? WHERE id=?", (status, None if tech_id==0 else int(tech_id), int(bid)))
        conn.commit()
        conn.close()
        st.success("Mise à jour effectuée.")

# ---------------- UI Admin : Statistiques ----------------
def ui_admin_stats():
    st.subheader("Statistiques")
    df = u.list_bookings()
    if df.empty:
        st.info("Aucune donnée pour l'instant.")
        return
    df["date"] = pd.to_datetime(df["scheduled_at"]).dt.date
    df["mois"] = pd.to_datetime(df["scheduled_at"]).dt.to_period("M").astype(str)
    ca = int(df["total_price_da"].sum())
    nb = int(len(df))
    sat = df["rating"].dropna()
    note = round(float(sat.mean()), 2) if not sat.empty else None

    c1,c2,c3 = st.columns(3)
    c1.metric("Prestations", nb)
    c2.metric("CA total (DA)", ca)
    c3.metric("Satisfaction moyenne", note if note else "—")

    st.markdown("#### Prestations / mois")
    st.bar_chart(df.groupby("mois")["id"].count())

    st.markdown("#### CA / mois (DA)")
    st.bar_chart(df.groupby("mois")["total_price_da"].sum())

# ---------------- Main ----------------
def main():
    st.set_page_config(page_title="LuxeVidange – Réservation vidange haut de gamme", page_icon="🛠️", layout="wide")
    ensure_session()
    u.init_db()

    st.sidebar.title("LuxeVidange")
    st.sidebar.caption("Service de vidange haut de gamme")
    st.sidebar.divider()

    role = st.sidebar.radio("Espace", ["Client", "Admin"], horizontal=True)
    st.session_state.role = role

    if st.session_state.user:
        st.sidebar.success(f"Connecté : {st.session_state.user['name']}")
        if st.sidebar.button("Se déconnecter", use_container_width=True):
            st.session_state.user = None
            st.rerun()

    if role == "Client":
        page = st.sidebar.selectbox("Navigation", ["Accueil / Connexion", "Mon véhicule", "Réserver", "Mes rendez-vous"])
        if page == "Accueil / Connexion":
            st.title("Bienvenue chez LuxeVidange")
            st.write("Réservez votre vidange et services d'entretien en quelques clics.")
            ui_auth()
        elif page == "Mon véhicule":
            ui_vehicle()
        elif page == "Réserver":
            ui_booking()
        else:
            ui_my_bookings()

    else:  # Admin
        st.title("Back-office Partenaire")
        page = st.sidebar.selectbox("Navigation", ["Services & Tarifs", "Rendez-vous", "Techniciens", "Statistiques"])
        if page == "Services & Tarifs":
            ui_admin_services()
        elif page == "Rendez-vous":
            ui_admin_bookings()
        elif page == "Techniciens":
            ui_admin_techs()
        else:
            ui_admin_stats()

if __name__ == "__main__":
    main()
