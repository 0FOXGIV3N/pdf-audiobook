import os
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import soundfile as sf
from kokoro import KPipeline

from .base import TTSProvider
from .text_normalizer import normalize_for_tts, split_tts_segments


class KokoroTTS(TTSProvider):
    """
    Kokoro TTS provider.

    v3.2.2:
    - Accepts voice= and speed= at generate() time for compatibility with speak_chunk.py.
    - Keeps segmented generation with real silence between heading/subtitle/body.
    - Keeps text normalization through text_normalizer.py.
    """

    def __init__(self, voice=None, speed=None, lang_code=None, sample_rate=24000):
        self.voice = voice or os.getenv("KOKORO_VOICE", os.getenv("VOICE", "af_heart"))
        self.speed = float(speed if speed is not None else os.getenv("KOKORO_SPEED", os.getenv("SPEED", "1.0")))
        self.lang_code = lang_code or os.getenv("KOKORO_LANG", "a")
        self.sample_rate = int(os.getenv("KOKORO_SAMPLE_RATE", str(sample_rate)))
        self.pause_seconds = float(os.getenv("KOKORO_SEGMENT_PAUSE", "0.45"))

        self.pipeline = KPipeline(lang_code=self.lang_code)

    def generate(
        self,
        text: str,
        output_file,
        voice: Optional[str] = None,
        speed: Optional[float] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        output_file = Path(output_file)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        active_voice = voice or self.voice
        active_speed = float(speed if speed is not None else self.speed)

        segments = split_tts_segments(text)
        if not segments:
            segments = [normalize_for_tts(text)]

        audio_parts = []
        silence = np.zeros(int(self.sample_rate * self.pause_seconds), dtype=np.float32)

        for idx, segment in enumerate(segments):
            segment = normalize_for_tts(segment)
            if not segment:
                continue

            generated_any = False

            for _, _, audio in self.pipeline(
                segment,
                voice=active_voice,
                speed=active_speed,
            ):
                generated_any = True
                audio_np = np.asarray(audio, dtype=np.float32)
                if audio_np.size:
                    audio_parts.append(audio_np)

            if generated_any and idx < len(segments) - 1:
                audio_parts.append(silence)

        if not audio_parts:
            raise RuntimeError("Kokoro produced no audio for this chunk.")

        final_audio = np.concatenate(audio_parts)
        sf.write(str(output_file), final_audio, self.sample_rate)

        return {
            "output_file": str(output_file),
            "segments": len(segments),
            "sample_rate": self.sample_rate,
            "duration_seconds": round(len(final_audio) / self.sample_rate, 2),
            "voice": active_voice,
            "speed": active_speed,
        }
