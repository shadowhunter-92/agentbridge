"""
Generates `guardrails.gif` from the (real) output of
`examples/policy_guardrails_demo.py` — the governance / compliance story.

An agent gets BLOCKED on a forbidden capability, an over-budget call, and a
needs-approval call, then a hash-chained, integrity-verified audit trail is shown.
This is the "Meta-Flex" clip: share it on Show HN / LinkedIn / in DMs.

Run:  .venv/Scripts/python tools/make_guardrails_gif.py
Output: ./guardrails.gif  (~16s loop)
"""

from __future__ import annotations
import os
from PIL import Image, ImageDraw, ImageFont

# ---- palette (matches landing/index.html + tools/make_demo_gif.py) ----
INK    = (11, 12, 15)
INK_2  = (16, 18, 24)
LINE   = (44, 46, 54)
BONE   = (236, 233, 226)
DIM    = (155, 158, 167)
FAINT  = (103, 106, 116)
LIME   = (200, 242, 78)     # allow / success
AMBER  = (231, 178, 76)     # budget / pending
DANGER = (255, 111, 107)    # blocked / deny

W, H = 980, 820
PAD_X, PAD_TOP, LINE_H = 38, 78, 22
FONT_PATH  = "C:/Windows/Fonts/consola.ttf"
FONTB_PATH = "C:/Windows/Fonts/consolab.ttf"
FONT_SIZE  = 17

FONT  = ImageFont.truetype(FONT_PATH,  FONT_SIZE)
FONTB = ImageFont.truetype(FONTB_PATH, FONT_SIZE)
FONT_SM = ImageFont.truetype(FONT_PATH, 12)


# ---- the actual demo output, grouped into reveal-stages ----
STAGES: list[list[tuple[str, str]]] = [
    # stage 0 — header + policy
    [
        ("", "blank"),
        ("   AgentBridge — governance in the call path", "title"),
        ("", "blank"),
        ("=" * 64, "rule"),
        ("  Policy in force for agent-007:", "policy_head"),
        ("    - DENY capabilities: wire_transfer, delete_database", "policy_item"),
        ("    - MAX cost per call: 3.0", "policy_item"),
        ("    - APPROVAL required above cost: 2.0", "policy_item"),
        ("-" * 64, "rule"),
    ],
    # stage 1 — the safe call goes through
    [
        ("", "blank"),
        ("  [ALLOWED] safe call: add (cost 1.0) -> 5", "allowed"),
    ],
    # stage 2 — forbidden capability blocked
    [
        ("  [BLOCKED] forbidden capability: wire_transfer (cost 1.0)", "blocked"),
        ("            reason: capability 'wire_transfer' is denied by policy", "reason"),
    ],
    # stage 3 — over the cost cap
    [
        ("  [BLOCKED] too expensive: add (cost 4.0)", "blocked"),
        ("            reason: cost 4.0 exceeds per-call cap 3.0", "reason"),
    ],
    # stage 4 — needs human approval
    [
        ("  [BLOCKED] needs approval: add (cost 2.5)", "blocked"),
        ("            reason: approval required: cost 2.5 > 2.0", "reason"),
    ],
    # stage 5 — budget + pending approvals
    [
        ("-" * 64, "rule"),
        ("  Budget spent: 1.0 / 5.0   (denied calls cost nothing)", "budget"),
        ("  Pending human approvals opened by policy: 1", "pending"),
    ],
    # stage 6 — the audit chain
    [
        ("", "blank"),
        ("  Tamper-evident audit trail (every decision, hash-chained):", "policy_head"),
        ("    #0  allow  add             d196e0c59db9", "audit_allow"),
        ("    #1  deny   wire_transfer   500586d1461b", "audit_deny"),
        ("    #2  deny   add             51c8326ee71d", "audit_deny"),
        ("    #3  deny   add             0a15540a4c4f", "audit_deny"),
    ],
    # stage 7 — verdict + footer
    [
        ("", "blank"),
        ("  Audit integrity verified: True", "verified"),
        ("  (EU AI Act Art. 12: automatic event logging, high-risk AI, Aug 2026)", "footer"),
        ("=" * 64, "rule"),
        ("  Any protocol in  ->  policy enforced  ->  provable log out.", "footer"),
    ],
]

# milliseconds per stage (blocks get a beat each so the eye catches each denial)
DURATIONS = [1500, 1300, 1500, 1500, 1500, 1400, 2600, 3200]


def _draw_tag(d, x, y, head, tag, tail, tag_colour, tail_colour=DIM):
    d.text((x, y), head, font=FONT, fill=BONE); x += FONT.getlength(head)
    d.text((x, y), tag,  font=FONTB, fill=tag_colour); x += FONTB.getlength(tag)
    d.text((x, y), tail, font=FONT, fill=tail_colour)


def draw_line(d: ImageDraw.ImageDraw, y: int, text: str, kind: str) -> None:
    if kind == "title":
        d.text((PAD_X, y), text, font=FONTB, fill=BONE); return
    if kind == "rule":
        d.text((PAD_X, y), text, font=FONT, fill=LINE); return
    if kind == "policy_head":
        d.text((PAD_X, y), text, font=FONTB, fill=BONE); return
    if kind == "policy_item":
        d.text((PAD_X, y), text, font=FONT, fill=DIM); return
    if kind == "reason":
        d.text((PAD_X, y), text, font=FONT, fill=FAINT); return
    if kind == "budget":
        d.text((PAD_X, y), text, font=FONT, fill=AMBER); return
    if kind == "pending":
        d.text((PAD_X, y), text, font=FONT, fill=AMBER); return
    if kind == "verified":
        d.text((PAD_X, y), text, font=FONTB, fill=LIME); return
    if kind == "footer":
        d.text((PAD_X, y), text, font=FONT, fill=DIM); return

    if kind == "allowed":
        idx = text.find("[ALLOWED]")
        head, tag = text[:idx], "[ALLOWED]"
        tail = text[idx + len(tag):]
        x = PAD_X
        d.text((x, y), head, font=FONT, fill=BONE); x += FONT.getlength(head)
        d.text((x, y), tag,  font=FONTB, fill=LIME); x += FONTB.getlength(tag)
        if tail.endswith("-> 5"):
            pre, suf = tail[:-4], tail[-4:]
            d.text((x, y), pre, font=FONT, fill=DIM); x += FONT.getlength(pre)
            d.text((x, y), suf, font=FONTB, fill=LIME)
        else:
            d.text((x, y), tail, font=FONT, fill=DIM)
        return

    if kind == "blocked":
        idx = text.find("[BLOCKED]")
        _draw_tag(d, PAD_X, y, text[:idx], "[BLOCKED]", text[idx + len("[BLOCKED]"):], DANGER)
        return

    if kind in ("audit_allow", "audit_deny"):
        decision = "allow" if kind == "audit_allow" else "deny "
        colour = LIME if kind == "audit_allow" else DANGER
        idx = text.find(decision)
        head, after = text[:idx], text[idx + len(decision):]
        # split the trailing hash off so it can be faint
        parts = after.rsplit("   ", 1)
        mid, hsh = (parts[0], parts[1]) if len(parts) == 2 else (after, "")
        x = PAD_X
        d.text((x, y), head, font=FONT, fill=DIM); x += FONT.getlength(head)
        d.text((x, y), decision, font=FONTB, fill=colour); x += FONTB.getlength(decision)
        sep = mid + ("   " if hsh else "")
        d.text((x, y), sep, font=FONT, fill=BONE); x += FONT.getlength(sep)
        if hsh:
            d.text((x, y), hsh, font=FONT, fill=FAINT)
        return

    d.text((PAD_X, y), text, font=FONT, fill=BONE)


def render_frame(visible_stages: int) -> Image.Image:
    img = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(img)

    d.rectangle([0, 0, W, 38], fill=INK_2)
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        cx, cy = 22 + i * 22, 19
        d.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=c)
    d.text((W // 2 - 92, 12), "agentbridge — guardrails demo", font=FONT_SM, fill=DIM)
    d.line([(0, 38), (W, 38)], fill=LINE, width=1)

    y = PAD_TOP
    for stage_idx in range(visible_stages):
        for text, kind in STAGES[stage_idx]:
            draw_line(d, y, text, kind)
            y += LINE_H

    wm = "github.com/shadowhunter-92/agentbridge"
    d.text((W - 18 - FONT_SM.getlength(wm), H - 24), wm, font=FONT_SM, fill=FAINT)
    return img


def main() -> None:
    frames, durations = [], []
    for i, dur in enumerate(DURATIONS, start=1):
        frames.append(render_frame(i))
        durations.append(dur)

    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "guardrails.gif")
    frames[0].save(
        out, save_all=True, append_images=frames[1:],
        duration=durations, loop=0, optimize=True,
    )
    size_kb = os.path.getsize(out) / 1024
    print(f"wrote {out}  ({size_kb:.0f} KB, {len(frames)} frames, "
          f"{sum(durations)/1000:.1f}s loop)")


if __name__ == "__main__":
    main()
