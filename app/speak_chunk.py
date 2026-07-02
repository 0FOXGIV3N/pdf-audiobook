import argparse
from pathlib import Path

from bootstrap import bootstrap_command
from tts import get_tts


def main():
    parser = argparse.ArgumentParser(description="Generate a WAV file from one narration chunk.")
    parser.add_argument("input_txt", help="Path to chunk .txt file inside the container")
    parser.add_argument("output_wav", help="Path to output .wav file inside the container")
    parser.add_argument("--voice", default=None, help="Kokoro voice name, e.g. af_heart")
    parser.add_argument("--speed", type=float, default=None, help="Speech speed")
    parser.add_argument("--quiet", action="store_true", help="Suppress startup banner")
    args = parser.parse_args()

    input_path = Path(args.input_txt)
    output_path = Path(args.output_wav)

    bootstrap_command(
        "speak_chunk",
        None,
        None,
        input_path,
        output_path,
        show_banner=not args.quiet,
    )

    if not input_path.exists():
        raise FileNotFoundError(f"Input chunk not found: {input_path}")

    text = input_path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Input chunk is empty: {input_path}")

    tts = get_tts("kokoro")
    written = tts.generate(text, output_path, voice=args.voice, speed=args.speed)

    print("Kokoro smoke test complete.")
    print(f"Input:  {input_path}")
    print(f"Output: {written}")


if __name__ == "__main__":
    main()
