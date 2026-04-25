import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, date

# 1. Seiteneinstellungen
st.set_page_config(page_title="DRK Zentrale", page_icon="🚑", layout="wide")

# --- LOGIN LOGIK ---
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

def check_login():
    if st.session_state.password == "drk112": # <-- Hier dein gewünschtes Passwort ändern
        st.session_state.logged_in = True
    else:
        st.error("Falsches Passwort!")

# --- FALLS NICHT EINGELOGGT: NUR LOGIN-MASKE ZEIGEN ---
if not st.session_state.logged_in:
    st.title("🚑 DRK Zentrale - Login")
    st.text_input("Bitte Passwort eingeben", type="password", key="password", on_change=check_login)
    st.stop() # Beendet das Programm hier, damit nichts geladen wird

# --- AB HIER: CODE FÜR EINGELOGGTE NUTZER ---

@st.cache_resource
def get_gspread_client():
    try:
        info = dict(st.secrets["gcp_service_account"])
        if "private_key" in info:
            info["private_key"] = info["private_key"].replace("\\n", "\n").strip()
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(info, scopes=scope)
        return gspread.authorize(creds)
    except Exception:
        return None

client = get_gspread_client()

# Titel erscheint erst NACH dem Login
st.title("🚑 DRK Einsatzplanung")
st.markdown(f"Angemeldet am: {date.today().strftime('%d.%m.%Y')}")
st.markdown("---")

if client:
    try:
        sh = client.open_by_key("1-UDDHPbmgKzPLtQCktAlqaHdfLOD6IjtGflmzw5yILU")
        
        # Tabs definieren
        tab_dispo, tab_fuhrpark, tab_personal = st.tabs([
            "📅 Disposition", 
            "🚐 Fuhrpark", 
            "👤 Personal"
        ])

        with tab_dispo:
            st.subheader("Aktuelle Fahrgäste")
            # Wir laden das erste Blatt (Index 0)
            data = sh.get_worksheet(0).get_all_records()
            if data:
                st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
            else:
                st.info("Keine Einträge in der Disposition.")

        with tab_fuhrpark:
            st.subheader("Fahrzeugstatus")
            try:
                data_veh = sh.worksheet("Fahrzeuge").get_all_records()
                st.dataframe(pd.DataFrame(data_veh), use_container_width=True, hide_index=True)
            except:
                st.info("Blatt 'Fahrzeuge' wurde nicht im Google Sheet gefunden.")

        with tab_personal:
            st.subheader("Personalübersicht")
            try:
                data_pers = sh.worksheet("Personal").get_all_records()
                st.dataframe(pd.DataFrame(data_pers), use_container_width=True, hide_index=True)
            except:
                st.info("Blatt 'Personal' wurde nicht im Google Sheet gefunden.")

    except Exception as e:
        st.error("Fehler beim Laden der Google-Daten.")
else:
    st.error("Verbindung zu Google fehlgeschlagen.")

# WICHTIG: Hier darf kein Code mehr kommen! Die Datei muss hier enden.

# Verbindung sofort beim Start aufbauen
try:
    sh = client.open("DRK-Dispo")
    heute = date.today()
    
    # Hier definieren wir die "Blätter" EINMALIG für das gesamte Skript
    disp_sheet = sh.worksheet("Disposition")
    veh_sheet = sh.worksheet("Fahrzeuge")
    pers_sheet = sh.worksheet("Personal")
    gaeste_sheet = sh.worksheet("Gaeste")
    log_sheet_db = sh.worksheet("Logbuch")
except Exception as e:
    st.error(f"Kritischer Fehler: Google Sheet konnte nicht geladen werden: {e}")
    st.stop()

# --- 2. HILFSFUNKTIONEN ---
def schreibe_log(nutzer, aktion, details):
    try:
        zeit = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        log_sheet_db.append_row([zeit, nutzer, aktion, details])
    except: pass

def whatsapp_einzel_tour(nummer, name, row, kennzeichen):
    ziel = str(row['Ziel'])
    maps_link = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(ziel)}"
    status_link = f"https://deine-app.streamlit.app/?fz={urllib.parse.quote(kennzeichen)}"
    text = f"🚑 *DRK Tour-Info*\n\nHallo {name},\n⏰ *{row['Uhrzeit']} Uhr*\n👤 Gast: {row['Patient']}\n🏁 Nach: {ziel}\n\n🗺️ *Navi:* {maps_link}\n✅ *Status:* {status_link}"
    return f"https://wa.me/{nummer}?text={urllib.parse.quote(text)}"
def whatsapp_sammel_tour(nummer, name, fahrzeug_df, kennzeichen):
    # fahrzeug_df enthält alle Zeilen der heutigen Touren für dieses KFZ
    zeit = fahrzeug_df.iloc[0]['Uhrzeit']
    gast_liste = ""
    for _, r in fahrzeug_df.iterrows():
        gast_liste += f"• {r['Patient']} (Ziel: {r['Ziel']})\n"
    
    status_link = f"https://deine-app.streamlit.app/?fz={urllib.parse.quote(kennzeichen)}"
    
    text = (f"🚑 *DRK Sammeltour-Info*\n\n"
            f"Hallo {name},\n"
            f"⏰ Abfahrt: *{zeit} Uhr*\n"
            f"🚐 Fahrzeug: *{kennzeichen}*\n\n"
            f"👥 *Fahrgäste:*\n{gast_liste}\n"
            f"✅ *Status melden:* {status_link}")
            
    return f"https://wa.me/{nummer}?text={urllib.parse.quote(text)}"

# --- 3. FAHRER-MODUS (Link-Abfrage) ---
params = st.query_params
if "fz" in params:
    kfz_kennzeichen = params["fz"]
    st.title(f"🚑 Status-Meldung für {kfz_kennzeichen}")
    
    if st.button("✅ Tour beendet / Fahrzeug FREI", use_container_width=True):
        try:
            cell = veh_sheet.find(kfz_kennzeichen)
            veh_sheet.update_cell(cell.row, 5, "Aktiv")
            veh_sheet.update_cell(cell.row, 7, "")
            veh_sheet.update_cell(cell.row, 8, datetime.now().strftime("%H:%M"))
            st.success("Danke! Fahrzeug ist wieder FREI.")
            st.balloons()
        except:
            st.error("Fahrzeug nicht gefunden.")

    st.subheader("⚠️ Mangel melden")
    m_input = st.text_area("Beschreibung...")
    if st.button("Absenden"):
        if m_input:
            cell = veh_sheet.find(kfz_kennzeichen)
            veh_sheet.update_cell(cell.row, 6, m_input)
            st.warning("Mangel gemeldet.")
    st.stop() # Beendet hier für Fahrer

# --- 4. DISPO-ANSICHT (UI SETUP) ---
st.set_page_config(page_title="DRK Zentrale", page_icon="🚑", layout="wide")

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.title("🚑 DRK-Dispo Login")
    with st.form("login"):
        u = st.text_input("Benutzer")
        p = st.text_input("Passwort", type="password")
        if st.form_submit_button("Anmelden"):
            st.session_state.logged_in, st.session_state.user = True, u
            st.rerun()
else:
    try:
        # 1. DATEN AUS GOOGLE SHEETS LADEN
        
    
        sh = client.open("DRK-Dispo")
        heute_dt = date.today()
        
        # In DataFrames laden
        df_all = pd.DataFrame(disp_sheet.get_all_records())
        veh_df = pd.DataFrame(veh_sheet.get_all_records())
        data = pers_sheet.get_all_records()
        pers_df = pd.DataFrame(data)
        if 'Abwesend_Von' in pers_df.columns:
            pers_df['Abwesend_Von'] = pers_df['Abwesend_Von'].astype(str).str.strip()
        if 'Abwesend_Bis' in pers_df.columns:
            pers_df['Abwesend_Bis'] = pers_df['Abwesend_Bis'].astype(str).str.strip()
        if 'Status' not in pers_df.columns:
            pers_df['Status'] = "Aktiv"
        gaeste_df = pd.DataFrame(gaeste_sheet.get_all_records())
        pers_df.columns = [c.strip() for c in pers_df.columns]
        
        # Sicherheits-Check für leere Sheets
        if gaeste_df.empty:
            gaeste_df = pd.DataFrame(columns=['Nachname', 'Vorname', 'Strasse', 'Hausnummer', 'PLZ', 'Ort', 'Stadtteil', 'Etage', 'Hilfsmittel'])
        
        # --- 2. & 3. PERSONAL- & GÄSTE-LOGIK (KOMPAKT) ---
        verfuegbar_pers = ["-"]
        heute_dt = date.today()
        
        if not pers_df.empty:
            # Wir bauen die Namen einmal sauber im DataFrame
            pers_df['Name'] = pers_df['Vorname'].astype(str) + " " + pers_df['Nachname'].astype(str)
            
            for _, p in pers_df.iterrows():
                # Wir nutzen p['Name'], das wir eine Zeile drüber gebaut haben
                aktueller_name = str(p['Name']).split('\n')[0].strip()
                p_status = str(p.get('Status', 'Aktiv')).strip()
                p_von = str(p.get('Abwesend_Von', '')).strip()
                p_bis = str(p.get('Abwesend_Bis', '')).strip()

                ist_da = True
                # Urlaubs-Prüfung
                if p_status != "Aktiv":
                    if p_von and p_bis:
                        try:
                            start_dat = datetime.strptime(p_von, "%d.%m.%Y").date()
                            ende_dat = datetime.strptime(p_bis, "%d.%m.%Y").date()
                            if start_dat <= heute_dt <= ende_dat:
                                ist_da = False
                        except:
                            ist_da = False # Sicherheit bei falschem Datum
                    else:
                        ist_da = False # Status nicht Aktiv aber kein Datum -> weg
                
                if ist_da:
                    verfuegbar_pers.append(aktueller_name)

        # Die finale Liste für deine Dropdowns
        namen_liste = verfuegbar_pers
        
        # Gäste-Dropdown
        if not gaeste_df.empty:
            gaeste_namen = ["-"] + (gaeste_df['Nachname'].astype(str) + ", " + gaeste_df['Vorname'].astype(str)).tolist()
        else:
            gaeste_namen = ["-"]
            
        # Fahrzeug-Dropdown
        verfuegbar_fz = ["-"]
        if not veh_df.empty:
            verfuegbar_fz += veh_df[veh_df['Status'].str.strip() == "Einsatzbereit"]['Kennzeichen'].tolist()

        # --- SIDEBAR (STATUS, TÜV & MÄNGEL) ---
        with st.sidebar:
            st.title("🚑 Zentrale")
            st.write(f"Nutzer: **{st.session_state.user}**")
            st.write("---")
            st.subheader("👨‍✈️ Personal-Status heute")
            
            fehlende_liste = []
            
            # Sicherheitscheck: Existieren die notwendigen Spalten überhaupt?
            # Wir definieren eine Liste mit Spalten, die wir erwarten
            erwartete_spalten = ['Vorname', 'Nachname', 'Status', 'Abwesend_Von', 'Abwesend_Bis']
            for col in erwartete_spalten:
                if col not in pers_df.columns:
                    pers_df[col] = ""
            # Wir prüfen, welche davon wirklich im DataFrame sind
            vorhandene_spalten = pers_df.columns.tolist()
            
            if not pers_df.empty:
                for _, p in pers_df.iterrows():
                    # Wir nutzen .get() mit einem Standardwert, damit es bei fehlender Spalte nicht kracht
                    p_status = str(p.get('Status', 'Aktiv')).split('\n')[0].strip()
                    v = str(p.get('Abwesend_Von', '')).split('\n')[0].strip()
                    b = str(p.get('Abwesend_Bis', '')).split('\n')[0].strip()
                    
                    # Nur prüfen, wenn Status nicht Aktiv ist UND Daten da sind
                    if p_status != "Aktiv" and v and b and v != "nan" and b != "nan":
                        try:
                            s_dat = datetime.strptime(v, "%d.%m.%Y").date()
                            e_dat = datetime.strptime(b, "%d.%m.%Y").date()
                            
                            if s_dat <= heute_dt <= e_dat:
                                vn = str(p.get('Vorname', 'Unbekannt')).split('\n')[0].strip()
                                nn = str(p.get('Nachname', '')).split('\n')[0].strip()
                                s_name = f"{vn} {nn}".strip()
                                
                                if s_name:
                                    fehlende_liste.append(f"{s_name} ({p_status})")
                        except:
                            pass

            # Anzeige
            if fehlende_liste:
                for entry in fehlende_liste:
                    st.error(f"❌ {entry}")
            else:
                st.success("✅ Alle einsatzbereit")
            
            st.write("---")

            # --- 2. TÜV & MÄNGEL CHECK ---
            tuev_liste = []
            mangel_liste_side = []
            
            if not veh_df.empty:
                for _, fz in veh_df.iterrows():
                    # TÜV Check (innerhalb der nächsten 28 Tage)
                    try:
                        t_str = str(fz.get('TÜV', '')).strip()
                        if t_str:
                            t_dat = datetime.strptime(t_str, "%d.%m.%Y").date()
                            if t_dat <= heute_dt + timedelta(days=28):
                                tuev_liste.append(f"{fz.get('Kennzeichen', 'Unbekannt')} ({t_str})")
                    except:
                        pass
                    
                    # Mängel Check
                    m_str = str(fz.get('Mängel', '')).strip()
                    if m_str and m_str.lower() not in ["keine", "-", "none", "nan", "ok"]:
                        mangel_liste_side.append(f"**{fz.get('Kennzeichen', 'Fahrzeug')}:** {m_str}")
            
            if tuev_liste:
                st.error("📅 TÜV FÄLLIG:")
                for t in tuev_liste:
                    st.warning(t)
            
            if mangel_liste_side:
                st.error("🛠️ OFFENE MÄNGEL:")
                for m in mangel_liste_side:
                    st.info(m)
            
            st.write("---")
            
            # --- 3. LOGOUT ---
            if st.button("Abmelden"):
                st.session_state.logged_in = False
                st.rerun()

        # --- HAUPT-TABS ---
        tab_dispo, tab_woche, tab_gaeste, tab_fuhrpark, tab_personal, tab_log = st.tabs([
            "📅 Touren Heute", 
            "🗓️ Wochenplan", 
            "👥 Gäste", 
            "🛠️ Fuhrpark", 
            "👤 Personal",  # Neu hinzugefügt
            "📜 Logbuch"
        ])

        # --- TAB 1: DISPOSITION ---
        # --- TAB 1: DISPOSITION ---
        with tab_dispo:
            st.header(f"📅 Tagesdisposition für heute, den {heute.strftime('%d.%m.%Y')}")

            # --- SÄULE 3: TAGES-RESET (Automatisches Aufräumen) ---
            heute_str = heute.strftime("%d.%m.%Y")
            # Wir prüfen gegen das Personal-DF, ob heute schon gearbeitet wurde
            if not pers_df.empty:
                letztes_datum = pers_df['Letztes_Update'].max() if 'Letztes_Update' in pers_df.columns else ""
                if letztes_datum != heute_str:
                    # Hier könnte man alle Fahrzeuge auf 'Aktiv' setzen, falls gewünscht
                    pass

            # --- SÄULE 1: ÜBERWACHUNG & MÄNGEL-RADAR ---
            st.markdown("### 🚨 Aktueller Status")
            alert_col1, alert_col2 = st.columns(2)

            with alert_col1:
                st.subheader("Zeit-Check")
                ueberfaellig_gefunden = False
                # Wir gehen das Fahrzeug-DF durch (veh_df)
                if not veh_df.empty:
                    for _, fz in veh_df.iterrows():
                        startzeit_str = fz.get('Tour_Startzeit', '')
                        if fz['Status'] == 'Besetzt' and startzeit_str:
                            try:
                                startzeit_dt = datetime.strptime(startzeit_str, "%H:%M")
                                # Auf heute normalisieren für Berechnung
                                startzeit_dt = startzeit_dt.replace(year=heute.year, month=heute.month, day=heute.day)
                                laufzeit = (datetime.now() - startzeit_dt).total_seconds() / 60
                                
                                if laufzeit > 90: # Nach 90 Min Warnung
                                    st.error(f"⚠️ **{fz['Kennzeichen']}** seit {int(laufzeit)} Min überfällig!")
                                    ueberfaellig_gefunden = True
                            except:
                                pass
                if not ueberfaellig_gefunden:
                    st.success("✅ Alle Fahrzeuge im Zeitrahmen.")# --- NEU: SAMMEL-ZUWEISUNG (Alternative zur Einzelbuchung) ---
            st.markdown("---")
            with st.expander("🚌 Sammel-Zuweisung (Mehrere Gäste -> Ein Auto)"):
                st.info("Wähle hier mehrere Gäste aus, um sie mit einem Klick einem Fahrzeug zuzuweisen.")
                
                # 1. Gäste Auswahl
                if not gaeste_df.empty:
                    # Wir bauen eine saubere Liste für das Multiselect
                    gaeste_liste_namen = (gaeste_df['Nachname'].astype(str) + ", " + gaeste_df['Vorname'].astype(str)).tolist()
                    auswahl_gaeste = st.multiselect("Gäste auswählen", gaeste_liste_namen)
                    
                    if auswahl_gaeste:
                        c1, c2 = st.columns(2)
                        
                        # 2. Fahrzeug Auswahl
                        fz_liste = [fz for fz in verfuegbar_fz if fz != "-"]
                        gewaehltes_fz = c1.selectbox("Verfügbares Fahrzeug", fz_liste, key="sammel_fz")
                        uhrzeit_sammel = c2.time_input("Abfahrtszeit", datetime.now(), key="sammel_zeit")
                        
                        # Kapazitäts-Check
                        if gewaehltes_fz:
                            fz_info = veh_df[veh_df['Kennzeichen'] == gewaehltes_fz].iloc[0]
                            # Sicherstellen, dass Sitze_Max eine Zahl ist
                            try:
                                max_plaetze = int(fz_info.get('Sitze_Max', 4))
                            except:
                                max_plaetze = 4
                            
                            aktuell_gewaehlt = len(auswahl_gaeste)
                            
                            if aktuell_gewaehlt > max_plaetze:
                                st.error(f"❌ ZU VIELE PERSONEN! {gewaehltes_fz} hat nur {max_plaetze} Plätze (Gewählt: {aktuell_gewaehlt})")
                            else:
                                st.success(f"✅ Kapazität okay: {aktuell_gewaehlt} von {max_plaetze} Plätzen belegt.")
                                
                                if st.button("🚀 Diese Sammeltour jetzt anlegen", use_container_width=True):
                                    with st.spinner("Speichere Touren..."):
                                        for gast_name in auswahl_gaeste:
                                            neue_tour = [
                                                heute.strftime("%d.%m.%Y"), # Datum
                                                uhrzeit_sammel.strftime("%H:%M"), # Uhrzeit
                                                gast_name, # Patient
                                                "-", # Start
                                                "Tagespflege", # Ziel (Standard)
                                                gewaehltes_fz, # Fahrzeug
                                                "Offen", # Status
                                                "1", # Personen pro Zeile
                                                "Nein", # Rollstuhl (Standard)
                                                "-", # Fahrer
                                                "-"  # Beifahrer
                                            ]
                                            disp_sheet.append_row(neue_tour)
                                        
                                        schreibe_log(st.session_state.user, "Sammeltour angelegt", f"{aktuell_gewaehlt} Personen in {gewaehltes_fz}")
                                        st.success(f"Erfolgreich! {aktuell_gewaehlt} Touren wurden in die Liste eingetragen.")
                                        st.rerun()
                else:
                    st.warning("Keine Gäste im System gefunden.")

            st.markdown("---")

            with alert_col2:
                st.subheader("Mängel-Monitor")
                maengel_gefunden = False
                if not veh_df.empty:
                    # Wir filtern Fahrzeuge, wo Mängel nicht leer sind
                    fz_maengel = veh_df[veh_df['Mängel'].astype(str).str.strip() != ""]
                    for _, fz_m in fz_maengel.iterrows():
                        with st.expander(f"🔧 {fz_m['Kennzeichen']}", expanded=True):
                            st.warning(fz_m['Mängel'])
                            if st.button("Behoben", key=f"fix_{fz_m['Kennzeichen']}"):
                                # Im Sheet löschen (Spalte F = 6)
                                cell = veh_sheet.find(fz_m['Kennzeichen'])
                                veh_sheet.update_cell(cell.row, 6, "")
                                st.rerun()
                        maengel_gefunden = True
                if not maengel_gefunden:
                    st.success("✅ Keine Mängel gemeldet.")

            st.divider()

            # --- 1. NEUE FAHRT ANLEGEN (DEIN BESTEHENDER CODE) ---
            with st.expander("➕ Neue Fahrt (aus Gästestamm) anlegen", expanded=False):
                with st.form("new_tour_form"):
                    c1, c2, c3 = st.columns(3)
                    
                    # Spalte 1: Wann und womit?
                    t_dat = c1.date_input("Datum", heute)
                    t_uhr = c1.time_input("Uhrzeit")
                    t_fz = c1.selectbox("Fahrzeug wählen", verfuegbar_fz)
                    
                    # Spalte 2: Wer und wohin?
                    t_gast_auswahl = c2.selectbox("Gast aus Stammbaum wählen", gaeste_namen)
                    t_ziel = c2.text_input("Ziel (z.B. Praxis, Klinik, Privat)")
                    t_pers_extra = c2.number_input("Zusätzliche Begleitpersonen", 0, 5, 0)
                    
                    # Spalte 3: Personal
                    t_f = c3.selectbox("Fahrer", namen_liste)
                    t_b = c3.selectbox("Beifahrer", namen_liste)
                    
                    if st.form_submit_button("Tour validieren & speichern"):
                        if t_gast_auswahl == "-":
                            st.error("❌ Bitte wähle zuerst einen Gast aus!")
                        elif not t_fz:
                            st.error("❌ Kein einsatzbereites Fahrzeug ausgewählt!")
                        else:
                            # Gast-Daten aus dem Stammbaum ziehen
                            g_data = gaeste_df[(gaeste_df['Nachname'] + ", " + gaeste_df['Vorname']) == t_gast_auswahl].iloc[0]
                            
                            # Adresse und Rollstuhl-Bedarf ermitteln
                            g_adr = f"{g_data['Strasse']} {g_data['Hausnummer']}, {g_data['Ort']} ({g_data['Etage']})"
                            bedarf_rs = 1 if g_data['Hilfsmittel'] == "Rollstuhl" else 0
                            
                            # Kapazitäts-Check gegen Fahrzeug-Daten
                            fz_info = veh_df[veh_df['Kennzeichen'] == t_fz].iloc[0]
                            max_s = int(fz_info['Sitze_Max'])
                            max_r = int(fz_info['Rollstuhl_Plätze'])
                            
                            # Formel: Gast(1) + Begleitung + (RS * 2 Plätze)
                            platz_verbrauch = (1 + t_pers_extra) + (bedarf_rs * 2)
                            
                            if platz_verbrauch > max_s:
                                st.error(f"⚠️ ÜBERBELEGT! Bedarf: {platz_verbrauch} Plätze. Das Fahrzeug {t_fz} hat nur {max_s}.")
                            elif bedarf_rs > max_r:
                                st.error(f"⚠️ KEIN RS-PLATZ! {t_fz} hat keine Vorrichtung für Rollstühle.")
                            else:
                                # Ab ins Google Sheet
                                neue_zeile = [
                                    t_dat.strftime("%d.%m.%Y"), 
                                    t_uhr.strftime("%H:%M"), 
                                    t_gast_auswahl, 
                                    g_adr, 
                                    t_ziel, 
                                    t_fz, 
                                    "Offen", 
                                    1 + t_pers_extra, 
                                    bedarf_rs, 
                                    t_f, 
                                    t_b
                                ]
                                disp_sheet.append_row(neue_zeile)
                                schreibe_log(st.session_state.user, "Tour angelegt", f"Gast: {t_gast_auswahl} mit {t_fz}")
                                st.success("✅ Tour erfolgreich gespeichert!")
                                st.rerun()

            st.write("---")
            # Anzeige Touren heute
            h_str = heute.strftime("%d.%m.%Y")
            df_heute = df_all[df_all['Datum'] == h_str] if not df_all.empty else pd.DataFrame()

            if not df_heute.empty:
                # 1. Spalten-Sicherheitsnetz
                erwartete_spalten = ['Uhrzeit', 'Patient', 'Fahrzeug', 'Start', 'Ziel', 'Personen', 'Rollstuhl', 'Fahrer', 'Beifahrer']
                for col in erwartete_spalten:
                    if col not in df_heute.columns:
                        df_heute[col] = "-"
                
                # Sortieren nach Uhrzeit
                df_heute = df_heute.sort_values(by="Uhrzeit")
                
                # --- NEU: SAMMEL-WHATSAPP LOGIK ---
                # Wir gruppieren, um zu sehen, welche Fahrzeuge zur gleichen Zeit mehrere Gäste haben
                st.subheader("📲 Sammel-Nachrichten")
                
                # Wir holen uns alle Kombinationen von Fahrzeug + Uhrzeit, die mehr als 1 Gast haben
                counts = df_heute.groupby(['Fahrzeug', 'Uhrzeit']).size().reset_index(name='Anzahl')
                sammel_touren = counts[counts['Anzahl'] > 1]
                
                if not sammel_touren.empty:
                    for _, s_row in sammel_touren.iterrows():
                        fz_kfz = s_row['Fahrzeug']
                        fz_zeit = s_row['Uhrzeit']
                        
                        if fz_kfz != "-":
                            # Alle Gäste für diese Fahrt finden
                            gaeste_df = df_heute[(df_heute['Fahrzeug'] == fz_kfz) & (df_heute['Uhrzeit'] == fz_zeit)]
                            fahrer_name = gaeste_df.iloc[0]['Fahrer']
                            
                            if fahrer_name != "-":
                                try:
                                    hdy_serie = pers_df[pers_df['Name'] == fahrer_name]['Handynummer']
                                    if not hdy_serie.empty:
                                        hdy = str(hdy_serie.iloc[0]).strip()
                                        
                                        # Button für Sammel-Nachricht
                                        if st.button(f"📢 Sammel-WA: {fz_kfz} ({fz_zeit}) an {fahrer_name}", key=f"s_wa_{fz_kfz}_{fz_zeit}"):
                                            wa_link = whatsapp_sammel_tour(hdy, fahrer_name, gaeste_df, fz_kfz)
                                            
                                            # Status-Update für Fahrzeug
                                            cell_fz = veh_sheet.find(fz_kfz)
                                            veh_sheet.update_cell(cell_fz.row, 5, "Besetzt")
                                            veh_sheet.update_cell(cell_fz.row, 7, datetime.now().strftime("%H:%M"))
                                            
                                            st.markdown(f'<meta http-equiv="refresh" content="0;URL={wa_link}">', unsafe_allow_html=True)
                                            st.rerun()
                                except: pass
                
                st.markdown("---")

                # 2. EINZEL-ANZEIGE (Dein bestehender Loop)
                for idx, row in df_heute.iterrows():
                    gs_row = idx + 2 
                    
                    with st.expander(f"⏰ {row['Uhrzeit']} | {row['Patient']} | {row['Fahrzeug']}"):
                        col_a, col_b = st.columns([2, 1])
                        
                        with col_a:
                            st.markdown(f"**📍 Start:** {row['Start']}")
                            st.markdown(f"**🏁 Ziel:** {row['Ziel']}")
                            anzahl_personen = row.get('Personen', '1')
                            st.info(f"👥 Personen: {anzahl_personen} | ♿ Rollstuhl: {'Ja' if row.get('Rollstuhl') == 1 else 'Nein'}")
                            st.write(f"🧑‍✈️ Personal: {row['Fahrer']} / {row['Beifahrer']}")

                        with col_b:
                            if row['Fahrer'] != "-":
                                try:
                                    fz_kennzeichen = row['Fahrzeug']
                                    # Sicherer Zugriff auf Handynummer
                                    hdy_query = pers_df[pers_df['Name'] == row['Fahrer']]['Handynummer']
                                    if not hdy_query.empty:
                                        hdy = str(hdy_query.iloc[0]).strip()
                                        wa_link = whatsapp_einzel_tour(hdy, row['Fahrer'], row, fz_kennzeichen)
                                        
                                        if st.button(f"📲 Senden & Start", key=f"wa_{idx}"):
                                            cell_fz = veh_sheet.find(fz_kennzeichen)
                                            veh_sheet.update_cell(cell_fz.row, 5, "Besetzt")
                                            veh_sheet.update_cell(cell_fz.row, 7, datetime.now().strftime("%H:%M"))
                                            
                                            st.markdown(f'<meta http-equiv="refresh" content="0;URL={wa_link}">', unsafe_allow_html=True)
                                            st.rerun()

                                        st.markdown(f"[Direkt-Link (Info)]({wa_link})")
                                except:
                                    st.warning("Handynummer fehlt!")
                            
                            if st.button(f"🗑️ Tour löschen", key=f"del_tour_{idx}"):
                                disp_sheet.delete_rows(gs_row)
                                schreibe_log(st.session_state.user, "Tour gelöscht", f"Patient: {row['Patient']}")
                                st.rerun()
            else:
                st.info(f"Für heute sind noch keine Fahrten geplant.")
                
        # --- TAB 2: GÄSTE-STAMM ---
        with tab_gaeste:
            st.subheader("👥 Gäste-Datenbank")
            
            # Spalten-Fix (Sicherheitsnetz)
            erwartete_g_spalten = ['Nachname', 'Vorname', 'Strasse', 'Hausnummer', 'PLZ', 'Ort', 'Stadtteil', 'Etage', 'Hilfsmittel']
            for col in erwartete_g_spalten:
                if col not in gaeste_df.columns:
                    gaeste_df[col] = "-"

            # --- BEREICH 1: NEUANLAGE ---
            with st.expander("🆕 Neuen Gast anlegen"):
                with st.form("add_guest_new"):
                    c1, c2, c3 = st.columns(3)
                    gn = c1.text_input("Nachname*")
                    gv = c1.text_input("Vorname*")
                    gs = c2.text_input("Strasse")
                    gh = c2.text_input("Hausnr.")
                    ge = c3.text_input("Etage")
                    ghilf = c3.selectbox("Hilfsmittel", ["Keines", "Rollstuhl", "Rollator", "Tragestuhl"])
                    gort = c2.text_input("Ort", value="Musterstadt")
                    
                    if st.form_submit_button("Gast speichern"):
                        if gn and gv:
                            gaeste_sheet.append_row([gn, gv, gs, gh, "", gort, "", ge, ghilf])
                            schreibe_log(st.session_state.user, "Gast angelegt", f"{gn}")
                            st.rerun()
                        else:
                            st.error("Name und Vorname fehlen!")

            st.write("---")
            
            # --- BEREICH 2: VERWALTUNG & BEARBEITEN ---
            st.write("### 🗂️ Gäste verwalten")
            
            # Suchfunktion für große Listen
            search_query = st.text_input("🔍 Gast suchen (Name oder Ort)", "").lower()
            
            if not gaeste_df.empty:
                for i, row in gaeste_df.iterrows():
                    # Suche/Filter Logik
                    full_name = f"{row['Nachname']} {row['Vorname']} {row['Ort']}".lower()
                    if search_query and search_query not in full_name:
                        continue
                    
                    gs_row_idx = i + 2
                    
                    with st.expander(f"👤 {row['Nachname']}, {row['Vorname']} - {row['Ort']}"):
                        # Status-Variable für den Modus (Bearbeiten oder Anzeigen)
                        edit_mode = st.toggle("📝 Bearbeitungs-Modus aktivieren", key=f"edit_toggle_{i}")
                        
                        if edit_mode:
                            # FORMULAR ZUM BEARBEITEN
                            with st.form(key=f"edit_guest_form_{i}"):
                                ec1, ec2, ec3 = st.columns(3)
                                e_n = ec1.text_input("Nachname", value=row['Nachname'])
                                e_v = ec1.text_input("Vorname", value=row['Vorname'])
                                e_s = ec2.text_input("Strasse", value=row['Strasse'])
                                e_h = ec2.text_input("Hausnr.", value=row['Hausnummer'])
                                e_o = ec2.text_input("Ort", value=row['Ort'])
                                e_e = ec3.text_input("Etage", value=row['Etage'])
                                # Hilfsmittel Index finden
                                h_opts = ["Keines", "Rollstuhl", "Rollator", "Tragestuhl"]
                                h_idx = h_opts.index(row['Hilfsmittel']) if row['Hilfsmittel'] in h_opts else 0
                                e_hi = ec3.selectbox("Hilfsmittel", h_opts, index=h_idx)
                                
                                if st.form_submit_button("💾 Änderungen speichern"):
                                    # Update im Google Sheet (Spalte 1 bis 9)
                                    vals = [e_n, e_v, e_s, e_h, row['PLZ'], e_o, row['Stadtteil'], e_e, e_hi]
                                    cells = gaeste_sheet.range(f'A{gs_row_idx}:I{gs_row_idx}')
                                    for idx_cell, val in enumerate(vals):
                                        cells[idx_cell].value = val
                                    gaeste_sheet.update_cells(cells)
                                    
                                    schreibe_log(st.session_state.user, "Gast bearbeitet", f"{e_n}")
                                    st.success("Daten aktualisiert!")
                                    st.rerun()
                        else:
                            # ANZEIGE-MODUS
                            c_left, c_right = st.columns([3, 1])
                            with c_left:
                                st.write(f"🏠 **Adresse:** {row['Strasse']} {row['Hausnummer']}, {row['Ort']}")
                                st.write(f"🏢 **Details:** Etage: {row['Etage']} | Hilfsmittel: {row['Hilfsmittel']}")
                            with c_right:
                                if st.button(f"🗑️ Löschen", key=f"del_g_{i}"):
                                    gaeste_sheet.delete_rows(gs_row_idx)
                                    schreibe_log(st.session_state.user, "Gast gelöscht", f"{row['Nachname']}")
                                    st.rerun()
            else:
                st.info("Keine Gäste gefunden.")

        # --- TAB 3: FUHRPARK ---
        with tab_fuhrpark:
            st.subheader("🛠️ Fahrzeuge & Mängel")
            with st.expander("🆕 Fahrzeug hinzufügen"):
                with st.form("new_fz"):
                    f1, f2, f3 = st.columns(3)
                    fkz = f1.text_input("Kennzeichen")
                    fs = f2.number_input("Sitze Max", 1, 15, 8)
                    fr = f3.number_input("RS Plätze", 0, 5, 1)
                    if st.form_submit_button("Speichern"):
                        veh_sheet.append_row([fkz, int(fs), int(fr), "01.01.2025", "Einsatzbereit", "Keine"])
                        st.rerun()

            for i, row in veh_df.iterrows():
                m_roh = str(row['Mängel'])
                m_liste = [m.strip() for m in m_roh.split("\n") if m.strip() and m.strip().lower() not in ["keine", "-", "none"]]
                farbe = "🟢" if row['Status'] == "Einsatzbereit" and not m_liste else "🟠" if m_liste else "🔴"
                
                with st.expander(f"{farbe} {row['Kennzeichen']}"):
                    # Basis-Daten Edit
                    with st.form(f"f_edit_{i}"):
                        c1, c2 = st.columns(2)
                        n_stat = c1.selectbox("Status", ["Einsatzbereit", "Werkstatt", "Gesperrt"], index=0 if row['Status']=="Einsatzbereit" else 1)
                        n_tuev = c1.text_input("TÜV", value=row['TÜV'])
                        n_s = c2.number_input("Sitze", value=int(row['Sitze_Max']))
                        n_r = c2.number_input("RS Plätze", value=int(row['Rollstuhl_Plätze']))
                        if st.form_submit_button("Basisdaten Update"):
                            veh_sheet.update_cell(i+2, 2, n_s); veh_sheet.update_cell(i+2, 3, n_r)
                            veh_sheet.update_cell(i+2, 4, n_tuev); veh_sheet.update_cell(i+2, 5, n_stat)
                            st.rerun()
                    
                    # Mängel-Sektion
                    st.write("**Mängel:**")
                    for m_idx, m_text in enumerate(m_liste):
                        mc1, mc2 = st.columns([4,1])
                        mc1.warning(m_text)
                        if mc2.button("✅ Erledigt", key=f"q_{i}_{m_idx}"):
                            m_liste.pop(m_idx)
                            veh_sheet.update_cell(i+2, 6, "\n".join(m_liste) if m_liste else "Keine")
                            st.rerun()
                    
                    with st.form(f"add_m_{i}", clear_on_submit=True):
                        neuer_m = st.text_input("Mangel melden")
                        if st.form_submit_button("➕ Eintragen"):
                            kombi = neuer_m if not m_liste else m_roh + "\n" + neuer_m
                            veh_sheet.update_cell(i+2, 6, kombi)
                            st.rerun()

        # --- TAB 4: LOGBUCH ---
        with tab_log:
            st.subheader("📜 System-Log")
            log_data = pd.DataFrame(log_sheet_db.get_all_records())
            if not log_data.empty: st.dataframe(log_data.iloc[::-1], use_container_width=True)# --- TAB: PERSONALVERWALTUNG (NEU) ---
        # --- TAB: PERSONALVERWALTUNG (KORRIGIERT) ---
        with tab_personal:
            st.subheader("👤 Personalverwaltung & Status")

            # 1. Mitarbeiter anlegen
            with st.form("p_neu"):
                c1, c2, c3 = st.columns(3)
                n_vorn = c1.text_input("Vorname")
                n_nach = c2.text_input("Nachname")
                n_handy = c3.text_input("Handynummer")
                
                # DIESER BUTTON MUSS HIER EINRÜCKT SEIN (innerhalb des with-Blocks)
                submit_new = st.form_submit_button("MA Speichern")
                if submit_new:
                    if n_vorn and n_nach:
                        pers_sheet.append_row([n_nach, n_vorn, n_handy, "Aktiv", ""])
                        st.rerun()

            st.write("---")
            st.write("### Aktuelles Personal")
            
            for i, r in pers_df.iterrows():
                # 1. FEHLERBEHEBUNG: Status sauber auslesen (kein dtype-Salat)
                # Wir nehmen den Wert direkt und stellen sicher, dass es ein einfacher Text ist
                raw_status = r['Status']
                if isinstance(raw_status, pd.Series):
                    akt_status = str(raw_status.iloc[0]).strip()
                else:
                    akt_status = str(raw_status).strip()

                gs_idx = i + 2
                
                # 2. FEHLERBEHEBUNG: Logik-Check für das Icon
                # Wir prüfen: Ist der Mitarbeiter im Sheet als "Aktiv" markiert?
                if akt_status == "Aktiv":
                    icon = "🟢"  # Jetzt ist Aktiv wirklich GRÜN
                elif akt_status in ["Urlaub", "Krank", "Fortbildung"]:
                    icon = "🔴"  # Abwesend ist ROT
                else:
                    icon = "⚪"  # Unbekannt ist GRAU
                
                # 2. DER EINE EXPANDER (Hier wird alles für diesen MA gebündelt)
                with st.expander(f"{icon} {r['Name']} (Status: {akt_status})"):
                    
                    # --- Bereich A: Bearbeiten-Formular ---
                    with st.form(f"p_edit_{i}"):
                        col1, col2, col3 = st.columns(3)
                        
                        # Status auswählen
                        st_neu = col1.selectbox(
                            "Status ändern", 
                            ["Aktiv", "Urlaub", "Krank", "Fortbildung"], 
                            index=["Aktiv", "Urlaub", "Krank", "Fortbildung"].index(akt_status) if akt_status in ["Aktiv", "Urlaub", "Krank", "Fortbildung"] else 0,
                            key=f"sel_{i}"
                        )
                        
                        # Datums-Felder
                        von_neu = col2.date_input("Abwesend Von", value=datetime.today(), key=f"v_{i}")
                        bis_neu = col3.date_input("Abwesend Bis", value=datetime.today(), key=f"b_{i}")

                        # Speichern-Button innerhalb des Formulars
                        if st.form_submit_button("💾 Änderungen speichern"):
                            pers_sheet.update_cell(gs_idx, 4, st_neu)
                            pers_sheet.update_cell(gs_idx, 5, von_neu.strftime("%d.%m.%Y"))
                            pers_sheet.update_cell(gs_idx, 6, bis_neu.strftime("%d.%m.%Y"))
                            st.success(f"Status für {r['Name']} aktualisiert!")
                            st.rerun()
                    
                    # --- Bereich B: Löschen (Außerhalb des Formulars, aber im Expander) ---
                    st.write("---") # Trennlinie im Expander
                    if st.button(f"🗑️ {r['Name']} löschen", key=f"p_del_{i}", help="Mitarbeiter unwiderruflich entfernen"):
                        pers_sheet.delete_rows(gs_idx)
                        schreibe_log(st.session_state.user, "Personal gelöscht", f"{r['Name']}")
                        st.rerun()
    except Exception as e:
        st.error(f"Kritischer Fehler: {e}")
