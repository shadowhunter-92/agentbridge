# AI Assistance Disclosure

In the interest of transparency — especially for teams whose legal/compliance review
asks about AI involvement before adopting an identity/governance tool — this project is
candid about how it was built.

## How this was built

- **Maintainer:** Haider Ali Khan (`shadowhunter-92`), who directs the architecture and
  product decisions, reviews and tests the code, and curates the result.
- **AI assistance:** a substantial portion of the implementation was written with the help
  of Anthropic's Claude, under that human direction and review. Commits reflect this with
  `Co-Authored-By` trailers, so the history is honest rather than hidden.

## Authorship, originality, and license

- The maintainer directs, reviews, edits, and accepts every change; the curated result is
  maintained as the maintainer's work.
- The code is **original** to this project — not copied from third-party codebases. Protocol
  adapters are validated against each protocol's real official SDK (see
  `docs/PROTOCOL_SUPPORT.md`), and the suite (124 tests) guards behaviour.
- The project is released under the **Apache License 2.0** (see `LICENSE`). Apache 2.0
  includes an explicit patent grant and clear contribution terms.

## Not legal advice

This document is a transparency statement, not legal advice. The treatment of AI-assisted
work under copyright varies by jurisdiction and is evolving. If your organization has
specific compliance requirements for adopting AI-assisted software, please apply your own
legal review — we're happy to answer factual questions about how the project was built.
