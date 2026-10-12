"""Export a CycloneDX 1.5 installed-Python dependency inventory.

Uses pip inspect as source, not guesses from requirements ranges. This is
review evidence; it does not replace artifact signing, lockfiles, a complete
container SBOM or vulnerability scanning.
"""
import datetime as dt
import json
import subprocess
import sys
import uuid


def main():
    captured = subprocess.run([sys.executable, "-m", "pip", "inspect", "--local"],
                              check=True, capture_output=True, text=True)
    inspect = json.loads(captured.stdout)
    components = []
    for item in inspect.get("installed", []):
        metadata = item.get("metadata", {})
        name = metadata.get("name", "").strip()
        version = metadata.get("version", "").strip()
        if not name or not version:
            raise ValueError("installed distribution without name/version")
        normalized = name.lower().replace("_", "-").replace(".", "-")
        components.append({
            "type": "library",
            "bom-ref": f"pkg:pypi/{normalized}@{version}",
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{normalized}@{version}",
        })
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {"timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
                     "tools": {"components": [{
                         "type": "application", "name": "AgentBridge review SBOM exporter",
                         "version": "1"}]}},
        "components": sorted(components, key=lambda v: v["purl"]),
    }
    json.dump(bom, sys.stdout, indent=2, sort_keys=True)
    print()


if __name__ == "__main__":
    main()
