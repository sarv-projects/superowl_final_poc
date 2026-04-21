#!/usr/bin/env python3
"""VAPI account migration utility for SuperOwl demo handoffs.

Usage:
  python vapi_migrate.py export
  python vapi_migrate.py import --key <new_vapi_key> --ngrok <https://new-url.ngrok-free.app>
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx

DEFAULT_EXPORT_FILE = "vapi_export.json"
BASE_URL = "https://api.vapi.ai"

STRIP_FIELDS = {
    "id",
    "orgId",
    "createdAt",
    "updatedAt",
    "isServerUrlSecretSet",
    "assistantId",
}

TOOL_IDENTITY_KEYS = ("name", "server", "description")
WORKSPACE_ROOT = Path.cwd().resolve()


def _safe_local_path(path_value: str, must_exist: bool = False) -> Path:
    """Resolve a user-provided path and keep file access within the workspace."""
    candidate = Path(path_value).expanduser().resolve(strict=False)
    try:
        candidate.relative_to(WORKSPACE_ROOT)
    except ValueError as exc:
        raise ValueError(f"Path is outside workspace: {path_value}") from exc

    if must_exist and not candidate.exists():
        raise FileNotFoundError(f"Path does not exist: {path_value}")
    return candidate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SuperOwl VAPI migration helper")
    sub = parser.add_subparsers(dest="command", required=True)

    exp = sub.add_parser("export", help="Export tools, assistants, and phone numbers")
    exp.add_argument("--key", default=os.getenv("VAPI_API_KEY"), help="VAPI API key")
    exp.add_argument("--out", default=DEFAULT_EXPORT_FILE, help="Output file")

    imp = sub.add_parser("import", help="Import into another VAPI account")
    imp.add_argument("--key", required=True, help="Target VAPI API key")
    imp.add_argument("--in", dest="in_file", default=DEFAULT_EXPORT_FILE, help="Input file")
    imp.add_argument("--ngrok", default=None, help="New ngrok base URL to rewrite webhook/tool URLs")
    imp.add_argument("--skip-webhooks", action="store_true", help="Skip URL rewrite for webhook/server URLs")
    imp.add_argument("--env-file", default=".env", help="Optional env file to patch with imported IDs")
    return parser.parse_args()


def make_client(api_key: str) -> httpx.Client:
    if not api_key:
        raise ValueError("Missing VAPI API key")
    return httpx.Client(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=30.0,
    )


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "results", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


def _get_collection(client: httpx.Client, paths: list[str]) -> tuple[str, list[dict[str, Any]]]:
    last_err = None
    for path in paths:
        try:
            resp = client.get(path)
            if resp.status_code >= 400:
                last_err = f"{path}: HTTP {resp.status_code}"
                continue
            items = _extract_items(resp.json())
            return path, items
        except Exception as exc:  # noqa: BLE001
            last_err = f"{path}: {exc}"
    raise RuntimeError(f"Failed fetching collection. Last error: {last_err}")


def _strip_fields(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_fields(x) for x in value]
    if isinstance(value, dict):
        cleaned = {}
        for k, v in value.items():
            if k in STRIP_FIELDS:
                continue
            cleaned[k] = _strip_fields(v)
        return cleaned
    return value


def _tool_identity(tool: dict[str, Any]) -> str:
    data = [str(tool.get(k, "")) for k in TOOL_IDENTITY_KEYS]
    return "|".join(data)


def export_account(api_key: str, output_file: str) -> None:
    with make_client(api_key) as client:
        tools_path, tools = _get_collection(client, ["/tool", "/tools"])
        assistants_path, assistants = _get_collection(client, ["/assistant", "/assistants"])
        phones_path, phone_numbers = _get_collection(client, ["/phone-number", "/phone-numbers"])

    payload = {
        "meta": {
            "base_url": BASE_URL,
            "endpoints": {
                "tools": tools_path,
                "assistants": assistants_path,
                "phone_numbers": phones_path,
            },
        },
        "tools": [_strip_fields(x) for x in tools],
        "assistants": [_strip_fields(x) for x in assistants],
        "phone_numbers": [_strip_fields(x) for x in phone_numbers],
    }

    output_path = _safe_local_path(output_file)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Exported {len(tools)} tools, {len(assistants)} assistants, {len(phone_numbers)} phone numbers -> {output_path}")


def _rewrite_ngrok_urls(value: Any, ngrok_base: str) -> Any:
    ngrok_base = ngrok_base.rstrip("/")
    pattern = re.compile(r"https://[^/]*ngrok[^/]*", flags=re.IGNORECASE)

    if isinstance(value, str):
        if "ngrok" in value.lower() and value.startswith("http"):
            return pattern.sub(ngrok_base, value)
        return value
    if isinstance(value, list):
        return [_rewrite_ngrok_urls(v, ngrok_base) for v in value]
    if isinstance(value, dict):
        return {k: _rewrite_ngrok_urls(v, ngrok_base) for k, v in value.items()}
    return value


def _remap_tool_ids(value: Any, id_map: dict[str, str]) -> Any:
    if isinstance(value, list):
        return [_remap_tool_ids(v, id_map) for v in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if k in {"toolId", "tool_id"} and isinstance(v, str):
                out[k] = id_map.get(v, v)
            elif k in {"toolIds", "tool_ids"} and isinstance(v, list):
                out[k] = [id_map.get(str(x), str(x)) for x in v]
            else:
                out[k] = _remap_tool_ids(v, id_map)
        return out
    return value


def _post_item(client: httpx.Client, paths: list[str], payload: dict[str, Any]) -> dict[str, Any]:
    last_err = None
    for path in paths:
        try:
            resp = client.post(path, json=payload)
            if resp.status_code >= 400:
                last_err = f"{path}: HTTP {resp.status_code} {resp.text[:300]}"
                continue
            body = resp.json()
            if isinstance(body, dict):
                return body
            return {"raw": body}
        except Exception as exc:  # noqa: BLE001
            last_err = f"{path}: {exc}"
    raise RuntimeError(f"Create failed. Last error: {last_err}")


def _patch_env_file(env_file: str, updates: dict[str, str]) -> None:
    path = _safe_local_path(env_file)
    if not path.exists():
        return

    lines = path.read_text(encoding="utf-8").splitlines()
    seen = set()
    new_lines: list[str] = []
    for line in lines:
        if "=" not in line or line.strip().startswith("#"):
            new_lines.append(line)
            continue
        key, _ = line.split("=", 1)
        key = key.strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            new_lines.append(line)

    for key, val in updates.items():
        if key not in seen:
            new_lines.append(f"{key}={val}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def import_account(api_key: str, in_file: str, ngrok: str | None, skip_webhooks: bool, env_file: str) -> None:
    input_path = _safe_local_path(in_file, must_exist=True)
    data = json.loads(input_path.read_text(encoding="utf-8"))
    tools = data.get("tools", [])
    assistants = data.get("assistants", [])
    phones = data.get("phone_numbers", [])

    tool_id_map: dict[str, str] = {}
    created_tools: list[dict[str, Any]] = []
    created_assistants: list[dict[str, Any]] = []
    created_phones: list[dict[str, Any]] = []

    with make_client(api_key) as client:
        # Build map of existing tools first to avoid duplicates.
        _, existing_tools = _get_collection(client, ["/tool", "/tools"])
        existing_by_identity = {_tool_identity(t): str(t.get("id", "")) for t in existing_tools}

        for tool in tools:
            original_tool = copy.deepcopy(tool)
            old_id = str(original_tool.get("id", ""))
            clean_tool = _strip_fields(original_tool)
            if ngrok and not skip_webhooks:
                clean_tool = _rewrite_ngrok_urls(clean_tool, ngrok)

            identity = _tool_identity(clean_tool)
            if identity in existing_by_identity and existing_by_identity[identity]:
                tool_id_map[old_id] = existing_by_identity[identity]
                continue

            created = _post_item(client, ["/tool", "/tools"], clean_tool)
            new_id = str(created.get("id", ""))
            if old_id and new_id:
                tool_id_map[old_id] = new_id
            created_tools.append(created)

        for assistant in assistants:
            old_id = str(assistant.get("id", ""))
            clean_assistant = _strip_fields(copy.deepcopy(assistant))
            clean_assistant = _remap_tool_ids(clean_assistant, tool_id_map)
            if ngrok and not skip_webhooks:
                clean_assistant = _rewrite_ngrok_urls(clean_assistant, ngrok)

            created = _post_item(client, ["/assistant", "/assistants"], clean_assistant)
            if old_id and created.get("id"):
                pass
            created_assistants.append(created)

        for phone in phones:
            clean_phone = _strip_fields(copy.deepcopy(phone))
            if ngrok and not skip_webhooks:
                clean_phone = _rewrite_ngrok_urls(clean_phone, ngrok)
            try:
                created = _post_item(client, ["/phone-number", "/phone-numbers"], clean_phone)
                created_phones.append(created)
            except RuntimeError:
                # Some accounts do not allow re-creating purchased numbers; keep import non-blocking.
                continue

    updates: dict[str, str] = {}
    if created_phones and created_phones[0].get("id"):
        updates["VAPI_PHONE_NUMBER_ID"] = str(created_phones[0]["id"])
    if created_assistants and created_assistants[0].get("id"):
        updates["VAPI_INBOUND_ASSISTANT_ID"] = str(created_assistants[0]["id"])
    if len(created_assistants) > 1 and created_assistants[1].get("id"):
        updates["VAPI_OUTBOUND_ASSISTANT_ID"] = str(created_assistants[1]["id"])

    if updates:
        _patch_env_file(env_file, updates)

    print(
        "Imported",
        f"tools={len(created_tools)}",
        f"assistants={len(created_assistants)}",
        f"phone_numbers={len(created_phones)}",
    )
    if updates:
        print(f"Patched {env_file}: {', '.join(sorted(updates.keys()))}")


def main() -> None:
    args = parse_args()
    if args.command == "export":
        export_account(args.key, args.out)
        return
    import_account(args.key, args.in_file, args.ngrok, args.skip_webhooks, args.env_file)


if __name__ == "__main__":
    main()
