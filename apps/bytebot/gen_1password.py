import argparse
import json
import os
import shutil
import subprocess
import tempfile
from getpass import getpass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

import yaml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a 1Password database item populated with Bytebot secrets")
    parser.add_argument("vault_id", help="Target 1Password vault identifier")
    parser.add_argument("item_title", help="Title for the new 1Password item")
    parser.add_argument("values_path", nargs="?", default="apps/bytebot/values.yaml", help="Path to the Bytebot values.yaml file")
    parser.add_argument("--secret-name", default="secrets", help="Secret name referenced in the Helm chart")
    parser.add_argument("--env-prefix", default="BYTEBOT_SECRET", help="Environment variable prefix for secret values")
    parser.add_argument("--secrets-file", help="Path to a YAML or JSON file containing secret overrides")
    parser.add_argument("--database-host", help="Hostname stored in the database item")
    parser.add_argument("--database-port", help="Port stored in the database item")
    parser.add_argument("--database-name", help="Database name stored in the database item")
    parser.add_argument("--database-username", help="Database username stored in the database item")
    parser.add_argument("--database-password", help="Database password stored in the database item")
    parser.add_argument("--dry-run", action="store_true", help="Render the payload without creating the 1Password item")
    return parser.parse_args()


def ensure_dependencies() -> None:
    if shutil.which("op") is None:
        raise RuntimeError("The 1Password CLI (op) must be installed and available on PATH")


def load_yaml(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError("The values file must contain a mapping at the root")
    return data


def collect_secret_keys(node: object, secret_name: str) -> Set[str]:
    keys: Set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            if "secretKeyRef" in value and isinstance(value["secretKeyRef"], dict):
                ref = value["secretKeyRef"]
                if ref.get("name") == secret_name and "key" in ref:
                    keys.add(str(ref["key"]))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(node)
    return keys


def load_overrides(path: Optional[str]) -> Dict[str, str]:
    if not path:
        return {}
    data_path = Path(path)
    with data_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError("Overrides file must contain a mapping of secret keys to values")
    return {str(key): str(value) for key, value in loaded.items()}


def build_env_key(prefix: str, key: str) -> str:
    normalized = key.upper().replace("-", "_")
    return f"{prefix}_{normalized}"


def resolve_secret_value(key: str, prefix: str, overrides: Dict[str, str]) -> str:
    if key in overrides:
        return overrides[key]
    env_key = build_env_key(prefix, key)
    env_value = os.getenv(env_key)
    if env_value:
        return env_value
    prompt = f"Enter value for {key}: "
    value = getpass(prompt)
    if not value:
        raise ValueError(f"No value provided for {key}")
    return value


def ensure_secret_values(keys: Iterable[str], prefix: str, overrides: Dict[str, str]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for key in sorted(keys):
        result[key] = resolve_secret_value(key, prefix, overrides)
    return result


def fetch_template() -> Dict:
    command = ["op", "item", "template", "get", "database"]
    response = subprocess.run(command, check=True, capture_output=True, text=True)
    template = json.loads(response.stdout)
    return template


def slugify(value: str) -> str:
    return value.lower().replace(" ", "-").replace("_", "-")


def attach_database_fields(template: Dict, args: argparse.Namespace) -> None:
    field_map: Dict[str, Dict] = {field.get("id"): field for field in template.get("fields", []) if isinstance(field, dict)}
    if args.database_host and "hostname" in field_map:
        field_map["hostname"]["value"] = args.database_host
    if args.database_port and "port" in field_map:
        field_map["port"]["value"] = args.database_port
    if args.database_name and "database" in field_map:
        field_map["database"]["value"] = args.database_name
    sections: List[Dict] = template.get("sections", [])
    for section in sections:
        if not isinstance(section, dict):
            continue
        section_fields = section.get("fields")
        if not isinstance(section_fields, list):
            continue
        section_field_map = {field.get("id"): field for field in section_fields if isinstance(field, dict)}
        if args.database_username and "username" in section_field_map:
            section_field_map["username"]["value"] = args.database_username
        if args.database_password and "password" in section_field_map:
            section_field_map["password"]["value"] = args.database_password


def append_secret_section(template: Dict, secrets: Dict[str, str]) -> None:
    if not secrets:
        return
    sections: List[Dict] = template.setdefault("sections", [])
    section_id = slugify("Bytebot Secrets")
    fields: List[Dict] = []
    for key, value in secrets.items():
        field_id = slugify(key)
        fields.append({"id": field_id, "label": key, "type": "CONCEALED", "value": value})
    section = {"id": section_id, "label": "Bytebot Secrets", "fields": fields}
    sections.append(section)


def create_item_payload(args: argparse.Namespace, template: Dict, secrets: Dict[str, str]) -> Dict:
    payload = template
    payload["title"] = args.item_title
    payload["vault"] = {"id": args.vault_id}
    attach_database_fields(payload, args)
    append_secret_section(payload, secrets)
    return payload


def execute_create(payload: Dict, dry_run: bool) -> Optional[str]:
    serialized = json.dumps(payload)
    if dry_run:
        print(serialized)
        return None
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(serialized)
        temp_path = handle.name
    try:
        command = ["op", "item", "create", "--template", temp_path, "--format", "json"]
        response = subprocess.run(command, check=True, capture_output=True, text=True)
    finally:
        Path(temp_path).unlink(missing_ok=True)
    created = json.loads(response.stdout)
    item_id = created.get("id")
    if not item_id:
        raise RuntimeError("Failed to retrieve the new item identifier")
    return item_id


def main() -> None:
    args = parse_args()
    ensure_dependencies()
    values_file = Path(args.values_path)
    if not values_file.exists():
        raise FileNotFoundError(f"Values file not found: {values_file}")
    values_data = load_yaml(values_file)
    secret_keys = collect_secret_keys(values_data, args.secret_name)
    overrides = load_overrides(args.secrets_file)
    secrets = ensure_secret_values(secret_keys, args.env_prefix, overrides)
    template = fetch_template()
    payload = create_item_payload(args, template, secrets)
    item_id = execute_create(payload, args.dry_run)
    if item_id:
        print(f"Created item ID: {item_id}")


if __name__ == "__main__":
    main()
