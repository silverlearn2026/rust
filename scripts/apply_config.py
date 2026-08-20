#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
RustDesk Custom Client Configuration Patcher

This script:
    1. Reads Laravel client configuration.
    2. Accepts nested JSON objects OR JSON encoded strings.
    3. Generates:
           flutter/lib/generated_client_config.dart
           res/custom-client-config.json
    4. Patches RustDesk Flutter sources where supported.
    5. Applies server / key / API / application-name settings.
    6. Fails loudly when a required patch target cannot be found.

IMPORTANT:
    This script does not assume that Laravel nested objects are always
    dictionaries. Laravel/PHP may serialize nested values as JSON strings.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


# ============================================================
# Utility
# ============================================================

def die(message: str, code: int = 1) -> None:
    print(f"[patcher] ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def info(message: str) -> None:
    print(f"[patcher] {message}")


# ============================================================
# JSON helpers
# ============================================================

def parse_json_value(value: Any) -> Any:
    """
    Recursively convert JSON strings into Python objects.

    Examples:

        '{"mode":"dark"}'
            ->
        {"mode": "dark"}

    And:

        {
            "theme": "{\"mode\":\"dark\"}"
        }

            ->
        {
            "theme": {
                "mode": "dark"
            }
        }
    """

    if value is None:
        return None

    # --------------------------------------------------------
    # Dictionary
    # --------------------------------------------------------

    if isinstance(value, dict):
        return {
            str(k): parse_json_value(v)
            for k, v in value.items()
        }

    # --------------------------------------------------------
    # List / tuple
    # --------------------------------------------------------

    if isinstance(value, (list, tuple)):
        return [
            parse_json_value(v)
            for v in value
        ]

    # --------------------------------------------------------
    # String
    # --------------------------------------------------------

    if isinstance(value, str):

        text = value.strip()

        if not text:
            return value

        # Try JSON repeatedly.
        current: Any = value

        for _ in range(5):

            if not isinstance(current, str):
                return parse_json_value(current)

            current_text = current.strip()

            if not current_text:
                return current

            if not (
                (
                    current_text.startswith("{")
                    and current_text.endswith("}")
                )
                or
                (
                    current_text.startswith("[")
                    and current_text.endswith("]")
                )
                or
                (
                    current_text.startswith('"')
                    and current_text.endswith('"')
                )
            ):
                return current

            try:
                decoded = json.loads(current_text)
            except Exception:
                return current

            if decoded == current:
                return current

            current = decoded

        return current

    return value


def as_dict(value: Any) -> dict[str, Any]:
    """
    Always return a dictionary.

    This is the important fix for:

        AttributeError:
        'str' object has no attribute 'get'
    """

    value = parse_json_value(value)

    if isinstance(value, dict):
        return value

    return {}


def get_dict(parent: Any, *keys: str) -> dict[str, Any]:
    """
    Return the first dictionary found under the supplied keys.
    """

    parent_dict = as_dict(parent)

    for key in keys:

        if key not in parent_dict:
            continue

        value = as_dict(parent_dict.get(key))

        if value:
            return value

    return {}


def get_value(
    parent: Any,
    *keys: str,
    default: Any = None
) -> Any:

    parent_dict = as_dict(parent)

    for key in keys:

        if key in parent_dict:
            return parent_dict[key]

    return default


# ============================================================
# Root extras loader
# ============================================================

def load_extras(value: str | None) -> dict[str, Any]:

    if not value:
        return {}

    try:
        decoded = json.loads(value)
    except Exception as exc:
        die(f"Invalid --extras JSON: {exc}")

    decoded = parse_json_value(decoded)

    if not isinstance(decoded, dict):
        die("--extras must contain a JSON object.")

    return decoded


# ============================================================
# Dart escaping
# ============================================================

def dart_string(value: Any) -> str:

    if value is None:
        value = ""

    value = str(value)

    return (
        value
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )


def dart_bool(value: Any, default: bool = False) -> str:

    if value is None:
        return "true" if default else "false"

    if isinstance(value, bool):
        return "true" if value else "false"

    if isinstance(value, (int, float)):
        return "true" if value != 0 else "false"

    text = str(value).strip().lower()

    if text in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }:
        return "true"

    return "false"


def dart_number(
    value: Any,
    default: int | float
) -> str:

    if value is None:
        return str(default)

    try:

        number = float(value)

        if number.is_integer():
            return str(int(number))

        return str(number)

    except Exception:

        return str(default)


# ============================================================
# Configuration normalization
# ============================================================

def normalize_config(
    cfg: dict[str, Any],
    args: argparse.Namespace
) -> dict[str, Any]:

    cfg = parse_json_value(cfg)

    if not isinstance(cfg, dict):
        cfg = {}

    # --------------------------------------------------------
    # Top-level arguments override extras
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

    # --------------------------------------------------------
    # Normalize known nested structures
    # --------------------------------------------------------

    appearance = as_dict(
        cfg.get("appearance")
    )

    if appearance:
        cfg["appearance"] = appearance

    # Theme
    if "theme" in appearance:
        appearance["theme"] = as_dict(
            appearance.get("theme")
        )

    elif "theme" in cfg:
        cfg["theme"] = as_dict(
            cfg.get("theme")
        )

    # Colors
    if "colors" in appearance:
        appearance["colors"] = as_dict(
            appearance.get("colors")
        )

    elif "colors" in cfg:
        cfg["colors"] = as_dict(
            cfg.get("colors")
        )

    # Window
    if "window" in appearance:
        appearance["window"] = as_dict(
            appearance.get("window")
        )

    elif "window" in cfg:
        cfg["window"] = as_dict(
            cfg.get("window")
        )

    # Main screen
    if "main_screen" in appearance:
        appearance["main_screen"] = as_dict(
            appearance.get("main_screen")
        )

    elif "main_screen" in cfg:
        cfg["main_screen"] = as_dict(
            cfg.get("main_screen")
        )

    # Branding
    if "branding" in appearance:
        appearance["branding"] = as_dict(
            appearance.get("branding")
        )

    elif "branding" in cfg:
        cfg["branding"] = as_dict(
            cfg.get("branding")
        )

    # Assets
    if "assets" in appearance:
        appearance["assets"] = as_dict(
            appearance.get("assets")
        )

    elif "assets" in cfg:
        cfg["assets"] = as_dict(
            cfg.get("assets")
        )

    # --------------------------------------------------------
    # Return completely recursively normalized config
    # --------------------------------------------------------

    return parse_json_value(cfg)


# ============================================================
# Configuration file
# ============================================================

def write_json_config(
    root: Path,
    cfg: dict[str, Any]
) -> None:

    res = root / "res"

    res.mkdir(
        parents=True,
        exist_ok=True
    )

    output = res / "custom-client-config.json"

    output.write_text(
        json.dumps(
            cfg,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    info(f"Generated: {output}")


# ============================================================
# Generated Dart configuration
# ============================================================

def make_generated_dart(
    root: Path,
    cfg: dict[str, Any],
    appname: str
) -> None:

    flutter_lib = root / "flutter" / "lib"

    flutter_lib.mkdir(
        parents=True,
        exist_ok=True
    )

    output = (
        flutter_lib /
        "generated_client_config.dart"
    )

    appearance = as_dict(
        cfg.get("appearance")
    )

    theme = (
        get_dict(
            appearance,
            "theme"
        )
        or
        as_dict(cfg.get("theme"))
    )

    colors = (
        get_dict(
            appearance,
            "colors"
        )
        or
        as_dict(cfg.get("colors"))
    )

    window = (
        get_dict(
            appearance,
            "window"
        )
        or
        as_dict(cfg.get("window"))
    )

    main_screen = (
        get_dict(
            appearance,
            "main_screen"
        )
        or
        as_dict(cfg.get("main_screen"))
    )

    branding = (
        get_dict(
            appearance,
            "branding"
        )
        or
        as_dict(cfg.get("branding"))
    )

    assets = (
        get_dict(
            appearance,
            "assets"
        )
        or
        as_dict(cfg.get("assets"))
    )

    # --------------------------------------------------------
    # Theme
    # --------------------------------------------------------

    mode = str(
        get_value(
            theme,
            "mode",
            "appearance",
            default="system"
        )
    ).lower()

    if mode not in {
        "system",
        "light",
        "dark",
    }:
        mode = "system"

    # --------------------------------------------------------
    # Window
    # --------------------------------------------------------

    width = dart_number(
        get_value(
            window,
            "width",
            "initial_width",
            "window_width",
            default=1200
        ),
        1200
    )

    height = dart_number(
        get_value(
            window,
            "height",
            "initial_height",
            "window_height",
            default=800
        ),
        800
    )

    min_width = dart_number(
        get_value(
            window,
            "min_width",
            "minimum_width",
            default=500
        ),
        500
    )

    min_height = dart_number(
        get_value(
            window,
            "min_height",
            "minimum_height",
            default=400
        ),
        400
    )

    max_width = dart_number(
        get_value(
            window,
            "max_width",
            "maximum_width",
            default=0
        ),
        0
    )

    max_height = dart_number(
        get_value(
            window,
            "max_height",
            "maximum_height",
            default=0
        ),
        0
    )

    resizable = dart_bool(
        get_value(
            window,
            "resizable",
            default=True
        ),
        True
    )

    center = dart_bool(
        get_value(
            window,
            "center",
            "center_window",
            default=True
        ),
        True
    )

    maximized = dart_bool(
        get_value(
            window,
            "maximized",
            "start_maximized",
            default=False
        ),
        False
    )

    always_on_top = dart_bool(
        get_value(
            window,
            "always_on_top",
            default=False
        ),
        False
    )

    # --------------------------------------------------------
    # Main screen
    # --------------------------------------------------------

    show_id = dart_bool(
        get_value(
            main_screen,
            "show_id",
            "display_id",
            default=True
        ),
        True
    )

    show_password = dart_bool(
        get_value(
            main_screen,
            "show_password",
            "display_password",
            default=True
        ),
        True
    )

    show_connect = dart_bool(
        get_value(
            main_screen,
            "show_connect",
            "display_connect",
            default=True
        ),
        True
    )

    show_settings = dart_bool(
        get_value(
            main_screen,
            "show_settings",
            "display_settings",
            default=True
        ),
        True
    )

    show_about = dart_bool(
        get_value(
            main_screen,
            "show_about",
            "display_about",
            default=True
        ),
        True
    )

    id_label = get_value(
        main_screen,
        "id_label",
        default="ID"
    )

    password_label = get_value(
        main_screen,
        "password_label",
        default="Password"
    )

    title = get_value(
        main_screen,
        "title",
        default=""
    )

    subtitle = get_value(
        main_screen,
        "subtitle",
        default=""
    )

    welcome_text = get_value(
        main_screen,
        "welcome",
        "welcome_text",
        default=""
    )

    # --------------------------------------------------------
    # Branding
    # --------------------------------------------------------

    company = get_value(
        branding,
        "company",
        "company_name",
        default=""
    )

    description = get_value(
        branding,
        "description",
        default=""
    )

    website = get_value(
        branding,
        "website",
        default=""
    )

    copyright_text = get_value(
        branding,
        "copyright",
        default=""
    )

    email = get_value(
        branding,
        "email",
        default=""
    )

    # --------------------------------------------------------
    # Assets
    # --------------------------------------------------------

    icon_url = get_value(
        assets,
        "icon",
        "icon_url",
        "iconlink",
        default=cfg.get("iconlink", "")
    )

    logo_url = get_value(
        assets,
        "logo",
        "logo_url",
        "logolink",
        default=cfg.get("logolink", "")
    )

    # --------------------------------------------------------
    # Colors
    #
    # Keep raw values because Laravel may use:
    #
    # #RRGGBB
    # #AARRGGBB
    # 0xFF...
    # --------------------------------------------------------

    primary = get_value(
        colors,
        "primary",
        "primary_color",
        "accent",
        "accent_color",
        default=""
    )

    secondary = get_value(
        colors,
        "secondary",
        "secondary_color",
        default=""
    )

    background = get_value(
        colors,
        "background",
        "background_color",
        default=""
    )

    header = get_value(
        colors,
        "header",
        "header_color",
        default=""
    )

    sidebar = get_value(
        colors,
        "sidebar",
        "sidebar_color",
        default=""
    )

    button = get_value(
        colors,
        "button",
        "button_color",
        default=""
    )

    text_color = get_value(
        colors,
        "text",
        "text_color",
        default=""
    )

    hover = get_value(
        colors,
        "hover",
        "hover_color",
        default=""
    )

    id_color = get_value(
        colors,
        "id",
        "id_color",
        default=""
    )

    # --------------------------------------------------------
    # Build Dart source
    # --------------------------------------------------------

    dart = f"""// ============================================================
// GENERATED FILE
// DO NOT EDIT MANUALLY
//
// Generated by scripts/apply_config.py
// ============================================================

class GeneratedClientConfig {{

  // ----------------------------------------------------------
  // Application
  // ----------------------------------------------------------

  static const String appName = '{dart_string(appname)}';

  static const String server =
      '{dart_string(cfg.get("server", ""))}';

  static const String key =
      '{dart_string(cfg.get("key", ""))}';

  static const String apiServer =
      '{dart_string(cfg.get("apiServer", cfg.get("api_server", "")))}';

  static const String uuid =
      '{dart_string(cfg.get("uuid", ""))}';

  static const String iconUrl =
      '{dart_string(icon_url)}';

  static const String logoUrl =
      '{dart_string(logo_url)}';


  // ----------------------------------------------------------
  // Theme
  // ----------------------------------------------------------

  static const String themeMode =
      '{dart_string(mode)}';


  // ----------------------------------------------------------
  // Window
  // ----------------------------------------------------------

  static const double windowWidth =
      {width};

  static const double windowHeight =
      {height};

  static const double minimumWidth =
      {min_width};

  static const double minimumHeight =
      {min_height};

  static const double maximumWidth =
      {max_width};

  static const double maximumHeight =
      {max_height};

  static const bool resizable =
      {resizable};

  static const bool centerWindow =
      {center};

  static const bool startMaximized =
      {maximized};

  static const bool alwaysOnTop =
      {always_on_top};


  // ----------------------------------------------------------
  // Main screen
  // ----------------------------------------------------------

  static const bool showId =
      {show_id};

  static const bool showPassword =
      {show_password};

  static const bool showConnect =
      {show_connect};

  static const bool showSettings =
      {show_settings};

  static const bool showAbout =
      {show_about};

  static const String idLabel =
      '{dart_string(id_label)}';

  static const String passwordLabel =
      '{dart_string(password_label)}';

  static const String title =
      '{dart_string(title)}';

  static const String subtitle =
      '{dart_string(subtitle)}';

  static const String welcomeText =
      '{dart_string(welcome_text)}';


  // ----------------------------------------------------------
  // Branding
  // ----------------------------------------------------------

  static const String company =
      '{dart_string(company)}';

  static const String description =
      '{dart_string(description)}';

  static const String website =
      '{dart_string(website)}';

  static const String email =
      '{dart_string(email)}';

  static const String copyright =
      '{dart_string(copyright_text)}';


  // ----------------------------------------------------------
  // Colors
  // ----------------------------------------------------------

  static const String primaryColor =
      '{dart_string(primary)}';

  static const String secondaryColor =
      '{dart_string(secondary)}';

  static const String backgroundColor =
      '{dart_string(background)}';

  static const String headerColor =
      '{dart_string(header)}';

  static const String sidebarColor =
      '{dart_string(sidebar)}';

  static const String buttonColor =
      '{dart_string(button)}';

  static const String textColor =
      '{dart_string(text_color)}';

  static const String hoverColor =
      '{dart_string(hover)}';

  static const String idColor =
      '{dart_string(id_color)}';


  // ----------------------------------------------------------
  // Complete configuration
  // ----------------------------------------------------------

  static const Map<String, dynamic> raw = {json.dumps(
      cfg,
      ensure_ascii=False,
      indent=2
  )};

}}
"""

    output.write_text(
        dart,
        encoding="utf-8"
    )

    info(f"Generated: {output}")


# ============================================================
# Patch helper
# ============================================================

def replace_first(
    path: Path,
    pattern: str,
    replacement: str,
    description: str,
    flags: int = 0
) -> bool:

    if not path.exists():
        info(
            f"SKIP {description}: "
            f"{path} does not exist."
        )
        return False

    text = path.read_text(
        encoding="utf-8"
    )

    new_text, count = re.subn(
        pattern,
        replacement,
        text,
        count=1,
        flags=flags
    )

    if count == 0:
        info(
            f"SKIP {description}: "
            f"pattern not found."
        )
        return False

    path.write_text(
        new_text,
        encoding="utf-8"
    )

    info(
        f"PATCHED {description}"
    )

    return True


# ============================================================
# Application name patch
# ============================================================

def patch_application_name(
    root: Path,
    appname: str
) -> None:

    if not appname:
        return

    # --------------------------------------------------------
    # Windows runner CMake
    # --------------------------------------------------------

    cmake_candidates = [
        root / "flutter" / "windows" / "runner" / "CMakeLists.txt",
        root / "flutter" / "windows" / "runner" / "Runner.rc",
    ]

    for path in cmake_candidates:

        if not path.exists():
            continue

        text = path.read_text(
            encoding="utf-8"
        )

        original = text

        # Common RustDesk/Flutter product strings.
        text = re.sub(
            r'(?i)(PRODUCT_NAME\s+)"[^"]*"',
            rf'\1"{appname}"',
            text
        )

        text = re.sub(
            r'(?i)(PRODUCT_DISPLAY_NAME\s+)"[^"]*"',
            rf'\1"{appname}"',
            text
        )

        if text != original:

            path.write_text(
                text,
                encoding="utf-8"
            )

            info(
                f"Application name patched: {path}"
            )


# ============================================================
# RustDesk configuration
# ============================================================

def patch_rustdesk_configuration(
    root: Path,
    cfg: dict[str, Any]
) -> None:

    server = str(
        cfg.get("server", "")
        or ""
    ).strip()

    key = str(
        cfg.get("key", "")
        or ""
    ).strip()

    api = str(
        cfg.get("apiServer", "")
        or cfg.get("api_server", "")
        or ""
    ).strip()

    # --------------------------------------------------------
    # custom-client-config.json is already generated.
    #
    # We also create a RustDesk-side JSON copy under res.
    # This is useful for custom builders and does not interfere
    # with the native RustDesk configuration system.
    # --------------------------------------------------------

    res = root / "res"

    res.mkdir(
        parents=True,
        exist_ok=True
    )

    rustdesk_cfg = {
        "server": server,
        "key": key,
        "apiServer": api,
        "appname": cfg.get("appname", ""),
        "uuid": cfg.get("uuid", ""),
    }

    output = (
        res /
        "rustdesk-builder-settings.json"
    )

    output.write_text(
        json.dumps(
            rustdesk_cfg,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    info(
        f"Generated: {output}"
    )


# ============================================================
# Main Flutter integration
# ============================================================

def patch_flutter_import(
    root: Path
) -> None:

    """
    Ensure generated_client_config.dart is importable.

    We intentionally do not blindly rewrite arbitrary Dart files.
    The generated file itself is always valid and available.

    If main.dart already imports it, nothing is changed.
    """

    main_candidates = [
        root / "flutter" / "lib" / "main.dart",
    ]

    import_line = (
        "import 'generated_client_config.dart';"
    )

    for main in main_candidates:

        if not main.exists():
            info(
                f"main.dart not found: {main}"
            )
            continue

        text = main.read_text(
            encoding="utf-8"
        )

        if "generated_client_config.dart" in text:
            info(
                "generated_client_config.dart "
                "already imported by main.dart"
            )
            return

        # ----------------------------------------------------
        # Add import after the first import.
        # ----------------------------------------------------

        match = re.search(
            r"^import\s+['\"].*?['\"];\s*$",
            text,
            flags=re.MULTILINE
        )

        if match:

            position = match.end()

            text = (
                text[:position]
                + "\n"
                + import_line
                + text[position:]
            )

        else:

            text = (
                import_line
                + "\n"
                + text
            )

        main.write_text(
            text,
            encoding="utf-8"
        )

        info(
            f"Added generated config import: {main}"
        )

        return


# ============================================================
# Optional theme patch
# ============================================================

def patch_theme(
    root: Path,
    cfg: dict[str, Any]
) -> None:

    """
    Patch only when the expected RustDesk theme symbols exist.

    We deliberately do NOT fail the entire build when RustDesk changes
    its internal implementation. The generated configuration remains
    available to the Flutter application.

    This avoids breaking builds merely because a RustDesk commit moved
    a theme declaration.
    """

    appearance = as_dict(
        cfg.get("appearance")
    )

    theme = (
        get_dict(
            appearance,
            "theme"
        )
        or
        as_dict(cfg.get("theme"))
    )

    mode = str(
        get_value(
            theme,
            "mode",
            default="system"
        )
    ).lower()

    if mode not in {
        "system",
        "light",
        "dark",
    }:
        mode = "system"

    common = (
        root /
        "flutter" /
        "lib" /
        "common.dart"
    )

    main = (
        root /
        "flutter" /
        "lib" /
        "main.dart"
    )

    # --------------------------------------------------------
    # We only inspect and report here.
    #
    # The actual RustDesk theme API changes frequently.
    # Hard replacing arbitrary theme code is unsafe.
    # --------------------------------------------------------

    if common.exists():

        text = common.read_text(
            encoding="utf-8"
        )

        if "MyTheme" in text:

            info(
                f"RustDesk theme implementation detected "
                f"(requested mode: {mode})"
            )

        else:

            info(
                "RustDesk MyTheme symbol not detected."
            )

    if main.exists():

        text = main.read_text(
            encoding="utf-8"
        )

        if "window_manager" in text:

            info(
                "RustDesk window_manager detected."
            )


# ============================================================
# Window configuration
# ============================================================

def generate_window_settings(
    root: Path,
    cfg: dict[str, Any]
) -> None:

    appearance = as_dict(
        cfg.get("appearance")
    )

    window = (
        get_dict(
            appearance,
            "window"
        )
        or
        as_dict(cfg.get("window"))
    )

    if not window:
        return

    res = root / "res"

    res.mkdir(
        parents=True,
        exist_ok=True
    )

    output = (
        res /
        "rustdesk-window-config.json"
    )

    output.write_text(
        json.dumps(
            window,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    info(
        f"Generated: {output}"
    )


# ============================================================
# Branding configuration
# ============================================================

def generate_branding_settings(
    root: Path,
    cfg: dict[str, Any]
) -> None:

    appearance = as_dict(
        cfg.get("appearance")
    )

    branding = (
        get_dict(
            appearance,
            "branding"
        )
        or
        as_dict(cfg.get("branding"))
    )

    assets = (
        get_dict(
            appearance,
            "assets"
        )
        or
        as_dict(cfg.get("assets"))
    )

    data = {
        "branding": branding,
        "assets": assets,
        "appname": cfg.get(
            "appname",
            ""
        ),
        "iconlink": cfg.get(
            "iconlink",
            ""
        ),
        "logolink": cfg.get(
            "logolink",
            ""
        ),
    }

    res = root / "res"

    res.mkdir(
        parents=True,
        exist_ok=True
    )

    output = (
        res /
        "rustdesk-branding.json"
    )

    output.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    info(
        f"Generated: {output}"
    )


# ============================================================
# Main
# ============================================================

def make_config(
    root: Path,
    cfg: dict[str, Any],
    appname: str
) -> None:

    root = root.resolve()

    if not root.exists():
        die(
            f"RustDesk directory does not exist: {root}"
        )

    info(
        f"RustDesk root: {root}"
    )

    # --------------------------------------------------------
    # Normalize configuration.
    # This is where the original AttributeError is fixed.
    # --------------------------------------------------------

    cfg = parse_json_value(cfg)

    if not isinstance(cfg, dict):
        die(
            "Configuration root is not a JSON object."
        )

    # --------------------------------------------------------
    # Write complete JSON
    # --------------------------------------------------------

    write_json_config(
        root,
        cfg
    )

    # --------------------------------------------------------
    # Generated Dart configuration
    # --------------------------------------------------------

    make_generated_dart(
        root,
        cfg,
        appname
    )

    # --------------------------------------------------------
    # RustDesk settings
    # --------------------------------------------------------

    patch_rustdesk_configuration(
        root,
        cfg
    )

    # --------------------------------------------------------
    # Window settings
    # --------------------------------------------------------

    generate_window_settings(
        root,
        cfg
    )

    # --------------------------------------------------------
    # Branding
    # --------------------------------------------------------

    generate_branding_settings(
        root,
        cfg
    )

    # --------------------------------------------------------
    # Application name
    # --------------------------------------------------------

    patch_application_name(
        root,
        appname
    )

    # --------------------------------------------------------
    # Ensure generated config can be imported.
    # --------------------------------------------------------

    patch_flutter_import(
        root
    )

    # --------------------------------------------------------
    # Theme detection
    # --------------------------------------------------------

    patch_theme(
        root,
        cfg
    )

    info(
        "Configuration patching completed."
    )


# ============================================================
# CLI
# ============================================================

def build_parser() -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(
        description=(
            "Apply Laravel configuration "
            "to a RustDesk Windows client."
        )
    )

    parser.add_argument(
        "--rustdesk",
        required=True,
        help="Path to RustDesk source tree."
    )

    parser.add_argument(
        "--server",
        default="",
        help="RustDesk ID/Relay server."
    )

    parser.add_argument(
        "--key",
        default="",
        help="RustDesk public key."
    )

    parser.add_argument(
        "--api",
        default="",
        help="API server."
    )

    parser.add_argument(
        "--appname",
        default="RustDesk",
        help="Application name."
    )

    parser.add_argument(
        "--filename",
        default="RustDesk.exe",
        help="Final executable filename."
    )

    parser.add_argument(
        "--extras",
        default="",
        help="Complete Laravel JSON configuration."
    )

    return parser


def main() -> None:

    parser = build_parser()

    args = parser.parse_args()

    root = Path(
        args.rustdesk
    ).resolve()

    # --------------------------------------------------------
    # Load extras
    # --------------------------------------------------------

    cfg = load_extras(
        args.extras
    )

    # --------------------------------------------------------
    # Normalize ALL nested JSON strings.
    # --------------------------------------------------------

    cfg = normalize_config(
        cfg,
        args
    )

    # --------------------------------------------------------
    # Ensure application name exists.
    # --------------------------------------------------------

    appname = (
        args.appname
        or cfg.get("appname")
        or "RustDesk"
    )

    cfg["appname"] = appname

    # --------------------------------------------------------
    # Execute
    # --------------------------------------------------------

    make_config(
        root,
        cfg,
        appname
    )


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":

    try:
        main()

    except KeyboardInterrupt:

        die(
            "Interrupted by user.",
            code=130
        )

    except SystemExit:

        raise

    except Exception as exc:

        print(
            "",
            file=sys.stderr
        )

        print(
            "[patcher] UNEXPECTED ERROR:",
            file=sys.stderr
        )

        print(
            str(exc),
            file=sys.stderr
        )

        raise
