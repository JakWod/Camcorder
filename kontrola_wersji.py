#!/usr/bin/env python3
import pygame
import sys
import os
import shutil
from datetime import datetime
from pathlib import Path
import cv2
import numpy as np
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput
from gpiozero import Button
import signal
import subprocess
import time
import json
from PIL import Image, ImageDraw, ImageFont
import threading
import math
import re

# ============================================================================
# KONFIGURACJA
# ============================================================================

VIDEO_DIR = Path("/home/pi/camera_project")
VIDEO_DIR.mkdir(exist_ok=True)
THUMBNAIL_DIR = VIDEO_DIR / "thumbnails"
THUMBNAIL_DIR.mkdir(exist_ok=True)
CONFIG_FILE = VIDEO_DIR / "camera_config.json"

# GPIO Pins
PIN_RECORD = 17
PIN_OK = 22
PIN_VIDEOS = 23
PIN_DELETE = 24
PIN_UP = 5
PIN_DOWN = 6
PIN_LEFT = 13
PIN_RIGHT = 19
PIN_MENU = 27
PIN_PLUS = 9
PIN_MINUS = 11

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

# Video Player
video_capture = None
video_paused = False
video_current_frame = 0
video_total_frames = 0
video_fps = 30
video_path_playing = None
video_last_frame_time = 0
video_last_surface = None

# Video Manager
videos = []
selected_index = 0
thumbnails = {}
videos_scroll_offset = 0
selected_videos = set()  # Multi-select: zestaw indeksów zaznaczonych filmów
video_context_menu_selection = 0  # Wybór w menu kontekstowym
video_info_index = 0  # Indeks filmu do wyświetlenia informacji
multi_select_mode = False  # Tryb zaznaczania wielu filmów

# Pygame
font_large = None
font_medium = None
font_small = None
font_tiny = None
SCREEN_WIDTH = 0
SCREEN_HEIGHT = 0

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

# SD Card Icons
sd_icon_surface = None
no_sd_icon_surface = None
SD_ICON_FILE = None
NO_SD_ICON_FILE = None

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
    "show_date": False,
    "show_time": False,
    "date_position": "top_left",
    "manual_date": None,
    "zoom": 0.0,
    "show_grid": True,
}

# Opcje
WB_MODES = ["auto", "incandescent", "tungsten", "fluorescent", "indoor", "daylight", "cloudy"]
DATE_POSITIONS = ["top_left", "top_right", "bottom_left", "bottom_right"]
VIDEO_RESOLUTIONS = ["1080p30", "1080p60", "720p30", "720p60", "4K30"]

# Mapowanie rozdzielczości
RESOLUTION_MAP = {
    "1080p30": {"size": (1920, 1080), "fps": 30},
    "1080p60": {"size": (1920, 1080), "fps": 60},
    "720p30": {"size": (1280, 720), "fps": 30},
    "720p60": {"size": (1280, 720), "fps": 60},
    "4K30": {"size": (3840, 2160), "fps": 30},
}

# Bitrate dla różnych rozdzielczości (w bitach na sekundę)
BITRATE_MAP = {
    "1080p30": 10000000,   # 10 Mbps
    "1080p60": 15000000,   # 15 Mbps
    "720p30": 6000000,     # 6 Mbps
    "720p60": 10000000,    # 10 Mbps
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
# FUNKCJE POMOCNICZE DLA IKON
# ============================================================================

def find_icon_file(base_name):
    """Znajdź plik ikony z dowolnym rozszerzeniem"""
    extensions = ['.png', '.PNG', '.jpg', '.JPG', '.jpeg', '.JPEG']
    
    for ext in extensions:
        path = VIDEO_DIR / f"{base_name}{ext}"
        if path.exists():
            print(f"[OK] Znaleziono ikonę: {path.name}")
            return path
    
    print(f"[WARN] Nie znaleziono ikony: {base_name}")
    return None


def create_fallback_sd_icon(size, is_available):
    """Stwórz prostą ikonę zastępczą"""
    surface = pygame.Surface(size, pygame.SRCALPHA)
    w, h = size
    
    if is_available:
        # Zielona ikona karty SD
        # Tło karty
        pygame.draw.rect(surface, GREEN, (5, 15, w-10, h-20), border_radius=5)
        pygame.draw.rect(surface, WHITE, (5, 15, w-10, h-20), 3, border_radius=5)
        
        # Wcięcie karty SD (góra)
        notch_width = 16
        notch_height = 8
        notch_x = w//2 - notch_width//2
        pygame.draw.rect(surface, BLACK, (notch_x, 15, notch_width, notch_height))
        
        # Kontakty na karcie (poziome linie)
        for i in range(4):
            y = 28 + i * 6
            pygame.draw.line(surface, DARK_GRAY, (12, y), (w-12, y), 2)
        
        # Tekst SD
        font = pygame.font.Font(None, 20)
        text = font.render("SD", True, WHITE)
        text_rect = text.get_rect(center=(w//2, h-15))
        surface.blit(text, text_rect)
    else:
        # Czerwona ikona braku karty
        # Tło karty
        pygame.draw.rect(surface, RED, (5, 15, w-10, h-20), border_radius=5)
        pygame.draw.rect(surface, WHITE, (5, 15, w-10, h-20), 3, border_radius=5)
        
        # Duży krzyżyk X
        margin = 12
        pygame.draw.line(surface, WHITE, (margin, 20), (w-margin, h-5), 5)
        pygame.draw.line(surface, WHITE, (w-margin, 20), (margin, h-5), 5)
        
        # Tekst NO
        font = pygame.font.Font(None, 18)
        text = font.render("NO", True, WHITE)
        text_rect = text.get_rect(center=(w//2, h//2))
        # Cień
        shadow = font.render("NO", True, BLACK)
        shadow_rect = shadow.get_rect(center=(w//2+1, h//2+1))
        surface.blit(shadow, shadow_rect)
        surface.blit(text, text_rect)
    
    return surface


def load_sd_icons():
    """Wczytaj ikony kart SD"""
    global sd_icon_surface, no_sd_icon_surface, SD_ICON_FILE, NO_SD_ICON_FILE
    
    icon_size = (60, 60)
    
    print("\n" + "="*60)
    print("[INFO] ŁADOWANIE IKON SD CARD")
    print("="*60)
    print(f"[DIR] Katalog: {VIDEO_DIR}")
    
    # Lista wszystkich plików w katalogu (dla diagnostyki)
    try:
        all_files = list(VIDEO_DIR.glob("*"))
        print(f"[LIST] Pliki w katalogu ({len(all_files)}):")
        for f in all_files[:15]:  # Pokaż pierwsze 15
            if f.is_file():
                print(f"   - {f.name}")
    except Exception as e:
        print(f"[WARN] Nie można listować plików: {e}")
    
    print()
    
    # Szukaj ikony SD (karta włożona)
    SD_ICON_FILE = find_icon_file("sd")
    
    if SD_ICON_FILE and SD_ICON_FILE.exists():
        try:
            print(f"[LOAD] Wczytywanie: {SD_ICON_FILE}")
            print(f"   Rozmiar pliku: {SD_ICON_FILE.stat().st_size} bajtów")
            
            sd_img = pygame.image.load(str(SD_ICON_FILE))
            original_size = sd_img.get_size()
            print(f"   Oryginalny rozmiar: {original_size}")
            
            sd_icon_surface = pygame.transform.smoothscale(sd_img, icon_size)
            print(f"[OK] Ikona SD wczytana i przeskalowana do {icon_size}")
            
        except Exception as e:
            print(f"[ERROR] Błąd wczytywania {SD_ICON_FILE.name}: {e}")
            print(f"   Tworzę ikonę zastępczą...")
            sd_icon_surface = create_fallback_sd_icon(icon_size, True)
    else:
        print(f"[WARN] Brak pliku ikony SD - używam ikony zastępczej")
        sd_icon_surface = create_fallback_sd_icon(icon_size, True)
    
    print()
    
    # Szukaj ikony NO SD (brak karty)
    NO_SD_ICON_FILE = find_icon_file("nosd")
    
    if NO_SD_ICON_FILE and NO_SD_ICON_FILE.exists():
        try:
            print(f"[LOAD] Wczytywanie: {NO_SD_ICON_FILE}")
            print(f"   Rozmiar pliku: {NO_SD_ICON_FILE.stat().st_size} bajtów")
            
            no_sd_img = pygame.image.load(str(NO_SD_ICON_FILE))
            original_size = no_sd_img.get_size()
            print(f"   Oryginalny rozmiar: {original_size}")
            
            no_sd_icon_surface = pygame.transform.smoothscale(no_sd_img, icon_size)
            print(f"[OK] Ikona NO SD wczytana i przeskalowana do {icon_size}")
            
        except Exception as e:
            print(f"[ERROR] Błąd wczytywania {NO_SD_ICON_FILE.name}: {e}")
            print(f"   Tworzę ikonę zastępczą...")
            no_sd_icon_surface = create_fallback_sd_icon(icon_size, False)
    else:
        print(f"[WARN] Brak pliku ikony NO SD - używam ikony zastępczej")
        no_sd_icon_surface = create_fallback_sd_icon(icon_size, False)
    
    print()
    print("="*60)
    print("[OK] IKONY SD GOTOWE")
    print("="*60 + "\n")


# ============================================================================
# FUNKCJE SD CARD
# ============================================================================

def check_sd_card():
    """Sprawdź czy karta SD jest dostępna"""
    try:
        return VIDEO_DIR.exists() and os.access(str(VIDEO_DIR), os.W_OK)
    except:
        return False


def get_available_space_gb():
    """Pobierz dostępne miejsce na karcie w GB"""
    try:
        stat = shutil.disk_usage(str(VIDEO_DIR))
        return stat.free / (1024**3)  # Konwersja na GB
    except:
        return 0


def get_recording_time_estimate():
    """Oblicz szacowany czas nagrywania na podstawie dostępnego miejsca"""
    if not check_sd_card():
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
        
        return f"{hours:02d}h {minutes:02d}m"
    except:
        return "-- : --"


def get_recording_quality():
    """Pobierz aktualną jakość nagrywania"""
    resolution = camera_settings.get("video_resolution", "1080p30")
    return resolution.replace("p", "p ")


def draw_sd_card_info():
    """Rysuj informacje o karcie SD"""
    sd_x = SCREEN_WIDTH - 100
    sd_y = 70  # Poniżej baterii
    
    # Sprawdź czy karta jest dostępna
    sd_available = check_sd_card()
    
    # Narysuj odpowiednią ikonę
    if sd_available and sd_icon_surface:
        screen.blit(sd_icon_surface, (sd_x, sd_y))
    elif not sd_available and no_sd_icon_surface:
        screen.blit(no_sd_icon_surface, (sd_x, sd_y))
    else:
        # Fallback - rysuj tekst
        draw_text_with_outline("SD" if sd_available else "NO", font_tiny, 
                              GREEN if sd_available else RED, BLACK, sd_x + 15, sd_y + 20)
    
    # Informacje tekstowe poniżej ikony
    info_y = sd_y + 65
    
    if sd_available:
        # Czas nagrywania i jakość nagrywania obok siebie, 10 jednostek niżej
        time_text = get_recording_time_estimate()
        quality_text = get_recording_quality()
        combined_text = f"{time_text} | {quality_text}"
        draw_text_with_outline(combined_text, font_medium, WHITE, BLACK, sd_x - 175, info_y + 15)
    else:
        # Brak karty
        draw_text_with_outline("BRAK SD", font_tiny, RED, BLACK, sd_x - 15, info_y)


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
        "video_resolution": "1080p30",
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
            else:
                controls["AwbEnable"] = False
        
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
        
        if not original_fps or original_fps <= 0 or original_fps > 120:
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
                    
                    if camera_settings.get("show_time", False):
                        date_text = date_obj.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        date_text = date_obj.strftime("%Y-%m-%d")
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
        
        temp_file = video_path.parent / f"temp_{video_path.name}"
        
        # Filtr drawtext
        drawtext_filter = (
            f"drawtext="
            f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
            f"text='{date_text_escaped}':"
            f"fontcolor=yellow:"
            f"fontsize=40:"
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
        
        # Zamiana plików
        video_path.unlink()
        temp_file.rename(video_path)
        
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
            "label": "Rozdzielczosc",
            "value": lambda: camera_settings.get("video_resolution", "1080p30"),
            "icon": "[VIDEO]",
            "section": "Image Quality/Size"
        },
        {
            "id": "grid",
            "label": "Siatka pomocnicza",
            "value": lambda: "WL." if camera_settings.get("show_grid", False) else "WYL.",
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
            "id": "brightness",
            "label": "Jasnosc",
            "value": lambda: f"{camera_settings.get('brightness', 0.0):.1f}",
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
            "label": "Ostrosc",
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
            "label": "Pokaz date",
            "value": lambda: "WL." if camera_settings.get("show_date", False) else "WYL.",
            "icon": "[DATE]",
            "section": "Znacznik Daty"
        },
        {
            "id": "show_time",
            "label": "Pokaz godzine",
            "value": lambda: "WL." if camera_settings.get("show_time", False) else "WYL.",
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
            {"type": "select", "label": "Rozdzielczosc", "key": "video_resolution", "options": VIDEO_RESOLUTIONS},
            {"type": "toggle", "label": "Siatka pomocnicza", "key": "show_grid"},
            {"type": "spacer"},
            {"type": "button", "label": "[RESET] RESET USTAWIEN", "action": "reset_section"},
        ]

    elif tile_id == "manual":
        submenu_items = [
            {"type": "header", "text": "[CONFIG] MANUAL SETTINGS"},
            {"type": "spacer"},
            {"type": "select", "label": "White Balance", "key": "awb_mode", "options": WB_MODES},
            {"type": "slider", "label": "Jasnosc", "key": "brightness", "min": -1.0, "max": 1.0, "step": 0.1},
            {"type": "slider", "label": "Kontrast", "key": "contrast", "min": 0.0, "max": 2.0, "step": 0.1},
            {"type": "slider", "label": "Saturacja", "key": "saturation", "min": 0.0, "max": 2.0, "step": 0.1},
            {"type": "slider", "label": "Ostrosc", "key": "sharpness", "min": 0.0, "max": 4.0, "step": 0.2},
            {"type": "slider", "label": "Ekspozycja", "key": "exposure_compensation", "min": -2.0, "max": 2.0, "step": 0.2},
            {"type": "spacer"},
            {"type": "button", "label": "[RESET] RESET USTAWIEN", "action": "reset_section"},
        ]

    elif tile_id == "date":
        submenu_items = [
            {"type": "header", "text": "[DATE] ZNACZNIK DATY"},
            {"type": "spacer"},
            {"type": "toggle", "label": "Pokaz date", "key": "show_date"},
            {"type": "toggle", "label": "Pokaz godzine", "key": "show_time"},
            {"type": "select", "label": "Pozycja daty", "key": "date_position", "options": DATE_POSITIONS},
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
    global current_state, selected_tile, menu_editing_mode, selected_section

    init_menu_tiles()
    selected_tile = 0
    selected_section = 0
    menu_editing_mode = False
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
    global current_state, submenu_editing
    
    save_config()
    apply_camera_settings()
    submenu_editing = False
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
    global selected_section, selected_tile
    if current_state == STATE_MENU:
        if menu_editing_mode:
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
    global selected_section, selected_tile
    if current_state == STATE_MENU:
        if menu_editing_mode:
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
            apply_camera_settings()
    else:
        submenu_selected = max(0, submenu_selected - 1)
        while submenu_selected > 0 and submenu_items[submenu_selected]["type"] in ["spacer", "header"]:
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
            apply_camera_settings()
    else:
        submenu_selected = min(len(submenu_items) - 1, submenu_selected + 1)
        while submenu_selected < len(submenu_items) - 1 and submenu_items[submenu_selected]["type"] in ["spacer", "header"]:
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

    # Rysuj ramkę panelu z opcjami (prawy)
    pygame.draw.rect(screen, DARK_GRAY, (list_panel_x, list_panel_y, list_panel_width, list_panel_height), border_radius=10)
    pygame.draw.rect(screen, LIGHT_BLUE, (list_panel_x, list_panel_y, list_panel_width, list_panel_height), 3, border_radius=10)


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
        if is_selected and not menu_editing_mode:
            # Kolor wybrany
            bg_color = (60, 60, 60)
            border_color = YELLOW
        else:
            # Kolor niewybrany
            bg_color = (30, 30, 30)
            border_color = GRAY

        # Rysuj prostokąt
        rect_style = border_radius=10
        if is_selected and not menu_editing_mode:
            # Jeśli wybrany i nie edytujemy, prostokąt łączy się z prawej
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


        # Ikona
        icon_color = YELLOW if is_selected else WHITE
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
    scroll_offset = max(0, selected_tile - visible_items // 2)

    # Czcionka dla menu - większa niż font_large
    menu_font = pygame.font.Font(None, 65)

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

            # Białe obramowanie - wydłużone o 2 piksele w dół
            pygame.draw.rect(screen, WHITE,
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

        # Rysuj czarny outline dla value
        outline_width = 2
        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if dx == 0 and dy == 0:
                    continue
                text_surface_outline = menu_font.render(value_text.upper(), True, BLACK)
                text_rect_outline = text_surface_outline.get_rect(topright=(value_x + dx, current_y + 20 + dy))
                screen.blit(text_surface_outline, text_rect_outline)

        # Rysuj właściwy tekst value
        text_surface = menu_font.render(value_text.upper(), True, value_color)
        text_rect = text_surface.get_rect(topright=(value_x, current_y + 20))
        screen.blit(text_surface, text_rect)


    # Dolna belka z przyciskami
    bottom_bar_y = SCREEN_HEIGHT - 80
    pygame.draw.rect(screen, DARK_GRAY, (0, bottom_bar_y, SCREEN_WIDTH, 80))

    # Lewy dolny róg: WYJDZ / MENU
    exit_x = 40
    exit_y = bottom_bar_y + 15
    draw_text_with_outline("WYJDZ", font_large, WHITE, BLACK, exit_x, exit_y)

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
    
    if submenu_editing:
        instructions = "Up/Down: Zmień | OK: Zatwierdź | MENU: Anuluj"
    else:
        instructions = "Up/Down: Nawigacja | OK: Wybierz | MENU: Wróć"
    
    draw_text(instructions, font_small, WHITE, SCREEN_WIDTH // 2, SCREEN_HEIGHT - 30, 
             center=True, bg_color=BLACK, padding=10)


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


def get_battery_level():
    """Odczytaj poziom naładowania baterii (0-100)"""
    # Jeśli ustawiono fikcyjny poziom baterii, użyj go
    if fake_battery_level is not None:
        return fake_battery_level

    try:
        # Próba odczytu z systemu Linux (Raspberry Pi)
        with open('/sys/class/power_supply/BAT0/capacity', 'r') as f:
            return int(f.read().strip())
    except:
        try:
            # Alternatywna ścieżka dla niektórych systemów
            with open('/sys/class/power_supply/BAT1/capacity', 'r') as f:
                return int(f.read().strip())
        except:
            # Jeśli nie można odczytać, zwróć 100% (pełna bateria jako domyślna)
            return 100


def draw_battery_icon():
    """Rysuj ikonę baterii z 4 segmentami"""
    # Pozycja i rozmiar baterii
    battery_x = SCREEN_WIDTH - 100
    battery_y = 20
    battery_width = 60
    battery_height = 28
    
    # Czarne tło pod baterią (outline)
    outline_padding = 2
    pygame.draw.rect(screen, BLACK,
                     (battery_x - outline_padding, battery_y - outline_padding,
                      battery_width + outline_padding * 2, battery_height + outline_padding * 2),
                     border_radius=4)
    
    # Główna ramka baterii (biała)
    pygame.draw.rect(screen, WHITE,
                     (battery_x, battery_y, battery_width, battery_height),
                     3, border_radius=4)
    
    # Końcówka baterii (po lewej)
    tip_width = 6
    tip_height = 12
    tip_x = battery_x - tip_width
    tip_y = battery_y + (battery_height - tip_height) // 2
    
    # Czarne tło pod końcówką
    pygame.draw.rect(screen, BLACK,
                     (tip_x - 1, tip_y - 1, tip_width + 2, tip_height + 2))
    
    # Biała końcówka
    pygame.draw.rect(screen, WHITE,
                     (tip_x, tip_y, tip_width, tip_height))
    
    # Ustawienia segmentów
    segment_width = 10
    segment_height = battery_height - 8  # Margines 4px góra i dół
    segment_spacing = 3
    segments_start_x = battery_x + battery_width - 6 - segment_width  # Margines od prawej krawędzi
    segment_y = battery_y + 4  # Margines od góry
    
    # Pobierz poziom baterii i oblicz ile segmentów pokazać
    battery_level = get_battery_level()
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
    
    # Rysuj segmenty
    for i in range(segments_to_draw):
        segment_x = segments_start_x - i * (segment_width + segment_spacing)
        
        # Czarne tło pod segmentem (outline)
        outline_rect = pygame.Rect(
            segment_x - 1,
            segment_y - 1,
            segment_width + 2,
            segment_height + 2
        )
        pygame.draw.rect(screen, BLACK, outline_rect)
        
        # Biały segment
        segment_rect = pygame.Rect(
            segment_x,
            segment_y,
            segment_width,
            segment_height
        )
        pygame.draw.rect(screen, WHITE, segment_rect)
    
    # Wyłącz clipping
    screen.set_clip(None)


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
    """Rysuj wskaźnik nagrywania lub STBY"""
    rec_x = 585  
    rec_y = 30

    if recording and recording_start_time:
        elapsed_time = time.time() - recording_start_time
        hours = int(elapsed_time // 3600)
        minutes = int((elapsed_time % 3600) // 60)
        seconds = int(elapsed_time % 60)
        milliseconds = int((elapsed_time % 1) * 100)
        time_text = f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:02d}"

        if int(pygame.time.get_ticks() / 500) % 2:
            pygame.draw.circle(screen, RED, (rec_x + 10, rec_y + 15), 8)

        draw_text_with_outline("REC", font_medium, RED, BLACK, rec_x + 30, rec_y)
        draw_text_with_outline(time_text, font_medium, RED, BLACK, rec_x + 95, rec_y)
    else:
        draw_text_with_outline("STBY", font_large, GREEN, BLACK, rec_x, rec_y)


def draw_menu_button():
    """Rysuj przycisk informujący o możliwości otwarcia menu w lewym górnym rogu"""
    button_width = 100
    button_height = 50
    button_x = 20
    button_y = 20

    # Rysuj tło przycisku
    pygame.draw.rect(screen, DARK_GRAY, (button_x, button_y, button_width, button_height), border_radius=10)
    pygame.draw.rect(screen, BLUE, (button_x, button_y, button_width, button_height), 3, border_radius=10)

    # Rysuj tekst na przycisku
    draw_text_with_outline("MENU", font_medium, WHITE, BLACK, button_x + button_width // 2, button_y + button_height // 2, center=True)


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
    print(f"[OK] {len(thumbnails)} miniatur")


def draw_text(text, font, color, x, y, center=False, bg_color=None, padding=10):
    """Rysuj tekst"""
    if not text or not font:
        return
    try:
        text_surface = font.render(str(text), True, color)
        if center:
            text_rect = text_surface.get_rect(center=(x, y))
        else:
            text_rect = text_surface.get_rect(topleft=(x, y))
        if bg_color:
            bg_rect = text_rect.inflate(padding * 2, padding * 2)
            pygame.draw.rect(screen, bg_color, bg_rect, border_radius=5)
        screen.blit(text_surface, text_rect)
    except:
        pass


def draw_text_with_outline(text, font, color, outline_color, x, y, center=False):
    """Rysuj tekst z obrysem"""
    if not text or not font:
        return
    try:
        outline_width = 2
        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if dx == 0 and dy == 0:
                    continue
                outline_surface = font.render(str(text), True, outline_color)
                if center:
                    outline_rect = outline_surface.get_rect(center=(x + dx, y + dy))
                else:
                    outline_rect = outline_surface.get_rect(topleft=(x + dx, y + dy))
                screen.blit(outline_surface, outline_rect)
        
        text_surface = font.render(str(text), True, color)
        if center:
            text_rect = text_surface.get_rect(center=(x, y))
        else:
            text_rect = text_surface.get_rect(topleft=(x, y))
        screen.blit(text_surface, text_rect)
    except:
        pass


def get_display_date():
    """Pobierz datę do wyświetlenia"""
    if camera_settings.get("manual_date"):
        return camera_settings["manual_date"]
    else:
        if camera_settings.get("show_time", False):
            return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            return datetime.now().strftime("%Y-%m-%d")


def draw_date_overlay():
    """Rysuj overlay daty na podglądzie"""
    if not camera_settings.get("show_date", False):
        return
    
    date_text = get_display_date()
    position = camera_settings.get("date_position", "top_left")
    
    margin = 20
    
    if position == "top_left":
        x, y = margin, margin
    elif position == "top_right":
        x, y = SCREEN_WIDTH - margin, margin
        temp_surface = font_small.render(date_text, True, YELLOW)
        x -= temp_surface.get_width()
    elif position == "bottom_left":
        x, y = margin, SCREEN_HEIGHT - margin - 30
    elif position == "bottom_right":
        x, y = SCREEN_WIDTH - margin, SCREEN_HEIGHT - margin - 30
        temp_surface = font_small.render(date_text, True, YELLOW)
        x -= temp_surface.get_width()
    else:
        x, y = margin, margin
    
    draw_text_with_outline(date_text, font_small, YELLOW, BLACK, x, y)


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
    """Nawigacja w lewo - w układzie siatki"""
    global selected_index
    if videos:
        if selected_index % 3 != 0:  # Jeśli nie jest w pierwszej kolumnie
            selected_index = max(0, selected_index - 1)


def videos_navigate_right():
    """Nawigacja w prawo - w układzie siatki"""
    global selected_index
    if videos:
        if selected_index % 3 != 2 and selected_index + 1 < len(videos):  # Jeśli nie jest w ostatniej kolumnie
            selected_index = min(len(videos) - 1, selected_index + 1)


# ============================================================================
# INICJALIZACJA
# ============================================================================

def init_pygame():
    """Inicjalizuj pygame"""
    global screen, font_large, font_medium, font_small, font_tiny, SCREEN_WIDTH, SCREEN_HEIGHT
    
    print("[INIT] Pygame init...")
    pygame.init()
    
    info = pygame.display.Info()
    SCREEN_WIDTH = info.current_w
    SCREEN_HEIGHT = info.current_h
    
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.FULLSCREEN)
    pygame.display.set_caption("Kamera System")
    pygame.mouse.set_visible(False)
    
    font_large = pygame.font.Font(None, 60)
    font_medium = pygame.font.Font(None, 40)
    font_small = pygame.font.Font(None, 30)
    font_tiny = pygame.font.Font(None, 24)
    
    screen.fill(BLACK)
    pygame.display.flip()
    
    # Wczytaj ikony SD
    load_sd_icons()
    
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
    
    load_config()
    apply_camera_settings()
    
    print(f"[OK] Kamera OK: {resolution}")


# ============================================================================
# NAGRYWANIE
# ============================================================================

def start_recording():
    """Start nagrywania - FPS w nazwie pliku"""
    global recording, current_file, encoder, recording_start_time, current_recording_fps
    
    if not recording:
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
        
        try:
            camera.stop_encoder()
            print("[OK] Encoder zatrzymany")
            
            time.sleep(1.5)
            
            if saved_file and saved_file.exists():
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
                    
                    if camera_settings.get("show_date", False):
                        def process_video():
                            print("[DATE] Dodawanie daty...")
                            add_date_overlay_to_video(saved_file)
                            print("[OK] Przetwarzanie zakończone")
                        
                        thread = threading.Thread(target=process_video, daemon=True)
                        thread.start()
                    else:
                        print("[OK] Przetwarzanie zakończone")
            else:
                print(f"[ERROR] Plik nie istnieje")
                
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
    
    print(f"\n[PLAY] ODTWARZANIE: {video_path.name}")
    
    video_capture = cv2.VideoCapture(str(video_path))
    if not video_capture.isOpened():
        print("[ERROR] Nie można otworzyć")
        return False
    
    video_fps = extract_fps_from_filename(video_path.name)
    
    if not video_fps:
        video_fps = video_capture.get(cv2.CAP_PROP_FPS)
        print(f"[FPS] OpenCV FPS: {video_fps}")
    
    if video_fps <= 0 or video_fps > 120:
        video_fps = 30
        print(f"[WARN] FPS nieprawidłowy, użyto 30")
    
    print(f"[OK] UŻYWAM FPS: {video_fps}")
    
    video_total_frames = int(video_capture.get(cv2.CAP_PROP_FRAME_COUNT))
    video_current_frame = 0
    video_paused = False
    video_path_playing = video_path
    video_last_frame_time = time.time()
    video_last_surface = None
    
    current_state = STATE_PLAYING
    print(f"[OK] Wideo: {video_total_frames} klatek @ {video_fps} FPS")
    return True


def stop_video_playback():
    """Zatrzymaj odtwarzanie"""
    global video_capture, current_state, video_path_playing, video_last_surface
    
    if video_capture:
        video_capture.release()
        video_capture = None
    
    video_path_playing = None
    video_last_surface = None
    current_state = STATE_VIDEOS
    print("[STOP] Zatrzymano")


def toggle_pause():
    """Przełącz pauzę"""
    global video_paused, video_last_frame_time
    video_paused = not video_paused
    if not video_paused:
        video_last_frame_time = time.time()
    print(f"{'[PAUSE] Pauza' if video_paused else '[PLAY] Wznowiono'}")


def seek_video(seconds):
    """Przewiń wideo"""
    global video_current_frame, video_capture, video_last_frame_time
    global video_path_playing, video_last_surface, video_paused

    if not video_capture:
        return

    frames_to_move = int(seconds * video_fps)
    if frames_to_move == 0:
        return

    target_frame = video_current_frame + frames_to_move
    target_frame = max(0, min(target_frame, video_total_frames - 1))

    was_paused = video_paused

    try:
        video_capture.set(cv2.CAP_PROP_POS_FRAMES, target_frame)

        ret, frame = video_capture.read()
        if not ret or frame is None:
            return

        video_current_frame = target_frame + 1

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
    draw_date_overlay()
    draw_battery_icon()

    # Ukryj elementy UI podczas nagrywania
    if not recording:
        draw_sd_card_info()
        draw_menu_button()
        draw_text("Record: START/STOP | Videos: Menu | Menu: Ustawienia | +/-: Zoom",
                 font_tiny, WHITE, SCREEN_WIDTH // 2, SCREEN_HEIGHT - 30, center=True, bg_color=BLACK, padding=8)

    draw_zoom_bar()
    draw_recording_indicator()


def draw_videos_screen():
    """Ekran listy filmów - układ siatki z miniaturkami"""
    global videos_scroll_offset
    screen.fill(BLACK)

    header_height = 100
    pygame.draw.rect(screen, DARK_GRAY, (0, 0, SCREEN_WIDTH, header_height))

    # Nagłówek z wskaźnikiem trybu multi-select
    if multi_select_mode:
        draw_text("[VIDEOS] NAGRANE FILMY - TRYB ZAZNACZANIA", font_large, YELLOW, SCREEN_WIDTH // 2, 50, center=True)
    else:
        draw_text("[VIDEOS] NAGRANE FILMY", font_large, WHITE, SCREEN_WIDTH // 2, 50, center=True)

    if not videos:
        draw_text("[EMPTY] Brak filmow", font_medium, GRAY, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 60, center=True)
        draw_text("Zamknij i nacisnij Record", font_small, DARK_GRAY, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2, center=True)
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

            # Ramka
            border_color = YELLOW if i == selected_index else WHITE
            border_width = 4 if i == selected_index else 2
            pygame.draw.rect(screen, border_color, (x, y, thumb_width, thumb_height), border_width, border_radius=5)

            # Checkbox dla zaznaczonych filmów
            if i in selected_videos:
                checkbox_size = 40
                checkbox_x = x + thumb_width - checkbox_size - 10
                checkbox_y = y + 10
                pygame.draw.circle(screen, GREEN, (checkbox_x + checkbox_size // 2, checkbox_y + checkbox_size // 2), checkbox_size // 2)
                draw_text("[YES]", font_medium, WHITE, checkbox_x + checkbox_size // 2, checkbox_y + checkbox_size // 2, center=True)

        # Rysuj scrollbar
        if total_rows > items_per_screen:
            # Tło scrollbara
            pygame.draw.rect(screen, DARK_GRAY, (scrollbar_x, start_y, scrollbar_width, scrollbar_area_height), border_radius=5)

            # Suwak scrollbara
            scrollbar_handle_height = max(30, int(scrollbar_area_height * items_per_screen / total_rows))
            scrollbar_handle_y = start_y + int((scrollbar_area_height - scrollbar_handle_height) * videos_scroll_offset / max(1, total_rows - items_per_screen))
            pygame.draw.rect(screen, WHITE, (scrollbar_x, scrollbar_handle_y, scrollbar_width, scrollbar_handle_height), border_radius=5)

        # Licznik filmów
        if selected_videos:
            counter_text = f"{selected_index + 1}/{len(videos)} | Zaznaczono: {len(selected_videos)}"
        else:
            counter_text = f"{selected_index + 1}/{len(videos)}"
        draw_text(counter_text, font_small, WHITE, SCREEN_WIDTH // 2, header_height + 10, center=True, bg_color=BLUE, padding=10)

    # Panel dolny
    panel_height = 80
    panel_y = SCREEN_HEIGHT - panel_height
    pygame.draw.rect(screen, DARK_GRAY, (0, panel_y, SCREEN_WIDTH, panel_height))

    # Instrukcje zależne od trybu
    if multi_select_mode:
        if selected_videos:
            draw_text("Up/Down/Left/Right: Nawigacja | OK: Zaznacz/Odznacz | Menu: Anuluj | Delete: Usun zaznaczone | Videos: Wroc",
                     font_small, YELLOW, SCREEN_WIDTH // 2, panel_y + 40, center=True)
        else:
            draw_text("Up/Down/Left/Right: Nawigacja | OK: Zaznacz/Odznacz | Menu: Anuluj | Videos: Wroc",
                     font_small, YELLOW, SCREEN_WIDTH // 2, panel_y + 40, center=True)
    else:
        if selected_videos:
            draw_text("Up/Down/Left/Right: Nawigacja | OK: Odtworz | Menu: Opcje | Delete: Usun zaznaczone | Videos: Wroc",
                     font_small, WHITE, SCREEN_WIDTH // 2, panel_y + 40, center=True)
        else:
            draw_text("Up/Down/Left/Right: Nawigacja | OK: Odtworz | Menu: Opcje | Delete: Usun | Videos: Wroc",
                     font_small, WHITE, SCREEN_WIDTH // 2, panel_y + 40, center=True)


def draw_video_context_menu():
    """Menu kontekstowe dla filmów"""
    overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    overlay.set_alpha(200)
    overlay.fill(BLACK)
    screen.blit(overlay, (0, 0))

    menu_width = 700
    menu_height = 400
    menu_x = (SCREEN_WIDTH - menu_width) // 2
    menu_y = (SCREEN_HEIGHT - menu_height) // 2

    pygame.draw.rect(screen, DARK_GRAY, (menu_x, menu_y, menu_width, menu_height), border_radius=20)
    pygame.draw.rect(screen, BLUE, (menu_x, menu_y, menu_width, menu_height), 5, border_radius=20)

    draw_text("[MENU] OPCJE", font_large, WHITE, SCREEN_WIDTH // 2, menu_y + 60, center=True)

    # Opcje menu
    menu_options = [
        {"label": "Zaznacz wiele filmow", "icon": "[SELECT]"},
        {"label": "Pokaz informacje", "icon": "[INFO]"},
    ]

    option_height = 80
    start_y = menu_y + 140

    for i, option in enumerate(menu_options):
        option_y = start_y + i * (option_height + 20)

        if i == video_context_menu_selection:
            pygame.draw.rect(screen, BLUE, (menu_x + 40, option_y, menu_width - 80, option_height), border_radius=15)
            pygame.draw.rect(screen, YELLOW, (menu_x + 40, option_y, menu_width - 80, option_height), 6, border_radius=15)
            text_color = YELLOW
        else:
            pygame.draw.rect(screen, GRAY, (menu_x + 40, option_y, menu_width - 80, option_height), border_radius=15)
            text_color = WHITE

        draw_text(f"{option['icon']} {option['label']}", font_medium, text_color,
                 SCREEN_WIDTH // 2, option_y + option_height // 2, center=True)

    draw_text("Up/Down: Wybierz | OK: Zatwierdz | Menu: Wroc", font_small, GRAY,
             SCREEN_WIDTH // 2, menu_y + menu_height - 40, center=True)


def draw_video_info_dialog():
    """Dialog z informacjami o filmie"""
    if not videos or video_info_index < 0 or video_info_index >= len(videos):
        return

    video = videos[video_info_index]

    overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    overlay.set_alpha(200)
    overlay.fill(BLACK)
    screen.blit(overlay, (0, 0))

    dialog_width = 900
    dialog_height = 700
    dialog_x = (SCREEN_WIDTH - dialog_width) // 2
    dialog_y = (SCREEN_HEIGHT - dialog_height) // 2

    pygame.draw.rect(screen, DARK_GRAY, (dialog_x, dialog_y, dialog_width, dialog_height), border_radius=20)
    pygame.draw.rect(screen, BLUE, (dialog_x, dialog_y, dialog_width, dialog_height), 5, border_radius=20)

    draw_text("[INFO] INFORMACJE O FILMIE", font_large, WHITE, SCREEN_WIDTH // 2, dialog_y + 60, center=True)

    # Miniaturka
    thumb_y = dialog_y + 120
    if video.stem in thumbnails:
        try:
            thumb_x = (SCREEN_WIDTH - 320) // 2
            screen.blit(thumbnails[video.stem], (thumb_x, thumb_y))
            pygame.draw.rect(screen, WHITE, (thumb_x, thumb_y, 320, 180), 3, border_radius=5)
        except:
            pass

    # Informacje
    info_y = thumb_y + 200
    info_spacing = 50

    # Nazwa pliku
    display_name = video.name
    if len(display_name) > 50:
        display_name = display_name[:47] + "..."
    draw_text(f"[FILE] Nazwa: {display_name}", font_small, WHITE, SCREEN_WIDTH // 2, info_y, center=True)

    # Rozmiar pliku
    size_mb = video.stat().st_size / (1024 * 1024)
    draw_text(f"[SIZE] Rozmiar: {size_mb:.2f} MB", font_small, WHITE, SCREEN_WIDTH // 2, info_y + info_spacing, center=True)

    # Data i godzina nagrania
    date_str = datetime.fromtimestamp(video.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    draw_text(f"[DATE] Data nagrania: {date_str}", font_small, WHITE, SCREEN_WIDTH // 2, info_y + info_spacing * 2, center=True)

    # Dlugosc filmu (jesli mozliwe)
    try:
        cap = cv2.VideoCapture(str(video))
        if cap.isOpened():
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = frame_count / fps if fps > 0 else 0
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            draw_text(f"[TIME] Dlugosc: {minutes}:{seconds:02d}", font_small, WHITE, SCREEN_WIDTH // 2, info_y + info_spacing * 3, center=True)

            # Format i FPS
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            draw_text(f"[VIDEO] Format: {width}x{height} @ {int(fps)} FPS", font_small, WHITE, SCREEN_WIDTH // 2, info_y + info_spacing * 4, center=True)
            cap.release()
        else:
            draw_text("[WARN] Nie mozna odczytac dlugosci", font_small, GRAY, SCREEN_WIDTH // 2, info_y + info_spacing * 3, center=True)
    except Exception as e:
        draw_text(f"[ERROR] Blad: {str(e)}", font_small, RED, SCREEN_WIDTH // 2, info_y + info_spacing * 3, center=True)

    draw_text("OK lub Menu: Zamknij", font_small, GRAY, SCREEN_WIDTH // 2, dialog_y + dialog_height - 40, center=True)


def draw_playing_screen():
    """Ekran odtwarzania"""
    global video_current_frame, video_last_frame_time, video_last_surface
    
    if not video_capture:
        screen.fill(BLACK)
        draw_text("[ERROR] Blad odtwarzania", font_large, RED, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2, center=True)
        return
    
    if not video_paused:
        current_time = time.time()
        frame_interval = 1.0 / video_fps
        
        if current_time - video_last_frame_time >= frame_interval:
            ret, frame = video_capture.read()
            
            if ret and frame is not None:
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
                video_last_frame_time = current_time
            else:
                stop_video_playback()
                return
    
    screen.fill(BLACK)
    if video_last_surface:
        try:
            frame_surface, new_w, new_h = video_last_surface
            x_offset = (SCREEN_WIDTH - new_w) // 2
            y_offset = (SCREEN_HEIGHT - new_h) // 2
            screen.blit(frame_surface, (x_offset, y_offset))
        except:
            pass
    
    panel_height = 150
    panel_y = SCREEN_HEIGHT - panel_height
    
    panel = pygame.Surface((SCREEN_WIDTH, panel_height))
    panel.set_alpha(200)
    panel.fill(BLACK)
    screen.blit(panel, (0, panel_y))
    
    if video_path_playing:
        name = video_path_playing.name
        if len(name) > 50:
            name = name[:47] + "..."
        draw_text(name, font_small, YELLOW, SCREEN_WIDTH // 2, panel_y + 20, center=True)
    
    progress_y = panel_y + 60
    progress_width = SCREEN_WIDTH - 100
    progress_x = 50
    progress_height = 15
    
    pygame.draw.rect(screen, DARK_GRAY, (progress_x, progress_y, progress_width, progress_height), border_radius=8)
    
    if video_total_frames > 0:
        progress_ratio = video_current_frame / video_total_frames
        filled_width = int(progress_width * progress_ratio)
        if filled_width > 0:
            pygame.draw.rect(screen, BLUE, (progress_x, progress_y, filled_width, progress_height), border_radius=8)
    
    pygame.draw.rect(screen, WHITE, (progress_x, progress_y, progress_width, progress_height), 2, border_radius=8)
    
    current_time_sec = video_current_frame / video_fps if video_fps > 0 else 0
    total_time_sec = video_total_frames / video_fps if video_fps > 0 else 0
    
    time_text = f"{format_time(current_time_sec)} / {format_time(total_time_sec)}"
    draw_text(time_text, font_small, WHITE, SCREEN_WIDTH // 2, progress_y + 35, center=True)
    
    fps_text = f"[VIDEO] {video_fps} FPS"
    draw_text(fps_text, font_tiny, GREEN, SCREEN_WIDTH - 150, panel_y + 20)
    
    status_text = "[PAUSE] PAUZA" if video_paused else "[PLAY] ODTWARZANIE"
    status_color = ORANGE if video_paused else GREEN
    draw_text(status_text, font_medium, status_color, SCREEN_WIDTH // 2, panel_y + 105, center=True)
    
    instructions = "OK: Pauza | Left/Right: Przewiń | Videos: Wyjdź"
    draw_text(instructions, font_tiny, GRAY, SCREEN_WIDTH // 2, 30, center=True, bg_color=BLACK, padding=8)


def draw_confirm_dialog():
    """Dialog potwierdzenia"""
    overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    overlay.set_alpha(220)
    overlay.fill(BLACK)
    screen.blit(overlay, (0, 0))

    dialog_width = 900
    dialog_height = 400
    dialog_x = (SCREEN_WIDTH - dialog_width) // 2
    dialog_y = (SCREEN_HEIGHT - dialog_height) // 2

    pygame.draw.rect(screen, DARK_GRAY, (dialog_x, dialog_y, dialog_width, dialog_height), border_radius=20)
    pygame.draw.rect(screen, RED, (dialog_x, dialog_y, dialog_width, dialog_height), 5, border_radius=20)

    draw_text("[WARN] POTWIERDZENIE", font_large, RED, SCREEN_WIDTH // 2, dialog_y + 60, center=True)

    if selected_videos:
        # Multi-delete
        draw_text(f"Usunac {len(selected_videos)} zaznaczonych filmow?", font_medium, WHITE, SCREEN_WIDTH // 2, dialog_y + 130, center=True)
        draw_text("Ta operacja jest nieodwracalna!", font_small, YELLOW, SCREEN_WIDTH // 2, dialog_y + 180, center=True)
    elif videos and 0 <= selected_index < len(videos):
        # Single delete
        video = videos[selected_index]
        draw_text("Usunac ten film?", font_medium, WHITE, SCREEN_WIDTH // 2, dialog_y + 130, center=True)

        name = video.name
        if len(name) > 40:
            name = name[:37] + "..."
        draw_text(name, font_small, YELLOW, SCREEN_WIDTH // 2, dialog_y + 180, center=True)
    
    button_y = dialog_y + 260
    button_w = 300
    button_h = 80
    spacing = 50
    
    yes_x = SCREEN_WIDTH // 2 + spacing // 2
    if confirm_selection == 1:
        pygame.draw.rect(screen, GREEN, (yes_x, button_y, button_w, button_h), border_radius=15)
        pygame.draw.rect(screen, YELLOW, (yes_x, button_y, button_w, button_h), 6, border_radius=15)
    else:
        pygame.draw.rect(screen, GREEN, (yes_x, button_y, button_w, button_h), border_radius=15)
        pygame.draw.rect(screen, WHITE, (yes_x, button_y, button_w, button_h), 2, border_radius=15)
    
    draw_text("[YES] TAK", font_large, WHITE, yes_x + button_w // 2, button_y + button_h // 2, center=True)
    
    no_x = SCREEN_WIDTH // 2 - button_w - spacing // 2
    if confirm_selection == 0:
        pygame.draw.rect(screen, RED, (no_x, button_y, button_w, button_h), border_radius=15)
        pygame.draw.rect(screen, YELLOW, (no_x, button_y, button_w, button_h), 6, border_radius=15)
    else:
        pygame.draw.rect(screen, RED, (no_x, button_y, button_w, button_h), border_radius=15)
        pygame.draw.rect(screen, WHITE, (no_x, button_y, button_w, button_h), 2, border_radius=15)
    
    draw_text("[NO] NIE", font_large, WHITE, no_x + button_w // 2, button_y + button_h // 2, center=True)
    draw_text("Left/Right: Wybierz | OK: Zatwierdz", font_small, GRAY, SCREEN_WIDTH // 2, dialog_y + dialog_height - 40, center=True)


# ============================================================================
# OBSŁUGA PRZYCISKÓW
# ============================================================================

def handle_record():
    global current_state
    if current_state == STATE_MAIN:
        if not recording:
            start_recording()
        else:
            stop_recording()


def handle_videos():
    global current_state, selected_videos, multi_select_mode
    if current_state == STATE_MAIN and not recording:
        refresh_videos()
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
    global current_state, video_context_menu_selection, multi_select_mode, selected_videos
    if current_state == STATE_MAIN and not recording:
        open_menu()
    elif current_state == STATE_MENU:
        close_menu()
    elif current_state == STATE_SUBMENU:
        close_submenu()
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
                if tile_id in ["grid", "show_date", "show_time"]:
                    key_map = {
                        "grid": "show_grid",
                        "show_date": "show_date",
                        "show_time": "show_time"
                    }
                    key = key_map[tile_id]
                    camera_settings[key] = not camera_settings.get(key, False)
                    save_config()
                    apply_camera_settings()
                    print(f"[TOGGLE] {tile['label']}: {camera_settings[key]}")

                # Cykliczne przełączanie dla select
                elif tile_id == "quality":
                    current_idx = VIDEO_RESOLUTIONS.index(camera_settings.get("video_resolution", "1080p30"))
                    new_idx = (current_idx + 1) % len(VIDEO_RESOLUTIONS)
                    camera_settings["video_resolution"] = VIDEO_RESOLUTIONS[new_idx]
                    save_config()
                    print(f"[SELECT] Rozdzielczość: {camera_settings['video_resolution']}")

                elif tile_id == "wb":
                    current_idx = WB_MODES.index(camera_settings.get("awb_mode", "auto"))
                    new_idx = (current_idx + 1) % len(WB_MODES)
                    camera_settings["awb_mode"] = WB_MODES[new_idx]
                    save_config()
                    apply_camera_settings()
                    print(f"[SELECT] White Balance: {camera_settings['awb_mode']}")

                elif tile_id == "date_position":
                    current_idx = DATE_POSITIONS.index(camera_settings.get("date_position", "top_left"))
                    new_idx = (current_idx + 1) % len(DATE_POSITIONS)
                    camera_settings["date_position"] = DATE_POSITIONS[new_idx]
                    save_config()
                    print(f"[SELECT] Pozycja daty: {camera_settings['date_position']}")

                # Dla sliderów otwórz submenu do precyzyjnej edycji
                elif tile_id in ["brightness", "contrast", "saturation", "sharpness", "exposure", "battery_level"]:
                    # Mapowanie tile_id na section
                    section_map = {
                        "brightness": "manual",
                        "contrast": "manual",
                        "saturation": "manual",
                        "sharpness": "manual",
                        "exposure": "manual",
                        "battery_level": "battery"
                    }
                    if tile_id in section_map:
                        open_submenu(section_map[tile_id])

    elif current_state == STATE_SUBMENU:
        submenu_ok()


def handle_delete():
    global current_state, confirm_selection
    if current_state == STATE_VIDEOS and videos:
        current_state = STATE_CONFIRM
        confirm_selection = 0


def handle_up():
    global video_context_menu_selection
    if current_state == STATE_VIDEOS:
        videos_navigate_up()
    elif current_state == STATE_PLAYING:
        print("[VOL] Głośność UP (TBD)")
    elif current_state == STATE_MENU:
        menu_navigate_up()
    elif current_state == STATE_SUBMENU:
        submenu_navigate_up()
    elif current_state == STATE_VIDEO_CONTEXT_MENU:
        video_context_menu_selection = max(0, video_context_menu_selection - 1)


def handle_down():
    global video_context_menu_selection
    if current_state == STATE_VIDEOS:
        videos_navigate_down()
    elif current_state == STATE_PLAYING:
        print("[VOL] Głośność DOWN (TBD)")
    elif current_state == STATE_MENU:
        menu_navigate_down()
    elif current_state == STATE_SUBMENU:
        submenu_navigate_down()
    elif current_state == STATE_VIDEO_CONTEXT_MENU:
        video_context_menu_selection = min(1, video_context_menu_selection + 1)


def handle_left():
    global confirm_selection
    if current_state == STATE_CONFIRM:
        confirm_selection = 0
    elif current_state == STATE_MENU:
        menu_navigate_left()
    elif current_state == STATE_VIDEOS:
        videos_navigate_left()


def handle_right():
    global confirm_selection
    if current_state == STATE_CONFIRM:
        confirm_selection = 1
    elif current_state == STATE_MENU:
        menu_navigate_right()
    elif current_state == STATE_VIDEOS:
        videos_navigate_right()


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
    global camera, recording, running, video_capture
    print("\n[CLEANUP] Zamykanie...")
    running = False
    
    if video_capture:
        video_capture.release()
    
    if recording:
        stop_recording()
    if camera:
        try:
            camera.stop()
            camera.close()
        except:
            pass
    
    save_config()
    
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
    
    init_pygame()
    init_camera()
    
    print("\n[GPIO] GPIO init...")
    btn_record = Button(PIN_RECORD, pull_up=True, bounce_time=0.3)
    btn_ok = Button(PIN_OK, pull_up=True, bounce_time=0.3)
    btn_videos = Button(PIN_VIDEOS, pull_up=True, bounce_time=0.3)
    btn_delete = Button(PIN_DELETE, pull_up=True, bounce_time=0.3)
    btn_up = Button(PIN_UP, pull_up=True, bounce_time=0.3)
    btn_down = Button(PIN_DOWN, pull_up=True, bounce_time=0.3)
    btn_left = Button(PIN_LEFT, pull_up=True, bounce_time=0.3)
    btn_right = Button(PIN_RIGHT, pull_up=True, bounce_time=0.3)
    btn_menu = Button(PIN_MENU, pull_up=True, bounce_time=0.3)
    btn_plus = Button(PIN_PLUS, pull_up=True, bounce_time=0.3)
    btn_minus = Button(PIN_MINUS, pull_up=True, bounce_time=0.3)
    
    btn_record.when_pressed = handle_record
    btn_ok.when_pressed = handle_ok
    btn_videos.when_pressed = handle_videos
    btn_delete.when_pressed = handle_delete
    btn_up.when_pressed = handle_up
    btn_down.when_pressed = handle_down
    btn_left.when_pressed = handle_left
    btn_right.when_pressed = handle_right
    btn_menu.when_pressed = handle_menu
    btn_plus.when_pressed = handle_zoom_in
    btn_minus.when_pressed = handle_zoom_out
    
    print("[OK] GPIO OK")
    
    print("\n" + "="*70)
    print("[SYSTEM] SYSTEM KAMERA - RASPBERRY PI 5")
    print("="*70)
    print("[MAIN] Kamera | [REC] Record | [VIDEOS] Videos | [CONFIG] Menu | [ZOOM] +/- Zoom")
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
            
            if current_state == STATE_PLAYING:
                if btn_right.is_pressed:
                    if hold_start_right is None:
                        hold_start_right = current_time
                else:
                    hold_start_right = None

                if btn_left.is_pressed:
                    if hold_start_left is None:
                        hold_start_left = current_time
                else:
                    hold_start_left = None
                
                if btn_right.is_pressed:
                    if hold_start_right is not None and current_time - hold_start_right >= 4 and current_time - hold_start_right < 10:
                        seek_video(1.0)   
                    elif hold_start_right is not None and current_time - hold_start_right >= 10:
                        seek_video(2.5)
                    else:
                        seek_video(0.5)
                    last_continuous_seek = current_time

                elif btn_left.is_pressed:
                    if hold_start_left is not None and 4 <= current_time - hold_start_left and 10 > current_time - hold_start_left:
                        seek_video(-1.0)   
                    elif hold_start_left is not None and current_time - hold_start_left >= 10:
                        seek_video(-2.5)
                    else:
                        seek_video(-0.5)
                    last_continuous_seek = current_time
            
            if current_state == STATE_MAIN:
                if btn_plus.is_pressed and current_time - last_zoom_time >= 0.05:
                    adjust_zoom(ZOOM_STEP)
                    last_zoom_time = current_time
                
                if btn_minus.is_pressed and current_time - last_zoom_time >= 0.05:
                    adjust_zoom(-ZOOM_STEP)
                    last_zoom_time = current_time
            
            if current_state == STATE_SUBMENU:
                if btn_up.is_pressed and current_time - last_menu_scroll >= MENU_SCROLL_DELAY:
                    submenu_navigate_up()
                    last_menu_scroll = current_time
                
                if btn_down.is_pressed and current_time - last_menu_scroll >= MENU_SCROLL_DELAY:
                    submenu_navigate_down()
                    last_menu_scroll = current_time
            
            if current_state == STATE_VIDEOS:
                if btn_up.is_pressed and current_time - last_videos_scroll >= VIDEOS_SCROLL_DELAY:
                    videos_navigate_up()
                    last_videos_scroll = current_time
                
                if btn_down.is_pressed and current_time - last_videos_scroll >= VIDEOS_SCROLL_DELAY:
                    videos_navigate_down()
                    last_videos_scroll = current_time
            
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
                draw_videos_screen()
                draw_confirm_dialog()
            elif current_state == STATE_PLAYING:
                draw_playing_screen()
            elif current_state == STATE_MENU:
                draw_menu_tiles(frame)
            elif current_state == STATE_SUBMENU:
                draw_submenu_screen(frame)
            elif current_state == STATE_VIDEO_CONTEXT_MENU:
                draw_videos_screen()
                draw_video_context_menu()
            elif current_state == STATE_VIDEO_INFO:
                draw_videos_screen()
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