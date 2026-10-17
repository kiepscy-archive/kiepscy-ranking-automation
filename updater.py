import os
import re
import json
import time
import sys
import argparse
import requests
from datetime import datetime, timedelta
from urllib.parse import urljoin, parse_qs, urlparse
from bs4 import BeautifulSoup

# ==============================================================================
# KONFIGURACJA (DANE WPISANE BEZPOŚREDNIO W KODZIE)
# ==============================================================================

SUBFORUM_URL = "https://forum.kiepscy.org.pl/viewforum.php?f=8"  
WP_URL = "http://kiepscy.org.pl"               
WP_PAGE_ID = 37                                            

WP_USER = "kacrudy"                                       
WP_CUSTOM_TOKEN = "fba8U57HyTvulhlJRh5uMdRe"                         

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) KiepskiUpdater/2.0'
}

API_HEADERS = {
    'X-Auth-Token': WP_CUSTOM_TOKEN
}

# ==============================================================================
# SYSTEM LOGOWANIA DO PLIKU I KONSOLI ORAZ AUTOCZYSZCZENIE
# ==============================================================================

def log_print(komunikat):
    print(komunikat)
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    try:
        with open("log.log", "a", encoding="utf-8") as f:
            f.write(f"{timestamp} {komunikat}\n")
    except Exception as e:
        print(f"⚠️ Nie udało się zapisać do pliku log.log: {e}")

def wyczysc_stare_logi(dni_wstecz=3):
    if not os.path.exists("log.log"):
        return
    
    dzis = datetime.now().date()
    zostawione_linie = []
    
    try:
        with open("log.log", "r", encoding="utf-8") as f:
            for linia in f:
                m = re.match(r'^\[(\d{4}-\d{2}-\d{2})', linia)
                if m:
                    try:
                        data_wpisu = datetime.strptime(m.group(1), "%Y-%m-%d").date()
                        if (dzis - data_wpisu).days <= dni_wstecz:
                            zostawione_linie.append(linia)
                    except ValueError:
                        zostawione_linie.append(linia)
                else:
                    zostawione_linie.append(linia)
                    
        with open("log.log", "w", encoding="utf-8") as f:
            f.writelines(zostawione_linie)
    except Exception as e:
        print(f"⚠️ Błąd podczas autoczyszczenia logów: {e}")

# ==============================================================================
# HELPERY I ANALIZA OCENY
# ==============================================================================

def czyść_bbcode(tekst):
    tekst = re.sub(r'\[/?[a-zA-Z0-9]+(=[^\]]+)?\]', '', tekst)
    return tekst.strip()

def wyciągnij_ocenę_z_dołu_posta(treść_posta):
    linie = [l.strip() for l in treść_posta.splitlines() if l.strip()]
    if not linie:
        return None

    ostatnia_linia = czyść_bbcode(linie[-1])
    wzorzec = r'^(?:.*\s)?(10|[0-9])(?:[\,\.]([0-9]))?[\-\+\*]?\s*/\s*10[\.\!\?]*$'
    m = re.match(wzorzec, ostatnia_linia, re.IGNORECASE)
    
    if m:
        ocena = int(m.group(1))
        if 0 <= ocena <= 10:
            return ocena

    return None

def parsuj_datę_postu(znacznik_czasu):
    if not znacznik_czasu:
        return None
    m = re.search(r'(\d{4}-\d{2}-\d{2})', znacznik_czasu)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            pass
    return None

def czysc_url(url):
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    qs.pop('start', None)
    qs.pop('sid', None)
    new_query = "&".join([f"{k}={v[0]}" for k, v in qs.items()])
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}" + (f"?{new_query}" if new_query else "")

def pasuje_do_odcinka(tytul_tekst, szukany_ep_str):
    szukany_czysty = szukany_ep_str.strip()
    
    if szukany_czysty.isdigit():
        szukany_ep_int = int(szukany_czysty)
        m = re.match(r'^0*(\d+)', tytul_tekst.strip())
        if m:
            try:
                if int(m.group(1)) == szukany_ep_int:
                    return True
            except ValueError:
                pass
        
        wzorzec = r'(?<!\d)0*' + str(szukany_ep_int) + r'(?!\d)'
        if re.search(wzorzec, tytul_tekst):
            return True
    else:
        if szukany_czysty.lower() in tytul_tekst.lower():
            return True
        
    return False

# ==============================================================================
# SZYBKI SCRAPER
# ==============================================================================

def pobierz_aktywne_tematy(url_subforum, data_od, data_do):
    odwiedzone = set()
    do_odwiedzenia = [url_subforum]
    aktywne_tematy = []

    log_print("⚡ Szybkie skanowanie listy tematów pod kątem nowej aktywności...")

    while do_odwiedzenia:
        curr = do_odwiedzenia.pop(0)
        curr_clean = czysc_url(curr)
        if curr_clean in odwiedzone:
            continue
        odwiedzone.add(curr_clean)

        try:
            res = requests.get(curr, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            for a in soup.find_all('a', class_='forumtitle'):
                do_odwiedzenia.append(urljoin(curr, a.get('href')))
            
            wiersze_tematow = soup.find_all('li', class_=re.compile(r'row'))
            for row in wiersze_tematow:
                a_topic = row.find('a', class_='topictitle')
                if not a_topic:
                    continue

                lastpost_span = row.find(class_=re.compile(r'lastpost'))
                data_ostatniego_posta = None
                if lastpost_span:
                    data_ostatniego_posta = parsuj_datę_postu(lastpost_span.text)

                if data_ostatniego_posta and data_ostatniego_posta >= data_od:
                    href = urljoin(curr, a_topic.get('href'))
                    clean_href = czysc_url(href)
                    if clean_href not in aktywne_tematy:
                        aktywne_tematy.append(clean_href)

        except Exception as e:
            log_print(f"⚠️ Błąd pobierania listy {curr}: {e}")

    return aktywne_tematy

def pobierz_dzisiejsze_i_wczorajsze_oceny(url_subforum, data_od, data_do):
    linki_tematow = pobierz_aktywne_tematy(url_subforum, data_od, data_do)

    if not linki_tematow:
        log_print("😴 Brak jakiejkolwiek aktywności w tematach z wczorajszego i dzisiejszego dnia. Koniec.")
        return {}

    log_print(f"🎯 Znaleziono {len(linki_tematow)} temat(y) z nową aktywnością. Pobieranie postów...")
    nowe_oceny = {}

    for url_t in linki_tematow:
        start = 0
        tytul_odcinka = ""
        
        while True:
            sep = "&" if "?" in url_t else "?"
            url_page = f"{url_t}{sep}start={start}" if start > 0 else url_t
            
            try:
                res = requests.get(url_page, headers=HEADERS, timeout=10)
                soup = BeautifulSoup(res.text, 'html.parser')
                
                if not tytul_odcinka:
                    h2 = soup.find('h2', class_='topic-title')
                    tytul_odcinka = h2.text.strip() if h2 else "Nieznany"
                    if "ogólnie o sezonie" in tytul_odcinka.lower():
                        break

                posty_html = soup.find_all('div', class_='post', id=re.compile(r'^p\d+'))
                if not posty_html:
                    break

                for post in posty_html:
                    p_author = post.find('p', class_='author')
                    data_postu = parsuj_datę_postu(p_author.text) if p_author else None
                    
                    if not data_postu or not (data_od <= data_postu <= data_do):
                        continue

                    autor_tag = post.find(class_=re.compile(r'username'))
                    autor = autor_tag.text.strip() if autor_tag else None
                    
                    tresc_tag = post.find('div', class_='content')
                    if tresc_tag and autor:
                        for q in tresc_tag.find_all(['blockquote', 'cite']):
                            q.decompose()
                        for q in tresc_tag.find_all(class_=re.compile(r'quote|uncited', re.I)):
                            q.decompose()

                        ocena = wyciągnij_ocenę_z_dołu_posta(tresc_tag.text)
                        if ocena is not None:
                            if tytul_odcinka not in nowe_oceny:
                                nowe_oceny[tytul_odcinka] = []
                            nowe_oceny[tytul_odcinka].append((autor, ocena))
                        else:
                            log_print(f"ℹ️ Post użytkownika {autor} w temacie '{tytul_odcinka}' z dnia {data_postu} nie zawiera poprawnej oceny na końcu.")

                strefa_pagi = soup.find('div', class_='pagination')
                ma_nastepna = False
                if strefa_pagi and (strefa_pagi.find('a', text=re.compile(r'Następna|Next|>', re.I)) or f"start={start + 25}" in res.text):
                    ma_nastepna = True

                if not ma_nastepna:
                    break
                start += 25
                time.sleep(0.2)

            except Exception as e:
                log_print(f"⚠️ Błąd podczas skanowania {url_page}: {e}")
                break

    return nowe_oceny

# ==============================================================================
# OBSŁUGA WORDPRESS API & EDYCJA TABELI HTML
# ==============================================================================

def formatuj_liczbe(wartosc):
    text = f"{round(wartosc, 2):.2f}".replace('.', ',')
    if ',' in text:
        text = text.rstrip('0').rstrip(',')
    return text

def zrob_backup_przed_zmiana(rows_data):
    backup_filename = "tabela_backup.json"
    try:
        with open(backup_filename, "w", encoding="utf-8") as f:
            json.dump(rows_data, f, ensure_ascii=False, indent=4)
        log_print(f"💾 Utworzono/zaktualizowano lokalną kopię zapasową w pliku: {backup_filename}")
    except Exception as e:
        log_print(f"⚠️ Nie udało się zapisać kopii zapasowej: {e}")

def testuj_polaczenie_wp():
    TABLE_ID = 116
    get_url = f"{WP_URL.rstrip('/')}/wp-json/custom/v1/get-table/{TABLE_ID}"
    log_print(f"🔍 Testowanie połączenia z WordPress API (Adres: {WP_URL}, Tabela ID: {TABLE_ID})...")
    
    try:
        res = requests.get(get_url, headers=API_HEADERS, timeout=10)
        if res.status_code == 200:
            log_print("✅ Sukces! Połączenie nawiązane, uwierzytelnianie poprawne (Status 200).")
            return True
        else:
            log_print(f"❌ Otrzymano kod statusu: {res.status_code} - {res.text}")
            return False
    except Exception as e:
        log_print(f"❌ Błąd połączenia: {e}")
        return False

def napraw_pozycje_w_wp():
    TABLE_ID = 116
    get_url = f"{WP_URL.rstrip('/')}/wp-json/custom/v1/get-table/{TABLE_ID}"
    log_print("🛠️ Uruchamianie weryfikacji i naprawy pozycji ex aequo w tabeli WP...")
    
    res = requests.get(get_url, headers=API_HEADERS)
    if res.status_code != 200:
        log_print(f"❌ Nie udało się pobrać tabeli z API (Status: {res.status_code})")
        return False
        
    rows = res.json().get('data', [])
    if not rows or len(rows) < 2:
        return False

    zrob_backup_przed_zmiana(rows)
    naglowek = rows[0]
    wiersze_danych = rows[1:]

    dane_obliczone = []
    for wiersz in wiersze_danych:
        if len(wiersz) <= 3:
            continue
        txt_srednia = str(wiersz[1])
        clean_srednia = re.sub(r'[^\d\.]', '', txt_srednia.replace(',', '.'))
        srednia_val = round(float(clean_srednia), 2) if clean_srednia else 0.0
        dane_obliczone.append({'srednia': srednia_val, 'pelny_wiersz': wiersz})

    dane_obliczone.sort(key=lambda x: x['srednia'], reverse=True)
    nowe_wiersze_tablepress = [naglowek]
    ostatnia_srednia = None
    biezaca_pozycja = 1

    for i, item in enumerate(dane_obliczone):
        if i > 0 and item['srednia'] == ostatnia_srednia:
            pozycja_w_rankingu = biezaca_pozycja
        else:
            biezaca_pozycja = i + 1
            pozycja_w_rankingu = biezaca_pozycja

        ostatnia_srednia = item['srednia']
        wiersz = list(item['pelny_wiersz'])
        wiersz[0] = bezpieczna_aktualizacja_komorki(wiersz[0], pozycja_w_rankingu)
        nowe_wiersze_tablepress.append(wiersz)

    update_url = f"{WP_URL.rstrip('/')}/wp-json/custom/v1/update-table"
    payload = {'table_id': TABLE_ID, 'data': nowe_wiersze_tablepress}
    res_post = requests.post(update_url, json=payload, headers=API_HEADERS)
    return res_post.status_code == 200

def aktualizuj_tabelę_wp(slownik_aktualizacji=None, manualna_korekta=None, manualne_dodanie_oceny=None, manualne_usunięcie_oceny=None):
    TABLE_ID = 116
    if slownik_aktualizacji is None:
        slownik_aktualizacji = {}
    
    get_url = f"{WP_URL.rstrip('/')}/wp-json/custom/v1/get-table/{TABLE_ID}"
    res = requests.get(get_url, headers=API_HEADERS)
    
    if res.status_code != 200:
        return False
        
    rows = res.json().get('data', [])
    if not rows or len(rows) < 2:
        return False

    if not os.path.exists("tabela_backup.json"):
        zrob_backup_przed_zmiana(rows)

    idx_lp = 0
    idx_srednia = 1
    idx_tytul = 2
    idx_liczba = 3

    naglowek = rows[0]
    wiersze_danych = rows[1:]

    dane_obliczone = []
    zmieniono = False

    for wiersz in wiersze_danych:
        if len(wiersz) <= idx_liczba:
            continue

        tytul_raw = str(wiersz[idx_tytul])
        soup_tytul = BeautifulSoup(tytul_raw, 'html.parser')
        tytul_tekst = soup_tytul.get_text(strip=True)

        txt_srednia = str(wiersz[idx_srednia])
        txt_liczba = str(wiersz[idx_liczba])

        raw_liczba = re.sub(r'\D', '', txt_liczba)
        stara_liczba_ocen = int(raw_liczba) if raw_liczba else 0

        clean_srednia = re.sub(r'[^\d\.]', '', txt_srednia.replace(',', '.'))
        stara_srednia = float(clean_srednia) if clean_srednia else 0.0

        stara_suma = stara_srednia * stara_liczba_ocen

        nowa_liczba_ocen = stara_liczba_ocen
        nowa_suma = stara_suma
        nowa_srednia = stara_srednia

        if manualna_korekta:
            szukany_ep_str = str(manualna_korekta['ep'])
            if pasuje_do_odcinka(tytul_tekst, szukany_ep_str):
                nowa_srednia = round(manualna_korekta['newavg'], 2)
                nowa_liczba_ocen = manualna_korekta['ratnr']
                zmieniono = True

        if manualne_dodanie_oceny:
            szukany_ep_str = str(manualne_dodanie_oceny['ep'])
            if pasuje_do_odcinka(tytul_tekst, szukany_ep_str):
                dodatkowa_ocena = manualne_dodanie_oceny['rate']
                nowa_liczba_ocen = stara_liczba_ocen + 1
                nowa_suma = stara_suma + dodatkowa_ocena
                nowa_srednia = round((nowa_suma / nowa_liczba_ocen) if nowa_liczba_ocen > 0 else 0.0, 2)
                zmieniono = True

                from_user = manualne_dodanie_oceny.get('from_user')
                if from_user and os.path.exists("baza_userow.json"):
                    with open("baza_userow.json", "r", encoding="utf-8") as bf:
                        baza_userow = json.load(bf)
                    
                    wzorcowa_lista = baza_userow.get("bazowa_lista_odcinków", [])
                    if from_user not in baza_userow:
                        baza_userow[from_user] = {"nieocenione": list(wzorcowa_lista), "ocenione": []}
                    
                    nieocenione = baza_userow[from_user].get("nieocenione", [])
                    ocenione = baza_userow[from_user].get("ocenione", [])
                    
                    dopasowany_nieoceniony = next((t for t in nieocenione if pasuje_do_odcinka(t, szukany_ep_str)), None)
                    if dopasowany_nieoceniony:
                        baza_userow[from_user]["nieocenione"].remove(dopasowany_nieoceniony)
                        if dopasowany_nieoceniony not in baza_userow[from_user]["ocenione"]:
                            baza_userow[from_user]["ocenione"].append(dopasowany_nieoceniony)
                    else:
                        if tytul_tekst not in baza_userow[from_user]["ocenione"]:
                            baza_userow[from_user]["ocenione"].append(tytul_tekst)
                    
                    with open("baza_userow.json", "w", encoding="utf-8") as bf:
                        json.dump(baza_userow, bf, ensure_ascii=False, indent=4)

        if manualne_usunięcie_oceny:
            szukany_ep_str = str(manualne_usunięcie_oceny['ep'])
            if pasuje_do_odcinka(tytul_tekst, szukany_ep_str):
                ocena_do_usuniecia = manualne_usunięcie_oceny['rate']
                if stara_liczba_ocen > 0:
                    nowa_liczba_ocen = stara_liczba_ocen - 1
                    nowa_suma = max(0.0, stara_suma - ocena_do_usuniecia)
                    nowa_srednia = round((nowa_suma / nowa_liczba_ocen) if nowa_liczba_ocen > 0 else 0.0, 2)
                    zmieniono = True
                
                from_user = manualne_usunięcie_oceny.get('from_user')
                if from_user and os.path.exists("baza_userow.json"):
                    with open("baza_userow.json", "r", encoding="utf-8") as bf:
                        baza_userow = json.load(bf)
                    
                    if from_user in baza_userow:
                        ocenione = baza_userow[from_user].get("ocenione", [])
                        dopasowany_oceniony = next((t for t in ocenione if pasuje_do_odcinka(t, szukany_ep_str)), None)
                        
                        if dopasowany_oceniony:
                            baza_userow[from_user]["ocenione"].remove(dopasowany_oceniony)
                            if dopasowany_oceniony not in baza_userow[from_user]["nieocenione"]:
                                baza_userow[from_user]["nieocenione"].append(dopasowany_oceniony)
                            
                            with open("baza_userow.json", "w", encoding="utf-8") as bf:
                                json.dump(baza_userow, bf, ensure_ascii=False, indent=4)

        for tytul_odcinka_forum, list_ocen in slownik_aktualizacji.items():
            if tytul_odcinka_forum.strip().lower() in tytul_tekst.lower():
                dodatkowa_suma = sum(list_ocen)
                dodatkowa_liczba = len(list_ocen)
                nowa_liczba_ocen = stara_liczba_ocen + dodatkowa_liczba
                nowa_suma = stara_suma + dodatkowa_suma
                nowa_srednia = round((nowa_suma / nowa_liczba_ocen) if nowa_liczba_ocen > 0 else 0.0, 2)
                zmieniono = True
                break

        dane_obliczone.append({
            'srednia': nowa_srednia,
            'liczba_ocen': nowa_liczba_ocen,
            'pelny_wiersz': wiersz  
        })

    if not zmieniono and not manualna_korekta and not manualne_dodanie_oceny and not manualne_usunięcie_oceny:
        return True

    zrob_backup_przed_zmiana(rows)
    dane_obliczone.sort(key=lambda x: x['srednia'], reverse=True)

    nowe_wiersze_tablepress = [naglowek]
    ostatnia_srednia = None
    biezaca_pozycja = 1

    for i, item in enumerate(dane_obliczone):
        if i > 0 and item['srednia'] == ostatnia_srednia:
            pozycja_w_rankingu = biezaca_pozycja
        else:
            biezaca_pozycja = i + 1
            pozycja_w_rankingu = biezaca_pozycja

        ostatnia_srednia = item['srednia']
        wiersz = list(item['pelny_wiersz'])
        
        wiersz[idx_lp] = bezpieczna_aktualizacja_komorki(wiersz[idx_lp], pozycja_w_rankingu)
        wiersz[idx_srednia] = bezpieczna_aktualizacja_komorki(wiersz[idx_srednia], formatuj_liczbe(item['srednia']))
        wiersz[idx_liczba] = bezpieczna_aktualizacja_komorki(wiersz[idx_liczba], item['liczba_ocen'])
            
        nowe_wiersze_tablepress.append(wiersz)

    update_url = f"{WP_URL.rstrip('/')}/wp-json/custom/v1/update-table"
    payload = {'table_id': TABLE_ID, 'data': nowe_wiersze_tablepress}
    res_post = requests.post(update_url, json=payload, headers=API_HEADERS)
    return res_post.status_code == 200
        
def bezpieczna_aktualizacja_komorki(stary_html, nowa_wartosc):
    if not stary_html:
        return str(nowa_wartosc)
    soup = BeautifulSoup(str(stary_html), 'html.parser')
    replaced = False
    for element in soup.find_all(string=True):
        if re.search(r'\d', element):
            new_text = re.sub(r'[\d,\.]+', str(nowa_wartosc), element, count=1)
            element.replace_with(new_text)
            replaced = True
            break
    if not replaced:
        return str(nowa_wartosc)
    return str(soup)

# ==============================================================================
# GŁÓWNA LOGIKA
# ==============================================================================

def main():
    wyczysc_stare_logi(dni_wstecz=3)

    parser = argparse.ArgumentParser(description="Kiepscy Ranking Updater")
    parser.add_argument("--onlycheck", action="store_true", help="Tylko test połączenia z WP API")
    parser.add_argument("--fixrank", action="store_true", help="Naprawia pozycje ex aequo w tabeli WP")
    parser.add_argument("--ep", type=str, help="Numer lub tytuł odcinka")
    parser.add_argument("--newavg", type=str, help="Nowa średnia ocena")
    parser.add_argument("--ratnr", type=int, help="Nowa liczba ocen")
    parser.add_argument("--newrate", type=str, help="Ocena do doliczenia")
    parser.add_argument("--deleterate", type=str, help="Ocena do usunięcia")
    parser.add_argument("--fromuser", type=str, help="Nazwa użytkownika")
    parser.add_argument("--saveuserjson", type=str, help="Zapisuje zmodyfikowany JSON użytkownika bezpośrednio do pliku baza_userow.json")
    
    args = parser.parse_args()

    if args.onlycheck:
        testuj_polaczenie_wp()
        return

    if args.fixrank:
        napraw_pozycje_w_wp()
        return

    # Obsługa zapisu zmodyfikowanej bazy użytkowników przesłanej z GUI
    if args.saveuserjson is not None:
        try:
            dane_wejsciowe = json.loads(args.saveuserjson)
            if os.path.exists("baza_userow.json"):
                with open("baza_userow.json", "r", encoding="utf-8") as bf:
                    pelna_baza = json.load(bf)
                
                # Aktualizujemy dane konkretnego usera
                for username, info in dane_wejsciowe.items():
                    pelna_baza[username] = info
                
                with open("baza_userow.json", "w", encoding="utf-8") as bf:
                    json.dump(pelna_baza, bf, ensure_ascii=False, indent=4)
                log_print(f"💾 Pomyślnie zaktualizowano bazę użytkowników w pliku baza_userow.json przez GitHub Actions!")
        except Exception as e:
            log_print(f"❌ Błąd podczas zapisu bazy użytkowników: {e}")
        return

    if args.ep is not None and args.newrate is not None:
        try:
            rate_val = float(args.newrate.replace(',', '.'))
        except ValueError:
            return
        dodanie = {'ep': args.ep, 'rate': rate_val, 'from_user': args.fromuser}
        aktualizuj_tabelę_wp(manualne_dodanie_oceny=dodanie)
        return

    if args.ep is not None and args.deleterate is not None:
        try:
            rate_val = float(args.deleterate.replace(',', '.'))
        except ValueError:
            return
        usuniecie = {'ep': args.ep, 'rate': rate_val, 'from_user': args.fromuser}
        aktualizuj_tabelę_wp(manualne_usunięcie_oceny=usuniecie)
        return

    if args.ep is not None and args.newavg is not None and args.ratnr is not None:
        try:
            avg_val = float(args.newavg.replace(',', '.'))
        except ValueError:
            return
        korekta = {'ep': args.ep, 'newavg': avg_val, 'ratnr': args.ratnr}
        aktualizuj_tabelę_wp(manualna_korekta=korekta)
        return

    dzis = datetime.now().date()
    wczoraj = dzis - timedelta(days=1)

    if not os.path.exists("baza_userow.json"):
        return

    with open("baza_userow.json", "r", encoding="utf-8") as f:
        baza_userow = json.load(f)

    wzorcowa_lista_odcinków = baza_userow.get("bazowa_lista_odcinków", [])
    znalezione_oceny = pobierz_dzisiejsze_i_wczorajsze_oceny(SUBFORUM_URL, wczoraj, dzis)
    
    do_aktualizacji_wp = {}
    zmieniono_bazę_json = False

    for tytul_odc, lista_postow in znalezione_oceny.items():
        for autor, ocena in lista_postow:
            if autor == "bazowa_lista_odcinków":
                continue

            if autor not in baza_userow:
                baza_userow[autor] = {
                    "nieocenione": list(wzorcowa_lista_odcinków),
                    "ocenione": []
                }
                zmieniono_bazę_json = True

            nieocenione = baza_userow[autor].get("nieocenione", [])
            ocenione = baza_userow[autor].get("ocenione", [])
            
            dopasowany_nieoceniony = next((t for t in nieocenione if t.lower() == tytul_odc.lower()), None)
            dopasowany_oceniony = next((t for t in ocenione if t.lower() == tytul_odc.lower()), None)

            if dopasowany_nieoceniony:
                baza_userow[autor]["nieocenione"].remove(dopasowany_nieoceniony)
                baza_userow[autor]["ocenione"].append(dopasowany_nieoceniony)
                zmieniono_bazę_json = True
                
                if dopasowany_nieoceniony not in do_aktualizacji_wp:
                    do_aktualizacji_wp[dopasowany_nieoceniony] = []
                do_aktualizacji_wp[dopasowany_nieoceniony].append(ocena)

    if zmieniono_bazę_json:
        with open("baza_userow.json", "w", encoding="utf-8") as f:
            json.dump(baza_userow, f, ensure_ascii=False, indent=4)
        if do_aktualizacji_wp:
            aktualizuj_tabelę_wp(slownik_aktualizacji=do_aktualizacji_wp)

if __name__ == "__main__":
    main()
