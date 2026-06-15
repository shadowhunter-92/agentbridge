"""
Render the 6 explainer scenes as 1280x720 PNGs (the visuals to pair with the HeyGen
voiceover). A separate ffmpeg step cuts them on the narration beats and muxes the audio.

Run:  .venv/Scripts/python tools/make_explainer_video.py
Out:  media/_scenes/scene0.png ... scene5.png
"""
from __future__ import annotations
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1280, 720
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "media", "_scenes")
os.makedirs(OUT, exist_ok=True)

INK   = (8, 9, 11)
BONE  = (236, 234, 227)
DIM   = (150, 156, 167)
FAINT = (95, 101, 111)
LINE  = (35, 38, 46)
LIME  = (201, 242, 78)
GREEN = (123, 227, 161)
AMBER = (231, 178, 76)
DANGER= (255, 107, 107)

def F(path, size):
    return ImageFont.truetype(path, size)
SUI   = "C:/Windows/Fonts/segoeui.ttf"
SUIB  = "C:/Windows/Fonts/segoeuib.ttf"
SUISB = "C:/Windows/Fonts/seguisb.ttf"
MONO  = "C:/Windows/Fonts/consola.ttf"
MONOB = "C:/Windows/Fonts/consolab.ttf"

def base():
    img = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(img)
    # faint grid
    for x in range(0, W, 48):
        d.line([(x, 0), (x, H)], fill=(15, 17, 21), width=1)
    for y in range(0, H, 48):
        d.line([(0, y), (W, y)], fill=(15, 17, 21), width=1)
    # lime glow top-right
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W-360, -220, W+220, 360], fill=(201, 242, 78, 46))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    d = ImageDraw.Draw(img)
    # vignette
    vig = Image.new("L", (W, H), 0)
    vd = ImageDraw.Draw(vig)
    vd.rectangle([0, 0, W, H], fill=0)
    vd.ellipse([-260, -160, W+260, H+160], fill=70)
    vig = vig.filter(ImageFilter.GaussianBlur(120))
    dark = Image.new("RGB", (W, H), (0, 0, 0))
    img = Image.composite(img, dark, vig)
    d = ImageDraw.Draw(img)
    # brand bar
    d.rounded_rectangle([48, 44, 70, 66], radius=6, fill=LIME)
    d.rectangle([54, 50, 64, 60], outline=INK, width=2)
    d.text((84, 45), "AgentBridge", font=F(SUIB, 20), fill=BONE)
    d.text((232, 49), "governance for AI agents", font=F(SUI, 13), fill=FAINT)
    # watermark
    wm = "github.com/shadowhunter-92/agentbridge"
    f = F(MONO, 13)
    d.text((W-48-d.textlength(wm, font=f), H-40), wm, font=f, fill=FAINT)
    return img, d

def ctext(d, y, text, font, fill):
    d.text((W//2, y), text, font=font, fill=fill, anchor="ma")

def kicker(d, text):
    f = F(SUISB, 15)
    # letter-spaced
    s = (" ".join(text.upper())).replace("   ", "  ")
    ctext(d, 150, s, f, FAINT)

# ---- scenes ----
def scene0(d):
    ctext(d, 120, "T H E   P R O B L E M", F(SUISB, 14), FAINT)
    ctext(d, 250, "Your AI agents are acting.", F(SUIB, 60), BONE)
    ctext(d, 330, "Can you prove what they did?", F(SUIB, 60), LIME)
    ctext(d, 470, "They call tools, move data, spend money —", F(SUI, 26), DIM)
    ctext(d, 510, "with no record, and no way to stop a bad call.", F(SUI, 26), DIM)

def scene1(d):
    ctext(d, 170, "AgentBridge", F(SUIB, 92), BONE)
    ctext(d, 330, "One neutral mesh every agent speaks through.", F(SUI, 30), DIM)
    ctext(d, 392, "T R A N S L A T E   ·   R O U T E   ·   V E R I F Y   ·   G O V E R N", F(SUISB, 20), LIME)
    chips = ["MCP", "A2A", "ACP", "OpenAI", "Gemini", "AGNTCY"]
    f = F(SUISB, 20)
    pad, gap = 26, 16
    widths = [d.textlength(c, font=f) + pad*2 for c in chips]
    total = sum(widths) + gap*(len(chips)-1)
    x = (W - total)//2
    y = 470
    for c, w in zip(chips, widths):
        d.rounded_rectangle([x, y, x+w, y+52], radius=26, outline=LINE, width=2, fill=(16, 18, 23))
        d.text((x+w/2, y+26), c, font=f, fill=BONE, anchor="mm")
        x += w + gap

def card(d, x0, y0, x1, y1, title=None):
    d.rounded_rectangle([x0, y0, x1, y1], radius=16, fill=(18, 21, 27), outline=LINE, width=2)
    if title:
        d.ellipse([x0+24, y0+24, x0+36, y0+36], fill=LIME)
        d.text((x0+48, y0+20), title, font=F(SUIB, 22), fill=BONE)
        d.line([(x0, y0+58), (x1, y0+58)], fill=LINE, width=2)

def tag(d, x, y, text, fg, bg, w=None):
    f = F(MONOB, 19)
    tw = (w or d.textlength(text, font=f)+24)
    d.rounded_rectangle([x, y, x+tw, y+34], radius=7, fill=bg)
    d.text((x+tw/2, y+17), text, font=f, fill=fg, anchor="mm")
    return tw

def scene2(d):
    kicker(d, "Governance in the call path")
    x0, y0, x1, y1 = 230, 240, 1050, 500
    card(d, x0, y0, x1, y1, "Policy · agent-007")
    rows = [("DENY", DANGER, "capabilities", "wire_transfer · delete_database"),
            ("MAX", BONE, "cost per call", "3.0"),
            ("APPROVAL", BONE, "required above", "2.0")]
    y = y0 + 82
    for t, tcol, what, why in rows:
        bg = DANGER if t == "DENY" else (28, 33, 41)
        fg = (26, 11, 11) if t == "DENY" else BONE
        tw = tag(d, x0+26, y, t, fg, bg)
        d.text((x0+26+tw+18, y+6), what, font=F(SUIB, 24), fill=BONE)
        f = F(MONO, 21)
        d.text((x1-26-d.textlength(why, font=f), y+7), why, font=f, fill=DIM)
        y += 64

def scene3(d):
    kicker(d, "Enforced before the tool is ever touched")
    x0, y0, x1, y1 = 210, 230, 1070, 540
    card(d, x0, y0, x1, y1)
    rows = [("ALLOWED", (10,14,9), GREEN, "safe call", "→ 5", GREEN),
            ("BLOCKED", (26,11,11), DANGER, "wire_transfer", "denied by policy", DIM),
            ("BLOCKED", (26,11,11), DANGER, "cost 4.0", "exceeds cap 3.0", DIM),
            ("BLOCKED", (26,11,11), DANGER, "cost 2.5", "needs human approval", DIM)]
    y = y0 + 28
    for t, fg, bg, what, why, wycol in rows:
        tw = tag(d, x0+28, y, t, fg, bg, w=118)
        d.text((x0+28+tw+18, y+6), what, font=F(SUIB, 24), fill=BONE)
        f = F(MONO, 21)
        d.text((x1-28-d.textlength(why, font=f), y+7), why, font=f, fill=wycol)
        y += 64

def scene4(d):
    kicker(d, "The proof")
    rows = [("#0", "allow", GREEN, "add", "d196e0c5…"),
            ("#1", "deny", DANGER, "wire_transfer", "500586d1…"),
            ("#2", "deny", DANGER, "add", "51c8326e…"),
            ("#3", "deny", DANGER, "add", "0a15540a…")]
    x0, x1 = 330, 950
    y = 210
    for seq, dec, dcol, cap, hsh in rows:
        d.rounded_rectangle([x0, y, x1, y+50], radius=11, fill=(15, 17, 22), outline=LINE, width=2)
        d.text((x0+22, y+13), seq, font=F(MONO, 20), fill=FAINT)
        d.text((x0+78, y+11), dec, font=F(MONOB, 21), fill=dcol)
        d.text((x0+190, y+12), cap, font=F(SUIB, 22), fill=BONE)
        f = F(MONO, 19)
        d.text((x1-22-d.textlength(hsh, font=f), y+15), hsh, font=f, fill=FAINT)
        if y > 210:
            d.line([(x0+46, y-22), (x0+46, y)], fill=LIME, width=2)
        y += 72
    # verified
    cy = y + 24
    d.ellipse([W//2-150, cy, W//2-110, cy+40], fill=LIME)
    bx, by = W//2-130, cy+20
    d.line([(bx-9, by+1), (bx-3, by+8), (bx+10, by-8)], fill=(10, 12, 8), width=4, joint="curve")
    d.text((W//2-95, cy-2), "Audit integrity verified", font=F(SUIB, 34), fill=LIME)
    ctext(d, cy+58, "tamper-evident · hash-chained · ~0.4 ms overhead", F(MONO, 19), FAINT)

def scene5(d):
    ctext(d, 150, "Govern your agents.", F(SUIB, 58), BONE)
    ctext(d, 224, "Prove what they did.", F(SUIB, 58), LIME)
    ctext(d, 360, "EU AI Act · Article 12 · automatic event logging · from Aug 2026", F(SUISB, 22), AMBER)
    url = "github.com/shadowhunter-92/agentbridge"
    f = F(MONOB, 32)
    uw = d.textlength(url, font=f)
    x0 = (W-uw)//2 - 30
    d.rounded_rectangle([x0, 430, x0+uw+60, 500], radius=12, fill=(16, 18, 23), outline=LINE, width=2)
    d.text((W//2, 448), url, font=f, fill=(255,255,255), anchor="ma")
    ctext(d, 540, "Open source · Apache-2.0 · any protocol in, any protocol out", F(SUI, 24), DIM)

SCENES = [scene0, scene1, scene2, scene3, scene4, scene5]

def main():
    for i, fn in enumerate(SCENES):
        img, d = base()
        fn(d)
        img.save(os.path.join(OUT, f"scene{i}.png"))
    print(f"wrote {len(SCENES)} scenes to {OUT}")

if __name__ == "__main__":
    main()
