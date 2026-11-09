"""Patch a WIZ runtime's workspace builder so Stock8 builds correctly on Windows.

The stock WIZ builder (season 2.5.x, plugin/workspace/model/builder.py) assumes
POSIX paths in two places. On Windows both fail silently and the build still
"succeeds":

1. ``_search`` joins paths with ``os.path.join`` (backslashes), but later steps
   identify app files with ``split("/")``. Result: main.js contains no apps and
   every page is blank.
2. Tailwind is generated with ``cd ... && node_modules/.bin/tailwindcss``. cmd.exe
   cannot run that POSIX path (the extensionless file is an sh shim), so
   ``tailwind.min.css`` is never written and main.css ships without any
   Tailwind utility classes. Result: broken layout (huge icons, unstyled buttons).

The runtime lives outside this repository, so this script re-applies both fixes.
It is idempotent, keeps a one-time backup (builder.py.stock8-orig), and exits
non-zero if the builder no longer matches the expected code, so a WIZ upgrade
cannot silently drop the fix.

Usage: python scripts/patch-wiz-runtime-windows.py <runtime-root>
"""
import os
import shutil
import sys

BUILDER = os.path.join("plugin", "workspace", "model", "builder.py")

SEARCH_OLD = "                self._search(os.path.join(target_file, f), result=result, extension=extension)\n"
SEARCH_NEW = (
    "                # Stock8 Windows patch: later steps identify files with split(\"/\").\n"
    "                self._search(os.path.join(target_file, f).replace(\"\\\\\", \"/\"), result=result, extension=extension)\n"
)

TAILWIND_OLD = "            Util.execute(f\"cd {build_base_path} && node_modules/.bin/tailwindcss -o tailwind.min.css --minify\", False)\n"
TAILWIND_NEW = (
    "            if os.name == \"nt\":\n"
    "                # Stock8 Windows patch: cmd.exe cannot run \"node_modules/.bin/tailwindcss\" (POSIX path, sh shim).\n"
    "                import subprocess\n"
    "                subprocess.run([os.path.join(build_base_path, \"node_modules\", \".bin\", \"tailwindcss.cmd\"), \"-o\", \"tailwind.min.css\", \"--minify\"], cwd=build_base_path, check=False)\n"
    "            else:\n"
    "                Util.execute(f\"cd {build_base_path} && node_modules/.bin/tailwindcss -o tailwind.min.css --minify\", False)\n"
)

PATCHES = (
    ("path separators", SEARCH_OLD, SEARCH_NEW),
    ("tailwind command", TAILWIND_OLD, TAILWIND_NEW),
)


def patch_source(source):
    """Return (patched_source, applied_names). Raise ValueError if a patch cannot be placed."""
    applied = []
    for name, old, new in PATCHES:
        if new in source:
            continue
        if source.count(old) != 1:
            raise ValueError(f"builder.py no longer matches the expected code for the {name} patch")
        source = source.replace(old, new)
        applied.append(name)
    return source, applied


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[-1])
        return 2
    path = os.path.join(argv[1], BUILDER)
    if not os.path.isfile(path):
        print(f"WIZ builder not found: {path}")
        return 1
    with open(path, encoding="utf-8", newline="") as f:
        source = f.read()
    # Normalise line endings for matching, then write back in the original style.
    crlf = "\r\n" in source
    try:
        patched, applied = patch_source(source.replace("\r\n", "\n"))
    except ValueError as exc:
        print(f"Not patched: {exc}. Check {path} by hand.")
        return 1
    if not applied:
        print("WIZ runtime builder already patched for Windows.")
        return 0
    backup = path + ".stock8-orig"
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
    if crlf:
        patched = patched.replace("\n", "\r\n")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(patched)
    print(f"Patched WIZ runtime builder for Windows: {', '.join(applied)} (backup: {backup})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
