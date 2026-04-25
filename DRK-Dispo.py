import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
import urllib.parse

# --- KONFIGURATION & VERBINDUNG ---
# (Stelle sicher, dass deine 'credentials.json' im selben Ordner liegt)
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_file('credentials.json', scopes=scope)
client = gspread.authorize(creds)

# Öffnen der Tabellen (Namen müssen exakt mit Google Sheets übereinstimmen)
spr = client.open("DRK-Dispo") 
disp_sheet = spr.worksheet("Disposition")
gaeste_sheet = spr.worksheet("Gäste")
veh_sheet = spr.worksheet("Fuhrpark")
pers_sheet = spr.worksheet("Personal")
log_sheet_db = spr.worksheet("Logbuch")

# --- HILFSFUNKTIONEN ---

def schreibe_log(user, aktion, info):
    """Schreibt eine Zeile in das Logbuch-Sheet"""
    zeit = datetime.now().strftime("%d.%m.%Y %H:%M")
    log_sheet_db.append_row([zeit, user, aktion, info])

def whatsapp_einzel_tour(handy, fahrer, row, fz):
    """Erstellt den Link für eine einzelne Fahrt"""
    text = f"Hallo {fahrer}, neue Tour für dich!\n\n⏰ Zeit: {row['Uhrzeit']}\n👤 Gast: {row['Patient']}\n📍 Start: {row['Start']}\n🏁 Ziel: {row['Ziel']}\n🚗 FZ: {fz}"
    return f"https://wa.me/{handy}?text={urllib.parse.quote(text)}"

def whatsapp_sammel_tour(handy, fahrer, df_gaeste, fz):
    """Erstellt den Link für eine Sammeltour mit mehreren Gästen"""
    liste_namen = "\n- ".join(df_gaeste['Patient'].tolist())
    zeit = df_gaeste.iloc[0]['Uhrzeit']
    text = f"Hallo {fahrer}, Sammeltour um {zeit}!\n\nFahrzeug: {fz}\n\nGäste:\n- {liste_namen}"
    return f"https://wa.me/{handy}?text={urllib.parse.quote(text)}"# --- DATEN AUS SHEETS LADEN ---
def load_data():
    # Wir laden alles in DataFrames für die schnelle Verarbeitung in Streamlit
    df_all = pd.DataFrame(disp_sheet.get_all_records())
    gaeste_df = pd.DataFrame(gaeste_sheet.get_all_records())
    veh_df = pd.DataFrame(veh_sheet.get_all_records())
    pers_df = pd.DataFrame(pers_sheet.get_all_records())
    
    # Namen für Selectboxen vorbereiten
    # Wir kombinieren Nachname und Vorname für die Auswahl
    gaeste_namen = ["-"] + (gaeste_df['Nachname'] + ", " + gaeste_df['Vorname']).tolist()
    verfuegbar_fz = veh_df[veh_df['Status'] == "Einsatzbereit"]['Kennzeichen'].tolist()
    namen_liste = ["-"] + pers_df[pers_df['Status'] == "Aktiv"]['Name'].tolist()
    
    return df_all, gaeste_df, veh_df, pers_df, gaeste_namen, verfuegbar_fz, namen_liste

# Session State für Login initialisieren
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

# --- SIDEBAR & LOGIN ---
with st.sidebar:
    st.title("🛡️ Admin-Bereich")
    if not st.session_state.logged_in:
        user = st.text_input("Nutzername")
        pw = st.text_input("Passwort", type="password")
        if st.button("Login"):
            if user == "admin" and pw == "1234": # Hier dein PW anpassen
                st.session_state.logged_in = True
                st.session_state.user = user
                st.rerun()
            else:
                st.error("Falsche Daten")
    else:
        st.success(f"Angemeldet als: {st.session_state.user}")
        if st.button("Logout"):
            st.session_state.logged_in = False
            st.rerun()

if st.session_state.logged_in:
    # Daten nur laden, wenn eingeloggt
    df_all, gaeste_df, veh_df, pers_df, gaeste_namen, verfuegbar_fz, namen_liste = load_data()
    heute = datetime.now().date()# --- TEIL 3: DAS DISPOSITIONS-DASHBOARD ---

if st.session_state.logged_in:
    # Definition der Haupt-Tabs
    tab_dispo, tab_gaeste, tab_fuhrpark, tab_personal, tab_log = st.tabs([
        "🚀 Disposition", "👥 Gäste-Stamm", "🛠️ Fuhrpark", "👤 Personal", "📜 Logbuch"
    ])

    with tab_dispo:
        st.subheader("🚌 Sammeltour-Planung (Schnell-Eingabe)")
        
        # Spalten für die Auswahl der Sammeltour
        sc1, sc2 = st.columns(2)
        
        # 1. Gäste wählen (Mehrfachauswahl)
        # Wir filtern das "-" aus der Namensliste
        gaeste_multi = [n for n in gaeste_namen if n != "-"]
        auswahl_gaeste = sc1.multiselect("Welche Gäste fahren mit?", gaeste_multi)
        
        # 2. Fahrzeug & Zeit wählen
        gewaehltes_fz = sc2.selectbox("Sammel-Fahrzeug wählen", verfuegbar_fz, key="sammel_fz")
        uhrzeit_sammel = sc2.time_input("Abfahrtszeit", datetime.now(), key="sammel_zeit")

        # --- KAPAZITÄTS-CHECK ---
        if gewaehltes_fz and auswahl_gaeste:
            fz_info = veh_df[veh_df['Kennzeichen'] == gewaehltes_fz].iloc[0]
            try:
                max_plaetze = int(fz_info.get('Sitze_Max', 4))
            except:
                max_plaetze = 4
            
            aktuell_gewaehlt = len(auswahl_gaeste)
            
            if aktuell_gewaehlt > max_plaetze:
                st.error(f"❌ ZU VIELE PERSONEN! {gewaehltes_fz} hat nur {max_plaetze} Plätze.")
            else:
                st.success(f"✅ Kapazität okay: {aktuell_gewaehlt} von {max_plaetze} Plätzen.")
                
                if st.button("🚀 Diese Sammeltour jetzt anlegen", use_container_width=True):
                    with st.spinner("Speichere Touren..."):
                        # --- BULK-LOGIK: Wir sammeln erst alle Zeilen ---
                        sammel_liste = []
                        for gast_name in auswahl_gaeste:
                            neue_tour = [
                                heute.strftime("%d.%m.%Y"),      # Spalte A: Datum
                                uhrzeit_sammel.strftime("%H:%M"), # Spalte B: Uhrzeit
                                gast_name,                        # Spalte C: Patient
                                "-",                              # Spalte D: Start (wird autom. "-" gesetzt)
                                "Tagespflege",                    # Spalte E: Ziel
                                gewaehltes_fz,                    # Spalte F: Fahrzeug
                                "Offen",                          # Spalte G: Status
                                "1",                              # Spalte H: Personen pro Zeile
                                "Nein",                           # Spalte I: Rollstuhl
                                "-",                              # Spalte J: Fahrer
                                "-"                               # Spalte K: Beifahrer
                            ]
                            sammel_liste.append(neue_tour)
                        
                        # ALLES IN EINEM RUTSCH AN GOOGLE SENDEN
                        if sammel_liste:
                            disp_sheet.append_rows(sammel_liste)
                        
                        schreibe_log(st.session_state.user, "Sammeltour angelegt", f"{len(auswahl_gaeste)} Personen")
                        st.success(f"✅ Erledigt! {len(auswahl_gaeste)} Einzeltouren wurden erstellt.")
                        st.rerun()

        st.markdown("---")

        # --- ALERTS & MÄNGEL-MONITOR ---
        st.subheader("⚠️ Wichtige Hinweise")
        alert_col1, alert_col2 = st.columns(2)

        with alert_col1:
            # Check für TÜV (Beispielhaft: TÜV diesen Monat fällig)
            # Hier könnte Logik für TÜV-Warnungen stehen
            st.info("💡 Tipp: Sammeltouren sparen Zeit bei der WhatsApp-Benachrichtigung.")

        with alert_col2:
            st.markdown("**🔧 Mängel-Monitor**")
            maengel_gefunden = False
            if not veh_df.empty:
                # Zeige alle Fahrzeuge mit Einträgen in der Spalte 'Mängel'
                fz_maengel = veh_df[veh_df['Mängel'].astype(str).str.strip().str.lower().notin(["keine", "-", "", "none"])]
                for _, fz_m in fz_maengel.iterrows():
                    with st.expander(f"🛠️ {fz_m['Kennzeichen']}", expanded=True):
                        st.warning(fz_m['Mängel'])
                        if st.button("Als behoben markieren", key=f"fix_{fz_m['Kennzeichen']}"):
                            # Wir suchen das Kennzeichen und löschen die Mängel-Zelle (Spalte 6)
                            cell = veh_sheet.find(fz_m['Kennzeichen'])
                            veh_sheet.update_cell(cell.row, 6, "Keine")
                            st.rerun()
                    maengel_gefunden = True
            
            if not maengel_gefunden:
                st.success("✅ Alle Fahrzeuge sind technisch einwandfrei.")# --- TEIL 4: EINZEL-TOUR & TAGESÜBERSICHT ---

        st.markdown("---")
        st.subheader("📝 Einzelne Fahrt anlegen")
        
        with st.form("neue_fahrt_form"):
            c1, c2, c3, c4 = st.columns(4)
            f_zeit = c1.time_input("Uhrzeit", datetime.now())
            f_gast = c2.selectbox("Gast", gaeste_namen)
            f_start = c3.text_input("Start", "Hausadresse")
            f_ziel = c4.text_input("Ziel", "Tagespflege")
            
            c5, c6, c7, c8 = st.columns(4)
            f_fz = c5.selectbox("Fahrzeug", ["-"] + verfuegbar_fz)
            f_stat = c6.selectbox("Status", ["Offen", "Bestätigt", "Abgeschlossen", "Storno"])
            f_fahrer = c7.selectbox("Fahrer", namen_liste)
            f_beifahrer = c8.selectbox("Beifahrer", namen_liste)
            
            if st.form_submit_button("➕ Einzelfahrt speichern"):
                # Vorbereitung der Datenzeile
                neue_zeile = [
                    heute.strftime("%d.%m.%Y"), 
                    f_zeit.strftime("%H:%M"), 
                    f_gast, f_start, f_ziel, f_fz, 
                    f_stat, "1", "Nein", f_fahrer, f_beifahrer
                ]
                disp_sheet.append_row(neue_zeile)
                schreibe_log(st.session_state.user, "Einzel-Tour", f"Gast: {f_gast}")
                st.success(f"Tour für {f_gast} angelegt!")
                st.rerun()

        st.markdown("---")
        st.subheader(f"📅 Tourenplan für heute ({heute.strftime('%d.%m.%Y')})")

        # Daten filtern für heute
        df_heute = df_all[df_all['Datum'] == heute.strftime("%d.%m.%Y")]

        if df_heute.empty:
            st.info("Noch keine Touren für heute geplant.")
        else:
            # 1. Übersicht nach Fahrern gruppiert für WhatsApp
            st.markdown("#### 📱 WhatsApp-Zentrale")
            
            # Alle Fahrer finden, die heute eingeteilt sind
            heutige_fahrer = df_heute[df_heute['Fahrer'] != "-"]['Fahrer'].unique()
            
            wa_cols = st.columns(len(heutige_fahrer) if len(heutige_fahrer) > 0 else 1)
            
            for idx, fahrer_name in enumerate(heutige_fahrer):
                # Handy-Nummer aus Personal-DF suchen
                try:
                    f_daten = pers_df[pers_df['Name'] == fahrer_name].iloc[0]
                    handy = str(f_daten.get('Handy', '')).replace(" ", "")
                except:
                    handy = ""

                # Touren für diesen Fahrer filtern
                f_touren = df_heute[df_heute['Fahrer'] == fahrer_name]
                
                if not handy:
                    wa_cols[idx % 3].error(f"❌ {fahrer_name}: Keine Nummer!")
                else:
                    # WhatsApp Button generieren
                    link = whatsapp_sammel_tour(handy, fahrer_name, f_touren, f_touren.iloc[0]['Fahrzeug'])
                    wa_cols[idx % 3].link_button(f"📲 Plan an {fahrer_name}", link, use_container_width=True)

            st.markdown("---")
            
            # 2. Die interaktive Tabelle mit allen Touren
            # Wir nutzen st.data_editor, damit der Disponent Status/Fahrer direkt ändern kann
            edited_df = st.data_editor(
                df_heute, 
                column_config={
                    "Status": st.column_config.SelectboxColumn(options=["Offen", "Bestätigt", "Abgeschlossen", "Storno"]),
                    "Fahrer": st.column_config.SelectboxColumn(options=namen_liste),
                    "Fahrzeug": st.column_config.SelectboxColumn(options=verfuegbar_fz),
                },
                disabled=["Datum", "Patient"], # Diese Felder nicht editierbar
                hide_index=True,
                use_container_width=True,
                key="main_editor"
            )

            if st.button("💾 Alle Änderungen in Tabelle speichern"):
                with st.spinner("Synchronisiere mit Google..."):
                    # Hier nutzen wir eine Funktion, die das gesamte Sheet für heute überschreibt
                    # Um Sicherzugehen: Wir löschen die heutigen Zeilen und schreiben sie neu
                    # (Alternativ kann man Zellen einzeln updaten, aber Bulk ist sicherer)
                    
                    # Logik: Wir holen alle Daten, entfernen "heute", fügen "edited_df" an
                    df_full = pd.DataFrame(disp_sheet.get_all_records())
                    df_ohne_heute = df_full[df_full['Datum'] != heute.strftime("%d.%m.%Y")]
                    
                    # Neues Gesamt-DF bauen
                    df_neu = pd.concat([df_ohne_heute, edited_df], ignore_index=True)
                    
                    # Sheet leeren und neu befüllen
                    disp_sheet.clear()
                    disp_sheet.update([df_neu.columns.values.tolist()] + df_neu.values.tolist())
                    
                    st.success("Gesamter Tourenplan aktualisiert!")
                    st.rerun()# --- TEIL 5: GÄSTE-STAMM & FUHRPARK-VERWALTUNG ---

    with tab_gaeste:
        st.subheader("👥 Gäste-Datenbank")
        
        # Neuer Gast anlegen
        with st.expander("➕ Neuen Gast hinzufügen"):
            with st.form("neuer_gast_form"):
                n_col1, n_col2 = st.columns(2)
                n_nach = n_col1.text_input("Nachname*")
                n_vorn = n_col2.text_input("Vorname*")
                n_str = n_col1.text_input("Straße")
                n_nr = n_col2.text_input("Hausnummer")
                n_ort = n_col1.text_input("Ort", "Musterstadt")
                n_plz = n_col2.text_input("PLZ")
                n_hilf = st.selectbox("Hilfsmittel", ["Keine", "Rollstuhl", "Rollator", "Tragesessel"])
                
                if st.form_submit_button("Gast speichern"):
                    if n_nach and n_vorn:
                        neuer_gast = [n_nach, n_vorn, n_str, n_nr, n_plz, n_ort, "", "", n_hilf]
                        gaeste_sheet.append_row(neuer_gast)
                        st.success(f"{n_vorn} {n_nach} wurde angelegt!")
                        st.rerun()
                    else:
                        st.error("Nachname und Vorname sind Pflichtfelder!")

        st.markdown("---")
        
        # Suche im Gäste-Stamm
        suche_gast = st.text_input("🔍 Gast suchen (Nachname)", "").lower()
        
        for i, row in gaeste_df.iterrows():
            if suche_gast in row['Nachname'].lower():
                # Google Sheets Zeilenindex (Header + 0-basiert -> +2)
                gs_row_idx = i + 2
                
                with st.expander(f"👤 {row['Nachname']}, {row['Vorname']} ({row['Hilfsmittel']})"):
                    with st.form(f"edit_gast_{i}"):
                        c1, c2 = st.columns(2)
                        e_n = c1.text_input("Nachname", value=row['Nachname'])
                        e_v = c2.text_input("Vorname", value=row['Vorname'])
                        e_s = c1.text_input("Straße", value=row['Straße'])
                        e_h = c2.text_input("Hausnr.", value=row['Hausnummer'])
                        e_o = c1.text_input("Ort", value=row['Ort'])
                        e_e = c2.text_input("Etage", value=row['Etage'])
                        e_hi = st.selectbox("Hilfsmittel", 
                                            ["Keine", "Rollstuhl", "Rollator", "Tragesessel"],
                                            index=["Keine", "Rollstuhl", "Rollator", "Tragesessel"].index(row['Hilfsmittel']) if row['Hilfsmittel'] in ["Keine", "Rollstuhl", "Rollator", "Tragesessel"] else 0)
                        
                        if st.form_submit_button("💾 Änderungen für Gast speichern"):
                            # BULK-UPDATE: Wir senden alle Spalten von A bis I gleichzeitig
                            neue_werte = [[e_n, e_v, e_s, e_h, row['PLZ'], e_o, row['Stadtteil'], e_e, e_hi]]
                            gaeste_sheet.update(f'A{gs_row_idx}:I{gs_row_idx}', neue_werte)
                            
                            schreibe_log(st.session_state.user, "Gast-Update", f"{e_n}")
                            st.success("Daten erfolgreich aktualisiert!")
                            st.rerun()

    with tab_fuhrpark:
        st.subheader("🛠️ Fahrzeug-Management")
        
        for i, row in veh_df.iterrows():
            fz_idx = i + 2
            # Farbliches Status-Icon
            fz_status = row['Status']
            fz_icon = "✅" if fz_status == "Einsatzbereit" else "⚠️" if fz_status == "Werkstatt" else "❌"
            
            with st.expander(f"{fz_icon} {row['Kennzeichen']} - {row['Fahrzeugtyp']}"):
                col_a, col_b = st.columns(2)
                col_a.metric("Sitzplätze", row['Sitze_Max'])
                col_a.metric("Rollstuhlplätze", row['Rollstuhl_Max'])
                col_b.write(f"**Nächster TÜV:** {row['TÜV']}")
                col_b.write(f"**Aktueller Status:** {fz_status}")
                
                with st.form(f"fz_update_{i}"):
                    st.markdown("**Status & Mängel bearbeiten**")
                    n_stat = st.selectbox("Status ändern", ["Einsatzbereit", "Werkstatt", "Defekt", "Reinigung"], 
                                         index=["Einsatzbereit", "Werkstatt", "Defekt", "Reinigung"].index(fz_status) if fz_status in ["Einsatzbereit", "Werkstatt", "Defekt", "Reinigung"] else 0)
                    n_maengel = st.text_area("Mängelbericht / Notizen", value=row['Mängel'])
                    
                    if st.form_submit_button("💾 Fahrzeug-Status speichern"):
                        # BULK-UPDATE für Status (Spalte E) und Mängel (Spalte F)
                        # Wir adressieren den Bereich E bis F
                        fz_update_werte = [[n_stat, n_maengel]]
                        veh_sheet.update(f'E{fz_idx}:F{fz_idx}', fz_update_werte)
                        
                        schreibe_log(st.session_state.user, "Fuhrpark-Update", f"{row['Kennzeichen']}: {n_stat}")
                        st.success("Fahrzeugdaten aktualisiert!")
                        st.rerun()# --- TEIL 6: PERSONALVERWALTUNG & LOGBUCH ---

    with tab_personal:
        st.subheader("👤 Personal- & Dienststatus")
        
        # Mitarbeiter neu anlegen
        with st.expander("➕ Neuen Mitarbeiter hinzufügen"):
            with st.form("p_neu"):
                c1, c2 = st.columns(2)
                n_vorn = c1.text_input("Vorname")
                n_nach = c2.text_input("Nachname")
                n_handy = st.text_input("WhatsApp-Nummer (z.B. 491701234567)")
                
                if st.form_submit_button("MA Speichern"):
                    if n_vorn and n_nach:
                        # Neuer MA: Name (A), Vorname (B), Handy (C), Status (D), Datum Von (E), Datum Bis (F)
                        pers_sheet.append_row([f"{n_nach}, {n_vorn}", n_vorn, n_handy, "Aktiv", "", ""])
                        st.success(f"{n_vorn} wurde angelegt!")
                        st.rerun()

        st.markdown("---")

        # Liste der Mitarbeiter
        for i, r in pers_df.iterrows():
            gs_idx = i + 2
            akt_status = str(r.get('Status', 'Aktiv')).strip()
            
            # --- LOGIK-CHECK FÜR DAS ICON ---
            if akt_status == "Aktiv":
                icon = "🟢" 
            elif akt_status in ["Urlaub", "Krank", "Fortbildung"]:
                icon = "🔴"
            else:
                icon = "⚪"

            with st.expander(f"{icon} {r.get('Name', 'Unbekannt')} (Status: {akt_status})"):
                # --- Bereich A: Bearbeiten-Formular ---
                with st.form(f"p_edit_{i}"):
                    col1, col2, col3 = st.columns(3)
                    
                    st_neu = col1.selectbox(
                        "Status ändern", 
                        ["Aktiv", "Urlaub", "Krank", "Fortbildung"], 
                        index=["Aktiv", "Urlaub", "Krank", "Fortbildung"].index(akt_status) if akt_status in ["Aktiv", "Urlaub", "Krank", "Fortbildung"] else 0,
                        key=f"sel_{i}"
                    )
                    
                    von_neu = col2.date_input("Abwesend Von", value=datetime.today(), key=f"v_{i}")
                    bis_neu = col3.date_input("Abwesend Bis", value=datetime.today(), key=f"b_{i}")

                    if st.form_submit_button("💾 Änderungen speichern"):
                        # BULK-UPDATE: Status (D), Von (E), Bis (F) gleichzeitig aktualisieren
                        bereich = f"D{gs_idx}:F{gs_idx}"
                        werte = [[st_neu, von_neu.strftime("%d.%m.%Y"), bis_neu.strftime("%d.%m.%Y")]]
                        
                        pers_sheet.update(bereich, werte)
                        schreibe_log(st.session_state.user, "Personal-Status", f"{r.get('Name')} -> {st_neu}")
                        st.success(f"Status für {r.get('Name')} aktualisiert!")
                        st.rerun()

                # --- Bereich B: Löschen ---
                st.write("---")
                if st.button(f"🗑️ {r.get('Name')} löschen", key=f"p_del_{i}"):
                    pers_sheet.delete_rows(gs_idx)
                    schreibe_log(st.session_state.user, "Personal gelöscht", f"{r.get('Name')}")
                    st.rerun()

    with tab_log:
        st.subheader("📜 System-Logbuch")
        st.info("Hier werden alle kritischen Änderungen protokolliert.")
        
        # Log-Daten frisch laden
        try:
            logs = pd.DataFrame(log_sheet_db.get_all_records())
            if not logs.empty:
                # Neueste Einträge zuerst anzeigen
                st.dataframe(logs.iloc[::-1], use_container_width=True, hide_index=True)
                
                if st.button("Logbuch leeren"):
                    # Behält den Header (Zeile 1) bei
                    log_sheet_db.resize(rows=1)
                    st.rerun()
            else:
                st.write("Noch keine Einträge vorhanden.")
        except:
            st.write("Logbuch konnte nicht geladen werden.")

# --- ENDE DER APP ---# --- DER "MOTOR" (MAIN LOOP) ---

# Dieser Teil sorgt dafür, dass die App überhaupt startet
if __name__ == "__main__":
    # Falls du alles in eine Funktion namens main_app() gepackt hast:
    # main_app() 
    
    # Falls du die Teile einfach untereinander kopiert hast, 
    # wird der Code ohnehin von oben nach unten ausgeführt.
    
    # WICHTIG: Der Login-Check aus Teil 2 muss alles umschließen!
    if st.session_state.logged_in:
        st.toast("Daten erfolgreich geladen!", icon="✅")
    else:
        st.info("Bitte loggen Sie sich über die Seitenleiste ein.")
