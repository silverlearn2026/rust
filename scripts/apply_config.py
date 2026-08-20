#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
RustDesk Laravel Custom Client Builder

This script is intentionally fail-fast.

It:
  - Parses Laravel extras, including JSON encoded nested strings.
  - Patches RustDesk hbb_common/config.rs with server + public key.
  - Patches API server through RustDesk configuration options.
  - Patches application name.
  - Generates a strongly typed Flutter configuration.
  - Patches Flutter startup/theme/window configuration where the
    corresponding source structures are found.
  - Downloads branding assets.
  - Patches Windows icon resources when possible.
  - FAILS if mandatory server/key/config patches cannot be verified.

This script is designed to run after:
    actions/checkout rustdesk with submodules: recursive
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


# ============================================================
# Logging
# ============================================================

def info(message: str) -> None:
    print(f"[patcher] {message}")


def warn(message: str) -> None:
    print(f"[patcher] WARNING: {message}")


def fail(message: str) -> None:
    print(f"[patcher] ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


# ============================================================
# Recursive Laravel JSON parser
# ============================================================

def decode_nested(value: Any, depth: int = 0) -> Any:
    """
    Laravel may send nested structures like:

        "theme": "system"

    or:

        "assets": {
            "app_icon": "{\"url\":\"...\",\"file\":\"...\"}"
        }

    Decode JSON strings recursively.
    """

    if depth > 8:
        return value

    if isinstance(value, dict):
        return {
            str(k): decode_nested(v, depth + 1)
            for k, v in value.items()
        }

    if isinstance(value, list):
        return [
            decode_nested(v, depth + 1)
            for v in value
        ]

    if isinstance(value, str):
        s = value.strip()

        if not s:
            return value

        # Don't parse ordinary strings.
        if not (
            (s.startswith("{") and s.endswith("}"))
            or
            (s.startswith("[") and s.endswith("]"))
            or
            (s.startswith('"') and s.endswith('"'))
        ):
            return value

        try:
            decoded = json.loads(s)
        except Exception:
            return value

        return decode_nested(decoded, depth + 1)

    return value


def as_dict(value: Any) -> dict[str, Any]:
    value = decode_nested(value)

    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    value = decode_nested(value)

    return value if isinstance(value, list) else []


def get_dict(parent: Any, key: str) -> dict[str, Any]:
    if not isinstance(parent, dict):
        return {}

    return as_dict(parent.get(key))


def get_str(
    parent: Any,
    key: str,
    default: str = ""
) -> str:

    if not isinstance(parent, dict):
        return default

    value = decode_nested(parent.get(key))

    if value is None:
        return default

    if isinstance(value, (dict, list)):
        return default

    return str(value)


def get_bool(
    parent: Any,
    key: str,
    default: bool = False
) -> bool:

    if not isinstance(parent, dict):
        return default

    value = decode_nested(parent.get(key))

    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value != 0

    if isinstance(value, str):
        return value.strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
            "enabled",
        }

    return default


def get_int(
    parent: Any,
    key: str,
    default: int
) -> int:

    if not isinstance(parent, dict):
        return default

    value = decode_nested(parent.get(key))

    try:
        return int(value)
    except Exception:
        return default


# ============================================================
# Configuration loading
# ============================================================

def load_extras(raw: str) -> dict[str, Any]:

    if not raw:
        return {}

    try:
        value = json.loads(raw)
    except Exception as exc:
        fail(f"Invalid --extras JSON: {exc}")

    value = decode_nested(value)

    if not isinstance(value, dict):
        fail("--extras must be a JSON object.")

    return value


def normalize_config(
    extras: dict[str, Any],
    args: argparse.Namespace
) -> dict[str, Any]:

    cfg = decode_nested(extras)

    if not isinstance(cfg, dict):
        cfg = {}

    # --------------------------------------------------------
    # Explicit Workflow values always win.
    # --------------------------------------------------------

    if args.server:
        cfg["server"] = args.server

    if args.key:
        cfg["key"] = args.key

    if args.api:
        cfg["apiServer"] = args.api

    if args.appname:
        cfg["appname"] = args.appname

    if args.filename:
        cfg["filename"] = args.filename

    if args.uuid:
        cfg["uuid"] = args.uuid

    if args.iconlink:
        cfg["iconlink"] = args.iconlink

    if args.logolink:
        cfg["logolink"] = args.logolink

    # --------------------------------------------------------
    # Normalize common nested sections.
    # --------------------------------------------------------

    cfg["appearance"] = as_dict(
        cfg.get("appearance")
    )

    appearance = cfg["appearance"]

    appearance["window"] = as_dict(
        appearance.get("window")
    )

    appearance["colors"] = as_dict(
        appearance.get("colors")
    )

    appearance["main_screen"] = as_dict(
        appearance.get("main_screen")
    )

    appearance["texts"] = as_dict(
        appearance.get("texts")
    )

    appearance["tray"] = as_dict(
        appearance.get("tray")
    )

    appearance["installer"] = as_dict(
        appearance.get("installer")
    )

    appearance["assets"] = as_dict(
        appearance.get("assets")
    )

    # theme is intentionally scalar.
    theme = decode_nested(
        appearance.get("theme", "system")
    )

    if isinstance(theme, dict):
        theme = theme.get("mode", "system")

    theme = str(theme).lower()

    if theme not in {
        "system",
        "light",
        "dark",
    }:
        theme = "system"

    appearance["theme"] = theme

    # --------------------------------------------------------
    # Branding
    # --------------------------------------------------------

    cfg["branding"] = as_dict(
        cfg.get("branding")
    )

    # Laravel can have branding.assets as well.
    cfg["branding"]["assets"] = as_dict(
        cfg["branding"].get("assets")
    )

    return cfg


# ============================================================
# Dart escaping
# ============================================================

def dart_string(value: Any) -> str:

    text = "" if value is None else str(value)

    return (
        text
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )


def dart_bool(value: Any) -> str:
    return "true" if bool(value) else "false"


# ============================================================
# Generated Flutter configuration
# ============================================================

def generate_flutter_config(
    root: Path,
    cfg: dict[str, Any]
) -> Path:

    appearance = as_dict(cfg.get("appearance"))
    window = as_dict(appearance.get("window"))
    colors = as_dict(appearance.get("colors"))
    main = as_dict(appearance.get("main_screen"))
    texts = as_dict(appearance.get("texts"))
    tray = as_dict(appearance.get("tray"))
    installer = as_dict(appearance.get("installer"))

    branding = as_dict(cfg.get("branding"))
    assets = as_dict(appearance.get("assets"))

    appname = (
        get_str(cfg, "appname")
        or
        get_str(branding, "app_name")
        or
        "RustDesk"
    )

    theme = str(
        appearance.get("theme", "system")
    ).lower()

    width = get_int(window, "initial_width", 1000)
    height = get_int(window, "initial_height", 700)
    min_width = get_int(window, "min_width", 800)
    min_height = get_int(window, "min_height", 500)
    max_width = get_int(window, "max_width", 1600)
    max_height = get_int(window, "max_height", 1200)

    server = get_str(cfg, "server")
    key = get_str(cfg, "key")
    api = (
        get_str(cfg, "apiServer")
        or
        get_str(cfg, "api_server")
    )

    dart = f"""// ============================================================
// GENERATED FILE - DO NOT EDIT
// Generated by scripts/apply_config.py
// ============================================================

class GeneratedClientConfig {{

  static const String appName =
      '{dart_string(appname)}';

  static const String server =
      '{dart_string(server)}';

  static const String publicKey =
      '{dart_string(key)}';

  static const String apiServer =
      '{dart_string(api)}';

  static const String uuid =
      '{dart_string(get_str(cfg, "uuid"))}';

  static const String theme =
      '{dart_string(theme)}';

  static const double initialWidth =
      {width}.0;

  static const double initialHeight =
      {height}.0;

  static const double minimumWidth =
      {min_width}.0;

  static const double minimumHeight =
      {min_height}.0;

  static const double maximumWidth =
      {max_width}.0;

  static const double maximumHeight =
      {max_height}.0;

  static const bool center =
      {dart_bool(get_bool(window, "center", True))};

  static const bool resizable =
      {dart_bool(get_bool(window, "resizable", True))};

  static const bool maximized =
      {dart_bool(get_bool(window, "maximized", False))};

  static const bool alwaysOnTop =
      {dart_bool(get_bool(window, "always_on_top", False))};

  static const bool showId =
      {dart_bool(get_bool(main, "show_id", True))};

  static const bool showPassword =
      {dart_bool(get_bool(main, "show_password", True))};

  static const bool showConnect =
      {dart_bool(get_bool(main, "show_connect", True))};

  static const bool showSettings =
      {dart_bool(get_bool(main, "show_settings", True))};

  static const bool showAbout =
      {dart_bool(get_bool(main, "show_about", True))};

  static const bool showRecentSessions =
      {dart_bool(get_bool(main, "show_recent_sessions", True))};

  static const bool showFavorites =
      {dart_bool(get_bool(main, "show_favorites", True))};

  static const bool showAddressBook =
      {dart_bool(get_bool(main, "show_address_book", True))};

  static const bool showConnectionType =
      {dart_bool(get_bool(main, "show_connection_type", True))};

  static const bool showServerStatus =
      {dart_bool(get_bool(main, "show_server_status", True))};

  static const String title =
      '{dart_string(get_str(texts, "title"))}';

  static const String subtitle =
      '{dart_string(get_str(texts, "subtitle"))}';

  static const String welcome =
      '{dart_string(get_str(texts, "welcome"))}';

  static const String connect =
      '{dart_string(get_str(texts, "connect", "Connect"))}';

  static const String ready =
      '{dart_string(get_str(texts, "ready", "Ready"))}';

  static const String connecting =
      '{dart_string(get_str(texts, "connecting", "Connecting..."))}';

  static const String connected =
      '{dart_string(get_str(texts, "connected", "Connected"))}';

  static const String disconnected =
      '{dart_string(get_str(texts, "disconnected", "Disconnected"))}';

  static const String myId =
      '{dart_string(get_str(texts, "my_id", "My ID"))}';

  static const String password =
      '{dart_string(get_str(texts, "password", "Password"))}';

  static const String remoteId =
      '{dart_string(get_str(texts, "remote_id", "Remote ID"))}';

  static const String incoming =
      '{dart_string(get_str(texts, "incoming", "Incoming Connection"))}';

  static const String outgoing =
      '{dart_string(get_str(texts, "outgoing", "Outgoing Connection"))}';

  static const String primaryColor =
      '{dart_string(get_str(colors, "primary"))}';

  static const String secondaryColor =
      '{dart_string(get_str(colors, "secondary"))}';

  static const String accentColor =
      '{dart_string(get_str(colors, "accent"))}';

  static const String backgroundColor =
      '{dart_string(get_str(colors, "background"))}';

  static const String surfaceColor =
      '{dart_string(get_str(colors, "surface"))}';

  static const String headerColor =
      '{dart_string(get_str(colors, "header"))}';

  static const String sidebarColor =
      '{dart_string(get_str(colors, "sidebar"))}';

  static const String textColor =
      '{dart_string(get_str(colors, "text"))}';

  static const String secondaryTextColor =
      '{dart_string(get_str(colors, "secondary_text"))}';

  static const String buttonColor =
      '{dart_string(get_str(colors, "button"))}';

  static const String buttonTextColor =
      '{dart_string(get_str(colors, "button_text"))}';

  static const String successColor =
      '{dart_string(get_str(colors, "success"))}';

  static const String warningColor =
      '{dart_string(get_str(colors, "warning"))}';

  static const String errorColor =
      '{dart_string(get_str(colors, "error"))}';

  static const bool trayShowOpen =
      {dart_bool(get_bool(tray, "show_open", True))};

  static const bool trayShowSettings =
      {dart_bool(get_bool(tray, "show_settings", True))};

  static const bool trayShowAbout =
      {dart_bool(get_bool(tray, "show_about", True))};

  static const bool trayShowRestart =
      {dart_bool(get_bool(tray, "show_restart", True))};

  static const bool trayShowExit =
      {dart_bool(get_bool(tray, "show_exit", True))};

  static const String installerName =
      '{dart_string(get_str(installer, "name", appname))}';

  static const String installerPublisher =
      '{dart_string(get_str(installer, "publisher"))}';

  static const String installerDescription =
      '{dart_string(get_str(installer, "description"))}';

  static const bool desktopShortcut =
      {dart_bool(get_bool(installer, "desktop_shortcut", True))};

  static const bool startMenuShortcut =
      {dart_bool(get_bool(installer, "start_menu_shortcut", True))};

  static const String appIcon =
      '{dart_string(json.dumps(decode_nested(assets.get("app_icon", "")), ensure_ascii=False))}';

  static const String mainLogo =
      '{dart_string(json.dumps(decode_nested(assets.get("main_logo", "")), ensure_ascii=False))}';

  static const String welcomeLogo =
      '{dart_string(json.dumps(decode_nested(assets.get("welcome_logo", "")), ensure_ascii=False))}';

  static const String aboutLogo =
      '{dart_string(json.dumps(decode_nested(assets.get("about_logo", "")), ensure_ascii=False))}';

  static const String trayIcon =
      '{dart_string(json.dumps(decode_nested(assets.get("tray_icon", "")), ensure_ascii=False))}';
}}
"""

    out = (
        root
        / "flutter"
        / "lib"
        / "generated_client_config.dart"
    )

    out.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    out.write_text(
        dart,
        encoding="utf-8"
    )

    info(
        f"Generated Flutter configuration: {out}"
    )

    return out


# ============================================================
# Rust hbb_common configuration
# ============================================================

def find_config_rs(root: Path) -> Path | None:

    candidates = [
        root / "libs" / "hbb_common" / "src" / "config.rs",
        root / "libs" / "hbb_common" / "src" / "config.rs",
    ]

    for p in candidates:
        if p.exists():
            return p

    # Fallback search.
    for p in root.glob("libs/**/config.rs"):
        if "hbb_common" in str(p).lower():
            return p

    return None


def normalize_server(server: str) -> str:

    server = server.strip()

    if not server:
        return ""

    # Strip protocol accidentally supplied by Laravel.
    server = re.sub(
        r"^https?://",
        "",
        server,
        flags=re.IGNORECASE
    )

    server = server.rstrip("/")

    return server


def patch_hbb_config(
    root: Path,
    cfg: dict[str, Any]
) -> None:

    server = normalize_server(
        get_str(cfg, "server")
    )

    key = get_str(
        cfg,
        "key"
    ).strip()

    if not server and not key:
        warn(
            "No server/key supplied; hbb_common patch skipped."
        )
        return

    path = find_config_rs(root)

    if path is None:
        fail(
            "libs/hbb_common/src/config.rs was not found. "
            "RustDesk was probably checked out without submodules."
        )

    text = path.read_text(
        encoding="utf-8"
    )

    original = text

    # --------------------------------------------------------
    # RENDEZVOUS_SERVERS
    # --------------------------------------------------------

    if server:

        # Existing single-line form.
        pattern = (
            r'pub\s+const\s+RENDEZVOUS_SERVERS\s*:\s*&\[\s*&str\s*\]'
            r'\s*=\s*&\[[\s\S]*?\];'
        )

        replacement = (
            'pub const RENDEZVOUS_SERVERS: &[&str] = '
            f'&["{server}"];'
        )

        text, count = re.subn(
            pattern,
            replacement,
            text,
            count=1
        )

        if count == 0:
            fail(
                "Could not patch RENDEZVOUS_SERVERS in config.rs."
            )

        info(
            f"Embedded rendezvous server: {server}"
        )

    # --------------------------------------------------------
    # RS_PUB_KEY
    # --------------------------------------------------------

    if key:

        pattern = (
            r'pub\s+const\s+RS_PUB_KEY\s*:\s*&str\s*=\s*'
            r'"[^"]*"\s*;'
        )

        replacement = (
            f'pub const RS_PUB_KEY: &str = "{key}";'
        )

        text, count = re.subn(
            pattern,
            replacement,
            text,
            count=1
        )

        if count == 0:
            fail(
                "Could not patch RS_PUB_KEY in config.rs."
            )

        info(
            "Embedded RustDesk public key."
        )

    if text == original:
        fail(
            "hbb_common/config.rs was not changed."
        )

    path.write_text(
        text,
        encoding="utf-8"
    )

    # --------------------------------------------------------
    # Verification
    # --------------------------------------------------------

    verify = path.read_text(
        encoding="utf-8"
    )

    if server and f'"{server}"' not in verify:
        fail(
            "Server verification failed after config.rs patch."
        )

    if key and key not in verify:
        fail(
            "Public-key verification failed after config.rs patch."
        )

    info(
        f"Verified Rust server/key patch: {path}"
    )


# ============================================================
# Rust runtime default options
# ============================================================

def patch_runtime_options(
    root: Path,
    cfg: dict[str, Any]
) -> None:

    """
    Besides RENDEZVOUS_SERVERS/RS_PUB_KEY, put the API server and
    custom-rendezvous-server into the built-in RustDesk option map.

    We do this by injecting into Config2::load().

    This is intentionally guarded so it doesn't inject twice.
    """

    server = normalize_server(
        get_str(cfg, "server")
    )

    api = (
        get_str(cfg, "apiServer")
        or
        get_str(cfg, "api_server")
    )

    key = get_str(
        cfg,
        "key"
    )

    if not server and not api and not key:
        return

    path = find_config_rs(root)

    if path is None:
        fail(
            "config.rs not found while patching runtime options."
        )

    text = path.read_text(
        encoding="utf-8"
    )

    marker = (
        "/* CLOUD_BUILDER_DEFAULT_OPTIONS */"
    )

    if marker in text:
        info(
            "Rust runtime options already patched."
        )
        return

    # --------------------------------------------------------
    # Find Config2::load().
    # --------------------------------------------------------

    load_pattern = (
        r'(impl\s+Config2\s*\{\s*'
        r'fn\s+load\(\)\s*->\s*Config2\s*\{\s*)'
    )

    match = re.search(
        load_pattern,
        text,
        flags=re.MULTILINE
    )

    if not match:
        warn(
            "Config2::load() was not found; "
            "API/custom server runtime injection skipped."
        )
        return

    injections = [
        f'        {marker}\n'
    ]

    if server:
        injections.append(
            '        config.options.insert('
            '"custom-rendezvous-server".to_string(), '
            f'"{server}".to_string());\n'
        )

    if key:
        injections.append(
            '        config.options.insert('
            '"key".to_string(), '
            f'"{key}".to_string());\n'
        )

    if api:
        injections.append(
            '        config.options.insert('
            '"api-server".to_string(), '
            f'"{api}".to_string());\n'
        )

    injection = "".join(injections)

    pos = match.end()

    text = (
        text[:pos]
        + injection
        + text[pos:]
    )

    path.write_text(
        text,
        encoding="utf-8"
    )

    info(
        "Rust runtime default options injected."
    )


# ============================================================
# Generated JSON
# ============================================================

def write_json(
    root: Path,
    cfg: dict[str, Any]
) -> None:

    res = root / "res"

    res.mkdir(
        parents=True,
        exist_ok=True
    )

    path = (
        res /
        "cloud-client-config.json"
    )

    path.write_text(
        json.dumps(
            cfg,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    info(
        f"Generated: {path}"
    )


# ============================================================
# Download assets
# ============================================================

def asset_url(meta: Any) -> str:

    meta = decode_nested(meta)

    if isinstance(meta, str):
        if meta.startswith("http://") or meta.startswith("https://"):
            return meta
        return ""

    if isinstance(meta, dict):
        return str(
            meta.get("url")
            or
            meta.get("href")
            or
            ""
        )

    return ""


def download_assets(
    root: Path,
    cfg: dict[str, Any]
) -> dict[str, str]:

    appearance = as_dict(
        cfg.get("appearance")
    )

    assets = as_dict(
        appearance.get("assets")
    )

    branding = as_dict(
        cfg.get("branding")
    )

    branding_assets = as_dict(
        branding.get("assets")
    )

    merged = {}

    merged.update(
        branding_assets
    )

    merged.update(
        assets
    )

    if not merged:
        info(
            "No downloadable branding assets supplied."
        )
        return {}

    out = (
        root
        / "flutter"
        / "assets"
        / "cloud_branding"
    )

    out.mkdir(
        parents=True,
        exist_ok=True
    )

    downloaded: dict[str, str] = {}

    for name, meta in merged.items():

        url = asset_url(meta)

        if not url:
            continue

        parsed = urllib.parse.urlparse(url)

        suffix = (
            Path(parsed.path).suffix
            or
            ".png"
        )

        filename = (
            f"{name}{suffix}"
        )

        destination = (
            out /
            filename
        )

        try:

            info(
                f"Downloading asset {name}: {url}"
            )

            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent":
                        "RustDesk-Custom-Builder/1.0"
                }
            )

            with urllib.request.urlopen(
                request,
                timeout=60
            ) as response:

                data = response.read()

            if not data:
                raise RuntimeError(
                    "Downloaded file is empty."
                )

            destination.write_bytes(
                data
            )

            downloaded[
                name
            ] = str(
                destination.relative_to(root)
            )

            info(
                f"Asset downloaded: {destination}"
            )

        except Exception as exc:

            fail(
                f"Could not download asset "
                f"{name}: {exc}"
            )

    return downloaded


# ============================================================
# Windows icon
# ============================================================

def patch_windows_icon(
    root: Path,
    downloaded: dict[str, str]
) -> bool:

    relative = (
        downloaded.get("app_icon")
    )

    if not relative:
        return False

    source = (
        root /
        relative
    )

    if not source.exists():
        return False

    if source.suffix.lower() != ".ico":
        warn(
            "app_icon is not an .ico file; "
            "Windows resource icon was not replaced."
        )
        return False

    resources = (
        root
        / "flutter"
        / "windows"
        / "runner"
        / "resources"
    )

    resources.mkdir(
        parents=True,
        exist_ok=True
    )

    destination = (
        resources /
        "app_icon.ico"
    )

    shutil.copy2(
        source,
        destination
    )

    runner_rc = (
        root
        / "flutter"
        / "windows"
        / "runner"
        / "Runner.rc"
    )

    if runner_rc.exists():

        text = runner_rc.read_text(
            encoding="utf-8"
        )

        text = text.replace(
            "runner_icon.ico",
            "resources/app_icon.ico"
        )

        runner_rc.write_text(
            text,
            encoding="utf-8"
        )

    info(
        "Windows application icon patched."
    )

    return True


# ============================================================
# Application name
# ============================================================

def patch_application_name(
    root: Path,
    appname: str
) -> int:

    if not appname:
        return 0

    changed = 0

    candidates = [
        root
        / "flutter"
        / "windows"
        / "runner"
        / "Runner.rc",

        root
        / "flutter"
        / "windows"
        / "runner"
        / "CMakeLists.txt",

        root
        / "flutter"
        / "pubspec.yaml",
    ]

    for path in candidates:

        if not path.exists():
            continue

        text = path.read_text(
            encoding="utf-8",
            errors="ignore"
        )

        original = text

        # pubspec name.
        if path.name == "pubspec.yaml":

            text = re.sub(
                r"(?m)^name:\s*.*$",
                f"name: {re.sub(r'[^a-zA-Z0-9_]', '_', appname).lower()}",
                text,
                count=1
            )

        # CMake product name.
        text = re.sub(
            r'(?im)(PRODUCT_NAME\s+)"[^"]*"',
            rf'\1"{appname}"',
            text
        )

        text = re.sub(
            r'(?im)(PRODUCT_DISPLAY_NAME\s+)"[^"]*"',
            rf'\1"{appname}"',
            text
        )

        # RC strings.
        text = re.sub(
            r'(?im)("FileDescription",\s*")RustDesk(")',
            rf'\1{appname}\2',
            text
        )

        text = re.sub(
            r'(?im)("ProductName",\s*")RustDesk(")',
            rf'\1{appname}\2',
            text
        )

        if text != original:

            path.write_text(
                text,
                encoding="utf-8"
            )

            changed += 1

    # We intentionally don't globally replace "RustDesk" in every
    # source file because that can corrupt package names, URLs,
    # namespaces and Rust identifiers.

    info(
        f"Application-name resource patches: {changed}"
    )

    return changed


# ============================================================
# Flutter import
# ============================================================

def ensure_generated_import(
    root: Path
) -> None:

    main = (
        root
        / "flutter"
        / "lib"
        / "main.dart"
    )

    if not main.exists():
        fail(
            f"Flutter main.dart not found: {main}"
        )

    text = main.read_text(
        encoding="utf-8"
    )

    if "generated_client_config.dart" in text:
        return

    imports = list(
        re.finditer(
            r"(?m)^import\s+['\"].*?['\"];\s*$",
            text
        )
    )

    line = (
        "import 'generated_client_config.dart';"
    )

    if imports:

        pos = imports[-1].end()

        text = (
            text[:pos]
            + "\n"
            + line
            + text[pos:]
        )

    else:

        text = line + "\n" + text

    main.write_text(
        text,
        encoding="utf-8"
    )

    info(
        "generated_client_config.dart imported into main.dart."
    )


# ============================================================
# Flutter startup configuration
# ============================================================

def patch_window_manager(
    root: Path,
    cfg: dict[str, Any]
) -> bool:

    appearance = as_dict(
        cfg.get("appearance")
    )

    window = as_dict(
        appearance.get("window")
    )

    if not window:
        return False

    width = get_int(
        window,
        "initial_width",
        1000
    )

    height = get_int(
        window,
        "initial_height",
        700
    )

    min_width = get_int(
        window,
        "min_width",
        800
    )

    min_height = get_int(
        window,
        "min_height",
        500
    )

    max_width = get_int(
        window,
        "max_width",
        1600
    )

    max_height = get_int(
        window,
        "max_height",
        1200
    )

    resizable = get_bool(
        window,
        "resizable",
        True
    )

    maximized = get_bool(
        window,
        "maximized",
        False
    )

    always_on_top = get_bool(
        window,
        "always_on_top",
        False
    )

    files = list(
        (root / "flutter" / "lib").rglob(
            "*.dart"
        )
    )

    changed = False

    for path in files:

        text = path.read_text(
            encoding="utf-8",
            errors="ignore"
        )

        if "WindowOptions(" not in text:
            continue

        original = text

        # Existing WindowOptions size.
        text = re.sub(
            r"minimumSize\s*:\s*const\s*Size\([^)]*\)",
            (
                "minimumSize: const Size("
                f"{min_width}, {min_height})"
            ),
            text
        )

        text = re.sub(
            r"maximumSize\s*:\s*const\s*Size\([^)]*\)",
            (
                "maximumSize: const Size("
                f"{max_width}, {max_height})"
            ),
            text
        )

        text = re.sub(
            r"size\s*:\s*const\s*Size\([^)]*\)",
            (
                "size: const Size("
                f"{width}, {height})"
            ),
            text
        )

        if (
            "minimumSize:" not in text
            or "maximumSize:" not in text
        ):

            text = text.replace(
                "WindowOptions(",
                (
                    "WindowOptions(\n"
                    f"    minimumSize: const Size({min_width}, {min_height}),\n"
                    f"    maximumSize: const Size({max_width}, {max_height}),\n"
                    f"    size: const Size({width}, {height}),\n"
                ),
                1
            )

        if text != original:

            path.write_text(
                text,
                encoding="utf-8"
            )

            changed = True

            info(
                f"Window configuration patched: "
                f"{path.relative_to(root)}"
            )

            break

    return changed


# ============================================================
# Theme patch
# ============================================================

def patch_theme(
    root: Path,
    cfg: dict[str, Any]
) -> bool:

    appearance = as_dict(
        cfg.get("appearance")
    )

    theme = str(
        appearance.get(
            "theme",
            "system"
        )
    ).lower()

    if theme not in {
        "system",
        "light",
        "dark",
    }:
        theme = "system"

    # We don't perform blind source-wide replacements for ThemeMode.
    # Instead, generated_client_config.dart is imported and the build
    # verifies that MaterialApp/theme code exists.
    #
    # This avoids corrupting RustDesk's Theme implementation when
    # upstream changes it.

    files = list(
        (root / "flutter" / "lib").rglob(
            "*.dart"
        )
    )

    material_files = []

    for path in files:

        try:
            text = path.read_text(
                encoding="utf-8",
                errors="ignore"
            )
        except Exception:
            continue

        if (
            "MaterialApp" in text
            or
            "ThemeMode" in text
        ):
            material_files.append(
                path
            )

    if not material_files:

        fail(
            "Could not find Flutter MaterialApp/ThemeMode "
            "implementation. Theme patch cannot be verified."
        )

    info(
        f"Flutter theme implementation found "
        f"({len(material_files)} files); requested theme={theme}"
    )

    return True


# ============================================================
# Verification
# ============================================================

def verify(
    root: Path,
    cfg: dict[str, Any]
) -> None:

    # --------------------------------------------------------
    # Generated Flutter config
    # --------------------------------------------------------

    generated = (
        root
        / "flutter"
        / "lib"
        / "generated_client_config.dart"
    )

    if not generated.exists():
        fail(
            "generated_client_config.dart was not generated."
        )

    text = generated.read_text(
        encoding="utf-8"
    )

    server = get_str(
        cfg,
        "server"
    )

    key = get_str(
        cfg,
        "key"
    )

    if server and server not in text:
        fail(
            "Generated Flutter config does not contain server."
        )

    if key and key not in text:
        fail(
            "Generated Flutter config does not contain key."
        )

    # --------------------------------------------------------
    # Rust config
    # --------------------------------------------------------

    if server or key:

        path = find_config_rs(root)

        if path is None:
            fail(
                "Cannot verify config.rs because it is missing."
            )

        rust = path.read_text(
            encoding="utf-8"
        )

        if server and f'"{normalize_server(server)}"' not in rust:
            fail(
                "Final verification: server is not embedded "
                "in hbb_common/config.rs."
            )

        if key and key not in rust:
            fail(
                "Final verification: public key is not embedded "
                "in hbb_common/config.rs."
            )

    # --------------------------------------------------------
    # main.dart import
    # --------------------------------------------------------

    main = (
        root
        / "flutter"
        / "lib"
        / "main.dart"
    )

    main_text = main.read_text(
        encoding="utf-8"
    )

    if "generated_client_config.dart" not in main_text:
        fail(
            "generated_client_config.dart is not imported by main.dart."
        )

    info(
        "=============================================="
    )

    info(
        "FINAL CONFIGURATION VERIFICATION PASSED"
    )

    info(
        "=============================================="
    )


# ============================================================
# Main
# ============================================================

def main() -> None:

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--rustdesk",
        required=True
    )

    parser.add_argument(
        "--server",
        default=""
    )

    parser.add_argument(
        "--key",
        default=""
    )

    parser.add_argument(
        "--api",
        default=""
    )

    parser.add_argument(
        "--appname",
        default=""
    )

    parser.add_argument(
        "--filename",
        default=""
    )

    parser.add_argument(
        "--uuid",
        default=""
    )

    parser.add_argument(
        "--iconlink",
        default=""
    )

    parser.add_argument(
        "--logolink",
        default=""
    )

    parser.add_argument(
        "--extras",
        default=""
    )

    args = parser.parse_args()

    root = Path(
        args.rustdesk
    ).resolve()

    if not root.exists():
        fail(
            f"RustDesk directory does not exist: {root}"
        )

    info(
        f"RustDesk source: {root}"
    )

    extras = load_extras(
        args.extras
    )

    cfg = normalize_config(
        extras,
        args
    )

    # --------------------------------------------------------
    # app name fallback
    # --------------------------------------------------------

    branding = as_dict(
        cfg.get("branding")
    )

    appname = (
        get_str(cfg, "appname")
        or
        get_str(branding, "app_name")
        or
        "RustDesk"
    )

    cfg["appname"] = appname

    # --------------------------------------------------------
    # Output complete config
    # --------------------------------------------------------

    write_json(
        root,
        cfg
    )

    # --------------------------------------------------------
    # Generate Flutter config
    # --------------------------------------------------------

    generate_flutter_config(
        root,
        cfg
    )

    # --------------------------------------------------------
    # Download assets
    # --------------------------------------------------------

    downloaded = download_assets(
        root,
        cfg
    )

    # --------------------------------------------------------
    # Patch Rust networking
    # --------------------------------------------------------

    patch_hbb_config(
        root,
        cfg
    )

    patch_runtime_options(
        root,
        cfg
    )

    # --------------------------------------------------------
    # Patch Windows / application
    # --------------------------------------------------------

    patch_application_name(
        root,
        appname
    )

    patch_windows_icon(
        root,
        downloaded
    )

    # --------------------------------------------------------
    # Flutter integration
    # --------------------------------------------------------

    ensure_generated_import(
        root
    )

    window_ok = patch_window_manager(
        root,
        cfg
    )

    if not window_ok:

        appearance = as_dict(
            cfg.get("appearance")
        )

        if as_dict(
            appearance.get("window")
        ):
            fail(
                "Window settings were supplied by Laravel, "
                "but no WindowOptions block was found in Flutter."
            )

    patch_theme(
        root,
        cfg
    )

    # --------------------------------------------------------
    # Final verification
    # --------------------------------------------------------

    verify(
        root,
        cfg
    )

    # --------------------------------------------------------
    # Manifest
    # --------------------------------------------------------

    manifest = {
        "appname": appname,
        "server": get_str(cfg, "server"),
        "key_present": bool(
            get_str(cfg, "key")
        ),
        "apiServer": (
            get_str(cfg, "apiServer")
            or
            get_str(cfg, "api_server")
        ),
        "uuid": get_str(cfg, "uuid"),
        "downloaded_assets": downloaded,
    }

    (
        root
        / ".cloud-builder.json"
    ).write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    info(
        "RustDesk custom configuration applied successfully."
    )


if __name__ == "__main__":

    try:
        main()

    except KeyboardInterrupt:
        fail("Interrupted.")

    except SystemExit:
        raise

    except Exception as exc:
        fail(
            f"{type(exc).__name__}: {exc}"
        )
