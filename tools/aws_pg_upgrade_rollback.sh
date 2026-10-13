#!/usr/bin/env bash
# Disposable AWS-hosted application wheel upgrade/rollback, synthetic evidence.
set -euo pipefail
umask 077
root=/opt/agentbridge-qualification
: "$AB_BASELINE_SHA"
: "$AB_CANDIDATE_SHA"
baseline="$AB_BASELINE_SHA"
candidate="$AB_CANDIDATE_SHA"
cd "$root/source"
git cat-file -e "$baseline^{commit}"
git cat-file -e "$candidate^{commit}"
test "$(git rev-parse HEAD)" = "$candidate"
mkdir -p "$root/releases/baseline" "$root/releases/candidate"
git worktree add --detach "$root/previous" "$baseline" > /opt/ab-logs/worktree.log 2>&1
"$root/venv/bin/python" -m pip -q install wheel setuptools >>/opt/ab-logs/python.log 2>&1
"$root/venv/bin/python" -m pip wheel --no-deps --no-build-isolation \
 -w "$root/releases/baseline" "$root/previous" > /opt/ab-logs/build_baseline.log 2>&1
"$root/venv/bin/python" -m pip wheel --no-deps --no-build-isolation \
 -w "$root/releases/candidate" "$root/source" > /opt/ab-logs/build_candidate.log 2>&1
oldwheel="$(find "$root/releases/baseline" -maxdepth 1 -name '*.whl' -type f | head -1)"
newwheel="$(find "$root/releases/candidate" -maxdepth 1 -name '*.whl' -type f | head -1)"
test -n "$oldwheel" && test -n "$newwheel"
oldhash="$(sha256sum "$oldwheel" | cut -d' ' -f1)"
newhash="$(sha256sum "$newwheel" | cut -d' ' -f1)"
test "$oldhash" != "$newhash"
echo "BASELINE_SHA=$baseline"
echo "CANDIDATE_SHA=$candidate"
echo "BASELINE_WHEEL_SHA256=$oldhash"
echo "CANDIDATE_WHEEL_SHA256=$newhash"
verify_evidence() {
 cd "$root"
 openssl pkeyutl -verify -rawin -pubin \
   -inkey "$root/observer/public.pem" \
   -in "$root/observer/receipt.json" \
   -sigfile "$root/observer/receipt.sig" >/dev/null
 runuser -u postgres -- psql -XAt -d agentbridge_test -c \
   "SELECT receipt_json FROM ab_evidence_effects WHERE operation_id='once';" \
   > "$root/observer/current.json"
 cmp -s "$root/observer/receipt.json" "$root/observer/current.json"
 count="$(runuser -u postgres -- psql -XAt -d agentbridge_test -c \
   "SELECT COUNT(*) FROM ab_evidence_effects WHERE operation_id='once';")"
 test "$count" = "1"
 "$root/venv/bin/python" -c \
   "import src.governance.fenced_postgres_destination as module; assert '/venv/' in module.__file__,module.__file__"
 echo EVIDENCE_SIGNATURE_AND_SINGLE_EFFECT_PRESERVED
}
install_release() {
 cd "$root"
 "$root/venv/bin/pip" -q install --force-reinstall --no-deps "$1" > /opt/ab-logs/install.log 2>&1
 verify_evidence
}
install_release "$oldwheel"
echo BASELINE_INSTALLED
install_release "$newwheel"
echo CANDIDATE_INSTALLED
install_release "$oldwheel"
echo ROLLBACK_INSTALLED
echo APPLICATION_ARTIFACT_UPGRADE_ROLLBACK_ACCEPTED
