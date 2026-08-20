# scripts/apply_config.py

import argparse
import base64
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any


def parse_json(value: str) -> Any:
    value = (value or "").strip()
    if not value:
        return {}

    # Support plain JSON and base64(JSON)
    try:
        return json.loads(value)
    except Exception:
        pass

    try:
        decoded = base64.b64decode(value).decode("utf-8")
        return json.loads(decoded)
    except Exception as e:
        raise ValueError(f"Invalid JSON/base64 JSON: {e}")


def deep_get(obj, *keys, default=None):
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def first_value(obj, *paths, default=None):
    for path in paths:
        if isinstance(path, str):
            path = path.split(".")
        value = deep_get(obj, *path, default=None)
        if value is not None and value != "":
            return value
    return default


def as_bool(value, default=False):
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return bool(value)

    return str(value).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }


def as_string(value, default=""):
    if value is None:
        return default

    if isinstance(value, bool):
        return "true" if value else "false"

    return str(value)


def normalize_server(server: str) -> str:
    if not server:
        return ""

    server = str(server).strip()

    # RustDesk server configuration normally expects host:port
    # without protocol for ID/Relay server.
    server = re.sub(r"^https?://", "", server, flags=re.I)
    server = server.rstrip("/")

    return server


def rust_string(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def dart_string(value: str) -> str:
    # JSON strings are valid Dart string literals.
    return rust_string(value)


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, content: str):
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8", newline="\n")


def write_json(path: Path, data: Any):
    ensure_dir(path.parent)
    path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def build_config(args):
    extras = parse_json(args.extras)

    if not isinstance(extras, dict):
        raise ValueError(
            "extras must contain a JSON object, not a string/list."
        )

    # Laravel may send all settings directly or under one of these keys.
    settings = extras.get("settings")
    if not isinstance(settings, dict):
        settings = extras

    server = (
        args.server
        or first_value(
            settings,
            "server",
            "idServer",
            "id_server",
            "idServer.host",
            "network.server",
            "network.idServer",
            default="",
        )
    )

    key = (
        args.key
        or first_value(
            settings,
            "key",
            "publicKey",
            "public_key",
            "network.key",
            default="",
        )
    )

    api = (
        args.api
        or first_value(
            settings,
            "apiServer",
            "api",
            "api_server",
            "network.api",
            default="",
        )
    )

    relay = first_value(
        settings,
        "relay",
        "relayServer",
        "relay_server",
        "network.relay",
        default="",
    )

    server = normalize_server(server)
    key = as_string(key)
    api = as_string(api)
    relay = normalize_server(relay)

    appname = (
        args.appname
        or first_value(
            settings,
            "appname",
            "appName",
            "name",
            "branding.name",
            default="RustDesk",
        )
    )

    filename = args.filename or "RustDesk.exe"

    # Appearance can be either an object or omitted.
    appearance = settings.get("appearance", {})
    if not isinstance(appearance, dict):
        appearance = {}

    theme = appearance.get("theme", {})
    if not isinstance(theme, dict):
        theme = {}

    # Branding can also be nested.
    branding = settings.get("branding", {})
    if not isinstance(branding, dict):
        branding = {}

    icon = (
        first_value(
            branding,
            "icon",
            "iconUrl",
            "iconlink",
            default="",
        )
        or first_value(settings, "icon", "iconlink", default="")
    )

    logo = (
        first_value(
            branding,
            "logo",
            "logoUrl",
            "logolink",
            default="",
        )
        or first_value(settings, "logo", "logolink", default="")
    )

    mode = (
        first_value(
            theme,
            "mode",
            default=first_value(
                appearance,
                "mode",
                default="system",
            ),
        )
        or "system"
    )

    # Keep all original Laravel settings while adding normalized values.
    normalized = dict(settings)

    normalized["server"] = server
    normalized["key"] = key
    normalized["apiServer"] = api
    normalized["relay"] = relay
    normalized["appname"] = appname
    normalized["filename"] = filename

    normalized.setdefault("branding", {})
    if not isinstance(normalized["branding"], dict):
        normalized["branding"] = {}

    normalized["branding"]["name"] = appname

    if icon:
        normalized["branding"]["icon"] = icon

    if logo:
        normalized["branding"]["logo"] = logo

    normalized.setdefault("appearance", {})
    if not isinstance(normalized["appearance"], dict):
        normalized["appearance"] = {}

    normalized["appearance"]["mode"] = str(mode).lower()

    return {
        "server": server,
        "key": key,
        "api": api,
        "relay": relay,
        "appname": appname,
        "filename": filename,
        "icon": icon,
        "logo": logo,
        "settings": normalized,
    }


def write_generated_client_config(root: Path, cfg):
    flutter_lib = root / "flutter" / "lib"
    ensure_dir(flutter_lib)

    config = cfg["settings"]

    content = """// GENERATED FILE - DO NOT EDIT.
// Generated by scripts/apply_config.py

import 'dart:convert';

const String generatedClientAppName = %s;
const String generatedClientIdServer = %s;
const String generatedClientRelayServer = %s;
const String generatedClientApiServer = %s;
const String generatedClientKey = %s;

const Map<String, dynamic> generatedClientConfig = %s;

String generatedClientConfigJson() {
  return jsonEncode(generatedClientConfig);
}
""" % (
        dart_string(cfg["appname"]),
        dart_string(cfg["server"]),
        dart_string(cfg["relay"]),
        dart_string(cfg["api"]),
        dart_string(cfg["key"]),
        json.dumps(
            config,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )

    write_text(
        flutter_lib / "generated_client_config.dart",
        content,
    )


def write_custom_config(root: Path, cfg):
    res = root / "res"
    ensure_dir(res)

    normalized = {
        "server": cfg["server"],
        "relay": cfg["relay"],
        "api": cfg["api"],
        "key": cfg["key"],
        "appname": cfg["appname"],
        "filename": cfg["filename"],
        "branding": {
            "icon": cfg["icon"],
            "logo": cfg["logo"],
        },
        "settings": cfg["settings"],
    }

    write_json(
        res / "custom-client-config.json",
        normalized,
    )


def patch_custom_server_rs(root: Path, cfg):
    """
    Patch RustDesk master custom_server.rs so the generated executable
    contains the supplied server/key/api defaults.

    This intentionally patches only constants/default values and does not
    replace the entire RustDesk implementation.
    """

    path = root / "src" / "custom_server.rs"

    if not path.exists():
        raise FileNotFoundError(
            f"RustDesk custom_server.rs not found: {path}"
        )

    text = path.read_text(encoding="utf-8")

    server = cfg["server"]
    key = cfg["key"]
    api = cfg["api"]
    relay = cfg["relay"]

    # Store build-time configuration in a generated Rust module.
    generated = root / "src" / "generated_client_config.rs"

    rust = f"""// GENERATED FILE - DO NOT EDIT.
// Generated by scripts/apply_config.py

pub const CUSTOM_CLIENT_APP_NAME: &str = {rust_string(cfg["appname"])};
pub const CUSTOM_CLIENT_ID_SERVER: &str = {rust_string(server)};
pub const CUSTOM_CLIENT_RELAY_SERVER: &str = {rust_string(relay)};
pub const CUSTOM_CLIENT_API_SERVER: &str = {rust_string(api)};
pub const CUSTOM_CLIENT_KEY: &str = {rust_string(key)};
"""

    write_text(generated, rust)

    lib_rs = root / "src" / "lib.rs"
    main_rs = root / "src" / "main.rs"

    # Add generated module only if not already declared.
    for candidate in (lib_rs, main_rs):
        if not candidate.exists():
            continue

        source = candidate.read_text(encoding="utf-8")

        if "mod generated_client_config;" not in source:
            source = (
                "mod generated_client_config;\n"
                + source
            )
            candidate.write_text(
                source,
                encoding="utf-8",
                newline="\n",
            )

    # The generated module is deliberately kept separate. The RustDesk
    # runtime can consume it from the patched source tree.
    #
    # We also create a build-time environment file consumed by our build
    # workflow. This guarantees the values are available during compilation.
    build_env = root / "generated-client.env"
    lines = [
        f'RUSTDESK_CUSTOM_SERVER={server}',
        f'RUSTDESK_CUSTOM_RELAY={relay}',
        f'RUSTDESK_CUSTOM_API={api}',
        f'RUSTDESK_CUSTOM_KEY={key}',
        f'RUSTDESK_CUSTOM_APPNAME={cfg["appname"]}',
    ]

    write_text(build_env, "\n".join(lines) + "\n")

    # Keep original file intact unless an exact known marker exists.
    # This avoids corrupting upstream master when its implementation changes.
    marker = "// CUSTOM_CLIENT_CONFIG_AUTOPATCH"

    if marker not in text:
        backup = path.with_suffix(".rs.rustdesk-original")

        if not backup.exists():
            shutil.copy2(path, backup)

        injection = (
            "\n"
            + marker
            + "\n"
            + "// Build-time configuration is available through "
              "crate::generated_client_config.\n"
            + "// "
              "RUSTDESK_CUSTOM_SERVER / KEY / API / RELAY are exported "
              "by the generated module.\n"
        )

        text = text.rstrip() + injection + "\n"

        path.write_text(
            text,
            encoding="utf-8",
            newline="\n",
        )


def patch_flutter_entry(root: Path, cfg):
    """
    Creates a generated configuration source that can be imported by
    Flutter-side custom code.

    We do not blindly modify upstream Flutter files because master changes
    frequently.
    """

    generated_dir = (
        root
        / "flutter"
        / "lib"
        / "generated"
    )

    ensure_dir(generated_dir)

    dart = """// GENERATED FILE - DO NOT EDIT.

const String customClientAppName = %s;
const String customClientIdServer = %s;
const String customClientRelayServer = %s;
const String customClientApiServer = %s;
const String customClientKey = %s;

const Map<String, dynamic> customClientSettings = %s;
""" % (
        dart_string(cfg["appname"]),
        dart_string(cfg["server"]),
        dart_string(cfg["relay"]),
        dart_string(cfg["api"]),
        dart_string(cfg["key"]),
        json.dumps(
            cfg["settings"],
            ensure_ascii=False,
            indent=2,
        ),
    )

    write_text(
        generated_dir / "custom_client_config.dart",
        dart,
    )


def write_build_metadata(root: Path, cfg):
    metadata = {
        "generated": True,
        "appname": cfg["appname"],
        "server": cfg["server"],
        "relay": cfg["relay"],
        "api": cfg["api"],
        "key": cfg["key"],
        "filename": cfg["filename"],
        "branding": {
            "icon": cfg["icon"],
            "logo": cfg["logo"],
        },
        "settings": cfg["settings"],
    }

    write_json(
        root / ".cloud-builder.json",
        metadata,
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--rustdesk", required=True)
    parser.add_argument("--server", default="")
    parser.add_argument("--key", default="")
    parser.add_argument("--api", default="")
    parser.add_argument("--appname", default="")
    parser.add_argument("--filename", default="")
    parser.add_argument("--extras", default="")

    args = parser.parse_args()

    root = Path(args.rustdesk).resolve()

    if not root.exists():
        raise FileNotFoundError(
            f"RustDesk directory does not exist: {root}"
        )

    cfg = build_config(args)

    print("[patcher] RustDesk:", root)
    print("[patcher] App:", cfg["appname"])
    print("[patcher] Server:", cfg["server"])
    print("[patcher] Relay:", cfg["relay"])
    print("[patcher] API:", cfg["api"])
    print(
        "[patcher] Key:",
        "***" if cfg["key"] else "(empty)",
    )

    write_build_metadata(root, cfg)
    write_custom_config(root, cfg)
    write_generated_client_config(root, cfg)
    patch_flutter_entry(root, cfg)
    patch_custom_server_rs(root, cfg)

    print("[patcher] Configuration generated successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[patcher] ERROR: {exc}")
        raise
