"""Open a local web page in the web browser, never in Word.

On Windows, opening map.html by its file type uses whatever program owns .html files,
which on some PCs is Microsoft Word. Uranus instead asks Windows which program is the
default *web browser* (the one that opens http links) and opens the page with that.
"""

import os
import pathlib
import shlex
import subprocess
import webbrowser


def _windows_browser_command():
    import winreg
    key = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
        progid = winreg.QueryValueEx(k, "ProgId")[0]
    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid + r"\shell\open\command") as k:
        return winreg.QueryValueEx(k, "")[0]


def open_html(path):
    url = pathlib.Path(os.path.abspath(path)).as_uri()
    if os.name == "nt":
        try:
            cmd = _windows_browser_command()
            exe = shlex.split(cmd, posix=False)[0].strip('"')
            if "winword" not in exe.lower() and os.path.isfile(exe):
                subprocess.Popen([exe, url])
                return
        except Exception:                        # noqa: BLE001
            pass
        try:
            os.startfile("microsoft-edge:" + url)    # noqa: S606 - Edge is on every Windows 10/11 PC
            return
        except Exception:                        # noqa: BLE001
            pass
    webbrowser.open(url)
