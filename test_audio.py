#!/usr/bin/env python3
"""
Skrypt diagnostyczny dla audio - sprawdź dlaczego mikrofon nie działa
"""
import sys

print("=" * 70)
print("TEST AUDIO - DIAGNOSTYKA MIKROFONU")
print("=" * 70)

# Test 1: Sprawdź czy PyAudio jest zainstalowane
print("\n[TEST 1] Sprawdzam czy PyAudio jest zainstalowane...")
try:
    import pyaudio
    print("[OK] PyAudio jest zainstalowane")
    print(f"[INFO] Wersja PyAudio: {pyaudio.__version__ if hasattr(pyaudio, '__version__') else 'unknown'}")
except ImportError as e:
    print(f"[ERROR] PyAudio NIE jest zainstalowane: {e}")
    print("[FIX] Uruchom: sudo apt-get install -y portaudio19-dev python3-pyaudio")
    print("[FIX] Lub: pip3 install pyaudio")
    sys.exit(1)

# Test 2: Inicjalizuj PyAudio
print("\n[TEST 2] Inicjalizacja PyAudio...")
try:
    audio = pyaudio.PyAudio()
    print("[OK] PyAudio zainicjalizowany")
except Exception as e:
    print(f"[ERROR] Nie można zainicjalizować PyAudio: {e}")
    sys.exit(1)

# Test 3: Sprawdź dostępne urządzenia
print("\n[TEST 3] Lista wszystkich urządzeń audio:")
device_count = audio.get_device_count()
print(f"[INFO] Znaleziono {device_count} urządzeń")

input_devices = []
for i in range(device_count):
    try:
        info = audio.get_device_info_by_index(i)
        print(f"\nUrządzenie {i}:")
        print(f"  Nazwa: {info['name']}")
        print(f"  Kanały wejściowe: {info['maxInputChannels']}")
        print(f"  Kanały wyjściowe: {info['maxOutputChannels']}")
        print(f"  Sample rate: {info['defaultSampleRate']}")
        print(f"  Host API: {info['hostApi']}")

        if info['maxInputChannels'] > 0:
            input_devices.append((i, info))
            print(f"  >>> TO JEST URZĄDZENIE WEJŚCIOWE (mikrofon) <<<")
    except Exception as e:
        print(f"  [BŁĄD] Nie można odczytać urządzenia {i}: {e}")

if not input_devices:
    print("\n[ERROR] NIE ZNALEZIONO ŻADNYCH URZĄDZEŃ WEJŚCIOWYCH!")
    print("[FIX] Sprawdź czy mikrofon jest podłączony:")
    print("       arecord -l")
    audio.terminate()
    sys.exit(1)

print(f"\n[OK] Znaleziono {len(input_devices)} urządzeń wejściowych")

# Test 4: Spróbuj domyślne urządzenie
print("\n[TEST 4] Test domyślnego urządzenia wejściowego...")
try:
    default_input = audio.get_default_input_device_info()
    print(f"[OK] Domyślne urządzenie: {default_input['name']}")
    print(f"     Index: {default_input['index']}")
    print(f"     Kanały: {default_input['maxInputChannels']}")
except Exception as e:
    print(f"[WARN] Nie można uzyskać domyślnego urządzenia: {e}")

# Test 5: Testuj każde urządzenie wejściowe
print("\n[TEST 5] Testuję każde urządzenie wejściowe...")
AUDIO_FORMAT = pyaudio.paInt16
AUDIO_CHANNELS = 1
AUDIO_RATE = 44100
AUDIO_CHUNK = 1024

working_devices = []

for idx, info in input_devices:
    print(f"\nTestuję urządzenie {idx}: {info['name']}")
    try:
        test_stream = audio.open(
            format=AUDIO_FORMAT,
            channels=AUDIO_CHANNELS,
            rate=AUDIO_RATE,
            input=True,
            input_device_index=idx,
            frames_per_buffer=AUDIO_CHUNK
        )

        # Spróbuj odczytać dane
        data = test_stream.read(AUDIO_CHUNK, exception_on_overflow=False)
        test_stream.close()

        print(f"  [OK] Urządzenie {idx} DZIAŁA!")
        print(f"       Odczytano {len(data)} bajtów danych")
        working_devices.append((idx, info))
    except Exception as e:
        print(f"  [ERROR] Urządzenie {idx} NIE DZIAŁA: {e}")

# Podsumowanie
print("\n" + "=" * 70)
print("PODSUMOWANIE")
print("=" * 70)

if working_devices:
    print(f"\n[OK] Znaleziono {len(working_devices)} działających urządzeń wejściowych:")
    for idx, info in working_devices:
        print(f"     - Urządzenie {idx}: {info['name']}")

    print("\n[ROZWIĄZANIE] Kod powinien używać urządzenia:")
    best_device = working_devices[0]
    print(f"     audio_device_index = {best_device[0]}")
    print(f"     Nazwa: {best_device[1]['name']}")
else:
    print("\n[ERROR] ŻADNE URZĄDZENIE NIE DZIAŁA!")
    print("\n[MOŻLIWE PRZYCZYNY]")
    print("1. Mikrofon nie jest podłączony")
    print("2. Mikrofon jest wyłączony lub wyciszony")
    print("3. Brak uprawnień do dostępu (dodaj użytkownika do grupy 'audio')")
    print("4. Sterownik audio nie działa poprawnie")
    print("\n[POLECENIA DIAGNOSTYCZNE]")
    print("  arecord -l                    # Lista urządzeń nagrywających")
    print("  arecord -L                    # Szczegółowa lista urządzeń")
    print("  arecord -d 3 test.wav         # Nagraj 3 sekundy testu")
    print("  groups                         # Sprawdź grupy użytkownika")
    print("  sudo usermod -aG audio $USER  # Dodaj do grupy audio")

audio.terminate()
print("\n[KONIEC TESTU]\n")
