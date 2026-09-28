import requests
from bs4 import BeautifulSoup
import re
import time
import os
import json
from urllib.parse import urljoin, parse_qs, urlparse

# --- KONFIGURACJA ---
URL_SUBFORUM = "https://forum.kiepscy.org.pl/viewforum.php?f=8" 
URL_WORDPRESS = "http://kiepscy-test.local" # Adres Twojej strony (na Localu lub docelowy)
TAJNY_TOKEN = "MojeTajneHasloKiepscy2026!" # Taki sam jak w Code Snippets
PLIK_BAZY = "baza_historia.json"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/115.0.0.0 Safari/537.36'
}

def analizuj_tekst_postu(tekst_postu):
    """
    Wyłapuje WYŁĄCZNIE oceny znajdujące się na samym końcu posta.
    Obsługuje formaty z BBCode (np. [b]6/10[/b]), połówki (6,5/10 -> zaokrągla w dół do 6)
    oraz ignoruje oceny słowne. Zwraca cyfrę (0-10) lub None.
    """
    if not tekst_postu:
        return None

    # 1. Usuwanie tagów BBCode
    tekst_czysty = re.sub(r'\[/?[a-zA-Z0-9\=\#\s\"\'\:\.\-\_]+\]', '', tekst_postu)
    
    # 2. Ostatnie ~120 znaków posta
    koncowka_tekstu = tekst_czysty.strip()[-120:].lower()

    # 3. Zaokrąglanie połówkowych ocen w dół (np. 6,5 -> 6, 8.5 -> 8)
    koncowka_tekstu = re.sub(r'(\d+)[\,\.]5', r'\1', koncowka_tekstu)

    # 4. Wzorzec dla ocen w formacie X/10 lub X na 10
    wzorzec = r'(\d{1,2})[\s\-\+\*]*(?:\/|na)\s*10\b'
    dopasowania = re.findall(wzorzec, koncowka_tekstu)
    
    if dopasowania:
        try:
            ocena = int(dopasowania[-1])
            if 0 <= ocena <= 10:
                return ocena
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

def wczytaj_baze():
    if os.path.exists(PLIK_BAZY):
        with open(PLIK_BAZY, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def zapisz_baze(baza):
    with open(PLIK_BAZY, 'w', encoding='utf-8') as f:
        json.dump(baza, f, ensure_ascii=False, indent=2)

def pobierz_tematy_z_subforum(url_startowy):
    odwiedzone_subfora = set()
    do_odwiedzenia_subfora = [url_startowy]
    linki_tematow = []

    while do_odwiedzenia_subfora:
        curr_sub = do_odwiedzenia_subfora.pop(0)
        curr_sub_clean = czysc_url(curr_sub)
        if curr_sub_clean in odwiedzone_subfora: continue
        odwiedzone_subfora.add(curr_sub_clean)

        start = 0
        while True:
            separator = "&" if "?" in curr_sub else "?"
            url_strony = f"{curr_sub}{separator}start={start}" if start > 0 else curr_sub
            try:
                res = requests.get(url_strony, headers=HEADERS, timeout=10)
                if res.status_code != 200: break
            except: break

            soup = BeautifulSoup(res.text, 'html.parser')
            for a in soup.find_all('a', class_='forumtitle'):
                href = urljoin(url_strony, a.get('href'))
                href_clean = czysc_url(href)
                if href_clean not in odwiedzone_subfora and href_clean not in do_odwiedzenia_subfora:
                    do_odwiedzenia_subfora.append(href)

            znaleziono = False
            for a in soup.find_all('a', class_='topictitle'):
                href = urljoin(url_strony, a.get('href'))
                href_clean = czysc_url(href)
                if href_clean not in linki_tematow:
                    linki_tematow.append(href_clean)
                    znaleziono = True

            strefa_paginacji = soup.find('div', class_='pagination')
            ma_nastepna = False
            if strefa_paginacji and (strefa_paginacji.find('a', text=re.compile(r'Następna|Next|>', re.I)) or f"start={start + 25}" in res.text):
                ma_nastepna = True

            if not ma_nastepna or not znaleziono: break
            start += 25
            time.sleep(0.2)

    return linki_tematow

def skanuj_i_wyslij():
    # 1. Wczytujemy dotychczasową bazę głosów
    baza_glosow = wczytaj_baze()
    tematy = pobierz_tematy_z_subforum(URL_SUBFORUM)

    # 2. Skanowanie forum pod kątem nowych ocen
    for url_t in tematy:
        start = 0
        tytul_odcinka = ""

        while True:
            separator = "&" if "?" in url_t else "?"
            url_strony = f"{url_t}{separator}start={start}" if start > 0 else url_t
            try:
                res = requests.get(url_strony, headers=HEADERS, timeout=10)
                if res.status_code != 200: break
            except: break

            soup = BeautifulSoup(res.text, 'html.parser')
            if not tytul_odcinka:
                h2 = soup.find('h2', class_='topic-title')
                tytul_odcinka = h2.text.strip() if h2 else "Odcinek"
                if "ogólnie o sezonie" in tytul_odcinka.lower() or "ogolnie o sezonie" in tytul_odcinka.lower():
                    break

            tytul_clean = re.sub(r'\s+', ' ', tytul_odcinka).strip()
            if tytul_clean not in baza_glosow:
                baza_glosow[tytul_clean] = {}

            posty_html = soup.find_all('div', class_='post', id=re.compile(r'^p\d+'))
            if not posty_html: break

            for post in posty_html:
                autor_tag = post.find(class_=re.compile(r'username'))
                autor = autor_tag.text.strip() if autor_tag else "Anonim"
                tresc_tag = post.find('div', class_='content')
                if tresc_tag:
                    for z in tresc_tag.find_all(['blockquote', 'cite']): z.decompose()
                    for k in tresc_tag.find_all(class_=re.compile(r'quote|uncited', re.I)): k.decompose()
                    tresc = re.sub(r' +', ' ', tresc_tag.text.strip())
                else: tresc = ""

                ocena_num = analizuj_tekst_postu(tresc) if tresc else None
                
                # Zapisujemy ocenę w bazie danych (nowa ocena tego usera nadpisze starą!)
                if ocena_num is not None:
                    baza_glosow[tytul_clean][autor] = ocena_num

            strefa = soup.find('div', class_='pagination')
            if not strefa or not (strefa.find('a', text=re.compile(r'Następna|Next|>', re.I)) or f"start={start + 25}" in res.text):
                break
            start += 25
            time.sleep(0.2)

    # 3. Zapisujemy stan bazy do pliku (by przetrwał do następnego uruchomienia)
    zapisz_baze(baza_glosow)

    # 4. Przeliczanie sum, liczby głosów i nowych średnich
    rankings = []
    for tytul_odc, glosy_userow in baza_glosow.items():
        if glosy_userow:
            suma_punktow = sum(glosy_userow.values())
            liczba_ocen = len(glosy_userow)
            srednia = suma_punktow / liczba_ocen
        else:
            suma_punktow = 0.0
            liczba_ocen = 0
            srednia = 0.0

        rankings.append({
            'tytul': tytul_odc,
            'srednia': srednia,
            'liczba': liczba_ocen,
            'suma': suma_punktow
        })

    # Sortowanie: najpierw po średniej, a przy remisach po liczbie ocen
    rankings.sort(key=lambda x: (x['srednia'], x['liczba']), reverse=True)

    # 5. Budowanie 5-kolumnowej tabeli dla TablePress
    tabela_data = [["Miejsce", "Średnia", "Tytuł", "Liczba ocen", "Suma ocen"]]

    for miejsce, item in enumerate(rankings, 1):
        srednia_fmt = f"{item['srednia']:.2f}".replace('.', ',') if item['srednia'] > 0 else "Brak"
        tabela_data.append([
            str(miejsce),
            srednia_fmt,
            item['tytul'],
            str(item['liczba']),
            str(item['suma'])
        ])

    # 6. Wysyłka gotowej tabeli do WordPressa
    endpoint = f"{URL_WORDPRESS.rstrip('/')}/wp-json/ranking/v1/update-table/"
    headers = {'x-auth-token': TAJNY_TOKEN, 'Content-Type': 'application/json'}
    
    try:
        res = requests.post(endpoint, json={'data': tabela_data}, headers=headers, timeout=30)
        print("Wynik wysyłki do WordPressa:", res.status_code, res.text)
    except Exception as e:
        print("Błąd podczas połączenia z WordPressem:", e)

if __name__ == '__main__':
    skanuj_i_wyslij()
