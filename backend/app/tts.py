"""Natural speech on the server with Kokoro (82M-parameter open TTS, Apache-2.0).

iOS doesn't expose its good (Premium) voices to web apps, so replies are
synthesised here and streamed to the phone one sentence at a time. Runs on
CPU through onnxruntime; the fp16 model is 2-5x faster than real time on a
couple of cores. If the model files are missing, Camena falls back to the
phone's own voice.
"""

from __future__ import annotations

import io
import logging
import os
import re
import gc
import threading
import time
import wave
from pathlib import Path

log = logging.getLogger("camena.tts")

MODEL_FILE = "kokoro-v1.0.fp16.onnx"
VOICES_FILE = "voices-v1.0.bin"
MAX_CHARS = 600
IDLE_UNLOAD_SECONDS = 15 * 60  # the model holds ~300 MB; hosts like Railway bill memory by the minute

# A short, curated menu; Kokoro has ~50 voices, most of them non-English.
VOICES = [
    {"id": "af_heart", "name": "Heart", "accent": "American"},
    {"id": "af_bella", "name": "Bella", "accent": "American"},
    {"id": "af_nicole", "name": "Nicole (soft)", "accent": "American"},
    {"id": "af_sarah", "name": "Sarah", "accent": "American"},
    {"id": "am_michael", "name": "Michael", "accent": "American"},
    {"id": "am_fenrir", "name": "Fenrir", "accent": "American"},
    {"id": "am_puck", "name": "Puck", "accent": "American"},
    {"id": "bf_emma", "name": "Emma", "accent": "British"},
    {"id": "bf_isabella", "name": "Isabella", "accent": "British"},
    {"id": "bm_george", "name": "George", "accent": "British"},
    {"id": "bm_fable", "name": "Fable", "accent": "British"},
]
DEFAULT_VOICE = "af_heart"

# The first letter of a Kokoro voice id is its language.
LANGS = {"a": "en-us", "b": "en-gb", "e": "es", "f": "fr-fr", "h": "hi", "i": "it", "j": "ja", "p": "pt-br", "z": "cmn"}


def clean_for_speech(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # markdown links -> their label
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_`#>|]", "", text)
    return re.sub(r"\s+", " ", text).strip()[:MAX_CHARS]


def _return_memory_to_os() -> None:
    """glibc keeps freed heap pages; malloc_trim hands them back so the host stops billing them."""
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass


def to_wav(samples, sample_rate: int) -> bytes:
    import numpy as np

    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


class Speech:
    def __init__(self, model_dir: Path, threads: int | None = None):
        self.model_dir = model_dir
        self.threads = threads or min(4, os.cpu_count() or 1)
        self._kokoro = None
        self._load_lock = threading.Lock()
        self._synth_lock = threading.Lock()  # onnxruntime is fastest one call at a time here
        self.error: str | None = None
        self.last_used = 0.0
        self._loaded_at = 0.0

    @property
    def available(self) -> bool:
        return (self.model_dir / MODEL_FILE).exists() and (self.model_dir / VOICES_FILE).exists() and not self.error

    def load(self):
        """Load the model (about a second). Safe to call from several threads."""
        with self._load_lock:
            if self._kokoro is None:
                import onnxruntime as rt
                from kokoro_onnx import Kokoro

                opts = rt.SessionOptions()
                opts.intra_op_num_threads = self.threads
                opts.inter_op_num_threads = 1
                session = rt.InferenceSession(str(self.model_dir / MODEL_FILE), opts, providers=["CPUExecutionProvider"])
                self._kokoro = Kokoro.from_session(session, str(self.model_dir / VOICES_FILE))
                self._kokoro.create("Ready.", voice=DEFAULT_VOICE)  # warm-up: the first call is slow
                self._loaded_at = time.monotonic()
                log.info("Kokoro loaded with %d threads", self.threads)
            return self._kokoro

    def unload_if_idle(self, idle_seconds: float = IDLE_UNLOAD_SECONDS) -> bool:
        """Free the model's memory after a quiet spell; the next reply reloads it (~1 s)."""
        if self._kokoro is None or time.monotonic() - max(self.last_used, self._loaded_at) < idle_seconds:
            return False
        with self._load_lock, self._synth_lock:
            self._kokoro = None
        gc.collect()
        _return_memory_to_os()
        log.info("Kokoro unloaded after %d idle minutes", idle_seconds // 60)
        return True

    def warm(self) -> None:
        if not self.available:
            return
        try:
            self.load()
        except Exception as e:  # noqa: BLE001 - a broken model must not take the app down
            self.error = str(e)
            log.exception("Kokoro failed to load; phones will use their own voice")

    def synthesize(self, text: str, voice: str = DEFAULT_VOICE, speed: float = 1.0) -> bytes:
        text = clean_for_speech(text)
        if not text:
            raise ValueError("nothing to say")
        if voice not in {v["id"] for v in VOICES}:
            voice = DEFAULT_VOICE
        kokoro = self.load()
        self.last_used = time.monotonic()
        with self._synth_lock:
            samples, rate = kokoro.create(text, voice=voice, speed=max(0.7, min(1.4, speed)), lang=LANGS[voice[0]])
        return to_wav(samples, rate)
