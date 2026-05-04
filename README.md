#  Raspberry Pi 5 — Kamera

 Kamera oparta na Raspberry Pi 5 z sensorem Sony IMX708. Obsługuje nagrywanie wideo w jakości do 4K30, podgląd na żywo, odtwarzanie nagrań, nakładkę daty/czasu, cyfrowy zoom, filtr IR CUT, monitoring baterii przez INA219 oraz rejestrację dźwięku z mikrofonu USB.

---

##  Spis treści

- [Wymagania sprzętowe](#wymagania-sprzętowe)
- [Wymagania programowe](#wymagania-programowe)
- [Struktura projektu](#struktura-projektu)
- [Instalacja](#instalacja)
- [Konfiguracja GPIO](#konfiguracja-gpio)
- [Uruchomienie](#uruchomienie)
- [Obsługa — matryca przycisków](#obsługa--matryca-przycisków-4x4)
- [Ekrany i stany aplikacji](#ekrany-i-stany-aplikacji)
- [Ustawienia kamery](#ustawienia-kamery)
- [Monitoring baterii (INA219)](#monitoring-baterii-ina219)
- [Nagrywanie audio](#nagrywanie-audio)
- [Filtr IR CUT](#filtr-ir-cut)
- [Zarządzanie kartą SD](#zarządzanie-kartą-sd)
- [Pliki konfiguracyjne](#pliki-konfiguracyjne)
- [Rozwiązywanie problemów](#rozwiązywanie-problemów)

---

## Wymagania sprzętowe

| Komponent | Opis |
|---|---|
| Raspberry Pi 5 | Jednostka główna |
| Sony IMX708 | Sensor obrazu (kamera CSI) |
| Wyświetlacz | Ekran fullscreen (HDMI lub DSI) |
| Mikrofon USB | Nagrywanie dźwięku (mono lub stereo, 48 kHz) |
| INA219 | Moduł monitoringu baterii (I²C, adres `0x41`) |
| Matryca przycisków 4×4 | Kontroler (GPIO, schemat kolumny/rzędy) |
| Filtr IR CUT | Sterowany przez mostek H (GPIO 24/25) |
| LED IR | Latarka podczerwieni (GPIO 12) |
| Bateria 3S 18650 | 9–12,6 V, 2300 mAh (konfigurowalnie) |
| Karta SD/MicroSD | Nośnik nagrań (montowana w `/media/pi/`) |

---

## Wymagania programowe

```
Python 3.11+
picamera2
pygame
opencv-python (cv2)
numpy
gpiozero
RPi.GPIO
pyaudio
lgpio
smbus
Pillow (PIL)
```

Instalacja zależności:

```bash
sudo apt update
sudo apt install python3-picamera2 python3-pygame python3-opencv \
                 python3-numpy python3-gpiozero python3-rpi.gpio \
                 python3-pyaudio python3-smbus ffmpeg
pip3 install lgpio Pillow
```

---

## Struktura projektu

```
camera_project/
├── main.py                  # Główna aplikacja
├── INA219.py                # Sterownik czujnika prądu/napięcia INA219
├── camera_config.json       # Plik konfiguracyjny (generowany automatycznie)
├── thumbnails/              # Cache miniaturek (dysk lokalny)
├── icons/
│   ├── steadyhand.png
│   ├── bright.png
│   ├── film.png
│   └── pause.png
└── fonts/
    ├── home_video/
    ├── compliance_sans/
    ├── digital_pixel_v123/
    └── digital_pixel_v124/
```

Nagrania są zapisywane bezpośrednio na kartę SD (`/media/pi/<nazwa_karty>/`).

---

## Instalacja

```bash
git clone <repo_url> /home/pi/camera_project
cd /home/pi/camera_project

# Ustaw zmienną środowiskową dla gpiozero
echo 'export GPIOZERO_PIN_FACTORY=lgpio' >> ~/.bashrc
source ~/.bashrc
```

Aby aplikacja uruchamiała się przy starcie systemu:

```bash
# /etc/systemd/system/camera.service
[Unit]
Description=Camera System
After=graphical.target

[Service]
User=pi
Environment=DISPLAY=:0
WorkingDirectory=/home/pi/camera_project
ExecStart=/usr/bin/python3 /home/pi/camera_project/main.py
Restart=on-failure

[Install]
WantedBy=graphical.target
```

```bash
sudo systemctl enable camera.service
sudo systemctl start camera.service
```

---

## Konfiguracja GPIO

### Matryca przycisków 4×4

| Sygnał | Piny GPIO |
|---|---|
| Kolumny (output) | 16, 13, 6, 5 |
| Rzędy (input, pull-up) | 17, 22, 23, 27 |

### Pozostałe piny

| Funkcja | Pin GPIO |
|---|---|
| IR CUT — dzień (HIGH) | 24 |
| IR CUT — noc (HIGH) | 25 |
| LED IR (latarka) | 12 |

### INA219

Komunikacja przez I²C, adres `0x41`, rezystor bocznikowy **0,1 Ω**, zakres 32 V / 2 A.

---

## Uruchomienie

```bash
cd /home/pi/camera_project
python3 main.py
```

Aplikacja automatycznie wykrywa kartę SD, inicjalizuje kamerę, mikrofon, INA219 oraz matrycę przycisków.

---

## Obsługa — matryca przycisków 4×4

```
┌────────┬────────┬────────┬────────┐
│   -    │   -    │  REC   │   -    │
├────────┼────────┼────────┼────────┤
│ MINUS  │   UP   │  PLUS  │  MENU  │
├────────┼────────┼────────┼────────┤
│  LEFT  │   OK   │ RIGHT  │ VIDEOS │
├────────┼────────┼────────┼────────┤
│   IR   │  DOWN  │   -    │ DELETE │
└────────┴────────┴────────┴────────┘
```

| Przycisk | Akcja |
|---|---|
| `REC` | Start / stop nagrywania |
| `OK` | Potwierdzenie / pauza |
| `MENU` | Otwórz menu / wyjdź z trybu edycji |
| `VIDEOS` | Przełącz widok nagrań |
| `DELETE` | Usuń zaznaczony film |
| `UP` / `DOWN` | Nawigacja / regulacja głośności |
| `LEFT` / `RIGHT` | Nawigacja / przewijanie wideo |
| `PLUS` / `MINUS` | Zoom cyfrowy (W/T) |
| `IR` | Przełącz filtr IR CUT (dzień/noc) |

---

## Ekrany i stany aplikacji

| Stan | Opis |
|---|---|
| **Podgląd (MAIN)** | Obraz na żywo z nakładkami HUD |
| **Filmy (VIDEOS)** | Siatka miniaturek nagranych filmów |
| **Odtwarzanie (PLAYING)** | Odtwarzacz wideo z paskiem postępu |
| **Menu (MENU)** | Ustawienia kamery (4 sekcje) |
| **Potwierdzenie (CONFIRM)** | Dialog usuwania pliku |
| **Popup wyboru** | Lista opcji dla danego ustawienia |
| **Informacje o filmie** | Metadane wybranego nagrania |

---

## Ustawienia kamery

Dostępne w menu głównym (sekcje: Image Quality/Size, Manual Settings, Znacznik Daty, Poziom Baterii).

### Rozdzielczości i bitrate

| Tryb | Rozdzielczość | FPS | Bitrate |
|---|---|---|---|
| 4K30 | 3840×2160 | 30 | 25 Mbps |
| 1080p50 | 1920×1080 | 50 | 14 Mbps |
| 1080p30 | 1920×1080 | 30 | 10 Mbps |
| 720p50 | 1280×720 | 50 | 9 Mbps |
| 720p30 | 1280×720 | 30 | 6 Mbps |

### Pozostałe parametry

- **Balans bieli**: auto, incandescent, tungsten, fluorescent, indoor, daylight, cloudy
- **ISO**: auto, 100, 200, 400, 800, 1600
- **Jasność**: −1.0 … +1.0
- **Kontrast**: 0.0 … 2.0
- **Saturacja**: 0.0 … 2.0
- **Ostrość**: 0.0 … 4.0
- **Ekspozycja**: −2.0 … +2.0 EV
- **Zoom cyfrowy**: 0–99% (do 4× crop)
- **Nakładka daty/czasu**: różne formaty, separatory, kolory i rozmiary czcionki

---

## Monitoring baterii (INA219)

Plik `INA219.py` dostarcza sterownik I²C dla układu INA219. Konfiguracja domyślna:

- Zakres: 32 V
- Wzmocnienie: 8× (320 mV)
- ADC: 12-bit, 32 próbki
- Rezystor bocznikowy: 0,1 Ω
- LSB prądu: 100 µA/bit

Poziom baterii obliczany jest na podstawie napięcia szyny (9 V = 0%, 12,6 V = 100%, średnia krocząca z 5 próbek). Wskaźnik wyświetla procent naładowania, szacowany czas pracy oraz ikonę pioruna podczas ładowania.

---

## Nagrywanie audio

- Biblioteka: **PyAudio** (48 kHz, 16-bit, mono/stereo)
- Audio nagrywane równolegle z wideo do pliku `.wav`
- Po zatrzymaniu nagrywania plik WAV jest łączony z H.264 przez **FFmpeg** (AAC 128 kbps)
- W trybie podglądu aktywny jest ciągły monitoring poziomu sygnału (wskaźnik VU — ALC CH1/CH2)

---

## Filtr IR CUT

Filtr mechaniczny sterowany mostkiem H (GPIO 24/25). Krótki impuls HIGH na odpowiednim pinie przestawia filtr.

| Tryb | IR CUT | LED IR (GPIO 12) | Night Vision |
|---|---|---|---|
| Dzień | ON | OFF | Wyłączony |
| Noc | OFF | ON | Włączony |

Ostatni stan filtra jest zapisywany do `camera_config.json` i przywracany przy starcie.

---

## Zarządzanie kartą SD

Aplikacja automatycznie wykrywa pierwszą zapisywalną kartę SD w `/media/pi/`. Stan karty sprawdzany jest co 2 sekundy. Miniaturki przechowywane są lokalnie w `~/camera_project/thumbnails/` (synchronizacja uruchamiana przy starcie).

---

## Pliki konfiguracyjne

`camera_config.json` — zapisuje wszystkie ustawienia automatycznie przy zamknięciu i każdej zmianie parametru.

```json
{
  "video_resolution": "1080p30",
  "awb_mode": "auto",
  "brightness": 0.0,
  "contrast": 1.0,
  "zoom": 0.0,
  "show_date": false,
  "font_family": "DigitalPixel2",
  "ir_filter_day_mode": true
}
```

---

## Rozwiązywanie problemów

| Objaw | Możliwa przyczyna | Rozwiązanie |
|---|---|---|
| `INA219 Failed to initialize` | Zły adres I²C | Sprawdź `i2cdetect -y 1`, domyślny adres `0x41` |
| Brak obrazu z kamery | Zły format / konfiguracja | Sprawdź `libcamera-hello` |
| Brak dźwięku | Brak mikrofonu USB | `arecord -l` — lista urządzeń wejściowych |
| `BRAK KARTY SD!` | Karta niezmontowana | Sprawdź `/media/pi/` |
| Filtr IR nie przełącza | Zły pin lub polaryzacja | Sprawdź schemat mostka H i piny 24/25 |
| Błąd czcionki | Brak pliku `.otf`/`.ttf` | Sprawdź ścieżki w `FONT_DEFINITIONS` |

---

## Licencja

Projekt do użytku prywatnego / edukacyjnego.
