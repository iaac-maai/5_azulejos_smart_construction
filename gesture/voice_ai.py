"""Azulejos voice, layer 2: understand free phrasing with AI.

When a spoken command is not one of the fixed commands, two AI steps run:
  1. Whisper (faster-whisper, offline after the first download) re-transcribes
     the recorded audio more accurately than the small live recogniser.
  2. A language model turns the sentence into one structured tile command,
     using the tile's current state as context (size, symmetry, glazes).
     Claude is used when ANTHROPIC_API_KEY is set; otherwise a local Ollama
     model (http://localhost:11434) if it is running.

The model only chooses the command and a vague amount ("small", "large");
voice_commands.resolve_scale() converts that into numbers using the motif's
real size. If the request is unclear, the model returns a short question,
which Azulejos speaks back instead of guessing.

Settings (environment variables, all optional):
  AZULEJOS_CLAUDE_MODEL   default claude-haiku-5-5
  AZULEJOS_OLLAMA_MODEL   default llama3.2
  AZULEJOS_WHISPER_MODEL  default base.en
"""
import json
import os
import urllib.request

import numpy as np

from voice_commands import ACTIONS, GLAZES

CLAUDE_MODEL = os.environ.get("AZULEJOS_CLAUDE_MODEL", "claude-haiku-5-5")
OLLAMA_MODEL = os.environ.get("AZULEJOS_OLLAMA_MODEL", "llama3.2")
OLLAMA_URL = "http://localhost:11434/api/chat"
WHISPER_MODEL = os.environ.get("AZULEJOS_WHISPER_MODEL", "base.en")

SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ACTIONS},
        "symmetry": {"type": "string", "enum": ["+", "X", "*", "none"],
                     "description": "+ quadrants, X triangles, * eight-fold"},
        "mode": {"type": "string", "enum": ["mirror", "rotate"]},
        "glaze": {"type": "string", "enum": list(GLAZES)},
        "target": {"type": "string", "enum": ["this", "last", "all", "pen"],
                   "description": "this = the line the artisan points at; pen = future lines"},
        "direction": {"type": "string",
                      "enum": ["bigger", "smaller", "clockwise", "anticlockwise"]},
        "amount": {"type": "string",
                   "enum": ["tiny", "small", "medium", "large", "double", "half"]},
        "percent": {"type": "number"},
        "millimetres": {"type": "number"},
        "degrees": {"type": "number"},
        "question": {"type": "string", "enum": ["size", "symmetry", "glaze", "strokes"]},
        "clarify": {"type": "string",
                    "description": "If the request is ambiguous, one short question to ask back"},
    },
    "required": ["action"],
}

SYSTEM = """You turn a tile artisan's spoken request into ONE command for Azulejos,
a gesture-and-voice tool for designing ceramic tiles. The artisan draws a motif
with their finger; the motif is mirrored or rotated across the tile.

Actions:
- set_symmetry: + (mirror across quadrants), X (mirror across triangles/diagonals),
  * (eight-fold rosette), none
- set_mode: mirror or rotate the copies
- undo, clear, save (save also sends the design to Rhino)
- glaze: colour lines. glazes: cobalt=blue, manganese=purple/brown, copper=green,
  antimony=yellow, ochre=orange, black. target pen = lines drawn from now on.
- delete: remove a line (target this = the one being pointed at, last = the newest)
- scale_motif: direction bigger/smaller. Use amount for vague words
  (a touch=tiny, a bit/slightly=small, quite=medium, much/a lot=large,
  double/half), or percent or millimetres when a number is said.
- rotate_motif: direction clockwise/anticlockwise, amount or degrees
  ("quarter turn" = 90 degrees)
- set_tile_size: millimetres (convert cm to mm)
- query: question size/symmetry/glaze/strokes
- unknown: nothing fits

Words like "this", "that", "here" mean the line the artisan is pointing at:
use target "this". Ignore the wake word ("azul" or "azulejos") and filler words.
If the request is genuinely ambiguous, use action unknown and put one short
question in clarify. Never invent numbers that were not said."""


# ---------------------------------------------------------------- Whisper
_whisper = None


def transcribe(audio_bytes, sample_rate=16000):
    """Better transcript of one utterance (16-bit mono audio), or None."""
    global _whisper
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    if _whisper is None:
        _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    if sample_rate != 16000 or len(audio) < 1600:
        return None
    segments, _ = _whisper.transcribe(audio, language="en", beam_size=1,
                                      initial_prompt="Azulejos, tile, cobalt, quadrants, mirror")
    text = " ".join(s.text for s in segments).strip()
    return text or None


# ---------------------------------------------------------------- language model
def _ask_claude(text, context):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None
    client = anthropic.Anthropic()
    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=300,
        system=SYSTEM,
        tools=[{"name": "tile_command", "description": "One Azulejos tile command",
                "input_schema": SCHEMA}],
        tool_choice={"type": "tool", "name": "tile_command"},
        messages=[{"role": "user", "content":
                   f"Tile state: {json.dumps(context)}\nArtisan said: \"{text}\""}],
    )
    for block in message.content:
        if getattr(block, "type", "") == "tool_use":
            return dict(block.input)
    return None


def _ask_ollama(text, context):
    body = json.dumps({
        "model": OLLAMA_MODEL,
        "stream": False,
        "format": SCHEMA,
        "options": {"temperature": 0},
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content":
                      f"Tile state: {json.dumps(context)}\nArtisan said: \"{text}\""}],
    }).encode()
    request = urllib.request.Request(OLLAMA_URL, data=body,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            reply = json.loads(response.read())
    except OSError:
        return None
    try:
        return json.loads(reply["message"]["content"])
    except (KeyError, ValueError):
        return None


def clean(intent):
    """Keep only valid fields from a model's answer."""
    if not isinstance(intent, dict) or intent.get("action") not in ACTIONS:
        return None
    allowed = SCHEMA["properties"]
    out = {}
    for key, value in intent.items():
        spec = allowed.get(key)
        if spec is None or value in (None, ""):
            continue
        if "enum" in spec and value not in spec["enum"]:
            continue
        if spec["type"] == "number":
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
        out[key] = value
    return out


def interpret(text, context):
    """(intent, source) for a free sentence; intent is None if no model answered."""
    for name, ask in (("Claude", _ask_claude), ("Ollama", _ask_ollama)):
        try:
            intent = clean(ask(text, context))
        except Exception as error:  # a failing model should never stop drawing
            print(f"Azulejos voice: {name} failed: {error}")
            intent = None
        if intent:
            return intent, name
    return None, None


def available():
    """Which AI pieces are ready, for the start-up message."""
    parts = []
    try:
        import faster_whisper  # noqa: F401
        parts.append("Whisper")
    except ImportError:
        pass
    if os.environ.get("ANTHROPIC_API_KEY"):
        parts.append("Claude")
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=0.5)
        parts.append("Ollama")
    except OSError:
        pass
    return parts
