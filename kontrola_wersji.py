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

# ============================================================================
# KONFIGURACJA
# ============================================================================

VIDEO_DIR = Path("/home/pi/camera_project")
VIDEO_DIR.mkdir(exist_ok=True)
THUMBNAIL_DIR = VIDEO_DIR / "thumbnails"
THUMBNAIL_DIR.mkdir(exist_ok=True)

# GPIO Pins
PIN_RECORD = 17
PIN_OK = 22
PIN_VIDEOS = 23
PIN_DELETE = 24
PIN_UP = 5
PIN_DOWN = 6
PIN_LEFT = 13
PIN_RIGHT = 19

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

# Stany
STATE_MAIN = 0
STATE_VIDEOS = 1
STATE_CONFIRM = 2
STATE_PLAYING = 3

# Globalne zmienne
camera = None
recording = False
current_file = None
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
video_last_surface = None  # Przechowuj ostatnią klatkę

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


# ============================================================================
# FUNKCJE POMOCNICZE
# ============================================================================

def generate_thumbnail(video_path):
    """Generuj miniaturkę"""
    try:
        print(f"🖼️  Miniatura: {video_path.name}")
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return False
        ret, frame = cap.read()
        if ret and frame is not None:
            thumbnail_path = THUMBNAIL_DIR / f"{video_path.stem}.jpg"
            frame_resized = cv2.resize(frame, (320, 180))
            cv2.imwrite(str(thumbnail_path), frame_resized)
            print(f"✅ Miniatura OK")
        cap.release()
        return ret
    except Exception as e:
        print(f"❌ Błąd miniatury: {e}")
        return False


def refresh_videos():
    """Odśwież listę filmów"""
    global videos, selected_index, thumbnails
    
    old_selected = videos[selected_index] if videos and 0 <= selected_index < len(videos) else None
    
    videos = sorted(VIDEO_DIR.glob("*.mp4"), reverse=True)
    
    # Zachowaj focus
    if old_selected and old_selected in videos:
        selected_index = videos.index(old_selected)
    else:
        selected_index = min(selected_index, max(0, len(videos) - 1))
    
    # Załaduj miniatury
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


def format_time(seconds):
    """Formatuj czas na MM:SS"""
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"


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
    camera = Picamera2()
    config = camera.create_video_configuration(
        main={"size": (1920, 1080), "format": "RGB888"},
        controls={"FrameRate": 30}
    )
    camera.configure(config)
    camera.start()
    print("✅ Kamera OK")


# ============================================================================
# NAGRYWANIE
# ============================================================================

def start_recording():
    """Start nagrywania"""
    global recording, current_file, encoder
    
    if not recording:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        current_file = VIDEO_DIR / f"video_{timestamp}.mp4"
        
        print(f"🔴 START: {current_file.name}")
        
        encoder = H264Encoder(bitrate=10000000)
        output = FfmpegOutput(str(current_file))
        camera.start_encoder(encoder, output)
        recording = True


def stop_recording():
    """Stop nagrywania"""
    global recording, current_file
    
    if recording:
        print("⏹️  STOP")
        camera.stop_encoder()
        recording = False
        
        if current_file and current_file.exists():
            size = current_file.stat().st_size / (1024*1024)
            print(f"✅ Zapisano: {size:.1f} MB")
            time.sleep(0.5)
            generate_thumbnail(current_file)


# ============================================================================
# ODTWARZANIE WIDEO
# ============================================================================

def start_video_playback(video_path):
    """Rozpocznij odtwarzanie wideo"""
    global video_capture, video_current_frame, video_total_frames, video_fps
    global video_path_playing, video_paused, current_state, video_last_frame_time, video_last_surface
    
    print(f"\n▶️  ODTWARZANIE: {video_path.name}")
    
    video_capture = cv2.VideoCapture(str(video_path))
    if not video_capture.isOpened():
        print("❌ Nie można otworzyć wideo")
        return False
    
    video_fps = video_capture.get(cv2.CAP_PROP_FPS)
    if video_fps <= 0:
        video_fps = 30
    
    video_total_frames = int(video_capture.get(cv2.CAP_PROP_FRAME_COUNT))
    video_current_frame = 0
    video_paused = False
    video_path_playing = video_path
    video_last_frame_time = time.time()
    video_last_surface = None  # Reset ostatniej klatki
    
    current_state = STATE_PLAYING
    print(f"✅ Wideo gotowe: {video_total_frames} klatek @ {video_fps:.1f} FPS")
    return True


def stop_video_playback():
    """Zatrzymaj odtwarzanie wideo"""
    global video_capture, current_state, video_path_playing, video_last_surface
    
    if video_capture:
        video_capture.release()
        video_capture = None
    
    video_path_playing = None
    video_last_surface = None
    current_state = STATE_VIDEOS
    print("⏹️  Zatrzymano odtwarzanie")


def toggle_pause():
    """Przełącz pauzę"""
    global video_paused, video_last_frame_time
    video_paused = not video_paused
    if not video_paused:
        video_last_frame_time = time.time()
    print(f"{'⏸️  Pauza' if video_paused else '▶️  Wznowiono'}")

#wodyk
def seek_video(seconds):
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
        # --- KLUCZ: używamy seek zamiast resetowania pliku ---
        video_capture.set(cv2.CAP_PROP_POS_FRAMES, target_frame)

        ret, frame = video_capture.read()
        if not ret or frame is None:
            return

        # zapamiętaj nową pozycję
        video_current_frame = target_frame + 1

        # konwersja na surface
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
        print("seek error:", e)
        video_paused = was_paused

        
    except Exception as e:
        print(f"❌ Błąd seek: {e}")
        video_paused = was_paused
        
    except subprocess.TimeoutExpired:
        print("❌ FFmpeg timeout")
        video_paused = was_paused
        stop_video_playback()
    except Exception as e:
        print(f"❌ Błąd przewijania: {e}")
        import traceback
        traceback.print_exc()
        video_paused = was_paused
        stop_video_playback()


# ============================================================================
# RYSOWANIE EKRANÓW
# ============================================================================

def draw_main_screen(frame):
    """Ekran główny - podgląd kamery"""
    screen.fill(BLACK)
    
    if frame is not None:
        try:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_resized = cv2.resize(frame_rgb, (SCREEN_WIDTH, SCREEN_HEIGHT))
            frame_surface = pygame.surfarray.make_surface(np.transpose(frame_resized, (1, 0, 2)))
            screen.blit(frame_surface, (0, 0))
        except:
            draw_text("📹 Kamera", font_large, WHITE, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2, center=True)
    
    # Panel statusu
    panel_height = 120
    panel_y = SCREEN_HEIGHT - panel_height
    
    panel = pygame.Surface((SCREEN_WIDTH, panel_height))
    panel.set_alpha(180)
    panel.fill(BLACK)
    screen.blit(panel, (0, panel_y))
    
    if recording:
        if int(pygame.time.get_ticks() / 500) % 2:
            status_text = "🔴 NAGRYWANIE"
            status_color = RED
        else:
            status_text = "⚫ NAGRYWANIE"
            status_color = ORANGE
        
        if current_file:
            draw_text(current_file.name, font_small, YELLOW, SCREEN_WIDTH // 2, panel_y + 30, center=True)
    else:
        status_text = "⚪ GOTOWY"
        status_color = GREEN
        draw_text("Naciśnij Record", font_small, GRAY, SCREEN_WIDTH // 2, panel_y + 30, center=True)
    
    draw_text(status_text, font_large, status_color, SCREEN_WIDTH // 2, panel_y + 70, center=True)
    draw_text("Record: START/STOP | Videos: Menu", font_tiny, WHITE, SCREEN_WIDTH // 2, 30, center=True, bg_color=BLACK, padding=8)


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
            
            # Miniatura
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
            
            # Info
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
            
            try:
                cap = cv2.VideoCapture(str(video))
                fps = cap.get(cv2.CAP_PROP_FPS)
                frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                if fps > 0:
                    duration = frame_count / fps
                    minutes = int(duration // 60)
                    seconds = int(duration % 60)
                    draw_text(f"⏱️  {minutes}:{seconds:02d}", font_tiny, info_color, info_x, y_offset + 150)
                cap.release()
            except:
                pass
            
            y_offset += row_height
        
        if len(videos) > visible_count:
            pos_text = f"{selected_index + 1}/{len(videos)}"
            draw_text(pos_text, font_small, WHITE, SCREEN_WIDTH - 150, header_height + 30, center=True, bg_color=BLUE, padding=10)
    
    # Panel
    panel_height = 80
    panel_y = SCREEN_HEIGHT - panel_height
    pygame.draw.rect(screen, DARK_GRAY, (0, panel_y, SCREEN_WIDTH, panel_height))
    
    draw_text("⬆️⬇️ Nawigacja | OK: Odtwórz | Delete: Usuń | Videos: Wróć", 
             font_small, WHITE, SCREEN_WIDTH // 2, panel_y + 40, center=True)


def draw_playing_screen():
    """Ekran odtwarzania wideo z kontrolkami"""
    global video_current_frame, video_last_frame_time, video_last_surface
    
    if not video_capture:
        screen.fill(BLACK)
        draw_text("❌ Błąd odtwarzania", font_large, RED, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2, center=True)
        return
    
    # Odtwórz kolejną klatkę (jeśli nie pauza)
    frame_updated = False
    if not video_paused:
        current_time = time.time()
        frame_interval = 1.0 / video_fps
        
        if current_time - video_last_frame_time >= frame_interval:
            ret, frame = video_capture.read()
            
            if ret and frame is not None:
                # Wyświetl klatkę
                try:
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    
                    # Zachowaj proporcje
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
                    
                    # Zapisz powierzchnię i offset dla późniejszego użycia
                    video_last_surface = (frame_surface, new_w, new_h)
                    frame_updated = True
                    
                except Exception as e:
                    print(f"⚠️  Błąd rysowania klatki: {e}")
                
                video_current_frame += 1
                video_last_frame_time = current_time
            else:
                # Koniec wideo
                stop_video_playback()
                return
    
    # Wyświetl ostatnią klatkę (nową lub z cache)
    screen.fill(BLACK)
    if video_last_surface:
        try:
            frame_surface, new_w, new_h = video_last_surface
            x_offset = (SCREEN_WIDTH - new_w) // 2
            y_offset = (SCREEN_HEIGHT - new_h) // 2
            screen.blit(frame_surface, (x_offset, y_offset))
        except:
            pass
    
    # Panel kontrolny na dole
    panel_height = 150
    panel_y = SCREEN_HEIGHT - panel_height
    
    panel = pygame.Surface((SCREEN_WIDTH, panel_height))
    panel.set_alpha(200)
    panel.fill(BLACK)
    screen.blit(panel, (0, panel_y))
    
    # Nazwa pliku
    if video_path_playing:
        name = video_path_playing.name
        if len(name) > 50:
            name = name[:47] + "..."
        draw_text(name, font_small, YELLOW, SCREEN_WIDTH // 2, panel_y + 20, center=True)
    
    # Pasek postępu
    progress_y = panel_y + 60
    progress_width = SCREEN_WIDTH - 100
    progress_x = 50
    progress_height = 15
    
    # Tło paska
    pygame.draw.rect(screen, DARK_GRAY, (progress_x, progress_y, progress_width, progress_height), border_radius=8)
    
    # Postęp
    if video_total_frames > 0:
        progress_ratio = video_current_frame / video_total_frames
        filled_width = int(progress_width * progress_ratio)
        if filled_width > 0:
            pygame.draw.rect(screen, BLUE, (progress_x, progress_y, filled_width, progress_height), border_radius=8)
    
    # Obramowanie
    pygame.draw.rect(screen, WHITE, (progress_x, progress_y, progress_width, progress_height), 2, border_radius=8)
    
    # Czasy
    current_time_sec = video_current_frame / video_fps if video_fps > 0 else 0
    total_time_sec = video_total_frames / video_fps if video_fps > 0 else 0
    
    time_text = f"{format_time(current_time_sec)} / {format_time(total_time_sec)}"
    draw_text(time_text, font_small, WHITE, SCREEN_WIDTH // 2, progress_y + 35, center=True)
    
    # Status (pauza/odtwarzanie)
    status_text = "⏸️  PAUZA" if video_paused else "▶️  ODTWARZANIE"
    status_color = ORANGE if video_paused else GREEN
    draw_text(status_text, font_medium, status_color, SCREEN_WIDTH // 2, panel_y + 105, center=True)
    
    # Instrukcje
    instructions = "OK: Pauza | ⬅️ ➡️ : ±5s | Videos: Wyjdź"
    draw_text(instructions, font_tiny, GRAY, SCREEN_WIDTH // 2, 30, center=True, bg_color=BLACK, padding=8)


def draw_confirm_dialog():
    """Dialog potwierdzenia usunięcia"""
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
    
    # TAK
    yes_x = SCREEN_WIDTH // 2 + spacing // 2
    if confirm_selection == 1:
        pygame.draw.rect(screen, GREEN, (yes_x, button_y, button_w, button_h), border_radius=15)
        pygame.draw.rect(screen, YELLOW, (yes_x, button_y, button_w, button_h), 6, border_radius=15)
    else:
        pygame.draw.rect(screen, GREEN, (yes_x, button_y, button_w, button_h), border_radius=15)
        pygame.draw.rect(screen, WHITE, (yes_x, button_y, button_w, button_h), 2, border_radius=15)
    
    draw_text("✓ TAK", font_large, WHITE, yes_x + button_w // 2, button_y + button_h // 2, center=True)
    
    # NIE
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
        # Wyjdź z odtwarzania
        stop_video_playback()
    elif current_state == STATE_CONFIRM:
        current_state = STATE_VIDEOS


def handle_ok():
    global current_state, confirm_selection, selected_index
    
    if current_state == STATE_VIDEOS:
        if videos and 0 <= selected_index < len(videos):
            start_video_playback(videos[selected_index])
    
    elif current_state == STATE_PLAYING:
        # Przełącz pauzę
        toggle_pause()
    
    elif current_state == STATE_CONFIRM:
        if confirm_selection == 1:
            # Usuń
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


def handle_delete():
    global current_state, confirm_selection
    if current_state == STATE_VIDEOS and videos:
        current_state = STATE_CONFIRM
        confirm_selection = 0


def handle_up():
    global selected_index
    if current_state == STATE_VIDEOS and videos:
        selected_index = max(0, selected_index - 1)
    elif current_state == STATE_PLAYING:
        # TODO: Zwiększ głośność
        print("🔊 Głośność UP (TBD)")


def handle_down():
    global selected_index
    if current_state == STATE_VIDEOS and videos:
        selected_index = min(len(videos) - 1, selected_index + 1)
    elif current_state == STATE_PLAYING:
        # TODO: Zmniejsz głośność
        print("🔉 Głośność DOWN (TBD)")


def handle_left():
    global confirm_selection
    if current_state == STATE_CONFIRM:
        confirm_selection = 0


def handle_right():
    global confirm_selection
    if current_state == STATE_CONFIRM:
        confirm_selection = 1


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
    
    btn_record.when_pressed = handle_record
    btn_ok.when_pressed = handle_ok
    btn_videos.when_pressed = handle_videos
    btn_delete.when_pressed = handle_delete
    btn_up.when_pressed = handle_up
    btn_down.when_pressed = handle_down
    btn_left.when_pressed = handle_left
    btn_right.when_pressed = handle_right
    
    print("✅ GPIO OK")
    
    print("\n" + "="*70)
    print("🎬 SYSTEM KAMERA - RASPBERRY PI 5")
    print("="*70)
    print("📺 Kamera live | 🔴 Record | 📹 Videos | ✅ Play | 🗑️  Delete")
    print("="*70 + "\n")
    
    clock = pygame.time.Clock()
    
    # Dla ciągłego przewijania
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
            
            # CIĄGŁE PRZEWIJANIE - sprawdzaj czy przyciski są przytrzymane
            if current_state == STATE_PLAYING:
                current_time = time.time()

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
                
                
                # Sprawdzaj co 0.1s (10 razy na sekundę)
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
            
            # Pobierz klatkę tylko dla ekranu głównego
            frame = None
            if current_state == STATE_MAIN:
                try:
                    frame = camera.capture_array()
                except:
                    frame = None
            
            # Rysuj odpowiedni ekran
            if current_state == STATE_MAIN:
                draw_main_screen(frame)
            elif current_state == STATE_VIDEOS:
                draw_videos_screen()
            elif current_state == STATE_CONFIRM:
                draw_videos_screen()
                draw_confirm_dialog()
            elif current_state == STATE_PLAYING:
                draw_playing_screen()
            
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