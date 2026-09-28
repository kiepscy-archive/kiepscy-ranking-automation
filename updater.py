import os
import re
import json
import time
import requests
from datetime import datetime, timedelta
from urllib.parse import urljoin, parse_qs, urlparse
from bs4 import BeautifulSoup

# ==============================================================================
# KONFIGURACJA (DANE WPISANE BEZPOŚREDNIO W KODZIE)
# ==============================================================================

SUBFORUM_URL = "https://forum.kiepscy.org.pl/viewforum.php?f=8"  # Wklej link do podforum
WP_URL = "kiepscy-test.local"                 # Adres Twojej strony WP
WP_PAGE_ID = 6                                              # ID strony z tabelką

# Dane do logowania w WordPress (Basic Auth)
WP_USER = "kacrudy"                                       # Login konta
WP_APP_PASS = "Reksiomiastosekretow500_game"                         # Hasło / Hasło aplikacji

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) KiepskiUpdater/2.0'
}

MIESIACE = {
    'sty': 1, 'lut': 2, 'mar': 3, 'kwi': 4, 'maj': 5, 'cze': 6,
    'lip': 7, 'sie': 8, 'wrz': 9, 'paź': 10, 'paz': 10, 'lis': 11, 'gru': 12,
    'stycznia': 1, 'lutego': 2, 'marca': 3, 'kwietnia': 4, 'maja': 5, 'czerwca': 6,
    'lipca': 7, 'sierpnia': 8, 'września': 9, 'wrzesnia': 9, 'października': 10,
    'listopada': 11, 'grudnia': 12
}

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
    """Parsuje datę z tekstu nagłówka posta lub kolumny ostatniego posta."""
    tekst = znacznik_czasu.lower()
    
    # Obsługa relatywnych dat w phpBB (np. "Dzisiaj, 14:20", "Wczoraj, 22:10")
    dzisiaj_date = datetime.now().date()
    if "dzisiaj" in tekst:
        return dzisiaj_date
    if "wczoraj" in tekst:
        return dzisiaj_date - timedelta(days=1)

    m = re.search(r'(\d{1,2})\s+([a-ząśężźćńł]+)\s+(\d{4})', tekst)
    if m:
        dzien = int(m.group(1))
        miesiac_str = m.group(2)
        rok = int(m.group(3))
        miesiac = MIESIACE.get(miesiac_str)
        if miesiac:
            try:
                return datetime(rok, miesiac, dzien).date()
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

# ==============================================================================
# SZYBKI SCRAPER (WYŁĄCZNIE DLA AKTYWNYCH TEMATÓW)
# ==============================================================================

def pobierz_aktywne_tematy(url_subforum, cel_data):
    """
    Skanuje listy wątków i filtrowaniem odrzuca te,
    w których ostatni post jest starszy niż szukana data.
    """
    odwiedzone = set()
    do_odwiedzenia = [url_subforum]
    aktywne_tematy = []

    print("⚡ Szybkie skanowanie listy tematów pod kątem nowej aktywności...")

    while do_odwiedzenia:
        curr = do_odwiedzenia.pop(0)
        curr_clean = czysc_url(curr)
        if curr_clean in odwiedzone:
            continue
        odwiedzone.add(curr_clean)

        try:
            res = requests.get(curr, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # Subfora / Sezony
            for a in soup.find_all('a', class_='forumtitle'):
                do_odwiedzenia.append(urljoin(curr, a.get('href')))
            
            # Przeglądanie wierszy z tematami na liście
            wiersze_tematow = soup.find_all('li', class_=re.compile(r'row'))
            for row in wiersze_tematow:
                a_topic = row.find('a', class_='topictitle')
                if not a_topic:
                    continue

                # Szukamy informacji o OSTATNIM POŚCIE w wierszu
                lastpost_span = row.find(class_=re.compile(r'lastpost'))
                data_ostatniego_posta = None
                if lastpost_span:
                    data_ostatniego_posta = parsuj_datę_postu(lastpost_span.text)

                # FILTR: Bierzemy temat TYLKO jeśli data ostatniego wpisu jest równa cel_data
                # lub ewentualnie nowsza (dzisiejsza)
                if data_ostatniego_posta and data_ostatniego_posta >= cel_data:
                    href = urljoin(curr, a_topic.get('href'))
                    clean_href = czysc_url(href)
                    if clean_href not in aktywne_tematy:
                        aktywne_tematy.append(clean_href)

        except Exception as e:
            print(f"⚠️ Błąd pobierania listy {curr}: {e}")

    return aktywne_tematy

def pobierz_wczorajsze_oceny(url_subforum, cel_data):
    # 1. Pobieramy TYLKO aktywne wątki
    linki_tematow = pobierz_aktywne_tematy(url_subforum, cel_data)

    if not linki_tematow:
        print("⚡ Brak jakiejkolwiek aktywności w tematach z wczorajszego dnia. Koniec.")
        return {}

    print(f"🎯 Znaleziono tylko {len(linki_tematow)} temat(y) z nową aktywnością. Pobieranie postów...")
    nowe_oceny = {}

    # 2. Głębokie skanowanie wyłącznie znalezionych aktywnych tematów
    for url_t in linki_tematow:
        # Przechodzimy od razu do OSTATNIEJ strony wątku, bo tam będą najnowsze posty
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
                    
                    if data_postu != cel_data:
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

                strefa_pagi = soup.find('div', class_='pagination')
                ma_nastepna = False
                if strefa_pagi and (strefa_pagi.find('a', text=re.compile(r'Następna|Next|>', re.I)) or f"start={start + 25}" in res.text):
                    ma_nastepna = True

                if not ma_nastepna:
                    break
                start += 25
                time.sleep(0.2)

            except Exception as e:
                print(f"⚠️ Błąd podczas skanowania {url_page}: {e}")
                break

    return nowe_oceny

# ==============================================================================
# OBSŁUGA WORDPRESS API & EDYCJA TABELI HTML
# ==============================================================================

def aktualizuj_tabelę_wp(slownik_aktualizacji):
    api_url = f"{WP_URL.rstrip('/')}/wp-json/wp/v2/pages/{WP_PAGE_ID}"
    
    res = requests.get(api_url, auth=(WP_USER, WP_APP_PASS))
    if res.status_code != 200:
        print(f"❌ Nie udało się pobrać strony z WP (Status: {res.status_code})")
        return False
    
    data = res.json()
    html_content = data['content']['rendered']
    soup = BeautifulSoup(html_content, 'html.parser')
    tabela = soup.find('table')
    
    if not tabela:
        print("❌ Nie znaleziono tabeli na stronie WordPress!")
        return False

    zmieniono = False
    wiersze = tabela.find_all('tr')
    for tr in wiersze:
        komorki = tr.find_all(['td', 'th'])
        if len(komorki) < 5:
            continue
        
        tytul_komorki = komorki[2].text.strip()
        
        if tytul_komorki in slownik_aktualizacji:
            list_ocen = slownik_aktualizacji[tytul_komorki]
            
            try:
                stara_liczka_ocen = int(re.sub(r'\D', '', komorki[3].text))
                stara_suma = float(re.sub(r'[^\d\.]', '', komorki[4].text.replace(',', '.')))
            except ValueError:
                continue

            dodatkowa_suma = sum(list_ocen)
            dodatkowa_liczba = len(list_ocen)

            nowa_liczba_ocen = stara_liczka_ocen + dodatkowa_liczba
            nowa_suma = stara_suma + dodatkowa_suma
            nowa_srednia = round(nowa_suma / nowa_liczba_ocen, 2)

            def podmień_treść(komórka, nowa_wartość):
                if komórka.find():
                    komórka.find().string = str(nowa_wartość)
                else:
                    komórka.string = str(nowa_wartość)

            srednia_format = f"{nowa_srednia:.2f}".replace('.', ',')
            suma_format = f"{nowa_suma:.2f}".replace('.', ',')

            podmień_treść(komorki[1], srednia_format)
            podmień_treść(komorki[3], str(nowa_liczba_ocen))
            podmień_treść(komorki[4], suma_format)

            zmieniono = True
            print(f"  • Zaktualizowano odcinek '{tytul_komorki}': Średnia={srednia_format}, Liczba ocen={nowa_liczba_ocen}")

    if zmieniono:
        payload = {'content': str(soup)}
        res_post = requests.post(api_url, json=payload, auth=(WP_USER, WP_APP_PASS))
        if res_post.status_code == 200:
            print("✅ Pomyślnie zaktualizowano stronę na WordPressie!")
            return True
        else:
            print(f"❌ Błąd wysyłania do WP: {res_post.status_code} - {res_post.text}")
            return False
    else:
        print("ℹ️ Brak nowych zmian w tabeli HTML.")
        return True

# ==============================================================================
# GŁÓWNA LOGIKA
# ==============================================================================

def main():
    wczoraj = (datetime.now() - timedelta(days=1)).date()
    print(f"🚀 Uruchamianie szybkiego aktualizatora. Szukam ocen z dnia: {wczoraj}")

    if not os.path.exists("baza_userow.json"):
        print("❌ Brak pliku baza_userow.json w repozytorium!")
        return

    with open("baza_userow.json", "r", encoding="utf-8") as f:
        baza_userow = json.load(f)

    znalezione_oceny = pobierz_wczorajsze_oceny(SUBFORUM_URL, wczoraj)
    
    do_aktualizacji_wp = {}
    zmieniono_bazę_json = False

    for tytul_odc, lista_postow in znalezione_oceny.items():
        for autor, ocena in lista_postow:
            if autor in baza_userow:
                nieocenione = baza_userow[autor].get("nieocenione", [])
                
                dopasowany_tytul = next((t for t in nieocenione if t.lower() == tytul_odc.lower()), None)

                if dopasowany_tytul:
                    baza_userow[autor]["nieocenione"].remove(dopasowany_tytul)
                    baza_userow[autor]["ocenione"].append(dopasowany_tytul)
                    zmieniono_bazę_json = True
                    
                    if dopasowany_tytul not in do_aktualizacji_wp:
                        do_aktualizacji_wp[dopasowany_tytul] = []
                    do_aktualizacji_wp[dopasowany_tytul].append(ocena)
                    
                    print(f"✨ Akceptacja oceny: {autor} ocenił '{dopasowany_tytul}' na {ocena}/10")

    if zmieniono_bazę_json:
        with open("baza_userow.json", "w", encoding="utf-8") as f:
            json.dump(baza_userow, f, ensure_ascii=False, indent=4)
        print("💾 Zapisano zaktualizowany plik baza_userow.json.")

        if do_aktualizacji_wp:
            aktualizuj_tabelę_wp(do_aktualizacji_wp)
    else:
        print("😴 Brak nowych, ważnych ocen z wczorajszego dnia.")

if __name__ == "__main__":
    main()
