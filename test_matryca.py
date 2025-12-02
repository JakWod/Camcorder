#!/usr/bin/env python3
"""
Test matrycy przycisków 4x4
Uruchom ten skrypt aby sprawdzić czy matryca jest poprawnie podłączona
"""

import RPi.GPIO as GPIO
import time

# Konfiguracja pinów
COL_PINS = [19, 13, 6, 5]   # C0, C1, C2, C3
ROW_PINS = [17, 22, 23, 27]  # R0, R1, R2, R3

# Mapowanie przycisków
BUTTON_MAP = {
    (0, 3): 'UP',
    (0, 2): 'MINUS',
    (0, 1): 'PLUS',
    (0, 0): 'MENU',
    (1, 3): 'LEFT',
    (1, 2): 'OK',
    (1, 1): 'RIGHT',
    (2, 3): 'DOWN',
    (2, 2): 'DELETE',
    (2, 1): 'VIDEOS',
    (3, 3): 'RECORD',
}

def init_matrix():
    """Inicjalizuj GPIO dla matrycy"""
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    # Kolumny jako wyjścia
    for col_pin in COL_PINS:
        GPIO.setup(col_pin, GPIO.OUT)
        GPIO.output(col_pin, GPIO.HIGH)

    # Rzędy jako wejścia z pull-up
    for row_pin in ROW_PINS:
        GPIO.setup(row_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    print("[OK] Matryca zainicjalizowana")
    print("\nNaciśnij przyciski aby je przetestować...")
    print("Ctrl+C aby zakończyć\n")

def scan_matrix():
    """Skanuj matrycę i zwróć naciśnięte przyciski"""
    pressed = []

    for col_idx, col_pin in enumerate(COL_PINS):
        GPIO.output(col_pin, GPIO.LOW)
        time.sleep(0.001)

        for row_idx, row_pin in enumerate(ROW_PINS):
            if GPIO.input(row_pin) == GPIO.LOW:
                button_key = (row_idx, col_idx)
                if button_key in BUTTON_MAP:
                    pressed.append(BUTTON_MAP[button_key])

        GPIO.output(col_pin, GPIO.HIGH)

    return pressed

def test_all_buttons():
    """Testuj wszystkie przyciski"""
    print("\n" + "="*60)
    print("TEST WSZYSTKICH PRZYCISKÓW")
    print("="*60)
    print("\nNaciśnij każdy przycisk aby go przetestować:")
    print("\nOczekiwane przyciski:")
    for key, name in sorted(BUTTON_MAP.items(), key=lambda x: x[1]):
        row, col = key
        print(f"  - {name:10s} (Rząd {row}, Kolumna {col})")
    print("\nCzekam na naciśnięcia...\n")

def main():
    try:
        init_matrix()
        test_all_buttons()

        last_pressed = set()

        while True:
            pressed = set(scan_matrix())

            # Wykryj nowe naciśnięcia
            new_pressed = pressed - last_pressed
            for button in new_pressed:
                print(f"✓ Naciśnięto: {button:10s} | Czas: {time.strftime('%H:%M:%S')}")

            last_pressed = pressed
            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\n\n[EXIT] Test zakończony")

    finally:
        GPIO.cleanup()
        print("[OK] GPIO cleanup")

if __name__ == '__main__':
    print("\n" + "="*60)
    print("   TEST MATRYCY PRZYCISKÓW 4x4 - RASPBERRY PI 5")
    print("="*60)
    main()
