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

- **Copyright is held by the maintainer, Haider Ali Khan** (see the `NOTICE` file). The
  maintainer directs, reviews, edits, selects, and arranges every change; the curated result
  is the maintainer's work and is licensed under the **Apache License 2.0** (see `LICENSE`),
  which includes an explicit patent grant and clear contribution terms.
- **The `Co-Authored-By: Claude` trailers in the commit history are attribution only.** They
  transparently credit AI assistance during development; they do **not** transfer or assign
  any copyright to Anthropic or to the model. Under Anthropic's terms, ownership of model
  outputs rests with the user.
- The code is **original** to this project — not copied from third-party codebases. Protocol
  adapters are validated against each protocol's real official SDK (see
  `docs/PROTOCOL_SUPPORT.md`), and the suite (124 tests) guards behaviour.

## Not legal advice

This document is a transparency statement, not legal advice. The treatment of AI-assisted
work under copyright varies by jurisdiction and is evolving. If your organization has
specific compliance requirements for adopting AI-assisted software, please apply your own
legal review — we're happy to answer factual questions about how the project was built.
