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
# Niestandardowy token bezpieczeństwa omijający blokady nagłówków serwera
WP_CUSTOM_TOKEN = "fba8U57HyTvulhlJRh5uMdRe"                         

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) KiepskiUpdater/2.0'
}

# Pomocniczy słownik nagłówków autoryzacyjnych do zapytań HTTP
API_HEADERS = {
    'X-Auth-Token': WP_CUSTOM_TOKEN
}

# ==============================================================================
# SYSTEM LOGOWANIA DO PLIKU I KONSOLI
# ==============================================================================

def log_print(komunikat):
    """Wypisuje komunikat w konsoli oraz dopisuje go do pliku log.log z znacznikiem czasu."""
    print(komunikat)
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    try:
        with open("log.log", "a", encoding="utf-8") as f:
            f.write(f"{timestamp} {komunikat}\n")
    except Exception as e:
        print(f"⚠️ Nie udało się zapisać do pliku log.log: {e}")

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
    """Sprawdza, czy tytuł odcinka pasuje do podanego argumentu (--ep).
       Obsługuje zarówno numery (zapobiegając myleniu 22 z 220), jak i nazwy tekstowe.
    """
    szukany_czysty = szukany_ep_str.strip()
    
    # Jeśli szukana fraza jest liczbą (np. "22" lub "022")
    if szukany_czysty.isdigit():
        szukany_ep_int = int(szukany_czysty)
        # Sprawdzenie liczby na samym początku tytułu
        m = re.match(r'^0*(\d+)', tytul_tekst.strip())
        if m:
            try:
                if int(m.group(1)) == szukany_ep_int:
                    return True
            except ValueError:
                pass
        
        # Szukanie jako osobnej liczby otoczonej nie-cyframi wewnątrz ciągu
        wzorzec = r'(?<!\d)0*' + str(szukany_ep_int) + r'(?!\d)'
        if re.search(wzorzec, tytul_tekst):
            return True
    else:
        # Jeśli to tekst (np. "Wielki bal"), szukamy dopasowania frazy w tytule (bez uwzględniania wielkości liter)
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
                    
                    # Sprawdzamy czy post mieści się w buforze (od wczoraj do dzisiaj)
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
    """Zapisuje lub nadpisuje plik kopii zapasowej przed zmodyfikowaniem tabeli."""
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
            data = res.json().get('data', [])
            log_print(f"📊 Pobrano tabelę pomyślnie. Liczba wierszy w tabeli: {len(data)}")
            return True
        elif res.status_code == 401:
            log_print("❌ Błąd 401: Nieautoryzowany dostęp. Sprawdź poprawność tokena w nagłówku.")
            return False
        else:
            log_print(f"❌ Otrzymano kod statusu: {res.status_code} - {res.text}")
            return False
    except Exception as e:
        log_print(f"❌ Błąd połączenia: {e}")
        return False

def napraw_pozycje_w_wp():
    """Pobiera tabelę z WordPressa, przelicza pozycje ex aequo na podstawie obecnych średnich i zapisuje."""
    TABLE_ID = 116
    get_url = f"{WP_URL.rstrip('/')}/wp-json/custom/v1/get-table/{TABLE_ID}"
    log_print("🛠️ Uruchamianie weryfikacji i naprawy pozycji ex aequo w tabeli WP...")
    
    res = requests.get(get_url, headers=API_HEADERS)
    if res.status_code != 200:
        log_print(f"❌ Nie udało się pobrać tabeli z API (Status: {res.status_code}) - {res.text}")
        return False
        
    rows = res.json().get('data', [])
    if not rows or len(rows) < 2:
        log_print("❌ Tabela jest pusta lub nie zawiera danych!")
        return False

    # Tworzymy backup przed nadpisaniem pozycji
    zrob_backup_przed_zmiana(rows)

    idx_lp = 0
    idx_srednia = 1
    idx_liczba = 3

    naglowek = rows[0]
    wiersze_danych = rows[1:]

    dane_obliczone = []

    for wiersz in wiersze_danych:
        if len(wiersz) <= idx_liczba:
            continue

        txt_srednia = str(wiersz[idx_srednia])
        clean_srednia = re.sub(r'[^\d\.]', '', txt_srednia.replace(',', '.'))
        srednia_val = round(float(clean_srednia), 2) if clean_srednia else 0.0

        dane_obliczone.append({
            'srednia': srednia_val,
            'pelny_wiersz': wiersz  
        })

    # Sortowanie malejąco po zaokrąglonej średniej
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
        
        if idx_lp is not None and len(wiersz) > idx_lp:
            wiersz[idx_lp] = bezpieczna_aktualizacja_komorki(wiersz[idx_lp], pozycja_w_rankingu)
            
        nowe_wiersze_tablepress.append(wiersz)

    update_url = f"{WP_URL.rstrip('/')}/wp-json/custom/v1/update-table"
    payload = {'table_id': TABLE_ID, 'data': nowe_wiersze_tablepress}

    res_post = requests.post(update_url, json=payload, headers=API_HEADERS)
    
    if res_post.status_code == 200:
        log_print("✅ Pomyślnie zweryfikowano i naprawiono pozycje ex aequo w tabeli WordPress!")
        return True
    else:
        log_print(f"❌ Błąd zapisu pozycji do TablePress: {res_post.status_code} - {res_post.text}")
        return False

def aktualizuj_tabelę_wp(slownik_aktualizacji=None, manualna_korekta=None, manualne_dodanie_oceny=None):
    TABLE_ID = 116
    if slownik_aktualizacji is None:
        slownik_aktualizacji = {}
    
    get_url = f"{WP_URL.rstrip('/')}/wp-json/custom/v1/get-table/{TABLE_ID}"
    res = requests.get(get_url, headers=API_HEADERS)
    
    if res.status_code != 200:
        log_print(f"❌ Nie udało się pobrać tabeli z API (Status: {res.status_code}) - {res.text}")
        return False
        
    rows = res.json().get('data', [])
    if not rows or len(rows) < 2:
        log_print("❌ Tabela jest pusta lub nie zawiera danych!")
        return False

    # SPRAWDZENIE: Jeśli brakuje pliku backupu w repo, utwórz go od razu jako stan początkowy
    if not os.path.exists("tabela_backup.json"):
        log_print("ℹ️ Nie znaleziono pliku kopii zapasowej w repozytorium. Tworzę początkowy backup tabeli...")
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

        # 1. RĘCZNA KOREKTA CAŁEJ ŚREDNIEJ I LICZBY OCEN (--ep, --newavg, --ratnr)
        if manualna_korekta:
            szukany_ep_str = str(manualna_korekta['ep'])
            if pasuje_do_odcinka(tytul_tekst, szukany_ep_str):
                nowa_srednia = round(manualna_korekta['newavg'], 2)
                nowa_liczba_ocen = manualna_korekta['ratnr']
                zmieniono = True
                log_print(f"🛠️ RĘCZNA KOREKTA dla odcinka '{tytul_tekst}': Ustawiono średnią na {formatuj_liczbe(nowa_srednia)} i liczbę ocen na {nowa_liczba_ocen}")

        # 2. RĘCZNE DOLICZENIE POJEDYNCZEJ OCENY (--ep, --newrate)
        if manualne_dodanie_oceny:
            szukany_ep_str = str(manualne_dodanie_oceny['ep'])
            if pasuje_do_odcinka(tytul_tekst, szukany_ep_str):
                dodatkowa_ocena = manualne_dodanie_oceny['rate']
                nowa_liczba_ocen = stara_liczba_ocen + 1
                nowa_suma = stara_suma + dodatkowa_ocena
                nowa_srednia = round((nowa_suma / nowa_liczba_ocen) if nowa_liczba_ocen > 0 else 0.0, 2)
                zmieniono = True
                log_print(f"➕ RĘCZNE DOLICZENIE OCENY dla odcinka '{tytul_tekst}': Doliczono ocenę {dodatkowa_ocena}. Nowa liczba ocen: {nowa_liczba_ocen}, Nowa średnia: {formatuj_liczbe(nowa_srednia)}")

        # 3. STANDARDOWA AKTUALIZACJA Z FORUM
        for tytul_odcinka_forum, list_ocen in slownik_aktualizacji.items():
            forum_czysty = tytul_odcinka_forum.strip()

            if forum_czysty.lower() == tytul_tekst.lower() or forum_czysty.lower() in tytul_tekst.lower():
                dodatkowa_suma = sum(list_ocen)
                dodatkowa_liczba = len(list_ocen)

                nowa_liczba_ocen = stara_liczba_ocen + dodatkowa_liczba
                nowa_suma = stara_suma + dodatkowa_suma
                nowa_srednia = round((nowa_suma / nowa_liczba_ocen) if nowa_liczba_ocen > 0 else 0.0, 2)

                zmieniono = True
                log_print(f"🎯 PODGLĄD DANYCH dla '{tytul_odcinka_forum}':")
                log_print(f"   • Przed: Liczba ocen={stara_liczba_ocen}, Średnia={stara_srednia}, Suma={stara_suma:.2f}")
                log_print(f"   • Po:    Liczba ocen={nowa_liczba_ocen}, Średnia={formatuj_liczbe(nowa_srednia)}, Suma={nowa_suma:.2f}")
                break

        dane_obliczone.append({
            'srednia': nowa_srednia,
            'liczba_ocen': nowa_liczba_ocen,
            'pelny_wiersz': wiersz  
        })

    if not zmieniono and not manualna_korekta and not manualne_dodanie_oceny:
        log_print("ℹ️ Brak odcinków do aktualizacji.")
        return True

    # Tworzymy kopię zapasową przed faktycznym nadpisaniem danych w WP
    zrob_backup_przed_zmiana(rows)

    # Sortowanie ex aequo po zaokrąglonej średniej
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
        
        if idx_lp is not None and len(wiersz) > idx_lp:
            wiersz[idx_lp] = bezpieczna_aktualizacja_komorki(wiersz[idx_lp], pozycja_w_rankingu)
        if len(wiersz) > idx_srednia:
            wiersz[idx_srednia] = bezpieczna_aktualizacja_komorki(wiersz[idx_srednia], formatuj_liczbe(item['srednia']))
        if len(wiersz) > idx_liczba:
            wiersz[idx_liczba] = bezpieczna_aktualizacja_komorki(wiersz[idx_liczba], item['liczba_ocen'])
            
        nowe_wiersze_tablepress.append(wiersz)

    update_url = f"{WP_URL.rstrip('/')}/wp-json/custom/v1/update-table"
    payload = {'table_id': TABLE_ID, 'data': nowe_wiersze_tablepress}

    res_post = requests.post(update_url, json=payload, headers=API_HEADERS)
    
    if res_post.status_code == 200:
        log_print("✅ Pomyślnie zaktualizowano tabelę i przeliczono ranking ex aequo!")
        return True
    else:
        log_print(f"❌ Błąd zapisu do TablePress: {res_post.status_code} - {res_post.text}")
        return False
        
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
    parser = argparse.ArgumentParser(description="Kiepscy Ranking Updater")
    parser.add_argument("--onlycheck", action="store_true", help="Tylko test połączenia z WP API")
    parser.add_argument("--fixrank", action="store_true", help="Sprawdza i naprawia pozycje ex aequo w tabeli WP bez zmiany ocen")
    parser.add_argument("--ep", type=str, help="Numer lub tytuł odcinka (np. 22, 552 lub 'Wielki bal')")
    parser.add_argument("--newavg", type=str, help="Nowa średnia ocena (np. 8,82)")
    parser.add_argument("--ratnr", type=int, help="Nowa liczba ocen (np. 14)")
    parser.add_argument("--newrate", type=str, help="Pojedyncza ocena do doliczenia (np. 7)")
    
    args = parser.parse_args()

    if args.onlycheck:
        testuj_polaczenie_wp()
        return

    if args.fixrank:
        napraw_pozycje_w_wp()
        return

    # Obsługa ręcznego doliczenia pojedynczej oceny (--ep, --newrate)
    if args.ep is not None and args.newrate is not None:
        try:
            rate_val = float(args.newrate.replace(',', '.'))
        except ValueError:
            log_print("❌ Błąd: Parametr --newrate musi być poprawną liczbą (np. 7)")
            return

        log_print(f"➕ Uruchamianie doliczenia oceny {rate_val} dla odcinka '{args.ep}'...")
        dodanie = {
            'ep': args.ep,
            'rate': rate_val
        }
        aktualizuj_tabelę_wp(manualne_dodanie_oceny=dodanie)
        return

    # Obsługa ręcznej korekty całej średniej i liczby ocen (--ep, --newavg, --ratnr)
    if args.ep is not None and args.newavg is not None and args.ratnr is not None:
        try:
            avg_val = float(args.newavg.replace(',', '.'))
        except ValueError:
            log_print("❌ Błąd: Parametr --newavg musi być poprawną liczbą (np. 8,82 lub 8.82)")
            return

        log_print(f"🛠️ Uruchamianie ręcznej korekty dla odcinka '{args.ep}'...")
        korekta = {
            'ep': args.ep,
            'newavg': avg_val,
            'ratnr': args.ratnr
        }
        aktualizuj_tabelę_wp(manualna_korekta=korekta)
        return

    # Standardowy obieg automatyczny (bufor: wczoraj oraz dzisiaj)
    dzis = datetime.now().date()
    wczoraj = dzis - timedelta(days=1)
    
    log_print(f"🚀 Uruchamianie aktualizatora. Szukam ocen z zakresu: {wczoraj} do {dzis}")

    if not os.path.exists("baza_userow.json"):
        log_print("❌ Brak pliku baza_userow.json w repozytorium!")
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
                log_print(f"🆕 Wykryto nowego użytkownika: '{autor}'. Automatyczne dodawanie do bazy z bazową pulą odcinków.")
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
                
                log_print(f"✨ Akceptacja oceny: {autor} ocenił '{dopasowany_nieoceniony}' na {ocena}/10")
            elif dopasowany_oceniony:
                log_print(f"⚠️ Odrzucono ocenę: {autor} ocenił '{tytul_odc}', ale ma już ten odcinek na liście ocenionych (ocena nie została policzona ponownie).")
            else:
                log_print(f"ℹ️ Użytkownik {autor} napisał post w temacie '{tytul_odc}', ale ten odcinek nie figuruje w bazie wzorcowej.")

    if zmieniono_bazę_json:
        with open("baza_userow.json", "w", encoding="utf-8") as f:
            json.dump(baza_userow, f, ensure_ascii=False, indent=4)
        log_print("💾 Zapisano zaktualizowany plik baza_userow.json.")

        if do_aktualizacji_wp:
            aktualizuj_tabelę_wp(slownik_aktualizacji=do_aktualizacji_wp)
    else:
        log_print("😴 Brak nowych, ważnych ocen z wczorajszego lub dzisiejszego dnia.")
        
        # Nawet jeśli nie ma nowych ocen, sprawdzamy czy w repo jest backup. 
        # Jeśli go brakuje, wymuszamy jego utworzenie poprzez pobranie stanu z WP.
        if not os.path.exists("tabela_backup.json"):
            log_print("🛡️ Wykryto brak pliku 'tabela_backup.json'. Pobieram stan początkowy z WP...")
            get_url = f"{WP_URL.rstrip('/')}/wp-json/custom/v1/get-table/{TABLE_ID}" if 'TABLE_ID' in globals() else f"{WP_URL.rstrip('/')}/wp-json/custom/v1/get-table/116"
            res = requests.get(get_url, headers=API_HEADERS)
            if res.status_code == 200:
                rows = res.json().get('data', [])
                if rows:
                    zrob_backup_przed_zmiana(rows)

if __name__ == "__main__":
    main()
