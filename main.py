#!/usr/bin/env python3
import pygame
import sys
import os
os.environ['GPIOZERO_PIN_FACTORY'] = 'lgpio'
import shutil
from datetime import datetime
from pathlib import Path
import cv2
import numpy as np
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput
from gpiozero import Button
import RPi.GPIO as GPIO
import signal
import subprocess
import time
import json
from PIL import Image, ImageDraw, ImageFont
import threading
import math
import re
from INA219 import INA219
import pyaudio
import wave
import struct

# ============================================================================
# KONFIGURACJA
# ============================================================================

# Katalogi
THUMBNAIL_DIR = Path("/home/pi/camera_project/thumbnails")  # Lokalny dysk - miniaturki
THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = Path("/home/pi/camera_project/camera_config.json")  # Lokalny dysk - config

# VIDEO_DIR będzie ustawiony dynamicznie przez find_sd_card()
VIDEO_DIR = None

# GPIO Pins - Matryca 4x4
# Kolumny (outputs)
COL_PINS = [16, 13, 6, 5]  # C0, C1, C2, C3
# Rzędy (inputs z pull-up)
ROW_PINS = [17, 22, 23, 27]  # R0, R1, R2, R3

# GPIO Pins - Filtr IR CUT (mostek H)
IR_CUT_A = 24  # Pełen dzień (IR filtr ON)
IR_CUT_B = 25  # Noc (IR filtr OFF)
IR_LED = 12    # Latarka IR (GPIO 12 = fizyczny pin 32)

# Mapowanie przycisków w matrycy [row][col]
# Układ:
#       C0   C1   C2   C3
# R0 [ MENU ][ + ][ - ][UP]
# R1 [    ][RIGHT ][OK][LEFT ]
# R2 [    ][VID][DEL ][DOWN ]
# R3 [ ][   ][    ][REC  ]

BUTTON_MAP = {
    (3, 1): 'RIGHT',      # R3, C1
    (0, 2): 'MENU',       # R0, C2
    (0, 1): 'VIDEOS',     # R0, C1
    (0, 0): 'DELETE',     # R0, C0
    (3, 2): 'PLUS',       # R3, C2
    (1, 2): 'UP',         # R1, C2
    (1, 1): 'OK',         # R1, C1
    (1, 0): 'DOWN',       # R1, C0
    (2, 2): 'MINUS',      # R2, C2
    (2, 1): 'LEFT',       # R2, C1
    (2, 0): 'IR',         # R2, C0
    (3, 3): 'RECORD',     # R3, C3
}

# Kolory
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (100, 100, 255)
GRAY = (128, 128, 128)
DARK_GRAY = (64, 64, 64)
YELLOW = (255, 255, 0)
ORANGE = (255, 165, 0)
LIGHT_BLUE = (173, 216, 230)
GRID_COLOR = (255, 255, 255, 80)

# Stany
STATE_MAIN = 0
STATE_VIDEOS = 1
STATE_CONFIRM = 2
STATE_PLAYING = 3
STATE_MENU = 4
STATE_SUBMENU = 5
STATE_VIDEO_CONTEXT_MENU = 6
STATE_VIDEO_INFO = 7
STATE_SELECTION_POPUP = 8
STATE_DATE_PICKER = 9

# Globalne zmienne
camera = None
recording = False
recording_start_time = None
current_file = None
current_recording_fps = None
encoder = None
running = True
screen = None
current_state = STATE_MAIN
confirm_selection = 0
fake_battery_level = None  # None = użyj rzeczywistego poziomu, lub wartość 0-100

# Audio - mikrofon
audio = None
audio_stream = None
audio_recording = False
audio_file = None
audio_thread = None
audio_level = 0.0  # Aktualny poziom głośności (0.0 - 1.0)
audio_level_right = 0.0
audio_device_index = None
audio_monitoring_stream = None  # NOWY: Stream do ciągłego monitoringu poziomu
audio_monitoring_thread = None  # NOWY: Wątek monitorujący poziom audio
audio_monitoring_active = False  # NOWY: Czy monitoring jest aktywny
AUDIO_CHUNK = 1024
AUDIO_FORMAT = pyaudio.paInt16
AUDIO_CHANNELS = 2
AUDIO_RATE = 44100

# INA219 Battery Monitor
BATTERY_CAPACITY_MAH = 2300  # Pojedyncza bateria 18650 2300mAh (3S)
ina219 = None
battery_current = 0  # Prąd w mA
battery_last_level = 100  # Ostatni zmierzony poziom baterii
battery_last_check_time = 0  # Czas ostatniego pomiaru
battery_estimated_minutes = 120  # Szacowany czas w minutach (domyślnie 2h)
battery_is_charging = False  # Stan ładowania z histerezą
battery_charge_hysteresis_high = 10  # Próg górny histerezy (mA) - włącz ładowanie
battery_charge_hysteresis_low = -10   # Próg dolny histerezy (mA) - wyłącz ładowanie
battery_voltage_samples = []  # Próbki napięcia do średniej kroczącej (5 próbek)
battery_max_displayed_level = 100.0  # Maksymalny wyświetlany poziom (tylko maleje podczas rozładowania)

# Matryca przycisków
matrix_cols = []
matrix_rows = []
last_button_press = {}  # Słownik do debounce
button_handlers = {}  # Słownik handler'ów dla każdego przycisku

# IR Cut Filter
ir_mode_day = True  # True = dzień (filtr IR ON), False = noc (filtr IR OFF)

# Video Player
video_capture = None
video_paused = False
video_current_frame = 0
video_total_frames = 0
video_fps = 30
video_path_playing = None
video_last_frame_time = 0
video_last_surface = None
video_audio_ready = False  # NOWY: Czy audio jest gotowe do odtwarzania
playback_loading_start_time = 0  # Czas rozpoczęcia ładowania wideo
video_current_volume = 1.0  # Zachowana głośność (0.0 - 1.0)
last_ui_interaction_time = 0  # Czas ostatniej interakcji z UI (do auto-ukrywania)
UI_HIDE_DELAY = 3.0  # Sekundy bezczynności przed ukryciem UI
last_volume_change_time = 0  # Czas ostatniej zmiany głośności (do pokazania wskaźnika)
VOLUME_INDICATOR_DURATION = 2.0  # Sekundy wyświetlania wskaźnika głośności

# Video Manager
videos = []
selected_index = 0
thumbnails = {}
videos_scroll_offset = 0
selected_videos = set()  # Multi-select: zestaw indeksów zaznaczonych filmów
video_context_menu_selection = 0  # Wybór w menu kontekstowym
video_info_index = 0  # Indeks filmu do wyświetlenia informacji
multi_select_mode = False  # Tryb zaznaczania wielu filmów

# Komunikaty błędów
error_message = None
error_message_time = 0
ERROR_DISPLAY_DURATION = 3.0  # Sekundy

# Monitorowanie karty SD
last_sd_check_time = 0
SD_CHECK_INTERVAL = 2.0  # Sprawdzaj co 2 sekundy

# Pygame
font_large = None
font_medium = None
font_small = None
font_mediumXL = None
font_tiny = None
menu_font = None
font_70 = None
SCREEN_WIDTH = 0
SCREEN_HEIGHT = 0
playback_icon = None  # Obrazek ikony playback
steadyhand_icon = None  # Obrazek ikony steadyhand
sd_icon = None  # Obrazek ikony karty SD
brightness_icon = None  # Obrazek ikony brightness
film_icon = None  # Obrazek ikony filmu
pause_icon = None  # Obrazek ikony pauzy

# Menu System
menu_tiles = []
selected_tile = 0
submenu_items = []
submenu_selected = 0
submenu_editing = False
submenu_edit_value = ""
current_submenu = None
last_menu_scroll = 0
last_videos_scroll = 0
menu_editing_mode = False  # True = edytujemy wartości, False = wybieramy sekcję
selected_section = 0  # Indeks wybranej sekcji (0-3: VIDEO, CONFIG, DATE, BATT)
menu_value_editing = False  # True = edytujemy konkretną wartość liczbową strzałkami lewo/prawo

# Date editing in menu
date_editing = False  # True = edytujemy datę bezpośrednio w menu
date_edit_day = 1
date_edit_month = 1
date_edit_year = 2025
date_edit_segment = 0  # 0=day, 1=month, 2=year
date_blink_state = True  # Stan migania dla segmentu
date_last_blink_time = 0

# Selection Popup
popup_options = []
popup_selected = 0
popup_tile_id = None

# SD Card Icons - REMOVED (replaced with zoom indicator)

# Camera Settings
camera_settings = {
    "video_resolution": "1080p30",
    "white_balance": "auto",
    "brightness": 0.0,
    "contrast": 1.0,
    "saturation": 1.0,
    "sharpness": 1.0,
    "exposure_compensation": 0.0,
    "awb_mode": "auto",
    "iso_mode": "auto",  # ISO setting
    "show_date": False,
    "show_time": False,
    "date_position": "top_left",
    "manual_date": None,
    "date_format": "DD/MM/YYYY",
    "date_month_text": False,
    "date_separator": "/",
    "date_color": "yellow",
    "date_font_size": "medium",
    "zoom": 0.0,
    "show_grid": True,
    "font_family": "HomeVideo",
    "audio_recording": True,  # NOWY: Włącz/wyłącz nagrywanie dźwięku
    "show_center_frame": True,  # NOWY: Pokaż ramkę środkową
    "night_vision_mode": False,  # NOWY: Tryb Night Vision (automatyczny dla IR)
    "ir_filter_day_mode": True,  # NOWY: Stan filtra IR (True = dzień, False = noc)
}

# Opcje
WB_MODES = ["auto", "incandescent", "tungsten", "fluorescent", "indoor", "daylight", "cloudy"]
DATE_POSITIONS = ["top_left", "top_right", "bottom_left", "bottom_right"]
DATE_FORMATS = ["DD/MM/YYYY", "MM/DD/YYYY", "YYYY/MM/DD"]
DATE_SEPARATORS = ["/", " ", "-"]
DATE_COLORS = ["yellow", "white", "red", "green", "blue", "orange"]
DATE_FONT_SIZES = ["small", "medium", "large", "extra_large"]
VIDEO_RESOLUTIONS = ["1080p30", "1080p50", "720p30", "720p50", "4K30"]

# ISO Settings (Analogue Gain)
ISO_MODES = ["auto", "100", "200", "400", "800", "1600"]
ISO_TO_GAIN = {
    "auto": None,
    "100": 1.0,
    "200": 2.0,
    "400": 4.0,
    "800": 8.0,
    "1600": 16.0
}

# Definicje czcionek
FONT_DEFINITIONS = {
    "HomeVideo": {
        "path": "/home/pi/fonts/home_video/HomeVideo-Regular.otf",
        "scale": 0.769,
        "polish_offset": 0,      # Offset dla polskich znaków
        "general_offset": 0      # Ogólny offset dla całej czcionki
    },
    "Faithful": {
        "path": "/home/pi/fonts/compliance_sans/Faithful.ttf",
        "scale": 0.923,
        "polish_offset": -5,
        "general_offset": -5
    },
    "DigitalPixel": {
        "path": "/home/pi/fonts/digital_pixel_v123/DigitalPixelV123-Regular.otf",
        "scale": 0.385,
        "polish_offset": -3,
        "general_offset": -5
    },
    "DigitalPixel2": {
        "path": "/home/pi/fonts/digital_pixel_v124/DigitalPixelV124-Regular.otf",
        "scale": 0.538,
        "polish_offset": -14,
        "general_offset": 0
    }
}

FONT_NAMES = list(FONT_DEFINITIONS.keys())

# Mapowanie rozdzielczości
RESOLUTION_MAP = {
    "1080p30": {"size": (1920, 1080), "fps": 30},
    "1080p50": {"size": (1920, 1080), "fps": 50},
    "720p30": {"size": (1280, 720), "fps": 30},
    "720p50": {"size": (1280, 720), "fps": 50},
    "4K30": {"size": (3840, 2160), "fps": 30},
}

# Bitrate dla różnych rozdzielczości (w bitach na sekundę)
BITRATE_MAP = {
    "1080p30": 10000000,   # 10 Mbps
    "1080p50": 14000000,   # 14 Mbps
    "720p30": 6000000,     # 6 Mbps
    "720p50": 9000000,     # 9 Mbps
    "4K30": 25000000,      # 25 Mbps
}

# Zoom
last_zoom_time = 0
last_zoom_change_time = 0
ZOOM_STEP = 0.02
ZOOM_BAR_TIMEOUT = 1.0

# Timing
MENU_SCROLL_DELAY = 0.35
VIDEOS_SCROLL_DELAY = 0.25


# ============================================================================
# FUNKCJE SD CARD
# ============================================================================

def find_sd_card():
    """
    Wykrywa pierwszą dostępną kartę SD zamontowaną w /media/pi/
    Zwraca Path do katalogu lub None
    """
    media_dir = Path("/media/pi")

    if not media_dir.exists():
        print("[WARN] Katalog /media/pi nie istnieje")
        return None

    try:
        # Szukaj wszystkich zamontowanych katalogów
        mounted_dirs = [d for d in media_dir.iterdir() if d.is_dir()]

        if not mounted_dirs:
            print("[WARN] Brak zamontowanych kart SD w /media/pi/")
            return None

        # Sprawdź który z katalogów jest zapisywalny
        for sd_dir in mounted_dirs:
            try:
                if os.access(str(sd_dir), os.W_OK):
                    # print(f"[OK] Wykryto kartę SD: {sd_dir}")
                    return sd_dir
            except:
                continue

        print("[WARN] Znaleziono karty SD, ale żadna nie jest zapisywalna")
        return None

    except Exception as e:
        print(f"[ERROR] Błąd wykrywania karty SD: {e}")
        return None


def sync_thumbnails_with_videos():
    """
    Synchronizuje miniaturki z filmami:
    - Usuwa miniaturki dla których nie ma filmu
    - Generuje brakujące miniaturki
    """
    global VIDEO_DIR, THUMBNAIL_DIR

    if not VIDEO_DIR or not VIDEO_DIR.exists():
        print("[WARN] VIDEO_DIR niedostępny, pomijam synchronizację")
        return

    print("\n" + "="*70)
    print("[SYNC] SYNCHRONIZACJA MINIATUREK")
    print("="*70)

    # Pobierz listę filmów i miniaturek
    video_files = set(VIDEO_DIR.glob("*.mp4"))
    video_stems = {v.stem for v in video_files}

    thumbnail_files = set(THUMBNAIL_DIR.glob("*.jpg"))
    thumbnail_stems = {t.stem for t in thumbnail_files}

    print(f"[INFO] Filmów: {len(video_files)}, Miniaturek: {len(thumbnail_files)}")

    # Usuń osierocone miniaturki (bez odpowiadającego filmu)
    orphaned = thumbnail_stems - video_stems
    if orphaned:
        print(f"[SYNC] Usuwam {len(orphaned)} osieroconych miniaturek...")
        for stem in orphaned:
            thumb_path = THUMBNAIL_DIR / f"{stem}.jpg"
            try:
                thumb_path.unlink()
                print(f"  - Usunięto: {stem}.jpg")
            except Exception as e:
                print(f"  - Błąd usuwania {stem}.jpg: {e}")
    else:
        print("[OK] Brak osieroconych miniaturek")

    # Znajdź filmy bez miniaturek
    missing = video_stems - thumbnail_stems
    if missing:
        print(f"[SYNC] Generuję {len(missing)} brakujących miniaturek...")
        for stem in missing:
            video_path = VIDEO_DIR / f"{stem}.mp4"
            print(f"  - Generowanie: {stem}.mp4")
            generate_thumbnail(video_path)
    else:
        print("[OK] Wszystkie miniaturki istnieją")

    print("="*70 + "\n")


def check_sd_card():
    """Sprawdź czy karta SD jest dostępna"""
    try:
        return VIDEO_DIR and VIDEO_DIR.exists() and os.access(str(VIDEO_DIR), os.W_OK)
    except:
        return False


def get_available_space_gb():
    """Pobierz dostępne miejsce na karcie w GB"""
    try:
        if not VIDEO_DIR:
            return 0
        stat = shutil.disk_usage(str(VIDEO_DIR))
        return stat.free / (1024**3)  # Konwersja na GB
    except:
        return 0


def get_recording_time_estimate():
    """Oblicz szacowany czas nagrywania na podstawie dostępnego miejsca"""
    if not check_sd_card() or not VIDEO_DIR:
        return "-- : --"

    try:
        free_space_bytes = shutil.disk_usage(str(VIDEO_DIR)).free
        
        # Pobierz bitrate dla aktualnej rozdzielczości
        resolution = camera_settings.get("video_resolution", "1080p30")
        bitrate = BITRATE_MAP.get(resolution, 10000000)
        
        # Oblicz czas w sekundach
        bytes_per_second = bitrate / 8
        estimated_seconds = free_space_bytes / bytes_per_second
        
        # Konwersja na godziny i minuty
        hours = int(estimated_seconds // 3600)
        minutes = int((estimated_seconds % 3600) // 60)
        
        return f"{hours:02d}h{minutes:02d}m"
    except:
        return "-- : --"


def get_recording_quality():
    """Pobierz aktualną jakość nagrywania"""
    resolution = camera_settings.get("video_resolution", "1080p30")
    return resolution.replace("p", "p ")


def format_manual_date(date_str):
    """Formatuje datę ręczną zgodnie z ustawieniami użytkownika (separator, format i miesiąc słownie)"""
    if not date_str:
        return "AUTO"

    # date_str jest w formacie YYYY-MM-DD
    year = date_str[0:4]
    month_num = date_str[5:7]
    day = date_str[8:10]

    # Pobierz separator, format i opcję miesiąca słownie
    separator = camera_settings.get("date_separator", "/")
    date_format = camera_settings.get("date_format", "DD/MM/YYYY")
    month_text = camera_settings.get("date_month_text", False)

    # Skróty miesięcy
    month_names = ["STY", "LUT", "MAR", "KWI", "MAJ", "CZE",
                  "LIP", "SIE", "WRZ", "PAŹ", "LIS", "GRU"]

    # Użyj miesiąca słownie jeśli włączone
    if month_text:
        month = month_names[int(month_num) - 1]
    else:
        month = month_num

    # Buduj datę zgodnie z formatem
    if date_format == "DD/MM/YYYY":
        return f"{day}{separator}{month}{separator}{year}"
    elif date_format == "MM/DD/YYYY":
        return f"{month}{separator}{day}{separator}{year}"
    else:  # YYYY/MM/DD
        return f"{year}{separator}{month}{separator}{day}"


def draw_recording_time_remaining():
    """Rysuj format (w owalu), FPS i czas pozostały do nagrywania w prawym górnym rogu"""
    right_margin = 20
    top_margin = 20

    # Pobierz szacowany czas nagrywania
    time_remaining = get_recording_time_estimate()

    # Pobierz aktualną rozdzielczość
    resolution = camera_settings.get("video_resolution", "1080p30")

    # Mapowanie rozdzielczości na czytelne nazwy formatów
    format_map = {
        "4K30": "4K",
        "1080p30": "FHD",
        "1080p50": "FHD",
        "720p30": "HD",
        "720p50": "HD"
    }
    format_name = format_map.get(resolution, "FHD")

    # Tekst formatu dla obliczenia rozmiaru owalu - UŻYWAMY NOWEJ CZCIONKI font_mediumXL
    format_text_surface = font_mediumXL.render(format_name, True, BLACK)
    format_text_width = format_text_surface.get_width()
    format_text_height = format_text_surface.get_height()

    # Wymiary owalu (z paddingiem)
    oval_padding_x = 18
    oval_padding_y = 2
    oval_width = format_text_width + oval_padding_x * 2
    oval_height = format_text_height + oval_padding_y * 2

    # Tekst czasu z nawiasami
    time_text = f"[{time_remaining}]"
    time_text_surface = menu_font.render(time_text, True, WHITE)
    time_text_width = time_text_surface.get_width()

    # Oblicz całkowitą szerokość (owal + spacja + [czas])
    spacing = 10
    total_width = oval_width + spacing + time_text_width

    # Pozycja początkowa wyrównana do prawej
    start_x = SCREEN_WIDTH - right_margin - total_width

    # === Rysuj owal z formatem ===
    # Przesunięcie formatu o 30px w lewo
    oval_x = start_x - 30
    oval_y = top_margin - oval_padding_y - 5

    # Rysuj biały owal (prostokąt z zaokrąglonymi rogami)
    pygame.draw.rect(screen, WHITE, (oval_x, oval_y, oval_width, oval_height), border_radius=int(oval_height // 2))

    # Rysuj czarne obramowanie owalu
    pygame.draw.rect(screen, BLACK, (oval_x, oval_y, oval_width, oval_height), 2, border_radius=int(oval_height // 2))

    # Rysuj czarny tekst formatu na białym tle (bez outline) - UŻYWAMY NOWEJ CZCIONKI
    format_text_x = oval_x + oval_padding_x + 5
    format_text_y = top_margin
    draw_text(format_name, font_mediumXL, BLACK, format_text_x, format_text_y)

    # === Rysuj czas pozostały (z czarnym outline) ===
    time_x = start_x + oval_width + spacing
    draw_text_with_outline(time_text, font_large, WHITE, BLACK, time_x + 10, top_margin)


def draw_zoom_indicator():
    """Rysuj wskaźnik zoomu Z99, steadyhand, AF AUTO, balans bieli, ISO i Brightness (zawsze widoczne, wyrównane do prawej, OD DOŁU)"""
    # Ukryj wskaźniki podczas nagrywania
    if recording:
        return

    zoom_right_edge = SCREEN_WIDTH - 20  # Margines od prawej krawędzi
    bottom_margin = 100  # Margines od dolnej krawędzi

    # ZMIANA: Rysowanie OD DOŁU DO GÓRY - zaczynamy od brightness (najniżej)

    # Brightness - najniżej (na dole)
    brightness_y = SCREEN_HEIGHT - bottom_margin

    # Pobierz wartość brightness z ustawień
    brightness_value = camera_settings.get("brightness", 0.0)
    brightness_value_text = f"{brightness_value:+.1f}"

    # Wyrenderuj tekst wartości
    brightness_value_surface = font_large.render(brightness_value_text, True, WHITE)
    brightness_value_width = brightness_value_surface.get_width()

    if brightness_icon is not None:
        # Skaluj ikonę - rozmiar jak tekst
        icon_height = 50  # Wysokość ikony dostosowana do tekstu
        icon_width = int(icon_height * (brightness_icon.get_width() / brightness_icon.get_height()))
        scaled_brightness = pygame.transform.scale(brightness_icon, (icon_width + 10, icon_height))

        # Oblicz całkowitą szerokość (ikona + odstęp + wartość)
        total_width = icon_width + 5 + brightness_value_width

        # Pozycja początkowa - wyrównanie do prawej
        start_x = zoom_right_edge - total_width

        # Rysuj ikonę
        screen.blit(scaled_brightness, (start_x - 20, brightness_y - 10))

        # Rysuj wartość obok ikony
        draw_text_with_outline(brightness_value_text, font_large, WHITE, BLACK, start_x + icon_width + 5, brightness_y)
    else:
        # Fallback - jeśli ikona się nie załadowała, użyj tekstu
        brightness_text = f"B {brightness_value:+.1f}"
        brightness_text_surface = font_large.render(brightness_text, True, WHITE)
        brightness_text_width = brightness_text_surface.get_width()
        brightness_x = zoom_right_edge - brightness_text_width
        draw_text_with_outline(brightness_text, font_large, WHITE, BLACK, brightness_x, brightness_y)

    # ISO powyżej brightness - DODATKOWE 5px przerwy
    iso_y = brightness_y - 55

    # Pobierz tryb ISO z ustawień
    iso_mode = camera_settings.get("iso_mode", "auto")
    if iso_mode == "auto":
        iso_text = "ISO AUTO"
    else:
        iso_text = f"ISO {iso_mode}"

    # Oblicz pozycję x aby wyrównać do prawej
    iso_text_surface = font_large.render(iso_text, True, WHITE)
    iso_text_width = iso_text_surface.get_width()
    iso_x = zoom_right_edge - iso_text_width

    draw_text_with_outline(iso_text, font_large, WHITE, BLACK, iso_x, iso_y)

    # White balance powyżej ISO - DODATKOWE 5px przerwy
    wb_y = iso_y - 55

    # Pobierz tryb balansu bieli z ustawień
    awb_mode = camera_settings.get("awb_mode", "auto")

    if awb_mode == "auto":
        wb_text = "P AUTO"
    else:
        # Mapowanie trybów AWB na temperatury kolorów
        wb_temp_map = {
            "incandescent": 2.8,
            "tungsten": 3.2,
            "fluorescent": 4.0,
            "indoor": 3.8,
            "daylight": 5.6,
            "cloudy": 6.5
        }
        wb_temp = wb_temp_map.get(awb_mode, 5.6)
        wb_text = f"P{wb_temp}K"

    # Oblicz pozycję x aby wyrównać do prawej
    wb_text_surface = font_large.render(wb_text, True, WHITE)
    wb_text_width = wb_text_surface.get_width()
    wb_x = zoom_right_edge - wb_text_width

    draw_text_with_outline(wb_text, font_large, WHITE, BLACK, wb_x, wb_y)

    # AF AUTO powyżej white balance
    af_y = wb_y - 75
    af_auto_text = "AF AUTO"
    af_auto_text_surface = font_large.render(af_auto_text, True, WHITE)
    af_auto_text_width = af_auto_text_surface.get_width()
    af_auto_x = zoom_right_edge - af_auto_text_width
    draw_text_with_outline(af_auto_text, font_large, WHITE, BLACK, af_auto_x, af_y)

    # Ikona steadyhand powyżej AF AUTO
    steadyhand_y = af_y - 85
    if steadyhand_icon is not None:
        # Skaluj ikonę - rozmiar jak wcześniej
        icon_height = 90  # Wysokość ikony
        icon_width = int(icon_height + 10)
        scaled_steadyhand = pygame.transform.scale(steadyhand_icon, (icon_width, icon_height))
        scaled_steadyhand = pygame.transform.flip(scaled_steadyhand, True, False)

        # Wyrównaj do prawej krawędzi
        steadyhand_x = zoom_right_edge - icon_width
        screen.blit(scaled_steadyhand, (steadyhand_x, steadyhand_y))

    # Zoom powyżej steadyhand - najwyżej
    zoom_y = steadyhand_y - 25

    # Pobierz poziom zoomu (0.0 - 1.0) i przelicz na procenty (0-99)
    zoom_level = camera_settings.get("zoom", 0.0)
    zoom_percent = int(zoom_level * 99)

    # Tekst wskaźnika zoomu w formacie Z99
    zoom_text = f"Z{zoom_percent:02d}"

    # Oblicz pozycję x aby wyrównać do prawej
    zoom_text_surface = font_large.render(zoom_text, True, WHITE)
    zoom_text_width = zoom_text_surface.get_width()
    zoom_x = zoom_right_edge - zoom_text_width

    # Rysuj wskaźnik zoomu z białym tekstem i czarnym obramowaniem
    draw_text_with_outline(zoom_text, font_large, WHITE, BLACK, zoom_x, zoom_y)


# ============================================================================
# FUNKCJE POMOCNICZE FPS
# ============================================================================

def get_current_fps():
    """Pobierz aktualny FPS z ustawień kamery"""
    resolution = camera_settings.get("video_resolution", "1080p30")
    res_config = RESOLUTION_MAP.get(resolution, {"fps": 30})
    return res_config["fps"]


def extract_fps_from_filename(filename):
    """Wyciągnij FPS z nazwy pliku"""
    match = re.search(r'_(\d+)fps', str(filename))
    if match:
        fps = int(match.group(1))
        print(f"[FPS] FPS z nazwy pliku: {fps}")
        return fps
    print(f"[WARN] Brak FPS w nazwie, użyję domyślnego")
    return None


# ============================================================================
# FUNKCJE AUDIO - MIKROFON
# ============================================================================

def init_audio():
    """Inicjalizuj PyAudio i wykryj mikrofon"""
    global audio, audio_device_index

    # Wycisz ostrzeżenia ALSA
    import os
    os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'

    # Przekieruj stderr ALSA do /dev/null (wycisza ostrzeżenia ALSA)
    import sys
    from contextlib import contextmanager

    @contextmanager
    def suppress_alsa_errors():
        """Tymczasowo wycisz błędy ALSA"""
        devnull = os.open(os.devnull, os.O_WRONLY)
        old_stderr = os.dup(2)
        sys.stderr.flush()
        os.dup2(devnull, 2)
        os.close(devnull)
        try:
            yield
        finally:
            os.dup2(old_stderr, 2)
            os.close(old_stderr)

    try:
        print("[AUDIO] Inicjalizacja PyAudio...")

        # Inicjalizuj PyAudio z wyciszonymi ostrzeżeniami ALSA
        with suppress_alsa_errors():
            audio = pyaudio.PyAudio()

        print("[AUDIO] PyAudio OK")

        # Wyświetl dostępne urządzenia
        device_count = audio.get_device_count()
        print(f"[AUDIO] Znaleziono {device_count} urządzeń audio")

        # Wyświetl wszystkie urządzenia wejściowe
        input_devices = []
        for i in range(device_count):
            try:
                with suppress_alsa_errors():
                    info = audio.get_device_info_by_index(i)
                print(f"[AUDIO] Device {i}: {info['name']}")
                print(f"        Input channels: {info['maxInputChannels']}")
                if info['maxInputChannels'] > 0:
                    input_devices.append((i, info))
                    print(f"        >>> MIKROFON <<<")
            except Exception as e:
                print(f"[AUDIO] Błąd odczytu urządzenia {i}: {e}")

        if not input_devices:
            print("[WARN] Nie znaleziono żadnych urządzeń wejściowych!")
            audio = None
            audio_device_index = None
            return False

        # Spróbuj najpierw domyślnego urządzenia
        try:
            with suppress_alsa_errors():
                default_input = audio.get_default_input_device_info()
            if default_input['maxInputChannels'] > 0:
                audio_device_index = default_input['index']
                print(f"[AUDIO] Domyślne urządzenie: {default_input['name']}")
                print(f"[AUDIO] Device index: {audio_device_index}")

                # TEST - Spróbuj otworzyć stream aby sprawdzić czy działa
                try:
                    with suppress_alsa_errors():
                        test_stream = audio.open(
                            format=AUDIO_FORMAT,
                            channels=AUDIO_CHANNELS,
                            rate=AUDIO_RATE,
                            input=True,
                            input_device_index=audio_device_index,
                            frames_per_buffer=AUDIO_CHUNK
                        )
                        test_stream.close()
                    print("[AUDIO] ✓ Test stream OK - urządzenie działa!")
                    return True
                except Exception as e:
                    print(f"[AUDIO] ✗ Test stream FAILED: {e}")
        except Exception as e:
            print(f"[AUDIO] Nie można użyć domyślnego urządzenia: {e}")

        # Jeśli domyślne nie działa, testuj wszystkie dostępne urządzenia
        print("[AUDIO] Testuję wszystkie dostępne urządzenia wejściowe...")
        for idx, info in input_devices:
            print(f"[AUDIO] Próba {idx}: {info['name']}")
            try:
                with suppress_alsa_errors():
                    test_stream = audio.open(
                        format=AUDIO_FORMAT,
                        channels=AUDIO_CHANNELS,
                        rate=AUDIO_RATE,
                        input=True,
                        input_device_index=idx,
                        frames_per_buffer=AUDIO_CHUNK
                    )
                    test_stream.close()

                # Jeśli test się powiódł, użyj tego urządzenia
                audio_device_index = idx
                print(f"[AUDIO] ✓ SUKCES! Używam urządzenia {idx}: {info['name']}")
                return True
            except Exception as e:
                print(f"[AUDIO] ✗ Urządzenie {idx} nie działa: {e}")
                continue

        # Jeśli żadne urządzenie nie działa
        print("[ERROR] Żadne urządzenie audio nie działa!")
        audio = None
        audio_device_index = None
        return False

    except Exception as e:
        print(f"[WARN] Błąd inicjalizacji audio: {e}")
        import traceback
        traceback.print_exc()
        audio = None
        audio_device_index = None
        return False


def calculate_audio_level(data):
    """Oblicz poziom głośności z danych audio (RMS) dla dwóch kanałów)"""
    try:
        # Konwertuj bajty na wartości int16
        audio_data = np.frombuffer(data, dtype=np.int16)

        # Dane są przeplatane (L1, R1, L2, R2, ...)
        # Oddziel kanał lewy (indeksy parzyste: 0, 2, 4, ...)
        audio_data_left = audio_data[0::2].astype(np.float64)
        # Oddziel kanał prawy (indeksy nieparzyste: 1, 3, 5, ...)
        audio_data_right = audio_data[1::2].astype(np.float64)

        # Oblicz RMS (Root Mean Square) dla kanału L
        mean_square_left = np.mean(audio_data_left**2)
        rms_left = np.sqrt(mean_square_left) if mean_square_left >= 0 else 0.0

        # Oblicz RMS dla kanału R
        mean_square_right = np.mean(audio_data_right**2)
        rms_right = np.sqrt(mean_square_right) if mean_square_right >= 0 else 0.0

        # Normalizuj do zakresu 0.0 - 1.0 (max int16 to 32768)
        normalized_left = min(1.0, rms_left / 32768.0)
        normalized_right = min(1.0, rms_right / 32768.0)

        # Zastosuj nieliniową skalę (logarytmiczną) dla lepszej wizualizacji (jak wcześniej)
        if normalized_left > 0:
            normalized_left = min(1.0, normalized_left * 10)
        if normalized_right > 0:
            normalized_right = min(1.0, normalized_right * 10)

        # Zwróć poziomy dla obu kanałów
        return normalized_left, normalized_right

    except Exception as e:
        # W przypadku błędu zwróć 0.0 dla obu
        return 0.0, 0.0


def audio_monitoring_loop():
    """NOWY: Ciągły monitoring poziomu audio - działa w tle ZAWSZE (nie tylko podczas nagrywania)"""
    global audio_monitoring_stream, audio_monitoring_active, audio_level

    # Wycisz błędy ALSA
    import os
    import sys
    from contextlib import contextmanager

    @contextmanager
    def suppress_alsa_errors():
        """Tymczasowo wycisz błędy ALSA"""
        devnull = os.open(os.devnull, os.O_WRONLY)
        old_stderr = os.dup(2)
        sys.stderr.flush()
        os.dup2(devnull, 2)
        os.close(devnull)
        try:
            yield
        finally:
            os.dup2(old_stderr, 2)
            os.close(old_stderr)

    try:
        print(f"[AUDIO-MON] Start monitoringu poziomu dźwięku")

        # Otwórz stream audio TYLKO do odczytu poziomu (nie nagrywamy do pliku)
        with suppress_alsa_errors():
            audio_monitoring_stream = audio.open(
                format=AUDIO_FORMAT,
                channels=AUDIO_CHANNELS,
                rate=AUDIO_RATE,
                input=True,
                input_device_index=audio_device_index,
                frames_per_buffer=AUDIO_CHUNK
            )

        print("[AUDIO-MON] Stream monitoring otwarty")

        # Pętla monitorująca - działa dopóki audio_monitoring_active == True
        while audio_monitoring_active:
            try:
                # Odczytaj dane audio (ale NIE zapisuj do pliku)
                data = audio_monitoring_stream.read(AUDIO_CHUNK, exception_on_overflow=False)

                # Oblicz poziom głośności
                level_left, level_right = calculate_audio_level(data) # ZMIANA: odbierz dwa poziomy

                # Thread-safe update zmiennej globalnej
                globals()['audio_level'] = level_left           # ZMIANA
                globals()['audio_level_right'] = level_right    # NOWY

            except Exception as e:
                # Ignoruj błędy odczytu (przepełnienie bufora itp.)
                pass

        # Zamknij stream po zakończeniu
        if audio_monitoring_stream:
            audio_monitoring_stream.stop_stream()
            audio_monitoring_stream.close()
            audio_monitoring_stream = None

        print(f"[AUDIO-MON] Zatrzymano monitoring poziomu dźwięku")

    except Exception as e:
        print(f"[ERROR] Błąd monitoringu audio: {e}")
        audio_monitoring_active = False
        if audio_monitoring_stream:
            try:
                audio_monitoring_stream.stop_stream()
                audio_monitoring_stream.close()
            except:
                pass
            audio_monitoring_stream = None


def start_audio_monitoring():
    """NOWY: Uruchom ciągły monitoring poziomu audio"""
    global audio_monitoring_active, audio_monitoring_thread

    if not audio or audio_device_index is None:
        print("[WARN] Audio nie zainicjalizowane - brak monitoringu")
        return False

    if audio_monitoring_active:
        print("[WARN] Monitoring już aktywny")
        return True

    audio_monitoring_active = True

    # Uruchom wątek monitorujący
    audio_monitoring_thread = threading.Thread(target=audio_monitoring_loop, daemon=True)
    audio_monitoring_thread.start()

    print("[AUDIO-MON] Monitoring poziomu audio uruchomiony")
    return True


def stop_audio_monitoring():
    """NOWY: Zatrzymaj ciągły monitoring poziomu audio"""
    global audio_monitoring_active, audio_monitoring_thread, audio_level

    audio_monitoring_active = False
    audio_level = 0.0

    # Poczekaj na zakończenie wątku
    if audio_monitoring_thread and audio_monitoring_thread.is_alive():
        audio_monitoring_thread.join(timeout=2.0)
        audio_monitoring_thread = None

    print("[AUDIO-MON] Monitoring poziomu audio zatrzymany")


def audio_recording_thread(audio_filepath):
    """Wątek nagrywający audio w tle"""
    global audio_stream, audio_recording, audio_level

    # Wycisz błędy ALSA podczas nagrywania
    import os
    import sys
    from contextlib import contextmanager

    @contextmanager
    def suppress_alsa_errors():
        """Tymczasowo wycisz błędy ALSA"""
        devnull = os.open(os.devnull, os.O_WRONLY)
        old_stderr = os.dup(2)
        sys.stderr.flush()
        os.dup2(devnull, 2)
        os.close(devnull)
        try:
            yield
        finally:
            os.dup2(old_stderr, 2)
            os.close(old_stderr)

    try:
        print(f"[AUDIO] Start nagrywania: {audio_filepath}")
        print(f"[AUDIO] Device index: {audio_device_index}")
        print(f"[AUDIO] Format: {AUDIO_FORMAT}, Channels: {AUDIO_CHANNELS}, Rate: {AUDIO_RATE}")

        # Otwórz stream audio z wyciszonymi błędami ALSA
        with suppress_alsa_errors():
            audio_stream = audio.open(
                format=AUDIO_FORMAT,
                channels=AUDIO_CHANNELS,
                rate=AUDIO_RATE,
                input=True,
                input_device_index=audio_device_index,
                frames_per_buffer=AUDIO_CHUNK
            )

        print("[AUDIO] Stream otwarty pomyślnie")

        # Otwórz plik WAV do zapisu
        wf = wave.open(str(audio_filepath), 'wb')
        wf.setnchannels(AUDIO_CHANNELS)
        wf.setsampwidth(audio.get_sample_size(AUDIO_FORMAT))
        wf.setframerate(AUDIO_RATE)

        print("[AUDIO] Plik WAV otwarty, rozpoczynam nagrywanie...")

        frame_count = 0
        # Nagrywaj dopóki audio_recording == True
        while audio_recording:
            try:
                data = audio_stream.read(AUDIO_CHUNK, exception_on_overflow=False)
                wf.writeframes(data)

                # NAPRAWIONE: Oblicz poziom głośności i zapisz w zmiennej globalnej
                level_left, level_right = calculate_audio_level(data) # ZMIANA: odbierz dwa poziomy

                # Thread-safe update zmiennej globalnej
                globals()['audio_level'] = level_left           # ZMIANA
                globals()['audio_level_right'] = level_right    # NOWY

                frame_count += 1
                # Co sekundę wypisz diagnostykę
                if frame_count % 43 == 0:  # ~1 sekunda przy 44100Hz / 1024
                    print(f"[AUDIO] Nagrywanie... poziom L/R: {level_left:.3f}/{level_right:.3f}") # ZMIANA: diagnostyka L/R

            except Exception as e:
                print(f"[WARN] Błąd odczytu audio: {e}")
                import traceback
                traceback.print_exc()
                break

        # Zamknij stream i plik
        audio_stream.stop_stream()
        audio_stream.close()
        audio_stream = None
        wf.close()

        print(f"[AUDIO] Zatrzymano nagrywanie audio")
        print(f"[AUDIO] Nagrano {frame_count} ramek")

        # Sprawdź rozmiar pliku
        if audio_filepath.exists():
            size = audio_filepath.stat().st_size
            print(f"[AUDIO] Rozmiar pliku WAV: {size} bajtów")
        else:
            print("[ERROR] Plik audio nie został utworzony!")

    except Exception as e:
        print(f"[ERROR] Błąd nagrywania audio: {e}")
        import traceback
        traceback.print_exc()
        audio_recording = False
        if audio_stream:
            audio_stream.stop_stream()
            audio_stream.close()
            audio_stream = None


def start_audio_recording(video_filepath):
    """Rozpocznij nagrywanie audio"""
    global audio_recording, audio_thread, audio_file, audio_level

    # Sprawdź czy nagrywanie dźwięku jest włączone w ustawieniach
    if not camera_settings.get("audio_recording", True):
        print("[AUDIO] Nagrywanie dźwięku wyłączone w ustawieniach")
        return None

    if not audio:
        print("[WARN] Audio nie zainicjalizowane")
        return None

    # Ścieżka do pliku audio (ten sam stem co video)
    audio_file = video_filepath.parent / f"{video_filepath.stem}.wav"

    audio_level = 0.0
    audio_recording = True

    # Uruchom wątek nagrywania
    audio_thread = threading.Thread(target=audio_recording_thread, args=(audio_file,), daemon=True)
    audio_thread.start()

    return audio_file


def stop_audio_recording():
    """Zatrzymaj nagrywanie audio"""
    global audio_recording, audio_thread, audio_level, audio_level_right # ZMIANA: dodaj audio_level_right

    audio_recording = False
    audio_level = 0.0
    audio_level_right = 0.0 # NOWY: reset prawego kanału

    # Poczekaj na zakończenie wątku
    if audio_thread and audio_thread.is_alive():
        audio_thread.join(timeout=2.0)
        audio_thread = None


def merge_audio_video(video_path, audio_path):
    """Połącz audio i video w jeden plik MP4"""
    try:
        print(f"[MERGE] Łączenie audio i video...")

        if not audio_path.exists():
            print("[WARN] Plik audio nie istnieje")
            return False

        if audio_path.stat().st_size < 1000:
            print("[WARN] Plik audio zbyt mały, pomijam")
            audio_path.unlink()
            return True

        # Plik tymczasowy dla video z audio (lokalny dysk, nie karta SD)
        temp_output = THUMBNAIL_DIR / f"temp_merged_{video_path.name}"

        # Użyj ffmpeg do połączenia
        cmd = [
            "ffmpeg",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-c:v", "copy",  # Kopiuj video bez reenkodowania
            "-c:a", "aac",   # Enkoduj audio do AAC
            "-b:a", "128k",  # Bitrate audio 128kbps
            "-shortest",     # Użyj krótszego strumienia
            "-y",
            str(temp_output)
        ]

        print(f"[MERGE] Uruchamiam ffmpeg...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            print(f"[ERROR] Błąd ffmpeg: {result.stderr}")
            if temp_output.exists():
                temp_output.unlink()
            return False

        # Sprawdź czy plik został utworzony
        if not temp_output.exists() or temp_output.stat().st_size < 1000:
            print("[ERROR] Plik wyjściowy nieprawidłowy")
            if temp_output.exists():
                temp_output.unlink()
            return False

        # Zamień pliki - użyj shutil.move dla operacji między różnymi systemami plików
        print(f"[MERGE] Przenoszenie {temp_output.stat().st_size / (1024*1024):.1f} MB na kartę SD...")
        video_path.unlink()  # Usuń stary plik
        shutil.move(str(temp_output), str(video_path))  # Przenieś nowy plik (działa między różnymi filesystemami)
        print(f"[MERGE] Plik przeniesiony na kartę SD")

        # Usuń plik audio
        audio_path.unlink()
        print(f"[MERGE] Plik audio usunięty")

        print(f"[OK] Audio i video połączone")
        return True

    except Exception as e:
        print(f"[ERROR] Błąd łączenia: {e}")
        if 'temp_output' in locals() and temp_output.exists():
            temp_output.unlink()
        return False


def draw_audio_level_indicator():
    """Rysuj wskaźnik poziomu głośności - styl VU meter z 48K, CH1/CH2 i segmentami"""
    if not audio or current_state != STATE_MAIN or recording:
        return

    # Poziomy audio z globalnych zmiennych
    level_left = globals().get('audio_level', 0.0)
    level_right = globals().get('audio_level_right', 0.0)

    # Pozycja nad przyciskiem P-MENU (lewy dolny róg)
    button_x = 20
    indicator_height_total = 80  # Zwiększone z 50 na 80
    indicator_x = button_x
    indicator_y = SCREEN_HEIGHT - 75 - indicator_height_total - 15  # 15px nad przyciskiem

    # Styl segmentowy - 15 segmentów na kanał (10 białych + 3 pomarańczowe + 2 czerwone)
    segment_count = 15
    segment_width = 20  # Zwiększone - dłuższe
    segment_height = 14  # Zmniejszone - mniej wysokie
    segment_spacing = 3  # Zwiększone z 2 na 3

    # --- Napis "ALC" nad wskaźnikiem, wyrównany do lewej ---
    alc_x = indicator_x + 8
    alc_y = indicator_y - 25  # Nad wskaźnikiem
    draw_text_with_outline("ALC", font_large, WHITE, BLACK, alc_x, alc_y)

    # --- "48K" label na początku (z czarnym outline, czcionka 70) ---
    label_48k_x = indicator_x + 8
    label_48k_y = indicator_y + indicator_height_total // 2 - 10
    draw_text_with_outline("48K", font_70, WHITE, BLACK, label_48k_x, label_48k_y)

    # --- "CH1" i "CH2" labels (stacked) - przesunięte o 10px w prawo, z czarnym outline ---
    ch_labels_x = label_48k_x + 35 + 65  # Na prawo od 48K
    ch1_y = indicator_y + 30
    ch2_y = indicator_y + indicator_height_total - 26
    draw_text_with_outline("CH1", font_small, WHITE, BLACK, ch_labels_x, ch1_y)
    draw_text_with_outline("CH2", font_small, WHITE, BLACK, ch_labels_x, ch2_y)

    # --- Segmenty dla CH1 (górny rząd) - przesunięte jeszcze bardziej w prawo ---
    segments_start_x = ch_labels_x + 28 + 10 + 20  # Dodatkowe 20px przesunięcia
    bar_y_ch1 = ch1_y + 2
    active_segments_left = int(level_left * segment_count)

    for i in range(segment_count):
        segment_x = segments_start_x + i * (segment_width + segment_spacing)

        # Kolor segmentu: 10 białych (przyciemniony->zielony), 3 pomarańczowe (przyciemniony->intensywny), 2 czerwone (przyciemniony->intensywny)
        if i < 10:
            # Białe segmenty - nieaktywne przyciemnione, aktywne zielone
            segment_color = GREEN if i < active_segments_left else (80, 80, 80)  # Przyciemniony biały
        elif i < 13:
            # Pomarańczowe segmenty - nieaktywne przyciemnione, aktywne intensywne
            segment_color = ORANGE if i < active_segments_left else (100, 65, 0)  # Przyciemniony pomarańczowy
        else:
            # Czerwone segmenty - nieaktywne przyciemnione, aktywne intensywne
            segment_color = RED if i < active_segments_left else (100, 0, 0)  # Przyciemniony czerwony

        # Rysuj segment z czarnym outlinem
        pygame.draw.rect(screen, segment_color, (segment_x, bar_y_ch1, segment_width, segment_height))
        pygame.draw.rect(screen, BLACK, (segment_x, bar_y_ch1, segment_width, segment_height), 1)

    # --- Segmenty dla CH2 (dolny rząd) ---
    bar_y_ch2 = ch2_y + 2
    active_segments_right = int(level_right * segment_count)

    for i in range(segment_count):
        segment_x = segments_start_x + i * (segment_width + segment_spacing)

        # Kolor segmentu: 10 białych (przyciemniony->zielony), 3 pomarańczowe (przyciemniony->intensywny), 2 czerwone (przyciemniony->intensywny)
        if i < 10:
            # Białe segmenty - nieaktywne przyciemnione, aktywne zielone
            segment_color = GREEN if i < active_segments_right else (80, 80, 80)  # Przyciemniony biały
        elif i < 13:
            # Pomarańczowe segmenty - nieaktywne przyciemnione, aktywne intensywne
            segment_color = ORANGE if i < active_segments_right else (100, 65, 0)  # Przyciemniony pomarańczowy
        else:
            # Czerwone segmenty - nieaktywne przyciemnione, aktywne intensywne
            segment_color = RED if i < active_segments_right else (100, 0, 0)  # Przyciemniony czerwony

        # Rysuj segment z czarnym outlinem
        pygame.draw.rect(screen, segment_color, (segment_x, bar_y_ch2, segment_width, segment_height))
        pygame.draw.rect(screen, BLACK, (segment_x, bar_y_ch2, segment_width, segment_height), 1)


# ============================================================================
# FUNKCJE KONFIGURACJI
# ============================================================================

def load_config():
    """Wczytaj konfigurację"""
    global camera_settings
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r') as f:
                loaded = json.load(f)
                camera_settings.update(loaded)
            print("[OK] Konfiguracja wczytana")
        else:
            save_config()
    except Exception as e:
        print(f"[WARN] Błąd wczytywania config: {e}")


def save_config():
    """Zapisz konfigurację"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(camera_settings, f, indent=2)
        print("[OK] Konfiguracja zapisana")
    except Exception as e:
        print(f"[WARN] Błąd zapisu config: {e}")


def reset_to_factory():
    """Reset do ustawień fabrycznych"""
    global camera_settings
    camera_settings = {
        "video_resolution": "1080p50",
        "white_balance": "auto",
        "brightness": 0.0,
        "contrast": 1.0,
        "saturation": 1.0,
        "sharpness": 1.0,
        "exposure_compensation": 0.0,
        "awb_mode": "auto",
        "show_date": False,
        "show_time": False,
        "date_position": "top_left",
        "manual_date": None,
        "zoom": 0.0,
        "show_grid": True,
    }
    save_config()
    apply_camera_settings()
    print("[OK] Reset do ustawień fabrycznych")


def reset_quality_settings():
    """Reset ustawień jakości"""
    camera_settings["video_resolution"] = "1080p30"
    save_config()
    apply_camera_settings()
    print("[OK] Reset ustawień jakości")


def reset_manual_settings():
    """Reset ustawień manualnych"""
    camera_settings["white_balance"] = "auto"
    camera_settings["brightness"] = 0.0
    camera_settings["contrast"] = 1.0
    camera_settings["saturation"] = 1.0
    camera_settings["sharpness"] = 1.0
    camera_settings["exposure_compensation"] = 0.0
    camera_settings["awb_mode"] = "auto"
    camera_settings["iso_mode"] = "auto"
    save_config()
    apply_camera_settings()
    print("[OK] Reset ustawień manualnych")


def reset_date_settings():
    """Reset ustawień daty"""
    camera_settings["show_date"] = False
    camera_settings["show_time"] = False
    camera_settings["date_position"] = "top_left"
    camera_settings["manual_date"] = None
    save_config()
    print("[OK] Reset ustawień daty")


def apply_camera_settings():
    """Zastosuj ustawienia do kamery"""
    if not camera:
        return

    try:
        controls = {}

        if "brightness" in camera_settings:
            controls["Brightness"] = camera_settings["brightness"]

        if "contrast" in camera_settings:
            controls["Contrast"] = camera_settings["contrast"]

        if "saturation" in camera_settings:
            controls["Saturation"] = camera_settings["saturation"]

        if "sharpness" in camera_settings:
            controls["Sharpness"] = camera_settings["sharpness"]

        if "exposure_compensation" in camera_settings:
            controls["ExposureValue"] = camera_settings["exposure_compensation"]

        if "awb_mode" in camera_settings:
            mode = camera_settings["awb_mode"]
            if mode == "auto":
                controls["AwbEnable"] = True
                controls["AwbMode"] = 0  # Auto mode
            else:
                controls["AwbEnable"] = False
                # Ustawiamy fixed gains dla różnych trybów białego
                # Wartości (red_gain, blue_gain) dla różnych temperatur
                colour_gains_map = {
                    "incandescent": (1.8, 1.2),   # 2800K - ciepłe światło
                    "tungsten": (1.7, 1.3),        # 3200K
                    "fluorescent": (1.4, 1.5),     # 4000K - chłodniejsze
                    "indoor": (1.5, 1.4),          # 3800K
                    "daylight": (1.0, 1.6),        # 5600K - światło dzienne
                    "cloudy": (0.9, 1.7)           # 6500K - zachmurzenie
                }
                if mode in colour_gains_map:
                    gains = colour_gains_map[mode]
                    controls["ColourGains"] = gains
                    print(f"[AWB] Ustawiono tryb: {mode} (gains: {gains})")

        # Night Vision Mode - nadpisuje inne ustawienia ekspozycji
        if camera_settings.get("night_vision_mode", False):
            print("[NIGHT VISION] Tryb Night Vision aktywny")

            # Wyłącz automatyczną ekspozycję (AEC) - KLUCZOWE dla stabilności obrazu IR
            controls["AeEnable"] = False

            # Ustaw stały czas ekspozycji w mikrosekundach
            # Dla 30fps: max ~33ms (33000μs), używamy 30ms dla bezpieczeństwa
            # Dla 50fps: max ~20ms (20000μs), używamy 18ms dla bezpieczeństwa
            resolution = camera_settings.get("video_resolution", "1080p30")
            fps = RESOLUTION_MAP.get(resolution, {"fps": 30})["fps"]

            if fps >= 50:
                exposure_time = 18000  # 18ms dla 50fps
            else:
                exposure_time = 30000  # 30ms dla 30fps

            controls["ExposureTime"] = exposure_time

            # Zwiększ czułość (gain) dla lepszej widoczności w IR
            # Wartości gain: 1.0 - 16.0 (wyższe = jaśniejszy obraz, ale więcej szumu)
            controls["AnalogueGain"] = 8.0  # Średnia wartość dla IR

            # Wyłącz redukcję szumów - może powodować migotanie
            controls["NoiseReductionMode"] = 0  # 0 = Off

            print(f"[NIGHT VISION] ExposureTime={exposure_time}μs, Gain=8.0, FPS={fps}")
        else:
            # Normalny tryb dzienny - ISO (Analogue Gain) setting
            if "iso_mode" in camera_settings:
                iso_mode = camera_settings["iso_mode"]
                if iso_mode == "auto":
                    # Tryb auto - włącz AEC
                    controls["AeEnable"] = True
                    print(f"[ISO] Tryb AUTO - AEC włączony")
                elif iso_mode in ISO_TO_GAIN:
                    gain_value = ISO_TO_GAIN[iso_mode]
                    if gain_value is not None:
                        # Wyłącz AEC i ustaw stały gain
                        controls["AeEnable"] = False
                        controls["AnalogueGain"] = gain_value
                        print(f"[ISO] Ustawiono ISO {iso_mode} (gain: {gain_value}) - AEC wyłączony")

        if "zoom" in camera_settings:
            apply_zoom(camera_settings["zoom"])

        camera.set_controls(controls)
        print(f"[OK] Ustawienia kamery zastosowane")

    except Exception as e:
        print(f"[WARN] Błąd ustawiania kamery: {e}")


def apply_zoom(zoom_level):
    """Zastosuj cyfrowy zoom"""
    if not camera:
        return
    
    try:
        sensor_size = camera.camera_properties['PixelArraySize']
        width, height = sensor_size
        
        max_zoom_factor = 4.0
        zoom_factor = 1.0 + (zoom_level * (max_zoom_factor - 1.0))
        
        crop_width = int(width / zoom_factor)
        crop_height = int(height / zoom_factor)
        
        x = (width - crop_width) // 2
        y = (height - crop_height) // 2
        
        camera.set_controls({"ScalerCrop": (x, y, crop_width, crop_height)})
        
    except Exception as e:
        print(f"[WARN] Błąd zoom: {e}")


def adjust_zoom(delta):
    """Zmień zoom o delta"""
    global camera_settings, last_zoom_change_time

    new_zoom = camera_settings["zoom"] + delta
    new_zoom = max(0.0, min(1.0, new_zoom))

    camera_settings["zoom"] = new_zoom
    apply_zoom(new_zoom)
    last_zoom_change_time = time.time()


def restore_ir_filter_state():
    """Przywróć ostatni zapisany stan filtra IR przy starcie"""
    global ir_mode_day, camera_settings

    # Sprawdź czy w konfiguracji jest zapisany stan filtra
    saved_state = camera_settings.get("ir_filter_day_mode", True)

    # Jeśli zapisany stan jest inny niż domyślny (True = dzień), przełącz
    if saved_state != ir_mode_day:
        print(f"[IR] Przywracanie zapisanego stanu: {'DZIEŃ' if saved_state else 'NOC'}")

        if saved_state:
            # Tryb dzienny - włącz filtr IR
            GPIO.output(IR_CUT_A, GPIO.HIGH)
            GPIO.output(IR_CUT_B, GPIO.LOW)
        else:
            # Tryb nocny - wyłącz filtr IR
            GPIO.output(IR_CUT_A, GPIO.LOW)
            GPIO.output(IR_CUT_B, GPIO.HIGH)

        time.sleep(0.1)
        GPIO.output(IR_CUT_A, GPIO.LOW)
        GPIO.output(IR_CUT_B, GPIO.LOW)

        ir_mode_day = saved_state

    # Zastosuj Night Vision i latarkę IR jeśli filtr jest wyłączony
    if not ir_mode_day:
        camera_settings["night_vision_mode"] = True
        GPIO.output(IR_LED, GPIO.HIGH)  # HIGH włącza latarkę IR
        print("[NIGHT VISION] Przywrócono tryb Night Vision")
        print("[IR LED] Latarka IR włączona (HIGH)")
    else:
        GPIO.output(IR_LED, GPIO.LOW)  # LOW wyłącza latarkę IR
        print("[IR LED] Latarka IR wyłączona (LOW)")

    print(f"[IR] Stan filtra: {'DZIEŃ' if ir_mode_day else 'NOC'}")


def toggle_ir_cut():
    """Zmienia polaryzację na mostku H, aby przełączyć filtr IR CUT"""
    global ir_mode_day, camera_settings

    if ir_mode_day:
        # POPRAWIONA LOGIKA: Tryb nocny = filtr IR wyłączony (odwrotnie niż było)
        print("[IR] Przełączanie: Tryb NOCNY (Filtr IR OFF)")
        GPIO.output(IR_CUT_A, GPIO.LOW)  # Odwrócone
        GPIO.output(IR_CUT_B, GPIO.HIGH)  # Odwrócone
    else:
        # POPRAWIONA LOGIKA: Tryb dzienny = filtr IR włączony (odwrotnie niż było)
        print("[IR] Przełączanie: Tryb DZIEŃ (Filtr IR ON)")
        GPIO.output(IR_CUT_A, GPIO.HIGH)  # Odwrócone
        GPIO.output(IR_CUT_B, GPIO.LOW)   # Odwrócone

    # Krótki impuls wystarczy do przełączenia mechanicznego filtra
    time.sleep(0.1)
    # Powrót do stanu spoczynkowego, aby nie grzać cewki filtra
    GPIO.output(IR_CUT_A, GPIO.LOW)
    GPIO.output(IR_CUT_B, GPIO.LOW)

    ir_mode_day = not ir_mode_day
    print(f"[IR] Tryb: {'DZIEŃ' if ir_mode_day else 'NOC'}")

    # Automatyczne włączenie/wyłączenie Night Vision i latarki IR
    if not ir_mode_day:
        # Filtr IR wyłączony (noc) - włącz Night Vision i latarkę IR
        camera_settings["night_vision_mode"] = True
        GPIO.output(IR_LED, GPIO.HIGH)  # HIGH włącza latarkę IR
        print("[NIGHT VISION] Automatycznie włączony")
        print("[IR LED] Latarka IR włączona (HIGH)")
        apply_camera_settings()
    else:
        # Filtr IR włączony (dzień) - wyłącz Night Vision i latarkę IR
        camera_settings["night_vision_mode"] = False
        GPIO.output(IR_LED, GPIO.LOW)  # LOW wyłącza latarkę IR
        print("[NIGHT VISION] Automatycznie wyłączony")
        print("[IR LED] Latarka IR wyłączona (LOW)")
        apply_camera_settings()

    # Zapisz stan filtra IR do pliku JSON
    camera_settings["ir_filter_day_mode"] = ir_mode_day
    save_config()


def add_date_overlay_to_video(video_path):
    """Dodaj overlay daty do video - zachowuje FPS"""
    if not camera_settings.get("show_date", False):
        print("[DATE] Data wyłączona - pomijam overlay")
        return True
    
    try:
        print(f"[DATE] Dodawanie daty do video...")
        
        # Pobierz FPS z nazwy pliku
        original_fps = extract_fps_from_filename(video_path.name)
        
        # Jeśli nie ma w nazwie, spróbuj opencv
        if not original_fps:
            probe_cap = cv2.VideoCapture(str(video_path))
            original_fps = probe_cap.get(cv2.CAP_PROP_FPS)
            probe_cap.release()
        
        if not original_fps or original_fps <= 0 or original_fps > 50:
            original_fps = get_current_fps()
        
        print(f"[VIDEO] Używam FPS: {original_fps}")
        
        # Przygotuj tekst daty
        if camera_settings.get("manual_date"):
            date_text = camera_settings["manual_date"]
        else:
            try:
                filename_parts = video_path.stem.split('_')
                if len(filename_parts) >= 3:
                    date_part = filename_parts[1]
                    time_part = filename_parts[2]
                    date_obj = datetime.strptime(f"{date_part}_{time_part}", "%Y%m%d_%H%M%S")

                    # Pobierz ustawienia formatu
                    date_format = camera_settings.get("date_format", "DD/MM/YYYY")
                    month_text = camera_settings.get("date_month_text", False)
                    separator = camera_settings.get("date_separator", "/")
                    show_time = camera_settings.get("show_time", False)

                    # Skróty miesięcy
                    month_names = ["STY", "LUT", "MAR", "KWI", "MAJ", "CZE",
                                  "LIP", "SIE", "WRZ", "PAŹ", "LIS", "GRU"]

                    # Pobierz komponenty daty
                    day = date_obj.strftime("%d")
                    month = month_names[date_obj.month - 1] if month_text else date_obj.strftime("%m")
                    year = date_obj.strftime("%Y")
                    time_str = date_obj.strftime("%H:%M:%S") if show_time else ""

                    # Formatuj datę według wybranego formatu
                    if date_format == "DD/MM/YYYY":
                        date_text = f"{day}{separator}{month}{separator}{year}"
                    elif date_format == "MM/DD/YYYY":
                        date_text = f"{month}{separator}{day}{separator}{year}"
                    elif date_format == "YYYY/MM/DD":
                        date_text = f"{year}{separator}{month}{separator}{day}"
                    else:
                        date_text = f"{day}{separator}{month}{separator}{year}"

                    # Dodaj czas jeśli włączony
                    if show_time:
                        date_text = f"{date_text} {time_str}"
                else:
                    date_obj = datetime.fromtimestamp(video_path.stat().st_mtime)
                    date_text = date_obj.strftime("%Y-%m-%d")
            except:
                date_text = datetime.now().strftime("%Y-%m-%d")

        print(f"[DATE] Tekst overlay: {date_text}")

        # ESCAPOWANIE dla ffmpeg
        date_text_escaped = date_text.replace('\\', '\\\\').replace(':', '\\:').replace("'", "\\'")

        # Ustaw pozycję
        position = camera_settings.get("date_position", "top_left")
        margin = 30

        if position == "top_left":
            x, y = str(margin), str(margin)
        elif position == "top_right":
            x = f"w-text_w-{margin}"
            y = str(margin)
        elif position == "bottom_left":
            x = str(margin)
            y = f"h-text_h-{margin}"
        elif position == "bottom_right":
            x = f"w-text_w-{margin}"
            y = f"h-text_h-{margin}"
        else:
            x, y = str(margin), str(margin)

        # Pobierz kolor z ustawień
        color_name = camera_settings.get("date_color", "yellow")

        # Mapowanie rozmiarów czcionek na wartości FFmpeg
        font_size_map = {
            "small": 24,
            "medium": 40,
            "large": 56,
            "extra_large": 72
        }

        # Pobierz rozmiar czcionki z ustawień
        font_size_name = camera_settings.get("date_font_size", "medium")
        font_size = font_size_map.get(font_size_name, 40)

        # Pobierz ścieżkę do wybranej czcionki z ustawień
        font_family = camera_settings.get("font_family", "HomeVideo")
        font_config = FONT_DEFINITIONS.get(font_family, FONT_DEFINITIONS["HomeVideo"])
        font_path_ffmpeg = font_config["path"]

        # Plik tymczasowy (lokalny dysk, nie karta SD)
        temp_file = THUMBNAIL_DIR / f"temp_{video_path.name}"

        # Filtr drawtext
        drawtext_filter = (
            f"drawtext="
            f"fontfile={font_path_ffmpeg}:"
            f"text='{date_text_escaped}':"
            f"fontcolor={color_name}:"
            f"fontsize={font_size}:"
            f"borderw=3:"
            f"bordercolor=black:"
            f"x={x}:"
            f"y={y}"
        )
        
        print(f"[VIDEO] Filtr: {drawtext_filter}")
        
        # Komenda ffmpeg
        cmd = [
            "ffmpeg",
            "-i", str(video_path),
            "-vf", drawtext_filter,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-fps_mode", "passthrough",
            "-c:a", "copy",
            "-y",
            str(temp_file)
        ]
        
        print(f"[VIDEO] Przetwarzanie ffmpeg...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        
        if result.returncode != 0:
            print(f"[WARN] FFmpeg error: {result.stderr}")
            if temp_file.exists():
                temp_file.unlink()
            return False
        
        if not temp_file.exists() or temp_file.stat().st_size < 1000:
            print(f"[WARN] Plik tymczasowy nieprawidłowy")
            if temp_file.exists():
                temp_file.unlink()
            return False
        
        # Weryfikacja FPS
        verify_cap = cv2.VideoCapture(str(temp_file))
        output_fps = verify_cap.get(cv2.CAP_PROP_FPS)
        verify_cap.release()
        
        print(f"[OK] FPS: {output_fps:.2f} (oczekiwano: {original_fps:.2f})")
        
        # Zamiana plików - użyj shutil.move dla operacji między różnymi systemami plików
        print(f"[DATE] Przenoszenie {temp_file.stat().st_size / (1024*1024):.1f} MB na kartę SD...")
        video_path.unlink()  # Usuń stary plik
        shutil.move(str(temp_file), str(video_path))  # Przenieś nowy plik (działa między różnymi filesystemami)
        print(f"[DATE] Plik przeniesiony na kartę SD")

        print(f"[OK] Data dodana pomyślnie")
        return True
        
    except Exception as e:
        print(f"[WARN] Błąd dodawania daty: {e}")
        import traceback
        traceback.print_exc()
        if 'temp_file' in locals() and temp_file.exists():
            temp_file.unlink()
        return False


# ============================================================================
# MENU SYSTEM
# ============================================================================

def init_menu_tiles():
    """Inicjalizuj kafelki głównego menu - listowy układ"""
    global menu_tiles

    menu_tiles = [
        {
            "id": "quality",
            "label": "Rozdzielczość",
            "value": lambda: camera_settings.get("video_resolution", "1080p30"),
            "icon": "[VIDEO]",
            "section": "Image Quality/Size"
        },
        {
            "id": "grid",
            "label": "Siatka pomocnicza",
            "value": lambda: "WŁ." if camera_settings.get("show_grid", False) else "WYŁ.",
            "icon": "[VIDEO]",
            "section": "Image Quality/Size"
        },
        {
            "id": "center_frame",
            "label": "Ramka środkowa",
            "value": lambda: "WŁ." if camera_settings.get("show_center_frame", True) else "WYŁ.",
            "icon": "[VIDEO]",
            "section": "Image Quality/Size"
        },
        {
            "id": "audio_rec",
            "label": "Nagrywanie dźwięku",
            "value": lambda: "WŁ." if camera_settings.get("audio_recording", True) else "WYŁ.",
            "icon": "[VIDEO]",
            "section": "Image Quality/Size"
        },
        {
            "id": "font",
            "label": "Czcionka",
            "value": lambda: camera_settings.get("font_family", "HomeVideo"),
            "icon": "[VIDEO]",
            "section": "Image Quality/Size"
        },
        {
            "id": "wb",
            "label": "White Balance",
            "value": lambda: camera_settings.get("awb_mode", "auto"),
            "icon": "[CONFIG]",
            "section": "Manual Settings"
        },
        {
            "id": "iso",
            "label": "ISO",
            "value": lambda: camera_settings.get("iso_mode", "auto").upper(),
            "icon": "[CONFIG]",
            "section": "Manual Settings"
        },
        {
            "id": "brightness",
            "label": "Jasność",
            "value": lambda: f"{camera_settings.get('brightness', 0.0):+.1f}",
            "icon": "[CONFIG]",
            "section": "Manual Settings"
        },
        {
            "id": "contrast",
            "label": "Kontrast",
            "value": lambda: f"{camera_settings.get('contrast', 1.0):.1f}",
            "icon": "[CONFIG]",
            "section": "Manual Settings"
        },
        {
            "id": "saturation",
            "label": "Saturacja",
            "value": lambda: f"{camera_settings.get('saturation', 1.0):.1f}",
            "icon": "[CONFIG]",
            "section": "Manual Settings"
        },
        {
            "id": "sharpness",
            "label": "Ostrość",
            "value": lambda: f"{camera_settings.get('sharpness', 1.0):.1f}",
            "icon": "[CONFIG]",
            "section": "Manual Settings"
        },
        {
            "id": "exposure",
            "label": "Ekspozycja",
            "value": lambda: f"{camera_settings.get('exposure_compensation', 0.0):.1f}",
            "icon": "[CONFIG]",
            "section": "Manual Settings"
        },
        {
            "id": "show_date",
            "label": "Pokaż date",
            "value": lambda: "WŁ." if camera_settings.get("show_date", False) else "WYŁ.",
            "icon": "[DATE]",
            "section": "Znacznik Daty"
        },
        {
            "id": "show_time",
            "label": "Pokaż godzine",
            "value": lambda: "WŁ." if camera_settings.get("show_time", False) else "WYŁ.",
            "icon": "[DATE]",
            "section": "Znacznik Daty"
        },
        {
            "id": "date_position",
            "label": "Pozycja daty",
            "value": lambda: camera_settings.get("date_position", "top_left"),
            "icon": "[DATE]",
            "section": "Znacznik Daty"
        },
        {
            "id": "manual_date",
            "label": "Ustaw datę ręcznie",
            "value": lambda: format_manual_date(camera_settings.get("manual_date")),
            "icon": "[DATE]",
            "section": "Znacznik Daty"
        },
        {
            "id": "date_format",
            "label": "Format daty",
            "value": lambda: camera_settings.get("date_format", "DD/MM/YYYY"),
            "icon": "[DATE]",
            "section": "Znacznik Daty"
        },
        {
            "id": "date_month_text",
            "label": "Miesiąc słownie",
            "value": lambda: "WŁ." if camera_settings.get("date_month_text", False) else "WYŁ.",
            "icon": "[DATE]",
            "section": "Znacznik Daty"
        },
        {
            "id": "date_separator",
            "label": "Separator daty",
            "value": lambda: "SLASH" if camera_settings.get("date_separator", "/") == "/" else ("SPACJA" if camera_settings.get("date_separator", "/") == " " else "KRESKA"),
            "icon": "[DATE]",
            "section": "Znacznik Daty"
        },
        {
            "id": "date_color",
            "label": "Kolor daty",
            "value": lambda: camera_settings.get("date_color", "yellow").upper(),
            "icon": "[DATE]",
            "section": "Znacznik Daty"
        },
        {
            "id": "date_font_size",
            "label": "Rozmiar czcionki",
            "value": lambda: camera_settings.get("date_font_size", "medium").upper(),
            "icon": "[DATE]",
            "section": "Znacznik Daty"
        },
        {
            "id": "battery_level",
            "label": "Fikcyjny poziom",
            "value": lambda: f"{fake_battery_level}%" if fake_battery_level is not None else "Rzeczywisty",
            "icon": "[BATT]",
            "section": "Poziom Baterii"
        }
    ]


def init_submenu(tile_id):
    """Inicjalizuj submenu"""
    global submenu_items, current_submenu
    
    current_submenu = tile_id
    
    if tile_id == "quality":
        submenu_items = [
            {"type": "header", "text": "[VIDEO] IMAGE QUALITY/SIZE"},
            {"type": "spacer"},
            {"type": "select", "label": "Rozdzielczość", "key": "video_resolution", "options": VIDEO_RESOLUTIONS},
            {"type": "toggle", "label": "Siatka pomocnicza", "key": "show_grid"},
            {"type": "select", "label": "Czcionka", "key": "font_family", "options": FONT_NAMES},
            {"type": "spacer"},
            {"type": "button", "label": "[RESET] RESET USTAWIEN", "action": "reset_section"},
        ]

    elif tile_id == "font":
        submenu_items = [
            {"type": "header", "text": "[VIDEO] CZCIONKA"},
            {"type": "spacer"},
            {"type": "select", "label": "Czcionka", "key": "font_family", "options": FONT_NAMES},
            {"type": "spacer"},
            {"type": "info", "text": "Zmiana czcionki wymaga"},
            {"type": "info", "text": "przeladowania interfejsu"},
        ]

    elif tile_id == "manual":
        submenu_items = [
            {"type": "header", "text": "[CONFIG] MANUAL SETTINGS"},
            {"type": "spacer"},
            {"type": "select", "label": "White Balance", "key": "awb_mode", "options": WB_MODES},
            {"type": "select", "label": "ISO", "key": "iso_mode", "options": ISO_MODES},
            {"type": "slider", "label": "Jasność", "key": "brightness", "min": -2.0, "max": 2.0, "step": 0.2},
            {"type": "slider", "label": "Kontrast", "key": "contrast", "min": 0.0, "max": 2.0, "step": 0.1},
            {"type": "slider", "label": "Saturacja", "key": "saturation", "min": 0.0, "max": 2.0, "step": 0.1},
            {"type": "slider", "label": "Ostrość", "key": "sharpness", "min": 0.0, "max": 4.0, "step": 0.2},
            {"type": "slider", "label": "Ekspozycja", "key": "exposure_compensation", "min": -2.0, "max": 2.0, "step": 0.2},
            {"type": "spacer"},
            {"type": "button", "label": "[RESET] RESET USTAWIEN", "action": "reset_section"},
        ]

    elif tile_id == "date":
        submenu_items = [
            {"type": "header", "text": "[DATE] ZNACZNIK DATY"},
            {"type": "spacer"},
            {"type": "toggle", "label": "Pokaż date", "key": "show_date"},
            {"type": "toggle", "label": "Pokaż godzine", "key": "show_time"},
            {"type": "select", "label": "Pozycja daty", "key": "date_position", "options": DATE_POSITIONS},
            {"type": "select", "label": "Format daty", "key": "date_format", "options": DATE_FORMATS},
            {"type": "toggle", "label": "Miesiąc słownie", "key": "date_month_text"},
            {"type": "select", "label": "Separator daty", "key": "date_separator", "options": DATE_SEPARATORS},
            {"type": "select", "label": "Kolor daty", "key": "date_color", "options": DATE_COLORS},
            {"type": "text", "label": "Reczna data", "key": "manual_date", "placeholder": "YYYY-MM-DD"},
            {"type": "spacer"},
            {"type": "button", "label": "[RESET] RESET USTAWIEN", "action": "reset_section"},
        ]

    elif tile_id == "battery":
        submenu_items = [
            {"type": "header", "text": "[BATT] POZIOM BATERII"},
            {"type": "spacer"},
            {"type": "battery_slider", "label": "Fikcyjny poziom", "key": "fake_battery", "min": 0, "max": 100, "step": 5},
            {"type": "spacer"},
            {"type": "button", "label": "[RESET] UZYJ RZECZYWISTEGO", "action": "reset_battery"},
        ]


def open_menu():
    """Otwórz menu główne"""
    global current_state, selected_tile, menu_editing_mode, selected_section, menu_value_editing

    init_menu_tiles()
    selected_tile = 0
    selected_section = 0
    menu_editing_mode = False
    menu_value_editing = False
    current_state = STATE_MENU
    print("\n[MENU] MENU OTWARTE")


def open_submenu(tile_id):
    """Otwórz submenu"""
    global current_state, submenu_selected, submenu_editing
    
    init_submenu(tile_id)
    submenu_selected = 2
    submenu_editing = False
    current_state = STATE_SUBMENU
    print(f"\n[SUBMENU] Submenu: {tile_id}")


def close_menu():
    """Zamknij menu"""
    global current_state, submenu_editing, menu_value_editing

    save_config()
    apply_camera_settings()
    submenu_editing = False
    menu_value_editing = False
    current_state = STATE_MAIN
    print("\n[MAIN] Ekran główny")


def close_submenu():
    """Zamknij submenu"""
    global current_state, submenu_editing
    
    save_config()
    apply_camera_settings()
    submenu_editing = False
    current_state = STATE_MENU
    print("\n[MENU] Menu główne")


def menu_navigate_left():
    """Nawigacja w lewo - wyjście z trybu edycji"""
    global menu_editing_mode
    if current_state == STATE_MENU and menu_editing_mode:
        menu_editing_mode = False
        print("[MENU] Wyjście z trybu edycji - wybór sekcji")


def menu_navigate_right():
    """Nawigacja w prawo - wejście do trybu edycji wartości"""
    global menu_editing_mode, selected_tile
    if current_state == STATE_MENU and not menu_editing_mode:
        menu_editing_mode = True
        selected_tile = 0
        print("[MENU] Wejście do trybu edycji wartości")


def menu_navigate_down():
    """Nawigacja w dół - wybór sekcji lub przewijanie opcji"""
    global selected_section, selected_tile, date_edit_day, date_edit_month, date_edit_year
    if current_state == STATE_MENU:
        if date_editing:
            # W trybie edycji daty: zmniejsz wartość aktualnego segmentu
            # Mapowanie segmentu na pole zależy od formatu daty
            date_format = camera_settings.get("date_format", "DD/MM/YYYY")

            if date_format == "DD/MM/YYYY":
                # Segmenty: 0=dzień, 1=miesiąc, 2=rok
                if date_edit_segment == 0:
                    date_edit_day = max(1, date_edit_day - 1)
                elif date_edit_segment == 1:
                    date_edit_month = max(1, date_edit_month - 1)
                elif date_edit_segment == 2:
                    date_edit_year = max(2000, date_edit_year - 1)
            elif date_format == "MM/DD/YYYY":
                # Segmenty: 0=miesiąc, 1=dzień, 2=rok
                if date_edit_segment == 0:
                    date_edit_month = max(1, date_edit_month - 1)
                elif date_edit_segment == 1:
                    date_edit_day = max(1, date_edit_day - 1)
                elif date_edit_segment == 2:
                    date_edit_year = max(2000, date_edit_year - 1)
            else:  # YYYY/MM/DD
                # Segmenty: 0=rok, 1=miesiąc, 2=dzień
                if date_edit_segment == 0:
                    date_edit_year = max(2000, date_edit_year - 1)
                elif date_edit_segment == 1:
                    date_edit_month = max(1, date_edit_month - 1)
                elif date_edit_segment == 2:
                    date_edit_day = max(1, date_edit_day - 1)

            print(f"[DATE] {date_edit_day:02d}-{date_edit_month:02d}-{date_edit_year:04d}")
        elif menu_value_editing:
            # W trybie edycji wartości: zablokuj nawigację
            return
        elif menu_editing_mode:
            # W trybie edycji: przewijaj opcje w dół
            section_names = ["Image Quality/Size", "Manual Settings", "Znacznik Daty", "Poziom Baterii"]
            current_section_name = section_names[selected_section]
            filtered_tiles = [tile for tile in menu_tiles if tile["section"] == current_section_name]
            selected_tile = min(len(filtered_tiles) - 1, selected_tile + 1)
        else:
            # Wybór sekcji: przełącz na następną sekcję
            selected_section = min(3, selected_section + 1)


def menu_navigate_up():
    """Nawigacja w górę - wybór sekcji lub przewijanie opcji"""
    global selected_section, selected_tile, date_edit_day, date_edit_month, date_edit_year
    if current_state == STATE_MENU:
        if date_editing:
            # W trybie edycji daty: zwiększ wartość aktualnego segmentu
            # Mapowanie segmentu na pole zależy od formatu daty
            date_format = camera_settings.get("date_format", "DD/MM/YYYY")

            if date_format == "DD/MM/YYYY":
                # Segmenty: 0=dzień, 1=miesiąc, 2=rok
                if date_edit_segment == 0:
                    date_edit_day = min(31, date_edit_day + 1)
                elif date_edit_segment == 1:
                    date_edit_month = min(12, date_edit_month + 1)
                elif date_edit_segment == 2:
                    date_edit_year = min(2099, date_edit_year + 1)
            elif date_format == "MM/DD/YYYY":
                # Segmenty: 0=miesiąc, 1=dzień, 2=rok
                if date_edit_segment == 0:
                    date_edit_month = min(12, date_edit_month + 1)
                elif date_edit_segment == 1:
                    date_edit_day = min(31, date_edit_day + 1)
                elif date_edit_segment == 2:
                    date_edit_year = min(2099, date_edit_year + 1)
            else:  # YYYY/MM/DD
                # Segmenty: 0=rok, 1=miesiąc, 2=dzień
                if date_edit_segment == 0:
                    date_edit_year = min(2099, date_edit_year + 1)
                elif date_edit_segment == 1:
                    date_edit_month = min(12, date_edit_month + 1)
                elif date_edit_segment == 2:
                    date_edit_day = min(31, date_edit_day + 1)

            print(f"[DATE] {date_edit_day:02d}-{date_edit_month:02d}-{date_edit_year:04d}")
        elif menu_value_editing:
            # W trybie edycji wartości: zablokuj nawigację
            return
        elif menu_editing_mode:
            # W trybie edycji: przewijaj opcje w górę
            selected_tile = max(0, selected_tile - 1)
        else:
            # Wybór sekcji: przełącz na poprzednią sekcję
            selected_section = max(0, selected_section - 1)


def submenu_navigate_up():
    """Nawigacja w górę w submenu"""
    global submenu_selected, fake_battery_level

    if submenu_editing:
        item = submenu_items[submenu_selected]
        if item["type"] == "slider":
            key = item["key"]
            camera_settings[key] = min(item["max"], camera_settings[key] + item["step"])
            apply_camera_settings()
        elif item["type"] == "battery_slider":
            current_level = fake_battery_level if fake_battery_level is not None else 100
            fake_battery_level = min(item["max"], current_level + item["step"])
        elif item["type"] == "select":
            key = item["key"]
            options = item["options"]
            current_idx = options.index(camera_settings[key]) if camera_settings[key] in options else 0
            new_idx = (current_idx + 1) % len(options)
            camera_settings[key] = options[new_idx]
            if key == "font_family":
                load_fonts()  # Przeładuj czcionki
                save_config()
            else:
                apply_camera_settings()
    else:
        submenu_selected = max(0, submenu_selected - 1)
        while submenu_selected > 0 and submenu_items[submenu_selected]["type"] in ["spacer", "header", "info"]:
            submenu_selected -= 1


def submenu_navigate_down():
    """Nawigacja w dół w submenu"""
    global submenu_selected, fake_battery_level

    if submenu_editing:
        item = submenu_items[submenu_selected]
        if item["type"] == "slider":
            key = item["key"]
            camera_settings[key] = max(item["min"], camera_settings[key] - item["step"])
            apply_camera_settings()
        elif item["type"] == "battery_slider":
            current_level = fake_battery_level if fake_battery_level is not None else 100
            fake_battery_level = max(item["min"], current_level - item["step"])
        elif item["type"] == "select":
            key = item["key"]
            options = item["options"]
            current_idx = options.index(camera_settings[key]) if camera_settings[key] in options else 0
            new_idx = (current_idx - 1) % len(options)
            camera_settings[key] = options[new_idx]
            if key == "font_family":
                load_fonts()  # Przeładuj czcionki
                save_config()
            else:
                apply_camera_settings()
    else:
        submenu_selected = min(len(submenu_items) - 1, submenu_selected + 1)
        while submenu_selected < len(submenu_items) - 1 and submenu_items[submenu_selected]["type"] in ["spacer", "header", "info"]:
            submenu_selected += 1


def submenu_ok():
    """Akcja OK w submenu"""
    global submenu_editing, submenu_edit_value
    
    item = submenu_items[submenu_selected]
    
    if item["type"] == "button":
        if item["action"] == "reset_section":
            if current_submenu == "quality":
                reset_quality_settings()
            elif current_submenu == "manual":
                reset_manual_settings()
            elif current_submenu == "date":
                reset_date_settings()
        elif item["action"] == "reset_battery":
            global fake_battery_level
            fake_battery_level = None

    elif item["type"] == "toggle":
        key = item["key"]
        camera_settings[key] = not camera_settings[key]
        save_config()

    elif item["type"] in ["slider", "select", "battery_slider"]:
        submenu_editing = not submenu_editing
    
    elif item["type"] == "text":
        if not submenu_editing:
            submenu_editing = True
            key = item["key"]
            submenu_edit_value = camera_settings[key] if camera_settings[key] else ""
        else:
            key = item["key"]
            camera_settings[key] = submenu_edit_value if submenu_edit_value else None
            submenu_editing = False
            submenu_edit_value = ""
            save_config()


def open_selection_popup(tile_id, options):
    """Otwórz małe okienko wyboru z listy opcji"""
    global current_state, popup_options, popup_selected, popup_tile_id

    popup_tile_id = tile_id
    popup_options = options

    # Znajdź aktualnie wybraną wartość
    current_value = camera_settings.get(tile_id.replace("_", "_"), None)
    if current_value and current_value in options:
        popup_selected = options.index(current_value)
    else:
        popup_selected = 0

    current_state = STATE_SELECTION_POPUP
    print(f"[POPUP] Otwarto popup wyboru dla: {tile_id}")


def open_date_picker():
    """Otwórz okienko wyboru daty"""
    global current_state, date_picker_day, date_picker_month, date_picker_year, date_picker_field

    # Inicjalizuj wartościami z manual_date lub aktualna data
    if camera_settings.get("manual_date"):
        try:
            from datetime import datetime
            date_obj = datetime.strptime(camera_settings["manual_date"], "%Y-%m-%d")
            date_picker_day = date_obj.day
            date_picker_month = date_obj.month
            date_picker_year = date_obj.year
        except:
            now = datetime.now()
            date_picker_day = now.day
            date_picker_month = now.month
            date_picker_year = now.year
    else:
        from datetime import datetime
        now = datetime.now()
        date_picker_day = now.day
        date_picker_month = now.month
        date_picker_year = now.year

    date_picker_field = 0  # Zacznij od dnia
    current_state = STATE_DATE_PICKER
    print("[DATE_PICKER] Otwarto date picker")


def close_popup():
    """Zamknij popup i wróć do menu"""
    global current_state, popup_tile_id, popup_options, popup_selected

    current_state = STATE_MENU
    popup_tile_id = None
    popup_options = []
    popup_selected = 0
    print("[POPUP] Zamknięto popup")


def popup_navigate_up():
    """Nawigacja w górę w popup"""
    global popup_selected
    popup_selected = max(0, popup_selected - 1)


def popup_navigate_down():
    """Nawigacja w dół w popup"""
    global popup_selected
    popup_selected = min(len(popup_options) - 1, popup_selected + 1)


def popup_confirm():
    """Zatwierdź wybór w popup"""
    global camera_settings

    if popup_tile_id and 0 <= popup_selected < len(popup_options):
        selected_value = popup_options[popup_selected]
        camera_settings[popup_tile_id] = selected_value
        save_config()

        # Specjalne akcje dla niektórych opcji
        if popup_tile_id == "font_family":
            load_fonts()
        elif popup_tile_id in ["brightness", "contrast", "saturation", "sharpness", "exposure_compensation", "awb_mode"]:
            apply_camera_settings()

        print(f"[POPUP] Wybrano: {selected_value}")
        close_popup()


def date_picker_navigate_left():
    """Nawigacja w lewo w date picker - przełącz pole"""
    global date_picker_field
    date_picker_field = max(0, date_picker_field - 1)


def date_picker_navigate_right():
    """Nawigacja w prawo w date picker - przełącz pole"""
    global date_picker_field
    date_picker_field = min(2, date_picker_field + 1)


def date_picker_navigate_up():
    """Zwiększ wartość aktualnego pola"""
    global date_picker_day, date_picker_month, date_picker_year

    if date_picker_field == 0:  # Dzień
        date_picker_day = min(31, date_picker_day + 1)
    elif date_picker_field == 1:  # Miesiąc
        date_picker_month = min(12, date_picker_month + 1)
    elif date_picker_field == 2:  # Rok
        date_picker_year = min(2099, date_picker_year + 1)


def date_picker_navigate_down():
    """Zmniejsz wartość aktualnego pola"""
    global date_picker_day, date_picker_month, date_picker_year

    if date_picker_field == 0:  # Dzień
        date_picker_day = max(1, date_picker_day - 1)
    elif date_picker_field == 1:  # Miesiąc
        date_picker_month = max(1, date_picker_month - 1)
    elif date_picker_field == 2:  # Rok
        date_picker_year = max(2000, date_picker_year - 1)


def date_picker_confirm():
    """Zatwierdź wybraną datę"""
    global camera_settings, current_state

    # Walidacja daty
    max_days = 31
    if date_picker_month in [4, 6, 9, 11]:
        max_days = 30
    elif date_picker_month == 2:
        # Sprawdź rok przestępny
        is_leap = (date_picker_year % 4 == 0 and date_picker_year % 100 != 0) or (date_picker_year % 400 == 0)
        max_days = 29 if is_leap else 28

    # Ogranicz dzień do maksymalnej wartości
    valid_day = min(date_picker_day, max_days)

    # Zapisz datę w formacie YYYY-MM-DD
    date_str = f"{date_picker_year:04d}-{date_picker_month:02d}-{valid_day:02d}"
    camera_settings["manual_date"] = date_str
    save_config()

    print(f"[DATE_PICKER] Ustawiono datę: {date_str}")
    current_state = STATE_MENU


def draw_menu_tiles(frame):
    """Rysuj menu z sekcjami pionowo po lewej stronie - ZMODYFIKOWANY UKŁAD"""
    if frame is not None:
        try:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_resized = cv2.resize(frame_rgb, (SCREEN_WIDTH, SCREEN_HEIGHT))
            frame_surface = pygame.surfarray.make_surface(np.transpose(frame_resized, (1, 0, 2)))
            screen.blit(frame_surface, (0, 0))
        except:
            screen.fill(BLACK)
    else:
        screen.fill(BLACK)

    overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    overlay.set_alpha(220)
    overlay.fill(BLACK)
    screen.blit(overlay, (0, 0))

    
    blue_gray_top = (70, 90, 110)  # Niebiesko-szary kolor

    gradient_height = SCREEN_HEIGHT
    start_color = BLACK
    end_color = blue_gray_top

    for y in range(gradient_height):
        ratio = y / gradient_height
        r = int(start_color[0] * (1 - ratio) + end_color[0] * ratio)
        g = int(start_color[1] * (1 - ratio) + end_color[1] * ratio) 
        b = int(start_color[2] * (1 - ratio) + end_color[2] * ratio)
        color = (r, g, b)
        pygame.draw.line(screen, color, (0, y), (SCREEN_WIDTH, y))

    

    # Wymiary paneli
    # Panel z sekcjami
    section_icon_size = 75
    section_panel_width = section_icon_size + 20
    section_height = section_icon_size
    
    # Panel z opcjami
    list_panel_margin = 30
    list_panel_x = section_panel_width + list_panel_margin
    list_panel_y = list_panel_margin
    list_panel_width = SCREEN_WIDTH - list_panel_x - list_panel_margin
    list_panel_height = SCREEN_HEIGHT - list_panel_y - 100 # Odejmujemy więcej, żeby zostawić miejsce na dolną belkę

    # Rysuj ramkę panelu z opcjami (prawy) - ciemniejszy odcień niebiesko-szarego z liniowym gradientem
    dark_blue_gray = (40, 50, 60)  # Ciemniejszy odcień niebiesko-szarego
    pygame.draw.rect(screen, dark_blue_gray, (list_panel_x, list_panel_y, list_panel_width, list_panel_height), border_radius=10)

    # Dodaj liniowy gradient - co 15 pikseli jasność +2, grubość linii -1 (start: 10px)
    # Cykl powtarza się gdy grubość dojdzie do 0
    line_spacing = 15
    brightness_increment = 2
    initial_line_thickness = 10
    cycle_length = initial_line_thickness + 1  # +1 żeby uwzględnić 0

    current_y = list_panel_y + line_spacing
    line_index = 0

    while current_y < list_panel_y + list_panel_height:
        # Cykliczny indeks (resetuje się po osiągnięciu cycle_length)
        cyclic_index = line_index % cycle_length

        # Oblicz nową jasność koloru
        brightness_boost = cyclic_index * brightness_increment
        line_color = (
            min(255, dark_blue_gray[0] + brightness_boost),
            min(255, dark_blue_gray[1] + brightness_boost),
            min(255, dark_blue_gray[2] + brightness_boost)
        )

        # Oblicz grubość linii (zmniejsza się o 1 co iterację, potem resetuje)
        line_thickness = initial_line_thickness - cyclic_index

        # Rysuj linię tylko jeśli ma grubość > 0
        if line_thickness > 0:
            for i in range(line_thickness):
                pygame.draw.line(screen, line_color,
                               (list_panel_x + 10, current_y + i),
                               (list_panel_x + list_panel_width - 10, current_y + i))

        current_y += line_spacing
        line_index += 1

    pygame.draw.rect(screen, LIGHT_BLUE, (list_panel_x, list_panel_y, list_panel_width, list_panel_height), 3, border_radius=10)

    # Dekoracyjny trójkąt w dolnej części kwadratu
    # Punkty trójkąta: lewy dolny róg, prawy dolny róg, górny środek (50px powyżej środka górnej krawędzi)
    triangle_left = (list_panel_x, list_panel_y + list_panel_height)
    triangle_right = (list_panel_x + list_panel_width, list_panel_y + list_panel_height)
    triangle_top = (list_panel_x + list_panel_width // 2, list_panel_y - 50)

    # Ciemniejszy kolor niż kwadrat (40, 50, 60 -> jeszcze ciemniejszy)
    triangle_base_color = (20, 25, 30)

    # Wysokość trójkąta - obliczamy z punktów
    triangle_height = triangle_left[1] - triangle_top[1]

    # Ucinamy 2/3 trójkąta (rysujemy tylko dolną 1/3)
    cut_offset = (triangle_height * 2) // 3
    visible_height = triangle_height - cut_offset

    # Oblicz wymiary powierzchni dla trójkąta
    triangle_surface_width = list_panel_width
    triangle_surface_height = visible_height

    # Utwórz osobną powierzchnię dla trójkąta z alpha
    triangle_surface = pygame.Surface((triangle_surface_width, triangle_surface_height), pygame.SRCALPHA)

    # Rysujemy trójkąt linia po linii z gradientem alpha
    for y_offset in range(visible_height):
        # Oblicz współrzędną Y (od 2/3 wysokości do dołu)
        current_y = triangle_top[1] + cut_offset + y_offset

        # Jeśli jesteśmy poza obszarem ekranu, przerwij
        if current_y >= list_panel_y + list_panel_height:
            break

        # Oblicz szerokość linii na tej wysokości (interpolacja liniowa)
        # Im niżej, tym szersza linia - obliczamy od początku trójkąta
        progress_from_top = (cut_offset + y_offset) / triangle_height
        line_width = int(list_panel_width * progress_from_top)

        # Gradient alpha: od dołu (255) do góry (0)
        alpha_ratio = y_offset / visible_height
        alpha = int(255 * alpha_ratio)

        # Oblicz pozycję X względem lewego górnego rogu surface
        line_x_start = (triangle_surface_width - line_width) // 2

        # Rysuj linię na surface
        line_color_with_alpha = (*triangle_base_color, alpha)
        for x in range(line_width):
            triangle_surface.set_at((line_x_start + x, y_offset), line_color_with_alpha)

    # Zastosuj lekkie rozmycie Gaussowskie
    # Używamy pygame.transform.smoothscale do symulacji rozmycia
    blur_size = max(2, triangle_surface_width // 50)  # Dynamiczny rozmiar rozmycia
    temp_small = pygame.transform.smoothscale(triangle_surface,
                                              (triangle_surface_width // blur_size,
                                               triangle_surface_height // blur_size))
    triangle_surface_blurred = pygame.transform.smoothscale(temp_small,
                                                            (triangle_surface_width,
                                                             triangle_surface_height))

    # Narysuj rozmyty trójkąt na ekranie
    triangle_blit_x = list_panel_x
    triangle_blit_y = triangle_top[1] + cut_offset
    screen.blit(triangle_surface_blurred, (triangle_blit_x, triangle_blit_y))

    # Sekcje po lewej stronie (pionowo, jedna pod drugą)
    sections = [
        {"icon": "[V]", "name": "Image Quality/Size"},
        {"icon": "[C]", "name": "Manual Settings"},
        {"icon": "[D]", "name": "Znacznik Daty"},
        {"icon": "[B]", "name": "Poziom Baterii"}
    ]

    section_x = list_panel_margin
    section_start_y = list_panel_y
    
    # Rysowanie sekcji i łączenie z panelem po prawej
    for i, section in enumerate(sections):
        y = section_start_y + i * section_height
        is_selected = (i == selected_section)

        # Rysuj tło i ramkę sekcji
        if is_selected and menu_editing_mode:
            # Kolor wybrany w trybie edycji - taki sam jak główny kwadrat
            bg_color = dark_blue_gray  # (40, 50, 60) - dopasowany do głównego panelu
            border_color = WHITE
        elif is_selected and not menu_editing_mode:
            # Kolor wybrany poza trybem edycji
            bg_color = (60, 60, 60)
            border_color = WHITE
        else:
            # Kolor niewybrany
            bg_color = (30, 30, 30)
            border_color = GRAY

        # Rysuj prostokąt
        rect_style = border_radius=10
        if is_selected and menu_editing_mode:
            # Jeśli wybrany i edytujemy (przeszliśmy strzałką w prawo), prostokąt łączy się z prawej
            pygame.draw.rect(screen, bg_color, (section_x, y, section_panel_width, section_height), rect_style)

            # Rysuj ramkę z pominięciem prawej krawędzi
            pygame.draw.line(screen, border_color, (section_x, y), (section_x + section_panel_width, y), 3) # Góra
            pygame.draw.line(screen, border_color, (section_x, y + section_height), (section_x + section_panel_width, y + section_height), 3) # Dół
            pygame.draw.line(screen, border_color, (section_x, y), (section_x, y + section_height), 3) # Lewa

            # Wypełnij szczelinę między sekcją a panelem głównym
            pygame.draw.rect(screen, bg_color, (section_x + section_panel_width - 3, y + 1, list_panel_x - (section_x + section_panel_width) + 6, section_height - 2))

        else:
            # Standardowy prostokąt z pełną ramką
            pygame.draw.rect(screen, bg_color, (section_x, y, section_panel_width, section_height), rect_style)
            pygame.draw.rect(screen, border_color, (section_x, y, section_panel_width, section_height), 3, rect_style)


        # Ikona - kolor zależy od stanu
        if is_selected and menu_editing_mode:
            # Jeśli wybrany i w trybie edycji (opcje po prawej zaznaczone) - biały
            icon_color = WHITE
        elif is_selected and not menu_editing_mode:
            # Jeśli wybrany ale nie w trybie edycji (aktualna zakładka, ikony z lewej zaznaczone) - żółty
            icon_color = YELLOW
        elif not menu_editing_mode:
            # Gdy zaznaczone są ikony z lewej (nawigacja po sekcjach), wszystkie nieaktywne ikony białe
            icon_color = WHITE
        else:
            # W trybie edycji opcji, nieaktywne ikony szare
            icon_color = GRAY
        draw_text(section["icon"], font_large, icon_color,
                  section_x + section_panel_width // 2, y + section_height // 2, center=True)


    # Panel z listą opcji dla wybranej sekcji (po prawej)
    # Filtruj opcje dla aktualnej sekcji
    section_names = ["Image Quality/Size", "Manual Settings", "Znacznik Daty", "Poziom Baterii"]
    current_section_name = section_names[selected_section]

    filtered_tiles = [tile for tile in menu_tiles if tile["section"] == current_section_name]

    # Rysuj elementy listy
    item_height = 70
    item_y = list_panel_y + 10

    # Dodatkowe przesunięcie w dół, żeby zaznaczenie było widoczne na środku
    visible_items = int((list_panel_height - 20) / item_height)

    # Scrolluj tylko jeśli elementów jest więcej niż zmieści się w panelu
    total_items = len(filtered_tiles)
    if total_items <= visible_items:
        scroll_offset = 0
    else:
        scroll_offset = max(0, selected_tile - visible_items // 2)

    for i, tile in enumerate(filtered_tiles):
        actual_idx = i

        # Opcje poza zakresem widoku
        if actual_idx < scroll_offset or actual_idx >= scroll_offset + visible_items:
            continue

        is_selected = (actual_idx == selected_tile and menu_editing_mode)
        current_y = item_y + (actual_idx - scroll_offset) * item_height

        # Tło zaznaczonego elementu
        if is_selected:
            # Gradient: ciemno granatowy na górze, jasnoniebieski na dole (1/3 wysokości)
            rect_x = list_panel_x + 5
            rect_y = current_y - 5
            rect_w = list_panel_width - 10
            rect_h = item_height

            # Ciemno granatowy kolor dla dolnych 2/3
            dark_navy = (15, 30, 60)
            # Jasnoniebieski dla górnej 1/3
            light_blue = (100, 150, 255)

            # Rysuj gradient - górna 1/3 z przejściem
            gradient_height = rect_h // 3
            for y_offset in range(rect_h):
                if y_offset < gradient_height:
                    # Gradient od jasnego do ciemnego
                    ratio = y_offset / gradient_height
                    r = int(light_blue[0] * (1 - ratio) + dark_navy[0] * ratio)
                    g = int(light_blue[1] * (1 - ratio) + dark_navy[1] * ratio)
                    b = int(light_blue[2] * (1 - ratio) + dark_navy[2] * ratio)
                    color = (r, g, b)
                else:
                    # Ciemno granatowy dla reszty
                    color = dark_navy

                pygame.draw.line(screen, color,
                               (rect_x, rect_y + 8 + y_offset),
                               (rect_x + rect_w, rect_y + 8 + y_offset))

            # Obramowanie - pomarańczowe gdy edytujemy wartość, białe normalnie
            border_color = ORANGE if menu_value_editing else WHITE
            pygame.draw.rect(screen, border_color,
                             (rect_x, rect_y + 8, rect_w, rect_h + 6), 5,
                             border_radius=8)

        # Label po lewej - z czarnym outline
        label_color = YELLOW if is_selected else WHITE
        draw_text_with_outline(tile["label"].upper(), menu_font, label_color, BLACK, list_panel_x + 25, current_y + 20)

        # Value po prawej - z czarnym outline
        try:
            value_text = tile["value"]() if callable(tile["value"]) else str(tile["value"])
        except:
            value_text = "---"

        value_color = YELLOW if is_selected else WHITE
        value_x = list_panel_x + list_panel_width - 25

        # Pobierz offsety dla aktualnej czcionki
        font_family = camera_settings.get("font_family", "HomeVideo")
        font_config = FONT_DEFINITIONS.get(font_family, FONT_DEFINITIONS["HomeVideo"])
        general_offset = font_config.get("general_offset", 0)
        polish_offset = font_config.get("polish_offset", 0)

        # Specjalne rysowanie dla daty w trybie edycji
        if tile["id"] == "manual_date" and date_editing:
            # Pobierz ustawienia formatu, separatora i miesiąca słownie
            separator = camera_settings.get("date_separator", "/")
            date_format = camera_settings.get("date_format", "DD/MM/YYYY")
            month_text = camera_settings.get("date_month_text", False)

            # Skróty miesięcy
            month_names = ["STY", "LUT", "MAR", "KWI", "MAJ", "CZE",
                          "LIP", "SIE", "WRZ", "PAŹ", "LIS", "GRU"]

            # Format zgodny z ustawieniami użytkownika z migającym segmentem
            day_str = f"{date_edit_day:02d}"
            # Użyj miesiąca słownie jeśli włączone
            if month_text:
                month_str = month_names[date_edit_month - 1]
                month_placeholder = "   "  # 3 spacje dla STY, LUT, etc.
            else:
                month_str = f"{date_edit_month:02d}"
                month_placeholder = "  "  # 2 spacje dla numerów
            year_str = f"{date_edit_year:04d}"

            # Pobierz aktualny czas dla migania
            global date_last_blink_time, date_blink_state
            current_time = pygame.time.get_ticks()
            if current_time - date_last_blink_time > 500:  # Migaj co 500ms
                date_blink_state = not date_blink_state
                date_last_blink_time = current_time

            # Określ który segment jest edytowany i migający w zależności od formatu
            # date_edit_segment: 0=pierwszy, 1=środkowy, 2=ostatni
            if date_format == "DD/MM/YYYY":
                # Segmenty: 0=day, 1=month, 2=year
                segment_values = [day_str, month_str, year_str]
                empty_placeholders = ["  ", month_placeholder, "    "]
            elif date_format == "MM/DD/YYYY":
                # Segmenty: 0=month, 1=day, 2=year
                segment_values = [month_str, day_str, year_str]
                empty_placeholders = [month_placeholder, "  ", "    "]
            else:  # YYYY/MM/DD
                # Segmenty: 0=year, 1=month, 2=day
                segment_values = [year_str, month_str, day_str]
                empty_placeholders = ["    ", month_placeholder, "  "]

            # Buduj tekst daty z uwzględnieniem migania
            date_parts = []
            for i, (value, placeholder) in enumerate(zip(segment_values, empty_placeholders)):
                if i == date_edit_segment:
                    # Ten segment miga
                    date_parts.append(value if date_blink_state else placeholder)
                else:
                    # Ten segment jest widoczny zawsze
                    date_parts.append(value)

                # Dodaj separator po pierwszym i drugim segmencie
                if i < 2:
                    date_parts.append(separator)

            value_text_upper = "".join(date_parts)

            # Oblicz offset
            polish_chars = 'śćźżóńŚĆŹŻÓŃ'
            has_polish = any(char in value_text_upper for char in polish_chars)
            y_offset = general_offset + (polish_offset if has_polish else 0)

            # Rysuj outline
            outline_width = 2
            for dx in range(-outline_width, outline_width + 1):
                for dy in range(-outline_width, outline_width + 1):
                    if dx == 0 and dy == 0:
                        continue
                    text_surface_outline = menu_font.render(value_text_upper, True, BLACK)
                    text_rect_outline = text_surface_outline.get_rect(topright=(value_x + dx, current_y + 20 + y_offset + dy))
                    screen.blit(text_surface_outline, text_rect_outline)

            # Rysuj tekst daty
            text_surface = menu_font.render(value_text_upper, True, value_color)
            text_rect = text_surface.get_rect(topright=(value_x, current_y + 20 + y_offset))
            screen.blit(text_surface, text_rect)
        else:
            # Standardowe rysowanie dla innych wartości
            value_text_upper = value_text.upper()

            # Sprawdź czy tekst zawiera polskie znaki diakrytyczne
            polish_chars = 'śćźżóńŚĆŹŻÓŃ'
            has_polish = any(char in value_text_upper for char in polish_chars)

            # Oblicz całkowity offset: ogólny offset + offset dla polskich znaków (jeśli są)
            y_offset = general_offset + (polish_offset if has_polish else 0)

            # Rysuj czarny outline dla value
            outline_width = 2
            for dx in range(-outline_width, outline_width + 1):
                for dy in range(-outline_width, outline_width + 1):
                    if dx == 0 and dy == 0:
                        continue
                    text_surface_outline = menu_font.render(value_text_upper, True, BLACK)
                    text_rect_outline = text_surface_outline.get_rect(topright=(value_x + dx, current_y + 20 + y_offset + dy))
                    screen.blit(text_surface_outline, text_rect_outline)

            # Rysuj właściwy tekst value
            text_surface = menu_font.render(value_text_upper, True, value_color)
            text_rect = text_surface.get_rect(topright=(value_x, current_y + 20 + y_offset))
            screen.blit(text_surface, text_rect)

    # Wskaźniki scrollowania dla listy opcji
    # Pokaż wskaźniki gdy jest więcej elementów niż mieści się na ekranie
    if total_items > visible_items:
        has_more_below = (scroll_offset + visible_items) < total_items
        has_more_above = scroll_offset > 0

        # Środek panelu z listą opcji (po prawej)
        arrow_x = list_panel_x + list_panel_width // 2

        # Strzałka w dół - gdy są więcej opcji poniżej
        if has_more_below:
            arrow_y = list_panel_y + list_panel_height - 25
            # Rysuj trójkąt skierowany w dół
            arrow_size = 15
            # Czarny outline (większy trójkąt)
            outline_size = arrow_size + 3
            pygame.draw.polygon(screen, BLACK, [
                (arrow_x, arrow_y + outline_size),  # Dolny wierzchołek
                (arrow_x - outline_size, arrow_y),   # Lewy górny wierzchołek
                (arrow_x + outline_size, arrow_y)    # Prawy górny wierzchołek
            ])
            # Żółty trójkąt na wierzchu
            pygame.draw.polygon(screen, YELLOW, [
                (arrow_x, arrow_y + arrow_size),  # Dolny wierzchołek
                (arrow_x - arrow_size, arrow_y),   # Lewy górny wierzchołek
                (arrow_x + arrow_size, arrow_y)    # Prawy górny wierzchołek
            ])

        # Strzałka w górę - gdy są więcej opcji powyżej
        if has_more_above:
            arrow_y = list_panel_y + 25
            # Rysuj trójkąt skierowany w górę
            arrow_size = 15
            # Czarny outline (większy trójkąt)
            outline_size = arrow_size + 3
            pygame.draw.polygon(screen, BLACK, [
                (arrow_x, arrow_y - outline_size),  # Górny wierzchołek
                (arrow_x - outline_size, arrow_y),   # Lewy dolny wierzchołek
                (arrow_x + outline_size, arrow_y)    # Prawy dolny wierzchołek
            ])
            # Żółty trójkąt na wierzchu
            pygame.draw.polygon(screen, YELLOW, [
                (arrow_x, arrow_y - arrow_size),  # Górny wierzchołek
                (arrow_x - arrow_size, arrow_y),   # Lewy dolny wierzchołek
                (arrow_x + arrow_size, arrow_y)    # Prawy dolny wierzchołek
            ])


def draw_menu_bottom_buttons():
    """Rysuj dolne przyciski menu - ZAWSZE NA WIERZCHU (wysoki z-index)"""
    # Dolne przyciski (bez belki w tle)
    bottom_bar_y = SCREEN_HEIGHT - 80
    exit_x = 40
    exit_y = bottom_bar_y + 15

    # Sprawdź czy jesteśmy w trybie popup
    in_popup_mode = (current_state == STATE_SELECTION_POPUP or current_state == STATE_DATE_PICKER)

    if in_popup_mode:
        # Tryb popup: COFNIJ / MENU i USTAW / OK (jak w trybie normalnym, ale COFNIJ zamiast WYJDŹ)
        # Lewy dolny róg: COFNIJ / MENU
        draw_text_with_outline("COFNIJ", font_large, WHITE, BLACK, exit_x, exit_y)

        menu_button_x = exit_x + 150
        menu_button_width = 140
        menu_button_height = 45
        pygame.draw.rect(screen, WHITE, (menu_button_x + 10, exit_y - 5, menu_button_width, menu_button_height),
                         border_radius=10)
        draw_text("MENU", font_large, BLACK, menu_button_x + 10 + menu_button_width // 2,
                  exit_y + menu_button_height // 2 - 5, center=True)

        # Prawy dolny róg: USTAW / OK
        ok_button_width = 100
        ok_button_x = SCREEN_WIDTH - 40 - ok_button_width
        ok_button_height = 45
        pygame.draw.rect(screen, WHITE, (ok_button_x + 13, exit_y - 5, ok_button_width - 25, ok_button_height),
                         border_radius=10)
        draw_text("OK", font_large, BLACK, ok_button_x + ok_button_width // 2,
                  exit_y + ok_button_height // 2 - 5, center=True)

        set_x = ok_button_x - 150
        draw_text_with_outline("USTAW", font_large, WHITE, BLACK, set_x, exit_y)
    else:
        # Tryb normalny: WYJDŹ / MENU i USTAW / OK
        # Lewy dolny róg: WYJDZ / MENU
        draw_text_with_outline("WYJDŹ", font_large, WHITE, BLACK, exit_x, exit_y)

        menu_button_x = exit_x + 150
        menu_button_width = 140
        menu_button_height = 45
        pygame.draw.rect(screen, WHITE, (menu_button_x + 10, exit_y - 5, menu_button_width, menu_button_height),
                         border_radius=10)
        draw_text("MENU", font_large, BLACK, menu_button_x + 10 + menu_button_width // 2,
                  exit_y + menu_button_height // 2 - 5, center=True)

        # Prawy dolny róg: USTAW / OK
        ok_button_width = 100
        ok_button_x = SCREEN_WIDTH - 40 - ok_button_width
        ok_button_height = 45
        pygame.draw.rect(screen, WHITE, (ok_button_x + 13, exit_y - 5, ok_button_width - 25, ok_button_height),
                         border_radius=10)
        draw_text("OK", font_large, BLACK, ok_button_x + ok_button_width // 2,
                  exit_y + ok_button_height // 2 - 5, center=True)

        set_x = ok_button_x - 150
        draw_text_with_outline("USTAW", font_large, WHITE, BLACK, set_x, exit_y)


def draw_submenu_screen(frame):
    """Rysuj submenu"""
    if frame is not None:
        try:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_resized = cv2.resize(frame_rgb, (SCREEN_WIDTH, SCREEN_HEIGHT))
            frame_surface = pygame.surfarray.make_surface(np.transpose(frame_resized, (1, 0, 2)))
            screen.blit(frame_surface, (0, 0))
        except:
            screen.fill(BLACK)
    else:
        screen.fill(BLACK)
    
    overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    overlay.set_alpha(220)
    overlay.fill(BLACK)
    screen.blit(overlay, (0, 0))
    
    menu_width = 1000
    menu_height = SCREEN_HEIGHT - 100
    menu_x = (SCREEN_WIDTH - menu_width) // 2
    menu_y = 50
    
    pygame.draw.rect(screen, DARK_GRAY, (menu_x, menu_y, menu_width, menu_height), border_radius=20)
    pygame.draw.rect(screen, BLUE, (menu_x, menu_y, menu_width, menu_height), 4, border_radius=20)
    
    item_height = 60
    visible_items = (menu_height - 100) // item_height
    scroll_offset = max(0, submenu_selected - visible_items // 2)
    
    y = menu_y + 30
    
    for i, item in enumerate(submenu_items[scroll_offset:scroll_offset + visible_items + 2]):
        actual_idx = i + scroll_offset
        
        if item["type"] == "header":
            draw_text(item["text"], font_medium, YELLOW, menu_x + menu_width // 2, y, center=True)
            y += 50
        
        elif item["type"] == "spacer":
            y += 20
        
        elif item["type"] == "slider":
            is_selected = (actual_idx == submenu_selected)

            if is_selected:
                pygame.draw.rect(screen, BLUE if not submenu_editing else ORANGE,
                               (menu_x + 20, y - 5, menu_width - 40, item_height - 10), border_radius=10)

            label_color = YELLOW if is_selected else WHITE
            draw_text(item["label"], font_small, label_color, menu_x + 40, y + 10)

            value = camera_settings[item["key"]]
            value_text = f"{value:.1f}"
            draw_text(value_text, font_small, GREEN if is_selected else GRAY, menu_x + menu_width - 250, y + 10)

            bar_x = menu_x + menu_width - 200
            bar_y = y + 20
            bar_width = 150
            bar_height = 10

            pygame.draw.rect(screen, GRAY, (bar_x, bar_y, bar_width, bar_height), border_radius=5)

            fill_ratio = (value - item["min"]) / (item["max"] - item["min"])
            fill_width = int(bar_width * fill_ratio)
            pygame.draw.rect(screen, GREEN, (bar_x, bar_y, fill_width, bar_height), border_radius=5)

            y += item_height

        elif item["type"] == "battery_slider":
            is_selected = (actual_idx == submenu_selected)

            if is_selected:
                pygame.draw.rect(screen, BLUE if not submenu_editing else ORANGE,
                               (menu_x + 20, y - 5, menu_width - 40, item_height - 10), border_radius=10)

            label_color = YELLOW if is_selected else WHITE
            draw_text(item["label"], font_small, label_color, menu_x + 40, y + 10)

            value = fake_battery_level if fake_battery_level is not None else 100
            value_text = f"{value}%" if fake_battery_level is not None else "AUTO"
            draw_text(value_text, font_small, GREEN if is_selected else GRAY, menu_x + menu_width - 250, y + 10)

            bar_x = menu_x + menu_width - 200
            bar_y = y + 20
            bar_width = 150
            bar_height = 10

            pygame.draw.rect(screen, GRAY, (bar_x, bar_y, bar_width, bar_height), border_radius=5)

            fill_ratio = (value - item["min"]) / (item["max"] - item["min"])
            fill_width = int(bar_width * fill_ratio)
            pygame.draw.rect(screen, GREEN, (bar_x, bar_y, fill_width, bar_height), border_radius=5)

            y += item_height
        
        elif item["type"] == "select":
            is_selected = (actual_idx == submenu_selected)
            
            if is_selected:
                pygame.draw.rect(screen, BLUE if not submenu_editing else ORANGE, 
                               (menu_x + 20, y - 5, menu_width - 40, item_height - 10), border_radius=10)
            
            label_color = YELLOW if is_selected else WHITE
            draw_text(item["label"], font_small, label_color, menu_x + 40, y + 15)
            
            value = camera_settings[item["key"]]
            value_color = GREEN if is_selected else GRAY
            draw_text(f"< {value} >", font_small, value_color, menu_x + menu_width - 250, y + 15)
            
            y += item_height
        
        elif item["type"] == "toggle":
            is_selected = (actual_idx == submenu_selected)
            
            if is_selected:
                pygame.draw.rect(screen, BLUE, 
                               (menu_x + 20, y - 5, menu_width - 40, item_height - 10), border_radius=10)
            
            label_color = YELLOW if is_selected else WHITE
            draw_text(item["label"], font_small, label_color, menu_x + 40, y + 15)
            
            value = camera_settings[item["key"]]
            toggle_text = "[YES] TAK" if value else "[NO] NIE"
            toggle_color = GREEN if value else RED
            draw_text(toggle_text, font_small, toggle_color, menu_x + menu_width - 200, y + 15)
            
            y += item_height
        
        elif item["type"] == "text":
            is_selected = (actual_idx == submenu_selected)
            
            if is_selected:
                pygame.draw.rect(screen, BLUE if not submenu_editing else ORANGE, 
                               (menu_x + 20, y - 5, menu_width - 40, item_height - 10), border_radius=10)
            
            label_color = YELLOW if is_selected else WHITE
            draw_text(item["label"], font_small, label_color, menu_x + 40, y + 15)
            
            if submenu_editing and is_selected:
                value_text = submenu_edit_value + "_"
            else:
                value = camera_settings[item["key"]]
                value_text = value if value else item.get("placeholder", "---")
            
            value_color = GREEN if is_selected else GRAY
            draw_text(value_text, font_tiny, value_color, menu_x + menu_width - 400, y + 15)
            
            y += item_height
        
        elif item["type"] == "info":
            # Wyświetl tekst informacyjny (nie można go zaznaczyć)
            draw_text(item["text"], font_tiny, GRAY, menu_x + menu_width // 2, y + 10, center=True)
            y += 30

        elif item["type"] == "button":
            is_selected = (actual_idx == submenu_selected)

            button_color = RED if "RESET" in item["label"] else GREEN

            if is_selected:
                pygame.draw.rect(screen, button_color,
                               (menu_x + 100, y - 5, menu_width - 200, item_height - 10), border_radius=15)
                pygame.draw.rect(screen, YELLOW,
                               (menu_x + 100, y - 5, menu_width - 200, item_height - 10), 5, border_radius=15)
            else:
                pygame.draw.rect(screen, button_color,
                               (menu_x + 100, y - 5, menu_width - 200, item_height - 10), border_radius=15)

            draw_text(item["label"], font_medium, WHITE, menu_x + menu_width // 2, y + 20, center=True)

            y += item_height + 10

    # Wskaźniki scrollowania
    total_items = len(submenu_items)

    # Zlicz tylko elementy które są opcjami (pomijamy header, spacer, info)
    selectable_items = sum(1 for item in submenu_items if item["type"] not in ["header", "spacer", "info"])

    # Pokaż wskaźniki gdy jest więcej niż 8 opcji
    has_more_below = (scroll_offset + visible_items + 2) < total_items
    has_more_above = scroll_offset > 0

    # Pokaż wskaźniki gdy jest więcej niż 8 wybieralnych opcji
    if selectable_items > 8:

        # Strzałka w dół - gdy są więcej opcji poniżej
        if has_more_below:
            arrow_y = menu_y + menu_height - 30
            arrow_x = menu_x + menu_width // 2
            # Rysuj trójkąt skierowany w dół
            arrow_size = 15
            # Czarny outline (większy trójkąt)
            outline_size = arrow_size + 3
            pygame.draw.polygon(screen, BLACK, [
                (arrow_x, arrow_y + outline_size),  # Dolny wierzchołek
                (arrow_x - outline_size, arrow_y),   # Lewy górny wierzchołek
                (arrow_x + outline_size, arrow_y)    # Prawy górny wierzchołek
            ])
            # Żółty trójkąt na wierzchu
            pygame.draw.polygon(screen, YELLOW, [
                (arrow_x, arrow_y + arrow_size),  # Dolny wierzchołek
                (arrow_x - arrow_size, arrow_y),   # Lewy górny wierzchołek
                (arrow_x + arrow_size, arrow_y)    # Prawy górny wierzchołek
            ])

        # Strzałka w górę - gdy są więcej opcji powyżej
        if has_more_above:
            arrow_y = menu_y + 80  # Poniżej nagłówka
            arrow_x = menu_x + menu_width // 2
            # Rysuj trójkąt skierowany w górę
            arrow_size = 15
            # Czarny outline (większy trójkąt)
            outline_size = arrow_size + 3
            pygame.draw.polygon(screen, BLACK, [
                (arrow_x, arrow_y - outline_size),  # Górny wierzchołek
                (arrow_x - outline_size, arrow_y),   # Lewy dolny wierzchołek
                (arrow_x + outline_size, arrow_y)    # Prawy dolny wierzchołek
            ])
            # Żółty trójkąt na wierzchu
            pygame.draw.polygon(screen, YELLOW, [
                (arrow_x, arrow_y - arrow_size),  # Górny wierzchołek
                (arrow_x - arrow_size, arrow_y),   # Lewy dolny wierzchołek
                (arrow_x + arrow_size, arrow_y)    # Prawy dolny wierzchołek
            ])

    if submenu_editing:
        instructions = "Up/Down: Zmień | OK: Zatwierdź | MENU: Anuluj"
    else:
        instructions = "Up/Down: Nawigacja | OK: Wybierz | MENU: Wróć"

    draw_text(instructions, font_small, WHITE, SCREEN_WIDTH // 2, SCREEN_HEIGHT - 30,
             center=True, bg_color=BLACK, padding=10)


def draw_selection_popup():
    """Rysuj małe okienko wyboru opcji"""
    if not popup_options:
        return

    # Przyciemnienie tła
    overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 200))
    screen.blit(overlay, (0, 0))

    # Wymiary popup
    popup_width = 600
    item_height = 80
    header_height = 80
    popup_height = min(600, len(popup_options) * item_height + 40 + header_height + 70) # +50 pikseli

    # Pozycja po prawej stronie ekranu
    popup_margin = 30
    popup_x = SCREEN_WIDTH - popup_width - popup_margin
    popup_y = (SCREEN_HEIGHT - popup_height) // 2 - 35  # -50 aby przesunąć o 50px w górę (nie w dół)

    # Tło popup - taki sam kolor jak główny kwadrat
    dark_blue_gray = (40, 50, 60)
    pygame.draw.rect(screen, dark_blue_gray, (popup_x, popup_y, popup_width, popup_height))

    # Dodaj liniowy gradient - algorytm jak w głównym kwadracie
    line_spacing = 15
    brightness_increment = 2
    initial_line_thickness = 10
    cycle_length = initial_line_thickness + 1

    current_y = popup_y + line_spacing
    line_index = 0

    while current_y < popup_y + popup_height:
        cyclic_index = line_index % cycle_length
        brightness_boost = cyclic_index * brightness_increment
        line_color = (
            min(255, dark_blue_gray[0] + brightness_boost),
            min(255, dark_blue_gray[1] + brightness_boost),
            min(255, dark_blue_gray[2] + brightness_boost)
        )
        line_thickness = initial_line_thickness - cyclic_index

        if line_thickness > 0:
            for i in range(line_thickness):
                pygame.draw.line(screen, line_color,
                               (popup_x + 10, current_y + i),
                               (popup_x + popup_width - 10, current_y + i))

        current_y += line_spacing
        line_index += 1

    # Białe obramowanie wokół całego okna
    pygame.draw.rect(screen, LIGHT_BLUE, (popup_x, popup_y, popup_width, popup_height), 3)

    # Nagłówek na czarnym tle
    pygame.draw.rect(screen, BLACK, (popup_x, popup_y, popup_width, header_height))

    # Mapowanie klucza ustawienia na nazwę wyświetlaną
    setting_to_label = {
        "video_resolution": "Rozdzielczość",
        "awb_mode": "White Balance",
        "iso_mode": "ISO",
        "date_position": "Pozycja daty",
        "date_format": "Format daty",
        "date_separator": "Separator daty",
        "date_color": "Kolor daty",
        "date_font_size": "Rozmiar czcionki",
        "font_family": "Czcionka"
    }

    # Znajdź nazwę opcji na podstawie popup_tile_id
    header_text = setting_to_label.get(popup_tile_id, "WYBIERZ OPCJĘ").upper()

    draw_text(header_text, menu_font, WHITE, popup_x + popup_width // 2, (popup_y + header_height // 2) + 10, center=True)

    # Białe obramowanie nagłówka (tylko góra, lewo, prawo - bez dołu)
    pygame.draw.line(screen, WHITE, (popup_x, popup_y), (popup_x + popup_width, popup_y), 3)  # Góra
    pygame.draw.line(screen, WHITE, (popup_x, popup_y), (popup_x, popup_y + header_height), 3)  # Lewo
    pygame.draw.line(screen, WHITE, (popup_x + popup_width, popup_y), (popup_x + popup_width, popup_y + header_height), 3)  # Prawo

    # Lista opcji - najpierw oblicz ile opcji się zmieści
    total_items = len(popup_options)
    available_space = popup_height - header_height
    fixed_padding = 20  # Stały padding gdy jest scrollowanie

    # Oblicz maksymalną liczbę widocznych elementów (z paddingiem)
    max_visible_items = (available_space - 2 * fixed_padding) // item_height

    # Sprawdź czy potrzebne scrollowanie
    needs_scrolling = total_items > max_visible_items

    if needs_scrolling:
        # Scrollowanie potrzebne - użyj stałego paddingu
        vertical_padding = fixed_padding
        visible_items = max_visible_items
    else:
        # Wszystkie opcje się mieszczą - wyśrodkuj (równa odległość od góry i dołu)
        total_items_height = total_items * item_height
        vertical_padding = (available_space - total_items_height) // 2
        visible_items = total_items

    list_start_y = popup_y + header_height + vertical_padding

    if needs_scrolling:
        # Scrollowanie potrzebne
        scroll_offset = max(0, min(popup_selected - visible_items // 2, total_items - visible_items))
    else:
        # Wszystkie opcje mieszczą się - brak scrollowania
        scroll_offset = 0

    # Ustaw clipping na obszar listy (żeby opcje nie nachodzily na nagłówek)
    list_clip_rect = pygame.Rect(
        popup_x,
        popup_y + header_height,
        popup_width,
        popup_height - header_height
    )
    screen.set_clip(list_clip_rect)

    for i in range(len(popup_options)):
        if i < scroll_offset or i >= scroll_offset + visible_items:
            continue

        option = popup_options[i]
        is_selected = (i == popup_selected)
        item_y = list_start_y + (i - scroll_offset) * item_height

        # Tło zaznaczonego elementu - taki sam gradient jak w głównym menu
        if is_selected:
            rect_x = popup_x + 20
            rect_y = item_y - 5
            rect_w = popup_width - 40
            rect_h = item_height - 10

            # Kolory gradientu jak w głównym menu
            dark_navy = (15, 30, 60)
            light_blue = (100, 150, 255)

            # Rysuj gradient - górna 1/3 z przejściem
            gradient_height_grad = rect_h // 3
            for y_offset in range(rect_h):
                if y_offset < gradient_height_grad:
                    # Gradient od jasnego do ciemnego
                    ratio = y_offset / gradient_height_grad
                    r = int(light_blue[0] * (1 - ratio) + dark_navy[0] * ratio)
                    g = int(light_blue[1] * (1 - ratio) + dark_navy[1] * ratio)
                    b = int(light_blue[2] * (1 - ratio) + dark_navy[2] * ratio)
                    color = (r, g, b)
                else:
                    # Ciemno granatowy dla reszty
                    color = dark_navy

                pygame.draw.line(screen, color,
                               (rect_x, rect_y + y_offset),
                               (rect_x + rect_w, rect_y + y_offset))

            # Białe obramowanie 5px
            pygame.draw.rect(screen, WHITE, (rect_x, rect_y, rect_w, rect_h), 5)
            text_color = YELLOW
        else:
            text_color = WHITE

        # Tekst opcji - używamy menu_font
        display_text = str(option).upper()
        draw_text(display_text, menu_font, text_color, popup_x + popup_width // 2, item_y + item_height // 2 - 10, center=True)

    # Wyłącz clipping przed rysowaniem wskaźników
    screen.set_clip(None)

    # Wskaźnik scrollowania - pokaż gdy są więcej opcji poniżej
    if needs_scrolling:
        has_more_below = (scroll_offset + visible_items) < total_items
        has_more_above = scroll_offset > 0

        # Strzałka w dół - gdy są więcej opcji poniżej
        if has_more_below:
            arrow_y = popup_y + popup_height - 30
            arrow_x = popup_x + popup_width // 2
            # Rysuj trójkąt skierowany w dół
            arrow_size = 15
            # Czarny outline (większy trójkąt)
            outline_size = arrow_size + 3
            pygame.draw.polygon(screen, BLACK, [
                (arrow_x, arrow_y + outline_size),  # Dolny wierzchołek
                (arrow_x - outline_size, arrow_y),   # Lewy górny wierzchołek
                (arrow_x + outline_size, arrow_y)    # Prawy górny wierzchołek
            ])
            # Żółty trójkąt na wierzchu
            pygame.draw.polygon(screen, YELLOW, [
                (arrow_x, arrow_y + arrow_size),  # Dolny wierzchołek
                (arrow_x - arrow_size, arrow_y),   # Lewy górny wierzchołek
                (arrow_x + arrow_size, arrow_y)    # Prawy górny wierzchołek
            ])

        # Strzałka w górę - gdy są więcej opcji powyżej
        if has_more_above:
            arrow_y = popup_y + header_height + 15
            arrow_x = popup_x + popup_width // 2
            # Rysuj trójkąt skierowany w górę
            arrow_size = 15
            # Czarny outline (większy trójkąt)
            outline_size = arrow_size + 3
            pygame.draw.polygon(screen, BLACK, [
                (arrow_x, arrow_y - outline_size),  # Górny wierzchołek
                (arrow_x - outline_size, arrow_y),   # Lewy dolny wierzchołek
                (arrow_x + outline_size, arrow_y)    # Prawy dolny wierzchołek
            ])
            # Żółty trójkąt na wierzchu
            pygame.draw.polygon(screen, YELLOW, [
                (arrow_x, arrow_y - arrow_size),  # Górny wierzchołek
                (arrow_x - arrow_size, arrow_y),   # Lewy dolny wierzchołek
                (arrow_x + arrow_size, arrow_y)    # Prawy dolny wierzchołek
            ])


def draw_date_picker():
    """Rysuj okienko wyboru daty z nawigacją lewo/prawo"""
    # Przyciemnienie tła
    overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 200))
    screen.blit(overlay, (0, 0))

    # Wymiary popup
    popup_width = 800
    header_height = 80
    popup_height = 280 + header_height

    # Pozycja po prawej stronie ekranu
    popup_margin = 30
    popup_x = SCREEN_WIDTH - popup_width - popup_margin
    popup_y = (SCREEN_HEIGHT - popup_height) // 2

    # Tło popup - taki sam kolor jak główny kwadrat
    dark_blue_gray = (40, 50, 60)
    pygame.draw.rect(screen, dark_blue_gray, (popup_x, popup_y, popup_width, popup_height))

    # Dodaj liniowy gradient - algorytm jak w głównym kwadracie
    line_spacing = 15
    brightness_increment = 2
    initial_line_thickness = 10
    cycle_length = initial_line_thickness + 1

    current_y = popup_y + line_spacing
    line_index = 0

    while current_y < popup_y + popup_height:
        cyclic_index = line_index % cycle_length
        brightness_boost = cyclic_index * brightness_increment
        line_color = (
            min(255, dark_blue_gray[0] + brightness_boost),
            min(255, dark_blue_gray[1] + brightness_boost),
            min(255, dark_blue_gray[2] + brightness_boost)
        )
        line_thickness = initial_line_thickness - cyclic_index

        if line_thickness > 0:
            for i in range(line_thickness):
                pygame.draw.line(screen, line_color,
                               (popup_x + 10, current_y + i),
                               (popup_x + popup_width - 10, current_y + i))

        current_y += line_spacing
        line_index += 1

    # Białe obramowanie wokół całego okna
    pygame.draw.rect(screen, LIGHT_BLUE, (popup_x, popup_y, popup_width, popup_height), 3)

    # Nagłówek na czarnym tle
    pygame.draw.rect(screen, BLACK, (popup_x, popup_y, popup_width, header_height))

    # Znajdź nazwę opcji - dla date picker zawsze "Ustaw datę ręcznie"
    header_text = "USTAW DATĘ RĘCZNIE"

    draw_text(header_text, menu_font, WHITE, popup_x + popup_width // 2, popup_y + header_height // 2, center=True)

    # Białe obramowanie nagłówka (tylko góra, lewo, prawo - bez dołu)
    pygame.draw.line(screen, WHITE, (popup_x, popup_y), (popup_x + popup_width, popup_y), 3)  # Góra
    pygame.draw.line(screen, WHITE, (popup_x, popup_y), (popup_x, popup_y + header_height), 3)  # Lewo
    pygame.draw.line(screen, WHITE, (popup_x + popup_width, popup_y), (popup_x + popup_width, popup_y + header_height), 3)  # Prawo

    # Pozycja pól
    field_y = popup_y + header_height + 50
    field_width = 150
    field_height = 100
    field_spacing = 60

    # Oblicz pozycje X dla trzech pól (dzień, miesiąc, rok)
    total_fields_width = field_width * 3 + field_spacing * 2
    start_x = popup_x + (popup_width - total_fields_width) // 2

    fields = [
        {"value": date_picker_day, "label": "DZIEŃ", "x": start_x},
        {"value": date_picker_month, "label": "MIESIĄC", "x": start_x + field_width + field_spacing},
        {"value": date_picker_year, "label": "ROK", "x": start_x + (field_width + field_spacing) * 2}
    ]

    # Rysuj pola
    for i, field in enumerate(fields):
        is_selected = (i == date_picker_field)

        # Tło pola - taki sam gradient jak w głównym menu
        if is_selected:
            rect_x = field["x"]
            rect_y = field_y
            rect_w = field_width
            rect_h = field_height

            # Kolory gradientu jak w głównym menu
            dark_navy = (15, 30, 60)
            light_blue = (100, 150, 255)

            # Rysuj gradient - górna 1/3 z przejściem
            gradient_height_grad = rect_h // 3
            for y_offset in range(rect_h):
                if y_offset < gradient_height_grad:
                    # Gradient od jasnego do ciemnego
                    ratio = y_offset / gradient_height_grad
                    r = int(light_blue[0] * (1 - ratio) + dark_navy[0] * ratio)
                    g = int(light_blue[1] * (1 - ratio) + dark_navy[1] * ratio)
                    b = int(light_blue[2] * (1 - ratio) + dark_navy[2] * ratio)
                    color = (r, g, b)
                else:
                    # Ciemno granatowy dla reszty
                    color = dark_navy

                pygame.draw.line(screen, color,
                               (rect_x, rect_y + y_offset),
                               (rect_x + rect_w, rect_y + y_offset))

            # Białe obramowanie 5px
            pygame.draw.rect(screen, WHITE, (rect_x, rect_y, rect_w, rect_h), 5)
            text_color = YELLOW
            label_color = YELLOW
        else:
            pygame.draw.rect(screen, (60, 60, 60), (field["x"], field_y, field_width, field_height))
            pygame.draw.rect(screen, GRAY, (field["x"], field_y, field_width, field_height), 3)
            text_color = WHITE
            label_color = GRAY

        # Label nad polem
        draw_text(field["label"], font_tiny, label_color, field["x"] + field_width // 2, field_y - 30, center=True)

        # Wartość
        value_text = f"{field['value']:02d}" if i < 2 else f"{field['value']:04d}"
        draw_text(value_text, font_large, text_color, field["x"] + field_width // 2, field_y + field_height // 2, center=True)

        # Strzałki dla zaznaczonego pola
        if is_selected:
            # Strzałka w górę
            arrow_up_y = field_y + 15
            draw_text("▲", font_medium, YELLOW, field["x"] + field_width // 2, arrow_up_y, center=True)

            # Strzałka w dół
            arrow_down_y = field_y + field_height - 30
            draw_text("▼", font_medium, YELLOW, field["x"] + field_width // 2, arrow_down_y, center=True)


# ============================================================================
# FUNKCJE POMOCNICZE
# ============================================================================

def draw_grid_overlay():
    """Rysuj siatkę 3x3"""
    if not camera_settings.get("show_grid", True):
        return

    x1 = SCREEN_WIDTH // 3
    x2 = 2 * SCREEN_WIDTH // 3

    y1 = SCREEN_HEIGHT // 3
    y2 = 2 * SCREEN_HEIGHT // 3

    grid_surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)

    line_color = (255, 255, 255, 80)
    line_width = 2

    pygame.draw.line(grid_surface, line_color, (x1, 0), (x1, SCREEN_HEIGHT), line_width)
    pygame.draw.line(grid_surface, line_color, (x2, 0), (x2, SCREEN_HEIGHT), line_width)

    pygame.draw.line(grid_surface, line_color, (0, y1), (SCREEN_WIDTH, y1), line_width)
    pygame.draw.line(grid_surface, line_color, (0, y2), (SCREEN_WIDTH, y2), line_width)

    screen.blit(grid_surface, (0, 0))


def draw_center_frame():
    """Rysuj ramkę środkową - dwa prostokąty z przerwą pośrodku"""
    if not camera_settings.get("show_center_frame", True):
        return

    # Wymiary ramki - znacznie mniejsza, proporcje 16:9 wycentrowane na ekranie
    frame_width = SCREEN_WIDTH // 6  # 1/6 szerokości ekranu (mniejsza)
    frame_height = int(frame_width * 9 / 16)  # Proporcje 16:9

    # Pozycja - wyśrodkowana
    frame_x = (SCREEN_WIDTH - frame_width) // 2
    frame_y = (SCREEN_HEIGHT - frame_height) // 2

    frame_surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)

    line_color = (255, 255, 255, 120)  # Biały z alpha
    line_width = 3

    # Większa szerokość przerwy pośrodku
    gap_width = 30

    # Środek ekranu
    center_x = SCREEN_WIDTH // 2

    # Lewy prostokąt (od frame_x do środka minus połowa przerwy)
    left_rect_width = (frame_width // 2) - (gap_width // 2)

    # Rysuj lewy prostokąt BEZ prawej krawędzi (rysujemy linie osobno)
    # Górna krawędź
    pygame.draw.line(frame_surface, line_color,
                     (frame_x, frame_y),
                     (frame_x + left_rect_width, frame_y),
                     line_width)
    # Dolna krawędź
    pygame.draw.line(frame_surface, line_color,
                     (frame_x, frame_y + frame_height),
                     (frame_x + left_rect_width, frame_y + frame_height),
                     line_width)
    # Lewa krawędź
    pygame.draw.line(frame_surface, line_color,
                     (frame_x, frame_y),
                     (frame_x, frame_y + frame_height),
                     line_width)

    # Prawy prostokąt (od środka plus połowa przerwy do końca ramki)
    right_rect_x = center_x + (gap_width // 2)
    right_rect_width = (frame_x + frame_width) - right_rect_x

    # Rysuj prawy prostokąt BEZ lewej krawędzi (rysujemy linie osobno)
    # Górna krawędź
    pygame.draw.line(frame_surface, line_color,
                     (right_rect_x, frame_y),
                     (right_rect_x + right_rect_width, frame_y),
                     line_width)
    # Dolna krawędź
    pygame.draw.line(frame_surface, line_color,
                     (right_rect_x, frame_y + frame_height),
                     (right_rect_x + right_rect_width, frame_y + frame_height),
                     line_width)
    # Prawa krawędź
    pygame.draw.line(frame_surface, line_color,
                     (right_rect_x + right_rect_width, frame_y),
                     (right_rect_x + right_rect_width, frame_y + frame_height),
                     line_width)

    screen.blit(frame_surface, (0, 0))


def get_battery_level():
    """Odczytaj poziom naładowania baterii (0-100) oraz prąd ładowania"""
    global battery_current, battery_voltage_samples

    # Jeśli ustawiono fikcyjny poziom baterii, użyj go
    if fake_battery_level is not None:
        battery_current = 0
        return fake_battery_level

    # Odczyt z INA219
    if ina219 is not None:
        try:
            bus_voltage = ina219.getBusVoltage_V()
            battery_current = ina219.getCurrent_mA()

            # Dodaj próbkę napięcia do listy (średnia krocząca z 5 próbek)
            battery_voltage_samples.append(bus_voltage)
            if len(battery_voltage_samples) > 5:
                battery_voltage_samples.pop(0)

            # Oblicz średnią z próbek
            avg_voltage = sum(battery_voltage_samples) / len(battery_voltage_samples)

            # Oblicz procent baterii na podstawie średniego napięcia (9V = 0%, 12.6V = 100%)
            p = (avg_voltage - 9) / 3.6 * 100
            if p > 100:
                p = 100
            if p < 0:
                p = 0

            return int(p)
        except Exception as e:
            print(f"[INA219] Error reading battery: {e}")
            battery_current = 0
            return 100

    # Fallback - zwróć 100%
    battery_current = 0
    return 100


def update_battery_estimate():
    """Aktualizuj szacowany czas pracy baterii na podstawie tempa rozładowywania"""
    global battery_last_level, battery_last_check_time, battery_estimated_minutes, battery_is_charging, battery_max_displayed_level

    current_time = time.time()
    current_level = get_battery_level()

    # Histereza ładowania - zapobiega migotaniu ikony
    if battery_is_charging:
        # Jeśli ładuje, wymagamy prądu poniżej progu dolnego aby wyłączyć
        if battery_current < battery_charge_hysteresis_low:
            battery_is_charging = False
    else:
        # Jeśli nie ładuje, wymagamy prądu powyżej progu górnego aby włączyć
        if battery_current > battery_charge_hysteresis_high:
            battery_is_charging = True

    # Oblicz precyzyjny procent z napięcia dla wyświetlania
    precise_percent = float(current_level)
    if ina219 is not None and fake_battery_level is None:
        try:
            # Użyj średniego napięcia
            if len(battery_voltage_samples) > 0:
                avg_voltage = sum(battery_voltage_samples) / len(battery_voltage_samples)
                precise_percent = ((avg_voltage - 9) / 3.6) * 100
                if precise_percent > 100:
                    precise_percent = 100
                if precise_percent < 0:
                    precise_percent = 0
        except:
            pass

    # Zarządzanie maksymalnym wyświetlanym poziomem
    if battery_is_charging:
        # Podczas ładowania pozwól na zwiększenie poziomu
        battery_max_displayed_level = max(battery_max_displayed_level, precise_percent)
    else:
        # Podczas rozładowywania - tylko zmniejszaj (nigdy nie zwiększaj)
        battery_max_displayed_level = min(battery_max_displayed_level, precise_percent)

    # Co 30 sekund aktualizuj szacowanie czasu
    if current_time - battery_last_check_time >= 30:
        if battery_last_check_time > 0:  # Pomijamy pierwszy pomiar
            time_diff_seconds = current_time - battery_last_check_time

            # Jeśli bateria nie ładuje i pobiera prąd - oblicz czas na podstawie rzeczywistego zużycia
            if not battery_is_charging and battery_current < 0:
                # Prąd rozładowania w mA (wartość ujemna, więc używamy abs)
                discharge_current_ma = abs(battery_current)

                if discharge_current_ma > 10:  # Minimalny próg 10mA aby uniknąć dzielenia przez ~0
                    # Ile mAh zostało w baterii
                    remaining_mah = (battery_max_displayed_level / 100.0) * BATTERY_CAPACITY_MAH

                    # Czas w godzinach = pojemność / prąd
                    remaining_hours = remaining_mah / discharge_current_ma
                    battery_estimated_minutes = int(remaining_hours * 60)

                    # Ogranicz maksymalny czas do 9999 minut
                    battery_estimated_minutes = min(9999, battery_estimated_minutes)
                else:
                    # Bardzo mały prąd - pokaż długi czas
                    battery_estimated_minutes = 9999
            else:
                # Ładowanie lub brak rozładowania - pokaż długi czas
                battery_estimated_minutes = 9999

        # Zaktualizuj wartości referencyjne
        battery_last_level = current_level
        battery_last_check_time = current_time


def draw_battery_icon():
    """Rysuj ikonę baterii z 4 segmentami w lewym górnym rogu (biała/zielona z piorunkiem gdy ładuje)"""
    # Użyj stanu z histerezy zamiast sprawdzać prąd bezpośrednio
    is_charging = battery_is_charging

    # Pozycja i rozmiar baterii - lewy górny róg - ZWIĘKSZONE ROZMIARY
    battery_width = 70  # Zwiększone z 60
    battery_height = 33  # Zwiększone z 28
    left_margin = 20
    top_margin = 20
    battery_x = left_margin
    battery_y = top_margin

    # Wybierz kolor w zależności od stanu ładowania (z histerezy)
    battery_color = GREEN if is_charging else WHITE

    # Czarne tło pod baterią (outline)
    outline_padding = 2
    pygame.draw.rect(screen, BLACK,
                     (battery_x - outline_padding, battery_y - outline_padding,
                      battery_width + outline_padding * 2, battery_height + outline_padding * 2),
                     border_radius=5)

    # Główna ramka baterii (ZIELONA gdy ładuje, BIAŁA gdy nie)
    pygame.draw.rect(screen, battery_color,
                     (battery_x, battery_y, battery_width, battery_height),
                     3, border_radius=5)

    # Końcówka baterii (PO LEWEJ - zwrócona w lewo)
    tip_width = 8  # Zwiększone z 6
    tip_height = 16  # Zwiększone z 12
    tip_x = battery_x - tip_width  # Po lewej stronie
    tip_y = battery_y + (battery_height - tip_height) // 2

    # Czarne tło pod końcówką
    pygame.draw.rect(screen, BLACK,
                     (tip_x - 1, tip_y - 1, tip_width + 2, tip_height + 2))

    # Końcówka w kolorze baterii
    pygame.draw.rect(screen, battery_color,
                     (tip_x, tip_y, tip_width, tip_height))

    # Ustawienia segmentów
    segment_width = 14  # Zwiększone z 10
    segment_height = battery_height - 10  # Margines 5px góra i dół
    segment_spacing = 4  # Zwiększone z 3
    segments_start_x = battery_x + 8  # Margines od lewej krawędzi
    segment_y = battery_y + 5  # Margines od góry

    # Pobierz poziom baterii i oblicz ile segmentów pokazać
    # NAPRAWIONE: Użyj battery_max_displayed_level zamiast surowego poziomu
    # aby uniknąć migotania segmentów przy wahaniach napięcia
    battery_level = battery_max_displayed_level
    if battery_level >= 75:
        segments_to_draw = 4
    elif battery_level >= 50:
        segments_to_draw = 3
    elif battery_level >= 25:
        segments_to_draw = 2
    else:
        segments_to_draw = 1

    # Ustaw clipping na wewnętrzną część baterii (żeby segmenty nie wychodziły poza ramkę)
    clip_margin = 3
    clip_rect = pygame.Rect(
        battery_x + clip_margin,
        battery_y + clip_margin,
        battery_width - clip_margin * 2,
        battery_height - clip_margin * 2
    )
    screen.set_clip(clip_rect)

    # Rysuj segmenty (od lewej do prawej) - ZIELONE gdy ładuje, BIAŁE gdy nie
    segment_color = GREEN if is_charging else WHITE

    for i in range(segments_to_draw):
        segment_x = segments_start_x + i * (segment_width + segment_spacing)

        # Czarne tło pod segmentem (outline)
        outline_rect = pygame.Rect(
            segment_x - 1,
            segment_y - 1,
            segment_width + 2,
            segment_height + 2
        )
        pygame.draw.rect(screen, BLACK, outline_rect)

        # Segment w odpowiednim kolorze (zielony gdy ładuje, biały gdy nie)
        segment_rect = pygame.Rect(
            segment_x,
            segment_y,
            segment_width,
            segment_height
        )
        pygame.draw.rect(screen, segment_color, segment_rect)

    # Wyłącz clipping
    screen.set_clip(None)

    # Rysuj piorunek gdy bateria się ładuje
    if is_charging:
        # Piorunek w środku baterii (klasyczny kształt)
        lightning_center_x = battery_x + battery_width // 2
        lightning_center_y = battery_y + battery_height // 2

        # Punkty pioruna - klasyczny kształt zigzag
        lightning_points = [
            (lightning_center_x - 2, lightning_center_y - 10),  # Lewy górny
            (lightning_center_x + 2, lightning_center_y - 10),  # Prawy górny
            (lightning_center_x + 5, lightning_center_y - 2),   # Prawy środek-góra
            (lightning_center_x + 2, lightning_center_y - 2),   # Wejście do środka
            (lightning_center_x + 6, lightning_center_y + 10),  # Prawy dolny
            (lightning_center_x + 2, lightning_center_y + 10),  # Środek dolny
            (lightning_center_x + 1, lightning_center_y + 2),   # Środek
            (lightning_center_x - 2, lightning_center_y + 2),   # Lewy środek
            (lightning_center_x - 6, lightning_center_y - 2),   # Lewy wystający
        ]

        # Czarne obramowanie pioruna (grubsze)
        for i in range(len(lightning_points)):
            p1 = lightning_points[i]
            p2 = lightning_points[(i + 1) % len(lightning_points)]
            pygame.draw.line(screen, BLACK, p1, p2, 4)

        # Żółty wypełniony piorun
        pygame.draw.polygon(screen, YELLOW, lightning_points)

    # Szacowany czas pracy baterii NA PRAWO od ikony baterii - FORMAT hh:mm lub --:-- gdy ładuje
    if is_charging:
        # Podczas ładowania pokaż --:--
        time_text = "--:--"
    else:
        # Podczas rozładowania pokaż rzeczywisty czas
        hours = battery_estimated_minutes // 60
        minutes = battery_estimated_minutes % 60

        # Ogranicz maksymalny czas do 99:59
        if hours > 99:
            hours = 99
            minutes = 59

        time_text = f"{hours:02d}:{minutes:02d}"

    # Użyj śledzonego maksymalnego poziomu (który tylko maleje podczas rozładowania)
    precise_percent = battery_max_displayed_level

    percent_text = f"{precise_percent:.1f}%"

    # NAPRAWIONE: Pozycja tekstów NA PRAWO od baterii w JEDNEJ LINII (poziomo)
    # Wyrównane do prawej krawędzi baterii
    battery_right_edge = battery_x + battery_width
    text_start_x = battery_right_edge + 20  # 20px odstępu od baterii
    text_y = battery_y + battery_height // 2 - 10  # Wyśrodkowane pionowo z baterią

    # Procent po lewej
    percent_x = text_start_x

    # Oblicz szerokość tekstu procentu
    percent_text_surface = font_large.render(percent_text, True, WHITE)
    percent_text_width = percent_text_surface.get_width()

    # Czas po prawej stronie procentu (w jednej linii, odstęp 20px)
    time_x = percent_x + percent_text_width + 20

    # Rysuj procent i czas w jednej linii
    draw_text_with_outline(percent_text, font_large, WHITE, BLACK, percent_x, text_y)
    draw_text_with_outline(time_text, font_large, WHITE, BLACK, time_x, text_y)


def draw_format_fps():
    """Rysuj informacje o formacie i FPS w prawym górnym rogu, pod REC/STBY"""
    right_margin = 20
    format_y = 120  # Poniżej REC/STBY

    # Pobierz aktualną rozdzielczość
    resolution = camera_settings.get("video_resolution", "1080p30")

    # Mapowanie rozdzielczości na czytelne nazwy formatów
    format_map = {
        "4K30": "4K",
        "1080p30": "FHD",
        "1080p50": "FHD",
        "720p30": "HD",
        "720p50": "HD"
    }

    # Pobierz nazwę formatu i FPS
    format_name = format_map.get(resolution, "FHD")
    res_config = RESOLUTION_MAP.get(resolution, {"fps": 30})
    fps_value = res_config["fps"]

    # Rysuj format w białym owalu z czarnym obramowaniem
    format_text_surface = font_large.render(format_name, True, BLACK)
    format_text_width = format_text_surface.get_width()
    format_text_height = format_text_surface.get_height()

    # Wymiary owalu (z paddingiem)
    oval_padding_x = 12
    oval_padding_y = 6
    oval_width = format_text_width + oval_padding_x * 2
    oval_height = format_text_height + oval_padding_y * 2

    # FPS po prawej stronie (obliczamy najpierw żeby znać całkowitą szerokość)
    fps_text = f"{fps_value}FPS"
    fps_text_surface = font_large.render(fps_text, True, WHITE)
    fps_text_width = fps_text_surface.get_width()

    # Wyrównaj do prawej krawędzi
    fps_x = SCREEN_WIDTH - right_margin - fps_text_width
    oval_x = fps_x - oval_width - 10  # 10px odstępu między owalem a FPS
    oval_y = format_y - oval_padding_y - 5

    # Rysuj biały owal (prostokąt z zaokrąglonymi rogami)
    pygame.draw.rect(screen, WHITE, (oval_x, oval_y, oval_width, oval_height), border_radius=int(oval_height // 2))

    # Rysuj czarne obramowanie owalu
    pygame.draw.rect(screen, BLACK, (oval_x, oval_y, oval_width, oval_height), 3, border_radius=int(oval_height // 2))

    # Rysuj czarny tekst formatu na białym tle (bez outline)
    format_text_x = oval_x + oval_padding_x + 5
    format_text_y = format_y
    draw_text(format_name, font_large, BLACK, format_text_x, format_text_y)

    # Rysuj FPS (z białym tekstem i czarnym outline)
    draw_text_with_outline(fps_text, font_large, WHITE, BLACK, fps_x, format_y)


def draw_zoom_bar():
    """Rysuj pasek zoom W/T - tylko gdy aktywny"""
    current_time = time.time()
    
    if current_time - last_zoom_change_time > ZOOM_BAR_TIMEOUT:
        return
    
    bar_width = 300
    bar_height = 30
    bar_x = SCREEN_WIDTH - 450
    bar_y = 20
    
    bg_surface = pygame.Surface((bar_width, bar_height), pygame.SRCALPHA)
    bg_surface.fill((0, 0, 0, 150))
    screen.blit(bg_surface, (bar_x, bar_y))
    
    pygame.draw.rect(screen, WHITE, (bar_x, bar_y, bar_width, bar_height), 2, border_radius=5)
    
    draw_text("W", font_small, WHITE, bar_x + 20, bar_y + bar_height // 2, center=True)
    draw_text("T", font_small, WHITE, bar_x + bar_width - 20, (bar_y + bar_height // 2) + 2, center=True)
    
    track_width = bar_width - 80
    track_x = bar_x + 40
    track_y = bar_y + bar_height // 2
    track_height = 4
    
    pygame.draw.rect(screen, DARK_GRAY, (track_x, track_y - track_height // 2, track_width, track_height), border_radius=2)
    
    zoom_level = camera_settings.get("zoom", 0.0)
    indicator_x = track_x + int(track_width * zoom_level)
    indicator_width = 8
    indicator_height = 20
    
    indicator_rect = pygame.Rect(
        indicator_x - indicator_width // 2,
        bar_y + (bar_height - indicator_height) // 2,
        indicator_width,
        indicator_height
    )
    pygame.draw.rect(screen, WHITE, indicator_rect, border_radius=3)


def draw_recording_indicator():
    """Rysuj wskaźnik nagrywania lub STBY w prawym górnym rogu, poniżej czasu nagrywania"""
    right_margin = 20
    rec_y = 75  # Poniżej czasu nagrywania

    if recording and recording_start_time:
        elapsed_time = time.time() - recording_start_time
        hours = int(elapsed_time // 3600)
        minutes = int((elapsed_time % 3600) // 60)
        seconds = int(elapsed_time % 60)

        # Timecode w formacie HH:MM:SS (bez klatek)
        timecode_text = f"TC {hours:02d}:{minutes:02d}:{seconds:02d}"

        # Oblicz szerokość napisu REC
        rec_text_surface = menu_font.render("REC", True, RED)
        rec_text_width = rec_text_surface.get_width()

        # Pozycja REC wyrównana do prawej
        rec_x = SCREEN_WIDTH - right_margin - rec_text_width

        # Migająca kropka
        if int(pygame.time.get_ticks() / 500) % 2:
            pygame.draw.circle(screen, RED, (rec_x - 15, rec_y + 12), 8)

        # Rysuj napis REC
        draw_text_with_outline("REC", menu_font, RED, BLACK, rec_x, rec_y)

        # Oblicz szerokość timecode
        tc_text_surface = menu_font.render(timecode_text, True, WHITE)
        tc_text_width = tc_text_surface.get_width()

        # TC na lewo od REC
        tc_x = rec_x - tc_text_width - 30  # 30px odstępu od REC

        draw_text_with_outline(timecode_text, menu_font, WHITE, BLACK, tc_x, rec_y)
    else:
        # STBY wyrównane do prawej
        stby_text_surface = menu_font.render("STBY", True, GREEN)
        stby_text_width = stby_text_surface.get_width()
        stby_x = SCREEN_WIDTH - right_margin - stby_text_width

        draw_text_with_outline("STBY", menu_font, GREEN, BLACK, stby_x, rec_y)


def draw_error_message():
    """Wyświetl komunikat błędu na środku ekranu"""
    global error_message, error_message_time

    if error_message is None:
        return

    # Sprawdź czy komunikat nie wygasł
    current_time = time.time()
    if current_time - error_message_time > ERROR_DISPLAY_DURATION:
        error_message = None
        return

    # Wymiary komunikatu
    padding = 30

    # Renderuj tekst aby poznać wymiary
    text_surface = font_large.render(error_message, True, WHITE)
    text_width = text_surface.get_width()
    text_height = text_surface.get_height()

    # Wymiary boksu
    box_width = text_width + padding * 2
    box_height = text_height + padding * 2

    # Pozycja na środku ekranu
    box_x = (SCREEN_WIDTH - box_width) // 2
    box_y = (SCREEN_HEIGHT - box_height) // 2

    # Rysuj półprzezroczyste tło (ciemne)
    overlay = pygame.Surface((box_width, box_height))
    overlay.set_alpha(220)
    overlay.fill((40, 40, 40))
    screen.blit(overlay, (box_x, box_y))

    # Rysuj czerwoną ramkę
    pygame.draw.rect(screen, RED, (box_x, box_y, box_width, box_height), 4, border_radius=10)

    # Rysuj tekst na środku
    text_x = box_x + box_width // 2 - text_width // 2
    text_y = box_y + box_height // 2 - text_height // 2
    screen.blit(text_surface, (text_x, text_y))


def draw_sd_indicator():
    """Rysuj spixelizowaną ikonę karty SD poniżej REC/STBY"""
    # Ukryj ikonę SD podczas nagrywania
    if recording:
        return

    if sd_icon is None:
        return

    right_margin = 10
    rec_y = 75  # Pozycja REC/STBY
    sd_y = rec_y + 30  # 30px poniżej REC/STBY

    # NAJPIERW spixelizuj oryginalną ikonę
    pixelized_icon = pixelize_image(sd_icon, pixel_size=4)

    # POTEM przeskaluj spixelizowaną ikonę do żądanego rozmiaru
    scaled_size = 90
    final_icon = pygame.transform.scale(sd_icon, (scaled_size + 20, scaled_size))

    # Wyrównaj do prawej krawędzi
    sd_width = final_icon.get_width()
    sd_x = SCREEN_WIDTH - right_margin - sd_width

    # Rysuj ikonę
    screen.blit(final_icon, (sd_x, sd_y))


def draw_menu_button():
    """Rysuj przycisk P-MENU w lewym dolnym rogu"""
    button_width = 220
    button_height = 55
    button_x = 20
    button_y = SCREEN_HEIGHT - button_height - 20

    # Rysuj białe tło przycisku
    pygame.draw.rect(screen, WHITE, (button_x, button_y, button_width, button_height), border_radius=10)

    # Rysuj czarną obramówkę
    pygame.draw.rect(screen, BLACK, (button_x, button_y, button_width, button_height), 3, border_radius=10)

    # Rysuj tekst na przycisku (czarny tekst na białym tle)
    draw_text("P-MENU", font_large, BLACK, button_x + button_width // 2, button_y + button_height // 2, center=True)


def generate_thumbnail(video_path, max_retries=3):
    """Generuj miniaturkę"""
    thumbnail_path = THUMBNAIL_DIR / f"{video_path.stem}.jpg"
    
    for attempt in range(max_retries):
        try:
            print(f"[THUMB] Miniatura: {video_path.name} (próba {attempt + 1}/{max_retries})")
            
            if not video_path.exists():
                print(f"[WARN] Plik nie istnieje")
                time.sleep(1)
                continue
            
            file_size = video_path.stat().st_size
            if file_size < 10000:
                print(f"[WARN] Plik za mały: {file_size} B")
                time.sleep(1)
                continue
            
            cap = cv2.VideoCapture(str(video_path))
            
            if not cap.isOpened():
                print(f"[WARN] Nie można otworzyć")
                cap.release()
                time.sleep(1)
                continue
            
            ret, frame = cap.read()
            cap.release()
            
            if not ret or frame is None:
                print(f"[WARN] Nie można pobrać klatki")
                time.sleep(1)
                continue
            
            if frame.shape[0] < 10 or frame.shape[1] < 10:
                print(f"[WARN] Klatka zbyt mała")
                time.sleep(1)
                continue
            
            frame_resized = cv2.resize(frame, (320, 180))
            success = cv2.imwrite(str(thumbnail_path), frame_resized)
            
            if not success:
                print(f"[WARN] Nie można zapisać")
                time.sleep(1)
                continue
            
            if thumbnail_path.exists() and thumbnail_path.stat().st_size > 1000:
                print(f"[OK] Miniatura OK")
                return True
            else:
                print(f"[WARN] Miniatura nieprawidłowa")
                if thumbnail_path.exists():
                    thumbnail_path.unlink()
                time.sleep(1)
                continue
                
        except Exception as e:
            print(f"[WARN] Błąd (próba {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
            continue
    
    print(f"[ERROR] Nie udało się po {max_retries} próbach")
    return False


def refresh_videos():
    """Odśwież listę filmów"""
    global videos, selected_index, thumbnails, selected_videos, multi_select_mode

    if not VIDEO_DIR:
        videos = []
        thumbnails = {}
        selected_videos.clear()
        multi_select_mode = False
        print("[WARN] VIDEO_DIR niedostępny")
        return

    old_selected = videos[selected_index] if videos and 0 <= selected_index < len(videos) else None

    videos = sorted(VIDEO_DIR.glob("*.mp4"), reverse=True)

    if old_selected and old_selected in videos:
        selected_index = videos.index(old_selected)
    else:
        selected_index = min(selected_index, max(0, len(videos) - 1))

    # Wyczyść zaznaczone filmy i wyłącz tryb multi-select przy odświeżeniu (po usunięciu)
    selected_videos.clear()
    multi_select_mode = False

    print("[THUMB] Ładowanie miniatur...")
    thumbnails = {}
    missing_thumbnails = []

    for video in videos:
        thumbnail_path = THUMBNAIL_DIR / f"{video.stem}.jpg"
        if thumbnail_path.exists():
            try:
                img = cv2.imread(str(thumbnail_path))
                if img is not None:
                    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                    surface = pygame.surfarray.make_surface(np.transpose(img_rgb, (1, 0, 2)))
                    thumbnails[video.stem] = surface
            except Exception as e:
                print(f"[WARN] Błąd {video.stem}: {e}")
        else:
            # Brak miniaturki - dodaj do listy do wygenerowania
            missing_thumbnails.append(video)

    print(f"[OK] {len(thumbnails)} miniatur załadowanych")

    # Generuj brakujące miniaturki w tle
    if missing_thumbnails:
        print(f"[THUMB] Brak {len(missing_thumbnails)} miniaturek - generowanie...")

        def generate_missing_thumbnails():
            for video in missing_thumbnails:
                try:
                    print(f"[THUMB] Generowanie: {video.name}")
                    if generate_thumbnail(video):
                        # Po wygenerowaniu, załaduj miniaturkę do pamięci
                        thumbnail_path = THUMBNAIL_DIR / f"{video.stem}.jpg"
                        if thumbnail_path.exists():
                            img = cv2.imread(str(thumbnail_path))
                            if img is not None:
                                img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                                surface = pygame.surfarray.make_surface(np.transpose(img_rgb, (1, 0, 2)))
                                thumbnails[video.stem] = surface
                                print(f"[THUMB] OK: {video.stem}")
                except Exception as e:
                    print(f"[THUMB] Błąd generowania {video.stem}: {e}")

        # Uruchom w osobnym wątku aby nie blokować UI
        thumb_thread = threading.Thread(target=generate_missing_thumbnails, daemon=True)
        thumb_thread.start()


def draw_text(text, font, color, x, y, center=False, bg_color=None, padding=10):
    """Rysuj tekst z offsetami zależnymi od czcionki"""
    if not text or not font:
        return
    try:
        text_surface = font.render(str(text), True, color)

        # Pobierz offsety dla aktualnej czcionki
        font_family = camera_settings.get("font_family", "HomeVideo")
        font_config = FONT_DEFINITIONS.get(font_family, FONT_DEFINITIONS["HomeVideo"])
        general_offset = font_config.get("general_offset", 0)
        polish_offset = font_config.get("polish_offset", 0)

        # Sprawdź czy tekst zawiera polskie znaki diakrytyczne
        polish_chars = 'śćźżóńŚĆŹŻÓŃ'
        has_polish = any(char in str(text) for char in polish_chars)

        # Oblicz całkowity offset: ogólny offset + offset dla polskich znaków (jeśli są)
        y_offset = general_offset + (polish_offset if has_polish else 0)

        if center:
            text_rect = text_surface.get_rect(center=(x, y + y_offset))
        else:
            text_rect = text_surface.get_rect(topleft=(x, y + y_offset))

        if bg_color:
            bg_rect = text_rect.inflate(padding * 2, padding * 2)
            pygame.draw.rect(screen, bg_color, bg_rect, border_radius=5)
        screen.blit(text_surface, text_rect)
    except:
        pass


def draw_text_with_outline(text, font, color, outline_color, x, y, center=False):
    """Rysuj tekst z obrysem i offsetami zależnymi od czcionki"""
    if not text or not font:
        return
    try:
        outline_width = 2

        # Pobierz offsety dla aktualnej czcionki
        font_family = camera_settings.get("font_family", "HomeVideo")
        font_config = FONT_DEFINITIONS.get(font_family, FONT_DEFINITIONS["HomeVideo"])
        general_offset = font_config.get("general_offset", 0)
        polish_offset = font_config.get("polish_offset", 0)

        # Sprawdź czy tekst zawiera polskie znaki diakrytyczne
        polish_chars = 'śćźżóńŚĆŹŻÓŃ'
        has_polish = any(char in str(text) for char in polish_chars)

        # Oblicz całkowity offset: ogólny offset + offset dla polskich znaków (jeśli są)
        y_offset = general_offset + (polish_offset if has_polish else 0)

        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if dx == 0 and dy == 0:
                    continue
                outline_surface = font.render(str(text), True, outline_color)
                if center:
                    outline_rect = outline_surface.get_rect(center=(x + dx, y + y_offset + dy))
                else:
                    outline_rect = outline_surface.get_rect(topleft=(x + dx, y + y_offset + dy))
                screen.blit(outline_surface, outline_rect)

        text_surface = font.render(str(text), True, color)
        if center:
            text_rect = text_surface.get_rect(center=(x, y + y_offset))
        else:
            text_rect = text_surface.get_rect(topleft=(x, y + y_offset))
        screen.blit(text_surface, text_rect)
    except:
        pass


def get_display_date():
    """Pobierz datę do wyświetlenia"""
    if camera_settings.get("manual_date"):
        return format_manual_date(camera_settings.get("manual_date"))
    else:
        now = datetime.now()
        date_format = camera_settings.get("date_format", "DD/MM/YYYY")
        month_text = camera_settings.get("date_month_text", False)
        separator = camera_settings.get("date_separator", "/")
        show_time = camera_settings.get("show_time", False)

        # Skróty miesięcy
        month_names = ["STY", "LUT", "MAR", "KWI", "MAJ", "CZE",
                      "LIP", "SIE", "WRZ", "PAŹ", "LIS", "GRU"]

        # Pobierz komponenty daty
        day = now.strftime("%d")
        month = month_names[now.month - 1] if month_text else now.strftime("%m")
        year = now.strftime("%Y")
        time_str = now.strftime("%H:%M:%S") if show_time else ""

        # Formatuj datę według wybranego formatu z wybranym separatorem
        if date_format == "DD/MM/YYYY":
            date_str = f"{day}{separator}{month}{separator}{year}"
        elif date_format == "MM/DD/YYYY":
            date_str = f"{month}{separator}{day}{separator}{year}"
        elif date_format == "YYYY/MM/DD":
            date_str = f"{year}{separator}{month}{separator}{day}"
        else:
            date_str = f"{day}{separator}{month}{separator}{year}"

        # Dodaj czas jeśli włączony
        if show_time:
            return f"{date_str} {time_str}"
        else:
            return date_str


def draw_date_overlay():
    """Rysuj overlay daty na podglądzie - pozycja zależy od stanu nagrywania"""
    if not camera_settings.get("show_date", False):
        return

    date_text = get_display_date()

    # Mapowanie nazw kolorów na wartości RGB
    color_map = {
        "yellow": YELLOW,
        "white": WHITE,
        "red": RED,
        "green": GREEN,
        "blue": BLUE,
        "orange": ORANGE
    }

    # Pobierz kolor z ustawień
    color_name = camera_settings.get("date_color", "yellow")
    date_color = color_map.get(color_name, YELLOW)

    # NA PODGLĄDZIE ZAWSZE UŻYWAMY EXTRA_LARGE (niezależnie od ustawienia)
    date_font = font_large

    # POZYCJA zależy od stanu nagrywania
    if recording:
        # PODCZAS NAGRYWANIA: Lewy dolny róg (tam gdzie był wcześniej przycisk P-MENU)
        x = 20
        y = SCREEN_HEIGHT - 65
    else:
        # BEZ NAGRYWANIA: Po prawej od przycisku P-MENU w lewym dolnym rogu
        # Przycisk P-MENU: x=20, y=SCREEN_HEIGHT-75, width=220, height=55
        pmenu_x = 20
        pmenu_width = 220
        pmenu_right_edge = pmenu_x + pmenu_width

        spacing = 60  # Odstęp od przycisku P-MENU
        x = pmenu_right_edge + spacing
        y = SCREEN_HEIGHT - 65  # Ta sama wysokość co przycisk P-MENU (środek przycisku)

    draw_text_with_outline(date_text, date_font, date_color, BLACK, x, y)


def format_time(seconds):
    """Formatuj czas"""
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"


def videos_navigate_up():
    """Nawigacja w górę - w układzie siatki"""
    global selected_index
    if videos:
        cols = 3
        selected_index = max(0, selected_index - cols)


def videos_navigate_down():
    """Nawigacja w dół - w układzie siatki"""
    global selected_index
    if videos:
        cols = 3
        selected_index = min(len(videos) - 1, selected_index + cols)


def videos_navigate_left():
    """Nawigacja w lewo - w układzie siatki z przechodzeniem między wierszami"""
    global selected_index
    if videos:
        cols = 3
        current_col = selected_index % cols

        if current_col == 0:
            # Jesteśmy w pierwszej kolumnie - przejdź do ostatniej kolumny poprzedniego wiersza
            if selected_index > 0:
                # Sprawdź ile kolumn ma poprzedni wiersz
                prev_row_start = selected_index - cols
                if prev_row_start >= 0:
                    # Znajdź ostatni element poprzedniego wiersza
                    prev_row_last = selected_index - 1
                    selected_index = prev_row_last
        else:
            # Normalnie przesuń o 1 w lewo
            selected_index = max(0, selected_index - 1)


def videos_navigate_right():
    """Nawigacja w prawo - w układzie siatki z przechodzeniem między wierszami"""
    global selected_index
    if videos:
        cols = 3
        current_col = selected_index % cols
        current_row = selected_index // cols
        total_rows = (len(videos) + cols - 1) // cols

        # Sprawdź ile elementów ma aktualny wiersz
        row_start = current_row * cols
        row_end = min(row_start + cols, len(videos))
        row_size = row_end - row_start

        if current_col == row_size - 1:
            # Jesteśmy w ostatniej kolumnie aktualnego wiersza - przejdź do pierwszej kolumny następnego wiersza
            if current_row < total_rows - 1:
                # Przejdź do pierwszego elementu następnego wiersza
                next_row_start = (current_row + 1) * cols
                if next_row_start < len(videos):
                    selected_index = next_row_start
        else:
            # Normalnie przesuń o 1 w prawo
            selected_index = min(len(videos) - 1, selected_index + 1)


# ============================================================================
# INICJALIZACJA
# ============================================================================

def load_fonts():
    """Załaduj wszystkie czcionki na podstawie wybranej font_family"""
    global font_large, font_medium, font_small, font_tiny, menu_font, font_mediumXL, font_70

    font_family = camera_settings.get("font_family", "HomeVideo")

    # Sprawdź czy czcionka istnieje w definicjach
    if font_family not in FONT_DEFINITIONS:
        font_family = "HomeVideo"  # Fallback do domyślnej

    font_config = FONT_DEFINITIONS[font_family]
    font_path = font_config["path"]
    font_scale = font_config["scale"]

    try:
        # Załaduj czcionkę niestandardową
        font_large = pygame.font.Font(font_path, int(60 * font_scale))
        font_medium = pygame.font.Font(font_path, int(40 * font_scale))
        font_small = pygame.font.Font(font_path, int(30 * font_scale))
        font_tiny = pygame.font.Font(font_path, int(24 * font_scale))
        menu_font = pygame.font.Font(font_path, int(65 * font_scale))
        font_mediumXL = pygame.font.Font(font_path, int(55 * font_scale))  # Nowa czcionka dla formatu
        font_70 = pygame.font.Font(font_path, int(70 * font_scale))  # Czcionka dla 48K w mic indicator
        print(f"[OK] Czcionka załadowana: {font_family}")
    except Exception as e:
        # Jeśli nie udało się załadować, użyj domyślnej czcionki systemowej
        print(f"[WARN] Nie można załadować czcionki {font_family}: {e}")
        print("[INFO] Używam domyślnej czcionki systemowej")
        font_large = pygame.font.Font(None, 60)
        font_medium = pygame.font.Font(None, 40)
        font_small = pygame.font.Font(None, 30)
        font_tiny = pygame.font.Font(None, 24)
        menu_font = pygame.font.Font(None, 65)
        font_mediumXL = pygame.font.Font(None, 55)
        font_70 = pygame.font.Font(None, 70)


def pixelize_image(image, pixel_size=4):
    """Spixelizuj obrazek poprzez skalowanie w dół i w górę"""
    if image is None:
        return None

    # Pobierz aktualne wymiary
    width, height = image.get_size()

    # Oblicz nowe wymiary (podziel przez pixel_size)
    small_width = max(1, width // pixel_size)
    small_height = max(1, height // pixel_size)

    # Skaluj w dół (zmniejsz)
    small_image = pygame.transform.scale(image, (small_width, small_height))

    # Skaluj z powrotem do oryginalnego rozmiaru (powiększ) - efekt pikseli
    pixelized = pygame.transform.scale(small_image, (width, height))

    return pixelized


def load_images():
    """Załaduj obrazki interfejsu"""
    global playback_icon, steadyhand_icon, sd_icon, brightness_icon, film_icon, pause_icon

    try:
        # Załaduj ikonę playback
        playback_path = Path(__file__).parent /"icons"/ "playback.png"
        if playback_path.exists():
            playback_icon = pygame.image.load(str(playback_path))
            print("[OK] Ikona playback załadowana")
        else:
            print(f"[WARN] Nie znaleziono pliku: {playback_path}")
            playback_icon = None

        # Załaduj ikonę steadyhand
        steadyhand_path = Path(__file__).parent /"icons"/ "steadyhand.png"
        if steadyhand_path.exists():
            steadyhand_icon = pygame.image.load(str(steadyhand_path))
            print("[OK] Ikona steadyhand załadowana")
        else:
            print(f"[WARN] Nie znaleziono pliku: {steadyhand_path}")
            steadyhand_icon = None

        # Załaduj ikonę SD
        sd_path = Path(__file__).parent /"icons"/ "sd.png"
        if sd_path.exists():
            sd_icon = pygame.image.load(str(sd_path))
            print("[OK] Ikona SD załadowana")
        else:
            print(f"[WARN] Nie znaleziono pliku: {sd_path}")
            sd_icon = None

        # Załaduj ikonę brightness
        brightness_path = Path(__file__).parent /"icons"/ "bright.png"
        if brightness_path.exists():
            brightness_icon = pygame.image.load(str(brightness_path))
            print("[OK] Ikona brightness załadowana")
        else:
            print(f"[WARN] Nie znaleziono pliku: {brightness_path}")
            brightness_icon = None

        # Załaduj ikonę filmu
        film_path = Path(__file__).parent /"icons"/ "film.png"
        if film_path.exists():
            film_icon = pygame.image.load(str(film_path))
            print("[OK] Ikona film załadowana")
        else:
            print(f"[WARN] Nie znaleziono pliku: {film_path}")
            film_icon = None

        # Załaduj ikonę pauzy
        pause_path = Path(__file__).parent /"icons"/ "pause.png"
        if pause_path.exists():
            pause_icon = pygame.image.load(str(pause_path))
            print("[OK] Ikona pause załadowana")
        else:
            print(f"[WARN] Nie znaleziono pliku: {pause_path}")
            pause_icon = None
    except Exception as e:
        print(f"[ERROR] Błąd wczytywania obrazków: {e}")
        playback_icon = None
        steadyhand_icon = None
        sd_icon = None
        brightness_icon = None
        pause_icon = None


# ============================================================================
# OBSŁUGA MATRYCY PRZYCISKÓW 4x4
# ============================================================================

def init_matrix():
    """Inicjalizuj matrycę przycisków 4x4"""
    global matrix_cols, matrix_rows

    print("[MATRIX] Inicjalizacja matrycy 4x4...")

    # Ustaw tryb BCM (numeracja GPIO)
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    # Konfiguruj kolumny jako wyjścia (output)
    for col_pin in COL_PINS:
        GPIO.setup(col_pin, GPIO.OUT)
        GPIO.output(col_pin, GPIO.HIGH)  # Ustaw na HIGH (nieaktywne)

    # Konfiguruj rzędy jako wejścia z pull-up
    for row_pin in ROW_PINS:
        GPIO.setup(row_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    # Konfiguruj piny IR CUT (mostek H)
    GPIO.setup(IR_CUT_A, GPIO.OUT)
    GPIO.setup(IR_CUT_B, GPIO.OUT)
    # Stan spoczynkowy - oba LOW
    GPIO.output(IR_CUT_A, GPIO.LOW)
    GPIO.output(IR_CUT_B, GPIO.LOW)

    # Konfiguruj pin latarki IR
    GPIO.setup(IR_LED, GPIO.OUT)
    GPIO.output(IR_LED, GPIO.LOW)  # LOW wyłącza latarkę IR (domyślnie wyłączona)

    # Przywróć ostatni zapisany stan filtra IR
    restore_ir_filter_state()

    print("[OK] Matryca 4x4 OK")
    print("[OK] IR Cut Filter OK")
    print("[OK] IR LED OK")


def scan_matrix():
    """Skanuj matrycę i zwróć naciśnięte przyciski"""
    pressed_buttons = []
    current_time = time.time()

    # Przeskanuj każdą kolumnę
    for col_idx, col_pin in enumerate(COL_PINS):
        # Aktywuj kolumnę (LOW)
        GPIO.output(col_pin, GPIO.LOW)

        # Daj czas na ustabilizowanie się sygnału
        time.sleep(0.001)

        # Sprawdź wszystkie rzędy
        for row_idx, row_pin in enumerate(ROW_PINS):
            if GPIO.input(row_pin) == GPIO.LOW:  # Przycisk naciśnięty
                button_key = (row_idx, col_idx)

                # Debounce - sprawdź czy minęło 300ms od ostatniego naciśnięcia
                if button_key not in last_button_press or \
                   current_time - last_button_press[button_key] > 0.3:

                    if button_key in BUTTON_MAP:
                        button_name = BUTTON_MAP[button_key]
                        pressed_buttons.append(button_name)
                        last_button_press[button_key] = current_time

        # Dezaktywuj kolumnę (HIGH)
        GPIO.output(col_pin, GPIO.HIGH)

    return pressed_buttons


def check_matrix_buttons():
    """Sprawdź matrycę i wywołaj odpowiednie handlery"""
    pressed = scan_matrix()

    for button_name in pressed:
        if button_name in button_handlers:
            handler = button_handlers[button_name]
            if handler:
                print(f"[MATRIX] Przycisk: {button_name}")
                handler()


def is_button_pressed(button_name):
    """Sprawdź czy dany przycisk jest obecnie naciśnięty (dla continuous input)"""
    for col_idx, col_pin in enumerate(COL_PINS):
        GPIO.output(col_pin, GPIO.LOW)
        time.sleep(0.001)

        for row_idx, row_pin in enumerate(ROW_PINS):
            button_key = (row_idx, col_idx)
            if button_key in BUTTON_MAP and BUTTON_MAP[button_key] == button_name:
                if GPIO.input(row_pin) == GPIO.LOW:
                    GPIO.output(col_pin, GPIO.HIGH)
                    return True

        GPIO.output(col_pin, GPIO.HIGH)

    return False


def init_pygame():
    """Inicjalizuj pygame"""
    global screen, SCREEN_WIDTH, SCREEN_HEIGHT

    print("[INIT] Pygame init...")
    pygame.init()

    # NAPRAWIONE: Inicjalizuj pygame.mixer dla odtwarzania dźwięku
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
        print("[MIXER] Pygame mixer zainicjalizowany")
    except Exception as e:
        print(f"[WARN] Nie można zainicjalizować pygame.mixer: {e}")

    info = pygame.display.Info()
    SCREEN_WIDTH = info.current_w
    SCREEN_HEIGHT = info.current_h

    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.FULLSCREEN)
    pygame.display.set_caption("Kamera System")
    pygame.mouse.set_visible(False)

    # Wczytaj konfigurację PRZED załadowaniem czcionek
    load_config()

    # Załaduj czcionki (korzysta z camera_settings["font_family"])
    load_fonts()

    # Załaduj obrazki interfejsu
    load_images()

    screen.fill(BLACK)
    pygame.display.flip()

    print("[OK] Pygame OK")


def init_camera():
    """Inicjalizuj kamerę"""
    global camera
    print("[INIT] Kamera init...")

    resolution = camera_settings.get("video_resolution", "1080p30")
    res_config = RESOLUTION_MAP[resolution]

    camera = Picamera2()
    config = camera.create_video_configuration(
        main={"size": res_config["size"], "format": "RGB888"},
        controls={"FrameRate": res_config["fps"]}
    )
    camera.configure(config)
    camera.start()

    # Konfiguracja została już wczytana w init_pygame()
    apply_camera_settings()

    print(f"[OK] Kamera OK: {resolution}")


# ============================================================================
# NAGRYWANIE
# ============================================================================

def start_recording():
    """Start nagrywania - FPS w nazwie pliku"""
    global recording, current_file, encoder, recording_start_time, current_recording_fps

    if not recording:
        if not VIDEO_DIR:
            print("[ERROR] VIDEO_DIR niedostępny - nie można nagrywać")
            return

        current_recording_fps = get_current_fps()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        current_file = VIDEO_DIR / f"video_{timestamp}_{current_recording_fps}fps.mp4"

        print(f"[REC] START: {current_file.name}")
        print(f"[VIDEO] FPS: {current_recording_fps}")

        try:
            resolution = camera_settings.get("video_resolution", "1080p30")
            bitrate = BITRATE_MAP.get(resolution, 10000000)

            encoder = H264Encoder(bitrate=bitrate, framerate=current_recording_fps)
            output = FfmpegOutput(str(current_file))
            camera.start_encoder(encoder, output)
            recording = True
            recording_start_time = time.time()

            # Rozpocznij nagrywanie audio
            start_audio_recording(current_file)

            print(f"[OK] Nagrywanie @ {current_recording_fps} FPS")
        except Exception as e:
            print(f"[ERROR] Błąd start: {e}")
            recording = False
            current_file = None
            current_recording_fps = None
            recording_start_time = None


def stop_recording():
    """Stop nagrywania"""
    global recording, current_file, encoder, recording_start_time, current_recording_fps

    if recording:
        print("[STOP] STOP...")
        recording = False
        saved_file = current_file
        saved_fps = current_recording_fps
        saved_audio_file = audio_file

        try:
            # Zatrzymaj nagrywanie audio
            stop_audio_recording()

            camera.stop_encoder()
            print("[OK] Encoder zatrzymany")

            # Przetwarzanie wideo w wątku w tle (nie blokuj głównego wątku)
            def process_video():
                processing_marker = None
                try:
                    # Czekaj aż plik będzie gotowy
                    time.sleep(1.5)

                    if saved_file and saved_file.exists():
                        # Utwórz znacznik przetwarzania
                        processing_marker = saved_file.with_suffix('.processing')
                        processing_marker.touch()
                        print(f"[PROCESSING] Utworzono znacznik: {processing_marker.name}")
                        size = saved_file.stat().st_size / (1024*1024)

                        if size < 0.1:
                            print(f"[WARN] Plik zbyt mały ({size:.1f} MB)")
                        else:
                            print(f"[OK] Zapisano: {size:.1f} MB @ {saved_fps} FPS")

                            verify_cap = cv2.VideoCapture(str(saved_file))
                            recorded_fps = verify_cap.get(cv2.CAP_PROP_FPS)
                            verify_cap.release()
                            print(f"[FPS] OpenCV wykrył FPS: {recorded_fps:.2f}")

                            print("[THUMB] Generowanie miniatury...")
                            generate_thumbnail(saved_file)

                            # Połącz audio i video
                            if saved_audio_file and saved_audio_file.exists():
                                print("[MERGE] Łączenie audio z video...")
                                merge_success = merge_audio_video(saved_file, saved_audio_file)
                                if not merge_success:
                                    print("[ERROR] Nie udało się połączyć audio z video!")
                                    # Usuń plik audio, jeśli merge się nie udał
                                    if saved_audio_file.exists():
                                        saved_audio_file.unlink()
                                        print("[CLEANUP] Usunięto nieudany plik audio")

                            # Dodaj datę jeśli włączona (tylko jeśli plik wideo nadal istnieje)
                            if saved_file.exists() and camera_settings.get("show_date", False):
                                print("[DATE] Dodawanie daty...")
                                date_success = add_date_overlay_to_video(saved_file)
                                if not date_success:
                                    print("[ERROR] Nie udało się dodać daty do video!")

                            print("[OK] Przetwarzanie zakończone")

                            # Usuń znacznik przetwarzania
                            if processing_marker and processing_marker.exists():
                                processing_marker.unlink()
                                print(f"[PROCESSING] Usunięto znacznik: {processing_marker.name}")
                    else:
                        print(f"[ERROR] Plik nie istnieje")
                except Exception as e:
                    print(f"[ERROR] Błąd przetwarzania wideo: {e}")
                    import traceback
                    traceback.print_exc()
                finally:
                    # Upewnij się, że znacznik zostanie usunięty nawet w przypadku błędu
                    if processing_marker and processing_marker.exists():
                        try:
                            processing_marker.unlink()
                            print(f"[PROCESSING] Usunięto znacznik (cleanup): {processing_marker.name}")
                        except:
                            pass

            thread = threading.Thread(target=process_video, daemon=True)
            thread.start()

        except Exception as e:
            print(f"[ERROR] Błąd: {e}")
            import traceback
            traceback.print_exc()

        finally:
            encoder = None
            current_file = None
            current_recording_fps = None
            recording_start_time = None


# ============================================================================
# ODTWARZANIE
# ============================================================================

def start_video_playback(video_path):
    """Rozpocznij odtwarzanie - FPS z nazwy pliku"""
    global video_capture, video_current_frame, video_total_frames, video_fps
    global video_path_playing, video_paused, current_state, video_last_frame_time, video_last_surface
    global video_audio_ready, playback_loading_start_time, last_ui_interaction_time  # NOWY: Flaga gotowości audio

    # Sprawdź czy film jest w trakcie przetwarzania
    processing_marker = video_path.with_suffix('.processing')
    if processing_marker.exists():
        print(f"[PLAY] Film jest w trakcie przetwarzania - czekaj...")
        show_error_message("Film jest przetwarzany - czekaj...")
        return False

    print(f"\n[PLAY] ODTWARZANIE: {video_path.name}")

    # Resetuj flagę audio - ZAPAUZUJ video dopóki audio się nie załaduje
    video_audio_ready = False
    video_paused = True
    playback_loading_start_time = time.time()
    # Inicjalizuj czas interakcji (pokaż UI na początku)
    last_ui_interaction_time = time.time()

    video_capture = cv2.VideoCapture(str(video_path))
    if not video_capture.isOpened():
        print("[ERROR] Nie można otworzyć")
        return False

    # Najpierw spróbuj wyciągnąć FPS z nazwy pliku (najniezawodniejsze)
    original_fps = extract_fps_from_filename(video_path.name)

    # Jeśli nie ma w nazwie, użyj ffprobe (dokładniejsze niż OpenCV)
    if not original_fps:
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=r_frame_rate", "-of", "default=noprint_wrappers=1:nokey=1",
                 str(video_path)],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                # ffprobe zwraca FPS jako ułamek (np. "30/1" lub "50/1")
                fps_str = result.stdout.strip()
                if '/' in fps_str:
                    num, denom = fps_str.split('/')
                    original_fps = float(num) / float(denom)
                else:
                    original_fps = float(fps_str)
                print(f"[FPS] ffprobe FPS: {original_fps}")
        except Exception as e:
            print(f"[WARN] Błąd ffprobe: {e}")

    # Jeśli ffprobe też zawiodło, użyj OpenCV jako ostateczność
    if not original_fps or original_fps <= 0:
        original_fps = video_capture.get(cv2.CAP_PROP_FPS)
        print(f"[FPS] OpenCV FPS (fallback): {original_fps}")

    # Walidacja FPS
    if original_fps <= 0 or original_fps > 60:
        original_fps = 30
        print(f"[WARN] FPS nieprawidłowy, użyto 30")

    # NAPRAWIONE: Oblicz prawdziwy FPS z długości wideo i liczby klatek
    # Niektóre filmy mają nieprawidłowe metadane FPS, więc sprawdzamy rzeczywisty FPS
    video_total_frames_temp = int(video_capture.get(cv2.CAP_PROP_FRAME_COUNT))

    # Pobierz rzeczywisty czas trwania wideo z ffprobe
    calculated_fps = None
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            duration_seconds = float(result.stdout.strip())
            if duration_seconds > 0 and video_total_frames_temp > 0:
                calculated_fps = video_total_frames_temp / duration_seconds
                print(f"[FPS] Obliczony FPS (klatki/czas): {calculated_fps:.2f}")
    except Exception as e:
        print(f"[WARN] Nie można obliczyć FPS z czasu trwania: {e}")

    # Diagnostyka - pokaż wszystkie źródła FPS
    print(f"[FPS] Metadane FPS: {original_fps:.2f}")
    if calculated_fps:
        print(f"[FPS] Rzeczywisty FPS: {calculated_fps:.2f}")

        # Jeśli jest duża rozbieżność (>5 FPS), użyj obliczonego FPS
        fps_diff = abs(original_fps - calculated_fps)
        if fps_diff > 5:
            print(f"[FPS] ROZBIEŻNOŚĆ {fps_diff:.1f} FPS! Używam obliczonego FPS")
            video_fps = calculated_fps
        else:
            # Metadane są OK, użyj ich
            video_fps = original_fps
    else:
        # Nie udało się obliczyć, użyj metadanych
        video_fps = original_fps

    print(f"[OK] UŻYWAM FPS: {video_fps:.2f}")

    video_total_frames = int(video_capture.get(cv2.CAP_PROP_FRAME_COUNT))
    video_current_frame = 0
      # NAPRAWIONE: Zapauzuj od razu - odpauzuj dopiero gdy audio będzie gotowe
    video_path_playing = video_path
    video_last_frame_time = time.time()
    video_last_surface = None

    # NAPRAWIONE: Odczytaj pierwszą klatkę aby pokazać ją od razu (zamiast czarnego ekranu)
    try:
        ret, first_frame = video_capture.read()
        if ret and first_frame is not None:
            frame_rgb = cv2.cvtColor(first_frame, cv2.COLOR_BGR2RGB)
            video_h, video_w = first_frame.shape[:2]
            aspect = video_w / video_h
            screen_aspect = SCREEN_WIDTH / SCREEN_HEIGHT

            if aspect > screen_aspect:
                new_w = SCREEN_WIDTH
                new_h = int(SCREEN_WIDTH / aspect)
            else:
                new_h = SCREEN_HEIGHT
                new_w = int(SCREEN_HEIGHT * aspect)

            frame_resized = cv2.resize(frame_rgb, (new_w, new_h))
            frame_surface = pygame.surfarray.make_surface(np.transpose(frame_resized, (1, 0, 2)))
            video_last_surface = (frame_surface, new_w, new_h)
            video_current_frame = 1  # Pierwsza ramka już odczytana
            print("[VIDEO] Pierwsza ramka załadowana")
    except Exception as e:
        print(f"[WARN] Nie można odczytać pierwszej ramki: {e}")

    # NAPRAWIONE: Ekstraktuj audio w wątku w tle aby nie blokować GUI
    def extract_and_play_audio():
        global video_audio_ready, video_paused, video_last_frame_time, video_current_frame
        try:
            # Ścieżka do tymczasowego pliku audio (lokalny dysk, nie karta SD)
            temp_audio_path = THUMBNAIL_DIR / f"temp_playback_audio_{video_path.stem}.wav"

            # Usuń stary plik tymczasowy jeśli istnieje
            if temp_audio_path.exists():
                temp_audio_path.unlink()

            # Użyj ffmpeg do ekstrahowania audio do WAV
            print(f"[AUDIO] Ekstrakcja audio w tle z MP4...")
            extract_cmd = [
                "ffmpeg",
                "-i", str(video_path),
                "-vn",  # Bez video
                "-acodec", "pcm_s16le",  # Kodek WAV
                "-ar", "44100",  # Sample rate
                "-ac", "2",  # Stereo
                "-y",  # Nadpisz jeśli istnieje
                str(temp_audio_path)
            ]

            result = subprocess.run(extract_cmd, capture_output=True, text=True, timeout=120)  # ZWIĘKSZONY timeout dla dużych plików

            if result.returncode == 0 and temp_audio_path.exists():
                pygame.mixer.music.load(str(temp_audio_path))
                pygame.mixer.music.set_volume(1.0)
                
                # --- KLUCZOWA POPRAWKA ---
                # 1. Przewiń wideo fizycznie na klatkę 0
                video_capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                # 2. Zresetuj licznik klatek interfejsu
                video_current_frame = 0
                # 3. Zsynchronizuj czas bazowy z momentem startu
                video_last_frame_time = time.time()
                
                # Uruchom dźwięk od zera
                pygame.mixer.music.play(start=0.0)
                
                video_audio_ready = True
                video_paused = False  # Odblokuj obraz
                print(f"[OK] Start od 0:00 - Audio i Video zsynchronizowane")
            else:
                print(f"[WARN] Nie można wyekstrahować audio: {result.stderr}")
                # NOWY: Nawet jeśli audio się nie powiodło, ustaw flagę i odpauzuj (aby nie czekać w nieskończoność)
                video_audio_ready = True
                video_paused = False

        except Exception as e:
            print(f"[WARN] Nie można odtworzyć dźwięku: {e}")
            # NOWY: Nawet w przypadku błędu, ustaw flagę i odpauzuj
            video_audio_ready = True
            video_paused = False

    # Uruchom ekstrakcję audio w wątku w tle
    audio_thread = threading.Thread(target=extract_and_play_audio, daemon=True)
    audio_thread.start()

    current_state = STATE_PLAYING
    print(f"[OK] Wideo: {video_total_frames} klatek @ {video_fps} FPS")
    return True


def stop_video_playback():
    """Zatrzymaj odtwarzanie"""
    global video_capture, current_state, video_path_playing, video_last_surface, video_audio_ready

    # NOWY: Resetuj flagę audio
    video_audio_ready = False

    if video_capture:
        video_capture.release()
        video_capture = None

    # Zatrzymaj dźwięk
    try:
        pygame.mixer.music.stop()
        print("[AUDIO] Zatrzymano dźwięk")
    except:
        pass

    # Usuń tymczasowy plik audio jeśli istnieje
    if video_path_playing:
        try:
            temp_audio_path = THUMBNAIL_DIR / f"temp_playback_audio_{video_path_playing.stem}.wav"
            if temp_audio_path.exists():
                temp_audio_path.unlink()
                print(f"[AUDIO] Usunięto tymczasowy plik: {temp_audio_path.name}")
        except Exception as e:
            print(f"[WARN] Nie można usunąć pliku tymczasowego: {e}")

    video_path_playing = None
    video_last_surface = None
    current_state = STATE_VIDEOS
    print("[STOP] Zatrzymano")


def toggle_pause():
    """Przełącz pauzę"""
    global video_paused, video_last_frame_time, last_ui_interaction_time
    video_paused = not video_paused

    # Odnotuj interakcję z UI
    last_ui_interaction_time = time.time()

    # NAPRAWIONE: Pauzuj/wznów dźwięk
    try:
        if video_paused:
            pygame.mixer.music.pause()
            print("[AUDIO] Zapauzowano dźwięk")
        else:
            pygame.mixer.music.unpause()
            video_last_frame_time = time.time()
            print("[AUDIO] Wznowiono dźwięk")
    except:
        pass

    if not video_paused:
        video_last_frame_time = time.time()
    print(f"{'[PAUSE] Pauza' if video_paused else '[PLAY] Wznowiono'}")


def seek_video(seconds):
    """Przewiń wideo"""
    global video_current_frame, video_capture, video_last_frame_time
    global video_path_playing, video_last_surface, video_paused, video_current_volume, last_ui_interaction_time

    if not video_capture:
        return

    frames_to_move = int(seconds * video_fps)
    if frames_to_move == 0:
        return

    target_frame = video_current_frame + frames_to_move
    target_frame = max(0, min(target_frame, video_total_frames - 1))

    # Odnotuj interakcję z UI
    last_ui_interaction_time = time.time()

    was_paused = video_paused

    try:
        video_capture.set(cv2.CAP_PROP_POS_FRAMES, target_frame)

        ret, frame = video_capture.read()
        if not ret or frame is None:
            return

        video_current_frame = target_frame + 1

        # NAPRAWIONE: Synchronizacja audio podczas przewijania
        # Zatrzymaj audio, załaduj od nowa z dokładnej pozycji
        # NOWY: Synchronizuj tylko jeśli audio jest już gotowe
        try:
            # Oblicz pozycję w sekundach
            target_time_seconds = target_frame / video_fps if video_fps > 0 else 0

            # Ścieżka do tymczasowego pliku audio (lokalny dysk, nie karta SD)
            temp_audio_path = THUMBNAIL_DIR / f"temp_playback_audio_{video_path_playing.stem}.wav"

            if video_audio_ready and temp_audio_path.exists():
                # Zatrzymaj obecne audio
                pygame.mixer.music.stop()

                # Załaduj ponownie
                pygame.mixer.music.load(str(temp_audio_path))
                # NAPRAWIONE: Zachowaj poprzednią głośność zamiast resetować do 1.0
                pygame.mixer.music.set_volume(video_current_volume)

                # Uruchom z dokładnej pozycji (set_pos PRZED play dla lepszej synchronizacji)
                pygame.mixer.music.play(start=target_time_seconds)

                # Jeśli było zapauzowane, zapauzuj ponownie
                if was_paused:
                    pygame.mixer.music.pause()

                print(f"[AUDIO] Przewinięto audio do: {target_time_seconds:.2f}s")
            else:
                print(f"[WARN] Brak pliku audio do przewinięcia")
        except Exception as e:
            print(f"[WARN] Nie można przewinąć audio: {e}")

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        h, w = frame.shape[:2]
        aspect = w / h
        screen_aspect = SCREEN_WIDTH / SCREEN_HEIGHT

        if aspect > screen_aspect:
            new_w = SCREEN_WIDTH
            new_h = int(SCREEN_WIDTH / aspect)
        else:
            new_h = SCREEN_HEIGHT
            new_w = int(SCREEN_HEIGHT * aspect)

        frame_resized = cv2.resize(frame_rgb, (new_w, new_h))
        frame_surface = pygame.surfarray.make_surface(np.transpose(frame_resized, (1, 0, 2)))

        video_last_surface = (frame_surface, new_w, new_h)

        video_last_frame_time = time.time()
        video_paused = was_paused

    except Exception as e:
        print(f"[ERROR] Błąd seek: {e}")
        video_paused = was_paused


# ============================================================================
# RYSOWANIE EKRANÓW
# ============================================================================

def draw_main_screen(frame):
    """Ekran główny"""
    screen.fill(BLACK)

    if frame is not None:
        try:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_resized = cv2.resize(frame_rgb, (SCREEN_WIDTH, SCREEN_HEIGHT))
            frame_surface = pygame.surfarray.make_surface(np.transpose(frame_resized, (1, 0, 2)))
            screen.blit(frame_surface, (0, 0))
        except:
            draw_text("[CAM] Kamera", font_large, WHITE, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2, center=True)

    draw_grid_overlay()
    draw_center_frame()  # NOWY: Ramka środkowa
    draw_date_overlay()
    draw_battery_icon()
    draw_zoom_indicator()  # Wskaźnik zoomu zawsze widoczny

    # NAPRAWIONE: Wskaźnik mikrofonu pokazuj PODCZAS nagrywania
    draw_audio_level_indicator()  # Wskaźnik mikrofonu - funkcja sama sprawdza czy nagrywamy

    # Ukryj elementy UI podczas nagrywania
    if not recording:
        draw_menu_button()
        # draw_text("Record: START/STOP | Videos: Menu | Menu: Ustawienia | +/-: Zoom",
                #  font_tiny, WHITE, SCREEN_WIDTH // 2, SCREEN_HEIGHT - 30, center=True, bg_color=BLACK, padding=8)

    # draw_zoom_bar()  # USUNIĘTE - nie pokazuj zoom bara
    draw_recording_indicator()
    # draw_sd_indicator()
    draw_recording_time_remaining()
    draw_error_message()  # Komunikaty błędów na wierzchu


def draw_videos_screen(hide_buttons=False):
    """Ekran listy filmów - układ siatki z miniaturkami

    Args:
        hide_buttons: Jeśli True, nie rysuj przycisków w dolnym panelu (ale panel zostaje)
    """
    global videos_scroll_offset

    # Gradient tła jak w menu
    blue_gray_top = (70, 90, 110)
    gradient_height = SCREEN_HEIGHT
    start_color = BLACK
    end_color = blue_gray_top

    for y in range(gradient_height):
        ratio = y / gradient_height
        r = int(start_color[0] * (1 - ratio) + end_color[0] * ratio)
        g = int(start_color[1] * (1 - ratio) + end_color[1] * ratio)
        b = int(start_color[2] * (1 - ratio) + end_color[2] * ratio)
        color = (r, g, b)
        pygame.draw.line(screen, color, (0, y), (SCREEN_WIDTH, y))

    header_height = 95

    # === GÓRNY NAGŁÓWEK - Data, godzina i długość zaznaczonego filmu ===
    # Ramka nagłówka - tylko dolna krawędź
    pygame.draw.line(screen, LIGHT_BLUE, (0, header_height), (SCREEN_WIDTH, header_height), 3)

    # Pobierz informacje o zaznaczonym filmie
    if videos and 0 <= selected_index < len(videos):
        selected_video = videos[selected_index]

        try:
            # Parsuj nazwę pliku: video_YYYYMMDD_HHMMSS_XXfps.mp4
            filename_parts = selected_video.stem.split('_')
            if len(filename_parts) >= 3:
                date_part = filename_parts[1]  # YYYYMMDD
                time_part = filename_parts[2]  # HHMMSS

                # Formatuj datę
                year = date_part[0:4]
                month = date_part[4:6]
                day = date_part[6:8]
                date_str = f"{day}/{month}/{year}"

                # Formatuj godzinę
                hour = time_part[0:2]
                minute = time_part[2:4]
                second = time_part[4:6]
                time_str = f"{hour}:{minute}:{second}"
            else:
                # Fallback - użyj daty modyfikacji pliku
                file_mtime = selected_video.stat().st_mtime
                date_obj = datetime.fromtimestamp(file_mtime)
                date_str = date_obj.strftime("%d/%m/%Y")
                time_str = date_obj.strftime("%H:%M:%S")
        except:
            date_str = "??/??/????"
            time_str = "??:??:??"

        # Oblicz długość filmu
        try:
            cap = cv2.VideoCapture(str(selected_video))
            if cap.isOpened():
                fps = cap.get(cv2.CAP_PROP_FPS)
                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                duration = frame_count / fps if fps > 0 else 0
                duration_hours = int(duration // 3600)
                duration_minutes = int((duration % 3600) // 60)
                duration_seconds = int(duration % 60)
                duration_str = f"{duration_hours}:{duration_minutes:02d}:{duration_seconds:02d}"
                cap.release()
            else:
                duration_str = "?:??:??"
        except:
            duration_str = "?:??:??"

        # Rysuj informacje w nagłówku (tylko jeśli nie jesteśmy w trybie multi-select)
        header_y = 33

        if not multi_select_mode:
            # Normalny tryb - pokaż datę, godzinę i długość z ikoną baterii
            # Napis "WYBRANY FILM:" na lewo od daty
            label_x = 40
            draw_text_with_outline("F.:", font_large, WHITE, BLACK, label_x, header_y)

            # Oblicz szerokość napisu "WYBRANY FILM:"
            label_text_surface = font_large.render("F.:", True, WHITE)
            label_text_width = label_text_surface.get_width()

            # Oblicz szerokość daty
            date_text_surface = font_large.render(date_str, True, WHITE)
            date_text_width = date_text_surface.get_width()

            # Data po prawej od napisu (odstęp 20px)
            date_x = label_x + label_text_width + 20
            draw_text(date_str, font_large, WHITE, date_x, header_y)

            # Godzina zaraz obok daty (odstęp 20px) - NA BIAŁO
            time_x = date_x + date_text_width + 20
            draw_text(time_str, font_large, WHITE, time_x, header_y)

            # Długość filmu na prawej stronie (bateria jest rysowana poniżej dla wszystkich trybów)
            # Oblicz pozycję baterii (żeby użyć do pozycjonowania długości filmu)
            battery_width_temp = 70
            battery_right_margin_temp = 40
            battery_x_temp = SCREEN_WIDTH - battery_right_margin_temp - battery_width_temp

            duration_text_surface = font_large.render(duration_str, True, WHITE)
            duration_text_width = duration_text_surface.get_width()
            duration_x = battery_x_temp - duration_text_width - 30

            # Ikona filmu na lewo od tekstu długości
            if film_icon:
                # Przeskaluj ikonę do odpowiedniej wysokości (dostosuj do tekstu)
                icon_height = 43
                icon_aspect = film_icon.get_width() / film_icon.get_height()
                icon_width = int(icon_height * icon_aspect)
                scaled_film_icon = pygame.transform.scale(film_icon, (icon_width, icon_height))

                # Pozycja ikony - na lewo od tekstu długości (odstęp 10px)
                icon_x = duration_x - icon_width - 10
                icon_y = header_y - 8  # Wyrównanie z tekstem
                screen.blit(scaled_film_icon, (icon_x, icon_y))

            draw_text(duration_str, font_large, WHITE, duration_x, header_y)
        else:
            # Tryb zaznaczania - pokaż napis "TRYB ZAZNACZANIA"
            draw_text_with_outline("TRYB ZAZNACZANIA", font_large, YELLOW, BLACK, SCREEN_WIDTH // 2, header_y, center=True)

    # Bateria w prawym górnym rogu (zawsze pokazywana)
    battery_width = 70
    battery_height = 33
    battery_right_margin = 40
    battery_x = SCREEN_WIDTH - battery_right_margin - battery_width
    battery_y = 30  # Stała pozycja w górnej części ekranu

    # Rysuj ikonę baterii
    battery_color = GREEN if battery_is_charging else WHITE

    # Czarne tło pod baterią (outline)
    outline_padding = 2
    pygame.draw.rect(screen, BLACK,
                   (battery_x - outline_padding, battery_y - outline_padding,
                    battery_width + outline_padding * 2, battery_height + outline_padding * 2),
                   border_radius=5)

    # Główna ramka baterii
    pygame.draw.rect(screen, battery_color,
                   (battery_x, battery_y, battery_width, battery_height),
                   3, border_radius=5)

    # Końcówka baterii (PO LEWEJ)
    tip_width = 8
    tip_height = 16
    tip_x = battery_x - tip_width
    tip_y = battery_y + (battery_height - tip_height) // 2

    # Czarne tło pod końcówką
    pygame.draw.rect(screen, BLACK,
                   (tip_x - 1, tip_y - 1, tip_width + 2, tip_height + 2))

    # Końcówka w kolorze baterii
    pygame.draw.rect(screen, battery_color,
                   (tip_x, tip_y, tip_width, tip_height))

    # Segmenty baterii
    segment_width = 14
    segment_height = battery_height - 10
    segment_spacing = 4
    segments_start_x = battery_x + 8
    segment_y = battery_y + 5

    # Oblicz ile segmentów pokazać
    battery_level = battery_max_displayed_level
    if battery_level >= 75:
        segments_to_draw = 4
    elif battery_level >= 50:
        segments_to_draw = 3
    elif battery_level >= 25:
        segments_to_draw = 2
    else:
        segments_to_draw = 1

    # Ustaw clipping na wewnętrzną część baterii
    clip_margin = 3
    clip_rect = pygame.Rect(
        battery_x + clip_margin,
        battery_y + clip_margin,
        battery_width - clip_margin * 2,
        battery_height - clip_margin * 2
    )
    screen.set_clip(clip_rect)

    # Rysuj segmenty
    segment_color = GREEN if battery_is_charging else WHITE

    for i in range(segments_to_draw):
        segment_x = segments_start_x + i * (segment_width + segment_spacing)

        # Czarne tło pod segmentem
        outline_rect = pygame.Rect(
            segment_x - 1,
            segment_y - 1,
            segment_width + 2,
            segment_height + 2
        )
        pygame.draw.rect(screen, BLACK, outline_rect)

        # Segment w odpowiednim kolorze
        segment_rect = pygame.Rect(
            segment_x,
            segment_y,
            segment_width,
            segment_height
        )
        pygame.draw.rect(screen, segment_color, segment_rect)

    # Wyłącz clipping
    screen.set_clip(None)

    # Rysuj piorunek gdy bateria się ładuje
    if battery_is_charging:
        lightning_center_x = battery_x + battery_width // 2
        lightning_center_y = battery_y + battery_height // 2
        lightning_points = [
            (lightning_center_x - 4, lightning_center_y - 8),
            (lightning_center_x + 2, lightning_center_y),
            (lightning_center_x - 2, lightning_center_y),
            (lightning_center_x + 4, lightning_center_y + 8),
            (lightning_center_x, lightning_center_y + 2),
            (lightning_center_x + 1, lightning_center_y - 2)
        ]
        pygame.draw.polygon(screen, YELLOW, lightning_points)

    if not videos:
        # Napis "NAGRANE FILMY" w lewym górnym rogu (tylko gdy brak filmów)
        draw_text_with_outline("NAGRANE FILMY", font_large, WHITE, BLACK, 40, 33)

        # Komunikat gdy brak filmów - wycentrowany na ekranie (nad dolnym panelem)
        message_y = (header_height + (SCREEN_HEIGHT - 80 - header_height)) // 2

        # Pierwszy wiersz: "Brak wideo do odtworzenia"
        draw_text_with_outline("Brak wideo do odtworzenia", font_large, WHITE, BLACK,
                              SCREEN_WIDTH // 2, message_y - 60, center=True)

        # Drugi wiersz: "Nagraj nowy materiał, aby pojawił się"
        draw_text_with_outline("Nagraj nowy materiał, aby pojawił się", font_large, WHITE, BLACK,
                              SCREEN_WIDTH // 2, message_y, center=True)

        # Trzeci wiersz: "w tym miejscu."
        draw_text_with_outline("w tym miejscu.", font_large, WHITE, BLACK,
                              SCREEN_WIDTH // 2, message_y + 60, center=True)
    else:
        # Ustawienia siatki
        cols = 3
        spacing_x = 30
        spacing_y = 30
        start_x = 20
        start_y = header_height + 30

        # Scrollbar
        scrollbar_width = 15
        scrollbar_margin = 20

        # Oblicz dynamicznie szerokość miniaturek żeby wypełnić ekran
        available_width = SCREEN_WIDTH - start_x - scrollbar_width - scrollbar_margin - 20  # 20 = margines prawy
        thumb_width = int((available_width - (cols - 1) * spacing_x) / cols)
        thumb_height = int(thumb_width * 9 / 16)  # Proporcja 16:9

        scrollbar_x = SCREEN_WIDTH - scrollbar_width - 10
        scrollbar_area_height = SCREEN_HEIGHT - header_height - 100

        # Oblicz ile wierszy potrzeba
        total_rows = (len(videos) + cols - 1) // cols
        items_per_screen = ((SCREEN_HEIGHT - header_height - 100) // (thumb_height + spacing_y))

        # Automatyczne przewijanie gdy selected_index jest poza widocznym obszarem
        selected_row = selected_index // cols
        if selected_row < videos_scroll_offset:
            videos_scroll_offset = selected_row
        elif selected_row >= videos_scroll_offset + items_per_screen:
            videos_scroll_offset = selected_row - items_per_screen + 1

        videos_scroll_offset = max(0, min(videos_scroll_offset, max(0, total_rows - items_per_screen)))

        # Rysuj miniaturki w siatce
        for i in range(len(videos)):
            row = i // cols
            col = i % cols

            # Pomiń elementy poza widocznym obszarem
            if row < videos_scroll_offset or row >= videos_scroll_offset + items_per_screen + 1:
                continue

            video = videos[i]

            x = start_x + col * (thumb_width + spacing_x)
            y = start_y + (row - videos_scroll_offset) * (thumb_height + spacing_y)

            # Sprawdź czy element jest widoczny na ekranie
            if y + thumb_height > SCREEN_HEIGHT - 100:
                continue

            # Tło miniaturki
            bg_color = BLUE if i == selected_index else DARK_GRAY
            pygame.draw.rect(screen, bg_color, (x - 5, y - 5, thumb_width + 10, thumb_height + 10), border_radius=10)

            # Miniaturka
            if video.stem in thumbnails:
                try:
                    # Skaluj miniaturkę do aktualnego rozmiaru ramki
                    thumb_surface = thumbnails[video.stem]
                    scaled_thumb = pygame.transform.scale(thumb_surface, (thumb_width, thumb_height))
                    screen.blit(scaled_thumb, (x, y))
                except:
                    pygame.draw.rect(screen, GRAY, (x, y, thumb_width, thumb_height), border_radius=5)
                    draw_text("[VIDEO]", font_large, WHITE, x + thumb_width // 2, y + thumb_height // 2, center=True)
            else:
                pygame.draw.rect(screen, GRAY, (x, y, thumb_width, thumb_height), border_radius=5)
                draw_text("[VIDEO]", font_large, WHITE, x + thumb_width // 2, y + thumb_height // 2, center=True)

            # Ramka - pomarańczowa dla zaznaczonych filmów, żółta dla aktualnie wybranego, biała dla reszty
            if i in selected_videos:
                border_color = ORANGE
                border_width = 4
            elif i == selected_index:
                border_color = YELLOW
                border_width = 4
            else:
                border_color = WHITE
                border_width = 2
            pygame.draw.rect(screen, border_color, (x, y, thumb_width, thumb_height), border_width, border_radius=5)

        # Rysuj scrollbar
        if total_rows > items_per_screen:
            # Tło scrollbara
            pygame.draw.rect(screen, DARK_GRAY, (scrollbar_x, start_y, scrollbar_width, scrollbar_area_height), border_radius=5)

            # Suwak scrollbara
            scrollbar_handle_height = max(30, int(scrollbar_area_height * items_per_screen / total_rows))
            scrollbar_handle_y = start_y + int((scrollbar_area_height - scrollbar_handle_height) * videos_scroll_offset / max(1, total_rows - items_per_screen))
            pygame.draw.rect(screen, WHITE, (scrollbar_x, scrollbar_handle_y, scrollbar_width, scrollbar_handle_height), border_radius=5)

        # Licznik zaznaczonych filmów w lewym górnym rogu (tylko gdy są zaznaczone)
        if selected_videos:
            counter_text = f"{len(selected_videos)}/{len(videos)}"
            draw_text_with_outline(counter_text, font_large, WHITE, BLACK, 40, 45)

    # Panel dolny - styl jak w menu (zawsze rysowany)
    panel_height = 80
    panel_y = SCREEN_HEIGHT - panel_height

    # Ciemniejszy odcień niebiesko-szarego
    dark_blue_gray = (40, 50, 60)
    pygame.draw.rect(screen, dark_blue_gray, (0, panel_y, SCREEN_WIDTH, panel_height))

    # Dodaj liniowy gradient - co 15 pikseli jasność +2, grubość linii -1 (start: 10px)
    line_spacing = 15
    brightness_increment = 2
    initial_line_thickness = 10
    cycle_length = initial_line_thickness + 1

    current_y = panel_y + line_spacing
    line_index = 0

    while current_y < panel_y + panel_height:
        cyclic_index = line_index % cycle_length
        brightness_boost = cyclic_index * brightness_increment
        line_color = (
            min(255, dark_blue_gray[0] + brightness_boost),
            min(255, dark_blue_gray[1] + brightness_boost),
            min(255, dark_blue_gray[2] + brightness_boost)
        )
        line_thickness = initial_line_thickness - cyclic_index

        if line_thickness > 0:
            for i in range(line_thickness):
                pygame.draw.line(screen, line_color,
                               (10, current_y + i),
                               (SCREEN_WIDTH - 10, current_y + i))

        current_y += line_spacing
        line_index += 1

    # Ramka panelu - tylko górna krawędź
    pygame.draw.line(screen, LIGHT_BLUE, (0, panel_y), (SCREEN_WIDTH, panel_y), 3)

    # Jeśli hide_buttons=True, nie rysuj przycisków (używane gdy popup jest wyświetlony)
    if hide_buttons:
        return

    # Dolne przyciski - styl jak w menu
    button_y = panel_y + 15
    exit_x = 40
    exit_y = button_y

    # Lewy dolny róg: WYJDŹ / VIDEOS
    draw_text_with_outline("WYJDŹ", font_large, WHITE, BLACK, exit_x, exit_y)

    videos_button_x = exit_x + 150
    videos_button_width = 140
    videos_button_height = 45
    pygame.draw.rect(screen, WHITE, (videos_button_x + 10, exit_y - 5, videos_button_width, videos_button_height),
                     border_radius=10)
    draw_text("VIDEOS", font_large, BLACK, videos_button_x + 10 + videos_button_width // 2,
              exit_y + videos_button_height // 2 - 5, center=True)

    # Prawy dolny róg: ODTWÓRZ / OK (lub ZAZNACZ w trybie multi-select)
    ok_button_width = 100
    ok_button_x = SCREEN_WIDTH - 40 - ok_button_width
    ok_button_height = 45
    pygame.draw.rect(screen, WHITE, (ok_button_x + 13, exit_y - 5, ok_button_width - 25, ok_button_height),
                     border_radius=10)
    draw_text("OK", font_large, BLACK, ok_button_x + ok_button_width // 2,
              exit_y + ok_button_height // 2 - 5, center=True)

    # Tekst przed przyciskiem OK zależy od trybu
    action_x = ok_button_x - 200
    if multi_select_mode:
        draw_text_with_outline("ZAZNACZ", font_large, YELLOW, BLACK, action_x, exit_y)
    else:
        draw_text_with_outline("ODTWÓRZ", font_large, WHITE, BLACK, action_x, exit_y)

    # Przycisk MENU wyrównany do prawej (na lewo od ODTWÓRZ/OK)
    menu_button_width = 120
    menu_button_height = 45
    # Pozycja: na lewo od "ODTWÓRZ"
    menu_button_x = action_x - menu_button_width - 40  # 40px odstępu od "ODTWÓRZ"
    menu_button_y = exit_y - 5

    # Tekst przed przyciskiem MENU zależy od trybu
    if multi_select_mode:
        draw_text_with_outline("OPUŚĆ TRYB", font_large, YELLOW, BLACK, menu_button_x - 290, exit_y)
    else:
        draw_text_with_outline("OPCJE", font_large, WHITE, BLACK, menu_button_x - 140, exit_y)

    pygame.draw.rect(screen, WHITE, (menu_button_x, menu_button_y, menu_button_width, menu_button_height),
                     border_radius=10)
    draw_text("MENU", font_large, BLACK, menu_button_x + menu_button_width // 2,
              menu_button_y + menu_button_height // 2, center=True)

    # Komunikaty błędów na wierzchu (np. "Film jest przetwarzany...")
    draw_error_message()


def draw_video_context_menu():
    """Menu kontekstowe dla filmów - styl jak popup wyboru opcji"""
    # Przyciemnienie tła
    overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 200))
    screen.blit(overlay, (0, 0))

    # Wymiary popup
    popup_width = 700
    item_height = 80
    header_height = 80

    # Opcje menu
    menu_options = [
        {"label": "Zaznacz wiele filmów"},
        {"label": "Pokaż informacje"},
    ]

    total_items = len(menu_options)
    popup_height = total_items * item_height + 40 + header_height + 70

    # Pozycja po prawej stronie ekranu
    popup_margin = 30
    popup_x = SCREEN_WIDTH - popup_width - popup_margin
    popup_y = (SCREEN_HEIGHT - popup_height) // 2 - 35

    # Tło popup - taki sam kolor jak główny kwadrat
    dark_blue_gray = (40, 50, 60)
    pygame.draw.rect(screen, dark_blue_gray, (popup_x, popup_y, popup_width, popup_height))

    # Dodaj liniowy gradient - algorytm jak w głównym kwadracie
    line_spacing = 15
    brightness_increment = 2
    initial_line_thickness = 10
    cycle_length = initial_line_thickness + 1

    current_y = popup_y + line_spacing
    line_index = 0

    while current_y < popup_y + popup_height:
        cyclic_index = line_index % cycle_length
        brightness_boost = cyclic_index * brightness_increment
        line_color = (
            min(255, dark_blue_gray[0] + brightness_boost),
            min(255, dark_blue_gray[1] + brightness_boost),
            min(255, dark_blue_gray[2] + brightness_boost)
        )
        line_thickness = initial_line_thickness - cyclic_index

        if line_thickness > 0:
            for i in range(line_thickness):
                pygame.draw.line(screen, line_color,
                               (popup_x + 10, current_y + i),
                               (popup_x + popup_width - 10, current_y + i))

        current_y += line_spacing
        line_index += 1

    # Białe obramowanie wokół całego okna
    pygame.draw.rect(screen, LIGHT_BLUE, (popup_x, popup_y, popup_width, popup_height), 3)

    # Nagłówek na czarnym tle
    pygame.draw.rect(screen, BLACK, (popup_x, popup_y, popup_width, header_height))

    header_text = "OPCJE"
    draw_text(header_text, menu_font, WHITE, popup_x + popup_width // 2, (popup_y + header_height // 2) + 10, center=True)

    # Białe obramowanie nagłówka (tylko góra, lewo, prawo - bez dołu)
    pygame.draw.line(screen, WHITE, (popup_x, popup_y), (popup_x + popup_width, popup_y), 3)  # Góra
    pygame.draw.line(screen, WHITE, (popup_x, popup_y), (popup_x, popup_y + header_height), 3)  # Lewo
    pygame.draw.line(screen, WHITE, (popup_x + popup_width, popup_y), (popup_x + popup_width, popup_y + header_height), 3)  # Prawo

    # Lista opcji
    vertical_padding = 60  # Zwiększone z 20 na 60 - przyciski niżej
    list_start_y = popup_y + header_height + vertical_padding

    for i, option in enumerate(menu_options):
        is_selected = (i == video_context_menu_selection)
        item_y = list_start_y + i * item_height

        # Tło zaznaczonego elementu - taki sam gradient jak w głównym menu
        if is_selected:
            rect_x = popup_x + 20
            rect_y = item_y - 5
            rect_w = popup_width - 40
            rect_h = item_height - 10

            # Kolory gradientu jak w głównym menu
            dark_navy = (15, 30, 60)
            light_blue = (100, 150, 255)

            # Rysuj gradient - górna 1/3 z przejściem
            gradient_height_grad = rect_h // 3
            for y_offset in range(rect_h):
                if y_offset < gradient_height_grad:
                    # Gradient od jasnego do ciemnego
                    ratio = y_offset / gradient_height_grad
                    r = int(light_blue[0] * (1 - ratio) + dark_navy[0] * ratio)
                    g = int(light_blue[1] * (1 - ratio) + dark_navy[1] * ratio)
                    b = int(light_blue[2] * (1 - ratio) + dark_navy[2] * ratio)
                    color = (r, g, b)
                else:
                    # Ciemno granatowy dla reszty
                    color = dark_navy

                pygame.draw.line(screen, color,
                               (rect_x, rect_y + y_offset),
                               (rect_x + rect_w, rect_y + y_offset))

            # Białe obramowanie 5px
            pygame.draw.rect(screen, WHITE, (rect_x, rect_y, rect_w, rect_h), 5)
            text_color = YELLOW
        else:
            text_color = WHITE

        # Tekst opcji - używamy menu_font
        display_text = option['label'].upper()
        draw_text(display_text, menu_font, text_color, popup_x + popup_width // 2, item_y + item_height // 2 - 10, center=True)

    # Dolne przyciski - styl jak w menu
    exit_x = 40
    exit_y = SCREEN_HEIGHT - 60

    # Lewy dolny róg: COFNIJ / MENU
    draw_text_with_outline("COFNIJ", font_large, WHITE, BLACK, exit_x, exit_y)

    menu_button_x = exit_x + 150
    menu_button_width = 140
    menu_button_height = 45
    pygame.draw.rect(screen, WHITE, (menu_button_x + 10, exit_y - 5, menu_button_width, menu_button_height),
                     border_radius=10)
    draw_text("MENU", font_large, BLACK, menu_button_x + 10 + menu_button_width // 2,
              exit_y + menu_button_height // 2 - 5, center=True)

    # Prawy dolny róg: WYBIERZ / OK
    ok_button_width = 100
    ok_button_x = SCREEN_WIDTH - 40 - ok_button_width
    ok_button_height = 45
    pygame.draw.rect(screen, WHITE, (ok_button_x + 13, exit_y - 5, ok_button_width - 25, ok_button_height),
                     border_radius=10)
    draw_text("OK", font_large, BLACK, ok_button_x + ok_button_width // 2,
              exit_y + ok_button_height // 2 - 5, center=True)

    wybierz_x = ok_button_x - 160
    draw_text_with_outline("WYBIERZ", font_large, WHITE, BLACK, wybierz_x, exit_y)


def draw_video_info_dialog():
    """Dialog z informacjami o filmie - styl jak popup menu"""
    if not videos or video_info_index < 0 or video_info_index >= len(videos):
        return

    video = videos[video_info_index]

    # Przyciemnienie tła
    overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 200))
    screen.blit(overlay, (0, 0))

    # Wymiary popup - szersze okno
    popup_width = 1100
    header_height = 80

    # Oblicz wysokość na podstawie zawartości
    content_height = 450  # Informacje bez miniaturki - więcej miejsca
    popup_height = header_height + content_height + 100

    # Pozycja po prawej stronie ekranu
    popup_margin = 30
    popup_x = SCREEN_WIDTH - popup_width - popup_margin
    popup_y = (SCREEN_HEIGHT - popup_height) // 2 - 35

    # Tło popup - taki sam kolor jak główny kwadrat
    dark_blue_gray = (40, 50, 60)
    pygame.draw.rect(screen, dark_blue_gray, (popup_x, popup_y, popup_width, popup_height))

    # Dodaj liniowy gradient - algorytm jak w głównym kwadracie
    line_spacing = 15
    brightness_increment = 2
    initial_line_thickness = 10
    cycle_length = initial_line_thickness + 1

    current_y = popup_y + line_spacing
    line_index = 0

    while current_y < popup_y + popup_height:
        cyclic_index = line_index % cycle_length
        brightness_boost = cyclic_index * brightness_increment
        line_color = (
            min(255, dark_blue_gray[0] + brightness_boost),
            min(255, dark_blue_gray[1] + brightness_boost),
            min(255, dark_blue_gray[2] + brightness_boost)
        )
        line_thickness = initial_line_thickness - cyclic_index

        if line_thickness > 0:
            for i in range(line_thickness):
                pygame.draw.line(screen, line_color,
                               (popup_x + 10, current_y + i),
                               (popup_x + popup_width - 10, current_y + i))

        current_y += line_spacing
        line_index += 1

    # Białe obramowanie wokół całego okna
    pygame.draw.rect(screen, LIGHT_BLUE, (popup_x, popup_y, popup_width, popup_height), 3)

    # Nagłówek na czarnym tle
    pygame.draw.rect(screen, BLACK, (popup_x, popup_y, popup_width, header_height))
    header_text = "INFORMACJE O FILMIE"
    draw_text(header_text, menu_font, WHITE, popup_x + popup_width // 2, (popup_y + header_height // 2) + 10, center=True)

    # Białe obramowanie nagłówka (tylko góra, lewo, prawo - bez dołu)
    pygame.draw.line(screen, WHITE, (popup_x, popup_y), (popup_x + popup_width, popup_y), 3)  # Góra
    pygame.draw.line(screen, WHITE, (popup_x, popup_y), (popup_x, popup_y + header_height), 3)  # Lewo
    pygame.draw.line(screen, WHITE, (popup_x + popup_width, popup_y), (popup_x + popup_width, popup_y + header_height), 3)  # Prawo

    # Informacje (bez miniaturki) - wyrównane do lewej
    info_y = popup_y + header_height + 50
    info_spacing = 60
    info_x = popup_x + 40  # Margines od lewej

    # Nazwa pliku
    display_name = video.name
    if len(display_name) > 50:
        display_name = display_name[:47] + "..."
    draw_text_with_outline(f"NAZWA: {display_name}", font_large, WHITE, BLACK, info_x, info_y)

    # Rozmiar pliku
    size_mb = video.stat().st_size / (1024 * 1024)
    draw_text_with_outline(f"ROZMIAR: {size_mb:.2f} MB", font_large, WHITE, BLACK, info_x, info_y + info_spacing)

    # Data i godzina nagrania
    date_str = datetime.fromtimestamp(video.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    draw_text_with_outline(f"DATA NAGRANIA: {date_str}", font_large, WHITE, BLACK, info_x, info_y + info_spacing * 2)

    # Dlugosc filmu (jesli mozliwe)
    try:
        cap = cv2.VideoCapture(str(video))
        if cap.isOpened():
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = frame_count / fps if fps > 0 else 0
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            draw_text_with_outline(f"DŁUGOŚĆ: {minutes}:{seconds:02d}", font_large, WHITE, BLACK, info_x, info_y + info_spacing * 3)

            # Format i FPS
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            draw_text_with_outline(f"FORMAT: {width}x{height} @ {int(fps)} FPS", font_large, WHITE, BLACK, info_x, info_y + info_spacing * 4)
            cap.release()
        else:
            draw_text_with_outline("Nie mozna odczytac dlugosci", font_large, GRAY, BLACK, info_x, info_y + info_spacing * 3)
    except Exception:
        draw_text_with_outline("Blad odczytu informacji", font_large, RED, BLACK, info_x, info_y + info_spacing * 3)

    # Dolny header w innym kolorze (ciemniejszy niebieski)
    footer_height = 80
    footer_y = popup_y + popup_height - footer_height
    footer_color = (30, 40, 50)  # Ciemniejszy odcień niż główne tło
    pygame.draw.rect(screen, footer_color, (popup_x, footer_y, popup_width, footer_height))

    # Białe obramowanie footera (wszystkie krawędzie)
    pygame.draw.line(screen, WHITE, (popup_x, footer_y), (popup_x + popup_width, footer_y), 2)  # Góra
    pygame.draw.line(screen, WHITE, (popup_x, footer_y), (popup_x, popup_y + popup_height), 3)  # Lewo
    pygame.draw.line(screen, WHITE, (popup_x + popup_width, footer_y), (popup_x + popup_width, popup_y + popup_height), 3)  # Prawo
    pygame.draw.line(screen, WHITE, (popup_x, popup_y + popup_height), (popup_x + popup_width, popup_y + popup_height), 3)  # Dół

    # Podpowiedzi na dole w dolnym headerze
    button_bar_y = footer_y + footer_height // 2

    # Prawo: biała ramka z tekstem "OK/MENU" - styl jak przycisk MENU/VIDEOS
    button_width = 250
    button_height = 55
    button_x = popup_x + popup_width - button_width - 40
    button_y = button_bar_y - button_height // 2

    # Biała wypełniona ramka
    pygame.draw.rect(screen, WHITE, (button_x, button_y, button_width, button_height), border_radius=10)

    # Czarny tekst wewnątrz ramki - wyrównany do lewej
    text_x = button_x + 20  # Margines od lewej krawędzi ramki
    draw_text("OK/MENU", font_large, BLACK, text_x, button_y + button_height // 2 - 15)

    # Tekst "ZAMKNIJ" tuż przy przycisku OK/MENU (na lewo)
    zamknij_text_width = font_large.size("ZAMKNIJ")[0]
    zamknij_x = button_x - zamknij_text_width - 30  # 30px odstępu od przycisku
    draw_text_with_outline("ZAMKNIJ", font_large, WHITE, BLACK, zamknij_x, button_bar_y - 15)


def draw_playing_screen():
    """Ekran odtwarzania"""
    global video_current_frame, video_last_frame_time, video_last_surface

    if not video_capture:
        screen.fill(BLACK)
        draw_text("[ERROR] Blad odtwarzania", font_large, RED, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2, center=True)
        return

    # NOWY: Odtwarzaj video tylko gdy audio jest gotowe (lub gdy audio jest wyłączone w ustawieniach)
    audio_enabled = camera_settings.get("audio_recording", True)
    can_play = (not video_paused) and (video_audio_ready or not audio_enabled)

    if can_play:
        current_time = time.time()
        frame_interval = 1.0 / video_fps
        elapsed = current_time - video_last_frame_time

        # Oblicz ile klatek powinno zostać wyświetlonych na podstawie czasu
        frames_to_advance = int(elapsed / frame_interval)

        if frames_to_advance > 0:
            for _ in range(frames_to_advance):
                ret, frame = video_capture.read()

                if not ret or frame is None:
                    stop_video_playback()
                    return

                if _ == frames_to_advance - 1:  # Tylko ostatnią klatkę rysujemy
                    try:
                        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                        video_h, video_w = frame.shape[:2]
                        aspect = video_w / video_h
                        screen_aspect = SCREEN_WIDTH / SCREEN_HEIGHT

                        if aspect > screen_aspect:
                            new_w = SCREEN_WIDTH
                            new_h = int(SCREEN_WIDTH / aspect)
                        else:
                            new_h = SCREEN_HEIGHT
                            new_w = int(SCREEN_HEIGHT * aspect)

                        frame_resized = cv2.resize(frame_rgb, (new_w, new_h))
                        frame_surface = pygame.surfarray.make_surface(np.transpose(frame_resized, (1, 0, 2)))

                        video_last_surface = (frame_surface, new_w, new_h)

                    except Exception as e:
                        print(f"[WARN] Błąd klatki: {e}")

                video_current_frame += 1

            # Zaktualizuj czas bazowy - dodaj dokładny czas ramek, nie aktualny czas
            video_last_frame_time += frames_to_advance * frame_interval

    screen.fill(BLACK)
    if video_last_surface:
        try:
            frame_surface, new_w, new_h = video_last_surface
            x_offset = (SCREEN_WIDTH - new_w) // 2
            y_offset = (SCREEN_HEIGHT - new_h) // 2
            screen.blit(frame_surface, (x_offset, y_offset))
        except:
            pass

    # NOWY: Wskaźnik ładowania audio - wyświetlaj gdy audio jeszcze się nie załadowało
    if not video_audio_ready:
        time_since_start = time.time() - playback_loading_start_time
        if time_since_start > 3.0:
            # Półprzezroczyste tło
            loading_overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
            loading_overlay.fill((0, 0, 0, 180))
            screen.blit(loading_overlay, (0, 0))

            # Tekst ładowania na środku ekranu
            loading_text = "ŁADOWANIE..."
            draw_text_with_outline(loading_text, font_large, YELLOW, BLACK, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 40, center=True)

            # Animowany pasek ładowania
            bar_width = 600
            bar_height = 20
            bar_x = (SCREEN_WIDTH - bar_width) // 2
            bar_y = SCREEN_HEIGHT // 2 + 20

            # Tło paska
            pygame.draw.rect(screen, DARK_GRAY, (bar_x, bar_y, bar_width, bar_height), border_radius=10)

            # Animowana wypełniona część (pulsująca)
            pulse_speed = 2.0
            pulse_phase = (time.time() * pulse_speed) % 1.0
            fill_width = int(bar_width * pulse_phase)
            pygame.draw.rect(screen, BLUE, (bar_x, bar_y, fill_width, bar_height), border_radius=10)

            # Białe obramowanie
            pygame.draw.rect(screen, WHITE, (bar_x, bar_y, bar_width, bar_height), 3, border_radius=10)

    # === PROGRESS BAR - na dole ekranu (ukryj po bezczynności) ===
    time_since_interaction = time.time() - last_ui_interaction_time
    show_progress_bar = (time_since_interaction < UI_HIDE_DELAY)

    if show_progress_bar:
        progress_margin = 50
        progress_y = SCREEN_HEIGHT - 100  # 100px od dolnej krawędzi
        progress_width = SCREEN_WIDTH - progress_margin * 2
        progress_x = progress_margin
        progress_height = 15

        pygame.draw.rect(screen, DARK_GRAY, (progress_x, progress_y, progress_width, progress_height), border_radius=8)

        if video_total_frames > 0:
            progress_ratio = video_current_frame / video_total_frames
            filled_width = int(progress_width * progress_ratio)
            if filled_width > 0:
                pygame.draw.rect(screen, BLUE, (progress_x, progress_y, filled_width, progress_height), border_radius=8)

        pygame.draw.rect(screen, WHITE, (progress_x, progress_y, progress_width, progress_height), 2, border_radius=8)

        # Czas aktualny / całkowity - poniżej progress bara
        current_time_sec = video_current_frame / video_fps if video_fps > 0 else 0
        total_time_sec = video_total_frames / video_fps if video_fps > 0 else 0

        time_text = f"{format_time(current_time_sec)} / {format_time(total_time_sec)}"
        draw_text(time_text, font_small, WHITE, SCREEN_WIDTH // 2, progress_y + 30, center=True)

    # === SYMBOL PAUZY - na środku ekranu (tylko gdy zapauzowane I audio jest gotowe) ===
    if video_paused and video_audio_ready:
        if pause_icon is not None:
            # Wyświetl ikonę pause.png
            # Rozmiar ikony - 200px (większy niż poprzednie paski)
            icon_size = 400

            # Pozycja na środku ekranu
            center_x = SCREEN_WIDTH // 2
            center_y = SCREEN_HEIGHT // 2

            # Przeskaluj ikonę do odpowiedniego rozmiaru
            scaled_pause = pygame.transform.scale(pause_icon, (icon_size, icon_size))

            # Pozycja do wyrysowania (wyśrodkowana)
            icon_x = center_x - icon_size // 2
            icon_y = center_y - icon_size // 2

            # Rysuj ikonę
            screen.blit(scaled_pause, (icon_x, icon_y))
        else:
            # Fallback - rysuj białe paski pauzy jeśli ikona się nie załadowała
            pause_icon_size = 120
            pause_bar_width = 35
            pause_bar_height = pause_icon_size
            pause_spacing = 25

            # Pozycja na środku ekranu
            center_x = SCREEN_WIDTH // 2
            center_y = SCREEN_HEIGHT // 2

            # Lewy pasek
            left_bar_x = center_x - pause_spacing - pause_bar_width
            left_bar_y = center_y - pause_bar_height // 2

            # Prawy pasek
            right_bar_x = center_x + pause_spacing
            right_bar_y = center_y - pause_bar_height // 2

            # Rysuj z półprzezroczystym tłem
            pause_bg = pygame.Surface((pause_icon_size * 2, pause_icon_size * 2), pygame.SRCALPHA)
            pause_bg.fill((0, 0, 0, 150))
            screen.blit(pause_bg, (center_x - pause_icon_size, center_y - pause_icon_size))

            # Czarny outline (większy prostokąt z tyłu)
            outline_width = 4
            pygame.draw.rect(screen, BLACK,
                            (left_bar_x - outline_width, left_bar_y - outline_width,
                             pause_bar_width + outline_width * 2, pause_bar_height + outline_width * 2))
            pygame.draw.rect(screen, BLACK,
                            (right_bar_x - outline_width, right_bar_y - outline_width,
                             pause_bar_width + outline_width * 2, pause_bar_height + outline_width * 2))

            # Rysuj białe paski pauzy (bez zaokrągleń - usunięto border_radius)
            pygame.draw.rect(screen, WHITE, (left_bar_x, left_bar_y, pause_bar_width, pause_bar_height))
            pygame.draw.rect(screen, WHITE, (right_bar_x, right_bar_y, pause_bar_width, pause_bar_height))

    # === WSKAŹNIK GŁOŚNOŚCI - pojawia się na 2 sekundy po zmianie (kolumny bez ramki) ===
    time_since_volume_change = time.time() - last_volume_change_time
    if time_since_volume_change < VOLUME_INDICATOR_DURATION:
        # Pozycja w prawym górnym rogu
        indicator_width = 280
        indicator_height = 100
        indicator_x = SCREEN_WIDTH - indicator_width - 50
        indicator_y = 50

        # Tekst głośności (procent)
        volume_percent = int(video_current_volume * 100)
        volume_text = f"VOL: {volume_percent}%"
        text_y = indicator_y + 15
        draw_text(volume_text, font_large, WHITE, indicator_x + indicator_width // 2, text_y, center=True)

        # NOWY DESIGN: Kolumny od najmniejszej do największej (10 kolumn)
        num_columns = 10
        column_spacing = 8
        total_spacing = column_spacing * (num_columns - 1)
        available_width = indicator_width - 60  # Marginesy
        column_base_width = (available_width - total_spacing) // num_columns

        columns_start_x = indicator_x + 30
        columns_bottom_y = indicator_y + indicator_height - 20
        max_column_height = 50

        # Oblicz ile kolumn powinno być zapalonych
        active_columns = int((volume_percent / 100.0) * num_columns)

        for i in range(num_columns):
            # Wysokość kolumny rośnie liniowo od lewej do prawej
            column_height = int(max_column_height * (i + 1) / num_columns)
            column_x = columns_start_x + i * (column_base_width + column_spacing)
            column_y = columns_bottom_y - column_height

            # Kolor kolumny - białe linie dla aktywnych, ciemne dla nieaktywnych
            if i < active_columns:
                column_color = WHITE
            else:
                # Nieaktywna kolumna - ciemny szary
                column_color = (50, 50, 50)

            # Rysuj kolumnę (bez ramki, ostre krawędzie)
            pygame.draw.rect(screen, column_color,
                           (column_x, column_y, column_base_width, column_height))


def draw_confirm_dialog():
    """Dialog potwierdzenia - styl jak popup menu"""
    # Przyciemnienie tła
    overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 200))
    screen.blit(overlay, (0, 0))

    # Wymiary popup
    popup_width = 1000
    header_height = 80
    content_height = 300
    popup_height = header_height + content_height

    # Pozycja po prawej stronie ekranu
    popup_margin = 30
    popup_x = SCREEN_WIDTH - popup_width - popup_margin
    popup_y = (SCREEN_HEIGHT - popup_height) // 2 - 35

    # Tło popup - taki sam kolor jak główny kwadrat
    dark_blue_gray = (40, 50, 60)
    pygame.draw.rect(screen, dark_blue_gray, (popup_x, popup_y, popup_width, popup_height))

    # Dodaj liniowy gradient - algorytm jak w głównym kwadracie
    line_spacing = 15
    brightness_increment = 2
    initial_line_thickness = 10
    cycle_length = initial_line_thickness + 1

    current_y = popup_y + line_spacing
    line_index = 0

    while current_y < popup_y + popup_height:
        cyclic_index = line_index % cycle_length
        brightness_boost = cyclic_index * brightness_increment
        line_color = (
            min(255, dark_blue_gray[0] + brightness_boost),
            min(255, dark_blue_gray[1] + brightness_boost),
            min(255, dark_blue_gray[2] + brightness_boost)
        )
        line_thickness = initial_line_thickness - cyclic_index

        if line_thickness > 0:
            for i in range(line_thickness):
                pygame.draw.line(screen, line_color,
                               (popup_x + 10, current_y + i),
                               (popup_x + popup_width - 10, current_y + i))

        current_y += line_spacing
        line_index += 1

    # Białe obramowanie wokół całego okna
    pygame.draw.rect(screen, LIGHT_BLUE, (popup_x, popup_y, popup_width, popup_height), 3)

    # Nagłówek na czarnym tle
    pygame.draw.rect(screen, BLACK, (popup_x, popup_y, popup_width, header_height))
    header_text = "POTWIERDZENIE USUNIĘCIA"
    draw_text(header_text, menu_font, RED, popup_x + popup_width // 2, (popup_y + header_height // 2) + 10, center=True)

    # Białe obramowanie nagłówka (tylko góra, lewo, prawo - bez dołu)
    pygame.draw.line(screen, WHITE, (popup_x, popup_y), (popup_x + popup_width, popup_y), 3)  # Góra
    pygame.draw.line(screen, WHITE, (popup_x, popup_y), (popup_x, popup_y + header_height), 3)  # Lewo
    pygame.draw.line(screen, WHITE, (popup_x + popup_width, popup_y), (popup_x + popup_width, popup_y + header_height), 3)  # Prawo

    # Treść - wycentrowana w popup
    content_y = popup_y + header_height + 50

    if selected_videos:
        # Multi-delete
        draw_text(f"Usunąć {len(selected_videos)} zaznaczonych filmów?", menu_font, WHITE, popup_x + popup_width // 2, content_y, center=True)
        draw_text("Ta operacja jest nieodwracalna!", font_large, YELLOW, popup_x + popup_width // 2, content_y + 50, center=True)
    elif videos and 0 <= selected_index < len(videos):
        # Single delete
        video = videos[selected_index]
        draw_text("Usunąć ten film?", menu_font, WHITE, popup_x + popup_width // 2, content_y, center=True)

        name = video.name
        if len(name) > 40:
            name = name[:37] + "..."
        draw_text(name, font_large, YELLOW, popup_x + popup_width // 2, content_y + 50, center=True)

    # Przyciski w stylu popup - 2 opcje obok siebie
    item_height = 80
    buttons_y = popup_y + header_height + 150

    # Opcje jako lista (dla spójności z innymi popup)
    options = [
        {"label": "NIE", "index": 0},
        {"label": "TAK", "index": 1}
    ]

    # Pozycje przycisków - obok siebie z odstępem
    button_spacing = 40
    button_width = (popup_width - 80 - button_spacing) // 2

    for i, option in enumerate(options):
        is_selected = (confirm_selection == option["index"])
        item_x = popup_x + 40 + i * (button_width + button_spacing)
        item_y = buttons_y

        # Tło zaznaczonego elementu - gradient jak w innych popup
        if is_selected:
            rect_x = item_x
            rect_y = item_y
            rect_w = button_width
            rect_h = item_height

            # Kolory gradientu
            dark_navy = (15, 30, 60)
            light_blue = (100, 150, 255)

            # Rysuj gradient - górna 1/3 z przejściem
            gradient_height_grad = rect_h // 3
            for y_offset in range(rect_h):
                if y_offset < gradient_height_grad:
                    # Gradient od jasnego do ciemnego
                    ratio = y_offset / gradient_height_grad
                    r = int(light_blue[0] * (1 - ratio) + dark_navy[0] * ratio)
                    g = int(light_blue[1] * (1 - ratio) + dark_navy[1] * ratio)
                    b = int(light_blue[2] * (1 - ratio) + dark_navy[2] * ratio)
                    color = (r, g, b)
                else:
                    # Ciemno granatowy dla reszty
                    color = dark_navy

                pygame.draw.line(screen, color,
                               (rect_x, rect_y + y_offset),
                               (rect_x + rect_w, rect_y + y_offset))

            # Białe obramowanie 5px
            pygame.draw.rect(screen, WHITE, (rect_x, rect_y, rect_w, rect_h), 5)
            text_color = YELLOW
        else:
            # Nieaktywny przycisk - ciemne tło
            pygame.draw.rect(screen, (30, 30, 30), (item_x, item_y, button_width, item_height))
            pygame.draw.rect(screen, GRAY, (item_x, item_y, button_width, item_height), 2)
            text_color = WHITE

        # Tekst opcji
        display_text = option['label'].upper()
        draw_text(display_text, menu_font, text_color, item_x + button_width // 2, item_y + item_height // 2 - 10, center=True)


# ============================================================================
# OBSŁUGA PRZYCISKÓW
# ============================================================================

def show_error_message(message):
    """Wyświetl komunikat błędu na ekranie"""
    global error_message, error_message_time
    error_message = message
    error_message_time = time.time()
    print(f"[ERROR] {message}")


def handle_record():
    global current_state
    if current_state == STATE_MAIN:
        if not recording:
            # Sprawdź czy karta SD jest dostępna
            if not check_sd_card():
                show_error_message("BRAK KARTY SD!")
                return
            start_recording()
        else:
            stop_recording()


def handle_videos():
    global current_state, selected_videos, multi_select_mode, selected_index
    if current_state == STATE_MAIN and not recording:
        # Sprawdź czy karta SD jest dostępna
        if not check_sd_card():
            show_error_message("BRAK KARTY SD!")
            return
        refresh_videos()
        selected_index = 0  # NAPRAWIONE: Resetuj do pierwszego filmu
        current_state = STATE_VIDEOS
        print("\n[VIDEOS] Menu Videos")
    elif current_state == STATE_VIDEOS:
        current_state = STATE_MAIN
        selected_videos.clear()  # Wyczyść zaznaczenia przy wyjściu
        multi_select_mode = False  # Wyłącz tryb multi-select
        print("\n[MAIN] Ekran główny")
    elif current_state == STATE_PLAYING:
        stop_video_playback()
    elif current_state == STATE_CONFIRM:
        current_state = STATE_VIDEOS


def handle_menu():
    global current_state, video_context_menu_selection, multi_select_mode, selected_videos, menu_value_editing, date_editing
    if current_state == STATE_MAIN and not recording:
        open_menu()
    elif current_state == STATE_MENU:
        if date_editing:
            # Jeśli edytujemy datę, wyłącz tryb edycji daty
            date_editing = False
            print("[MENU] Wyłączono tryb edycji daty")
        elif menu_value_editing:
            # Jeśli edytujemy wartość, wyłącz tryb edycji
            menu_value_editing = False
            print("[MENU] Wyłączono tryb edycji wartości")
        else:
            # Zamknij menu
            close_menu()
    elif current_state == STATE_SUBMENU:
        close_submenu()
    elif current_state == STATE_SELECTION_POPUP:
        close_popup()
    elif current_state == STATE_DATE_PICKER:
        current_state = STATE_MENU
        print("[DATE_PICKER] Anulowano")
    elif current_state == STATE_VIDEOS:
        if multi_select_mode:
            # Anuluj tryb multi-select i wyczyść zaznaczenia
            multi_select_mode = False
            selected_videos.clear()
            print("[CANCEL] Tryb zaznaczania wielu filmów WYŁĄCZONY - zaznaczenia wyczyszczone")
        else:
            # Otwórz menu kontekstowe
            current_state = STATE_VIDEO_CONTEXT_MENU
            video_context_menu_selection = 0
    elif current_state == STATE_VIDEO_CONTEXT_MENU:
        # Zamknij menu kontekstowe
        current_state = STATE_VIDEOS
    elif current_state == STATE_VIDEO_INFO:
        # Zamknij dialog informacji
        current_state = STATE_VIDEOS


def handle_ok():
    global current_state, confirm_selection, selected_index, selected_tile, selected_videos, video_info_index, multi_select_mode

    if current_state == STATE_VIDEOS:
        if videos and 0 <= selected_index < len(videos):
            if multi_select_mode:
                # W trybie multi-select: toggle zaznaczenia
                if selected_index in selected_videos:
                    selected_videos.remove(selected_index)
                    print(f"[UNCHECK] Odznaczono film #{selected_index + 1}")
                else:
                    selected_videos.add(selected_index)
                    print(f"[CHECK] Zaznaczono film #{selected_index + 1}")
            else:
                # Normalnie: odtwórz film
                start_video_playback(videos[selected_index])

    elif current_state == STATE_PLAYING:
        toggle_pause()

    elif current_state == STATE_CONFIRM:
        if confirm_selection == 1:
            # Usuń wszystkie zaznaczone filmy lub pojedynczy
            if selected_videos:
                # Usuń wszystkie zaznaczone
                for idx in sorted(selected_videos, reverse=True):
                    if 0 <= idx < len(videos):
                        video = videos[idx]
                        video.unlink()
                        thumb = THUMBNAIL_DIR / f"{video.stem}.jpg"
                        if thumb.exists():
                            thumb.unlink()
                        print(f"[DELETE] Usunięto: {video.name}")
                selected_videos.clear()
            else:
                # Usuń pojedynczy film
                if videos and 0 <= selected_index < len(videos):
                    video = videos[selected_index]
                    video.unlink()
                    thumb = THUMBNAIL_DIR / f"{video.stem}.jpg"
                    if thumb.exists():
                        thumb.unlink()
                    print(f"[DELETE] Usunięto: {video.name}")
            refresh_videos()
        current_state = STATE_VIDEOS
        confirm_selection = 0

    elif current_state == STATE_VIDEO_CONTEXT_MENU:
        # Obsługa wyboru w menu kontekstowym
        if video_context_menu_selection == 0:
            # Włącz tryb zaznaczania wielu filmów
            multi_select_mode = True
            current_state = STATE_VIDEOS
            print("[OK] Tryb zaznaczania wielu filmów WŁĄCZONY")
        elif video_context_menu_selection == 1:
            # Pokaż informacje
            video_info_index = selected_index
            current_state = STATE_VIDEO_INFO

    elif current_state == STATE_VIDEO_INFO:
        # Zamknij dialog informacji
        current_state = STATE_VIDEOS

    elif current_state == STATE_SELECTION_POPUP:
        popup_confirm()

    elif current_state == STATE_DATE_PICKER:
        date_picker_confirm()

    elif current_state == STATE_MENU:
        if not menu_editing_mode:
            # Jeśli nie jesteśmy w trybie edycji, OK wchodzi do trybu edycji (tak jak prawo)
            menu_navigate_right()
        elif menu_editing_mode:
            # W trybie edycji: zmień wartość zaznaczonej opcji
            section_names = ["Image Quality/Size", "Manual Settings", "Znacznik Daty", "Poziom Baterii"]
            current_section_name = section_names[selected_section]
            filtered_tiles = [tile for tile in menu_tiles if tile["section"] == current_section_name]

            if 0 <= selected_tile < len(filtered_tiles):
                tile = filtered_tiles[selected_tile]
                tile_id = tile["id"]

                # Toggle dla opcji boolean
                if tile_id in ["grid", "show_date", "show_time", "center_frame", "audio_rec"]:
                    key_map = {
                        "grid": "show_grid",
                        "show_date": "show_date",
                        "show_time": "show_time",
                        "center_frame": "show_center_frame",
                        "audio_rec": "audio_recording"
                    }
                    key = key_map[tile_id]
                    camera_settings[key] = not camera_settings.get(key, False)
                    save_config()
                    apply_camera_settings()
                    print(f"[TOGGLE] {tile['label']}: {camera_settings[key]}")

                # Otwórz popup dla opcji z listą
                elif tile_id == "quality":
                    open_selection_popup("video_resolution", VIDEO_RESOLUTIONS)

                elif tile_id == "wb":
                    open_selection_popup("awb_mode", WB_MODES)

                elif tile_id == "iso":
                    open_selection_popup("iso_mode", ISO_MODES)

                elif tile_id == "date_position":
                    open_selection_popup("date_position", DATE_POSITIONS)

                elif tile_id == "manual_date":
                    # Włącz tryb edycji daty bezpośrednio w menu
                    global date_editing, date_edit_day, date_edit_month, date_edit_year, date_edit_segment
                    date_editing = not date_editing
                    if date_editing:
                        # Inicjalizuj wartości z manual_date lub aktualna data
                        if camera_settings.get("manual_date"):
                            try:
                                date_obj = datetime.strptime(camera_settings["manual_date"], "%Y-%m-%d")
                                date_edit_day = date_obj.day
                                date_edit_month = date_obj.month
                                date_edit_year = date_obj.year
                            except:
                                now = datetime.now()
                                date_edit_day = now.day
                                date_edit_month = now.month
                                date_edit_year = now.year
                        else:
                            now = datetime.now()
                            date_edit_day = now.day
                            date_edit_month = now.month
                            date_edit_year = now.year
                        date_edit_segment = 0
                        print("[DATE] Edycja daty włączona")
                    else:
                        # Zapisz datę
                        date_str = f"{date_edit_year:04d}-{date_edit_month:02d}-{date_edit_day:02d}"
                        camera_settings["manual_date"] = date_str
                        save_config()
                        print(f"[DATE] Zapisano datę: {date_str}")

                elif tile_id == "date_format":
                    open_selection_popup("date_format", DATE_FORMATS)

                elif tile_id == "date_month_text":
                    camera_settings["date_month_text"] = not camera_settings.get("date_month_text", False)
                    save_config()
                    print(f"[TOGGLE] Miesiąc słownie: {camera_settings['date_month_text']}")

                elif tile_id == "date_separator":
                    open_selection_popup("date_separator", DATE_SEPARATORS)

                elif tile_id == "date_color":
                    open_selection_popup("date_color", DATE_COLORS)

                elif tile_id == "date_font_size":
                    open_selection_popup("date_font_size", DATE_FONT_SIZES)

                elif tile_id == "font":
                    open_selection_popup("font_family", FONT_NAMES)

                # Dla sliderów włącz/wyłącz tryb edycji wartości
                elif tile_id in ["brightness", "contrast", "saturation", "sharpness", "exposure", "battery_level"]:
                    global menu_value_editing
                    menu_value_editing = not menu_value_editing
                    if menu_value_editing:
                        print(f"[EDIT] Edycja wartości: {tile['label']}")
                    else:
                        print(f"[EDIT] Zakończono edycję: {tile['label']}")

    elif current_state == STATE_SUBMENU:
        submenu_ok()


def handle_delete():
    global current_state, confirm_selection, date_editing, camera_settings, menu_value_editing, selected_tile, menu_editing_mode

    if current_state == STATE_MENU and date_editing:
        # Podczas edycji daty: resetuj do automatycznej daty
        camera_settings["manual_date"] = None
        date_editing = False
        save_config()
        print("[DATE] Reset do automatycznej daty")
    elif current_state == STATE_MENU and (menu_editing_mode or menu_value_editing):
        # Reset zaznaczonej opcji do wartości fabrycznej
        # Mapowanie tile ID na klucz ustawienia i wartość domyślną
        factory_defaults = {
            "quality": ("video_resolution", "1080p30"),
            "grid": ("show_grid", True),
            "font": ("font_family", "HomeVideo"),
            "wb": ("awb_mode", "auto"),
            "iso": ("iso_mode", "auto"),
            "brightness": ("brightness", 0.0),
            "contrast": ("contrast", 1.0),
            "saturation": ("saturation", 1.0),
            "sharpness": ("sharpness", 1.0),
            "exposure": ("exposure_compensation", 0.0),
            "show_date": ("show_date", False),
            "show_time": ("show_time", False),
            "date_position": ("date_position", "top_left"),
            "manual_date": ("manual_date", None),
            "date_format": ("date_format", "DD/MM/YYYY"),
            "date_month_text": ("date_month_text", False),
            "date_separator": ("date_separator", "/"),
            "date_color": ("date_color", "yellow"),
            "date_font_size": ("date_font_size", "medium"),
            "battery_level": ("fake_battery_level", None)  # Specjalny przypadek
        }

        # Pobierz aktualnie zaznaczony tile
        section_names = ["Image Quality/Size", "Manual Settings", "Znacznik Daty", "Poziom Baterii"]
        current_section_name = section_names[selected_section]
        filtered_tiles = [tile for tile in menu_tiles if tile["section"] == current_section_name]

        if 0 <= selected_tile < len(filtered_tiles):
            tile = filtered_tiles[selected_tile]
            tile_id = tile["id"]

            if tile_id in factory_defaults:
                setting_key, default_value = factory_defaults[tile_id]

                # Specjalne obsługi dla battery_level
                if tile_id == "battery_level":
                    global fake_battery_level
                    fake_battery_level = default_value
                    print(f"[RESET] Poziom baterii zresetowany do rzeczywistego")
                else:
                    camera_settings[setting_key] = default_value
                    print(f"[RESET] {tile['label']} zresetowany do: {default_value}")

                # Wyłącz tryb edycji wartości jeśli był włączony
                menu_value_editing = False

                # Zapisz zmiany
                save_config()
                apply_camera_settings()
    elif current_state == STATE_VIDEOS and videos:
        current_state = STATE_CONFIRM
        confirm_selection = 0


def handle_up():
    global video_context_menu_selection, last_videos_scroll, video_current_volume, last_volume_change_time
    if current_state == STATE_VIDEOS:
        current_time = time.time()
        if current_time - last_videos_scroll >= VIDEOS_SCROLL_DELAY:
            videos_navigate_up()
            last_videos_scroll = current_time
    elif current_state == STATE_PLAYING:
        current_volume = pygame.mixer.music.get_volume()
        new_volume = min(1.0, current_volume + 0.05)
        pygame.mixer.music.set_volume(new_volume)
        # Zapisz aktualną głośność i czas zmiany
        video_current_volume = new_volume
        last_volume_change_time = time.time()
        print(f"[VOL] Głośność UP: {int(new_volume * 100)}%")
    elif current_state == STATE_MENU:
        menu_navigate_up()
    elif current_state == STATE_SUBMENU:
        submenu_navigate_up()
    elif current_state == STATE_VIDEO_CONTEXT_MENU:
        video_context_menu_selection = max(0, video_context_menu_selection - 1)
    elif current_state == STATE_SELECTION_POPUP:
        popup_navigate_up()
    elif current_state == STATE_DATE_PICKER:
        date_picker_navigate_up()


def handle_down():
    global video_context_menu_selection, last_videos_scroll, video_current_volume, last_volume_change_time
    if current_state == STATE_VIDEOS:
        current_time = time.time()
        if current_time - last_videos_scroll >= VIDEOS_SCROLL_DELAY:
            videos_navigate_down()
            last_videos_scroll = current_time
    elif current_state == STATE_PLAYING:
        current_volume = pygame.mixer.music.get_volume()
        new_volume = max(0.0, current_volume - 0.05)
        pygame.mixer.music.set_volume(new_volume)
        # Zapisz aktualną głośność i czas zmiany
        video_current_volume = new_volume
        last_volume_change_time = time.time()
        print(f"[VOL] Głośność DOWN: {int(new_volume * 100)}%")
    elif current_state == STATE_MENU:
        menu_navigate_down()
    elif current_state == STATE_SUBMENU:
        submenu_navigate_down()
    elif current_state == STATE_VIDEO_CONTEXT_MENU:
        video_context_menu_selection = min(1, video_context_menu_selection + 1)
    elif current_state == STATE_SELECTION_POPUP:
        popup_navigate_down()
    elif current_state == STATE_DATE_PICKER:
        date_picker_navigate_down()


def handle_left():
    global confirm_selection, fake_battery_level, date_edit_segment
    if current_state == STATE_CONFIRM:
        confirm_selection = 0
    elif current_state == STATE_MENU:
        if date_editing:
            # W trybie edycji daty: przełącz na poprzedni segment
            date_edit_segment = max(0, date_edit_segment - 1)
            print(f"[DATE] Segment: {date_edit_segment}")
        elif menu_value_editing:
            # W trybie edycji wartości: zmniejsz wartość
            section_names = ["Image Quality/Size", "Manual Settings", "Znacznik Daty", "Poziom Baterii"]
            current_section_name = section_names[selected_section]
            filtered_tiles = [tile for tile in menu_tiles if tile["section"] == current_section_name]

            if 0 <= selected_tile < len(filtered_tiles):
                tile = filtered_tiles[selected_tile]
                tile_id = tile["id"]

                if tile_id == "brightness":
                    camera_settings["brightness"] = max(-1.0, camera_settings.get("brightness", 0.0) - 0.1)
                    apply_camera_settings()
                    save_config()
                elif tile_id == "contrast":
                    camera_settings["contrast"] = max(0.0, camera_settings.get("contrast", 1.0) - 0.1)
                    apply_camera_settings()
                    save_config()
                elif tile_id == "saturation":
                    camera_settings["saturation"] = max(0.0, camera_settings.get("saturation", 1.0) - 0.1)
                    apply_camera_settings()
                    save_config()
                elif tile_id == "sharpness":
                    camera_settings["sharpness"] = max(0.0, camera_settings.get("sharpness", 1.0) - 0.2)
                    apply_camera_settings()
                    save_config()
                elif tile_id == "exposure":
                    camera_settings["exposure_compensation"] = max(-2.0, camera_settings.get("exposure_compensation", 0.0) - 0.2)
                    apply_camera_settings()
                    save_config()
                elif tile_id == "battery_level":
                    current_level = fake_battery_level if fake_battery_level is not None else 100
                    fake_battery_level = max(0, current_level - 5)
        else:
            menu_navigate_left()
    elif current_state == STATE_VIDEOS:
        videos_navigate_left()
    elif current_state == STATE_DATE_PICKER:
        date_picker_navigate_left()


def handle_right():
    global confirm_selection, fake_battery_level, date_edit_segment
    if current_state == STATE_CONFIRM:
        confirm_selection = 1
    elif current_state == STATE_MENU:
        if date_editing:
            # W trybie edycji daty: przełącz na następny segment
            date_edit_segment = min(2, date_edit_segment + 1)
            print(f"[DATE] Segment: {date_edit_segment}")
        elif menu_value_editing:
            # W trybie edycji wartości: zwiększ wartość
            section_names = ["Image Quality/Size", "Manual Settings", "Znacznik Daty", "Poziom Baterii"]
            current_section_name = section_names[selected_section]
            filtered_tiles = [tile for tile in menu_tiles if tile["section"] == current_section_name]

            if 0 <= selected_tile < len(filtered_tiles):
                tile = filtered_tiles[selected_tile]
                tile_id = tile["id"]

                if tile_id == "brightness":
                    camera_settings["brightness"] = min(1.0, camera_settings.get("brightness", 0.0) + 0.1)
                    apply_camera_settings()
                    save_config()
                elif tile_id == "contrast":
                    camera_settings["contrast"] = min(2.0, camera_settings.get("contrast", 1.0) + 0.1)
                    apply_camera_settings()
                    save_config()
                elif tile_id == "saturation":
                    camera_settings["saturation"] = min(2.0, camera_settings.get("saturation", 1.0) + 0.1)
                    apply_camera_settings()
                    save_config()
                elif tile_id == "sharpness":
                    camera_settings["sharpness"] = min(4.0, camera_settings.get("sharpness", 1.0) + 0.2)
                    apply_camera_settings()
                    save_config()
                elif tile_id == "exposure":
                    camera_settings["exposure_compensation"] = min(2.0, camera_settings.get("exposure_compensation", 0.0) + 0.2)
                    apply_camera_settings()
                    save_config()
                elif tile_id == "battery_level":
                    current_level = fake_battery_level if fake_battery_level is not None else 100
                    fake_battery_level = min(100, current_level + 5)
        else:
            menu_navigate_right()
    elif current_state == STATE_VIDEOS:
        videos_navigate_right()
    elif current_state == STATE_DATE_PICKER:
        date_picker_navigate_right()


def handle_zoom_in():
    global fake_battery_level
    if current_state == STATE_MAIN:
        adjust_zoom(ZOOM_STEP)
    elif current_state == STATE_MENU and menu_editing_mode:
        # Zwiększ wartość liczbową dla zaznaczonego elementu (tylko w trybie edycji)
        section_names = ["Image Quality/Size", "Manual Settings", "Znacznik Daty", "Poziom Baterii"]
        current_section_name = section_names[selected_section]
        filtered_tiles = [tile for tile in menu_tiles if tile["section"] == current_section_name]

        if 0 <= selected_tile < len(filtered_tiles):
            tile = filtered_tiles[selected_tile]
            tile_id = tile["id"]

            if tile_id == "brightness":
                camera_settings["brightness"] = min(1.0, camera_settings.get("brightness", 0.0) + 0.1)
                apply_camera_settings()
                save_config()
            elif tile_id == "contrast":
                camera_settings["contrast"] = min(2.0, camera_settings.get("contrast", 1.0) + 0.1)
                apply_camera_settings()
                save_config()
            elif tile_id == "saturation":
                camera_settings["saturation"] = min(2.0, camera_settings.get("saturation", 1.0) + 0.1)
                apply_camera_settings()
                save_config()
            elif tile_id == "sharpness":
                camera_settings["sharpness"] = min(4.0, camera_settings.get("sharpness", 1.0) + 0.2)
                apply_camera_settings()
                save_config()
            elif tile_id == "exposure":
                camera_settings["exposure_compensation"] = min(2.0, camera_settings.get("exposure_compensation", 0.0) + 0.2)
                apply_camera_settings()
                save_config()
            elif tile_id == "battery_level":
                current_level = fake_battery_level if fake_battery_level is not None else 100
                fake_battery_level = min(100, current_level + 5)


def handle_zoom_out():
    global fake_battery_level
    if current_state == STATE_MAIN:
        adjust_zoom(-ZOOM_STEP)
    elif current_state == STATE_MENU and menu_editing_mode:
        # Zmniejsz wartość liczbową dla zaznaczonego elementu (tylko w trybie edycji)
        section_names = ["Image Quality/Size", "Manual Settings", "Znacznik Daty", "Poziom Baterii"]
        current_section_name = section_names[selected_section]
        filtered_tiles = [tile for tile in menu_tiles if tile["section"] == current_section_name]

        if 0 <= selected_tile < len(filtered_tiles):
            tile = filtered_tiles[selected_tile]
            tile_id = tile["id"]

            if tile_id == "brightness":
                camera_settings["brightness"] = max(-1.0, camera_settings.get("brightness", 0.0) - 0.1)
                apply_camera_settings()
                save_config()
            elif tile_id == "contrast":
                camera_settings["contrast"] = max(0.0, camera_settings.get("contrast", 1.0) - 0.1)
                apply_camera_settings()
                save_config()
            elif tile_id == "saturation":
                camera_settings["saturation"] = max(0.0, camera_settings.get("saturation", 1.0) - 0.1)
                apply_camera_settings()
                save_config()
            elif tile_id == "sharpness":
                camera_settings["sharpness"] = max(0.0, camera_settings.get("sharpness", 1.0) - 0.2)
                apply_camera_settings()
                save_config()
            elif tile_id == "exposure":
                camera_settings["exposure_compensation"] = max(-2.0, camera_settings.get("exposure_compensation", 0.0) - 0.2)
                apply_camera_settings()
                save_config()
            elif tile_id == "battery_level":
                current_level = fake_battery_level if fake_battery_level is not None else 100
                fake_battery_level = max(0, current_level - 5)


def cleanup(signum=None, frame=None):
    """Zamknięcie"""
    global camera, recording, running, video_capture, audio, audio_recording
    print("\n[CLEANUP] Zamykanie...")
    running = False

    if video_capture:
        video_capture.release()

    # NAPRAWIONE: Zatrzymaj pygame.mixer
    try:
        pygame.mixer.music.stop()
        pygame.mixer.quit()
        print("[OK] Mixer cleanup OK")
    except:
        pass

    # Zatrzymaj nagrywanie audio jeśli aktywne
    if audio_recording:
        stop_audio_recording()

    # NOWY: Zatrzymaj monitoring audio
    if audio_monitoring_active:
        stop_audio_monitoring()

    # Zamknij PyAudio
    if audio:
        try:
            audio.terminate()
            print("[OK] Audio cleanup OK")
        except:
            pass

    if recording:
        stop_recording()
    if camera:
        try:
            camera.stop()
            camera.close()
        except:
            pass

    save_config()

    # Cleanup GPIO
    try:
        GPIO.cleanup()
        print("[OK] GPIO cleanup OK")
    except:
        pass

    try:
        pygame.quit()
    except:
        pass
    sys.exit(0)


# ============================================================================
# GŁÓWNY PROGRAM
# ============================================================================

if __name__ == '__main__':
    signal.signal(signal.SIGINT, cleanup)

    # Wykryj i ustaw kartę SD
    print("\n" + "="*70)
    print("[SD CARD] WYKRYWANIE KARTY SD")
    print("="*70)
    VIDEO_DIR = find_sd_card()
    if VIDEO_DIR:
        print(f"[OK] Katalog wideo: {VIDEO_DIR}")
    else:
        print("[ERROR] Nie znaleziono karty SD! Aplikacja może nie działać poprawnie.")
        # Fallback do katalogu domyślnego
        VIDEO_DIR = Path("/home/pi/camera_project/videos")
        VIDEO_DIR.mkdir(parents=True, exist_ok=True)
        print(f"[FALLBACK] Używam: {VIDEO_DIR}")
    print("="*70 + "\n")

    init_pygame()
    init_camera()

    # Inicjalizacja audio - mikrofon
    print("\n" + "="*70)
    print("[AUDIO] INICJALIZACJA SYSTEMU AUDIO")
    print("="*70)
    audio_ok = init_audio()
    if audio_ok:
        print(f"[OK] Audio zainicjalizowane - device_index: {audio_device_index}")

        # NOWY: Uruchom ciągły monitoring poziomu audio
        start_audio_monitoring()
    else:
        print("[WARN] Audio nie zainicjalizowane - aplikacja będzie działać bez dźwięku")
    print("="*70 + "\n")

    # Inicjalizacja INA219 Battery Monitor
    try:
        ina219 = INA219(addr=0x41)
        print("[INA219] Battery monitor initialized successfully")
    except Exception as e:
        print(f"[INA219] Failed to initialize battery monitor: {e}")
        ina219 = None

    # Inicjalizacja matrycy przycisków 4x4
    init_matrix()

    # Przypisanie handler'ów do przycisków
    button_handlers['RECORD'] = handle_record
    button_handlers['OK'] = handle_ok
    button_handlers['VIDEOS'] = handle_videos
    button_handlers['DELETE'] = handle_delete
    button_handlers['UP'] = handle_up
    button_handlers['DOWN'] = handle_down
    button_handlers['LEFT'] = handle_left
    button_handlers['RIGHT'] = handle_right
    button_handlers['MENU'] = handle_menu
    button_handlers['PLUS'] = handle_zoom_in
    button_handlers['MINUS'] = handle_zoom_out
    button_handlers['IR'] = toggle_ir_cut

    # Synchronizuj miniaturki z filmami
    sync_thumbnails_with_videos()

    print("\n" + "="*70)
    print("[SYSTEM] SYSTEM KAMERA - RASPBERRY PI 5")
    print("="*70)
    print("[MAIN] Kamera | [REC] Record | Videos | [CONFIG] Menu | [ZOOM] +/- Zoom")
    print("="*70 + "\n")

    clock = pygame.time.Clock()
    
    last_continuous_seek = 0
    hold_start_right = None
    hold_start_left = None
    
    try:
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    cleanup()
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        cleanup()

            current_time = time.time()

            # Aktualizuj szacowany czas baterii (co 30 sekund)
            update_battery_estimate()

            # Monitoruj dostępność karty SD (co 2 sekundy)
            if current_time - last_sd_check_time >= SD_CHECK_INTERVAL:
                old_video_dir = VIDEO_DIR
                new_video_dir = find_sd_card()

                # Wykryj zmianę stanu karty SD
                if old_video_dir is None and new_video_dir is not None:
                    # Karta została wsadzona
                    VIDEO_DIR = new_video_dir
                    print(f"[SD CARD] Karta SD wykryta: {VIDEO_DIR}")
                elif old_video_dir is not None and new_video_dir is None:
                    # Karta została wyjęta
                    VIDEO_DIR = None
                    print("[SD CARD] Karta SD wyjęta")
                elif old_video_dir != new_video_dir and new_video_dir is not None:
                    # Zmieniono kartę SD
                    VIDEO_DIR = new_video_dir
                    print(f"[SD CARD] Zmieniono kartę SD: {VIDEO_DIR}")

                last_sd_check_time = current_time

            # Skanuj matrycę przycisków i wywołuj handlery
            check_matrix_buttons()

            # Sprawdź czy karta SD jest dostępna podczas przeglądania filmów
            if current_state in [STATE_VIDEOS, STATE_PLAYING, STATE_CONFIRM]:
                if not check_sd_card():
                    print("[WARN] Karta SD niedostępna - powrót do podglądu")
                    if current_state == STATE_PLAYING:
                        stop_video_playback()
                    current_state = STATE_MAIN
                    selected_videos.clear()
                    multi_select_mode = False

            if current_state == STATE_PLAYING:
                if is_button_pressed('RIGHT'):
                    if hold_start_right is None:
                        hold_start_right = current_time
                else:
                    hold_start_right = None

                if is_button_pressed('LEFT'):
                    if hold_start_left is None:
                        hold_start_left = current_time
                else:
                    hold_start_left = None

                # NAPRAWIONE: Płynne przyspieszenie przewijania - każda sekunda dodaje ~15% do prędkości
                # Prędkość bazowa zależy od długości filmiku
                if is_button_pressed('RIGHT'):
                    hold_duration = current_time - hold_start_right if hold_start_right is not None else 0
                    # Oblicz długość filmiku w sekundach
                    video_duration_sec = video_total_frames / video_fps if video_fps > 0 else 60
                    # Bazowa prędkość skalowana do długości filmiku
                    # Krótkie filmiki (< 60s): base_speed = 0.5s
                    # Średnie filmiki (60-300s): base_speed = 0.5-2.5s
                    # Długie filmiki (> 300s): base_speed = 2.5s+
                    base_speed = 0.5 + (video_duration_sec / 120.0)  # Wzrost bazowej prędkości z długością
                    base_speed = min(base_speed, 5.0)  # Maksymalnie 5s bazowo
                    speed_multiplier = 1.0 + (hold_duration * 0.15)  # 15% za sekundę
                    speed_multiplier = min(speed_multiplier, 2.0)  # Maksymalnie 2x prędkości bazowej
                    seek_speed = base_speed * speed_multiplier
                    seek_video(seek_speed)
                    last_continuous_seek = current_time

                elif is_button_pressed('LEFT'):
                    hold_duration = current_time - hold_start_left if hold_start_left is not None else 0
                    # Oblicz długość filmiku w sekundach
                    video_duration_sec = video_total_frames / video_fps if video_fps > 0 else 60
                    # Bazowa prędkość skalowana do długości filmiku
                    base_speed = 0.5 + (video_duration_sec / 120.0)  # Wzrost bazowej prędkości z długością
                    base_speed = min(base_speed, 5.0)  # Maksymalnie 5s bazowo
                    speed_multiplier = 1.0 + (hold_duration * 0.15)  # 15% za sekundę
                    speed_multiplier = min(speed_multiplier, 2.0)  # Maksymalnie 2x prędkości bazowej
                    seek_speed = base_speed * speed_multiplier
                    seek_video(-seek_speed)
                    last_continuous_seek = current_time

            if current_state == STATE_MAIN:
                if is_button_pressed('PLUS') and current_time - last_zoom_time >= 0.05:
                    adjust_zoom(ZOOM_STEP)
                    last_zoom_time = current_time

                if is_button_pressed('MINUS') and current_time - last_zoom_time >= 0.05:
                    adjust_zoom(-ZOOM_STEP)
                    last_zoom_time = current_time

            if current_state == STATE_SUBMENU:
                if is_button_pressed('UP') and current_time - last_menu_scroll >= MENU_SCROLL_DELAY:
                    submenu_navigate_up()
                    last_menu_scroll = current_time

                if is_button_pressed('DOWN') and current_time - last_menu_scroll >= MENU_SCROLL_DELAY:
                    submenu_navigate_down()
                    last_menu_scroll = current_time

            # STATE_VIDEOS: Nawigacja obsługiwana przez handle_up/down poprzez check_matrix_buttons()
            # Usunięto ciągłe sprawdzanie is_button_pressed dla STATE_VIDEOS aby uniknąć duplikacji
            
            frame = None
            if current_state in [STATE_MAIN, STATE_MENU, STATE_SUBMENU]:
                try:
                    frame = camera.capture_array()
                except:
                    frame = None
            
            if current_state == STATE_MAIN:
                draw_main_screen(frame)
            elif current_state == STATE_VIDEOS:
                draw_videos_screen()
            elif current_state == STATE_CONFIRM:
                draw_videos_screen(hide_buttons=True)
                draw_confirm_dialog()
            elif current_state == STATE_PLAYING:
                draw_playing_screen()
            elif current_state == STATE_MENU:
                draw_menu_tiles(frame)
                draw_menu_bottom_buttons()  # Przyciski na wierzchu (wysoki z-index)
            elif current_state == STATE_SUBMENU:
                draw_submenu_screen(frame)
            elif current_state == STATE_SELECTION_POPUP:
                draw_menu_tiles(frame)
                draw_selection_popup()
                draw_menu_bottom_buttons()  # Przyciski na wierzchu (wysoki z-index)
            elif current_state == STATE_DATE_PICKER:
                draw_menu_tiles(frame)
                draw_date_picker()
                draw_menu_bottom_buttons()  # Przyciski na wierzchu (wysoki z-index)
            elif current_state == STATE_VIDEO_CONTEXT_MENU:
                draw_videos_screen(hide_buttons=True)
                draw_video_context_menu()
            elif current_state == STATE_VIDEO_INFO:
                draw_videos_screen(hide_buttons=True)
                draw_video_info_dialog()

            pygame.display.flip()
            clock.tick(30)
    
    except KeyboardInterrupt:
        cleanup()
    except Exception as e:
        print(f"\n[ERROR] Błąd: {e}")
        import traceback
        traceback.print_exc()
        cleanup()
    
    cleanup()
