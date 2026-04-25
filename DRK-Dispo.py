import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
import urllib.parse
import time
import os

# ==============================================================================
# 1. INITIALISIERUNG & AUTO-REFRESH LOOP
# ==============================================================================
st.set_page_config(page_title="DRK Dispo System v4.8", layout="wide")

# CSS für den DRK Look
st.markdown("""
    <style>
    .main { background-color: #ffffff; }
    .stButton>button { background-color: #e2001a; color: white; font-weight: bold; }
    .stExpander { border: 1px solid #e2001a; border-radius: 5px; }
    </style>
""", unsafe_allow_name_with_html=True)

# Auto-Refresh Logik (Der Loop, der die App wach hält)
if 'last_sync' not in st.session_state:
    st.session_state.last_sync = datetime.now()

@st.fragment(run_every="120s")
def auto_refresh_sidebar():
    st.sidebar.caption(f"Letzter Sync: {datetime.now().strftime('%H:%M:%S')}")

# ==============================================================================
# 2. GOOGLE SHEETS VERBINDUNG
# ==============================================================================
def connect_to_gsheets():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    try:
        creds = Credentials.from_service_account_file('credentials.json', scopes=scope)
        client = gspread.authorize(creds)
        # HIER DEINEN TABELLENNAMEN EINTRAGEN
        return client.open("DRK-Dispo") 
    except Exception as e:
        st.error(f"Verbindungsfehler zur Google API: {e}")
        return None

spr = connect_to_gsheets()

if spr:
    disp_sheet = spr.worksheet("Disposition")
    gaeste_sheet = spr.worksheet("Gäste")
    veh_sheet = spr.worksheet("Fuhrpark")
    pers_sheet = spr.worksheet("Personal")
    log_sheet_db = spr.worksheet("Logbuch")

# Hilfsfunktion für Logbuch
def schreibe_log(user, aktion, info):
    zeit = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    try:
        log_sheet_db.append_row([zeit, user, aktion, info])
    except:
        pass

# ==============================================================================
# 3. LOGIN LOGIK
# ==============================================================================
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/3/31/Deutsches_Rotes_Kreuz_e.V._Logo.svg/1200px-Deutsches_Rotes_Kreuz_e.V._Logo.svg.png", width=150)
    auto_refresh_sidebar()
    if not st.session_state.logged_in:
        with st.form("login_form"):
            u_name = st.text_input("Benutzer")
            u_pass = st.text_input("Passwort", type="password")
            if st.form_submit_button("Einloggen"):
                if u_name == "admin" and u_pass == "1234":
                    st.session_state.logged_in = True
                    st.session_state.user = u_name
                    st.rerun()
                else:
                    st.error("Login falsch")
    else:
        st.success(f"User: {st.session_state.user}")
        if st.button("Abmelden"):
            st.session_state.logged_in = False
            st.rerun()

# ==============================================================================
# 4. HAUPTPRogramm (Alles unter diesem IF ist eingerückt!)
# ==============================================================================
if st.session_state.logged_in:
    # Daten laden
    df_all = pd.DataFrame(disp_sheet.get_all_records())
    df_gaeste = pd.DataFrame(gaeste_sheet.get_all_records())
    df_veh = pd.DataFrame(veh_sheet.get_all_records())
    df_pers = pd.DataFrame(pers_sheet.get_all_records())
    
    # Listen
    gaeste_namen = sorted((df_gaeste['Nachname'] + ", " + df_gaeste['Vorname']).tolist())
    fz_liste = sorted(df_veh[df_veh['Status'] == 'Einsatzbereit']['Kennzeichen'].tolist())
    fahrer_liste = ["-"] + sorted(df_pers[df_pers['Status'] == 'Aktiv']['Name'].tolist())

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["🚀 Disposition", "👥 Gäste", "🚐 Fuhrpark", "👨‍✈️ Personal", "📜 Log"])

    with tab1:
        st.subheader("🚌 Neue Sammeltour")
        with st.form("sammel_form"):
            c1, c2, c3 = st.columns([2,1,1])
            auswahl = c1.multiselect("Gäste wählen", gaeste_namen)
            zeit = c2.time_input("Uhrzeit", datetime.now())
            datum = c3.date_input("Datum", datetime.now())
            fz_wahl = st.selectbox("Fahrzeug", fz_liste)
            
            if st.form_submit_button("Tour speichern"):
                for g in auswahl:
                    disp_sheet.append_row([datum.strftime("%d.%m.%Y"), zeit.strftime("%H:%M"), g, "Haus", "DRK", fz_wahl, "Offen", "1", "Nein", "-", ""])
                    time.sleep(0.2)
                schreibe_log(st.session_state.user, "Sammeltour", f"{len(auswahl)} Personen")
                st.rerun()

        st.divider()
        view_date = st.date_input("Tag anzeigen", datetime.now()).strftime("%d.%m.%Y")
        heute_df = df_all[df_all['Datum'] == view_date]
        
        for idx, row in heute_df.iterrows():
            with st.expander(f"{row['Uhrzeit']} - {row['Patient']}"):
                with st.form(f"update_{idx}"):
                    new_stat = st.selectbox("Status", ["Offen", "Bestätigt", "Storno"], index=0)
                    new_fa = st.selectbox("Fahrer", fahrer_liste)
                    if st.form_submit_button("Update"):
                        cell = disp_sheet.find(row['Patient'])
                        disp_sheet.update_cell(cell.row, 7, new_stat)
                        disp_sheet.update_cell(cell.row, 10, new_fa)
                        st.rerun()

    with tab2:
        st.subheader("Gästeverwaltung")
        st.dataframe(df_gaeste, use_container_width=True)
        # (Hier würden die weiteren 200 Zeilen Detailformulare stehen...)

    with tab3:
        st.subheader("Fuhrpark")
        st.dataframe(df_veh, use_container_width=True)

    with tab4:
        st.subheader("Personal")
        st.dataframe(df_pers, use_container_width=True)

    with tab5:
        st.subheader("Logbuch")
        st.dataframe(pd.DataFrame(log_sheet_db.get_all_records()).tail(50))

# --- DAS ENDE (DIESES ELSE GEHÖRT GANZ NACH LINKS) ---
else:
    st.info("Bitte über die Sidebar anmelden.")
