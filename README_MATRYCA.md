# Aktualizacja: Obsługa matrycy przycisków 4x4

## Co się zmieniło?

Kod został zaktualizowany aby obsługiwać **matrycę przycisków 4x4** z 8 wyjściami zamiast 11 osobnych przycisków.

### Zmiany w kodzie:

1. **Nowe importy:**
   - Dodano `import RPi.GPIO as GPIO` dla bezpośredniej obsługi GPIO

2. **Nowa konfiguracja pinów (linie 33-59):**
   ```python
   COL_PINS = [19, 13, 6, 5]     # Kolumny C0-C3 jako outputs
   ROW_PINS = [17, 22, 23, 27]   # Rzędy R0-R3 jako inputs
   BUTTON_MAP = {...}             # Mapowanie pozycji do funkcji
   ```

3. **Nowe funkcje obsługi matrycy (linie 3180-3262):**
   - `init_matrix()` - Inicjalizacja GPIO dla matrycy
   - `scan_matrix()` - Skanowanie matrycy i wykrywanie naciśnięć
   - `check_matrix_buttons()` - Wywołanie handlerów dla naciśniętych przycisków
   - `is_button_pressed()` - Sprawdzanie stanu przycisku (dla continuous input)

4. **Zaktualizowana inicjalizacja (linie 4529-4543):**
   - Zastąpiono tworzenie obiektów `Button` przez `init_matrix()`
   - Przypisanie handlerów przez słownik `button_handlers`

5. **Zaktualizowana główna pętla (linia 4569):**
   - Dodano `check_matrix_buttons()` - skanowanie matrycy w każdej iteracji
   - Zamieniono `btn_*.is_pressed` na `is_button_pressed('NAME')`

6. **Zaktualizowany cleanup (linie 4513-4517):**
   - Dodano `GPIO.cleanup()` przy wyjściu

## Jak używać?

### 1. Podłącz matrycę zgodnie z instrukcją

Zobacz pliki:
- **[INSTRUKCJA_MATRYCA_4x4.md](INSTRUKCJA_MATRYCA_4x4.md)** - szczegółowa instrukcja
- **[schemat_polaczenia_matryca.txt](schemat_polaczenia_matryca.txt)** - schemat ASCII

### 2. Przetestuj połączenie

```bash
python3 test_matryca.py
```

Ten skrypt wyświetli wszystkie naciśnięte przyciski i pomoże zweryfikować połączenia.

### 3. Uruchom główny program

```bash
python3 kontrola_wersji.py
```

Program automatycznie zainicjalizuje matrycę i będzie gotowy do użycia.

## Schemat podłączenia (skrócona wersja)

```
Matryca → Raspberry Pi GPIO
━━━━━━━━━━━━━━━━━━━━━━━━━━
C3 → GPIO 5  (pin 29)
C2 → GPIO 6  (pin 31)
C1 → GPIO 13 (pin 33)
C0 → GPIO 19 (pin 35)
━━━━━━━━━━━━━━━━━━━━━━━━━━
R0 → GPIO 17 (pin 11)
R1 → GPIO 22 (pin 15)
R2 → GPIO 23 (pin 16)
R3 → GPIO 27 (pin 13)
```

## Układ przycisków

```
      C3      C2      C1      C0
   ┌───────┬───────┬───────┬───────┐
R0 │  UP   │ MINUS │ PLUS  │ MENU  │
   ├───────┼───────┼───────┼───────┤
R1 │ LEFT  │  OK   │ RIGHT │       │
   ├───────┼───────┼───────┼───────┤
R2 │ DOWN  │DELETE │VIDEOS │       │
   ├───────┼───────┼───────┼───────┤
R3 │RECORD │       │       │       │
   └───────┴───────┴───────┴───────┘
```

## Dostosowanie układu przycisków

Jeśli fizyczny układ Twojej matrycy jest inny, możesz go dostosować edytując `BUTTON_MAP` w pliku `kontrola_wersji.py` (linia 47):

```python
BUTTON_MAP = {
    (row, col): 'FUNCTION_NAME',
    # przykład:
    (0, 3): 'UP',      # Przycisk w rzędzie 0, kolumnie 3
    (1, 2): 'OK',      # Przycisk w rzędzie 1, kolumnie 2
    # ...
}
```

Numeracja:
- Rzędy: 0, 1, 2, 3 (od góry do dołu)
- Kolumny: 0, 1, 2, 3 (od prawej do lewej - C0, C1, C2, C3)

## Dostępne funkcje przycisków

- `RECORD` - Start/stop nagrywania
- `OK` - Potwierdzenie / pauza
- `VIDEOS` - Przeglądarka filmów
- `DELETE` - Usuń film
- `UP` - Nawigacja w górę
- `DOWN` - Nawigacja w dół
- `LEFT` - Nawigacja w lewo / cofanie
- `RIGHT` - Nawigacja w prawo / przewijanie
- `MENU` - Otwórz menu ustawień
- `PLUS` - Zoom in
- `MINUS` - Zoom out

## Debugowanie

### Przyciski nie reagują

1. Sprawdź logi podczas uruchamiania:
   ```
   [MATRIX] Inicjalizacja matrycy 4x4...
   [OK] Matryca 4x4 OK
   ```

2. Jeśli widzisz błędy GPIO, sprawdź:
   - Czy piny nie są zajęte przez inną usługę
   - Czy nie ma konfliktów numeracji (BCM vs BOARD)
   - Czy Raspberry Pi 5 ma włączone GPIO

3. Użyj skryptu testowego:
   ```bash
   python3 test_matryca.py
   ```

### Złe przyciski są wykrywane

To oznacza że fizyczny układ matrycy jest inny niż założony w kodzie.

**Rozwiązanie:**

1. Uruchom `test_matryca.py`
2. Naciśnij każdy przycisk i zanotuj co jest wykrywane
3. Dostosuj `BUTTON_MAP` w kodzie głównym

### Ghost buttons (fałszywe naciśnięcia)

Jeśli przyciski reagują na dotknięcie lub wykrywane są dodatkowe naciśnięcia:

1. **Zwiększ czas debounce:**
   W linii 3221-3222 zmień `0.3` na większą wartość (np. `0.5`)

2. **Dodaj diody:**
   Podłącz diody 1N4148 w szereg z każdym przyciskiem (anoda do kolumny)

3. **Sprawdź połączenia:**
   Upewnij się że przewody są dobrze podłączone i nie ma zwarć

## Zalety matrycy 4x4

✓ Tylko 8 pinów zamiast 11
✓ Oszczędność GPIO
✓ Łatwiejsze okablowanie
✓ Możliwość rozbudowy do 16 przycisków

## Różnice vs poprzednia wersja

| Cecha | Stara wersja | Nowa wersja (matryca) |
|-------|-------------|----------------------|
| Liczba pinów GPIO | 11 | 8 |
| Typ połączenia | Bezpośrednie | Matryca |
| Biblioteka GPIO | gpiozero | RPi.GPIO |
| Debounce | Sprzętowy (gpiozero) | Programowy |
| Continuous input | `btn.is_pressed` | `is_button_pressed()` |

## Pliki projektu

- **kontrola_wersji.py** - Główny program (zaktualizowany)
- **INSTRUKCJA_MATRYCA_4x4.md** - Szczegółowa instrukcja podłączenia
- **schemat_polaczenia_matryca.txt** - Wizualny schemat połączeń
- **test_matryca.py** - Skrypt testowy
- **README_MATRYCA.md** - Ten plik (podsumowanie)

## Wsparcie

W razie problemów:
1. Sprawdź logi w konsoli
2. Uruchom skrypt testowy `test_matryca.py`
3. Sprawdź fizyczne połączenia
4. Zweryfikuj układ przycisków w `BUTTON_MAP`

---

**Ostatnia aktualizacja:** 2025-12-02
**Kompatybilność:** Raspberry Pi 5 (powinno działać też na Pi 3/4)
