"""Azulejos voice commands: wake word, fixed commands, glazes and amounts.

Three layers turn speech into a tile action (see voice.py):
  1. fixed commands  - parse_rules(): offline word matching, instant
  2. free phrasing   - voice_ai.interpret(): Whisper + a language model
  3. speech+pointing - "delete THIS": the fingertip at the moment "this" is said

Every layer produces the same intent dict, e.g.
  {"action": "set_symmetry", "symmetry": "+"}
  {"action": "glaze", "glaze": "cobalt", "target": "pen"}
  {"action": "scale_motif", "direction": "bigger", "amount": "small"}
and resolve_scale() turns vague amounts into numbers using the tile's size.
"""
import re
import shutil
import subprocess
import sys

WAKE_SKELETON = "slhs"     # consonant pattern of "azulejos": a-Z-u-L-e-J-o-S
AWAKE_SECONDS = 6.0        # after the wake word alone, listen this long for a command

ACTIONS = ["set_symmetry", "set_mode", "undo", "clear", "save", "glaze", "delete",
           "scale_motif", "rotate_motif", "set_tile_size", "query", "unknown"]

# Traditional tile glaze pigments. Hex values are approximate screen colours.
GLAZES = {
    "cobalt": "#1B2A9C",       # blue
    "manganese": "#5B3A55",    # purple-brown
    "copper": "#2E7D5B",       # green
    "antimony": "#D9A92B",     # yellow
    "ochre": "#C4692B",        # orange-brown (iron)
    "black": "#22201E",
}
GLAZE_WORDS = {
    "cobalt": "cobalt", "blue": "cobalt",
    "manganese": "manganese", "purple": "manganese", "brown": "manganese",
    "copper": "copper", "green": "copper",
    "antimony": "antimony", "yellow": "antimony",
    "ochre": "ochre", "orange": "ochre", "okra": "ochre", "oker": "ochre",
    "black": "black",
}

# vague amounts -> fraction of the motif's current size
AMOUNTS = {"tiny": 0.03, "small": 0.07, "medium": 0.15, "large": 0.30}
AMOUNT_WORDS = [
    ("a tiny bit", "tiny"), ("a touch", "tiny"), ("tiny", "tiny"),
    ("a little", "small"), ("a bit", "small"), ("slightly", "small"), ("little", "small"),
    ("a lot", "large"), ("much", "large"), ("way", "large"), ("really", "large"),
    ("quite", "medium"), ("more", "medium"),
]
DEGREE_AMOUNTS = {"tiny": 3, "small": 10, "medium": 22.5, "large": 45}

NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}

POINTING_WORDS = ("this", "that", "these", "those", "here")


def next_glaze(glaze):
    """The glaze after this one, for 'change colour'."""
    names = list(GLAZES)
    return names[(names.index(glaze) + 1) % len(names)]


# ---------------------------------------------------------------- wake word
def skeleton(text):
    """Consonant pattern of how a phrase sounds: 'as you lay hose' -> 'slhs'."""
    s = re.sub(r"[^a-z]", "", text.lower())
    s = s.replace("ph", "f").replace("z", "s").replace("j", "h").replace("x", "ks")
    s = re.sub(r"[aeiouyw]", "", s)
    return re.sub(r"(.)\1+", r"\1", s)


def find_wake(text):
    """(found, rest_of_text). Matches 'azulejos' and sound-alikes such as
    'as you lay hose', 'a zoo lay house', 'is you lay hoes'."""
    words = [w for w in text.lower().split() if w != "[unk]"]
    fillers = {"a", "as", "hose", "house", "hoes", "los", "is", "his", "us", "oh", "so", "lay", "you"}
    for i, w in enumerate(words):
        if w == "azul":                      # closed-vocabulary hearing of "Azulejos"
            j = i + 1
            while j < len(words) and words[j] in fillers:
                j += 1
            return True, " ".join(words[j:])
    for i in range(len(words)):
        for n in (1, 2, 3, 4):
            chunk = words[i:i + n]
            if len(chunk) < n:
                break
            sk = skeleton(" ".join(chunk))
            if sk == WAKE_SKELETON or sk in (WAKE_SKELETON + "t", WAKE_SKELETON + "d"):
                return True, " ".join(words[i + n:])
    return False, text


# ---------------------------------------------------------------- numbers
def words_to_number(text):
    """First number in the text, from digits or words ('two hundred and ten' -> 210)."""
    m = re.search(r"\d+(\.\d+)?", text)
    if m:
        return float(m.group())
    total, current, found = 0, 0, False
    for w in text.lower().replace("-", " ").split():
        if w in NUMBER_WORDS:
            current += NUMBER_WORDS[w]
            found = True
        elif w == "hundred" and found:
            current = max(current, 1) * 100
        elif w == "thousand" and found:
            total += max(current, 1) * 1000
            current = 0
        elif w == "and" and found:
            continue
        elif found:
            break
    return float(total + current) if found else None


def has(text, *phrases):
    t = f" {text} "
    return any(f" {p} " in t for p in phrases)


def amount_of(text):
    for phrase, amount in AMOUNT_WORDS:
        if has(text, phrase):
            return amount
    return "medium"


def target_of(text):
    if has(text, *POINTING_WORDS, "this one", "that one"):
        return "this"
    if has(text, "everything", "all", "whole", "all of it"):
        return "all"
    if has(text, "last", "last one", "previous"):
        return "last"
    return None


# ---------------------------------------------------------------- layer 1
def parse_rules(text):
    """Fixed commands, matched offline. Returns an intent dict or None."""
    t = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    t = " ".join(t.split())
    if not t:
        return None

    # tile size first, so "tile eight centimetres" is not read as eight-fold
    if has(t, "tile") and (has(t, "millimetres", "millimeters", "mm", "centimetres",
                                "centimeters", "cm")):
        n = words_to_number(t)
        if n:
            mm = n * 10 if has(t, "centimetres", "centimeters", "cm") else n
            return {"action": "set_tile_size", "millimetres": mm}

    # symmetry
    if has(t, "eight fold", "eightfold", "eight", "8", "rosette", "star", "radial"):
        return {"action": "set_symmetry", "symmetry": "*"}
    if has(t, "quadrants", "quadrant", "quarters", "plus"):
        return {"action": "set_symmetry", "symmetry": "+"}
    if has(t, "triangles", "triangle", "diagonals", "diagonal", "x", "ex", "cross"):
        return {"action": "set_symmetry", "symmetry": "X"}
    if has(t, "no symmetry", "symmetry off", "no mirror", "free drawing"):
        return {"action": "set_symmetry", "symmetry": "none"}

    # editing
    if has(t, "undo", "go back", "take that back", "oops"):
        return {"action": "undo"}
    if has(t, "clear", "start again", "start over", "erase everything", "wipe"):
        return {"action": "clear"}
    if has(t, "save", "send to rhino", "send it", "export", "send"):
        return {"action": "save"}

    # glaze colours
    for word, glaze in GLAZE_WORDS.items():
        if has(t, word):
            return {"action": "glaze", "glaze": glaze, "target": target_of(t) or "pen"}

    # "change colour" with no colour named: step to the next glaze
    if has(t, "colour", "color") and has(t, "change", "next", "different"):
        return {"action": "glaze", "glaze": "next", "target": target_of(t) or "pen"}

    # mirror / rotate copies (only when no amount is given, else it is a motif turn)
    if has(t, "rotate", "rotation", "turn") and not has(t, "bit", "little", "degrees", "more", "it", "this"):
        return {"action": "set_mode", "mode": "rotate"}
    if has(t, "mirror", "reflect", "reflection"):
        return {"action": "set_mode", "mode": "mirror"}

    # simple backups for layer 2, so the basics work without the AI
    if has(t, "delete", "remove"):
        return {"action": "delete", "target": target_of(t) or "this"}
    if has(t, "bigger", "larger", "smaller", "grow", "shrink"):
        direction = "bigger" if has(t, "bigger", "larger", "grow") else "smaller"
        return {"action": "scale_motif", "direction": direction, "amount": amount_of(t),
                "target": target_of(t) or "all"}
    if has(t, "how big", "what size", "size"):
        return {"action": "query", "question": "size"}
    if has(t, "which symmetry", "what symmetry"):
        return {"action": "query", "question": "symmetry"}
    return None


# ---------------------------------------------------------------- amounts
def resolve_scale(intent, motif_size_mm=None):
    """Scale factor for a scale_motif intent, aware of the motif's real size.

    'a bit bigger' -> +7%; 'much smaller' -> -30%; '2 cm bigger' on a motif
    that is 100 mm across -> +20%. Exact percentages are used as given.
    """
    sign = 1 if intent.get("direction", "bigger") == "bigger" else -1
    if intent.get("percent"):
        return max(0.1, 1 + sign * float(intent["percent"]) / 100)
    if intent.get("millimetres") and motif_size_mm:
        return max(0.1, 1 + sign * float(intent["millimetres"]) / motif_size_mm)
    amount = intent.get("amount", "medium")
    if amount == "double":
        return 2.0 if sign > 0 else 0.5
    if amount == "half":
        return 0.5
    return max(0.1, 1 + sign * AMOUNTS.get(amount, AMOUNTS["medium"]))


def resolve_degrees(intent):
    """Turn angle in degrees for a rotate_motif intent (clockwise positive)."""
    sign = -1 if intent.get("direction") == "anticlockwise" else 1
    if intent.get("degrees"):
        return sign * float(intent["degrees"])
    return sign * DEGREE_AMOUNTS.get(intent.get("amount", "small"), 10)


# ---------------------------------------------------------------- speaking
def speak(text):
    """Say text out loud (macOS 'say'), without blocking the camera loop."""
    if sys.platform == "darwin" and shutil.which("say"):
        try:
            subprocess.Popen(["say", "-r", "200", text],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass


def describe(intent):
    """Short text for what Azulejos understood."""
    a = intent.get("action")
    if a == "set_symmetry":
        return {"+": "mirror quadrants", "X": "mirror triangles", "*": "eight fold",
                "none": "no symmetry"}.get(intent.get("symmetry"), "symmetry")
    if a == "set_mode":
        return "rotate copies" if intent.get("mode") == "rotate" else "mirror copies"
    if a == "glaze":
        where = {"pen": "", "this": " this line", "all": " everything", "last": " last line"}
        return f"{intent.get('glaze')}{where.get(intent.get('target', 'pen'), '')}"
    if a == "scale_motif":
        return f"{intent.get('direction', 'bigger')} ({intent.get('amount', 'medium')})"
    if a == "rotate_motif":
        return f"turn {intent.get('direction', 'clockwise')}"
    if a == "set_tile_size":
        return f"tile {intent.get('millimetres'):.0f} millimetres"
    if a == "delete":
        return f"delete {intent.get('target', 'this')}"
    return a.replace("_", " ")


# ---------------------------------------------------------------- grammar
# The English speech model has no word "azulejos". Listening for this fixed
# list instead of all of English makes Vosk map "Azulejos" onto the nearest
# sound-alike below, and makes the commands themselves far more reliable.
WAKE_SOUNDALIKES = [
    "azul", "as", "you", "lay", "hose", "house", "hoes", "zoo", "a", "is", "who",
    "hey", "his", "us", "oh", "so", "soul", "hello", "los", "this",
]
COMMAND_PHRASES = [
    "eight fold", "eightfold", "rosette", "star", "radial", "quadrants", "quadrant",
    "quarters", "plus", "triangles", "triangle", "diagonals", "diagonal", "cross",
    "no symmetry", "symmetry off", "no mirror", "free drawing", "mirror", "reflect",
    "rotate", "rotation", "turn", "undo", "go back", "take that back", "oops", "clear",
    "start again", "start over", "erase everything", "wipe", "save", "send to rhino",
    "send it", "export", "delete", "remove", "bigger", "larger", "smaller", "grow",
    "shrink", "make", "it", "the", "one", "line", "everything", "all", "whole", "last",
    "previous", "tile", "millimetres", "millimeters", "centimetres", "centimeters",
    "how big", "what size", "size", "which symmetry", "what symmetry", "colour", "color",
    "clockwise", "anticlockwise", "counterclockwise", "quarter", "half", "double",
    "degrees", "percent", "and", "to", "please", "more", "less", "rounder", "thicker",
    "change", "next", "different",
]


def grammar_words():
    """Every word Azulejos listens for (Vosk closed-vocabulary mode)."""
    words = set()
    groups = [WAKE_SOUNDALIKES, COMMAND_PHRASES, list(GLAZE_WORDS), list(NUMBER_WORDS),
              ["hundred", "thousand"], list(POINTING_WORDS),
              [p for p, _ in AMOUNT_WORDS]]
    for group in groups:
        for phrase in group:
            words.update(phrase.split())
    return sorted(words)
