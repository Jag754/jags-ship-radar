"""Turn log ship codes like ANVL_Hornet into readable names."""

import re

MANUFACTURERS = {
    "AEGS": "Aegis",
    "ANVL": "Anvil",
    "AOPOA": "Aopoa",
    "ARGO": "Argo",
    "BANU": "Banu",
    "CNOU": "C.O.",
    "CRUS": "Crusader",
    "DRAK": "Drake",
    "ESPR": "Esperia",
    "GAMA": "Gatac",
    "GRIN": "Greycat",
    "KRIG": "Kruger",
    "MISC": "MISC",
    "MRAI": "Mirai",
    "ORIG": "Origin",
    "RSI": "RSI",
    "TMBL": "Tumbril",
    "VNCL": "Vanduul",
    "XIAN": "Aopoa",
    "XNAA": "Aopoa",
}

OVERRIDES = {
    "ANVL_Pisces_Rescue": "Anvil C8R Pisces Rescue",
    "ARGO_RAFT": "Argo RAFT",
    "GRIN_STV": "Greycat STV",
    "Krig_l22_alphawolf": "Kruger L-22 Alpha Wolf",
    "MISC_Freelancer_MAX": "MISC Freelancer MAX",
    "RSI_Constellation_Andromeda_GS": "RSI Constellation Andromeda GS",
    "RSI_Constellation_Mk5_Centaurus": "RSI Constellation Centaurus",
}


def _word(w):
    return w[0].upper() + w[1:] if w and w.islower() else w


def pretty_name(code, overrides=None):
    if overrides and code in overrides:
        return overrides[code]
    if code in OVERRIDES:
        return OVERRIDES[code]
    maker, _, model = code.partition("_")
    maker = MANUFACTURERS.get(maker.upper(), _word(maker))
    model = " ".join(_word(w) for w in model.split("_") if w)
    return f"{maker} {model}".strip()


def tokens(text):
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t}


def model_tokens(code, overrides=None):
    """Words that identify the model, without the manufacturer, for matching channel names."""
    name = pretty_name(code, overrides)
    maker = MANUFACTURERS.get(code.partition("_")[0].upper(), "")
    return tokens(name) - tokens(maker)
