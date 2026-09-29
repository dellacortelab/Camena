"""Server voice: routes always; real synthesis only when the model files are present."""

from __future__ import annotations

import io
import os
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app
from app.tts import Speech, clean_for_speech

MODEL_DIR = Path(os.environ.get("CAMENA_TEST_TTS_DIR", "/opt/kokoro"))


def test_clean_for_speech():
    text = "**Yes!** See [the menu](https://x.test/m) or https://y.test ```code``` # done"
    assert clean_for_speech(text) == "Yes! See the menu or done"


def _client(tmp_path, monkeypatch, tts_dir):
    monkeypatch.setenv("CAMENA_PASSCODE", "hunter22")
    monkeypatch.setenv("CAMENA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CAMENA_TTS_DIR", str(tts_dir))
    client = TestClient(create_app(load_settings(), start_scheduler=False))
    client.post("api/login", json={"passcode": "hunter22"})
    return client


def test_without_model_the_phone_voice_is_used(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, tmp_path / "no-model")
    assert client.get("api/tts/voices").json()["available"] is False
    assert client.post("api/tts", json={"text": "hi"}).status_code == 503


@pytest.mark.skipif(not (MODEL_DIR / "kokoro-v1.0.fp16.onnx").exists(), reason="Kokoro model not installed")
def test_real_synthesis_returns_wav(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, MODEL_DIR)
    voices = client.get("api/tts/voices").json()
    assert voices["available"] and voices["default"] == "af_heart"
    res = client.post("api/tts", json={"text": "Hello Dennis, the weather looks great.", "voice": "bf_emma"})
    assert res.status_code == 200 and res.headers["content-type"] == "audio/wav"
    with wave.open(io.BytesIO(res.content)) as w:
        assert w.getframerate() == 24000 and w.getnframes() / 24000 > 1.0
    assert client.post("api/tts", json={"text": "   "}).status_code == 400


@pytest.mark.skipif(not (MODEL_DIR / "kokoro-v1.0.fp16.onnx").exists(), reason="Kokoro model not installed")
def test_idle_unload_and_reload():
    speech = Speech(MODEL_DIR, threads=2)
    speech.synthesize("Hello.")
    assert not speech.unload_if_idle(idle_seconds=60)   # just used
    assert speech.unload_if_idle(idle_seconds=0)
    assert speech._kokoro is None
    assert len(speech.synthesize("Back again.")) > 1000  # reloads transparently
