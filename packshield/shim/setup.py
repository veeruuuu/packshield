"""
PATH-shim setup/teardown. Per PROJECT.md Sec 4's hard rule: the shim
enforces BLOCK/WARN/ALLOW synchronously, at install time, entirely on
its own -- no dashboard/network dependency for enforcement to work.

SCOPE LIMITATION, stated plainly (see PROJECT.md log): this shim only
intercepts `npm install <pkg>` / `pip install <pkg>` with an EXPLICIT
package name. Bare `npm install` (installs everything from package.json)
and `pip install -r requirements.txt` are NOT covered -- our pipeline
only knows how to resolve one named package's tree, not "everything in
a manifest." These pass through untouched, with a visible warning.

ALSO: `python -m pip install <pkg>` is NOT interceptable by any PATH
shim on `pip` -- that invocation runs python.exe, never touches
anything named `pip`. Inherent limitation of PATH shimming, not fixable
by this design.

TWO MECHANISMS, both installed together:
1. .cmd files in ~/.packshield/shims, added to User PATH. Works in shells
   where User PATH is searched before the real binaries' location.
2. PowerShell profile functions. REQUIRED for reliability on Windows:
   Node.js's installer adds itself to SYSTEM PATH, which Windows searches
   before User PATH regardless of string order -- meaning mechanism 1
   alone silently loses to the real npm on most Windows setups.
   PowerShell resolves profile-defined functions before ever searching
   PATH, sidestepping that problem entirely, with no admin rights needed.
   LIMITATION: only works inside PowerShell -- cmd.exe or a raw
   Start-Process bypassing the profile is not covered by this mechanism.

Also installs a standalone `shieldmax` PowerShell function, so
`shieldmax npm install <pkg>` / `shieldmax pip install <pkg>` works as a
prefix command, in addition to the existing `npm install <pkg>
--shieldmax` suffix-flag form handled inside _shim_intercept.
"""

import json
import shutil
import subprocess
from pathlib import Path

SHIM_DIR = Path.home() / ".packshield" / "shims"
SHIM_CONFIG_PATH = Path.home() / ".packshield" / "shim_config.json"

NPM_SHIM_CONTENT = """@echo off
packshield _shim_intercept npm %*
"""

PIP_SHIM_CONTENT = """@echo off
packshield _shim_intercept pip %*
"""

PROFILE_MARKER_START = "# >>> packshield shim >>>"
PROFILE_MARKER_END = "# <<< packshield shim <<<"

PROFILE_FUNCTIONS_TEMPLATE = """{marker_start}
function npm {{
    packshield _shim_intercept npm @args
}}
function pip {{
    packshield _shim_intercept pip @args
}}
function shieldmax {{
    param(
        [Parameter(Mandatory=$true, Position=0)]
        [ValidateSet("npm", "pip")]
        [string]$pm,
        [Parameter(ValueFromRemainingArguments=$true)]
        [string[]]$rest
    )
    packshield _shim_intercept $pm @rest --shieldmax
}}
{marker_end}
"""


def _find_real_binary(name: str) -> str | None:
    """Find the real binary BEFORE our shim directory is on PATH, so we
    never accidentally record our own shim as the 'real' target."""
    return shutil.which(name)


def _get_profile_path() -> Path:
    return Path(
        subprocess.run(
            ["powershell", "-Command", "$PROFILE"],
            capture_output=True, text=True, check=True
        ).stdout.strip()
    )


def install_shim() -> tuple[bool, str]:
    """Mechanism 1: .cmd files + User PATH. See module docstring for why
    this alone is often not enough on Windows."""
    real_npm = _find_real_binary("npm")
    real_pip = _find_real_binary("pip")

    if not real_npm and not real_pip:
        return False, "Could not find a real npm or pip on PATH -- nothing to shim."

    SHIM_DIR.mkdir(parents=True, exist_ok=True)

    if real_npm:
        (SHIM_DIR / "npm.cmd").write_text(NPM_SHIM_CONTENT, encoding="utf-8")
    if real_pip:
        (SHIM_DIR / "pip.cmd").write_text(PIP_SHIM_CONTENT, encoding="utf-8")

    config = {"real_npm_path": real_npm, "real_pip_path": real_pip}
    SHIM_CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")

    try:
        current_path = subprocess.run(
            ["powershell", "-Command", "[Environment]::GetEnvironmentVariable('Path', 'User')"],
            capture_output=True, text=True, check=True
        ).stdout.strip()
    except subprocess.CalledProcessError as e:
        return False, f"Could not read current User PATH: {e}"

    shim_dir_str = str(SHIM_DIR)
    if shim_dir_str in current_path:
        return True, f"Shim files present at {SHIM_DIR} (already on User PATH)."

    new_path = f"{shim_dir_str};{current_path}"
    try:
        subprocess.run(
            ["powershell", "-Command", f"[Environment]::SetEnvironmentVariable('Path', '{new_path}', 'User')"],
            check=True
        )
    except subprocess.CalledProcessError as e:
        return False, f"Wrote shim files but could not update PATH: {e}"

    return True, f"Shim files written to {SHIM_DIR} and added to User PATH. Real npm: {real_npm}. Real pip: {real_pip}."


def uninstall_shim() -> tuple[bool, str]:
    try:
        current_path = subprocess.run(
            ["powershell", "-Command", "[Environment]::GetEnvironmentVariable('Path', 'User')"],
            capture_output=True, text=True, check=True
        ).stdout.strip()
    except subprocess.CalledProcessError as e:
        return False, f"Could not read current User PATH: {e}"

    shim_dir_str = str(SHIM_DIR)
    parts = [p for p in current_path.split(";") if p and p != shim_dir_str]
    new_path = ";".join(parts)

    try:
        subprocess.run(
            ["powershell", "-Command", f"[Environment]::SetEnvironmentVariable('Path', '{new_path}', 'User')"],
            check=True
        )
    except subprocess.CalledProcessError as e:
        return False, f"Could not update PATH: {e}"

    if SHIM_DIR.exists():
        shutil.rmtree(SHIM_DIR, ignore_errors=True)
    if SHIM_CONFIG_PATH.exists():
        SHIM_CONFIG_PATH.unlink()

    return True, "Shim files removed from PATH and deleted."


def get_real_binary(pm: str) -> str | None:
    if not SHIM_CONFIG_PATH.exists():
        return None
    try:
        config = json.loads(SHIM_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return config.get(f"real_{pm}_path")


def install_profile_functions() -> tuple[bool, str]:
    """Mechanism 2: PowerShell profile functions -- the one that actually
    makes interception reliable on Windows. Also installs the standalone
    `shieldmax` prefix command (see module docstring)."""
    profile_path = _get_profile_path()
    profile_path.parent.mkdir(parents=True, exist_ok=True)

    existing = profile_path.read_text(encoding="utf-8") if profile_path.exists() else ""
    if PROFILE_MARKER_START in existing:
        # Already installed from an earlier version -- replace the block
        # in place so re-running `packshield shim install` after this
        # update actually picks up the new `shieldmax` function too.
        start = existing.index(PROFILE_MARKER_START)
        end = existing.index(PROFILE_MARKER_END) + len(PROFILE_MARKER_END)
        block = PROFILE_FUNCTIONS_TEMPLATE.format(marker_start=PROFILE_MARKER_START, marker_end=PROFILE_MARKER_END)
        new_content = existing[:start] + block.strip() + existing[end:]
        profile_path.write_text(new_content, encoding="utf-8")
        return True, (
            f"Updated PackShield functions (including the new `shieldmax` command) in your PowerShell profile: {profile_path}\n"
            f"IMPORTANT: close and reopen PowerShell (or run '. $PROFILE') for this to take effect."
        )

    block = PROFILE_FUNCTIONS_TEMPLATE.format(marker_start=PROFILE_MARKER_START, marker_end=PROFILE_MARKER_END)
    with open(profile_path, "a", encoding="utf-8") as f:
        f.write("\n" + block)

    return True, (
        f"Added npm/pip override functions and the `shieldmax` command to your PowerShell profile: {profile_path}\n"
        f"IMPORTANT: close and reopen PowerShell (or run '. $PROFILE') for this to take effect.\n"
        f"NOTE: this only intercepts npm/pip inside PowerShell -- cmd.exe and other shells "
        f"are not covered by this mechanism."
    )


def uninstall_profile_functions() -> tuple[bool, str]:
    profile_path = _get_profile_path()
    if not profile_path.exists():
        return True, "No PowerShell profile found -- nothing to remove."

    content = profile_path.read_text(encoding="utf-8")
    if PROFILE_MARKER_START not in content:
        return True, "No PackShield block found in PowerShell profile."

    start = content.index(PROFILE_MARKER_START)
    end = content.index(PROFILE_MARKER_END) + len(PROFILE_MARKER_END)
    new_content = content[:start] + content[end:]
    profile_path.write_text(new_content, encoding="utf-8")

    return True, f"Removed PackShield functions from {profile_path}. Restart PowerShell."