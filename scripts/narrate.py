"""Narration for the demo video: one audio file per row of docs/video-script.md, read by Gemini TTS on Vertex AI.

    .venv\\Scripts\\python scripts\\narrate.py            # every row
    .venv\\Scripts\\python scripts\\narrate.py 0:42 1:36  # only these rows, to redo a line

Files land in video/narration/ (gitignored) as 0000.wav, 0008.wav ... named by the row's time, each sped up by
SPEED with ffmpeg (atempo keeps the pitch), plus all.wav: every row in order with a short pause between them.
"""
import re
import subprocess
import sys
import time
from pathlib import Path

from google.genai import types

from carpevigor import llm

MODEL = "gemini-3.8-flash-tts"
VOICE = "Algieba"
SPEED = 1.0  # read at about 160 words a minute already (2 Nov 2026): faster lost non-native listeners
PAUSE = 0.6  # seconds of silence between rows in all.wav
# Only the line goes to the model, no direction on how to say it: the TTS model read directions aloud, long or short
# ("Say in a low voice: ..." came back spoken, 2 Nov 2026). The voice itself carries the tone; Carpe Class did the same.

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "docs" / "video-script.md"
OUT = ROOT / "video" / "narration"


def rows() -> list[tuple[str, str]]:
    """(time, voice) for each table row of the script, in order."""
    found = re.findall(r"^\| (\d:\d\d) \|[^|]*\| (.+?) \|$", SCRIPT.read_text(encoding="utf-8"), re.M)
    if not found:
        raise SystemExit(f"No rows found in {SCRIPT}: has the table layout changed?")
    return found


def speak(text: str) -> bytes:
    settings = types.GenerateContentConfig(response_modalities=["AUDIO"], speech_config=types.SpeechConfig(
        voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE))))
    # 17 lines in a row hit the per-minute quota (2 Nov 2026): same waits as the app's own calls
    for wait in llm.RETRY_WAITS + (None,):
        try:
            answer = llm._client().models.generate_content(model=MODEL, contents=text, config=settings)
            break
        except Exception as error:
            if wait is None or getattr(error, "code", None) not in llm.RETRIED:
                raise
            time.sleep(wait)
    audio = answer.candidates[0].content.parts[0].inline_data
    if audio.mime_type != "audio/wav":
        raise SystemExit(f"Expected audio/wav from {MODEL}, got {audio.mime_type}")
    return audio.data


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def main(only: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    script = rows()
    for time, text in script:
        if only and time not in only:
            continue
        raw = OUT / f"raw-{time.replace(':', '')}.wav"
        raw.write_bytes(speak(text))
        done = OUT / f"{time.replace(':', '').zfill(4)}.wav"
        # silence trimmed at both ends (the model pads some lines by seconds), then sped up
        trim = "silenceremove=start_periods=1:start_threshold=-45dB"
        ffmpeg("-i", str(raw), "-filter:a", f"{trim},areverse,{trim},areverse,atempo={SPEED}", str(done))
        raw.unlink()
        print(time, done.name)
    # all.wav from every row present, so a single redone line rebuilds the whole track
    parts = [OUT / f"{t.replace(':', '').zfill(4)}.wav" for t, _ in script]
    missing = [p.name for p in parts if not p.exists()]
    if missing:
        raise SystemExit(f"all.wav not built, rows missing: {', '.join(missing)}")
    silence = OUT / "pause.wav"
    ffmpeg("-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", str(PAUSE), str(silence))
    listing = OUT / "list.txt"
    listing.write_text("".join(f"file '{p.name}'\nfile 'pause.wav'\n" for p in parts), encoding="utf-8")
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(listing), "-c:a", "pcm_s16le", "-ar", "24000", "-ac", "1",
           str(OUT / "all.wav"))
    print("all.wav")


if __name__ == "__main__":
    main(sys.argv[1:])
