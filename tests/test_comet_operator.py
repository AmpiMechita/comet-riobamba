import json
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.ops import comet_operator


class CometOperatorServiceNameTests(unittest.TestCase):
    def test_service_name_is_passed_as_data_not_powershell_code(self):
        service_name = 'x"; Write-Output INJECTED;#'
        response = json.dumps(
            {
                "Name": service_name,
                "State": "Stopped",
                "ProcessId": 0,
                "StartMode": "Manual",
            }
        )
        with patch.object(comet_operator.shutil, "which", return_value="pwsh"):
            with patch.object(
                comet_operator,
                "_run",
                return_value=response,
            ) as run:
                result = comet_operator._service_snapshot(Path("."), service_name)

        args = run.call_args.args[0]
        env = run.call_args.kwargs["env"]
        self.assertEqual(env["COMET_OPERATOR_SERVICE_NAME"], service_name)
        self.assertIn("$env:COMET_OPERATOR_SERVICE_NAME", args[-1])
        self.assertNotIn(service_name, args[-1])
        self.assertEqual(result["name"], service_name)

    def test_default_service_name_preserves_normal_behavior(self):
        service_name = comet_operator.SERVICE_DEFAULT
        response = json.dumps(
            {
                "Name": service_name,
                "State": "Stopped",
                "ProcessId": 0,
                "StartMode": "Manual",
            }
        )
        with patch.object(comet_operator.shutil, "which", return_value="pwsh"):
            with patch.object(
                comet_operator,
                "_run",
                return_value=response,
            ) as run:
                result = comet_operator._service_snapshot(Path("."), service_name)

        self.assertEqual(
            run.call_args.kwargs["env"]["COMET_OPERATOR_SERVICE_NAME"],
            "CometRiobamba",
        )
        self.assertEqual(
            result,
            {
                "name": "CometRiobamba",
                "status": "Stopped",
                "pid": 0,
                "start_mode": "Manual",
            },
        )


if __name__ == "__main__":
    unittest.main()
