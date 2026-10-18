"""
Vega Launcher — Authentic Minecraft Animated Particle System (particle_overlay.py)
Provides animated, atmospheric floating Minecraft particles:
- Nether & Ender Portal swirls (effect_0..7 animated sequence)
- Enchanting Table SGA glyphs (sga_a..z morphing runes)
- End Rod & Crit stars (glitter_0..7 animated twinkle)
- Soul Sand & Sculk souls (sculk_soul_0..10, soul_0..10 animated rise & fade)
- Totem & Flame sparkles (spark_0..7 animated burst & flame)
- Mixed / All preset

Features:
- Animated sprite sequence playback matching authentic Minecraft particle timing.
- Ethereal ambient transparency with smooth sine envelope (never harsh, soft depth).
- Smart Performance Mode: 0% CPU consumption when game is running or window minimized.
"""

import os
import sys
import math
import random
from typing import List, Dict, Any, Optional
from PySide6.QtCore import Qt, QTimer, QRectF, QEvent
from PySide6.QtGui import QPainter, QColor, QBrush, QPixmap, QPaintEvent
from PySide6.QtWidgets import QWidget


def get_particles_dir() -> str:
    """
    Robust path resolver for particle sprite assets across dev, PyInstaller, and Inno Setup environments.
    Checks candidate directories in order:
    1. Executable directory (production installed root: <install_dir>/assets/particles)
    2. PyInstaller temporary extraction directory (sys._MEIPASS/assets/particles)
    3. PyInstaller _internal directory (<install_dir>/_internal/assets/particles)
    4. Module directory (development / python main.py: <repo>/assets/particles)
    """
    candidates = []
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, "assets", "particles"))
        candidates.append(os.path.join(exe_dir, "_internal", "assets", "particles"))
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(os.path.join(meipass, "assets", "particles"))
    mod_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(mod_dir, "assets", "particles"))
    parent_dir = os.path.dirname(mod_dir)
    candidates.append(os.path.join(parent_dir, "assets", "particles"))

    for c in candidates:
        if os.path.isdir(c):
            return c
    return candidates[0]


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARTICLES_DIR = get_particles_dir()


class AmbientParticle:
    __slots__ = (
        "x", "y", "radius", "speed_y", "drift_amp", "drift_speed", "phase",
        "age", "max_age", "target_alpha", "seq_frames", "loop", "ticks_per_frame",
        "color_idx", "sprite_idx", "half_w", "half_h"
    )

    def __init__(self, w: float, h: float, sequences: List[Dict[str, Any]], color_count: int):
        self.reset(w, h, sequences, color_count, initial=True)

    def reset(self, w: float, h: float, sequences: List[Dict[str, Any]], color_count: int, initial: bool = False):
        if sequences:
            seq = random.choice(sequences)
            self.seq_frames = seq["frames"]
            self.loop = seq.get("loop", True)
            self.half_w = seq.get("half_w", 10.0)
            self.half_h = seq.get("half_h", 10.0)
            base_tpf = seq.get("ticks_per_frame", 4)
        else:
            self.seq_frames = []
            self.loop = True
            self.half_w = 10.0
            self.half_h = 10.0
            base_tpf = 4

        num_frames = len(self.seq_frames) if self.seq_frames else 1

        if not self.loop:
            # Authentic Minecraft soul & sculk / spark animation timing:
            # 11 frames playback over ~22-33 ticks (~0.7s - 1.1s) at 2..3 ticks/frame
            # Exactly matches Minecraft Java Edition SoulParticle lifetime (16-24 game ticks).
            self.ticks_per_frame = random.choice([base_tpf, max(base_tpf, 3)])
            self.max_age = num_frames * self.ticks_per_frame
            self.age = random.randint(0, self.max_age - 1) if initial else 0
            # Swift upward surge: Minecraft souls rush upward as they open their mouth and scream
            self.speed_y = random.uniform(2.5, 4.2)
            self.drift_amp = random.uniform(0.6, 1.4)
            self.drift_speed = random.uniform(0.06, 0.12)
            self.target_alpha = random.randint(180, 240)
            self.radius = 3.0
            self.x = random.uniform(20.0, max(100.0, w - 20.0))
            # Spawn souls distributed across the canvas so they emerge organically everywhere
            self.y = random.uniform(60.0, max(100.0, h - 20.0))
        else:
            # Ambient floating particles (Portal, Runes, Stars)
            self.ticks_per_frame = base_tpf
            self.radius = random.uniform(2.0, 3.5)
            self.speed_y = random.uniform(0.55, 1.25)
            self.drift_amp = random.uniform(0.4, 1.4)
            self.drift_speed = random.uniform(0.02, 0.045)
            self.max_age = random.randint(140, 260)
            self.age = random.randint(0, self.max_age) if initial else 0
            self.target_alpha = random.randint(40, 85)
            self.x = random.uniform(0, max(100.0, w))
            self.y = random.uniform(0, max(100.0, h)) if initial else max(100.0, h) + random.uniform(5, 30)

        self.phase = random.uniform(0, math.pi * 2)
        self.color_idx = random.randint(0, max(0, color_count - 1)) if color_count > 0 else 0
        self.sprite_idx = 0

    def update(self, w: float, h: float, sequences: List[Dict[str, Any]], color_count: int):
        self.age += 1
        self.y -= self.speed_y
        self.phase += self.drift_speed
        self.x += math.sin(self.phase) * self.drift_amp
        if self.age >= self.max_age or self.y < -30 or self.x < -30 or self.x > w + 30:
            self.reset(w, h, sequences, color_count, initial=False)


class ParticleOverlay(QWidget):
    """Transparent background canvas rendering floating animated Minecraft particles."""

    PRESETS = ("portal", "runes", "stars", "souls", "sparkles", "all")

    def __init__(self, parent=None, num_particles: int = 35):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.NoFocus)

        self._enabled = True
        self._is_paused = False
        self._filter_installed = False
        self._preset = "portal"
        self.num_particles = max(10, min(60, num_particles))
        self.particles: List[AmbientParticle] = []
        self._opacity_percent = 50

        # Default Electric Amethyst palette
        self.palette = [
            QColor(168, 85, 247),  # Light purple
            QColor(192, 132, 252), # Amethyst glow
            QColor(139, 92, 246),  # Primary purple
            QColor(34, 211, 238),  # Ender pearl cyan accent
        ]

        # Raw loaded sequences by category
        self._raw_sequences: Dict[str, List[Dict[str, Any]]] = {}
        # Active sequences matching current preset and palette
        self._active_sequences: List[Dict[str, Any]] = []
        # Flattened list of active sprites for compatibility and checks
        self._active_sprites: List[QPixmap] = []

        self._load_all_sprites()
        self._update_active_sprites()

        self.timer = QTimer(self)
        self.timer.setInterval(40)  # ~25 FPS (smooth ambient tick, lower CPU)
        self.timer.timeout.connect(self._on_tick)

        self._init_particles()
        self.timer.start()

    def _load_all_sprites(self):
        """Loads authentic particle animation frame sequences from assets/particles/."""
        global PARTICLES_DIR
        self._raw_sequences.clear()
        PARTICLES_DIR = get_particles_dir()
        if not os.path.isdir(PARTICLES_DIR):
            return

        target_size = 20  # Sharp Minecraft pixel scale (20x20)

        def _load_frames(cat: str, names: List[str], size: int = 20) -> List[QPixmap]:
            frames = []
            cat_dir = os.path.join(PARTICLES_DIR, cat)
            for n in names:
                fp = os.path.join(cat_dir, n)
                if os.path.exists(fp):
                    orig = QPixmap(fp)
                    if not orig.isNull():
                        scaled = orig.scaled(size, size, Qt.KeepAspectRatio, Qt.FastTransformation)
                        frames.append(scaled)
            return frames

        # 1. Portal sequence (effect_0..7)
        portal_names = [f"effect_{i}.png" for i in range(8)]
        portal_frames = _load_frames("portal", portal_names, size=20)
        if portal_frames:
            self._raw_sequences["portal"] = [{
                "frames": portal_frames,
                "loop": True,
                "ticks_per_frame": 4,  # ~133ms per frame, authentic game tick rate
                "tintable": True,
            }]

        # 2. Runes (Standard Galactic Alphabet sga_a..z)
        rune_names = [f"sga_{chr(c)}.png" for c in range(ord('a'), ord('z')+1)]
        rune_frames = _load_frames("runes", rune_names, size=20)
        if rune_frames:
            # Create a set of morphing rune sequences (cycling 4-5 glyphs)
            rune_seqs = []
            for i in range(0, len(rune_frames), 4):
                chunk = rune_frames[i:i+4]
                if len(chunk) >= 2:
                    rune_seqs.append({
                        "frames": chunk,
                        "loop": True,
                        "ticks_per_frame": 6,
                        "tintable": True,
                    })
            if not rune_seqs:
                rune_seqs.append({"frames": rune_frames, "loop": True, "ticks_per_frame": 6, "tintable": True})
            self._raw_sequences["runes"] = rune_seqs

        # 3. Stars (Glitter sequence 0..7 and crit stars)
        glitter_names = [f"glitter_{i}.png" for i in range(8)]
        glitter_frames = _load_frames("stars", glitter_names, size=20)
        stars_seqs = []
        if glitter_frames:
            stars_seqs.append({"frames": glitter_frames, "loop": True, "ticks_per_frame": 4, "tintable": False})
        crit_frames = _load_frames("stars", ["enchanted_hit.png", "glint.png", "glow.png"], size=20)
        if crit_frames:
            stars_seqs.append({"frames": crit_frames, "loop": True, "ticks_per_frame": 8, "tintable": False})
        if stars_seqs:
            self._raw_sequences["stars"] = stars_seqs

        # 4. Souls (Sculk souls 0..10 and Soul sand souls 0..10)
        # Scaled to 32x32 (crisp 2x integer pixel art scale) and 2 ticks/frame (~66ms/frame)
        souls_seqs = []
        sculk_names = [f"sculk_soul_{i}.png" for i in range(11)]
        sculk_frames = _load_frames("souls", sculk_names, size=32)
        if sculk_frames:
            souls_seqs.append({"frames": sculk_frames, "loop": False, "ticks_per_frame": 2, "tintable": False})
        soul_names = [f"soul_{i}.png" for i in range(11)]
        soul_frames = _load_frames("souls", soul_names, size=32)
        if soul_frames:
            souls_seqs.append({"frames": soul_frames, "loop": False, "ticks_per_frame": 2, "tintable": False})
        if souls_seqs:
            self._raw_sequences["souls"] = souls_seqs

        # 5. Sparkles (Sparks 0..7 and Flames)
        sparkles_seqs = []
        spark_names = [f"spark_{i}.png" for i in range(8)]
        spark_frames = _load_frames("sparkles", spark_names, size=20)
        if spark_frames:
            sparkles_seqs.append({"frames": spark_frames, "loop": False, "ticks_per_frame": 2, "tintable": False})
        flame_frames = _load_frames("sparkles", ["flame.png", "soul_fire_flame.png"], size=20)
        if flame_frames:
            sparkles_seqs.append({"frames": flame_frames, "loop": True, "ticks_per_frame": 6, "tintable": False})
        if sparkles_seqs:
            self._raw_sequences["sparkles"] = sparkles_seqs

    def _tint_pixmap(self, pixmap: QPixmap, color: QColor) -> QPixmap:
        """Tints a grayscale/white alpha mask pixmap with the specified color."""
        tinted = QPixmap(pixmap.size())
        tinted.fill(Qt.transparent)
        p = QPainter(tinted)
        p.drawPixmap(0, 0, pixmap)
        p.setCompositionMode(QPainter.CompositionMode_SourceIn)
        p.fillRect(tinted.rect(), color)
        p.end()
        return tinted

    def _update_active_sprites(self):
        """Constructs the active animation sequences based on current preset and theme palette."""
        self._active_sequences = []

        if self._preset == "all":
            selected_cats = ["portal", "runes", "stars", "souls", "sparkles"]
        else:
            selected_cats = [self._preset]

        for cat in selected_cats:
            raw_seqs = self._raw_sequences.get(cat, [])
            for seq in raw_seqs:
                if seq.get("tintable", False) and self.palette:
                    for col in self.palette:
                        tinted_frames = [self._tint_pixmap(f, col) for f in seq["frames"]]
                        hw = tinted_frames[0].width() / 2.0 if tinted_frames else 10.0
                        hh = tinted_frames[0].height() / 2.0 if tinted_frames else 10.0
                        self._active_sequences.append({
                            "frames": tinted_frames,
                            "loop": seq.get("loop", True),
                            "ticks_per_frame": seq.get("ticks_per_frame", 4),
                            "half_w": hw,
                            "half_h": hh,
                        })
                else:
                    frames_list = list(seq["frames"])
                    hw = frames_list[0].width() / 2.0 if frames_list else 10.0
                    hh = frames_list[0].height() / 2.0 if frames_list else 10.0
                    self._active_sequences.append({
                        "frames": frames_list,
                        "loop": seq.get("loop", True),
                        "ticks_per_frame": seq.get("ticks_per_frame", 4),
                        "half_w": hw,
                        "half_h": hh,
                    })

        # Keep a flattened list of active sprites
        self._active_sprites = [f for seq in self._active_sequences for f in seq["frames"]]

    def set_preset(self, preset: str):
        """Switch authentic particle preset (portal, runes, stars, souls, sparkles, all)."""
        clean_preset = str(preset).lower()
        if clean_preset not in self.PRESETS:
            clean_preset = "portal"
        if self._preset != clean_preset:
            self._preset = clean_preset
            self._update_active_sprites()
            c_count = len(self.palette)
            for p in self.particles:
                p.reset(float(self.width()), float(self.height()), self._active_sequences, c_count, initial=True)
            self.update()

    def get_preset(self) -> str:
        return self._preset

    def set_opacity_percent(self, percent: int):
        """Sets the particle opacity level (0 to 100)."""
        self._opacity_percent = max(0, min(100, int(percent)))
        self.update()

    def get_opacity_percent(self) -> int:
        return self._opacity_percent

    def _init_particles(self):
        w = float(self.width()) if self.width() > 10 else 1280.0
        h = float(self.height()) if self.height() > 10 else 720.0
        c_len = len(self.palette)
        self.particles = [AmbientParticle(w, h, self._active_sequences, c_len) for _ in range(self.num_particles)]

    def set_palette(self, colors: List[QColor]):
        """Sets the theme color palette and updates tinted animation sequences."""
        if colors:
            self.palette = list(colors)
            self._update_active_sprites()
            c_len = len(self.palette)
            for p in self.particles:
                p.color_idx = random.randint(0, max(0, c_len - 1)) if c_len > 0 else 0
                if self._active_sequences:
                    seq = random.choice(self._active_sequences)
                    p.seq_frames = seq["frames"]
                    p.loop = seq.get("loop", True)
                    p.ticks_per_frame = seq.get("ticks_per_frame", 4)
                    if not p.loop:
                        p.max_age = len(p.seq_frames) * p.ticks_per_frame
            self.update()

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)
        if not self._enabled:
            if self.timer.isActive():
                self.timer.stop()
            self.hide()
        else:
            self.show()
            if not self._is_paused and not self.timer.isActive():
                self.timer.start()

    def is_enabled(self) -> bool:
        return self._enabled

    def pause(self):
        """Immediately halts rendering timer for 0% CPU consumption."""
        self._is_paused = True
        if self.timer.isActive():
            self.timer.stop()

    def resume(self):
        """Resumes particle simulation when game exits or window is un-minimized."""
        self._is_paused = False
        if self._enabled and not self.timer.isActive():
            self.timer.start()
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        win = self.window()
        if win and not getattr(self, "_filter_installed", False):
            win.installEventFilter(self)
            self._filter_installed = True

    def eventFilter(self, watched, event):
        if event.type() == QEvent.WindowStateChange:
            win = self.window()
            if win and win.isMinimized():
                if self.timer.isActive():
                    self.timer.stop()
            elif self._enabled and not self._is_paused:
                if not self.timer.isActive():
                    self.timer.start()
        return super().eventFilter(watched, event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            win = self.window()
            if win and win.isMinimized():
                if self.timer.isActive():
                    self.timer.stop()
            elif self._enabled and not self._is_paused:
                if not self.timer.isActive():
                    self.timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = float(self.width())
        h = float(self.height())
        for p in self.particles:
            if p.x > w:
                p.x = random.uniform(0, max(50.0, w))
            if p.y > h:
                p.y = random.uniform(0, max(50.0, h))

    def _on_tick(self):
        if not self._enabled or self._is_paused:
            return
        win = self.window()
        if win and (win.isMinimized() or not win.isVisible()):
            return
        w = float(self.width())
        h = float(self.height())
        if w <= 10 or h <= 10:
            return
        c_len = max(1, len(self.palette))
        for p in self.particles:
            p.update(w, h, self._active_sequences, c_len)
        self.update()

    def paintEvent(self, event: QPaintEvent):
        if not self._enabled or not self.particles:
            return
        win = self.window()
        if win and (win.isMinimized() or not win.isVisible()):
            return
        if self.width() <= 10 or self.height() <= 10:
            return

        painter = QPainter(self)
        c_count = len(self.palette)
        opacity_mult = max(0.0, min(1.0, getattr(self, "_opacity_percent", 50) / 100.0))
        if opacity_mult <= 0.001:
            painter.end()
            return


        if self._active_sequences:
            # Render animated Minecraft pixel art particle sequences
            for p in self.particles:
                frames = p.seq_frames
                if not frames:
                    continue

                if p.loop:
                    # Ambient looping particles (Portal swirls, Runes, Stars)
                    t = min(1.0, max(0.0, p.age / float(max(1, p.max_age))))
                    alpha = int(p.target_alpha * math.sin(t * math.pi) * (opacity_mult / 0.5))
                    alpha = max(0, min(255, alpha))
                    if alpha <= 1:
                        continue
                    frame_idx = int(p.age / max(1, p.ticks_per_frame)) % len(frames)
                else:
                    # Authentic Minecraft sprite sequence (Souls & Sculk, Sparks)
                    # Advances frame directly by ticks_per_frame matching authentic in-game speed
                    frame_idx = min(len(frames) - 1, p.age // max(1, p.ticks_per_frame))
                    alpha = int(p.target_alpha * (opacity_mult / 0.5))
                    alpha = max(0, min(255, alpha))
                    if alpha <= 1:
                        continue

                sprite = frames[frame_idx]
                painter.setOpacity(alpha / 255.0)
                painter.drawPixmap(int(p.x - p.half_w), int(p.y - p.half_h), sprite)

        elif c_count > 0:
            # Fallback to soft glow circles if sprites cannot be loaded
            painter.setRenderHint(QPainter.Antialiasing, True)
            for p in self.particles:
                t = min(1.0, max(0.0, p.age / float(max(1, p.max_age))))
                alpha = int(p.target_alpha * math.sin(t * math.pi) * (opacity_mult / 0.5))
                alpha = max(0, min(255, alpha))
                if alpha <= 1:
                    continue

                base_col = self.palette[p.color_idx % c_count]
                glow_col = QColor(base_col.red(), base_col.green(), base_col.blue(), max(5, alpha // 3))
                painter.setBrush(QBrush(glow_col))
                painter.setPen(Qt.NoPen)
                glow_r = p.radius * 2.2
                painter.drawEllipse(QRectF(p.x - glow_r, p.y - glow_r, glow_r * 2.0, glow_r * 2.0))

                core_col = QColor(base_col.red(), base_col.green(), base_col.blue(), alpha)
                painter.setBrush(QBrush(core_col))
                painter.drawEllipse(QRectF(p.x - p.radius, p.y - p.radius, p.radius * 2.0, p.radius * 2.0))

        painter.end()
