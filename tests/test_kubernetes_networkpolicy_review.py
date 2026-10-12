"""Structural contract for the review-only Kubernetes network policies."""
from pathlib import Path

import yaml


def test_review_worker_policy_defaults_to_explicit_egress_paths():
    path = Path(__file__).resolve().parents[1] / "deploy/kubernetes/networkpolicy.review.yaml"
    policies = list(yaml.safe_load_all(path.read_text()))
    worker, proxy = policies
    assert worker["kind"] == proxy["kind"] == "NetworkPolicy"
    assert worker["spec"]["podSelector"]["matchLabels"]["app.kubernetes.io/name"] == "agentbridge-worker"
    assert worker["spec"]["policyTypes"] == ["Egress"]
    rules = worker["spec"]["egress"]
    allowed_ports = {p["port"] for rule in rules for p in rule["ports"]}
    assert allowed_ports == {3128, 5432, 53}
    assert all("ipBlock" not in dest for rule in rules for dest in rule["to"])
    assert proxy["spec"]["policyTypes"] == ["Ingress"]
    assert proxy["spec"]["ingress"][0]["ports"][0]["port"] == 3128
    assert proxy["spec"]["ingress"][0]["from"][0]["podSelector"]["matchLabels"][
        "app.kubernetes.io/name"] == "agentbridge-worker"
