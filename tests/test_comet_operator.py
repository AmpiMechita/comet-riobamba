import unittest
from pathlib import Path

from scripts.ops import comet_operator


class CometOperatorGuardTests(unittest.TestCase):
    def test_git_status_separates_staged_unstaged_and_untracked(self):
        result = comet_operator._summarize_git_status(
            "M  staged.py\n M unstaged.py\n?? new.py\n"
        )
        self.assertEqual(result["tracked_changes"], 2)
        self.assertEqual(result["staged_changes"], 1)
        self.assertEqual(result["unstaged_changes"], 1)
        self.assertEqual(result["untracked"], 1)
        self.assertEqual(
            result["paths"], ["staged.py", "unstaged.py", "new.py"]
        )

    def test_git_status_uses_all_to_enumerate_nested_untracked_files(self):
        from unittest.mock import patch

        root = Path(".")
        with patch.object(
            comet_operator, "_git", return_value="?? nested/a.py\n?? nested/b.py\n"
        ) as git:
            raw_status = comet_operator._git_status(root)

        git.assert_called_once_with(
            root, "status", "--porcelain=v1", "--untracked-files=all"
        )
        result = comet_operator._summarize_git_status(raw_status)
        self.assertEqual(result["untracked"], 2)
        self.assertEqual(result["paths"], ["nested/a.py", "nested/b.py"])

    def test_expected_service_start_mode_fails_closed(self):
        args = comet_operator.parse_args(
            ["--expect-service-start-mode", "Manual"]
        )
        snapshot = {
            "head": "abc",
            "branch": "main",
            "git": {
                "tracked_changes": 0,
                "staged_changes": 0,
                "unstaged_changes": 0,
                "untracked": 0,
            },
            "service": {
                "status": "Stopped",
                "pid": 0,
                "start_mode": "Automatic",
            },
            "protected": {
                comet_operator.PROTECTED_SCORING.as_posix(): {
                    "sha256": "A" * 64
                }
            },
        }
        self.assertIn(
            "service.start_mode: expected='Manual' actual='Automatic'",
            comet_operator.evaluate(snapshot, args),
        )

    def test_require_service_stopped_also_requires_manual_start_mode(self):
        args = comet_operator.parse_args(["--require-service-stopped"])
        snapshot = {
            "head": "abc",
            "branch": "main",
            "git": {
                "tracked_changes": 0,
                "staged_changes": 0,
                "unstaged_changes": 0,
                "untracked": 0,
            },
            "service": {
                "status": "Stopped",
                "pid": 0,
                "start_mode": "Automatic",
            },
            "protected": {
                comet_operator.PROTECTED_SCORING.as_posix(): {
                    "sha256": "A" * 64
                }
            },
        }
        failures = comet_operator.evaluate(snapshot, args)
        self.assertTrue(
            any(
                failure.startswith(
                    "service: expected status='Stopped' pid=0 start_mode='Manual'"
                )
                for failure in failures
            )
        )

    def test_expected_git_stage_counts_are_enforced(self):
        args = comet_operator.parse_args(
            ["--expect-staged-changes", "1", "--expect-unstaged-changes", "2"]
        )
        snapshot = {
            "head": "abc",
            "branch": "main",
            "git": {
                "tracked_changes": 3,
                "staged_changes": 0,
                "unstaged_changes": 3,
                "untracked": 0,
            },
            "service": {
                "status": "Stopped",
                "pid": 0,
                "start_mode": "Manual",
            },
            "protected": {
                comet_operator.PROTECTED_SCORING.as_posix(): {
                    "sha256": "A" * 64
                }
            },
        }
        failures = comet_operator.evaluate(snapshot, args)
        self.assertIn(
            "git.staged_changes: expected=1 actual=0",
            failures,
        )
        self.assertIn(
            "git.unstaged_changes: expected=2 actual=3",
            failures,
        )


    def test_service_name_is_passed_as_data_not_powershell_code(self):
        from unittest.mock import patch

        service_name = 'x"; Write-Output INJECTED;#'
        with patch.object(comet_operator.shutil, "which", return_value="pwsh"):
            with patch.object(
                comet_operator,
                "_run",
                return_value=comet_operator.json.dumps(
                    {
                        "Name": service_name,
                        "State": "Stopped",
                        "ProcessId": 0,
                        "StartMode": "Manual",
                    }
                ),
            ) as run:
                result = comet_operator._service_snapshot(Path("."), service_name)

        args = run.call_args.args[0]
        env = run.call_args.kwargs["env"]
        self.assertEqual(env["COMET_OPERATOR_SERVICE_NAME"], service_name)
        self.assertIn("$env:COMET_OPERATOR_SERVICE_NAME", args[-1])
        self.assertNotIn(service_name, args[-1])
        self.assertEqual(result["name"], service_name)


    def test_default_service_name_preserves_normal_behavior(self):
        from unittest.mock import patch

        service_name = comet_operator.SERVICE_DEFAULT
        response = comet_operator.json.dumps(
            {
                "Name": service_name,
                "State": "Stopped",
                "ProcessId": 0,
                "StartMode": "Manual",
            }
        )
        with patch.object(comet_operator.shutil, "which", return_value="pwsh"):
            with patch.object(comet_operator, "_run", return_value=response) as run:
                result = comet_operator._service_snapshot(Path("."), service_name)

        self.assertEqual(
            run.call_args.kwargs["env"]["COMET_OPERATOR_SERVICE_NAME"],
            "CometRiobamba",
        )
        self.assertEqual(
            result,
            {"name": "CometRiobamba", "status": "Stopped", "pid": 0, "start_mode": "Manual"},
        )


if __name__ == "__main__":
    unittest.main()
