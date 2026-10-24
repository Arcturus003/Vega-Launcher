"""
Vega Launcher — Procedural Sound Effects Engine (sound_manager.py)
Provides low-latency, lightweight Minecraft-themed UI audio feedback.
Synthesizes clean 44.1kHz WAV sound effects procedurally without external downloads.
"""

import os
import sys
import math
import wave
import struct
import time
import subprocess
from typing import List
from PySide6.QtCore import QObject, QUrl
from PySide6.QtMultimedia import QSoundEffect


SOUND_VERSION = 10


def _ensure_dir(path: str):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)


def get_sounds_dir() -> str:
    """
    Robust path resolver for sound assets across dev, PyInstaller, and Inno Setup environments.
    Checks candidate directories in order:
    1. Executable directory (production installed root: <install_dir>/assets/sounds)
    2. PyInstaller temporary extraction directory (sys._MEIPASS/assets/sounds)
    3. PyInstaller _internal directory (<install_dir>/_internal/assets/sounds)
    4. Module directory (development / python main.py: <repo>/assets/sounds)
    """
    candidates = []
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, "assets", "sounds"))
        candidates.append(os.path.join(exe_dir, "_internal", "assets", "sounds"))
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(os.path.join(meipass, "assets", "sounds"))
    mod_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(mod_dir, "assets", "sounds"))
    parent_dir = os.path.dirname(mod_dir)
    candidates.append(os.path.join(parent_dir, "assets", "sounds"))

    for c in candidates:
        if os.path.isdir(c):
            return c
    return candidates[0]


def extract_authentic_minecraft_sounds(dest_dir: str) -> bool:
    """
    Extracts authentic original Minecraft sound effects from local .minecraft/assets/objects
    (or bundled assets/sounds) and converts them to 44.1kHz stereo WAV files.
    Returns True if all sounds are available.
    """
    appdata = os.environ.get("APPDATA", "")
    objs = os.path.join(appdata, ".minecraft", "assets", "objects")
    bundled_dir = get_sounds_dir()

    mappings = {
        "click.wav": os.path.join(objs, "ec", "ec4f4d122ab7c5d44e48419de0e3de1b0922514d"),
        "launch.wav": os.path.join(objs, "30", "301f32642b654addbd06a430768fead464fd24c4"),
        "levelup.wav": os.path.join(objs, "b9", "b9c60e807ba770e8c4a2b1bae81d51813dc64b6c"),
        "error.wav": os.path.join(objs, "93", "934b16e82b94d5790175615303594f0ec28da4a0"),
        "door_open.wav": os.path.join(objs, "4e", "4ed1f29f3e1378811f7fcc49db743400b8e3284f"),
        "door_close.wav": os.path.join(objs, "87", "871634413de37a092d0e5fe7844a37917c27bbf2"),
        "book_flip.wav": os.path.join(objs, "23", "234d6a686516c264a370ea834b87d47ae7334ef7"),
        "enderchest_open.wav": os.path.join(objs, "82", "822b19d5b722fd689e60cfaa7c3ae39a3bdf701c"),
        "enderchest_close.wav": os.path.join(objs, "5f", "5f3412ca2fe0141a412dfd66567aa13a26e89ec1"),
        "break.wav": os.path.join(objs, "8b", "8bf3ecb0fe9a6a615f5995e3dd21b6c39adc21d5"),
        "fizz.wav": os.path.join(objs, "c6", "c649e60ea9a99c97501a50d2dc4e579343e91ea8"),
        "beacon_activate.wav": os.path.join(objs, "19", "191510085f615e2d44136f45c41dd19aecf601e5"),
        "beacon_deactivate.wav": os.path.join(objs, "38", "385211c4a419a4613f311e45cd070e442e6a8a53"),
        "challenge_complete.wav": os.path.join(objs, "21", "210c839d6fab655373b3a5e4c278f59dff4936d8"),
        "amethyst_shimmer.wav": os.path.join(objs, "da", "da0969aedca90796e6828293b6d8f85f4c1a35f8"),
        "enchant.wav": os.path.join(objs, "f0", "f05f55328f2b98b3c7d881fcdef7e7964d8082fa"),
        "pop.wav": os.path.join(objs, "8f", "8f45b5faf6dfae2065846d26612f7552b73640dd"),
        "teleport.wav": os.path.join(objs, "7b", "7b4b5323ef066caa1ae43cbe66fffd9dfce4ed32"),
        "lever_on.wav": (os.path.join(objs, "ec", "ec4f4d122ab7c5d44e48419de0e3de1b0922514d"), "asetrate=44100*1.15,aresample=44100"),
        "lever_off.wav": (os.path.join(objs, "ec", "ec4f4d122ab7c5d44e48419de0e3de1b0922514d"), "asetrate=44100*0.88,aresample=44100"),
        "bookshelf_insert.wav": os.path.join(objs, "ff", "ff0253a660370841a8e7a1e3370c66c0e3a29dac"),
    }

    _ensure_dir(os.path.join(dest_dir, "test.wav"))
    import shutil
    extracted = 0
    for wname, ogg_src in mappings.items():
        wdst = os.path.join(dest_dir, wname)
        bundled_wav = os.path.join(bundled_dir, wname)
        if os.path.abspath(dest_dir) != os.path.abspath(bundled_dir) and os.path.exists(bundled_wav) and os.path.getsize(bundled_wav) > 0:
            try:
                shutil.copy2(bundled_wav, wdst)
                extracted += 1
                continue
            except Exception:
                pass
        if os.path.exists(wdst) and os.path.getsize(wdst) > 1000:
            extracted += 1
            continue
        af_args = []
        if isinstance(ogg_src, tuple):
            ogg_src, af_filter = ogg_src
            af_args = ["-af", af_filter]
        if os.path.exists(ogg_src):
            try:
                cmd = ["ffmpeg", "-y", "-i", ogg_src] + af_args + ["-ar", "44100", "-ac", "2", wdst]
                subprocess.run(
                    cmd,
                    capture_output=True,
                    check=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if os.path.exists(wdst) and os.path.getsize(wdst) > 0:
                    extracted += 1
            except Exception:
                pass
    return extracted == len(mappings)


def generate_click_wav(path: str):
    """
    Synthesizes an authentic, crisp Minecraft mechanical button click (18ms).
    Produces a single, unified tactile impulse (850Hz to 400Hz micro-pitch sweep)
    with rapid exponential damping (15ms) and end-tapering to completely eliminate
    double-tap/echo artifacts and DC pops.
    """
    _ensure_dir(path)
    sample_rate = 44100
    duration = 0.018
    num_samples = int(sample_rate * duration)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        samples = []
        for i in range(num_samples):
            t = i / sample_rate
            attack = min(1.0, t / 0.0008)
            decay = math.exp(-t * 260.0)
            taper = min(1.0, (duration - t) / 0.002) if t > duration - 0.002 else 1.0
            env = attack * decay * taper

            freq = 400.0 + 450.0 * math.exp(-t * 350.0)
            tone = math.sin(2.0 * math.pi * freq * t)
            texture = ((i * 13) % 7 - 3) / 3.0 * math.exp(-t * 500.0) * 0.20

            val = (tone + texture) * env * 0.85
            clamped = max(-1.0, min(1.0, val))
            samples.append(int(clamped * 32767))
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def generate_launch_wav(path: str):
    """
    Synthesizes an immersive Minecraft Nether/End Portal activation warp sound (420ms).
    Layers a deep cinematic sub-bass surge (65Hz-110Hz) with mystical fifth and octave
    harmonics, ethereal phase chorus, and shimmering portal energy particles.
    """
    _ensure_dir(path)
    sample_rate = 44100
    duration = 0.42
    num_samples = int(sample_rate * duration)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        samples = []
        phase_sub = 0.0
        for i in range(num_samples):
            t = i / sample_rate
            p = t / duration
            env = math.sin(math.pi * (p ** 0.8)) ** 1.5

            freq_sub = 65.0 + 45.0 * (p ** 1.3)
            phase_sub += 2.0 * math.pi * freq_sub / sample_rate
            sub_bass = math.sin(phase_sub)

            harmony = 0.35 * math.sin(phase_sub * 1.5 + 0.3) + 0.20 * math.sin(phase_sub * 2.0)
            shimmer = 0.12 * math.sin(2.0 * math.pi * 660.0 * t + 0.5 * math.sin(2.0 * math.pi * 8.0 * t)) * (1.0 - p)

            val = (0.60 * sub_bass + harmony + shimmer) * env * 0.85
            clamped = max(-1.0, min(1.0, val))
            samples.append(int(clamped * 32767))
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def generate_levelup_wav(path: str):
    """
    Synthesizes the iconic Minecraft experience orb / level-up chime (550ms).
    A bright, resonant 3-note ascending arpeggio (G5 784Hz -> B5 988Hz -> D6 1175Hz)
    with bell harmonics and crystalline decay.
    """
    _ensure_dir(path)
    sample_rate = 44100
    duration = 0.55
    num_samples = int(sample_rate * duration)
    notes = [
        (0.00, 783.99),   # G5
        (0.12, 987.77),   # B5
        (0.24, 1174.66),  # D6
    ]
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        samples = []
        for i in range(num_samples):
            t = i / sample_rate
            total_val = 0.0
            for start_t, freq in notes:
                if t >= start_t:
                    dt = t - start_t
                    attack = min(1.0, dt / 0.003)
                    decay = math.exp(-dt * 9.0)
                    env = attack * decay
                    tone = (
                        0.70 * math.sin(2.0 * math.pi * freq * dt)
                        + 0.22 * math.sin(2.0 * math.pi * (freq * 2.0) * dt)
                        + 0.08 * math.sin(2.0 * math.pi * (freq * 3.0) * dt)
                    ) * env
                    total_val += tone
            clamped = max(-1.0, min(1.0, total_val * 0.75))
            samples.append(int(clamped * 32767))
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def generate_error_wav(path: str):
    """
    Synthesizes a solid Minecraft anvil / iron strike thud (220ms).
    Features a metallic attack strike (115Hz fundamental + inharmonic bell ring)
    with a damped tactile thud, communicating clear error feedback without cartoon bends.
    """
    _ensure_dir(path)
    sample_rate = 44100
    duration = 0.22
    num_samples = int(sample_rate * duration)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        samples = []
        for i in range(num_samples):
            t = i / sample_rate
            attack = min(1.0, t / 0.002)
            decay = math.exp(-t * 22.0)
            env = attack * decay

            thud = math.sin(2.0 * math.pi * 115.0 * t)
            metal_ring = 0.40 * math.sin(2.0 * math.pi * 310.0 * t) + 0.25 * math.sin(2.0 * math.pi * 560.0 * t)
            val = (0.65 * thud + metal_ring) * env * 0.85
            clamped = max(-1.0, min(1.0, val))
            samples.append(int(clamped * 32767))
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def generate_door_open_wav(path: str):
    """
    Synthesizes an authentic Minecraft wooden door opening creak (450ms).
    Features wood friction harmonic modulation (140Hz to 280Hz creak)
    with a gentle wooden latch click.
    """
    _ensure_dir(path)
    sample_rate = 44100
    duration = 0.45
    num_samples = int(sample_rate * duration)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        samples = []
        phase = 0.0
        for i in range(num_samples):
            t = i / sample_rate
            p = t / duration
            env = math.sin(math.pi * p) ** 0.85
            freq = 140.0 + 140.0 * (p ** 1.2)
            phase += 2.0 * math.pi * freq / sample_rate
            creak = math.sin(phase) + 0.35 * math.sin(phase * 2.3 + math.sin(phase * 0.5))
            val = creak * env * 0.75
            clamped = max(-1.0, min(1.0, val))
            samples.append(int(clamped * 32767))
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def generate_door_close_wav(path: str):
    """
    Synthesizes an authentic Minecraft wooden door closing slam (350ms).
    Features a solid wooden frame impact thud (105Hz) and resonant timber decay.
    """
    _ensure_dir(path)
    sample_rate = 44100
    duration = 0.35
    num_samples = int(sample_rate * duration)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        samples = []
        for i in range(num_samples):
            t = i / sample_rate
            attack = min(1.0, t / 0.003)
            decay = math.exp(-t * 18.0)
            env = attack * decay
            thud = math.sin(2.0 * math.pi * 105.0 * t) + 0.35 * math.sin(2.0 * math.pi * 210.0 * t)
            click = 0.40 * math.sin(2.0 * math.pi * 850.0 * t) * math.exp(-t * 90.0)
            val = (0.75 * thud + click) * env * 0.85
            clamped = max(-1.0, min(1.0, val))
            samples.append(int(clamped * 32767))
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def generate_teleport_wav(path: str):
    """
    Synthesizes an authentic Minecraft Enderman teleport warp sound (650ms).
    Features a mystical upward reverse whoosh frequency sweep followed by
    an ethereal descending pitch bend, phase chorus and crystalline resonance.
    """
    _ensure_dir(path)
    sample_rate = 44100
    duration = 0.65
    num_samples = int(sample_rate * duration)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        samples = []
        phase = 0.0
        for i in range(num_samples):
            t = i / sample_rate
            p = t / duration
            if p < 0.4:
                env = (p / 0.4) ** 1.8
                freq = 280.0 + 520.0 * (p / 0.4) ** 2.0
            else:
                p_desc = (p - 0.4) / 0.6
                env = math.exp(-p_desc * 4.5)
                freq = 800.0 * math.exp(-p_desc * 3.0) + 120.0

            phase += 2.0 * math.pi * freq / sample_rate
            tone = math.sin(phase) + 0.35 * math.sin(phase * 1.5 + 0.4)
            shimmer = 0.20 * math.sin(2.0 * math.pi * (freq * 2.2) * t) * (1.0 - p)
            noise = ((i * 37) % 19 - 9) / 9.0 * 0.12 * env

            val = (0.65 * tone + shimmer + noise) * env * 0.85
            clamped = max(-1.0, min(1.0, val))
            samples.append(int(clamped * 32767))
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def generate_lever_on_wav(path: str):
    """
    Synthesizes an authentic Minecraft redstone lever flick ON (22ms).
    Features a high-attack tactile redstone switch impulse (920Hz down to 540Hz)
    with rapid exponential damping (14ms) producing a crisp, bright 'tık!'.
    """
    _ensure_dir(path)
    sample_rate = 44100
    duration = 0.022
    num_samples = int(sample_rate * duration)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        samples = []
        for i in range(num_samples):
            t = i / sample_rate
            attack = min(1.0, t / 0.0006)
            decay = math.exp(-t * 240.0)
            taper = min(1.0, (duration - t) / 0.002) if t > duration - 0.002 else 1.0
            env = attack * decay * taper

            freq = 540.0 + 380.0 * math.exp(-t * 300.0)
            tone = math.sin(2.0 * math.pi * freq * t)
            click_snap = 0.35 * math.sin(2.0 * math.pi * (freq * 1.8) * t) * math.exp(-t * 400.0)
            texture = ((i * 17) % 7 - 3) / 3.0 * math.exp(-t * 450.0) * 0.15

            val = (tone + click_snap + texture) * env * 0.85
            clamped = max(-1.0, min(1.0, val))
            samples.append(int(clamped * 32767))
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def generate_lever_off_wav(path: str):
    """
    Synthesizes an authentic Minecraft redstone lever flick OFF (26ms).
    Features a deeper, heavier tactile redstone release thud (640Hz down to 310Hz)
    with damped timber resonance (18ms) producing a solid, satisfying 'tok!'.
    """
    _ensure_dir(path)
    sample_rate = 44100
    duration = 0.026
    num_samples = int(sample_rate * duration)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        samples = []
        for i in range(num_samples):
            t = i / sample_rate
            attack = min(1.0, t / 0.0008)
            decay = math.exp(-t * 190.0)
            taper = min(1.0, (duration - t) / 0.002) if t > duration - 0.002 else 1.0
            env = attack * decay * taper

            freq = 310.0 + 330.0 * math.exp(-t * 220.0)
            tone = math.sin(2.0 * math.pi * freq * t)
            body = 0.40 * math.sin(2.0 * math.pi * (freq * 0.7) * t) * math.exp(-t * 260.0)
            texture = ((i * 11) % 5 - 2) / 2.0 * math.exp(-t * 350.0) * 0.12

            val = (tone + body + texture) * env * 0.85
            clamped = max(-1.0, min(1.0, val))
            samples.append(int(clamped * 32767))
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def generate_bookshelf_insert_wav(path: str):
    """
    Synthesizes an organic, warm Minecraft chiseled bookshelf book insert sound (65ms).
    Layers a woody acoustic impulse (320Hz sliding to 160Hz) with subtle parchment friction.
    """
    _ensure_dir(path)
    sample_rate = 44100
    duration = 0.065
    num_samples = int(sample_rate * duration)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        samples = []
        phase = 0.0
        for i in range(num_samples):
            t = i / sample_rate
            p = t / duration
            env = math.exp(-p * 14.0) * math.sin(min(1.0, p / 0.08) * (math.pi / 2))
            freq = 320.0 - 160.0 * (p ** 0.5)
            phase += 2.0 * math.pi * freq / sample_rate
            wood_body = math.sin(phase) + 0.35 * math.sin(phase * 2.1)
            friction = (math.sin(2.0 * math.pi * 1840.0 * t) * 0.15) * (1.0 - p)
            val = (wood_body * 0.75 + friction) * env * 0.85
            clamped = max(-1.0, min(1.0, val))
            samples.append(int(clamped * 32767))
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))


class SoundManager(QObject):
    """Singleton audio manager for Vega Launcher UI sound effects."""

    _instance = None

    @classmethod
    def get_instance(cls, parent=None, sounds_dir: str = None):
        if cls._instance is None:
            cls._instance = SoundManager(parent=parent, sounds_dir=sounds_dir)
        return cls._instance

    def __init__(self, parent=None, sounds_dir: str = None):
        super().__init__(parent)
        if sounds_dir:
            self.sounds_dir = sounds_dir
        else:
            self.sounds_dir = get_sounds_dir()

        self._enabled = True
        self._volume = 70  # 0 to 100
        self._effects = {}
        self._click_voices: List[QSoundEffect] = []
        self._click_voice_idx = 0
        self._last_click_time = 0.0
        self._last_sound_times: Dict[str, float] = {}
        self._sound_cooldown = 0.14
        self._init_sounds()

    def _init_sounds(self):
        try:
            os.makedirs(self.sounds_dir, exist_ok=True)
            test_file = os.path.join(self.sounds_dir, ".write_test")
            with open(test_file, "w") as f:
                f.write("ok")
            os.remove(test_file)
        except (OSError, PermissionError):
            user_data = os.environ.get("APPDATA", os.path.expanduser("~"))
            self.sounds_dir = os.path.join(user_data, ".minecraft_launcher", "sounds")
            os.makedirs(self.sounds_dir, exist_ok=True)

        version_file = os.path.join(self.sounds_dir, ".sound_version")
        force_regen = False
        try:
            if not os.path.exists(version_file):
                force_regen = True
            else:
                with open(version_file, "r", encoding="utf-8") as vf:
                    if vf.read().strip() != str(SOUND_VERSION):
                        force_regen = True
        except Exception:
            force_regen = True

        sound_generators = {
            "click": (os.path.join(self.sounds_dir, "click.wav"), generate_click_wav),
            "launch": (os.path.join(self.sounds_dir, "launch.wav"), generate_launch_wav),
            "levelup": (os.path.join(self.sounds_dir, "levelup.wav"), generate_levelup_wav),
            "error": (os.path.join(self.sounds_dir, "error.wav"), generate_error_wav),
            "door_open": (os.path.join(self.sounds_dir, "door_open.wav"), generate_door_open_wav),
            "door_close": (os.path.join(self.sounds_dir, "door_close.wav"), generate_door_close_wav),
            "book_flip": (os.path.join(self.sounds_dir, "book_flip.wav"), generate_click_wav),
            "enderchest_open": (os.path.join(self.sounds_dir, "enderchest_open.wav"), generate_door_open_wav),
            "enderchest_close": (os.path.join(self.sounds_dir, "enderchest_close.wav"), generate_door_close_wav),
            "break": (os.path.join(self.sounds_dir, "break.wav"), generate_error_wav),
            "fizz": (os.path.join(self.sounds_dir, "fizz.wav"), generate_error_wav),
            "beacon_activate": (os.path.join(self.sounds_dir, "beacon_activate.wav"), generate_launch_wav),
            "beacon_deactivate": (os.path.join(self.sounds_dir, "beacon_deactivate.wav"), generate_door_close_wav),
            "challenge_complete": (os.path.join(self.sounds_dir, "challenge_complete.wav"), generate_levelup_wav),
            "amethyst_shimmer": (os.path.join(self.sounds_dir, "amethyst_shimmer.wav"), generate_levelup_wav),
            "enchant": (os.path.join(self.sounds_dir, "enchant.wav"), generate_levelup_wav),
            "pop": (os.path.join(self.sounds_dir, "pop.wav"), generate_click_wav),
            "teleport": (os.path.join(self.sounds_dir, "teleport.wav"), generate_teleport_wav),
            "lever_on": (os.path.join(self.sounds_dir, "lever_on.wav"), generate_lever_on_wav),
            "lever_off": (os.path.join(self.sounds_dir, "lever_off.wav"), generate_lever_off_wav),
            "bookshelf_insert": (os.path.join(self.sounds_dir, "bookshelf_insert.wav"), generate_bookshelf_insert_wav),
        }

        # Step 1: Attempt to extract authentic original Minecraft sound effects
        if force_regen or not all(os.path.exists(p) and os.path.getsize(p) > 0 for p, _ in sound_generators.values()):
            extracted = extract_authentic_minecraft_sounds(self.sounds_dir)
            if not extracted:
                # Step 2: Fall back to procedurally synthesized waveforms if assets are unavailable
                for name, (file_path, gen_fn) in sound_generators.items():
                    try:
                        if force_regen or not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                            gen_fn(file_path)
                    except Exception as e:
                        print(f"[SoundManager] Sound '{name}' generator warning: {e}")

        vol_float = self._volume / 100.0

        for name, (file_path, _) in sound_generators.items():
            try:
                effect = QSoundEffect(self)
                effect.setSource(QUrl.fromLocalFile(file_path))
                effect.setVolume(vol_float)
                self._effects[name] = effect
            except Exception as e:
                print(f"[SoundManager] Sound '{name}' load warning: {e}")

        # Dedicated voice pool for UI click feedback (4 round-robin voices prevents clipping)
        click_path = os.path.join(self.sounds_dir, "click.wav")
        self._click_voices = []
        if os.path.exists(click_path):
            click_url = QUrl.fromLocalFile(click_path)
            for _ in range(4):
                try:
                    voice = QSoundEffect(self)
                    voice.setSource(click_url)
                    voice.setVolume(vol_float)
                    self._click_voices.append(voice)
                except Exception:
                    pass

        try:
            with open(version_file, "w", encoding="utf-8") as f:
                f.write(str(SOUND_VERSION))
        except Exception:
            pass

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)

    def is_enabled(self) -> bool:
        return self._enabled

    def set_volume(self, volume: int):
        self._volume = max(0, min(100, int(volume)))
        vol_float = self._volume / 100.0
        for effect in self._effects.values():
            try:
                effect.setVolume(vol_float)
            except Exception:
                pass
        for voice in self._click_voices:
            try:
                voice.setVolume(vol_float)
            except Exception:
                pass

    def get_volume(self) -> int:
        return self._volume

    def play(self, sound_name: str, force: bool = False):
        if not self._enabled and not force:
            return
        if sound_name == "click":
            self.play_click(force=force)
            return

        now = time.time()
        last_t = self._last_sound_times.get(sound_name, 0.0)
        if now - last_t < getattr(self, "_sound_cooldown", 0.14):
            return
        self._last_sound_times[sound_name] = now

        effect = self._effects.get(sound_name)
        if effect:
            try:
                if effect.isPlaying():
                    effect.stop()
                effect.play()
            except Exception:
                pass

    def play_click(self, force: bool = False):
        if not self._enabled and not force:
            return
        now = time.time()
        # 50ms debounce
        if now - self._last_click_time < 0.05:
            return
        self._last_click_time = now

        if self._click_voices:
            try:
                voice = self._click_voices[self._click_voice_idx % len(self._click_voices)]
                self._click_voice_idx += 1
                if voice.isPlaying():
                    voice.stop()
                voice.play()
                return
            except Exception:
                pass

        eff = self._effects.get("click")
        if eff:
            try:
                if eff.isPlaying():
                    eff.stop()
                eff.play()
            except Exception:
                pass

    def play_launch(self, force: bool = False):
        self.play("launch", force=force)

    def play_levelup(self, force: bool = False):
        self.play("levelup", force=force)

    def play_error(self, force: bool = False):
        self.play("error", force=force)

    def play_door_open(self, force: bool = False):
        self.play("door_open", force=force)

    def play_door_close(self, force: bool = False):
        self.play("door_close", force=force)

    def play_book_flip(self, force: bool = False):
        self.play("book_flip", force=force)

    def play_enderchest_open(self, force: bool = False):
        self.play("enderchest_open", force=force)

    def play_enderchest_close(self, force: bool = False):
        self.play("enderchest_close", force=force)

    def play_break(self, force: bool = False):
        if not self._enabled and not force:
            return
        self.play("break", force=force)
        try:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1000, lambda: self.play("fizz", force=force))
        except Exception:
            pass

    def play_fizz(self, force: bool = False):
        self.play("fizz", force=force)

    def play_beacon_activate(self, force: bool = False):
        self.play("beacon_activate", force=force)

    def play_beacon_deactivate(self, force: bool = False):
        self.play("beacon_deactivate", force=force)

    def play_challenge_complete(self, force: bool = False):
        self.play("challenge_complete", force=force)

    def play_amethyst_shimmer(self, force: bool = False):
        self.play("amethyst_shimmer", force=force)

    def play_enchant(self, force: bool = False):
        self.play("enchant", force=force)

    def play_pop(self, force: bool = False):
        self.play("pop", force=force)

    def play_teleport(self, force: bool = False):
        self.play("teleport", force=force)

    def play_lever_on(self, force: bool = False):
        self.play("lever_on", force=force)

    def play_lever_off(self, force: bool = False):
        self.play("lever_off", force=force)

    def play_lever(self, is_on: bool, force: bool = False):
        if is_on:
            self.play_lever_on(force=force)
        else:
            self.play_lever_off(force=force)

    def play_bookshelf_insert(self, force: bool = False):
        self.play("bookshelf_insert", force=force)

    play_subtab = play_bookshelf_insert

    @classmethod
    def safe_click(cls):
        """Safe 1-line helper to play UI click sound without caller try/except boilerplate."""
        try:
            cls.get_instance().play_click()
        except Exception:
            pass

    @classmethod
    def safe_error(cls):
        """Safe 1-line helper to play UI error sound without caller try/except boilerplate."""
        try:
            cls.get_instance().play_error()
        except Exception:
            pass

    @classmethod
    def safe_play(cls, sound_name: str, force: bool = False):
        """Safe 1-line helper to play any registered sound effect safely."""
        try:
            inst = cls.get_instance()
            inst.play(sound_name, force=force)
        except Exception:
            pass

