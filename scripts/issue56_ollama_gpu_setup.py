#!/usr/bin/env python3
"""Prepare one Ollama 0.40.2 service per GPU on a NEW host; default is plan only.

Run locally on the new host after its operator supplies GPU IDs, unused ports,
new container names/data directories and a complete verified model digest.
This tool does not connect to another host or change existing containers.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.request

VERSION = "0.40.2"


def build_plan(lanes: list[dict], model: str, expected_digest: str) -> list[dict]:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_digest) or not model.strip():
        raise ValueError("a model name and full 64-character digest are required")
    if not lanes:
        raise ValueError("at least one GPU lane is required")
    seen = {key: set() for key in ("gpu", "port", "name", "data_dir")}
    plan = []
    for lane in lanes:
        for key in seen:
            if lane[key] in seen[key]:
                raise ValueError("GPU, port, container name and data directory must each be distinct")
            seen[key].add(lane[key])
        gpu, port, name, data = lane["gpu"], lane["port"], lane["name"], lane["data_dir"]
        if (not isinstance(gpu, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", gpu)
                or type(port) is not int or not 1024 <= port <= 65535
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]+", name)
                or not Path(data).is_absolute() or ":" in data):
            raise ValueError("invalid new-host lane configuration")
        bind = lane.get("bind", "127.0.0.1")
        bind = str(ipaddress.IPv4Address(bind))
        command = ["docker", "run", "-d", "--name", name, "--gpus", f"device={gpu}",
                   "-p", f"{bind}:{port}:11434", "-v", f"{data}:/root/.ollama",
                   "-e", "OLLAMA_HOST=0.0.0.0:11434", f"ollama/ollama:{VERSION}"]
        plan.append({"command": command, "name": name, "data_dir": data,
                     "url": f"http://{'127.0.0.1' if bind == '0.0.0.0' else bind}:{port}",
                     "model": model, "expected_digest": expected_digest})
    return plan


def verify_metadata(version: dict, tags: dict, model: str, digest: str) -> None:
    if version.get("version") != VERSION:
        raise ValueError("Ollama version mismatch")
    matches = [m for m in tags.get("models", []) if m.get("name") == model]
    if len(matches) != 1 or matches[0].get("digest") != digest:
        raise ValueError("model digest mismatch or model missing")


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


def apply_plan(plan: list[dict]) -> None:
    # Preflight every lane before creating any service. Never remove or replace one.
    existing = set(subprocess.check_output(["docker", "ps", "-a", "--format", "{{.Names}}"], text=True).splitlines())
    for lane in plan:
        if lane["name"] in existing or Path(lane["data_dir"]).exists():
            raise ValueError("new-host setup requires unused container names and new data directories")
    for lane in plan:
        Path(lane["data_dir"]).mkdir(mode=0o700, parents=True)
        subprocess.run(lane["command"], check=True)
        deadline = time.monotonic() + 120
        while True:
            try:
                version = get_json(lane["url"] + "/api/version")
                break
            except (OSError, urllib.error.URLError):
                if time.monotonic() >= deadline:
                    raise TimeoutError("new Ollama service did not become healthy")
                time.sleep(1)
        if version.get("version") != VERSION:
            raise ValueError("Ollama version mismatch; service retained for operator inspection")
        subprocess.run(["docker", "exec", lane["name"], "ollama", "pull", lane["model"]], check=True)
        verify_metadata(version, get_json(lane["url"] + "/api/tags"), lane["model"], lane["expected_digest"])
        print(json.dumps({"name": lane["name"], "healthy": True, "version": VERSION,
                          "model_digest": lane["expected_digest"]}), flush=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lanes", required=True, help="JSON array: gpu, port, name, new data_dir, optional bind")
    parser.add_argument("--model", required=True)
    parser.add_argument("--expected-digest", required=True)
    parser.add_argument("--apply", action="store_true", help="execute locally on the operator-configured NEW host")
    args = parser.parse_args(argv)
    plan = build_plan(json.loads(Path(args.lanes).read_text()), args.model, args.expected_digest)
    if args.apply:
        apply_plan(plan)
    else:
        print(json.dumps({"executed": False, "plan": plan}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
