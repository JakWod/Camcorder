# Instrukcja podłączenia matrycy przycisków 4x4 do Raspberry Pi 5

## Schemat podłączenia

### Piny matrycy (od góry do dołu):
```
C3 - C2 - C1 - C0 - R0 - R1 - R2 - R3
```

### Połączenia z Raspberry Pi GPIO:

| Pin matrycy | GPIO Raspberry Pi | Typ     | Funkcja        |
|-------------|-------------------|---------|----------------|
| C3          | GPIO 5            | OUTPUT  | Kolumna 3      |
| C2          | GPIO 6            | OUTPUT  | Kolumna 2      |
| C1          | GPIO 13           | OUTPUT  | Kolumna 1      |
| C0          | GPIO 19           | OUTPUT  | Kolumna 0      |
| R0          | GPIO 17           | INPUT   | Rząd 0         |
| R1          | GPIO 22           | INPUT   | Rząd 1         |
| R2          | GPIO 23           | INPUT   | Rząd 2         |
| R3          | GPIO 27           | INPUT   | Rząd 3         |

### Szczegóły podłączenia:

**Kolumny (C0-C3) - OUTPUTS:**
- C0 → GPIO 19 (pin fizyczny 35)
- C1 → GPIO 13 (pin fizyczny 33)
- C2 → GPIO 6  (pin fizyczny 31)
- C3 → GPIO 5  (pin fizyczny 29)

**Rzędy (R0-R3) - INPUTS z pull-up:**
- R0 → GPIO 17 (pin fizyczny 11)
- R1 → GPIO 22 (pin fizyczny 15)
- R2 → GPIO 23 (pin fizyczny 16)
- R3 → GPIO 27 (pin fizyczny 13)

## Układ przycisków w matrycy

```
        C3      C2      C1      C0
      +-------+-------+-------+-------+
R0    |  UP   | MINUS | PLUS  | MENU  |
      +-------+-------+-------+-------+
R1    | LEFT  |  OK   | RIGHT |       |
      +-------+-------+-------+-------+
R2    | DOWN  |DELETE |VIDEOS |       |
      +-------+-------+-------+-------+
R3    |RECORD |       |       |       |
      +-------+-------+-------+-------+
```

### Przypisanie funkcji:

1. **UP** (R0, C3) - Nawigacja w górę
2. **DOWN** (R2, C3) - Nawigacja w dół
3. **LEFT** (R1, C3) - Nawigacja w lewo / cofanie wideo
4. **RIGHT** (R1, C1) - Nawigacja w prawo / przewijanie wideo
5. **OK** (R1, C2) - Potwierdzenie / pauza
6. **MENU** (R0, C0) - Otwórz menu ustawień
7. **RECORD** (R3, C3) - Start/stop nagrywania
8. **VIDEOS** (R2, C1) - Przeglądarka filmów
9. **DELETE** (R2, C2) - Usuń film (w trybie podglądu)
10. **PLUS** (R0, C1) - Zoom in
11. **MINUS** (R0, C2) - Zoom out

## Jak działa matryca?

Matryca 4x4 to 16 przycisków połączonych w siatkę, ale używa tylko 8 pinów zamiast 16.

### Zasada działania:
1. **Kolumny** są ustawione jako **wyjścia** (outputs) i domyślnie są w stanie **HIGH**
2. **Rzędy** są ustawione jako **wejścia** (inputs) z **pull-up resistors** (domyślnie HIGH)
3. Program **skanuje** każdą kolumnę po kolei:
   - Ustawia jedną kolumnę na **LOW**
   - Sprawdza wszystkie rzędy
   - Jeśli rząd jest **LOW**, to przycisk w tym rzędzie i kolumnie jest naciśnięty
   - Ustawia kolumnę z powrotem na **HIGH**
4. Proces powtarza się dla każdej kolumny

### Przykład:
- Gdy naciskasz przycisk **OK** (R1, C2):
  - Program ustawia C2 na LOW
  - Sprawdza R1 → jest LOW (bo przycisk łączy C2 z R1)
  - Wykrywa naciśnięcie i wywołuje funkcję `handle_ok()`

## Fizyczne podłączenie

### Krok po kroku:

1. **Wyłącz Raspberry Pi**

2. **Podłącz kolumny** (C0-C3) do GPIO jako outputs:
   ```
   Matryca C3 → GPIO 5  (pin 29)
   Matryca C2 → GPIO 6  (pin 31)
   Matryca C1 → GPIO 13 (pin 33)
   Matryca C0 → GPIO 19 (pin 35)
   ```

3. **Podłącz rzędy** (R0-R3) do GPIO jako inputs:
   ```
   Matryca R0 → GPIO 17 (pin 11)
   Matryca R1 → GPIO 22 (pin 15)
   Matryca R2 → GPIO 23 (pin 16)
   Matryca R3 → GPIO 27 (pin 13)
   ```

4. **WAŻNE:** Nie zapomnij podłączyć masy (GND) jeśli matryca tego wymaga

5. **Włącz Raspberry Pi** i uruchom program

## Testowanie

Po uruchomieniu programu powinieneś zobaczyć w konsoli:
```
[MATRIX] Inicjalizacja matrycy 4x4...
[OK] Matryca 4x4 OK
```

Przy naciśnięciu przycisku pojawi się:
```
[MATRIX] Przycisk: OK
```

## Troubleshooting

### Przyciski nie działają:
1. Sprawdź połączenia - czy wszystkie 8 pinów jest podłączonych
2. Sprawdź kolejność - C3, C2, C1, C0, R0, R1, R2, R3
3. Sprawdź czy GPIO nie są używane przez inne usługi

### Przyciski reagują na dotknięcie lub nieprawidłowo:
1. To normalne - może być efekt "ghost button" w matrycach bez diod
2. Możesz dodać diody (1N4148) w szereg z każdym przyciskiem (anoda do kolumny)
3. Zwiększ czas debounce w kodzie (domyślnie 300ms)

### Złe przyciski są wykrywane:
1. Sprawdź układ przycisków w matrycy - może być inny niż założony
2. Dostosuj `BUTTON_MAP` w kodzie do rzeczywistego układu

## Modyfikacja układu przycisków

Jeśli Twoja matryca ma inny układ fizyczny, możesz go zmienić w pliku `kontrola_wersji.py`:

```python
BUTTON_MAP = {
    (0, 3): 'UP',      # R0, C3
    (0, 2): 'MINUS',   # R0, C2
    (0, 1): 'PLUS',    # R0, C1
    (0, 0): 'MENU',    # R0, C0
    (1, 3): 'LEFT',    # R1, C3
    (1, 2): 'OK',      # R1, C2
    (1, 1): 'RIGHT',   # R1, C1
    (2, 3): 'DOWN',    # R2, C3
    (2, 2): 'DELETE',  # R2, C2
    (2, 1): 'VIDEOS',  # R2, C1
    (3, 3): 'RECORD',  # R3, C3
}
```

Zmień pary `(row, col)` aby dopasować do rzeczywistego położenia przycisków.

## Diagram pinów Raspberry Pi 5

```
         3V3  (1) (2)  5V
   GPIO  2    (3) (4)  5V
   GPIO  3    (5) (6)  GND
   GPIO  4    (7) (8)  GPIO 14
         GND  (9) (10) GPIO 15
★ GPIO 17   (11) (12) GPIO 18
★ GPIO 27   (13) (14) GND
★ GPIO 22   (15) (16) GPIO 23 ★
         3V3 (17) (18) GPIO 24
   GPIO 10   (19) (20) GND
   GPIO  9   (21) (22) GPIO 25
   GPIO 11   (23) (24) GPIO 8
         GND (25) (26) GPIO 7
   GPIO  0   (27) (28) GPIO 1
★ GPIO  5   (29) (30) GND
★ GPIO  6   (31) (32) GPIO 12
★ GPIO 13   (33) (34) GND
★ GPIO 19   (35) (36) GPIO 16
   GPIO 26   (37) (38) GPIO 20
         GND (39) (40) GPIO 21
```

★ = Piny używane przez matrycę
