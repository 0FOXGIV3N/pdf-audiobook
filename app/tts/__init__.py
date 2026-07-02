import os

from .kokoro import KokoroTTS


def get_tts(provider: str | None = None):
    provider = (provider or os.getenv("TTS_PROVIDER", "kokoro")).strip().lower()

    if provider == "kokoro":
        return KokoroTTS(
            lang_code=os.getenv("KOKORO_LANG", "a"),
            voice=os.getenv("VOICE", "af_heart"),
            speed=float(os.getenv("SPEED", "1.0")),
        )

    raise ValueError(f"Unsupported TTS provider: {provider}")
