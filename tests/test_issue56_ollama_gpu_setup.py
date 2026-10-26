from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

import _paths  # noqa: F401

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "issue56_ollama_gpu_setup.py"


class GpuSetupTests(unittest.TestCase):
    def tool(self):
        spec = importlib.util.spec_from_file_location("gpu_setup", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_plan_is_one_container_per_gpu_with_distinct_ports_and_no_execution(self):
        tool = self.tool()
        lanes = [{"gpu": str(i), "port": 11500 + i, "name": f"annotation-{i}",
                  "data_dir": f"/tmp/new-model-{i}"} for i in range(3)]
        plan = tool.build_plan(lanes, "local-model", "a" * 64)
        self.assertEqual(len(plan), 3)
        for index, lane in enumerate(plan):
            cmd = lane["command"]
            self.assertEqual(cmd[cmd.index("--gpus") + 1], f"device={index}")
            self.assertEqual(cmd[-1], "ollama/ollama:0.40.2")
            self.assertEqual(lane["expected_digest"], "a" * 64)
            self.assertNotIn("--privileged", cmd)

    def test_full_digest_and_distinct_lane_resources_are_required(self):
        tool = self.tool()
        lane = {"gpu": "0", "port": 11500, "name": "annotation-0", "data_dir": "/tmp/new-model-0"}
        with self.assertRaises(ValueError):
            tool.build_plan([lane], "local-model", "c2ae7f03")
        with self.assertRaises(ValueError):
            tool.build_plan([lane, lane], "local-model", "a" * 64)

    def test_health_uses_explicit_lan_bind_and_only_wildcard_maps_to_loopback(self):
        tool = self.tool()
        lane = {"gpu": "0", "port": 11500, "name": "annotation-0", "data_dir": "/tmp/new-model-0",
                "bind": "192.0.2.25"}
        self.assertEqual(tool.build_plan([lane], "m", "a" * 64)[0]["url"], "http://192.0.2.25:11500")
        lane["bind"] = "0.0.0.0"
        self.assertEqual(tool.build_plan([lane], "m", "a" * 64)[0]["url"], "http://127.0.0.1:11500")
        lane["bind"] = "999.999.999.999"
        with self.assertRaises(ValueError):
            tool.build_plan([lane], "m", "a" * 64)

    def test_digest_or_version_mismatch_cannot_pass_health(self):
        tool = self.tool()
        with self.assertRaises(ValueError):
            tool.verify_metadata({"version": "0.40.1"}, {"models": []}, "m", "a" * 64)
        with self.assertRaises(ValueError):
            tool.verify_metadata({"version": "0.40.2"}, {"models": [{"name": "m", "digest": "b" * 64}]},
                                 "m", "a" * 64)
        tool.verify_metadata({"version": "0.40.2"}, {"models": [{"name": "m", "digest": "a" * 64}]},
                             "m", "a" * 64)
