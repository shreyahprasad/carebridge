"""Opt-in live catalog rehearsal; default harness tests never call the API."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys

from runner import Budget, Tool, run_agent
from shreyah_harness.runtime import anthropic_client
import shreyah_harness.runtime as shared_runtime
import shreyah_harness.guardrails as shared_guardrails

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="explicitly permit paid model calls")
    parser.add_argument("--metadata-only", action="store_true", help="emit comparison provenance without a model call")
    parser.add_argument("--prompt", type=Path, default=ROOT / "prompts/baseline.txt")
    args = parser.parse_args()
    if not args.live and not args.metadata_only:
        parser.error("live calls require --live; use offline unit tests for protocol validation")
    if not os.environ.get("CLAUDE_MODEL"):
        parser.error("CLAUDE_MODEL must be configured")
    if not args.metadata_only and not os.environ.get("ANTHROPIC_API_KEY"):
        parser.error("ANTHROPIC_API_KEY and CLAUDE_MODEL must be configured; values are never printed")
    prompt = args.prompt.read_text()
    limits = {"max_requests": 6, "max_tools": 4, "max_retries": 1, "seconds": 30}
    try:
        sdk_version = importlib.metadata.version("anthropic")
    except importlib.metadata.PackageNotFoundError:
        sdk_version = "not-installed"
    try:
        schema_version = importlib.metadata.version("jsonschema")
    except importlib.metadata.PackageNotFoundError:
        schema_version = "not-installed"
    def file_hash(name):
        return hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    metadata = {"comparison": {"model": os.environ["CLAUDE_MODEL"], "sdk_version": sdk_version,
                               "runner_sha256": file_hash("runner.py"),
                               "runtime_sha256": hashlib.sha256(Path(shared_runtime.__file__).read_bytes()).hexdigest(),
                               "guardrails_sha256": hashlib.sha256(Path(shared_guardrails.__file__).read_bytes()).hexdigest(),
                               "jsonschema_version": schema_version,
                               "adapter_sha256": file_hash("adapter.py"),
                               "fixtures_sha256": file_hash("catalog.json"), "limits": limits, "max_tokens": 800},
                "candidate": {"prompt_version": args.prompt.stem,
                              "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()}}
    if args.metadata_only:
        print(json.dumps(metadata))
        return
    try:
        from anthropic import APIConnectionError, APITimeoutError, RateLimitError, InternalServerError
    except ImportError:
        parser.error("install optional dependencies from requirements.txt in the project virtual environment")
    task = json.load(sys.stdin)
    catalog = json.loads((ROOT / "catalog.json").read_text())
    observed = {}

    def validate_lookup(value):
        if not isinstance(value, dict) or set(value) != {"item_id"} or not isinstance(value["item_id"], str):
            raise ValueError("lookup requires exactly item_id: string")
        if value["item_id"] != task.get("item_id"):
            raise ValueError("lookup outside requested item")

    def lookup(value):
        record = catalog.get(value["item_id"])
        observed["record"] = record
        observed["looked_up"] = True
        return {"record": record, "source": "synthetic-catalog-v1"}

    def validate_output(value):
        if not observed.get("looked_up") or not isinstance(value, dict) or set(value) != {"item_id", "available", "source"}:
            raise ValueError("a real lookup and exact result fields are required")
        record = observed["record"]
        expected = record["available"] if record else None
        if value["item_id"] != task.get("item_id") or value["source"] != "synthetic-catalog-v1":
            raise ValueError("unsupported identifier or source")
        if type(value["available"]) is not type(expected) or value["available"] != expected:
            raise ValueError("availability unsupported by observed lookup")

    tool = Tool({"name": "lookup_catalog", "description": "Read one item from a synthetic catalog. Missing availability stays null.",
                 "input_schema": {"type": "object", "properties": {"item_id": {"type": "string"}},
                                  "required": ["item_id"], "additionalProperties": False}}, validate_lookup, lookup, risk="read",
                resource=lambda value: value["item_id"])
    client = anthropic_client(timeout=30)
    result = run_agent(client.messages.create, model=os.environ["CLAUDE_MODEL"],
                       prompt=prompt, prompt_version=args.prompt.stem, task=task, tools=[tool],
                       validate_output=validate_output, budget=Budget(**limits),
                       retryable=(APIConnectionError, APITimeoutError, RateLimitError, InternalServerError))
    client.close()
    result["run"]["fixtures_sha256"] = hashlib.sha256(json.dumps(catalog, sort_keys=True).encode()).hexdigest()
    result["metadata"] = metadata
    print(json.dumps(result))


if __name__ == "__main__":
    main()
