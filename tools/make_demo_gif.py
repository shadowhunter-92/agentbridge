"""
Generates `demo.gif` from the (real) output of `examples/demo_story.py`.

This is the README hero. We render the demo's output progressively as a
"terminal" with the AgentBridge palette, so the GIF stays crisp on GitHub
and exactly matches the landing page's aesthetic.

Run:  .venv/Scripts/python tools/make_demo_gif.py
Output: ./demo.gif  (~14s loop, ~900KB)
"""

from __future__ import annotations
import os
from PIL import Image, ImageDraw, ImageFont

# ---- palette (matches landing/index.html) ----
INK    = (11, 12, 15)         # background
INK_2  = (16, 18, 24)         # chrome
LINE   = (44, 46, 54)         # divider
BONE   = (236, 233, 226)      # primary text
DIM    = (155, 158, 167)      # secondary text
FAINT  = (103, 106, 116)      # tertiary text
LIME   = (200, 242, 78)       # success / allow
AMBER  = (231, 178, 76)       # warn / deny
DANGER = (255, 111, 107)      # blocked / error

W, H = 920, 740
PAD_X, PAD_TOP, LINE_H = 38, 78, 22
FONT_PATH  = "C:/Windows/Fonts/consola.ttf"
FONTB_PATH = "C:/Windows/Fonts/consolab.ttf"
FONT_SIZE  = 17

FONT  = ImageFont.truetype(FONT_PATH,  FONT_SIZE)
FONTB = ImageFont.truetype(FONTB_PATH, FONT_SIZE)
FONT_SM = ImageFont.truetype(FONT_PATH, 12)


# ---- the actual demo output, grouped into reveal-stages ----
STAGES: list[list[tuple[str, str]]] = [
    # stage 0 — header
    [
        ("", "blank"),
        ("   AgentBridge — one mesh every agent speaks through", "title"),
        ("", "blank"),
        ("=" * 60, "rule"),
        ("  Protocols in the mesh: a2a, acp, agntcy, gemini, mcp, openai", "header"),
        ("=" * 60, "rule"),
    ],
    # stage 1 — blocked
    [
        ("", "blank"),
        ("  1) An UNKNOWN agent tries to use the mesh:", "step"),
        ("     [BLOCKED] unknown or revoked identity 'demo-agent'", "blocked"),
    ],
    # stage 2 — register
    [
        ("", "blank"),
        ("  2) We register its identity (Ed25519 DID) and give it a budget.", "step"),
    ],
    # stage 3 — the money shot: 6 protocols, one tool
    [
        ("", "blank"),
        ("  3) Now the SAME live MCP `add` tool is reached from EVERY protocol,", "step"),
        ("     each translated + governed through the one mesh:", "step"),
        ("", "blank"),
        ("     openai  -> bridge -> live MCP tool -> 5", "route"),
        ("     gemini  -> bridge -> live MCP tool -> 5", "route"),
        ("     acp     -> bridge -> live MCP tool -> 5", "route"),
        ("     agntcy  -> bridge -> live MCP tool -> 5", "route"),
        ("     a2a     -> bridge -> live MCP tool -> 5", "route"),
        ("     mcp     -> bridge -> live MCP tool -> 5", "route"),
    ],
    # stage 4 — budget
    [
        ("", "blank"),
        ("  4) Budget spent: 6.0 / 10", "budget"),
    ],
    # stage 5 — audit chain
    [
        ("", "blank"),
        ("  5) Tamper-evident audit trail (every call, hash-chained):", "step"),
        ("     #0 deny  openai ->mcp add  d4e6e0545e", "audit_deny"),
        ("     #1 allow openai ->mcp add  1ed66cb94c", "audit_allow"),
        ("     #2 allow gemini ->mcp add  7a9a85b98a", "audit_allow"),
        ("     #3 allow acp    ->mcp add  d9ba11960f", "audit_allow"),
        ("     #4 allow agntcy ->mcp add  3d3acfb5d1", "audit_allow"),
        ("     #5 allow a2a    ->mcp add  ec7cbeef28", "audit_allow"),
        ("     #6 allow mcp    ->mcp add  7f68e44308", "audit_allow"),
    ],
    # stage 6 — verdict + footer
    [
        ("", "blank"),
        ("     Audit integrity verified: True", "verified"),
        ("=" * 60, "rule"),
        ("  Translate · route · verify · govern — any protocol, one mesh.", "footer"),
    ],
]

# milliseconds per stage
DURATIONS = [1100, 1300, 1100, 2400, 1100, 2400, 3000]


def colour_for(kind: str, segment: str | None = None) -> tuple[int, int, int]:
    if kind == "title":     return BONE
    if kind == "rule":      return LINE
    if kind == "header":    return BONE
    if kind == "step":      return BONE
    if kind == "budget":    return AMBER
    if kind == "verified":  return LIME
    if kind == "footer":    return DIM
    if kind == "blocked":   return DANGER
    if kind == "route":     return BONE
    if kind == "audit_allow": return LIME
    if kind == "audit_deny":  return AMBER
    return BONE


def draw_line(d: ImageDraw.ImageDraw, y: int, text: str, kind: str) -> None:
    """Draw a line with kind-aware highlights (bold protocol names, lime ' -> 5'),
    keeping monospaced alignment intact."""
    base_colour = colour_for(kind)

    if kind == "route":
        # "     openai  -> bridge -> live MCP tool -> 5"
        # Highlight the protocol token (bold bone) and the final ' -> 5' (lime).
        prefix = text[:5]                 # "     "
        rest   = text[5:]
        proto_end = rest.find(' ')
        proto = rest[:proto_end]
        tail  = rest[proto_end:]          # "  -> bridge -> live MCP tool -> 5"
        x = PAD_X
        d.text((x, y), prefix, font=FONT, fill=FAINT); x += FONT.getlength(prefix)
        d.text((x, y), proto,  font=FONTB, fill=BONE); x += FONTB.getlength(proto)
        # split tail into pre-' -> 5' and ' -> 5'
        if tail.endswith(" -> 5"):
            pre, suf = tail[:-5], tail[-5:]
            d.text((x, y), pre, font=FONT, fill=DIM); x += FONT.getlength(pre)
            d.text((x, y), suf, font=FONTB, fill=LIME)
        else:
            d.text((x, y), tail, font=FONT, fill=DIM)
        return

    if kind in ("audit_allow", "audit_deny"):
        # "     #N allow|deny  proto ->mcp cap  hash"
        # decision token coloured; rest neutral; hash faint.
        decision = "allow" if kind == "audit_allow" else "deny "
        idx = text.find(decision)
        if idx > 0:
            head = text[:idx]
            after = text[idx + len(decision):]
            # find the hash (last token, 10+ hex chars) and split it off
            parts = after.rsplit("  ", 1)
            mid, hsh = (parts[0], parts[1]) if len(parts) == 2 else (after, "")
            x = PAD_X
            d.text((x, y), head, font=FONT, fill=DIM); x += FONT.getlength(head)
            d.text((x, y), decision, font=FONTB, fill=base_colour); x += FONTB.getlength(decision)
            mid_with_sep = mid + ("  " if hsh else "")
            d.text((x, y), mid_with_sep, font=FONT, fill=BONE); x += FONT.getlength(mid_with_sep)
            if hsh:
                d.text((x, y), hsh, font=FONT, fill=FAINT)
            return

    if kind == "blocked":
        # highlight the [BLOCKED] tag
        idx = text.find("[BLOCKED]")
        if idx >= 0:
            head, tag, tail = text[:idx], "[BLOCKED]", text[idx + len("[BLOCKED]"):]
            x = PAD_X
            d.text((x, y), head, font=FONT, fill=BONE); x += FONT.getlength(head)
            d.text((x, y), tag,  font=FONTB, fill=DANGER); x += FONTB.getlength(tag)
            d.text((x, y), tail, font=FONT, fill=DIM)
            return

    if kind == "title":
        d.text((PAD_X, y), text, font=FONTB, fill=BONE); return

    if kind == "rule":
        d.text((PAD_X, y), text, font=FONT, fill=LINE); return

    d.text((PAD_X, y), text, font=FONT, fill=base_colour)


def render_frame(visible_stages: int) -> Image.Image:
    img = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(img)

    # chrome bar
    d.rectangle([0, 0, W, 38], fill=INK_2)
    # three dots
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        cx, cy = 22 + i * 22, 19
        d.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=c)
    d.text((W // 2 - 70, 12), "agentbridge — demo", font=FONT_SM, fill=DIM)
    d.line([(0, 38), (W, 38)], fill=LINE, width=1)

    # body
    y = PAD_TOP
    for stage_idx in range(visible_stages):
        for text, kind in STAGES[stage_idx]:
            draw_line(d, y, text, kind)
            y += LINE_H

    # subtle bottom watermark
    wm = "github.com/shadowhunter-92/agentbridge"
    d.text((W - 18 - FONT_SM.getlength(wm), H - 24), wm, font=FONT_SM, fill=FAINT)
    return img


def main() -> None:
    frames, durations = [], []
    for i, dur in enumerate(DURATIONS, start=1):
        frames.append(render_frame(i))
        durations.append(dur)

    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "demo.gif")
    frames[0].save(
        out, save_all=True, append_images=frames[1:],
        duration=durations, loop=0, optimize=True,
    )
    size_kb = os.path.getsize(out) / 1024
    print(f"wrote {out}  ({size_kb:.0f} KB, {len(frames)} frames, "
          f"{sum(durations)/1000:.1f}s loop)")


if __name__ == "__main__":
    main()
