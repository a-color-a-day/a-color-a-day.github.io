import json
import random
from datetime import datetime, timezone
import os
import requests
from PIL import Image
import io
import colorsys

SITE_URL = "https://a-color-a-day.github.io/infinity/"


# Wie genau muss ein bekannter Farbname zur Farbe passen?
# 0   = nur exakt derselbe Hex-Code (trifft nur etwa alle 1,5 Jahre)
# 1.0 = für das Auge nicht unterscheidbar (trifft etwa jeden 10. Tag)  <- Standard
# 2.0 = kaum unterscheidbar (trifft etwa jeden 2. Tag)
NAME_MATCH_TOLERANCE = 1.0

_database_cache = None
_named_labs_cache = None


def load_color_database():
    """Lädt die Farbnamen-Datenbank (color_database.json, Hex-Code -> Name)."""
    global _database_cache
    if _database_cache is None:
        try:
            with open('color_database.json', 'r', encoding='utf-8') as f:
                _database_cache = json.load(f)
        except FileNotFoundError:
            _database_cache = {}
    return _database_cache


def srgb_to_lab(r, g, b):
    """Rechnet eine RGB-Farbe in den Lab-Farbraum um, in dem Abstände dem Seheindruck entsprechen."""
    def lin(v):
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    rl, gl, bl = lin(r), lin(g), lin(b)
    x = (0.4124564 * rl + 0.3575761 * gl + 0.1804375 * bl) / 0.95047
    y = (0.2126729 * rl + 0.7151522 * gl + 0.0721750 * bl)
    z = (0.0193339 * rl + 0.1191920 * gl + 0.9503041 * bl) / 1.08883
    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def named_labs():
    global _named_labs_cache
    if _named_labs_cache is None:
        _named_labs_cache = []
        for hex_key, name in load_color_database().items():
            h = hex_key.lstrip('#')
            rgb = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            _named_labs_cache.append((srgb_to_lab(*rgb), name))
    return _named_labs_cache


def lookup_universal_name(r, g, b, hex_code):
    """Gibt den bekannten Farbnamen zurück, falls es einen passenden gibt, sonst None."""
    db = load_color_database()
    exact = db.get(hex_code.lower())
    if exact:
        return exact
    if NAME_MATCH_TOLERANCE <= 0 or not db:
        return None
    L, a, bb = srgb_to_lab(r, g, b)
    best_name, best_d2 = None, None
    for (l2, a2, b2), name in named_labs():
        d2 = (L - l2) ** 2 + (a - a2) ** 2 + (bb - b2) ** 2
        if best_d2 is None or d2 < best_d2:
            best_name, best_d2 = name, d2
    if best_d2 is not None and best_d2 <= NAME_MATCH_TOLERANCE ** 2:
        return best_name
    return None


def title_case(name):
    """Jedes Wort mit Großbuchstaben beginnen: 'Deep-sea purple' -> 'Deep-sea Purple'."""
    return " ".join(w[:1].upper() + w[1:] for w in name.split(" "))


def generate_color_name(r, g, b, hex_code):
    # 1. Gibt es schon einen bekannten Namen für diese Farbe? Dann wird er verwendet.
    known = lookup_universal_name(r, g, b, hex_code)
    if known:
        return known

    # 2. Ansonsten Fallback auf unsere poetische HSL-Logik
    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
    h, l, s = colorsys.rgb_to_hls(rf, gf, bf)
    hue = h * 360

    if l < 0.22:
        light_mod = ["Deep-sea", "Midnight", "Abyss", "Shadows", "Obsidian"]
    elif l > 0.78:
        light_mod = ["Mist", "Whisper", "Dawn", "Glow", "Haze"]
    elif s < 0.18:
        light_mod = ["Muted", "Silent", "Dust", "Faded", "Soft"]
    else:
        light_mod = ["Radiant", "Vivid", "Ethereal", "Pure", "Luminous"]

    if hue < 15 or hue >= 345:
        base_names = ["scarlet", "crimson", "ember", "ruby", "blush"]
    elif 15 <= hue < 45:
        base_names = ["amber", "copper", "rust", "autumn", "terra"]
    elif 45 <= hue < 70:
        base_names = ["saffron", "honey", "ochre", "sun", "gold"]
    elif 70 <= hue < 150:
        base_names = ["olive", "moss", "emerald", "forest", "sage"]
    elif 150 <= hue < 200:
        base_names = ["teal", "lagoon", "pine", "glacier", "mint"]
    elif 200 <= hue < 260:
        base_names = ["cerulean", "azure", "cobalt", "ocean", "indigo"]
    elif 260 <= hue < 310:
        base_names = ["purple", "lilac", "lavender", "plum", "violet"]
    else:
        base_names = ["magenta", "coral", "rose", "orchid", "wine"]

    mod = light_mod[(r + g) % len(light_mod)]
    base = base_names[(g + b) % len(base_names)]

    return title_case(f"{mod} {base}")


def link_facets(text, url):
    """Macht die Adresse im Bluesky-Post anklickbar (Bluesky rechnet in Bytes)."""
    raw = text.encode("utf-8")
    start = raw.find(url.encode("utf-8"))
    if start < 0:
        return []
    return [{
        "index": {"byteStart": start, "byteEnd": start + len(url.encode("utf-8"))},
        "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}]
    }]


try:
    with open('colors.json', 'r', encoding='utf-8') as f:
        history = json.load(f)
except FileNotFoundError:
    history = []

today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
is_new_entry = False

if history and history[-1].get("date") == today_str:
    latest_entry = history[-1]
    print(f"Using existing color for today: {latest_entry['name']} ({latest_entry['hex']})")
else:
    is_new_entry = True
    day_number = max((e.get("day", 0) for e in history), default=0) + 1

    # Jede Farbe kommt nur einmal vor: bereits gezeigte Farben werden übersprungen
    used_hex = {e.get("hex", "").upper() for e in history}
    while True:
        r = random.randint(0, 255)
        g = random.randint(0, 255)
        b = random.randint(0, 255)
        hex_code = f"#{r:02X}{g:02X}{b:02X}"
        if hex_code not in used_hex:
            break

    color_name = generate_color_name(r, g, b, hex_code)

    latest_entry = {
        "day": day_number,
        "date": today_str,
        "hex": hex_code,
        "rgb": [r, g, b],
        "name": color_name
    }
    history.append(latest_entry)

    with open('colors.json', 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    print(f"Generated Day {day_number}: {color_name} ({hex_code})")

handle = os.environ.get("BLUESKY_HANDLE")
password = os.environ.get("BLUESKY_PASSWORD")
force_post = os.environ.get("FORCE_POST") == "1"

if not (handle and password):
    print("Bluesky credentials not found in environment variables.")
elif not is_new_entry and not force_post:
    # Verhindert doppelte Posts, wenn der Lauf am selben Tag nochmal gestartet wird
    print("Color for today already existed - skipping Bluesky post (set FORCE_POST=1 to post anyway).")
else:
    try:
        print("Logging in to Bluesky...")
        session_res = requests.post("https://bsky.social/xrpc/com.atproto.server.createSession", json={
            "identifier": handle,
            "password": password
        }, timeout=30)
        session_res.raise_for_status()
        session = session_res.json()
        access_token = session["accessJwt"]
        did = session["did"]

        print("Generating color image...")
        img = Image.new("RGB", (1080, 1080), tuple(latest_entry["rgb"]))
        img_byte_arr = io.BytesIO()
        # PNG statt JPEG: verlustfrei, damit die Farbe exakt bleibt
        img.save(img_byte_arr, format='PNG', optimize=True)
        img_bytes = img_byte_arr.getvalue()

        print("Uploading image blob to Bluesky...")
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "image/png"
        }
        blob_res = requests.post("https://bsky.social/xrpc/com.atproto.repo.uploadBlob",
                                 headers=headers, data=img_bytes, timeout=60)
        blob_res.raise_for_status()
        blob_data = blob_res.json()["blob"]

        day_str = str(latest_entry['day']).zfill(5)
        text = (
            f"Day {day_str} / 16,777,216\n"
            f"{latest_entry['name']}\n"
            f"{latest_entry['hex']} • RGB ({latest_entry['rgb'][0]}, {latest_entry['rgb'][1]}, {latest_entry['rgb'][2]})\n\n"
            f"\"One small splash of color per day – for eternity.\"\n\n"
            f"{SITE_URL}"
        )

        print("Publishing post to Bluesky...")
        post_record = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "facets": link_facets(text, SITE_URL),
            "embed": {
                "$type": "app.bsky.embed.images",
                "images": [
                    {
                        "alt": f"{latest_entry['name']} ({latest_entry['hex']})",
                        "image": blob_data
                    }
                ]
            }
        }

        post_res = requests.post("https://bsky.social/xrpc/com.atproto.repo.createRecord", headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }, json={
            "repo": did,
            "collection": "app.bsky.feed.post",
            "record": post_record
        }, timeout=30)
        post_res.raise_for_status()
        print("Successfully posted to Bluesky!")

    except Exception as e:
        print(f"Error posting to Bluesky: {e}")
