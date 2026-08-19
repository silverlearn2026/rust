
#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re, shutil, sys, urllib.request
from pathlib import Path
from typing import Any

def die(msg: str):
    raise RuntimeError(msg)

def load_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    obj = json.loads(value)
    if not isinstance(obj, dict):
        die("--extras must be a JSON object")
    return obj

def hex_rgb(v: Any, default: str) -> str:
    if not isinstance(v, str):
        return default
    s = v.strip().lstrip("#").upper()
    if re.fullmatch(r"[0-9A-F]{8}", s):
        s = s[2:]
    return s if re.fullmatch(r"[0-9A-F]{6}", s) else default

def dartq(s: Any) -> str:
    return json.dumps("" if s is None else str(s), ensure_ascii=False)

def num(o, k, d):
    v = o.get(k)
    return float(v) if isinstance(v, (int, float)) else d

def boolean(o, k, d):
    v = o.get(k)
    return v if isinstance(v, bool) else d

def patch_once(text, pattern, repl, label):
    new, n = re.subn(pattern, repl, text, count=1, flags=re.MULTILINE)
    if n != 1:
        die(f"Could not patch {label}; RustDesk source shape changed.")
    return new

def download(url: str, dest: Path):
    if not url:
        return
    req = urllib.request.Request(url, headers={"User-Agent": "RustDesk-Client-Builder"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    print(f"[patcher] downloaded {dest} ({len(data)} bytes)")

def make_config(rustdesk: Path, cfg: dict, appname: str):
    appearance = cfg.get("appearance") or {}
    colors = appearance.get("colors") or cfg.get("colors") or {}
    theme = appearance.get("theme") or cfg.get("theme") or {}
    window = appearance.get("window") or cfg.get("window") or {}
    screen = appearance.get("main_screen") or cfg.get("main_screen") or {}
    branding = appearance.get("branding") or cfg.get("branding") or {}

    mode = str(theme.get("mode", "system")).lower()
    if mode not in {"light", "dark", "system"}:
        mode = "system"

    def f(k, d): return num(window, k, d)
    def b(k, d): return str(boolean(window, k, d)).lower()

    dart = f"""// GENERATED FILE - DO NOT EDIT.
import 'dart:ui';

class ClientWindowConfig {{
  const ClientWindowConfig();
  double get width => {f('initial_width', 1080)};
  double get height => {f('initial_height', 720)};
  double get minWidth => {f('min_width', 0)};
  double get minHeight => {f('min_height', 0)};
  double get maxWidth => {f('max_width', 0)};
  double get maxHeight => {f('max_height', 0)};
  bool get center => {b('center', True)};
  bool get resizable => {b('resizable', True)};
  bool get maximized => {b('maximized', False)};
  bool get alwaysOnTop => {b('always_on_top', False)};
}}

class ClientConfig {{
  static const window = ClientWindowConfig();
  static const String appName = {dartq(appname)};
  static const String themeMode = {dartq(mode)};
  static const String company = {dartq(branding.get('company', ''))};
  static const String publisher = {dartq(branding.get('publisher', ''))};
  static const String website = {dartq(branding.get('website', ''))};
  static const String email = {dartq(branding.get('email', ''))};
  static const String copyright = {dartq(branding.get('copyright', ''))};
  static const String description = {dartq(branding.get('description', ''))};
  static const bool showId = {str(boolean(screen, 'show_id', True)).lower()};
  static const bool showPassword = {str(boolean(screen, 'show_password', True)).lower()};
  static const String idLabel = {dartq(screen.get('id_label', 'ID'))};
  static const String passwordLabel = {dartq(screen.get('password_label', 'One-time Password'))};
}}
"""
    (rustdesk/"flutter/lib/generated_client_config.dart").write_text(dart, encoding="utf-8")

def patch_common(rustdesk: Path, cfg: dict):
    p = rustdesk/"flutter/lib/common.dart"
    if not p.exists(): die(f"Missing {p}")
    t = p.read_text(encoding="utf-8")
    if "generated_client_config.dart" not in t:
        t = t.replace("import '../consts.dart';",
                      "import '../consts.dart';\nimport 'generated_client_config.dart';", 1)

    appearance = cfg.get("appearance") or {}
    colors = appearance.get("colors") or cfg.get("colors") or {}
    accent = "0xFF" + hex_rgb(colors.get("accent") or colors.get("primary"), "0071FF")
    gray = "0xFF" + hex_rgb(colors.get("background") or colors.get("surface"), "EFEFF2")
    border = "0xFF" + hex_rgb(colors.get("border"), "CCCCCC")
    idc = "0xFF" + hex_rgb(colors.get("id"), "00B6F0")
    button = "0xFF" + hex_rgb(colors.get("button") or colors.get("primary"), "2C8CFF")
    hover = "0xFF" + hex_rgb(colors.get("hover"), "999999")
    lightbg = "0xFF" + hex_rgb(colors.get("light_background"), "FFFFFF")
    darkbg = "0xFF" + hex_rgb(colors.get("dark_background"), "18191E")
    darksurface = "0xFF" + hex_rgb(colors.get("dark_surface"), "24252B")

    pairs = [
        (r"static const Color grayBg = Color\(0x[0-9A-Fa-f]+\);", f"static const Color grayBg = Color({gray});", "grayBg"),
        (r"static const Color accent = Color\(0x[0-9A-Fa-f]+\);", f"static const Color accent = Color({accent});", "accent"),
        (r"static const Color border = Color\(0x[0-9A-Fa-f]+\);", f"static const Color border = Color({border});", "border"),
        (r"static const Color idColor = Color\(0x[0-9A-Fa-f]+\);", f"static const Color idColor = Color({idc});", "idColor"),
        (r"static const Color button = Color\(0x[0-9A-Fa-f]+\);", f"static const Color button = Color({button});", "button"),
        (r"static const Color hoverBorder = Color\(0x[0-9A-Fa-f]+\);", f"static const Color hoverBorder = Color({hover});", "hoverBorder"),
        (r"scaffoldBackgroundColor: Colors\.white,", f"scaffoldBackgroundColor: Color({lightbg}),", "light background"),
        (r"dialogBackgroundColor: Colors\.white,", f"dialogBackgroundColor: Color({lightbg}),", "light dialog"),
        (r"scaffoldBackgroundColor: Color\(0x[0-9A-Fa-f]+\),", f"scaffoldBackgroundColor: Color({darkbg}),", "dark background"),
        (r"dialogBackgroundColor: Color\(0x[0-9A-Fa-f]+\),", f"dialogBackgroundColor: Color({darkbg}),", "dark dialog"),
        (r"cardColor: grayBg,", f"cardColor: Color({gray}),", "light card"),
        (r"primary: Colors\.blue, secondary: accent, background: grayBg",
         f"primary: Color({accent}), secondary: Color({accent}), background: Color({gray})", "light color scheme"),
        (r"primary: Colors\.blue,\s*secondary: accent,\s*background: Color\(0x[0-9A-Fa-f]+\),",
         f"primary: Color({accent}), secondary: Color({accent}), background: Color({darksurface}),", "dark color scheme"),
        (r"cardColor: Color\(0x[0-9A-Fa-f]+\),", f"cardColor: Color({darksurface}),", "dark card"),
    ]
    for a,b,c in pairs:
        t = patch_once(t, a, b, c)

    mode = str((appearance.get("theme") or cfg.get("theme") or {}).get("mode", "system")).lower()
    if mode not in {"light","dark","system"}: mode = "system"
    pattern = r"static ThemeMode currentThemeMode\(\) \{.*?\n\s*\}"
    repl = f"""static ThemeMode currentThemeMode() {{
    const configured = ThemeMode.{mode};
    if (configured != ThemeMode.system) return configured;
    final preference = getThemeModePreference();
    if (preference == ThemeMode.system) {{
      return WidgetsBinding.instance.platformDispatcher.platformBrightness == Brightness.light
          ? ThemeMode.light
          : ThemeMode.dark;
    }}
    return preference;
  }}"""
    t = patch_once(t, pattern, repl, "theme mode")
    p.write_text(t, encoding="utf-8")

def patch_main(rustdesk: Path):
    p = rustdesk/"flutter/lib/main.dart"
    if not p.exists(): die(f"Missing {p}")
    t = p.read_text(encoding="utf-8")
    if "generated_client_config.dart" not in t:
        t = t.replace("import 'consts.dart';",
                      "import 'consts.dart';\nimport 'generated_client_config.dart';", 1)

    if "applyGeneratedClientWindowConfig();" not in t:
        t = patch_once(t, r"runApp\(App\(\)\);\n",
                       "runApp(App());\n  await applyGeneratedClientWindowConfig();\n",
                       "window configuration hook")

    if "Future<void> applyGeneratedClientWindowConfig()" not in t:
        anchor = "void runMobileApp() async {"
        fn = """Future<void> applyGeneratedClientWindowConfig() async {
  if (!isDesktop || desktopType != DesktopType.main) return;
  final c = ClientConfig.window;
  if (c.width > 0 && c.height > 0) {
    await windowManager.setSize(Size(c.width, c.height));
  }
  if (c.minWidth > 0 && c.minHeight > 0) {
    await windowManager.setMinimumSize(Size(c.minWidth, c.minHeight));
  }
  if (c.maxWidth > 0 && c.maxHeight > 0) {
    await windowManager.setMaximumSize(Size(c.maxWidth, c.maxHeight));
  }
  await windowManager.setResizable(c.resizable);
  if (c.center) await windowManager.center();
  if (c.maximized) await windowManager.maximize();
  if (c.alwaysOnTop) await windowManager.setAlwaysOnTop(true);
}

"""
        if anchor not in t: die("main.dart runMobileApp anchor not found")
        t = t.replace(anchor, fn+anchor, 1)
    p.write_text(t, encoding="utf-8")

def patch_home(rustdesk: Path):
    p = rustdesk/"flutter/lib/desktop/pages/desktop_home_page.dart"
    if not p.exists(): return
    t = p.read_text(encoding="utf-8")
    if "generated_client_config.dart" not in t:
        m = re.search(r"^import .*$", t, flags=re.MULTILINE)
        if m:
            t = t[:m.end()]+"\nimport '../../generated_client_config.dart';"+t[m.end():]
    t = re.sub(r"(Widget\s+buildIDBoard\(BuildContext context\)\s*\{)",
               r"\1\n    if (!ClientConfig.showId) return const SizedBox.shrink();", t, count=1)
    t = re.sub(r"(buildPasswordBoard2\(BuildContext context,\s*ServerModel model\)\s*\{)",
               r"\1\n    if (!ClientConfig.showPassword) return const SizedBox.shrink();", t, count=1)
    p.write_text(t, encoding="utf-8")

def assets(rustdesk: Path, cfg: dict):
    appearance = cfg.get("appearance") or {}
    a = appearance.get("assets") or cfg.get("assets") or {}
    icon = a.get("application_icon") or a.get("icon") or cfg.get("iconlink") or ""
    logo = a.get("main_logo") or a.get("logo") or cfg.get("logolink") or ""
    assetdir = rustdesk/"flutter/assets"
    resdir = rustdesk/"res"
    assetdir.mkdir(parents=True, exist_ok=True)
    resdir.mkdir(parents=True, exist_ok=True)

    if icon:
        ext = Path(urllib.request.urlparse(icon).path).suffix.lower() or ".png"
        d = resdir/("icon"+ext); download(icon,d)
        if d.suffix.lower()==".png": shutil.copy2(d, assetdir/"icon.png")
    if logo:
        ext = Path(urllib.request.urlparse(logo).path).suffix.lower() or ".png"
        d = assetdir/("logo"+ext); download(logo,d)
        if d.suffix.lower()==".png": shutil.copy2(d,assetdir/"logo.png")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--rustdesk",required=True)
    ap.add_argument("--server",default="")
    ap.add_argument("--key",default="")
    ap.add_argument("--api",default="")
    ap.add_argument("--appname",default="")
    ap.add_argument("--filename",default="")
    ap.add_argument("--extras",default="")
    args=ap.parse_args()
    root=Path(args.rustdesk).resolve()
    cfg=load_json(args.extras)
    cfg.setdefault("server",args.server); cfg.setdefault("key",args.key)
    cfg.setdefault("api_server",args.api); cfg.setdefault("appname",args.appname)
    cfg.setdefault("filename",args.filename); cfg.setdefault("appearance",{})
    make_config(root,cfg,args.appname or cfg.get("appname") or "RustDesk")
    patch_common(root,cfg)
    patch_main(root)
    patch_home(root)
    assets(root,cfg)
    (root/"res/custom-client-config.json").write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding="utf-8")
    print("[patcher] complete")

if __name__=="__main__":
    try: main()
    except Exception as e:
        print("[patcher] ERROR:",e,file=sys.stderr)
        raise
