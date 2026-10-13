"""No-network tests of dangerous AWS two-host orchestration decisions."""
import contextlib
import io
from types import SimpleNamespace
import unittest

from tools.aws_pg_two_host_orchestrator import PHASES, commands, run, validate


def args(**overrides):
    base = dict(
        primary_id="i-0123456789abcdef0",
        standby_id="i-0123456789abcdef1",
        primary_ip="172.31.10.2",
        standby_ip="172.31.11.3",
        parameter_prefix="/agentbridge/ephemeral-static-ci",
        harness_sha="1" * 40,
        candidate_sha="2" * 40,
        baseline_sha="3" * 40,
        region="us-east-1",
        evidence_file="not-written-by-dry-run.json",
        execute=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestAwsTwoHostOrchestrator(unittest.TestCase):
    def test_dry_run_does_not_import_boto3_or_call_aws(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(run(args()), 0)
        self.assertIn('"aws_called": false', output.getvalue())
        self.assertIn('"instances_created": false', output.getvalue())

    def test_rejects_unsafe_parameters(self):
        invalid = [
            dict(primary_id="i-bad;rm -rf /"),
            dict(standby_id="i-0123456789abcdef0"),
            dict(primary_ip="8.8.8.8"),
            dict(standby_ip="127.0.0.1"),
            dict(candidate_sha="main"),
            dict(harness_sha="$(whoami)"),
            dict(parameter_prefix="/production/db"),
            dict(region="eu-west-1"),
        ]
        for case in invalid:
            with self.subTest(case=case), self.assertRaises(ValueError):
                validate(args(**case))

    def test_cleanup_order_and_no_embedded_passwords(self):
        order = [phase for phase, _ in PHASES]
        self.assertLess(order.index("stop-primary"), order.index("promote"))
        self.assertLess(order.index("observe"), order.index("stop-primary"))
        for phase, _ in PHASES:
            cmd = "\n".join(commands(args(), phase))
            self.assertIn("set -euo pipefail", cmd)
            self.assertIn("AB_SOURCE_SHA", cmd)
            self.assertNotIn("PGPASSWORD=", cmd)
            self.assertNotIn("password=", cmd.lower())
            self.assertNotIn("AWS_SECRET_ACCESS_KEY", cmd)


if __name__ == "__main__":
    unittest.main()
