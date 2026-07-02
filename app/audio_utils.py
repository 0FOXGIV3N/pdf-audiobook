from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, List, Tuple

import numpy as np
import soundfile as sf

ProgressCallback = Callable[[int, int, Path], None]


def read_wav(path: str | Path) -> Tuple[np.ndarray, int]:
    """Read a WAV file as float32 audio.

    Returns:
        (audio, sample_rate)

    Audio is always returned as a NumPy array. Mono files are returned as a
    one-dimensional array. Stereo/multichannel files are returned as a
    two-dimensional array.
    """
    path = Path(path)
    audio, sample_rate = sf.read(str(path), dtype="float32", always_2d=False)
    return np.asarray(audio, dtype=np.float32), int(sample_rate)


def write_wav(path: str | Path, audio: np.ndarray, sample_rate: int) -> None:
    """Write audio to a WAV file, creating parent folders if needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.asarray(audio, dtype=np.float32), int(sample_rate))


def silence(seconds: float, sample_rate: int, channels: int | None = None) -> np.ndarray:
    """Create a block of silence.

    Args:
        seconds: Duration in seconds.
        sample_rate: Audio sample rate.
        channels: Optional number of channels. If None or 1, mono silence is
            returned. If greater than 1, a 2D array is returned.
    """
    frames = max(0, int(round(float(seconds) * int(sample_rate))))
    if channels and channels > 1:
        return np.zeros((frames, channels), dtype=np.float32)
    return np.zeros(frames, dtype=np.float32)


def concat_audio(parts: Iterable[np.ndarray]) -> np.ndarray:
    """Concatenate audio arrays after removing empty parts."""
    clean_parts: List[np.ndarray] = []
    for part in parts:
        arr = np.asarray(part, dtype=np.float32)
        if arr.size:
            clean_parts.append(arr)

    if not clean_parts:
        return np.zeros(0, dtype=np.float32)

    return np.concatenate(clean_parts, axis=0)


def concat_wavs(
    wav_paths: Iterable[str | Path],
    output_wav: str | Path,
    gap_seconds: float = 0.0,
    crossfade_ms: int = 0,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    """Concatenate WAV files in order and write one output WAV.

    This performs strict sample-rate validation. If one source WAV differs in
    sample rate, the function raises an error rather than silently resampling.

    Args:
        wav_paths: Ordered source WAV paths.
        output_wav: Destination WAV path.
        gap_seconds: Optional silence inserted between source files.
        crossfade_ms: Reserved future hook. Must currently be 0.
        progress_callback: Optional callback called after each source WAV is read.
    """
    if int(crossfade_ms) != 0:
        raise NotImplementedError("crossfade_ms is reserved for a future release; use 0 for now.")

    paths = [Path(p) for p in wav_paths]
    if not paths:
        raise ValueError("No WAV files were provided for stitching.")

    audio_parts: List[np.ndarray] = []
    sample_rate: int | None = None
    channels: int | None = None

    for index, path in enumerate(paths, start=1):
        if not path.exists():
            raise FileNotFoundError(f"Missing WAV file: {path}")

        audio, sr = read_wav(path)
        if sample_rate is None:
            sample_rate = sr
            channels = audio.shape[1] if audio.ndim == 2 else 1
        elif sr != sample_rate:
            raise ValueError(
                f"Sample-rate mismatch while stitching. Expected {sample_rate}, "
                f"got {sr}: {path}"
            )

        audio_parts.append(audio)

        if progress_callback:
            progress_callback(index, len(paths), path)

        if gap_seconds > 0 and index < len(paths):
            audio_parts.append(silence(gap_seconds, sample_rate, channels))

    final_audio = concat_audio(audio_parts)
    if sample_rate is None:
        raise RuntimeError("Could not determine sample rate while stitching WAVs.")

    write_wav(output_wav, final_audio, sample_rate)

    return {
        "output_file": str(Path(output_wav)),
        "input_files": len(paths),
        "sample_rate": sample_rate,
        "duration_seconds": round(len(final_audio) / sample_rate, 2),
        "gap_seconds": float(gap_seconds),
        "crossfade_ms": int(crossfade_ms),
    }
