"""Source-checkout compatibility wrapper for the installed offline verifier."""
from src.governance.evidence_cli import main, verify_bundle

__all__ = ["main", "verify_bundle"]

if __name__ == "__main__":
    raise SystemExit(main())
