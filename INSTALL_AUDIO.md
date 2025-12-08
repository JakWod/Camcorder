# Instrukcja instalacji obsługi audio (mikrofon)

## Instalacja PyAudio na Raspberry Pi

### 1. Zainstaluj zależności systemowe

```bash
sudo apt-get update
sudo apt-get install -y portaudio19-dev python3-pyaudio
```

### 2. Zainstaluj PyAudio przez pip

```bash
pip3 install pyaudio
```

Lub jeśli używasz środowiska wirtualnego:

```bash
source venv/bin/activate
pip install pyaudio
```

### 3. Sprawdź dostępne urządzenia audio

Uruchom następujący skrypt aby zobaczyć dostępne mikrofony:

```python
import pyaudio

p = pyaudio.PyAudio()
for i in range(p.get_device_count()):
    info = p.get_device_info_by_index(i)
    print(f"Device {i}: {info['name']}")
    print(f"  Input channels: {info['maxInputChannels']}")
    print(f"  Output channels: {info['maxOutputChannels']}")
    print()
p.terminate()
```

### 4. Konfiguracja mikrofonu USB (jeśli używasz)

Jeśli używasz mikrofonu USB, upewnij się że jest podłączony:

```bash
arecord -l
```

Powinieneś zobaczyć listę urządzeń nagrywających.

### 5. Test mikrofonu

Przetestuj mikrofon przed użyciem kamery:

```bash
arecord -d 5 test.wav
aplay test.wav
```

## Funkcje audio w kodzie

### Automatyczna detekcja mikrofonu

Kod automatycznie wykrywa domyślny mikrofon i używa go do nagrywania.

### Wskaźnik poziomu głośności

Nad przyciskiem **P-MENU** (lewy dolny róg) wyświetla się wskaźnik poziomu głośności:
- **Zielony pasek** - normalny poziom dźwięku
- **Żółty pasek** - wysoki poziom (>60%)
- **Czerwony pasek** - bardzo wysoki poziom (>85%, możliwe przesterowanie)
- **Szary napis MIC** - mikrofon wykryty ale cisza
- **Zielony napis MIC** - mikrofon aktywnie nagrywa dźwięk

### Parametry nagrywania audio

- **Format**: WAV (PCM 16-bit)
- **Sample rate**: 44100 Hz
- **Kanały**: 1 (mono)
- **Kodek w finalnym MP4**: AAC 128 kbps

### Proces nagrywania

1. Podczas nagrywania wideo tworzone są dwa pliki:
   - `video_YYYYMMDD_HHMMSS_XXfps.mp4` - wideo bez audio
   - `video_YYYYMMDD_HHMMSS_XXfps.wav` - audio (tymczasowy)

2. Po zatrzymaniu nagrywania:
   - Audio i wideo są automatycznie łączone przez **ffmpeg**
   - Plik WAV jest usuwany
   - Finalny plik MP4 zawiera zsynchronizowany dźwięk

### Rozwiązywanie problemów

#### Brak audio w nagraniu

1. Sprawdź czy mikrofon jest wykrywany:
```bash
arecord -l
```

2. Sprawdź logi programu - powinieneś zobaczyć:
```
[AUDIO] Inicjalizacja PyAudio...
[AUDIO] Znaleziono X urządzeń audio
[AUDIO] Używam urządzenia: [nazwa mikrofonu]
```

3. Jeśli mikrofon nie jest wykrywany, sprawdź połączenie USB/jack

#### Audio nie synchronizuje się z wideo

- Upewnij się że ffmpeg jest zainstalowany:
```bash
sudo apt-get install ffmpeg
```

#### Zbyt cichy dźwięk

Zwiększ głośność mikrofonu przez alsamixer:
```bash
alsamixer
```

Wybierz kartę dźwiękową (F6) i zwiększ poziom wejścia.

#### Szumy lub przesterowanie

- Zmniejsz poziom wejścia w `alsamixer`
- Ustaw mikrofon dalej od źródła dźwięku
- Używaj lepszego mikrofonu z redukcją szumów

## Wyłączenie audio

Jeśli chcesz wyłączyć nagrywanie audio:

1. Odłącz mikrofon
2. Lub zakomentuj linię w `start_recording()`:
```python
# start_audio_recording(current_file)
```

Program będzie działał normalnie bez audio.
