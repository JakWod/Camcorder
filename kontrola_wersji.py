#!/usr/bin/env python3
import pygame
import sys
import os
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

# Zoom
last_zoom_time = 0
ZOOM_STEP = 0.02

# Timing
MENU_SCROLL_DELAY = 0.35
VIDEOS_SCROLL_DELAY = 0.25


# ============================================================================
# FUNKCJE POMOCNICZE FPS
# ============================================================================

def get_current_fps():
    """Pobierz aktualny FPS z ustawień kamery"""
    resolution = camera_settings.get("video_resolution", "1080p30")
    res_config = RESOLUTION_MAP.get(resolution, {"fps": 30})
    return res_config["fps"]


def extract_fps_from_filename(filename):
    """Wyciągnij FPS z nazwy pliku (np. video_20250117_143022_30fps.mp4 -> 30)"""
    match = re.search(r'_(\d+)fps', str(filename))
    if match:
        fps = int(match.group(1))
        print(f"📊 FPS z nazwy pliku: {fps}")
        return fps
    print(f"⚠️  Brak FPS w nazwie, użyję domyślnego")
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
            print("✅ Konfiguracja wczytana")
        else:
            save_config()
    except Exception as e:
        print(f"⚠️  Błąd wczytywania config: {e}")


def save_config():
    """Zapisz konfigurację"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(camera_settings, f, indent=2)
        print("✅ Konfiguracja zapisana")
    except Exception as e:
        print(f"⚠️  Błąd zapisu config: {e}")


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
    print("✅ Reset do ustawień fabrycznych")


def reset_quality_settings():
    """Reset ustawień jakości"""
    camera_settings["video_resolution"] = "1080p30"
    save_config()
    apply_camera_settings()
    print("✅ Reset ustawień jakości")


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
    print("✅ Reset ustawień manualnych")


def reset_date_settings():
    """Reset ustawień daty"""
    camera_settings["show_date"] = False
    camera_settings["show_time"] = False
    camera_settings["date_position"] = "top_left"
    camera_settings["manual_date"] = None
    save_config()
    print("✅ Reset ustawień daty")


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
        print(f"✅ Ustawienia kamery zastosowane")
        
    except Exception as e:
        print(f"⚠️  Błąd ustawiania kamery: {e}")


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
        print(f"⚠️  Błąd zoom: {e}")


def adjust_zoom(delta):
    """Zmień zoom o delta"""
    global camera_settings
    
    new_zoom = camera_settings["zoom"] + delta
    new_zoom = max(0.0, min(1.0, new_zoom))
    
    camera_settings["zoom"] = new_zoom
    apply_zoom(new_zoom)


def add_date_overlay_to_video(video_path):
    """Dodaj overlay daty do video - zachowuje FPS"""
    if not camera_settings.get("show_date", False):
        print("📅 Data wyłączona - pomijam overlay")
        return True
    
    try:
        print(f"📅 Dodawanie daty do video...")
        
        # Pobierz FPS z nazwy pliku
        original_fps = extract_fps_from_filename(video_path.name)
        
        # Jeśli nie ma w nazwie, spróbuj opencv
        if not original_fps:
            probe_cap = cv2.VideoCapture(str(video_path))
            original_fps = probe_cap.get(cv2.CAP_PROP_FPS)
            probe_cap.release()
        
        if not original_fps or original_fps <= 0 or original_fps > 120:
            original_fps = get_current_fps()
        
        print(f"🎬 Używam FPS: {original_fps}")
        
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
        
        print(f"📅 Tekst overlay: {date_text}")
        
        # ESCAPOWANIE dla ffmpeg - KLUCZOWE!
        # Dwukropki muszą być escapowane w ffmpeg
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
        
        # Filtr drawtext z prawidłowym escapowaniem
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
        
        print(f"🎬 Filtr: {drawtext_filter}")
        
        # Komenda ffmpeg - BEZ zmiany FPS (fps_mode passthrough)
        cmd = [
            "ffmpeg",
            "-i", str(video_path),
            "-vf", drawtext_filter,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-fps_mode", "passthrough",  # Nie zmieniaj FPS!
            "-c:a", "copy",
            "-y",
            str(temp_file)
        ]
        
        print(f"🎬 Przetwarzanie ffmpeg...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        
        if result.returncode != 0:
            print(f"⚠️  FFmpeg error: {result.stderr}")
            if temp_file.exists():
                temp_file.unlink()
            return False
        
        if not temp_file.exists() or temp_file.stat().st_size < 1000:
            print(f"⚠️  Plik tymczasowy nieprawidłowy")
            if temp_file.exists():
                temp_file.unlink()
            return False
        
        # Weryfikacja FPS
        verify_cap = cv2.VideoCapture(str(temp_file))
        output_fps = verify_cap.get(cv2.CAP_PROP_FPS)
        verify_cap.release()
        
        print(f"✅ FPS: {output_fps:.2f} (oczekiwano: {original_fps:.2f})")
        
        # Zamiana plików
        video_path.unlink()
        temp_file.rename(video_path)
        
        print(f"✅ Data dodana pomyślnie")
        return True
        
    except Exception as e:
        print(f"⚠️  Błąd dodawania daty: {e}")
        import traceback
        traceback.print_exc()
        if 'temp_file' in locals() and temp_file.exists():
            temp_file.unlink()
        return False


# ============================================================================
# MENU SYSTEM
# ============================================================================

def init_menu_tiles():
    """Inicjalizuj kafelki głównego menu"""
    global menu_tiles
    
    menu_tiles = [
        {
            "id": "quality",
            "title": "Image Quality/Size",
            "icon": "🎬",
            "description": "Rozdzielczość i FPS"
        },
        {
            "id": "manual",
            "title": "Manual Settings",
            "icon": "⚙️",
            "description": "Parametry kamery"
        },
        {
            "id": "date",
            "title": "Znacznik Daty",
            "icon": "📅",
            "description": "Data na filmie"
        }
    ]


def init_submenu(tile_id):
    """Inicjalizuj submenu"""
    global submenu_items, current_submenu
    
    current_submenu = tile_id
    
    if tile_id == "quality":
        submenu_items = [
            {"type": "header", "text": "🎬 IMAGE QUALITY/SIZE"},
            {"type": "spacer"},
            {"type": "select", "label": "Rozdzielczość", "key": "video_resolution", "options": VIDEO_RESOLUTIONS},
            {"type": "toggle", "label": "Siatka pomocnicza", "key": "show_grid"},
            {"type": "spacer"},
            {"type": "button", "label": "🔄 RESET USTAWIEŃ", "action": "reset_section"},
        ]
    
    elif tile_id == "manual":
        submenu_items = [
            {"type": "header", "text": "⚙️  MANUAL SETTINGS"},
            {"type": "spacer"},
            {"type": "select", "label": "White Balance", "key": "awb_mode", "options": WB_MODES},
            {"type": "slider", "label": "Jasność", "key": "brightness", "min": -1.0, "max": 1.0, "step": 0.1},
            {"type": "slider", "label": "Kontrast", "key": "contrast", "min": 0.0, "max": 2.0, "step": 0.1},
            {"type": "slider", "label": "Saturacja", "key": "saturation", "min": 0.0, "max": 2.0, "step": 0.1},
            {"type": "slider", "label": "Ostrość", "key": "sharpness", "min": 0.0, "max": 4.0, "step": 0.2},
            {"type": "slider", "label": "Ekspozycja", "key": "exposure_compensation", "min": -2.0, "max": 2.0, "step": 0.2},
            {"type": "spacer"},
            {"type": "button", "label": "🔄 RESET USTAWIEŃ", "action": "reset_section"},
        ]
    
    elif tile_id == "date":
        submenu_items = [
            {"type": "header", "text": "📅 ZNACZNIK DATY"},
            {"type": "spacer"},
            {"type": "toggle", "label": "Pokaż datę", "key": "show_date"},
            {"type": "toggle", "label": "Pokaż godzinę", "key": "show_time"},
            {"type": "select", "label": "Pozycja daty", "key": "date_position", "options": DATE_POSITIONS},
            {"type": "text", "label": "Ręczna data", "key": "manual_date", "placeholder": "YYYY-MM-DD"},
            {"type": "spacer"},
            {"type": "button", "label": "🔄 RESET USTAWIEŃ", "action": "reset_section"},
        ]


def open_menu():
    """Otwórz menu główne"""
    global current_state, selected_tile
    
    init_menu_tiles()
    selected_tile = 0
    current_state = STATE_MENU
    print("\n⚙️  MENU OTWARTE")


def open_submenu(tile_id):
    """Otwórz submenu"""
    global current_state, submenu_selected, submenu_editing
    
    init_submenu(tile_id)
    submenu_selected = 2
    submenu_editing = False
    current_state = STATE_SUBMENU
    print(f"\n📂 Submenu: {tile_id}")


def close_menu():
    """Zamknij menu"""
    global current_state, submenu_editing
    
    save_config()
    apply_camera_settings()
    submenu_editing = False
    current_state = STATE_MAIN
    print("\n📺 Ekran główny")


def close_submenu():
    """Zamknij submenu"""
    global current_state, submenu_editing
    
    save_config()
    apply_camera_settings()
    submenu_editing = False
    current_state = STATE_MENU
    print("\n⚙️  Menu główne")


def menu_navigate_left():
    """Nawigacja w lewo"""
    global selected_tile
    if current_state == STATE_MENU:
        selected_tile = max(0, selected_tile - 1)


def menu_navigate_right():
    """Nawigacja w prawo"""
    global selected_tile
    if current_state == STATE_MENU:
        selected_tile = min(len(menu_tiles) - 1, selected_tile + 1)


def menu_navigate_down():
    """Nawigacja w dół"""
    global selected_tile
    if current_state == STATE_MENU:
        selected_tile = -1


def menu_navigate_up():
    """Nawigacja w górę"""
    global selected_tile
    if current_state == STATE_MENU and selected_tile == -1:
        selected_tile = 1


def submenu_navigate_up():
    """Nawigacja w górę w submenu"""
    global submenu_selected
    
    if submenu_editing:
        item = submenu_items[submenu_selected]
        if item["type"] == "slider":
            key = item["key"]
            camera_settings[key] = min(item["max"], camera_settings[key] + item["step"])
            apply_camera_settings()
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
    global submenu_selected
    
    if submenu_editing:
        item = submenu_items[submenu_selected]
        if item["type"] == "slider":
            key = item["key"]
            camera_settings[key] = max(item["min"], camera_settings[key] - item["step"])
            apply_camera_settings()
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
    
    elif item["type"] == "toggle":
        key = item["key"]
        camera_settings[key] = not camera_settings[key]
        save_config()
    
    elif item["type"] in ["slider", "select"]:
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
    """Rysuj kafelki menu"""
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
    
    draw_text("⚙️  USTAWIENIA", font_large, YELLOW, SCREEN_WIDTH // 2, 60, center=True)
    
    tile_width = 350
    tile_height = 250
    spacing = 40
    start_x = (SCREEN_WIDTH - (tile_width * 3 + spacing * 2)) // 2
    tile_y = 180
    
    for i, tile in enumerate(menu_tiles):
        x = start_x + i * (tile_width + spacing)
        
        is_selected = (i == selected_tile)
        
        if is_selected:
            pygame.draw.rect(screen, BLUE, (x, tile_y, tile_width, tile_height), border_radius=20)
            pygame.draw.rect(screen, YELLOW, (x, tile_y, tile_width, tile_height), 6, border_radius=20)
        else:
            pygame.draw.rect(screen, DARK_GRAY, (x, tile_y, tile_width, tile_height), border_radius=20)
            pygame.draw.rect(screen, GRAY, (x, tile_y, tile_width, tile_height), 3, border_radius=20)
        
        icon_size = 100
        icon_y = tile_y + 40
        draw_text(tile["icon"], font_large, WHITE, x + tile_width // 2, icon_y, center=True)
        
        title_y = icon_y + 80
        draw_text(tile["title"], font_medium, WHITE if not is_selected else YELLOW, 
                 x + tile_width // 2, title_y, center=True)
        
        desc_y = title_y + 45
        draw_text(tile["description"], font_tiny, GRAY if not is_selected else WHITE, 
                 x + tile_width // 2, desc_y, center=True)
    
    reset_y = tile_y + tile_height + 60
    reset_width = 600
    reset_height = 80
    reset_x = (SCREEN_WIDTH - reset_width) // 2
    
    is_reset_selected = (selected_tile == -1)
    
    if is_reset_selected:
        pygame.draw.rect(screen, RED, (reset_x, reset_y, reset_width, reset_height), border_radius=15)
        pygame.draw.rect(screen, YELLOW, (reset_x, reset_y, reset_width, reset_height), 6, border_radius=15)
    else:
        pygame.draw.rect(screen, RED, (reset_x, reset_y, reset_width, reset_height), border_radius=15)
        pygame.draw.rect(screen, WHITE, (reset_x, reset_y, reset_width, reset_height), 2, border_radius=15)
    
    draw_text("🔄 RESET DO FABRYCZNYCH", font_medium, WHITE, 
             SCREEN_WIDTH // 2, reset_y + reset_height // 2, center=True)
    
    instructions = "⬅️➡️ Nawigacja | ⬇️ Reset | OK: Wybierz | MENU: Zamknij"
    draw_text(instructions, font_small, WHITE, SCREEN_WIDTH // 2, SCREEN_HEIGHT - 30, 
             center=True, bg_color=BLACK, padding=10)


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
            toggle_text = "✓ TAK" if value else "✗ NIE"
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
        instructions = "⬆️⬇️ : Zmień | OK: Zatwierdź | MENU: Anuluj"
    else:
        instructions = "⬆️⬇️ : Nawigacja | OK: Wybierz | MENU: Wróć"
    
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


def draw_battery_icon():
    """Rysuj ikonę baterii z outline i oddzielnymi segmentami"""
    battery_x = SCREEN_WIDTH - 100
    battery_y = 20
    battery_width = 60
    battery_height = 28
    
    # Obrys baterii (czarny, cienki)
    pygame.draw.rect(screen, BLACK, 
                    (battery_x - 2, battery_y - 2, battery_width + 4, battery_height + 4), 
                    border_radius=4)
    
    # Rama baterii (biała)
    pygame.draw.rect(screen, WHITE, 
                    (battery_x, battery_y, battery_width, battery_height), 
                    3, border_radius=4)
    
    # Końcówka baterii
    tip_x = battery_x + battery_width
    tip_y = battery_y + 8
    tip_width = 6
    tip_height = 12
    
    # Obrys końcówki
    pygame.draw.rect(screen, BLACK, (tip_x - 1, tip_y - 1, tip_width + 2, tip_height + 2))
    pygame.draw.rect(screen, WHITE, (tip_x, tip_y, tip_width, tip_height))
    
    # 4 segmenty baterii jako osobne obiekty
    segment_width = 8
    segment_height = battery_height - 10
    segment_spacing = 2
    segment_x_start = battery_x + 6
    segment_y = battery_y + 5
    
    # Kąt nachylenia
    angle = 30
    top_offset = segment_height * math.tan(math.radians(angle)) / 2
    
    # Rysuj 4 segmenty
    for i in range(4):
        segment_x = segment_x_start + i * (segment_width + segment_spacing)
        
        # Punkty dla równoległoboku
        points = [
            (segment_x + top_offset, segment_y),
            (segment_x + segment_width + top_offset, segment_y),
            (segment_x + segment_width - top_offset, segment_y + segment_height),
            (segment_x - top_offset, segment_y + segment_height)
        ]
        
        # Czarny outline dla każdego segmentu
        outline_points = [
            (points[0][0] - 1, points[0][1] - 1),
            (points[1][0] + 1, points[1][1] - 1),
            (points[2][0] + 1, points[2][1] + 1),
            (points[3][0] - 1, points[3][1] + 1)
        ]
        pygame.draw.polygon(screen, BLACK, outline_points)
        
        # Biały segment
        pygame.draw.polygon(screen, WHITE, points)


def draw_zoom_bar():
    """Rysuj pasek zoom W/T"""
    bar_width = 300
    bar_height = 30
    bar_x = (SCREEN_WIDTH - bar_width) // 2
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
    """Rysuj wskaźnik nagrywania"""
    if not recording or not recording_start_time:
        return
    
    elapsed_time = time.time() - recording_start_time
    hours = int(elapsed_time // 3600)
    minutes = int((elapsed_time % 3600) // 60)
    seconds = int(elapsed_time % 60)
    milliseconds = int((elapsed_time % 1) * 100)
    time_text = f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:02d}"
    
    rec_x = 30
    rec_y = 30
    
    if int(pygame.time.get_ticks() / 500) % 2:
        pygame.draw.circle(screen, RED, (rec_x + 10, rec_y + 15), 8)
    
    draw_text_with_outline("REC", font_medium, RED, BLACK, rec_x + 30, rec_y)
    draw_text_with_outline(time_text, font_medium, RED, BLACK, rec_x + 95, rec_y)


def generate_thumbnail(video_path, max_retries=3):
    """Generuj miniaturkę"""
    thumbnail_path = THUMBNAIL_DIR / f"{video_path.stem}.jpg"
    
    for attempt in range(max_retries):
        try:
            print(f"🖼️  Miniatura: {video_path.name} (próba {attempt + 1}/{max_retries})")
            
            if not video_path.exists():
                print(f"⚠️  Plik nie istnieje")
                time.sleep(1)
                continue
            
            file_size = video_path.stat().st_size
            if file_size < 10000:
                print(f"⚠️  Plik za mały: {file_size} B")
                time.sleep(1)
                continue
            
            cap = cv2.VideoCapture(str(video_path))
            
            if not cap.isOpened():
                print(f"⚠️  Nie można otworzyć")
                cap.release()
                time.sleep(1)
                continue
            
            ret, frame = cap.read()
            cap.release()
            
            if not ret or frame is None:
                print(f"⚠️  Nie można pobrać klatki")
                time.sleep(1)
                continue
            
            if frame.shape[0] < 10 or frame.shape[1] < 10:
                print(f"⚠️  Klatka zbyt mała")
                time.sleep(1)
                continue
            
            frame_resized = cv2.resize(frame, (320, 180))
            success = cv2.imwrite(str(thumbnail_path), frame_resized)
            
            if not success:
                print(f"⚠️  Nie można zapisać")
                time.sleep(1)
                continue
            
            if thumbnail_path.exists() and thumbnail_path.stat().st_size > 1000:
                print(f"✅ Miniatura OK")
                return True
            else:
                print(f"⚠️  Miniatura nieprawidłowa")
                if thumbnail_path.exists():
                    thumbnail_path.unlink()
                time.sleep(1)
                continue
                
        except Exception as e:
            print(f"⚠️  Błąd (próba {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
            continue
    
    print(f"❌ Nie udało się po {max_retries} próbach")
    return False


def refresh_videos():
    """Odśwież listę filmów"""
    global videos, selected_index, thumbnails
    
    old_selected = videos[selected_index] if videos and 0 <= selected_index < len(videos) else None
    
    videos = sorted(VIDEO_DIR.glob("*.mp4"), reverse=True)
    
    if old_selected and old_selected in videos:
        selected_index = videos.index(old_selected)
    else:
        selected_index = min(selected_index, max(0, len(videos) - 1))
    
    print("🖼️  Ładowanie miniatur...")
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
                print(f"⚠️  Błąd {video.stem}: {e}")
    print(f"✅ {len(thumbnails)} miniatur")


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
    """Rysuj overlay daty na podglądzie na żywo (NIE na nagraniu)"""
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
    """Nawigacja w górę"""
    global selected_index
    if videos:
        selected_index = max(0, selected_index - 1)


def videos_navigate_down():
    """Nawigacja w dół"""
    global selected_index
    if videos:
        selected_index = min(len(videos) - 1, selected_index + 1)


# ============================================================================
# INICJALIZACJA
# ============================================================================

def init_pygame():
    """Inicjalizuj pygame"""
    global screen, font_large, font_medium, font_small, font_tiny, SCREEN_WIDTH, SCREEN_HEIGHT
    
    print("🔄 Pygame init...")
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
    
    print("✅ Pygame OK")


def init_camera():
    """Inicjalizuj kamerę"""
    global camera
    print("🔄 Kamera init...")
    
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
    
    print(f"✅ Kamera OK: {resolution}")


# ============================================================================
# NAGRYWANIE - Z FPS W NAZWIE PLIKU!
# ============================================================================

def start_recording():
    """Start nagrywania - FPS w nazwie pliku"""
    global recording, current_file, encoder, recording_start_time, current_recording_fps
    
    if not recording:
        current_recording_fps = get_current_fps()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # ⚠️ KLUCZOWE: FPS w nazwie pliku!
        current_file = VIDEO_DIR / f"video_{timestamp}_{current_recording_fps}fps.mp4"
        
        print(f"🔴 START: {current_file.name}")
        print(f"🎬 FPS: {current_recording_fps}")
        
        try:
            encoder = H264Encoder(bitrate=10000000, framerate=current_recording_fps)
            output = FfmpegOutput(str(current_file))
            camera.start_encoder(encoder, output)
            recording = True
            recording_start_time = time.time()
            print(f"✅ Nagrywanie @ {current_recording_fps} FPS")
        except Exception as e:
            print(f"❌ Błąd start: {e}")
            recording = False
            current_file = None
            current_recording_fps = None
            recording_start_time = None


def stop_recording():
    """Stop nagrywania"""
    global recording, current_file, encoder, recording_start_time, current_recording_fps
    
    if recording:
        print("⏹️  STOP...")
        recording = False
        saved_file = current_file
        saved_fps = current_recording_fps
        
        try:
            camera.stop_encoder()
            print("✅ Encoder zatrzymany")
            
            time.sleep(1.5)
            
            if saved_file and saved_file.exists():
                size = saved_file.stat().st_size / (1024*1024)
                
                if size < 0.1:
                    print(f"⚠️  Plik zbyt mały ({size:.1f} MB)")
                else:
                    print(f"✅ Zapisano: {size:.1f} MB @ {saved_fps} FPS")
                    
                    # Weryfikacja FPS
                    verify_cap = cv2.VideoCapture(str(saved_file))
                    recorded_fps = verify_cap.get(cv2.CAP_PROP_FPS)
                    verify_cap.release()
                    print(f"📊 OpenCV wykrył FPS: {recorded_fps:.2f}")
                    
                    print("🖼️  Generowanie miniatury...")
                    generate_thumbnail(saved_file)
                    
                    if camera_settings.get("show_date", False):
                        def process_video():
                            print("📅 Dodawanie daty...")
                            add_date_overlay_to_video(saved_file)
                            print("✅ Przetwarzanie zakończone")
                        
                        thread = threading.Thread(target=process_video, daemon=True)
                        thread.start()
                    else:
                        print("✅ Przetwarzanie zakończone")
            else:
                print(f"❌ Plik nie istnieje")
                
        except Exception as e:
            print(f"❌ Błąd: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            encoder = None
            current_file = None
            current_recording_fps = None
            recording_start_time = None


# ============================================================================
# ODTWARZANIE - UŻYWA FPS Z NAZWY PLIKU!
# ============================================================================

def start_video_playback(video_path):
    """Rozpocznij odtwarzanie - FPS z nazwy pliku"""
    global video_capture, video_current_frame, video_total_frames, video_fps
    global video_path_playing, video_paused, current_state, video_last_frame_time, video_last_surface
    
    print(f"\n▶️  ODTWARZANIE: {video_path.name}")
    
    video_capture = cv2.VideoCapture(str(video_path))
    if not video_capture.isOpened():
        print("❌ Nie można otworzyć")
        return False
    
    # ⚠️ KLUCZOWE: Najpierw spróbuj FPS z nazwy pliku!
    video_fps = extract_fps_from_filename(video_path.name)
    
    # Jeśli nie ma w nazwie, użyj OpenCV
    if not video_fps:
        video_fps = video_capture.get(cv2.CAP_PROP_FPS)
        print(f"📊 OpenCV FPS: {video_fps}")
    
    if video_fps <= 0 or video_fps > 120:
        video_fps = 30
        print(f"⚠️  FPS nieprawidłowy, użyto 30")
    
    print(f"✅ UŻYWAM FPS: {video_fps}")
    
    video_total_frames = int(video_capture.get(cv2.CAP_PROP_FRAME_COUNT))
    video_current_frame = 0
    video_paused = False
    video_path_playing = video_path
    video_last_frame_time = time.time()
    video_last_surface = None
    
    current_state = STATE_PLAYING
    print(f"✅ Wideo: {video_total_frames} klatek @ {video_fps} FPS")
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
    print("⏹️  Zatrzymano")


def toggle_pause():
    """Przełącz pauzę"""
    global video_paused, video_last_frame_time
    video_paused = not video_paused
    if not video_paused:
        video_last_frame_time = time.time()
    print(f"{'⏸️  Pauza' if video_paused else '▶️  Wznowiono'}")


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
        print(f"❌ Błąd seek: {e}")
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
            draw_text("📹 Kamera", font_large, WHITE, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2, center=True)
    
    draw_grid_overlay()
    draw_date_overlay()
    draw_battery_icon()
    draw_zoom_bar()
    
    if recording:
        draw_recording_indicator()
    
    draw_text("Record: START/STOP | Videos: Menu | Menu: Ustawienia | +/-: Zoom", 
             font_tiny, WHITE, SCREEN_WIDTH // 2, SCREEN_HEIGHT - 30, center=True, bg_color=BLACK, padding=8)


def draw_videos_screen():
    """Ekran listy filmów"""
    screen.fill(BLACK)
    
    header_height = 100
    pygame.draw.rect(screen, DARK_GRAY, (0, 0, SCREEN_WIDTH, header_height))
    draw_text("📹 NAGRANE FILMY", font_large, WHITE, SCREEN_WIDTH // 2, 50, center=True)
    
    if not videos:
        draw_text("📭 Brak filmów", font_medium, GRAY, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 60, center=True)
        draw_text("Zamknij i naciśnij Record", font_small, DARK_GRAY, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2, center=True)
    else:
        y_offset = header_height + 30
        row_height = 200
        visible_count = (SCREEN_HEIGHT - header_height - 150) // row_height
        
        start_idx = max(0, selected_index - visible_count // 2)
        end_idx = min(len(videos), start_idx + visible_count)
        
        for i in range(start_idx, end_idx):
            video = videos[i]
            
            if i == selected_index:
                pygame.draw.rect(screen, BLUE, (30, y_offset - 10, SCREEN_WIDTH - 60, row_height - 20), border_radius=15)
                prefix = "👉 "
                name_color = YELLOW
                info_color = WHITE
            else:
                pygame.draw.rect(screen, DARK_GRAY, (30, y_offset - 10, SCREEN_WIDTH - 60, row_height - 20), border_radius=15)
                prefix = "   "
                name_color = WHITE
                info_color = GRAY
            
            thumb_x, thumb_y = 50, y_offset + 10
            
            if video.stem in thumbnails:
                try:
                    screen.blit(thumbnails[video.stem], (thumb_x, thumb_y))
                except:
                    pygame.draw.rect(screen, GRAY, (thumb_x, thumb_y, 320, 180), border_radius=5)
                    draw_text("📹", font_large, WHITE, thumb_x + 160, thumb_y + 90, center=True)
            else:
                pygame.draw.rect(screen, GRAY, (thumb_x, thumb_y, 320, 180), border_radius=5)
                draw_text("📹", font_large, WHITE, thumb_x + 160, thumb_y + 90, center=True)
            
            pygame.draw.rect(screen, WHITE if i == selected_index else DARK_GRAY, 
                           (thumb_x, thumb_y, 320, 180), 3, border_radius=5)
            
            info_x = thumb_x + 340
            
            draw_text(f"#{i + 1}", font_small, info_color, info_x, y_offset + 10)
            
            display_name = video.name
            if len(display_name) > 35:
                display_name = display_name[:32] + "..."
            draw_text(f"{prefix}{display_name}", font_medium, name_color, info_x, y_offset + 45)
            
            size = video.stat().st_size / (1024*1024)
            date_str = datetime.fromtimestamp(video.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            
            draw_text(f"📊 {size:.1f} MB", font_tiny, info_color, info_x, y_offset + 90)
            draw_text(f"📅 {date_str}", font_tiny, info_color, info_x, y_offset + 120)
            
            # Pokazuj FPS z nazwy pliku
            fps_from_name = extract_fps_from_filename(video.name)
            if fps_from_name:
                draw_text(f"🎬 {fps_from_name} FPS", font_tiny, GREEN if i == selected_index else GRAY, 
                         info_x, y_offset + 150)
            
            y_offset += row_height
        
        if len(videos) > visible_count:
            pos_text = f"{selected_index + 1}/{len(videos)}"
            draw_text(pos_text, font_small, WHITE, SCREEN_WIDTH - 150, header_height + 30, center=True, bg_color=BLUE, padding=10)
    
    panel_height = 80
    panel_y = SCREEN_HEIGHT - panel_height
    pygame.draw.rect(screen, DARK_GRAY, (0, panel_y, SCREEN_WIDTH, panel_height))
    
    draw_text("⬆️⬇️ Nawigacja | OK: Odtwórz | Delete: Usuń | Videos: Wróć", 
             font_small, WHITE, SCREEN_WIDTH // 2, panel_y + 40, center=True)


def draw_playing_screen():
    """Ekran odtwarzania"""
    global video_current_frame, video_last_frame_time, video_last_surface
    
    if not video_capture:
        screen.fill(BLACK)
        draw_text("❌ Błąd odtwarzania", font_large, RED, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2, center=True)
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
                    print(f"⚠️  Błąd klatki: {e}")
                
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
    
    # Pokazuj FPS odtwarzania
    fps_text = f"🎬 {video_fps} FPS"
    draw_text(fps_text, font_tiny, GREEN, SCREEN_WIDTH - 150, panel_y + 20)
    
    status_text = "⏸️  PAUZA" if video_paused else "▶️  ODTWARZANIE"
    status_color = ORANGE if video_paused else GREEN
    draw_text(status_text, font_medium, status_color, SCREEN_WIDTH // 2, panel_y + 105, center=True)
    
    instructions = "OK: Pauza | ⬅️ ➡️ : Przewiń | Videos: Wyjdź"
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
    
    draw_text("⚠️  POTWIERDZENIE", font_large, RED, SCREEN_WIDTH // 2, dialog_y + 60, center=True)
    
    if videos and 0 <= selected_index < len(videos):
        video = videos[selected_index]
        draw_text("Usunąć ten film?", font_medium, WHITE, SCREEN_WIDTH // 2, dialog_y + 130, center=True)
        
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
    
    draw_text("✓ TAK", font_large, WHITE, yes_x + button_w // 2, button_y + button_h // 2, center=True)
    
    no_x = SCREEN_WIDTH // 2 - button_w - spacing // 2
    if confirm_selection == 0:
        pygame.draw.rect(screen, RED, (no_x, button_y, button_w, button_h), border_radius=15)
        pygame.draw.rect(screen, YELLOW, (no_x, button_y, button_w, button_h), 6, border_radius=15)
    else:
        pygame.draw.rect(screen, RED, (no_x, button_y, button_w, button_h), border_radius=15)
        pygame.draw.rect(screen, WHITE, (no_x, button_y, button_w, button_h), 2, border_radius=15)
    
    draw_text("✗ NIE", font_large, WHITE, no_x + button_w // 2, button_y + button_h // 2, center=True)
    draw_text("⬅️ ➡️  Wybierz | OK: Zatwierdź", font_small, GRAY, SCREEN_WIDTH // 2, dialog_y + dialog_height - 40, center=True)


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
    global current_state
    if current_state == STATE_MAIN and not recording:
        refresh_videos()
        current_state = STATE_VIDEOS
        print("\n📹 Menu Videos")
    elif current_state == STATE_VIDEOS:
        current_state = STATE_MAIN
        print("\n📺 Ekran główny")
    elif current_state == STATE_PLAYING:
        stop_video_playback()
    elif current_state == STATE_CONFIRM:
        current_state = STATE_VIDEOS


def handle_menu():
    global current_state
    if current_state == STATE_MAIN and not recording:
        open_menu()
    elif current_state == STATE_MENU:
        close_menu()
    elif current_state == STATE_SUBMENU:
        close_submenu()


def handle_ok():
    global current_state, confirm_selection, selected_index, selected_tile
    
    if current_state == STATE_VIDEOS:
        if videos and 0 <= selected_index < len(videos):
            start_video_playback(videos[selected_index])
    
    elif current_state == STATE_PLAYING:
        toggle_pause()
    
    elif current_state == STATE_CONFIRM:
        if confirm_selection == 1:
            if videos and 0 <= selected_index < len(videos):
                video = videos[selected_index]
                video.unlink()
                thumb = THUMBNAIL_DIR / f"{video.stem}.jpg"
                if thumb.exists():
                    thumb.unlink()
                print(f"🗑 Usunięto: {video.name}")
                refresh_videos()
        current_state = STATE_VIDEOS
        confirm_selection = 0
    
    elif current_state == STATE_MENU:
        if selected_tile == -1:
            reset_to_factory()
        elif 0 <= selected_tile < len(menu_tiles):
            open_submenu(menu_tiles[selected_tile]["id"])
    
    elif current_state == STATE_SUBMENU:
        submenu_ok()


def handle_delete():
    global current_state, confirm_selection
    if current_state == STATE_VIDEOS and videos:
        current_state = STATE_CONFIRM
        confirm_selection = 0


def handle_up():
    if current_state == STATE_VIDEOS:
        videos_navigate_up()
    elif current_state == STATE_PLAYING:
        print("🔊 Głośność UP (TBD)")
    elif current_state == STATE_MENU:
        menu_navigate_up()
    elif current_state == STATE_SUBMENU:
        submenu_navigate_up()


def handle_down():
    if current_state == STATE_VIDEOS:
        videos_navigate_down()
    elif current_state == STATE_PLAYING:
        print("🔉 Głośność DOWN (TBD)")
    elif current_state == STATE_MENU:
        menu_navigate_down()
    elif current_state == STATE_SUBMENU:
        submenu_navigate_down()


def handle_left():
    global confirm_selection
    if current_state == STATE_CONFIRM:
        confirm_selection = 0
    elif current_state == STATE_MENU:
        menu_navigate_left()


def handle_right():
    global confirm_selection
    if current_state == STATE_CONFIRM:
        confirm_selection = 1
    elif current_state == STATE_MENU:
        menu_navigate_right()


def handle_zoom_in():
    if current_state == STATE_MAIN:
        adjust_zoom(ZOOM_STEP)


def handle_zoom_out():
    if current_state == STATE_MAIN:
        adjust_zoom(-ZOOM_STEP)


def cleanup(signum=None, frame=None):
    """Zamknięcie"""
    global camera, recording, running, video_capture
    print("\nZamykanie...")
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
    
    print("\nGPIO init...")
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
    
    print("✅ GPIO OK")
    
    print("\n" + "="*70)
    print("🎬 SYSTEM KAMERA - RASPBERRY PI 5")
    print("="*70)
    print("📺 Kamera | 🔴 Record | 📹 Videos | ⚙️  Menu | 🔍 +/- Zoom")
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
            
            pygame.display.flip()
            clock.tick(30)
    
    except KeyboardInterrupt:
        cleanup()
    except Exception as e:
        print(f"\n❌ Błąd: {e}")
        import traceback
        traceback.print_exc()
        cleanup()
    
    cleanup()