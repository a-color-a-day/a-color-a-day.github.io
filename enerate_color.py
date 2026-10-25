import json
import random
from datetime import datetime

COLOR_NAMES = ["Azure", "Cerulean", "Crimson", "Emerald", "Indigo", "Magenta", "Ochre", "Saffron", "Scarlet", "Teal", "Vermilion", "Violet", "Amber", "Celeste", "Coral", "Cyan", "Maroon", "Olive"]
MODIFIERS = ["Vivid", "Deep", "Muted", "Radiant", "Quiet", "Celestial", "Ethereal", "Infinite", "Luminous", "Solitary", "Subtle", "Pure"]

def generate_color_name(r, g, b):
    mod_index = (r + g) % len(MODIFIERS)
    name_index = (g + b) % len(COLOR_NAMES)
    return f"{MODIFIERS[mod_index]} {COLOR_NAMES[name_index]}"

# Farbhistorie laden oder neu anlegen
try:
    with open('colors.json', 'r', encoding='utf-8') as f:
        history = json.load(f)
except FileNotFoundError:
    history = []

day_number = len(history) + 1
r = random.randint(0, 255)
g = random.randint(0, 255)
b = random.randint(0, 255)
hex_code = f"#{r:02X}{g:02X}{b:02X}"
color_name = generate_color_name(r, g, b)
today_str = datetime.utcnow().strftime("%Y-%m-%d")

new_entry = {
    "day": day_number,
    "date": today_str,
    "hex": hex_code,
    "rgb": [r, g, b],
    "name": color_name
}

history.append(new_entry)

with open('colors.json', 'w', encoding='utf-8') as f:
    json.dump(history, f, indent=2, ensure_ascii=False)

print(f"Generated Day {day_number}: {color_name} ({hex_code})")
