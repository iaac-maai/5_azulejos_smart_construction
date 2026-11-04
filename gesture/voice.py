"""Azulejos voice listener: microphone -> wake word -> tile command.

Runs in the background while you draw. Say "azul" and then a command,
in one breath or within a few seconds:
    "azul, change colour"             "azul ... cobalt"
    "azul, make this bigger"          "azul, delete this" (while pointing)

How a sentence becomes a command:
  layer 1  fixed commands (voice_commands.parse_rules), offline and instant
  layer 2  anything else -> Whisper + language model (voice_ai.interpret)
  layer 3  if the sentence contains "this"/"that"/"here", the moment that word
           was spoken is attached, so the drawing can pick the line under the
           fingertip at exactly that moment

Speech recognition: Vosk small English model (offline, Apache 2.0). It is
downloaded into models/ on first run (about 40 MB).

Test the microphone without the camera:
    python gesture/voice.py           # listen and print commands
    python gesture/voice.py --text "azul make it a bit bigger"
"""
import json
import queue
import sys
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

import voice_ai
import voice_commands as vc

ROOT = Path(__file__).resolve().parent.parent
VOSK_DIR = ROOT / "models" / "vosk-model-small-en-us-0.15"
VOSK_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
RATE = 16000


@dataclass
class Command:
    intent: dict
    heard: str                    # what was understood, for the screen
    source: str                   # "rules", "Claude", "Ollama"
    pointed_at: float = None      # wall-clock time "this" was said, or None
    created: float = field(default_factory=time.time)


def ensure_vosk_model():
    if VOSK_DIR.exists():
        return VOSK_DIR
    VOSK_DIR.parent.mkdir(parents=True, exist_ok=True)
    archive = VOSK_DIR.parent / "vosk-small-en.zip"
    print("Downloading the Vosk speech model (about 40 MB)...")
    urllib.request.urlretrieve(VOSK_URL, archive)
    with zipfile.ZipFile(archive) as z:
        z.extractall(VOSK_DIR.parent)
    archive.unlink()
    return VOSK_DIR


def understand(text, context, audio=None, words=None, stream_start=None, use_ai=True,
               free_text=None):
    """One spoken sentence (after the wake word) -> Command or None.

    text       what the closed-vocabulary recogniser heard (commands)
    free_text  what the open recogniser heard (any English), for the AI
    """
    pointed_at = None
    for w in words or []:
        if w.get("word") in vc.POINTING_WORDS and stream_start is not None:
            pointed_at = stream_start + float(w.get("start", 0))
            break
    intent = vc.parse_rules(text)
    if intent:
        return Command(intent, text, "rules", pointed_at)
    if not use_ai:
        return None
    better = voice_ai.transcribe(audio) if audio else None
    sentence = better or free_text or text
    intent, source = voice_ai.interpret(sentence, context)
    if intent:
        if pointed_at is None and any(f" {p} " in f" {sentence.lower()} " for p in vc.POINTING_WORDS):
            pointed_at = time.time() - 1.0     # no word timing from Whisper: about 1 s ago
        return Command(intent, sentence, source, pointed_at)
    return Command({"action": "unknown"}, sentence, "none")


class VoiceListener(threading.Thread):
    """Background thread. Puts Command objects into self.commands."""

    def __init__(self, context_fn=dict, use_ai=True):
        super().__init__(daemon=True)
        self.commands = queue.Queue()
        self.context_fn = context_fn      # returns the tile state for the AI
        self.use_ai = use_ai
        self.partial = ""                 # live words, for the screen
        self.level = 0.0                  # microphone loudness 0..1
        self.heard = queue.Queue()        # (commands_text, free_text, woke) for debugging
        self.awake_until = 0.0
        self.said = ""                    # the last command heard, for the screen
        self.said_at = 0.0
        self.status = "starting"
        self._audio = queue.Queue()

    def _on_audio(self, data, frames, time_info, status):
        self._audio.put(bytes(data))

    def run(self):
        try:
            import sounddevice as sd
            from vosk import KaldiRecognizer, Model, SetLogLevel
        except ImportError as error:
            self.status = f"voice off ({error.name} not installed)"
            return
        SetLogLevel(-1)
        try:
            model = Model(str(ensure_vosk_model()))
        except Exception as error:
            self.status = f"voice off (speech model: {error})"
            return
        # closed vocabulary: wake word sound-alikes + command words, rest -> [unk]
        recogniser = KaldiRecognizer(model, RATE, json.dumps(vc.grammar_words() + ["[unk]"]))
        recogniser.SetWords(True)
        # open vocabulary: any English, used for free phrasing when Whisper is missing
        free = KaldiRecognizer(model, RATE)
        free_parts = []
        ai = ", ".join(voice_ai.available()) if self.use_ai else ""
        self.status = "listening - say 'azul' + command" + (f" | AI: {ai}" if ai else "")
        utterance = []
        stream_start = None
        try:
            with sd.RawInputStream(samplerate=RATE, blocksize=4000, dtype="int16",
                                   channels=1, callback=self._on_audio):
                while True:
                    data = self._audio.get()
                    if stream_start is None:
                        stream_start = time.time() - 0.25
                    utterance.append(data)
                    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                    self.level = min(1.0, float(np.sqrt(np.mean(samples ** 2))) / 3000.0)
                    if free.AcceptWaveform(data):
                        free_parts.append(json.loads(free.Result()).get("text", ""))
                    if recogniser.AcceptWaveform(data):
                        result = json.loads(recogniser.Result())
                        free_parts.append(json.loads(free.FinalResult()).get("text", ""))
                        free_text = " ".join(t for t in free_parts if t)
                        free_parts = []
                        self._on_sentence(result, b"".join(utterance), stream_start, free_text)
                        utterance = []
                        self.partial = ""
                    else:
                        self.partial = json.loads(recogniser.PartialResult()).get("partial", "")
                        if vc.find_wake(self.partial)[0]:     # show LISTENING while it is being said
                            self.awake_until = time.time() + vc.AWAKE_SECONDS
        except Exception as error:
            self.status = f"voice off (microphone: {error})"

    def _on_sentence(self, result, audio, stream_start, free_text=""):
        text = " ".join(w for w in result.get("text", "").split() if w != "[unk]")
        if not text and not free_text:
            return
        woke, rest = vc.find_wake(text)
        free_woke, free_rest = vc.find_wake(free_text)
        if not woke and free_woke:          # the open recogniser caught the wake word
            woke, rest = True, vc.find_wake(text)[1] if text else ""
        self.heard.put((text, free_text, woke))
        if woke and not rest and not (free_woke and free_rest):
            self.awake_until = time.time() + vc.AWAKE_SECONDS
            vc.speak("yes")
            return
        if not woke and time.time() > self.awake_until:
            return                      # ordinary talk in the room: ignore
        self.awake_until = 0.0
        command_text = rest if woke else text
        free_command = free_rest if free_woke else free_text
        self.said = command_text or free_command
        self.said_at = time.time()
        words = result.get("result", [])
        context = self.context_fn()
        # the AI step can take a second or two: run it beside the camera loop
        threading.Thread(target=self._understand, daemon=True,
                         args=(command_text, context, audio, words, stream_start, free_command)).start()

    def _understand(self, text, context, audio, words, stream_start, free_text):
        command = understand(text, context, audio, words, stream_start, self.use_ai, free_text)
        if command:
            self.commands.put(command)


def main():
    if "--text" in sys.argv:
        text = " ".join(sys.argv[sys.argv.index("--text") + 1:])
        woke, rest = vc.find_wake(text)
        print("wake word heard:", woke)
        command = understand(rest if woke else text, {"tile_mm": 200, "symmetry": "+"})
        print(command)
        if command:
            print("Azulejos:", vc.describe(command.intent))
        return
    listener = VoiceListener(context_fn=lambda: {"tile_mm": 200, "symmetry": "+"})
    listener.start()
    last = ""
    last_level = 0.0
    print("Starting voice... press Ctrl+C to stop")
    print("Every sentence it hears is printed; the bar shows the microphone level.")
    try:
        while True:
            if listener.status != last:
                print(listener.status)
                last = listener.status
            if time.time() - last_level > 1.0 and listener.status.startswith("listening"):
                bar = "#" * int(listener.level * 30)
                print(f"\r  mic {bar:<30}", end="", flush=True)
                last_level = time.time()
            while not listener.heard.empty():
                text, free_text, woke = listener.heard.get()
                print(f"\n  heard (commands): '{text}'   heard (any English): '{free_text}'"
                      f"   wake word: {'YES' if woke else 'no'}")
            try:
                c = listener.commands.get(timeout=0.2)
                print(f"[{c.source}] heard '{c.heard}' -> {c.intent}"
                      + (" (pointing)" if c.pointed_at else ""))
                vc.speak(vc.describe(c.intent))
            except queue.Empty:
                pass
            if not listener.is_alive() and "off" in listener.status:
                print(listener.status)
                break
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
