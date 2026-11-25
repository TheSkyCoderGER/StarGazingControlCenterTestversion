#!/usr/bin/env python3
"""
Star Gazing Control Center by TheSkyCoder
Desktop-Steuerung für ZWO Seestar S30 / S30 Pro / S50 / S50 Pro
© 2026 TheSkyCoder. Der Programmname darf nicht verändert werden; veränderte Fassungen
zeigen automatisch den Zusatz „modifiziert“ (siehe LICENSE.md).
WLAN (JSON-RPC, TCP-Port 4700), Bildvorschau (TCP-Port 4800)
und Bluetooth LE (Scan / GATT-Explorer)

Inoffiziell, nicht von ZWO. Protokoll basiert auf Community-Reverse-Engineering
(u. a. smart-underworld/seestar_alp). Nutzung auf eigenes Risiko.

Abhängigkeiten:
  Pflicht:  Python 3.9+ (Tkinter ist bei Windows-Python dabei)
  Optional: cryptography  -> Anmeldung ab Firmware 6.45 / 7.18+ (PEM-Schlüssel)
            numpy, pillow -> Bildvorschau
            bleak         -> Bluetooth LE
"""

import asyncio
import hashlib
import os
import base64
import io
import json
import math
import queue
import re
import socket
import struct
import sys
import threading
import time
import zipfile
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    HAVE_CRYPTO = True
except ImportError:
    HAVE_CRYPTO = False

try:
    from bleak import BleakClient, BleakScanner
    HAVE_BLEAK = True
except ImportError:
    HAVE_BLEAK = False

try:
    import numpy as np
    from PIL import Image, ImageTk
    HAVE_IMAGING = True
except ImportError:
    HAVE_IMAGING = False

# --------------------------------------------------------------------------
# Übersetzung
# Die App ist auf Deutsch geschrieben. Angezeigte Texte werden beim Anzeigen übersetzt – die Programmlogik
# arbeitet weiter mit den deutschen Originalen (Auswahllisten werden dafür zurückübersetzt).
# Sprachdateien: Ordner „lang“ neben dem Programm, eine Datei je Sprache (<code>.txt):
#   erste Zeile  "# name: English"   danach je Zeile  "<Nummer>\t<Übersetzung>"  (\n für Zeilenumbruch)
# Die Nummern beziehen sich auf lang/source.txt (deutsche Originale, gleiche Nummern).
# --------------------------------------------------------------------------
LANG_DIR = Path(__file__).with_name("lang")
LANG_FALLBACK = "en"           # fehlt eine Übersetzung, erst Englisch, dann Deutsch


class I18N:
    def __init__(self):
        self.lang = "de"
        self.names = {"de": "Deutsch"}
        self.source = []
        self.tables = {}           # code -> {deutsch: übersetzung}
        self.exact = {}
        self.templates = []        # (regex, deutsch, übersetzung)
        self.affix = []            # Satzanfänge/-enden, an die das Programm weiteren Text hängt
        self.cache = {}
        self.vars = []             # (original StringVar, Anzeige-StringVar)
        self.load_index()

    # -- Dateien
    @staticmethod
    def _unescape(t):
        return t.replace("\\n", "\n").replace("\\t", "\t")

    def load_index(self):
        try:
            self.source = [self._unescape(l.split("\t", 1)[1]) for l in
                           (LANG_DIR / "source.txt").read_text(encoding="utf-8").splitlines()
                           if "\t" in l and not l.startswith("#")]
        except Exception:
            self.source = []
        for f in sorted(LANG_DIR.glob("*.txt")) if LANG_DIR.exists() else []:
            if f.stem == "source":
                continue
            try:
                first = f.read_text(encoding="utf-8").splitlines()[0]
                self.names[f.stem] = first.split(":", 1)[1].strip() if first.startswith("# name:") else f.stem
            except Exception:
                continue

    def _table(self, code):
        if code in self.tables:
            return self.tables[code]
        tab = {}
        f = LANG_DIR / f"{code}.txt"
        if f.exists() and self.source:
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.startswith("#") or "\t" not in line:
                    continue
                idx, txt = line.split("\t", 1)
                try:
                    i = int(idx)
                except ValueError:
                    continue
                if 0 <= i < len(self.source) and txt.strip():
                    tab[self.source[i]] = self._unescape(txt)
        self.tables[code] = tab
        return tab

    def set_language(self, code):
        if code not in self.names:
            code = "de"
        self.lang = code
        self.cache = {}
        self.exact, self.templates, self.affix = {}, [], []
        if code == "de":
            return
        merged = {}
        if code != LANG_FALLBACK:
            merged.update(self._table(LANG_FALLBACK))
        merged.update(self._table(code))
        for src, dst in list(merged.items()):
            # Leerzeichen/Umbrüche am Rand wie im Original (Editoren schneiden sie gern ab)
            lead, trail = src[:len(src) - len(src.lstrip())], src[len(src.rstrip()):]
            dst = merged[src] = lead + dst.strip() + trail if dst.strip() else dst
        for src, dst in list(merged.items()):                      # auch ohne Leerzeichen/Umbrüche am Rand
            ss, ds = src.strip(), dst.strip()
            if ss and ss != src and ss not in merged:
                merged[ss] = ds

        def compile_tmpl(src, pre="", post=""):
            body = re.sub(r"\\\{(\d+)\\\}", lambda m: f"(?P<g{m.group(1)}>.*?)", re.escape(src))
            return re.compile("^" + pre + body + post + "$", re.S)

        for src, dst in merged.items():
            if re.search(r"\{\d+\}", src):
                try:
                    self.templates.append((compile_tmpl(src), src, dst))
                except re.error:
                    pass
            else:
                self.exact[src] = dst
            try:
                if src != src.lstrip() and src.strip():          # Endstück: " · {0} Frames" an etwas angehängt
                    self.affix.append((compile_tmpl(src, pre="(?P<gP>.+?)"), src, dst, "P"))
                if src != src.rstrip() and src.strip():          # Anfang: "Läuft bereits auf: " + Liste
                    self.affix.append((compile_tmpl(src, post="(?P<gR>.+)"), src, dst, "R"))
            except re.error:
                pass
        # Vorlagen und Satzanfänge/-enden gemeinsam, die mit dem längsten festen Text zuerst
        fixed = lambda src: len(re.sub(r"\{\d+\}", "", src).strip())
        self.templates = sorted([(rx, src, dst, None) for rx, src, dst in self.templates] + self.affix,
                                key=lambda x: -fixed(x[1]))

    # -- Übersetzen
    def t(self, text):
        if not isinstance(text, str) or not text.strip():
            return text
        if text in self.cache:
            return self.cache[text]
        res = text if self.lang == "de" else self._t(text, 0)
        if (NAME_MODIFIED or TRIAL_STARTS > 0) and APP_NAME in res:   # Zusatz am Namen (verändert / Testversion)
            full = display_name()
            res = res.replace(full, APP_NAME).replace(APP_NAME, full)
        if len(self.cache) > 20000:
            self.cache.clear()
        self.cache[text] = res
        return res

    def raw(self, text):
        """Übersetzung ohne Namenszusatz (für den Zusatz selbst)."""
        return text if self.lang == "de" else self._t(text, 0)

    def _t(self, text, depth):
        if text in self.exact:
            return self.exact[text]
        st = text.strip()
        if st != text and st in self.exact:
            return text.replace(st, self.exact[st])
        m = re.match(r"((?:M|NGC|IC|Sh2-|C|B|Mel|Cr|HCG|Abell|Arp|LDN|LBN|vdB|Ced)\s?\d+[A-Za-z]?) (.+)$", text)
        if m and m.group(2) in self.exact:                              # "M31 Andromedagalaxie" → Katalognummer + Name
            return m.group(1) + " " + self.exact[m.group(2)]
        m = re.match(r"(Mo|Di|Mi|Do|Fr|Sa|So) (\d.*)$", text)                # "Di 20.10." / "Mo 22:00"
        if m and m.group(1) in self.exact:
            return self.exact[m.group(1)] + " " + m.group(2)
        m = re.match(r"(\[[^\]\n]{1,60}\] )(.+)$", text, re.S)          # Protokoll: "[Gerät] Meldung"
        if m:
            return m.group(1) + self._t(m.group(2), depth + 1)
        if len(st) > 2 and st[-1] in ".:!?" and st[:-1] in self.exact:     # nur das Satzzeichen ist dazugekommen
            return text.replace(st, self.exact[st[:-1]] + st[-1])
        if depth < 4:
            for rx, src, dst, side in self.templates:
                m = rx.match(text)
                if not m:
                    continue
                g = m.groupdict()
                extra = g.pop("g" + side) if side else None
                vals = {k[1:]: self._t(v, depth + 1) for k, v in g.items()}
                core = re.sub(r"\{(\d+)\}", lambda x: vals.get(x.group(1), x.group(0)), dst)
                if side is None:
                    return core
                ex = self._t(extra, depth + 1)                       # angehängter Text, ggf. als Liste
                if ex == extra and ", " in extra:
                    ex = ", ".join(self._t(e, depth + 1) for e in extra.split(", "))
                return ex + core if side == "P" else core + ex
        for sep in ("\n", "  ·  ", " · ", " – "):                    # zusammengesetzte Texte stückweise
            if sep in text:
                parts = text.split(sep)
                if len(parts) > 1:
                    tr = [self._t(p, depth + 1) if p.strip() else p for p in parts]
                    if tr != parts:
                        return sep.join(tr)
        return text

    def back(self, shown, originals):
        """Angezeigten (übersetzten) Listeneintrag wieder dem deutschen Original zuordnen."""
        for o in originals:
            if self.t(o) == shown:
                return o
        return shown


I18 = I18N()


def tr(text):
    return I18.t(text)


def fmt_num(x, nd=1):
    """Zahl mit dem Dezimaltrennzeichen der eingestellten Sprache (Deutsch 41,2 – Englisch 41.2)."""
    t = f"{x:.{nd}f}"
    return t if I18.lang in ("en", "zh", "ja") else t.replace(".", ",")


def system_language():
    """Sprache des Betriebssystems als Kürzel (de, en, fr …)."""
    code = None
    try:
        if sys.platform == "win32":
            import ctypes
            import locale as _loc
            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            code = _loc.windows_locale.get(lcid, "")
    except Exception:
        code = None
    if not code:
        for env in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
            if os.environ.get(env):
                code = os.environ[env]
                break
    if not code:
        try:
            import locale as _loc
            code = (_loc.getlocale()[0] or "")
        except Exception:
            code = ""
    code = (code or "de").replace("-", "_").split(".")[0]
    for c in (code.lower(), code.split("_")[0].lower()):
        if c in I18.names:
            return c
    return "en" if "en" in I18.names else "de"


# ---- Anbindung an Tk: übersetzt Anzeigetexte, ohne die Programmlogik zu berühren --------------------------
_TEXT_OPTS = ("-text", "-label")
_orig_options = tk.Misc._options
_orig_fmt = ttk._format_optdict
_orig_wm_title = tk.Wm.wm_title


def _shadow_var(widget, var):
    """Anzeige-Variable für Labels/Buttons mit textvariable: zeigt die Übersetzung des Originals."""
    try:
        sv = tk.StringVar(master=widget, value=tr(var.get()))
    except Exception:
        return var
    def follow(*_a):
        try:
            sv.set(tr(var.get()))
        except Exception:
            pass
    var.trace_add("write", follow)
    I18.vars.append((var, sv))
    return sv


def _combo_shadow(widget, var):
    """Auswahlliste (nur lesbar): zeigt Übersetzungen, schreibt beim Auswählen das deutsche Original zurück."""
    sv = tk.StringVar(master=widget, value=tr(var.get()))
    lock = [False]

    def to_orig(*_a):
        if lock[0]:
            return
        lock[0] = True
        try:
            o = I18.back(sv.get(), getattr(widget, "_i18n_vals", []))
            if var.get() != o:
                var.set(o)
        finally:
            lock[0] = False

    def to_shown(*_a):
        if lock[0]:
            return
        lock[0] = True
        try:
            sv.set(tr(var.get()))
        finally:
            lock[0] = False
    sv.trace_add("write", to_orig)
    var.trace_add("write", to_shown)
    I18.vars.append((var, sv))
    return sv


def _patched_options(self, cnf, kw=None):
    if kw:
        cnf = tk._cnfmerge((cnf, kw))
    elif cnf:
        cnf = tk._cnfmerge(cnf)
    if cnf:
        cnf = dict(cnf)
        cls = getattr(self, "widgetName", "")
        if "text" in cnf and isinstance(cnf["text"], str) and cls != "canvas":
            orig = getattr(self, "_i18n_orig", None)
            if orig is None:
                try:
                    self._i18n_orig = orig = {}
                except Exception:
                    orig = {}
            orig["text"] = cnf["text"]
            cnf["text"] = tr(cnf["text"])
        elif "text" in cnf and isinstance(cnf["text"], str):
            cnf["text"] = tr(cnf["text"])
        tv = cnf.get("textvariable")
        if isinstance(tv, tk.StringVar) and cls in ("ttk::label", "label", "ttk::button", "button",
                                                   "ttk::checkbutton", "ttk::radiobutton", "ttk::labelframe"):
            cnf["textvariable"] = _shadow_var(self, tv)
        if cls == "ttk::combobox":
            if "values" in cnf:
                vals = list(cnf["values"]) if not isinstance(cnf["values"], str) else [cnf["values"]]
                self._i18n_vals = vals
                if getattr(self, "_i18n_ro", False) or str(cnf.get("state", "")) == "readonly":
                    cnf["values"] = [tr(v) for v in vals]
            if str(cnf.get("state", "")) == "readonly" and isinstance(tv, tk.StringVar):
                self._i18n_ro = True
                cnf["textvariable"] = _combo_shadow(self, tv)
    return _orig_options(self, cnf, None)


def _patched_fmt(optdict, script=False, ignore=None):
    if "text" in optdict and isinstance(optdict["text"], str):
        optdict = dict(optdict)
        optdict["text"] = tr(optdict["text"])
    return _orig_fmt(optdict, script, ignore)


def _patched_title(self, string=None):
    if string is not None:
        self._i18n_title = string
        string = tr(string)
    return _orig_wm_title(self, string)


tk.Misc._options = _patched_options
ttk._format_optdict = _patched_fmt
tk.Wm.wm_title = tk.Wm.title = _patched_title

_orig_tv_insert = ttk.Treeview.insert
_orig_tv_item = ttk.Treeview.item
_orig_tv_heading = ttk.Treeview.heading


def _tv_vals(kw):
    if "values" in kw and kw["values"] is not None:
        kw = dict(kw)
        kw["values"] = [tr(v) if isinstance(v, str) else v for v in kw["values"]]
    return kw


def _tv_insert(self, parent, index, iid=None, **kw):
    return _orig_tv_insert(self, parent, index, iid, **_tv_vals(kw))


def _tv_item(self, item, option=None, **kw):
    return _orig_tv_item(self, item, option, **_tv_vals(kw))


def _tv_heading(self, column, option=None, **kw):
    if "text" in kw:
        self.__dict__.setdefault("_i18n_heads", {})[column] = kw["text"]
    return _orig_tv_heading(self, column, option, **kw)


ttk.Treeview.insert = _tv_insert
ttk.Treeview.item = _tv_item
ttk.Treeview.heading = _tv_heading

for _fn in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askquestion", "askyesnocancel",
            "askretrycancel"):
    _orig = getattr(messagebox, _fn)

    def _wrap(title=None, message=None, _o=_orig, **kw):
        return _o(tr(title) if title else title, tr(message) if message else message, **kw)
    setattr(messagebox, _fn, _wrap)

for _fn in ("askopenfilename", "asksaveasfilename"):
    _orig = getattr(filedialog, _fn)

    def _wrapf(*a, _o=_orig, **kw):
        if "title" in kw:
            kw["title"] = tr(kw["title"])
        return _o(*a, **kw)
    setattr(filedialog, _fn, _wrapf)


def retranslate_all(root):
    """Nach einem Sprachwechsel: alle sichtbaren Texte neu setzen."""
    for var, sv in list(I18.vars):
        try:
            sv.set(tr(var.get()))
        except Exception:
            pass

    def walk(w):
        orig = getattr(w, "_i18n_orig", None)
        if orig and "text" in orig:
            try:
                w.configure(text=orig["text"])
            except Exception:
                pass
        if isinstance(w, ttk.Combobox) and getattr(w, "_i18n_ro", False):
            try:
                w.configure(values=list(getattr(w, "_i18n_vals", [])))
            except Exception:
                pass
        if isinstance(w, ttk.Treeview):
            for col, txt in getattr(w, "_i18n_heads", {}).items():
                try:
                    w.heading(col, text=txt)
                except Exception:
                    pass
        if isinstance(w, (tk.Tk, tk.Toplevel)) and getattr(w, "_i18n_title", None):
            try:
                w.title(w._i18n_title)
            except Exception:
                pass
        for c in w.winfo_children():
            walk(c)
    walk(root)


# --------------------------------------------------------------------------
# Designs (alle Farben der App an einer Stelle)
# --------------------------------------------------------------------------
_COMMON = {"ok": "#3ddc84", "warn": "#ffd166", "err": "#ff6b6b", "ok_btn": "#1e8c55", "err_btn": "#b23b3b",
           "primary_fg": "#ffffff", "btn_fg": "#eaf3ff", "event": "#c3b5ff", "rx": "#9ee6b8", "tx": "#9cc9ff"}
THEMES = {
    "Blau": dict(_COMMON, **{
        "bg": "#0f2a47", "panel": "#163659", "panel2": "#1b4170", "field": "#0a1f37", "textbg": "#081a2f",
        "canvas": "#071629", "fg": "#e8f1ff", "muted": "#9fb7d3", "muted2": "#c3d4ea", "dim": "#6f89a8",
        "grid": "#2d4c72", "border": "#2b527f", "accent": "#7cc4ff",
        "btn": "#1f5f9e", "btn_hover": "#2a72bb", "btn_press": "#184e83", "btn_border": "#3a7cc0",
        "primary": "#2d8cff", "primary_hover": "#56a3ff", "primary_press": "#1f6fd1", "primary_border": "#6fb2ff",
        "tab": "#143456", "tab_sel": "#1f5f9e", "sel": "#2d8cff",
        "ring_ok": "#1d5a4a", "ring_warn": "#5f5a2a", "ring_err": "#5f2f3a"}),
    "Nacht (rot)": dict(_COMMON, **{
        "bg": "#140404", "panel": "#1f0707", "panel2": "#2a0a0a", "field": "#0e0202", "textbg": "#0b0202",
        "canvas": "#080101", "fg": "#ff8a7a", "muted": "#b8564b", "muted2": "#d56a5d", "dim": "#7a3229",
        "grid": "#3a1010", "border": "#4a1414", "accent": "#ff6a55",
        "btn": "#3a0d0d", "btn_hover": "#541414", "btn_press": "#2c0909", "btn_border": "#6a1c1c",
        "primary": "#8a1b1b", "primary_hover": "#a52323", "primary_press": "#6d1414", "primary_border": "#b33a3a",
        "tab": "#1f0707", "tab_sel": "#3a0d0d", "sel": "#8a1b1b", "btn_fg": "#ffb0a5", "primary_fg": "#ffd5cf",
        "ok": "#ff9a7a", "warn": "#ffb36b", "err": "#ff4a4a", "ok_btn": "#5a1a10", "err_btn": "#7a1010",
        "event": "#ff9a8a", "rx": "#ff9a8a", "tx": "#ffb0a0",
        "ring_ok": "#3a1410", "ring_warn": "#3a2410", "ring_err": "#4a1010"}),
    "Dunkel": dict(_COMMON, **{
        "bg": "#14161c", "panel": "#1d2028", "panel2": "#2a2e39", "field": "#1d2028", "textbg": "#0e1015",
        "canvas": "#0b0d12", "fg": "#e6e6e6", "muted": "#9a9a9a", "muted2": "#bbbbbb", "dim": "#707070",
        "grid": "#444444", "border": "#3a3d47", "accent": "#e58e7a",
        "btn": "#262a35", "btn_hover": "#323746", "btn_press": "#1d2028", "btn_border": "#3a3d47",
        "primary": "#c0392b", "primary_hover": "#e74c3c", "primary_press": "#a83224", "primary_border": "#e06a5c",
        "tab": "#1d2028", "tab_sel": "#2a2e39", "sel": "#7a3a30",
        "ring_ok": "#1e3a26", "ring_warn": "#3a3a1e", "ring_err": "#3a2222"}),
}
for _tn, _tv in THEMES.items():                 # Ladeblitz: gelb, im Nachtmodus gedämpft (Dunkeladaption)
    _tv.setdefault("bolt", "#b34a1e" if _tn.startswith("Nacht") else "#ffd23f")
C = dict(THEMES["Blau"])          # aktive Farben (wird beim Start aus der Konfiguration gesetzt)

APP_NAME = "Star Gazing Control Center by TheSkyCoder"
EDITION = os.environ.get("SGCC_EDITION", "seestar")    # "asiair" = eigenständige ASIAIR-Ausgabe (asiair_start.py)
EDITION_SUFFIX = {"asiair": "ASIAIR-Edition"}
APP_ID = "StarGazingControlCenter"
TRIAL_STARTS = 10                # > 0 = Testversion: so viele Starts, danach gesperrt (wird beim Bauen gesetzt)
TRIAL_WARN_FROM = 8              # ab diesem Start Vorwarnung
TRIAL_CONTACT = ("For the full version, feel free to contact me on Facebook: profile “Bönn Ingstedt” – "
                 "easiest to find by searching for “TheSkyCoder”.")     # Testversion: Hinweise immer Englisch


def _trial_stores():
    base = Path(os.environ.get("APPDATA") or Path.home())
    return [base / "TheSkyCoder" / ".sgcc_t", Path.home() / ".sgcc_t"]


def trial_bump():
    """Startzähler der Testversion lesen und um 1 erhöhen. Mehrfach abgelegt (Registry + Dateien), es zählt der
    höchste Stand – so setzt Löschen einer einzelnen Datei den Zähler nicht zurück."""
    seen = [0]
    for f in _trial_stores():
        try:
            seen.append(int(f.read_text().strip() or 0))
        except Exception:
            pass
    reg = None
    try:
        import winreg
        reg = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\TheSkyCoder\StarGazingControlCenter")
        try:
            seen.append(int(winreg.QueryValueEx(reg, "t")[0]))
        except OSError:
            pass
    except Exception:
        reg = None
    n = max(seen) + 1
    for f in _trial_stores():
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(str(n))
        except Exception:
            pass
    if reg is not None:
        try:
            import winreg
            winreg.SetValueEx(reg, "t", 0, winreg.REG_DWORD, n)
            winreg.CloseKey(reg)
        except Exception:
            pass
    return n


TRIAL_COUNT = trial_bump() if TRIAL_STARTS > 0 and __name__ == "__main__" else 0


# --------------------------------------------------------------------------
# Echtheitsprüfung des Programmnamens
# Nur vom Urheber signierte Fassungen zeigen den Namen ohne Zusatz. Wird das Programm, der Katalog oder
# eine mitgelieferte Sprachdatei verändert (oder der Name), passt die Signatur nicht mehr und der Name
# erhält den Zusatz „(modifiziert)“ in der eingestellten Sprache.
# --------------------------------------------------------------------------
SIGN_PUBKEY = "btrleRI0MCJqsPmYXClokPEKuMnQM3RBBNfikGMvlNQ="
SIGN_FILE = Path(__file__).with_name("SIGNATUR.txt")
MAIN_KEY = "PROGRAMM"                     # das Hauptskript – unabhängig vom Dateinamen


def release_manifest(folder, files):
    """Signierter Text: je Datei Name und SHA-256 (Zeilenenden vereinheitlicht)."""
    lines = []
    for rel in sorted(files):
        path = Path(__file__).resolve() if rel == MAIN_KEY else Path(folder) / rel
        data = path.read_bytes().replace(b"\r\n", b"\n")
        lines.append(f"{rel}:{hashlib.sha256(data).hexdigest()}")
    return "\n".join(lines).encode("utf-8")


def _ed25519_verify_py(pub, msg, sig):
    """Ed25519-Prüfung nach RFC 8032 in reinem Python (falls 'cryptography' fehlt)."""
    q = 2 ** 255 - 19
    L = 2 ** 252 + 27742317777372353535851937790883648493
    d = -121665 * pow(121666, q - 2, q) % q
    I = pow(2, (q - 1) // 4, q)

    def H(m):
        return hashlib.sha512(m).digest()

    def add(P, Q):
        x1, y1, z1, t1 = P
        x2, y2, z2, t2 = Q
        A = (y1 - x1) * (y2 - x2) % q
        B = (y1 + x1) * (y2 + x2) % q
        Cc = t1 * 2 * d * t2 % q
        D = z1 * 2 * z2 % q
        E, F, G, Hh = B - A, D - Cc, D + Cc, B + A
        return (E * F % q, G * Hh % q, F * G % q, E * Hh % q)

    def mul(s, P):
        Q = (0, 1, 1, 0)
        while s > 0:
            if s & 1:
                Q = add(Q, P)
            P = add(P, P)
            s >>= 1
        return Q

    def eq(P, Q):
        return (P[0] * Q[2] - Q[0] * P[2]) % q == 0 and (P[1] * Q[2] - Q[1] * P[2]) % q == 0

    def recover_x(y, sign):
        if y >= q:
            return None
        x2 = (y * y - 1) * pow(d * y * y + 1, q - 2, q)
        if x2 == 0:
            return None if sign else 0
        x = pow(x2, (q + 3) // 8, q)
        if (x * x - x2) % q != 0:
            x = x * I % q
        if (x * x - x2) % q != 0:
            return None
        if (x & 1) != sign:
            x = q - x
        return x

    def decompress(b):
        y = int.from_bytes(b, "little")
        sign = y >> 255
        y &= (1 << 255) - 1
        x = recover_x(y, sign)
        return None if x is None else (x, y, 1, x * y % q)

    gy = 4 * pow(5, q - 2, q) % q
    G = (recover_x(gy, 0), gy, 1, recover_x(gy, 0) * gy % q)
    if len(pub) != 32 or len(sig) != 64:
        return False
    A = decompress(pub)
    R = decompress(sig[:32])
    if A is None or R is None:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= L:
        return False
    h = int.from_bytes(H(sig[:32] + pub + msg), "little") % L
    return eq(mul(s, G), add(R, mul(h, A)))


def check_original():
    """True = unveränderte, vom Urheber signierte Fassung."""
    try:
        info = json.loads(SIGN_FILE.read_text(encoding="utf-8"))
        files = list(info["files"])
        if MAIN_KEY not in files or "catalog.json" not in files:
            return False
        bundled = {f"lang/{p.name}" for p in LANG_DIR.glob("*.txt")} if LANG_DIR.exists() else set()
        if any(f.startswith("lang/") and f not in bundled for f in files):
            return False                                   # mitgelieferte Sprachdatei fehlt
        msg = release_manifest(Path(__file__).resolve().parent, files)
        sig = base64.b64decode(info["signature"])
        pub = base64.b64decode(SIGN_PUBKEY)
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            Ed25519PublicKey.from_public_bytes(pub).verify(sig, msg)
            return True
        except ImportError:
            return _ed25519_verify_py(pub, msg, sig)
    except Exception:
        return False


def _owner_key_paths():
    """Wo der private Schlüssel des Urhebers liegen darf (nur auf seinem eigenen PC)."""
    here = Path(__file__).resolve().parent
    paths = [Path(os.environ["STARGAZING_SIGNING_KEY"])] if os.environ.get("STARGAZING_SIGNING_KEY") else []
    paths += [Path.home() / ".stargazing_signaturschluessel.pem", here.parent / "Signaturschluessel_PRIVAT.pem"]
    paths += sorted(here.parent.glob("Signatur_Werkzeug*/Signaturschluessel_PRIVAT.pem"))
    return paths


def auto_sign_if_owner():
    """Auf dem PC des Urhebers (privater Schlüssel vorhanden) die eigene Fassung selbst neu signieren."""
    try:
        from cryptography.hazmat.primitives import serialization
    except ImportError:
        return False
    for kp in _owner_key_paths():
        try:
            if not kp.is_file():
                continue
            key = serialization.load_pem_private_key(kp.read_bytes(), password=None)
            pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            if base64.b64encode(pub).decode() != SIGN_PUBKEY:
                continue                                   # fremder Schlüssel
            folder = Path(__file__).resolve().parent
            files = [MAIN_KEY, "catalog.json"] + sorted(f"lang/{p.name}" for p in LANG_DIR.glob("*.txt"))
            sig = key.sign(release_manifest(folder, files))
            SIGN_FILE.write_text(json.dumps({"files": files, "signature": base64.b64encode(sig).decode()},
                                            indent=1), encoding="utf-8")
            return check_original()
        except Exception:
            continue
    return False


ORIGINAL_SIGNED = check_original()
AUTO_SIGNED = (not ORIGINAL_SIGNED) and auto_sign_if_owner()
NAME_MODIFIED = not (ORIGINAL_SIGNED or AUTO_SIGNED)
MODIFIED_MARK = "(modifiziert)"


def display_name():
    """Programmname wie angezeigt – bei veränderter Fassung mit Zusatz in der aktuellen Sprache."""
    if TRIAL_STARTS > 0:
        name = f"{APP_NAME} · Trial version"
        return name if not NAME_MODIFIED else f"{name} {I18.raw(MODIFIED_MARK) or '(modified)'}"
    if not NAME_MODIFIED:
        return APP_NAME
    mark = I18.raw(MODIFIED_MARK)
    if not re.search(r"\w", mark or "") or mark.strip() in ("()", ""):
        mark = "(modified)"                                 # Zusatz darf nicht leer übersetzt werden
    return f"{APP_NAME} {mark}"
RPC_PORT = 4700
IMG_PORT = 4800
DISCOVERY_PORT = 4720


# --------------------------------------------------------------------------
# Modellprofile
# Werte laut ZWO/Händlerangaben. fov_w/fov_h = Bildfeld in Grad (kurze/lange Seite),
# genutzt für die Mosaik-Planung. 60 s nur im EQ-Modus (Polausrichtung nötig).
# --------------------------------------------------------------------------
MODELS = {
    "S50": {
        "label": "Seestar S50", "optik": "50 mm · 250 mm · f/5", "sensor": "Sony IMX462 · 1080 × 1920",
        "fov": "0,73° × 1,29°", "fov_w": 0.73, "fov_h": 1.29, "wide": False,
        "lp_name": "LP-Filter (Duo-Band)",
    },
    "S50 Pro": {
        "label": "Seestar S50 Pro", "optik": "50 mm · 260 mm · f/5,2 (+ Weitwinkel 63°)",
        "sensor": "1/1,2\" · 2160 × 3840", "fov": "ca. 1,6° × 2,8°", "fov_w": 1.58, "fov_h": 2.8, "wide": True,
        "lp_name": "Duo-Band-Filter (OIII/Hα)",
    },
    "S30": {
        "label": "Seestar S30", "optik": "30 mm · 150 mm · f/5 (+ Weitwinkel)", "sensor": "Sony IMX662 · 1920 × 1080",
        "fov": "1,2° × 2,13°", "fov_w": 1.2, "fov_h": 2.13, "wide": True,
        "lp_name": "LP-Filter",
    },
    "S30 Pro": {
        "label": "Seestar S30 Pro", "optik": "30 mm · 160 mm · f/5,3 (+ Weitwinkel 63°)",
        "sensor": "Sony IMX585 · 3840 × 2160", "fov": "2,26° × 3,99°", "fov_w": 2.26, "fov_h": 3.99, "wide": True,
        "lp_name": "LP-Filter",
    },
}

VIEW_MODES = {"Sterne / Deep Sky": "star", "Mond": "moon", "Sonne (nur mit Sonnenfilter!)": "sun",
              "Landschaft": "scenery"}
ONOFF = [("Aus", False), ("An", True)]


def _g(d, path, default=None):
    """Verschachtelt lesen: _g(res, 'stack.cont_capt')."""
    for part in path.split("."):
        if not isinstance(d, dict) or part not in d:
            return default
        d = d[part]
    return d


def _first(res, *paths):
    for p in paths:
        v = _g(res, p)
        if v is not None:
            return v
    return None


def _set(params):
    return [("set_setting", params)]


def _stack(params):
    # neuere Firmware: set_setting{"stack": …}, ältere: set_stack_setting
    return [("set_setting", {"stack": params}), ("set_stack_setting", params)]


# Einstellungen wie in der Seestar-App. Jede Zeile:
#   key, Abschnitt, Beschriftung, Optionen [(Text, Wert)], Lesen(res)->Wert, Senden(wert, alle)->[(Methode, Params)…],
#   nur_für(Modell)->bool (optional)
SETTINGS = [
    # --- Stacking -----------------------------------------------------------
    ("exp", "Stacking", "Belichtung pro Frame",
     [("2 s", 2000), ("5 s", 5000), ("10 s", 10000), ("20 s", 20000), ("30 s", 30000), ("60 s (nur EQ, Maximum)", 60000)],
     lambda r: _g(r, "exp_ms.stack_l"), lambda v, a: _set({"exp_ms": {"stack_l": v}}), None),
    ("gain", "Stacking", "Gain",
     [("40", 40), ("60", 60), ("80 (Standard)", 80), ("100", 100), ("120", 120)],
     lambda r: _first(r, "_camera.gain", "gain"), lambda v, a: [("set_control_value", ["gain", v])], None),
    ("lp", "Stacking", "{lp}",
     ONOFF, lambda r: _g(r, "stack_lenhance"), lambda v, a: _set({"stack_lenhance": v}), None),
    ("auto_lp", "Stacking", "Filter automatisch wählen",
     ONOFF, lambda r: _first(r, "auto_lenhance", "stack.auto_lenhance"),
     lambda v, a: [("set_setting", {"stack": {"auto_lenhance": v}}), ("set_setting", {"auto_lenhance": v})], None),
    ("dither", "Stacking", "Dithering",
     ONOFF, lambda r: _g(r, "stack_dither.enable"),
     lambda v, a: _set({"stack_dither": {"enable": v, "pix": a.get("dither_pix", 50), "interval": a.get("dither_int", 5)}}), None),
    ("dither_pix", "Stacking", "Dither-Abstand",
     [("10 px", 10), ("25 px", 25), ("50 px", 50), ("75 px", 75), ("100 px", 100)],
     lambda r: _g(r, "stack_dither.pix"),
     lambda v, a: _set({"stack_dither": {"enable": a.get("dither", True), "pix": v, "interval": a.get("dither_int", 5)}}), None),
    ("dither_int", "Stacking", "Dither alle … Frames",
     [("1", 1), ("2", 2), ("3", 3), ("5", 5), ("10", 10)],
     lambda r: _g(r, "stack_dither.interval"),
     lambda v, a: _set({"stack_dither": {"enable": a.get("dither", True), "pix": a.get("dither_pix", 50), "interval": v}}), None),
    ("calib", "Stacking", "Dark-Kalibrierung",
     ONOFF, lambda r: _g(r, "frame_calib"), lambda v, a: _set({"frame_calib": v}), None),
    ("save", "Stacking", "Einzelframes speichern",
     [("Nein", "none"), ("Nur gute Frames", "ok"), ("Alle Frames", "all")],
     lambda r: ("all" if _first(r, "stack.save_discrete_frame", "save_discrete_frame") else
                "ok" if _first(r, "stack.save_discrete_ok_frame", "save_discrete_ok_frame") else
                ("none" if _first(r, "stack.save_discrete_frame", "save_discrete_frame") is not None else None)),
     lambda v, a: _stack({"save_discrete_frame": v == "all", "save_discrete_ok_frame": v == "ok"}), None),
    ("cont", "Stacking", "Serienaufnahme (ohne Stacken)",
     ONOFF, lambda r: (_g(r, "stack.capt_type") == "cont_capt") if _g(r, "stack.capt_type") is not None
     else _first(r, "stack.cont_capt", "stack_cont_capt", "cont_capt"),
     # wie die Seestar-App (APK 25.11.): Aufnahmeart capt_type "cont_capt" / "stack", mit gewählter Kamera wide_cam
     lambda v, a: [("set_setting", {"wide_cam": bool(a.get("wide_cam", False)),
                                    "stack": {"capt_type": "cont_capt" if v else "stack"}})], None),
    ("drizzle", "Stacking", "4K-Modus (Drizzle 2×)",
     ONOFF, lambda r: _g(r, "stack.drizzle2x"), lambda v, a: _set({"stack": {"drizzle2x": v}}), None),
    ("dbe", "Stacking", "Hintergrund-Extraktion (DBE)",
     ONOFF, lambda r: _first(r, "stack.dbe_enable", "stack.dbe"),          # dbe_enable = Schalter der Seestar-App
     # wie die Seestar-App (APK 25.11., setStackAdjust): wide_cam + stack{brightness, contrast, saturation, dbe_enable}
     lambda v, a: [("set_setting", {"wide_cam": bool(a.get("wide_cam", False)),
                                    "stack": {"brightness": 0.0, "contrast": 0.0, "saturation": 0.0,
                                              "dbe_enable": bool(v)}})], None),
    ("star_corr", "Stacking", "Sternkorrektur",
     ONOFF, lambda r: _g(r, "stack.star_correction"), lambda v, a: _set({"stack": {"star_correction": v}}), None),
    ("plane_lines", "Stacking", "Flugzeug-/Satellitenspuren entfernen",
     ONOFF, lambda r: _g(r, "stack.airplane_line_removal"),
     lambda v, a: _set({"stack": {"airplane_line_removal": v}}), None),
    ("stack_after_goto", "Stacking", "Nach GoTo automatisch stacken",
     ONOFF, lambda r: _g(r, "stack_after_goto"), lambda v, a: _set({"stack_after_goto": v}), None),
    # --- Fokus ----------------------------------------------------------------
    ("auto_af", "Fokus", "Smart-AF (GoTo/Temperatur)",
     ONOFF, lambda r: _g(r, "auto_af"), lambda v, a: _set({"auto_af": v}), None),
    ("af_before", "Fokus", "Autofokus vor jedem Ziel",
     ONOFF, lambda r: _first(r, "plan_target_af", "af_before_stack"),
     lambda v, a: [("set_setting", {"plan_target_af": v}), ("set_setting", {"af_before_stack": v})], None),
    # --- Gerät ----------------------------------------------------------------
    ("heater", "Gerät", "Anti-Tau-Heizung",
     ONOFF,                                   # Firmware kennt nur Ein/Aus (heater_enable), keine Stufen
     lambda r: _g(r, "heater_enable") if _g(r, "heater_enable") is not None
     else ((_g(r, "heater.state") is not False and bool(_g(r, "heater.value"))) if _g(r, "heater") is not None else None),
     # wie die Seestar-App (APK 25.11., setHeater): nur pi_output_set2, Wert immer 90
     lambda v, a: [("pi_output_set2", {"heater": {"state": bool(v), "value": 90}})], None),
    ("power_off", "Gerät", "Automatisch ausschalten",
     ONOFF, lambda r: _g(r, "auto_power_off"), lambda v, a: _set({"auto_power_off": v}), None),
    ("temp_unit", "Gerät", "Temperatureinheit",
     [("°C", "C"), ("°F", "F")], lambda r: _g(r, "temp_unit"), lambda v, a: _set({"temp_unit": v}), None),
    ("ppa", "Gerät", "EQ-Polausrichtung kalibrieren",
     ONOFF, lambda r: _g(r, "auto_3ppa_calib"), lambda v, a: _set({"auto_3ppa_calib": v}), None),
    ("gohome", "Gerät", "Nach Seestar-Plan Arm schließen",
     ONOFF, lambda r: _first(r, "viewplan_gohome", "viewplan_go_home", "viewplan.go_home"),
     lambda v, a: [("set_setting", {"viewplan_gohome": v}), ("set_setting", {"viewplan_go_home": v}),
                   ("set_setting", {"viewplan": {"go_home": v}})], None),
    ("expert", "Gerät", "Expertenmodus",
     ONOFF, lambda r: _g(r, "expert_mode"), lambda v, a: _set({"expert_mode": v}), None),
    # --- Live-Ansicht -----------------------------------------------------------
    ("zoom", "Live-Ansicht", "Zoom (Sonne/Mond/Planet)",
     [("1×", 0), ("2×", 1), ("4×", 2)], lambda r: _g(r, "rtsp_roi_index"),
     lambda v, a: _set({"rtsp_roi_index": v}), None),
    ("cont_exp", "Live-Ansicht", "Belichtung Live-Bild",
     [("50 ms", 50), ("100 ms", 100), ("200 ms", 200), ("500 ms", 500), ("1 s", 1000), ("2 s", 2000)],
     lambda r: _g(r, "exp_ms.continuous"), lambda v, a: _set({"exp_ms": {"continuous": v}}), None),
    # --- Weitwinkel (S30, S30 Pro, S50 Pro) --------------------------------------
    ("wide_cam", "Weitwinkel", "Weitwinkelkamera verwenden",
     ONOFF, lambda r: _g(r, "wide_cam"), lambda v, a: _set({"wide_cam": v}), lambda m: MODELS.get(m, {}).get("wide")),
    ("wide_4k", "Weitwinkel", "Weitwinkel in 4K",
     ONOFF, lambda r: _g(r, "wide_4k"), lambda v, a: _set({"wide_4k": v}), lambda m: MODELS.get(m, {}).get("wide")),
    ("wide_denoise", "Weitwinkel", "Weitwinkel-Entrauschen",
     ONOFF, lambda r: _first(r, "wide_denoise", "stack.wide_denoise"), lambda v, a: _set({"wide_denoise": v}),
     lambda m: MODELS.get(m, {}).get("wide")),
]
SECTIONS = ["Stacking", "Fokus", "Gerät", "Live-Ansicht", "Weitwinkel"]
SETTING_LABEL = {x[0]: x[2] for x in SETTINGS}
SETTING_HINTS = {
    "cont": "Serienaufnahme: Das Seestar nimmt nur Einzelbilder hintereinander auf und rechnet sie NICHT zu einem "
            "Gesamtbild zusammen (kein Live-Stack). Sinnvoll für Meteore/Satelliten oder wenn du die Einzelbilder "
            "selbst bearbeitest. Für normale Aufnahmen AUS lassen – Einzelbilder speichert das Seestar mit "
            "„Einzelframes speichern“ auch beim Stacken.",
}
ARM_CLOSE_SETTINGS = ("power_off", "gohome")      # Einstellungen, mit denen das Seestar den Arm selbst schließt
RECOMMENDED = {"exp": 10000, "gain": 80, "lp": False, "dither": True, "dither_pix": 50, "dither_int": 5,
               "calib": True, "save": "ok", "heater": False}


def model_key(product_model: str):
    """'Seestar S50', 'S30P', 'S50 Pro' … -> Schlüssel in MODELS (oder None)."""
    compact = re.sub(r"[\s_-]+", "", str(product_model or "")).lower()
    m = re.search(r"s(30|50)(pro|p(?!lus))?", compact)
    if not m:
        return None
    return f"S{m.group(1)}" + (" Pro" if m.group(2) else "")
CONFIG_FILE = Path.home() / ".star_gazing_control_center.json"
_OLD_CONFIG = Path.home() / ".seestar_control.json"          # Einstellungen der Vorgängerversion übernehmen
if not CONFIG_FILE.exists() and _OLD_CONFIG.exists():
    try:
        CONFIG_FILE.write_text(_OLD_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception:
        pass


# --------------------------------------------------------------------------
# Zugangsdaten: WLAN-Passwörter nicht im Klartext speichern
# Windows: DPAPI (nur dein Windows-Benutzerkonto kann es wieder lesen); sonst nur verschleiert.
# --------------------------------------------------------------------------
def _dpapi(data: bytes, encrypt: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(data, len(data))
    src, dst = BLOB(len(data), buf), BLOB()
    fn = ctypes.windll.crypt32.CryptProtectData if encrypt else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0x01, ctypes.byref(dst)):   # 0x01 = UI verbieten
        raise OSError("DPAPI fehlgeschlagen")
    try:
        return ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(dst.pbData)


def titlebar_style(win, theme):
    """Windows: Titelleiste passend zum Design (Dunkel/Nacht dunkel, Nacht zusätzlich rot) – eine helle Leiste
    stört nachts die Dunkeladaption. Auf anderen Systemen und älterem Windows passiert einfach nichts."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        dark = ctypes.c_int(0 if theme == "Blau" else 1)
        for attr in (20, 19):                               # DWMWA_USE_IMMERSIVE_DARK_MODE (neu / alt)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(dark), 4) == 0:
                break
        night = theme.startswith("Nacht")
        cap = ctypes.c_uint(0x00000A1E if night else 0xFFFFFFFF)     # COLORREF 0x00BBGGRR, 0xFFFFFFFF = Standard
        txt = ctypes.c_uint(0x003A46D0 if night else 0xFFFFFFFF)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(cap), 4)   # Leistenfarbe (Win 11)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(txt), 4)   # Schriftfarbe (Win 11)
    except Exception:
        pass


def _win_hwnd(win):
    import ctypes
    win.update_idletasks()
    return ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()


def monitor_rects():
    """Alle Bildschirme als (links, oben, rechts, unten) in Windows-Koordinaten – auch links/oberhalb vom
    Hauptbildschirm (negative Werte). Ohne Windows: ein Bildschirm ab (0, 0)."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            rects = []
            proc = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                      wintypes.LPARAM)

            def cb(_h, _dc, r, _p):
                rects.append((r.contents.left, r.contents.top, r.contents.right, r.contents.bottom))
                return 1
            ctypes.windll.user32.EnumDisplayMonitors(None, None, proc(cb), 0)
            if rects:
                return rects
        except Exception:
            pass
    return None


def window_monitor(win):
    """Rechteck des Bildschirms, auf dem das Fenster gerade (überwiegend) liegt."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class MI(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                            ("dwFlags", wintypes.DWORD)]
            mon = ctypes.windll.user32.MonitorFromWindow(_win_hwnd(win), 2)      # MONITOR_DEFAULTTONEAREST
            mi = MI()
            mi.cbSize = ctypes.sizeof(MI)
            if ctypes.windll.user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
                r = mi.rcMonitor
                return (r.left, r.top, r.right, r.bottom)
        except Exception:
            pass
    return (0, 0, win.winfo_screenwidth(), win.winfo_screenheight())


def toggle_fullscreen(win, state):
    """Vollbild auf dem Bildschirm, auf dem das Fenster gerade ist. Tk würde unter Windows das Fenster erst
    „wiederherstellen“ – bei mehreren Monitoren landet es dann oft auf dem anderen Bildschirm."""
    going = not state.get("fs")
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            hwnd = _win_hwnd(win)
            GWL_STYLE, WS_CAPTION, WS_THICKFRAME = -16, 0x00C00000, 0x00040000
            SWP_FRAMECHANGED, SWP_SHOWWINDOW, SWP_NOZORDER = 0x0020, 0x0040, 0x0004
            if going:
                l, t, r, b = window_monitor(win)
                rect = wintypes.RECT()
                u.GetWindowRect(hwnd, ctypes.byref(rect))
                state.update(style=u.GetWindowLongW(hwnd, GWL_STYLE), zoomed=bool(u.IsZoomed(hwnd)),
                             rect=(rect.left, rect.top, rect.right, rect.bottom))
                u.SetWindowLongW(hwnd, GWL_STYLE, state["style"] & ~(WS_CAPTION | WS_THICKFRAME))
                u.SetWindowPos(hwnd, 0, l, t, r - l, b - t, SWP_FRAMECHANGED | SWP_SHOWWINDOW | SWP_NOZORDER)
            else:
                u.SetWindowLongW(hwnd, GWL_STYLE, state.get("style", u.GetWindowLongW(hwnd, GWL_STYLE)))
                l, t, r, b = state.get("rect", (100, 100, 1300, 900))
                u.SetWindowPos(hwnd, 0, l, t, r - l, b - t, SWP_FRAMECHANGED | SWP_SHOWWINDOW | SWP_NOZORDER)
                if state.get("zoomed"):
                    u.ShowWindow(hwnd, 3)                                   # SW_MAXIMIZE
            state["fs"] = going
            return
        except Exception:
            pass
    state["fs"] = going
    win.attributes("-fullscreen", going)


def secret_protect(text: str) -> str:
    if not text:
        return ""
    raw = text.encode("utf-8")
    if sys.platform == "win32":
        try:
            return "dpapi:" + base64.b64encode(_dpapi(raw, True)).decode()
        except Exception:
            pass
    return "b64:" + base64.b64encode(raw).decode()


def secret_unprotect(blob: str) -> str:
    try:
        if not blob:
            return ""
        kind, _, data = blob.partition(":")
        raw = base64.b64decode(data)
        if kind == "dpapi":
            raw = _dpapi(raw, False)
        return raw.decode("utf-8")
    except Exception:
        return ""


DEFAULT_AP_PASS = "12345678"            # Werkseinstellung des Seestar-WLANs (laut Handbuch)
AP_DEFAULT_IP = "10.0.0.1"              # Adresse des Seestar im eigenen WLAN (Direktverbindung)


def tcp_reachable(host, port=4700, timeout=1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _netsh(*args, timeout=20):
    import subprocess
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run(["netsh", "wlan", *args], capture_output=True, timeout=timeout, creationflags=flags)
    out = (r.stdout or b"") + (r.stderr or b"")
    for enc in ("utf-8", "cp850", "cp1252"):
        try:
            return r.returncode, out.decode(enc)
        except UnicodeDecodeError:
            continue
    return r.returncode, out.decode("latin-1")


def join_seestar_wifi(ssid: str, password: str, host: str = AP_DEFAULT_IP, wait: float = 30.0):
    """PC (Windows) mit dem WLAN des Seestar verbinden. Gibt (ok, Meldung) zurück."""
    if sys.platform != "win32":
        return False, "Automatisches WLAN-Verbinden geht nur unter Windows – bitte im WLAN-Menü des PCs verbinden."
    if not ssid:
        return False, "Kein WLAN-Name eingetragen."
    import tempfile
    from xml.sax.saxutils import escape
    sec = (f"<authEncryption><authentication>WPA2PSK</authentication><encryption>AES</encryption>"
           f"<useOneX>false</useOneX></authEncryption><sharedKey><keyType>passPhrase</keyType>"
           f"<protected>false</protected><keyMaterial>{escape(password)}</keyMaterial></sharedKey>") if password else \
          ("<authEncryption><authentication>open</authentication><encryption>none</encryption>"
           "<useOneX>false</useOneX></authEncryption>")
    xml = (f'<?xml version="1.0"?><WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">'
           f"<name>{escape(ssid)}</name><SSIDConfig><SSID><name>{escape(ssid)}</name></SSID></SSIDConfig>"
           f"<connectionType>ESS</connectionType><connectionMode>manual</connectionMode>"
           f"<MSM><security>{sec}</security></MSM></WLANProfile>")
    fd, path = tempfile.mkstemp(suffix=".xml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(xml)
        code, out = _netsh("add", "profile", f"filename={path}", "user=current")
    finally:
        try:
            os.remove(path)                      # Datei mit Passwort sofort wieder löschen
        except OSError:
            pass
    if code != 0:
        if "location" in out.lower() or "standort" in out.lower():
            return False, ("Windows verlangt für WLAN-Befehle die Standortfreigabe: Einstellungen › Datenschutz › "
                           "Standort › „Desktop-Apps Zugriff auf den Standort erlauben“ einschalten.")
        return False, f"WLAN-Profil konnte nicht angelegt werden: {out.strip()[:200]}"
    code, out = _netsh("connect", f"name={ssid}", f"ssid={ssid}")
    if code != 0:
        return False, f"Verbinden mit „{ssid}“ fehlgeschlagen: {out.strip()[:200]}"
    end = time.time() + wait
    while time.time() < end:
        if tcp_reachable(host, timeout=1.5):
            return True, f"PC ist mit dem WLAN „{ssid}“ verbunden."
        time.sleep(1.5)
    return False, (f"Mit „{ssid}“ verbunden, aber das Seestar antwortet nicht unter {host}. Passwort richtig? "
                   "Ist das Seestar eingeschaltet und in der Nähe?")


# --------------------------------------------------------------------------
# Konfiguration
# --------------------------------------------------------------------------
def load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    try:
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass


# --------------------------------------------------------------------------
# Hilfsfunktionen Koordinaten
# --------------------------------------------------------------------------
def parse_ra(text: str) -> float:
    """RA in Stunden. Akzeptiert '5.588', '5h35m17s', '5:35:17', '5 35 17'."""
    t = text.strip().lower().replace("h", " ").replace("m", " ").replace("s", " ").replace(":", " ")
    parts = [float(p) for p in t.split()]
    if not parts:
        raise ValueError("RA leer")
    val = parts[0] + (parts[1] / 60 if len(parts) > 1 else 0) + (parts[2] / 3600 if len(parts) > 2 else 0)
    if not 0 <= val < 24:
        raise ValueError("RA muss zwischen 0 und 24 h liegen")
    return val


def parse_dec(text: str) -> float:
    """Dec in Grad. Akzeptiert '-5.39', '-5°23'28"', '-5:23:28', '-5 23 28'."""
    t = text.strip()
    neg = t.startswith("-")
    for ch in "°d'm\"s:+-":
        t = t.replace(ch, " ")
    parts = [float(p) for p in t.split()]
    if not parts:
        raise ValueError("Dec leer")
    val = parts[0] + (parts[1] / 60 if len(parts) > 1 else 0) + (parts[2] / 3600 if len(parts) > 2 else 0)
    val = -val if neg else val
    if not -90 <= val <= 90:
        raise ValueError("Dec muss zwischen -90° und +90° liegen")
    return val


# Kleiner Katalog für den Schnellzugriff (J2000; RA in h, Dec in °)
CATALOG = {
    "M31 Andromedagalaxie": (0.7123, 41.269),
    "M33 Dreiecksgalaxie": (1.5641, 30.660),
    "M45 Plejaden": (3.7833, 24.117),
    "M42 Orionnebel": (5.5881, -5.391),
    "M1 Krebsnebel": (5.5756, 22.014),
    "NGC 2244 Rosettennebel": (6.5333, 4.950),
    "M81 Bodes Galaxie": (9.9259, 69.065),
    "M101 Feuerradgalaxie": (14.0535, 54.349),
    "M51 Whirlpoolgalaxie": (13.4983, 47.195),
    "M13 Herkuleshaufen": (16.6948, 36.461),
    "M57 Ringnebel": (18.8932, 33.029),
    "M27 Hantelnebel": (19.9934, 22.721),
    "NGC 7000 Nordamerikanebel": (20.9800, 44.330),
    "IC 1396 Elefantenrüssel": (21.6500, 57.500),
    "NGC 6992 Cirrusnebel Ost": (20.9400, 31.720),
    "IC 1805 Herznebel": (2.5450, 61.450),
    "IC 1848 Seelennebel": (2.8500, 60.430),
}


# --------------------------------------------------------------------------
# Standort: Windows-Standortdienst · Seestar · Internet (IP) · manuell
# --------------------------------------------------------------------------
LOC_SOURCES = {
    "windows": ("Windows-Standortdienst", "genau (oft wenige Meter bis km); die Position bleibt auf deinem PC. "
                "Windows-Einstellung „Standort“ muss für Desktop-Apps erlaubt sein."),
    "seestar": ("Standort aus dem Seestar", "die Position, die die Seestar-App auf dem Handy im Teleskop gespeichert hat; "
                "wird nur aus deinem Seestar gelesen."),
    "internet": ("Ungefähr über die Internet-Adresse", "Genauigkeit meist Stadt/Region (ca. 5–50 km). Dabei wird deine "
                 "öffentliche IP-Adresse an einen Dienst (freeipapi.com bzw. ipwho.is) gesendet."),
}
if EDITION == "asiair":
    LOC_SOURCES.pop("seestar")                                  # ASIAIR-Ausgabe: kein Seestar vorhanden
IP_SERVICES = ("https://free.freeipapi.com/api/json/", "https://ipwho.is/")


def local_timezone_name():
    """IANA-Zeitzone des PCs (für die Uhrzeit am Seestar)."""
    try:
        import tzlocal
        n = tzlocal.get_localzone_name()
        if n:
            return n
    except Exception:
        pass
    off = datetime.now().astimezone().utcoffset()
    h = int(round(off.total_seconds() / 3600)) if off is not None else 0
    return "UTC" if h == 0 else f"Etc/GMT{'-' if h > 0 else '+'}{abs(h)}"     # Etc-Zonen haben umgekehrtes Vorzeichen


def parse_coord(text, is_lat):
    """'52.52', '52,52', '52°31'12\\" N', '13 24 0 O', '-0.12' -> Grad (Nord/Ost positiv)."""
    t = str(text).strip().upper().replace(",", ".")
    if not t:
        raise ValueError("leer")
    neg = t.startswith("-") or t.endswith(("S", "W"))
    if is_lat and t.endswith(("O", "E", "W")) or (not is_lat and t.endswith(("N", "S"))):
        raise ValueError("Himmelsrichtung passt nicht")
    for ch in "°'\"′″NSOEW+-":
        t = t.replace(ch, " ")
    try:
        parts = [float(x) for x in t.split()]
    except ValueError:
        raise ValueError("keine gültige Zahl") from None
    if not parts or len(parts) > 3:
        raise ValueError("Format")
    v = parts[0] + (parts[1] / 60 if len(parts) > 1 else 0) + (parts[2] / 3600 if len(parts) > 2 else 0)
    v = -v if neg else v
    if is_lat and not -90 <= v <= 90 or not is_lat and not -180 <= v <= 180:
        raise ValueError("außerhalb des gültigen Bereichs")
    return v


def fmt_dms(v, is_lat):
    hemi = ("N" if v >= 0 else "S") if is_lat else ("O" if v >= 0 else "W")
    a = abs(v)
    d = int(a)
    m = int((a - d) * 60)
    s_ = (a - d - m / 60) * 3600
    return f"{d}°{m:02d}′{s_:04.1f}″ {hemi}"


def locate_windows(timeout=20):
    """Position über den Windows-Standortdienst. -> (dict | None, Fehlertext)."""
    if sys.platform != "win32":
        return None, "nur unter Windows verfügbar"
    wdg = None
    for mod in ("winrt.windows.devices.geolocation", "winsdk.windows.devices.geolocation"):
        try:
            wdg = __import__(mod, fromlist=["Geolocator"])
            break
        except Exception:
            continue
    if wdg is None:
        return None, "Windows-Schnittstelle fehlt (pip install winrt-Windows.Devices.Geolocation)"

    async def run():
        try:
            st = await wdg.Geolocator.request_access_async()
            if int(st) == 2:                                   # GeolocationAccessStatus.DENIED
                return None, ("Zugriff verweigert – Windows-Einstellungen › Datenschutz › Standort: "
                              "„Desktop-Apps Zugriff auf den Standort erlauben“ einschalten")
        except Exception:
            pass                                               # ältere Windows-Versionen: direkt versuchen
        pos = await wdg.Geolocator().get_geoposition_async()
        c = pos.coordinate
        try:
            p = c.point.position
            lat, lon = p.latitude, p.longitude
        except Exception:
            lat, lon = c.latitude, c.longitude
        return {"lat": float(lat), "lon": float(lon), "acc_m": float(getattr(c, "accuracy", 0) or 0)}, ""

    try:
        import asyncio as _a
        return _a.run(_a.wait_for(run(), timeout))
    except Exception as e:
        msg = str(e) or type(e).__name__
        if "denied" in msg.lower() or "0x80070005" in msg:
            msg = "Zugriff verweigert – Windows-Standortdienst und Zugriff für Desktop-Apps einschalten"
        return None, f"Windows-Standort nicht verfügbar: {msg}"


def locate_internet(timeout=6):
    """Ungefähre Position über die öffentliche IP-Adresse. -> (dict | None, Fehlertext)."""
    import urllib.request
    last = ""
    for url in IP_SERVICES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": APP_ID})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode("utf-8", "ignore"))
            if d.get("success") is False:
                raise ValueError(d.get("message", "Dienst lehnt ab"))
            lat = d.get("latitude", d.get("lat"))
            lon = d.get("longitude", d.get("lon", d.get("lng")))
            if lat is None or lon is None or (float(lat) == 0 and float(lon) == 0):
                raise ValueError("keine Koordinaten")
            place = d.get("cityName") or d.get("city") or ""
            country = d.get("countryName") or d.get("country") or ""
            return {"lat": float(lat), "lon": float(lon), "acc_m": 25000.0,
                    "place": ", ".join(x for x in (place, country) if x)}, ""
        except Exception as e:
            last = f"{url.split('/')[2]}: {e}"
    return None, f"Internet-Abfrage fehlgeschlagen ({last})"


# --------------------------------------------------------------------------
# Astronomie-Hilfen (ohne Zusatzpakete)
# --------------------------------------------------------------------------
def julian_date(t=None):
    t = time.time() if t is None else t
    return t / 86400.0 + 2440587.5


def precess_j2000(ra_h, dec_deg, t=None):
    """J2000 -> mittleres Äquinoktium des Datums (IAU 1976). Das Seestar erwartet Koordinaten zum Datum."""
    T = (julian_date(t) - 2451545.0) / 36525.0
    a = math.radians
    zeta = a((2306.2181 * T + 0.30188 * T * T + 0.017998 * T ** 3) / 3600)
    z = a((2306.2181 * T + 1.09468 * T * T + 0.018203 * T ** 3) / 3600)
    th = a((2004.3109 * T - 0.42665 * T * T - 0.041833 * T ** 3) / 3600)
    ra0, d0 = a(ra_h * 15), a(dec_deg)
    A = math.cos(d0) * math.sin(ra0 + zeta)
    B = math.cos(th) * math.cos(d0) * math.cos(ra0 + zeta) - math.sin(th) * math.sin(d0)
    C = math.sin(th) * math.cos(d0) * math.cos(ra0 + zeta) + math.cos(th) * math.sin(d0)
    ra = (math.degrees(math.atan2(A, B) + z) / 15) % 24
    return ra, math.degrees(math.asin(max(-1, min(1, C))))


def lst_hours(lon_deg, t=None):
    jd = julian_date(t)
    T = (jd - 2451545.0) / 36525.0
    gmst = 280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * T * T - T ** 3 / 38710000
    return ((gmst + lon_deg) % 360) / 15


def alt_az(ra_h, dec_deg, lat, lon, t=None):
    """Höhe/Azimut (Grad, Azimut ab Nord über Ost) für J2000-Koordinaten."""
    ra, dec = precess_j2000(ra_h, dec_deg, t)
    H = math.radians((lst_hours(lon, t) - ra) * 15)
    la, de = math.radians(lat), math.radians(dec)
    sa = math.sin(la) * math.sin(de) + math.cos(la) * math.cos(de) * math.cos(H)
    alt = math.asin(max(-1, min(1, sa)))
    az = math.atan2(-math.cos(de) * math.sin(H), math.sin(de) * math.cos(la) - math.cos(de) * math.sin(la) * math.cos(H))
    return math.degrees(alt), math.degrees(az) % 360


def transit(ra_h, dec_deg, lat, lon, t=None):
    """Nächste Kulmination (Unix-Zeit) und Höhe dabei."""
    t = time.time() if t is None else t
    ra, dec = precess_j2000(ra_h, dec_deg, t)
    dh = (ra - lst_hours(lon, t)) % 24          # Sternzeit-Stunden bis zur Kulmination
    tt = t + dh * 3600 / 1.0027379
    return tt, 90 - abs(lat - dec)


def next_time_above(ra_h, dec_deg, lat, lon, min_alt, t=None, horizon_h=24):
    """Erste Zeit (Unix) innerhalb horizon_h, zu der das Objekt über min_alt steht; None wenn nie."""
    t = time.time() if t is None else t
    for k in range(int(horizon_h * 12) + 1):
        tk = t + k * 300
        if alt_az(ra_h, dec_deg, lat, lon, tk)[0] >= min_alt:
            return tk
    return None


# --------------------------------------------------------------------------
# Sonne, Mond, Dunkelheit (genau genug für Planung: ca. 0,3°)
# --------------------------------------------------------------------------
def _ecl_to_eq(lam, beta, jd):
    eps = math.radians(23.439 - 0.0000004 * (jd - 2451545.0))
    lam, beta = math.radians(lam), math.radians(beta)
    ra = math.atan2(math.sin(lam) * math.cos(eps) - math.tan(beta) * math.sin(eps), math.cos(lam))
    dec = math.asin(math.sin(beta) * math.cos(eps) + math.cos(beta) * math.sin(eps) * math.sin(lam))
    return (math.degrees(ra) / 15) % 24, math.degrees(dec)


def sun_ecl(t=None):
    n = julian_date(t) - 2451545.0
    L = (280.460 + 0.9856474 * n) % 360
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    return (L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)) % 360


def moon_ecl(t=None):
    T = (julian_date(t) - 2451545.0) / 36525
    sd = lambda a, b: math.sin(math.radians(a + b * T))
    lam = (218.32 + 481267.881 * T + 6.29 * sd(135.0, 477198.87) - 1.27 * sd(259.3, -413335.36)
           + 0.66 * sd(235.7, 890534.22) + 0.21 * sd(269.9, 954397.74) - 0.19 * sd(357.5, 35999.05)
           - 0.11 * sd(186.5, 966404.03)) % 360
    beta = (5.13 * sd(93.3, 483202.02) + 0.28 * sd(228.2, 960400.89) - 0.28 * sd(318.3, 6003.15)
            - 0.17 * sd(217.6, -407332.21))
    return lam, beta


def alt_az_date(ra_h, dec_deg, lat, lon, t=None):
    """Wie alt_az, aber für Koordinaten zum Datum (Sonne, Mond)."""
    H = math.radians((lst_hours(lon, t) - ra_h) * 15)
    la, de = math.radians(lat), math.radians(dec_deg)
    sa = math.sin(la) * math.sin(de) + math.cos(la) * math.cos(de) * math.cos(H)
    return math.degrees(math.asin(max(-1, min(1, sa))))


def sun_alt(lat, lon, t=None):
    ra, dec = _ecl_to_eq(sun_ecl(t), 0.0, julian_date(t))
    return alt_az_date(ra, dec, lat, lon, t)


def moon_info(lat, lon, t=None):
    """-> (Höhe °, beleuchteter Anteil 0..1, RA h, Dec ° zum Datum)."""
    lam, beta = moon_ecl(t)
    ra, dec = _ecl_to_eq(lam, beta, julian_date(t))
    elong = math.acos(max(-1, min(1, math.cos(math.radians(beta)) * math.cos(math.radians(lam - sun_ecl(t))))))
    return alt_az_date(ra, dec, lat, lon, t), (1 - math.cos(elong)) / 2, ra, dec


def ang_sep(ra1_h, dec1, ra2_h, dec2):
    a1, a2 = math.radians(ra1_h * 15), math.radians(ra2_h * 15)
    d1, d2 = math.radians(dec1), math.radians(dec2)
    c = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(a1 - a2)
    return math.degrees(math.acos(max(-1, min(1, c))))


def night_window(lat, lon, t=None, limit=-18.0):
    """Nächste Nacht: (Beginn, Ende) als Unix-Zeit, in der die Sonne unter `limit` steht.
    Nimmt notfalls -12° (nautisch), wenn es im Sommer nie astronomisch dunkel wird. -> (start, ende, grenze)"""
    t = time.time() if t is None else t
    base = datetime.fromtimestamp(t)
    noon = base.replace(hour=12, minute=0, second=0, microsecond=0)
    if base.hour < 12 and sun_alt(lat, lon, t) < -6:
        noon -= timedelta(days=1)                       # wir sind mitten in der Nacht
    t0 = noon.timestamp()
    for lim in (limit, -12.0, -6.0):
        start = end = None
        for k in range(0, 24 * 12 + 1):                 # 5-Minuten-Schritte über 24 h
            tk = t0 + k * 300
            dark = sun_alt(lat, lon, tk) < lim
            if dark and start is None:
                start = tk
            if start is not None and not dark:
                end = tk
                break
        if start is not None:
            return start, end or (t0 + 86400), lim
    return None, None, None


# --------------------------------------------------------------------------
# Wetter (Open-Meteo, kostenlos, ohne Schlüssel; Daten CC BY 4.0)
# --------------------------------------------------------------------------
WX_URL = "https://api.open-meteo.com/v1/forecast"
WX_FIELDS = ("cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high", "precipitation_probability",
             "precipitation", "temperature_2m", "dew_point_2m", "relative_humidity_2m", "wind_speed_10m",
             "wind_gusts_10m")


def fetch_weather(lat, lon, timeout=12):
    """Stündliche Vorhersage für 3 Tage. Koordinaten werden auf 0,01° (ca. 1 km) gerundet gesendet."""
    import urllib.request
    import urllib.parse
    q = urllib.parse.urlencode({"latitude": f"{lat:.2f}", "longitude": f"{lon:.2f}", "hourly": ",".join(WX_FIELDS),
                                "timezone": "auto", "forecast_days": 3, "timeformat": "unixtime",
                                "wind_speed_unit": "kmh"})
    req = urllib.request.Request(f"{WX_URL}?{q}", headers={"User-Agent": APP_ID})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8", "ignore"))
    h = d.get("hourly") or {}
    times = h.get("time") or []
    if not times:
        raise ValueError(d.get("reason") or "keine Daten")
    rows = []
    for i, tt in enumerate(times):
        rows.append({"t": float(tt), **{k: (h.get(k) or [None] * len(times))[i] for k in WX_FIELDS}})
    return {"rows": rows, "fetched": time.time(), "lat": lat, "lon": lon}


def wx_at(wx, t):
    """Wetterzeile zur Stunde von t (oder None)."""
    if not wx:
        return None
    best = None
    for r in wx["rows"]:
        if r["t"] <= t < r["t"] + 3600:
            return r
        if r["t"] <= t:
            best = r
    return best if best and t - best["t"] < 3 * 3600 else None


def night_summary(wx, lat, lon, t=None):
    """Zusammenfassung der nächsten Nacht aus Wetter + Sonne/Mond."""
    s0, s1, lim = night_window(lat, lon, t)
    if s0 is None:
        return None
    hours, clear, rain_max, dew_min, wind_max, best = [], 0.0, 0, None, 0, None
    tt = s0
    while tt < s1:
        r = wx_at(wx, tt)
        cc = r["cloud_cover"] if r and r.get("cloud_cover") is not None else None
        hours.append((tt, cc))
        if r:
            if cc is not None and cc <= 30:
                clear += 0.5
            rain_max = max(rain_max, r.get("precipitation_probability") or 0)
            if r.get("temperature_2m") is not None and r.get("dew_point_2m") is not None:
                gap = r["temperature_2m"] - r["dew_point_2m"]
                dew_min = gap if dew_min is None else min(dew_min, gap)
            wind_max = max(wind_max, r.get("wind_gusts_10m") or 0)
        tt += 1800
    run, start = 0, None
    for tt, cc in hours + [(None, 100)]:
        if cc is not None and cc <= 30:
            run, start = (run + 1, start if run else tt)
        else:
            if run and (best is None or run > best[2]):
                best = (start, start + run * 1800, run)
            run = 0
    mid = (s0 + s1) / 2
    malt, mill, _, _ = moon_info(lat, lon, mid)
    return {"start": s0, "end": s1, "limit": lim, "clear_h": clear, "best": best, "rain_max": rain_max,
            "dew_min": dew_min, "wind_max": wind_max, "moon_illum": mill, "moon_alt_mid": malt,
            "has_wx": bool(wx), "dark_h": (s1 - s0) / 3600}


# --------------------------------------------------------------------------
# Empfehlungen: was lohnt sich heute Nacht?
# --------------------------------------------------------------------------
EMISSION_TYPES = ("Emissionsnebel", "Supernovaüberrest", "Planetarischer Nebel", "Sternhaufen + Nebel", "Nebel")
# Bekannte Paradeobjekte für kleine Smart-Teleskope (hell, groß, lohnend) – bekommen einen Bonus
SHOWPIECES = {"M1", "M8", "M13", "M16", "M17", "M20", "M27", "M31", "M33", "M42", "M45", "M51", "M57", "M63", "M64",
              "M81", "M82", "M97", "M101", "M104", "M106", "M11", "M3", "M5", "M92", "M35", "M44", "M74", "M77",
              "M78", "M83", "M65", "M66", "M94", "NGC 7000", "IC 5070", "NGC 6960", "NGC 6992", "NGC 6888",
              "NGC 2237", "NGC 2244", "IC 1805", "IC 1848", "IC 1396", "NGC 2024", "Barnard 33", "IC 434", "IC 405",
              "NGC 281", "NGC 7635", "NGC 869", "NGC 884", "NGC 4565", "NGC 7293", "NGC 6543", "IC 2177", "NGC 1499",
              "IC 443", "NGC 2264", "NGC 7380", "NGC 2359", "NGC 3372", "IC 410", "NGC 1977", "NGC 7023", "NGC 891",
              "NGC 253", "NGC 55", "NGC 300", "NGC 5128", "NGC 104", "NGC 5139", "NGC 2070", "NGC 3628", "NGC 4631",
              "NGC 7331", "NGC 6946", "NGC 2403", "NGC 6826", "NGC 2392", "Caldwell 9", "IC 1318", "NGC 1333",
              "NGC 6914", "NGC 7822", "Sh2-155"}


def recommend(objects, lat, lon, model, wx=None, narrowband=False, min_alt=30, t=None, limit=25):
    """Bewertet alle Katalogobjekte für die nächste dunkle Nacht. -> Liste von dicts, beste zuerst."""
    s0, s1, lim = night_window(lat, lon, t)
    if s0 is None:
        return [], None
    m = MODELS.get(model or "S50", MODELS["S50"])
    step = 1800
    samples = []
    tt = s0
    while tt <= s1:
        r = wx_at(wx, tt)
        clear = 1.0 if not r or r.get("cloud_cover") is None else max(0.0, 1 - r["cloud_cover"] / 100) ** 1.5
        malt, mill, mra, mdec = moon_info(lat, lon, tt)
        samples.append((tt, clear, malt, mill, mra, mdec, lst_hours(lon, tt)))
        tt += step
    if not samples:
        return [], (s0, s1, lim)
    jd_mid = (s0 + s1) / 2
    la = math.radians(lat)
    # Wie stark stört der Mond in dieser Nacht insgesamt? (Beleuchtung × Anteil der Nacht über dem Horizont)
    moon_bright = sum(x[3] for x in samples if x[2] > 0) / len(samples)
    out = []
    for o in objects:
        oid, name, alias, typ, ra, dec, mag, size = o
        if 90 - abs(lat - dec) < min_alt:              # kulminiert nie hoch genug
            continue
        rn, dn = precess_j2000(ra, dec, jd_mid)
        de = math.radians(dn)
        good, score, alts, best_t, best_alt, msep_min = 0.0, 0.0, [], None, -90, 180
        for tt, clear, malt, mill, mra, mdec, lst in samples:
            H = math.radians((lst - rn) * 15)
            alt = math.degrees(math.asin(max(-1, min(1, math.sin(la) * math.sin(de) +
                                                       math.cos(la) * math.cos(de) * math.cos(H)))))
            alts.append(alt)
            if alt > best_alt:
                best_alt, best_t = alt, tt
            if alt < min_alt:
                continue
            moonf = 1.0
            if malt > 0:
                sep = ang_sep(rn, dn, mra, mdec)
                msep_min = min(msep_min, sep)
                pen = mill * max(0.0, 1 - sep / 90)           # nah + hell = schlecht
                moonf = 1 - (0.35 if narrowband else 0.85) * pen
            altf = min(1.0, 0.6 + (alt - min_alt) / 60)
            good += step / 3600 * clear
            score += step / 3600 * clear * moonf * altf
        if good < 0.75:
            continue
        deg = (size or 0) / 60
        is_em = any(typ.startswith(x) for x in EMISSION_TYPES)
        fit = 1.0
        if deg:
            if deg < m["fov_w"] * 0.08:
                fit = 0.45                                 # sehr klein im Bild
            elif deg < m["fov_w"] * 0.2:
                fit = 0.75
            elif deg > m["fov_h"] * 1.6:
                fit = 1.1 if oid in SHOWPIECES else 0.85   # nur als Mosaik (Paradeobjekte lohnen trotzdem)
        else:
            fit = 0.6
        if mag is not None and not is_em:
            fit *= 1.0 if mag <= 9 else (0.8 if mag <= 10.5 else 0.55)
        if narrowband:
            fit *= 1.25 if is_em else 0.35
        elif is_em and mag is None:
            fit *= 0.8                                     # lichtschwacher Nebel ohne Filter
        if moon_bright > 0.3 and (typ.startswith("Galax") or typ.startswith("Reflex")):
            fit *= 1 - 0.65 * moon_bright                  # heller Mond hellt den ganzen Himmel auf: Galaxien leiden
        if deg and m["fov_w"] * 0.2 <= deg <= m["fov_h"] * 1.0:
            fit *= 1.2                                     # füllt das Bildfeld gut
        if typ.startswith("Offener") and not name:
            fit *= 0.6
        if typ.startswith("Reflexion") and mag is None:
            fit *= 0.7
        if "Dwarf" in name or "Zwerg" in name:
            fit *= 0.35                                    # extrem lichtschwache Zwerggalaxien
        bonus = 1.6 if oid in SHOWPIECES else (1.2 if (name or re.match(r"M\d+$", oid)) else 0.8)
        total = score * fit * bonus
        hint = []
        if deg > m["fov_h"] * 0.9:
            nx = math.ceil(deg / (m["fov_w"] * 0.8))
            ny = max(1, math.ceil(deg / (m["fov_h"] * 0.8)))
            hint.append(f"größer als das Bildfeld – Mosaik {nx}×{ny}")
        elif deg and deg < m["fov_w"] * 0.15:
            hint.append("klein im Bild")
        if is_em:
            hint.append("ideal mit Schmalbandfilter" if not narrowband else "passt zum Schmalbandfilter")
        if msep_min < 30 and samples[len(samples) // 2][3] > 0.3:
            hint.append(f"Mond nur {msep_min:.0f}° entfernt")
        win = [samples[i][0] for i, a in enumerate(alts) if a >= min_alt]
        out.append({"o": o, "score": total, "good_h": good, "max_alt": best_alt, "best_t": best_t,
                    "from": win[0] if win else None, "to": (win[-1] + step) if win else None, "alts": alts,
                    "times": [x[0] for x in samples], "clear": [x[1] for x in samples],
                    "moon_sep": msep_min if msep_min < 180 else None, "hint": ", ".join(hint)})
    out.sort(key=lambda x: -x["score"])
    seen, uniq = set(), []
    for r in out:                                          # gleiche Objekte unter mehreren Katalognamen nur einmal
        key = r["o"][1] or r["o"][0]
        key = re.sub(r"\s*\(.*?\)|\s+[hχ]\b.*$", "", key)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq[:limit], (s0, s1, lim)


def auto_plan(recs, s0, s1, max_targets=4, min_alt=30):
    """Teilt die Nacht in Abschnitte und nimmt pro Abschnitt das beste Ziel, das dann hoch genug steht.
    -> [(rec, start, ende)]"""
    if not recs:
        return []
    n = max(1, min(max_targets, int(round((s1 - s0) / 3600 / 2.2))))      # etwa 2–2,5 h pro Ziel
    edges = [s0 + (s1 - s0) * k / n for k in range(n + 1)]
    used, plan = set(), []
    for a, b in zip(edges, edges[1:]):
        best, best_v = None, 0.0
        for r in recs:
            if id(r) in used:
                continue
            idx = [i for i, tt in enumerate(r["times"]) if a <= tt < b]
            if not idx:
                continue
            ok = [i for i in idx if r["alts"][i] >= min_alt]
            if len(ok) < max(1, len(idx) * 0.75):
                continue
            v = r["score"] * sum(r["clear"][i] * min(1.0, 0.6 + (r["alts"][i] - min_alt) / 60) for i in ok) / len(idx)
            if v > best_v:
                best, best_v = r, v
        if best:
            used.add(id(best))
            if plan and plan[-1][0] is best:
                plan[-1] = (best, plan[-1][1], b)
            else:
                plan.append((best, a, b))
    return plan


MONTHS = ("Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez")


def season_table(objects, lat, lon, min_alt=30, year=None):
    """Pro Objekt und Monat: Stunden in einer dunklen Nacht (Mitte des Monats) über min_alt – am Standort.
    Komplett offline gerechnet. -> {oid: [12 Werte]}"""
    year = year or datetime.now().year
    nights = []
    for m in range(1, 13):
        t = datetime(year, m, 15, 12, 0).timestamp()
        s0, s1, _lim = night_window(lat, lon, t)
        if s0 is None:
            nights.append([])
            continue
        samples, tt = [], s0
        while tt < s1:
            samples.append(lst_hours(lon, tt))
            tt += 1800
        nights.append(samples)
    la = math.radians(lat)
    sl, cl = math.sin(la), math.cos(la)
    out = {}
    for o in objects:
        ra, dec = o[4], o[5]
        de = math.radians(dec)
        sd, cd = math.sin(de), math.cos(de)
        if 90 - abs(lat - dec) < min_alt:
            out[o[0]] = [0.0] * 12
            continue
        thr = math.sin(math.radians(min_alt))
        row = []
        for samples in nights:
            n = 0
            for lst in samples:
                if sl * sd + cl * cd * math.cos(math.radians((lst - ra) * 15)) >= thr:
                    n += 1
            row.append(n * 0.5)
        out[o[0]] = row
    return out


def best_months(row):
    """„Okt–Feb“ aus den Monatsstunden (Monate mit mindestens 60 % der besten Zeit und ≥ 1,5 h)."""
    mx = max(row) if row else 0
    if mx < 1.5:
        return "–"
    good = [h >= max(1.5, 0.6 * mx) for h in row]
    if all(good):
        return tr("ganzjährig")
    start = next(i for i in range(12) if good[i] and not good[i - 1])
    parts, i = [], start
    for _ in range(12):
        if good[i] and not good[i - 1]:
            j = i
            while good[(j + 1) % 12] and (j + 1) % 12 != i:
                j = (j + 1) % 12
            parts.append(tr(MONTHS[i]) if i == j else f"{tr(MONTHS[i])}–{tr(MONTHS[j])}")
        i = (i + 1) % 12
    return ", ".join(parts)


WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def wd(t):
    """Wochentag kurz (unabhängig von der Spracheinstellung des Systems; wird mit übersetzt)."""
    return WEEKDAYS[datetime.fromtimestamp(t).weekday()]


def load_catalog_extra():
    """Erweiterung aus den Siril-Katalogen (NGC/IC vollständig, Sh2, LDN) – nur über die Suche erreichbar,
    damit Listen, Empfehlungen und Jahreszeiten bei den gut machbaren Zielen bleiben."""
    try:
        return json.loads(Path(__file__).with_name("catalog.json").read_text(encoding="utf-8")).get("extra", [])
    except Exception:
        return []


def obj_label(o):
    """Anzeige in Auswahllisten: 'M31 – Andromedagalaxie' bzw. 'Sh2-101'."""
    return f"{o[0]} – {o[1]}" if o[1] else o[0]


def obj_search(objects, q, limit=300):
    """Objekte, deren Kennung/Name/Alias den Suchtext enthält (Leerzeichen egal); exakte Kennung zuerst."""
    q = (q or "").strip().lower().replace(" ", "")
    if not q:
        return list(objects[:limit])
    exact, rest = [], []
    for o in objects:
        oid = o[0].lower().replace(" ", "")
        if oid == q:
            exact.append(o)
        elif q in (oid + o[1] + o[2]).lower().replace(" ", ""):
            rest.append(o)
            if len(rest) >= limit:
                break
    return exact + rest


def load_catalog():
    p = Path(__file__).with_name("catalog.json")
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d["objects"]
    except Exception:
        return [[k.split(" ")[0] if not k.startswith(("NGC", "IC")) else " ".join(k.split(" ")[:2]),
                 " ".join(k.split(" ")[1:]), "", "", v[0], v[1], None, 0] for k, v in CATALOG.items()]


# --------------------------------------------------------------------------
# WLAN-Client (JSON-RPC über TCP)
# --------------------------------------------------------------------------
class SeestarWifi:
    def __init__(self, log, on_event, on_state):
        self.log = log
        self.on_event = on_event
        self.on_state = on_state
        self.sock = None
        self.host = None
        self.cmdid = 10000
        self.lock = threading.Lock()
        self.pending = {}          # id -> (Event, [Antwort])
        self.running = False
        self.recv_thread = None
        self.hb_thread = None
        self.pem_path = ""
        self.on_connected = None
        self.last_rx = 0.0
        self.silence_limit = 45          # s ohne jede Antwort -> Verbindung gilt als tot
        self.guard = None                # guard(method, params) -> False = Befehl blockieren

    # ---- Discovery -------------------------------------------------------
    last_scan = {}                       # Diagnose der letzten Suche (lokale Adressen, Weg)

    @staticmethod
    def local_ipv4s():
        """Alle IPv4-Adressen dieses PCs (ohne Loopback/APIPA) – WLAN, LAN, Seestar-Hotspot …"""
        ips = set()
        try:
            for fam, _, _, _, sa in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                ips.add(sa[0])
        except OSError:
            pass
        for probe in ("10.0.0.1", "192.168.1.1", "8.8.8.8"):  # Route-Trick, sendet nichts
            try:
                t = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                t.connect((probe, 9))
                ips.add(t.getsockname()[0])
                t.close()
            except OSError:
                pass
        return sorted(ip for ip in ips if not ip.startswith(("127.", "169.254.", "0.")))

    @staticmethod
    def discover(timeout: float = 2.5):
        """Seestar suchen: 1) UDP-Broadcast über JEDE Netzwerkkarte (nicht nur die Standardkarte),
        mehrfach gesendet; 2) findet das nichts (z. B. Firewall blockt die UDP-Antwort), werden die
        lokalen Netze nach offenem Steuerport 4700 abgesucht (TCP, wird von der Firewall nicht geblockt)."""
        import select
        found = {}
        local = SeestarWifi.local_ipv4s()
        msg = json.dumps({"id": 1, "method": "scan_iscope", "params": ""}).encode()
        socks = []
        for ip in local + [""]:
            try:
                s_ = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s_.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s_.bind((ip, 0))
                s_.setblocking(False)
                socks.append((s_, ip))
            except OSError:
                pass
        try:
            end = time.time() + timeout
            nxt = 0.0
            while time.time() < end:
                if time.time() >= nxt:                       # 3× senden: UDP geht gern verloren
                    for s_, ip in socks:
                        targets = {"255.255.255.255"}
                        if ip:
                            targets.add(ip.rsplit(".", 1)[0] + ".255")
                        for tgt in targets:
                            try:
                                s_.sendto(msg, (tgt, DISCOVERY_PORT))
                            except OSError:
                                pass
                    nxt = time.time() + timeout / 3
                r, _, _ = select.select([s_ for s_, _ in socks], [], [], 0.2) if socks else ([], [], [])
                for s_ in r:
                    try:
                        data, addr = s_.recvfrom(4096)
                    except OSError:
                        continue
                    if addr[0] in local:
                        continue                              # eigenes Paket
                    try:
                        found[addr[0]] = json.loads(data.decode(errors="ignore"))
                    except Exception:
                        found[addr[0]] = {}
        finally:
            for s_, _ in socks:
                s_.close()
        via = "UDP"
        if not found:
            via = "TCP-Suche"
            found = SeestarWifi.tcp_sweep(local)
        SeestarWifi.last_scan = {"local": local, "via": via if found else "–"}
        return found

    @staticmethod
    def tcp_sweep(local, port=None, timeout=0.4):
        """Ersatzsuche: alle Adressen der lokalen /24-Netze auf offenen Steuerport prüfen (parallel, ~2 s)."""
        from concurrent.futures import ThreadPoolExecutor
        port = port or RPC_PORT
        nets = []
        for ip in local:
            n = ip.rsplit(".", 1)[0]
            if n not in nets:
                nets.append(n)
        hosts = [f"{n}.{i}" for n in nets[:4] for i in range(1, 255) if f"{n}.{i}" not in local]
        def probe(h):
            try:
                with socket.create_connection((h, port), timeout=timeout):
                    return h
            except OSError:
                return None
        with ThreadPoolExecutor(max_workers=128) as ex:
            return {h: {} for h in ex.map(probe, hosts) if h}

    # ---- Verbindung ------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self.sock is not None and self.running

    def connect(self, host: str, pem_path: str = "") -> bool:
        self.disconnect()
        self.host = host
        self.pem_path = pem_path
        try:
            self.sock = socket.create_connection((host, RPC_PORT), timeout=5)
            self.sock.settimeout(1.0)
        except Exception as e:
            self.sock = None
            self.log(f"Verbindung zu {host}:{RPC_PORT} fehlgeschlagen: {e}", "err")
            return False
        self.running = True
        self.last_rx = time.time()
        self.recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self.recv_thread.start()
        self.log(f"TCP-Verbindung zu {host}:{RPC_PORT} steht.", "ok")

        if pem_path:
            self.authenticate()
        else:
            self.log("Kein PEM-Schlüssel gesetzt – bei Firmware ab ca. 7.18 werden "
                     "Befehle ohne Anmeldung evtl. abgelehnt.", "warn")

        self.hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.hb_thread.start()
        self.on_state(True)
        if self.on_connected:
            self.on_connected()
        return True

    def disconnect(self):
        was = self.running
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None
        for ev, _ in list(self.pending.values()):
            ev.set()
        self.pending.clear()
        if was:
            self.log("Verbindung getrennt.", "warn")
            self.on_state(False)

    # ---- Senden / Empfangen ----------------------------------------------
    def _next_id(self) -> int:
        with self.lock:
            self.cmdid += 1
            return self.cmdid

    def send(self, method: str, params=None, wait: bool = True, timeout: float = 10.0, quiet=False):
        if not self.connected:
            self.log("Nicht verbunden.", "err")
            return None
        if self.guard and not self.guard(method, params):
            return None
        cid = self._next_id()
        msg = {"id": cid, "method": method}
        if params is not None:
            msg["params"] = params
        payload = json.dumps(msg) + "\r\n"
        ev, box = threading.Event(), []
        if wait:
            self.pending[cid] = (ev, box)
        try:
            with self.lock:
                self.sock.sendall(payload.encode())
        except Exception as e:
            self.log(f"Senden fehlgeschlagen: {e}", "err")
            self.pending.pop(cid, None)
            self.disconnect()
            return None
        if not quiet:
            self.log(f"→ {json.dumps(msg, ensure_ascii=False)}", "tx")
        if not wait:
            return None
        ev.wait(timeout)
        self.pending.pop(cid, None)
        if not box:
            if not quiet:
                self.log(f"Keine Antwort auf {method} (Timeout {timeout}s)", "warn")
            return None
        resp = box[0]
        if not quiet:
            code = resp.get("code", 0)
            tag = "rx" if code in (0, None) and "error" not in resp else "err"
            self.log(f"← {json.dumps(resp, ensure_ascii=False)[:600]}", tag)
        return resp

    def _recv_loop(self):
        buf = ""
        while self.running and self.sock:
            try:
                chunk = self.sock.recv(65536)
                if not chunk:
                    self.log("Seestar hat die Verbindung geschlossen.", "err")
                    break
                buf += chunk.decode(errors="ignore")
                self.last_rx = time.time()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.log(f"Empfangsfehler: {e}", "err")
                break
            while "\r\n" in buf:
                line, buf = buf.split("\r\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if "Event" in obj:
                    self.on_event(obj)
                elif "id" in obj and obj["id"] in self.pending:
                    ev, box = self.pending[obj["id"]]
                    box.append(obj)
                    ev.set()
        if self.running:
            self.disconnect()

    def _heartbeat_loop(self):
        while self.running:
            for _ in range(50):
                if not self.running:
                    return
                time.sleep(0.1)
            if time.time() - self.last_rx > self.silence_limit:
                self.log(f"Seit {self.silence_limit} s keine Antwort – Verbindung gilt als unterbrochen.", "err")
                self.disconnect()
                return
            self.send("test_connection", wait=False, quiet=True)

    # ---- Anmeldung (Firmware 6.45+ / 7.18+) --------------------------------
    def authenticate(self) -> bool:
        if not HAVE_CRYPTO:
            self.log("Paket 'cryptography' fehlt – pip install cryptography", "err")
            return False
        try:
            key = serialization.load_pem_private_key(Path(self.pem_path).read_bytes(), password=None)
        except Exception as e:
            self.log(f"PEM-Schlüssel konnte nicht geladen werden: {e}", "err")
            return False
        resp = self.send("get_verify_str", timeout=12)
        challenge = ""
        if isinstance(resp, dict) and isinstance(resp.get("result"), dict):
            challenge = resp["result"].get("str", "")
        if not challenge:
            self.log("Keine Anmelde-Challenge erhalten (Seestar beschäftigt oder alte Firmware).", "warn")
            return False
        sig = key.sign(challenge.encode(), padding.PKCS1v15(), hashes.SHA1())
        resp = self.send("verify_client", {"sign": base64.b64encode(sig).decode(), "data": challenge}, timeout=12)
        ok = False
        if isinstance(resp, dict):
            res = resp.get("result", resp.get("code", -1))
            if res == 0 or (isinstance(res, dict) and "key_envelope" in res and resp.get("code", 0) == 0):
                ok = True
        self.log("Anmeldung erfolgreich." if ok else f"Anmeldung fehlgeschlagen: {resp}", "ok" if ok else "err")
        return ok


# --------------------------------------------------------------------------
# ZWO ASIAIR (Mini, Plus, Pro und Kameras mit eingebautem Air, z. B. ASI585MC Air)
# Protokoll nach der Community-Dokumentation github.com/cpius/air-control (MIT):
#   TCP 4700 – Kamera, Sequenzen, Plate Solve, Autofokus (RSA-Anmeldung ab Firmware 7.18,
#              eigener Schlüssel aus der ASIAIR-App, NICHT der Seestar-Schlüssel)
#   TCP 4400 – Montierung und Guiding (ohne Anmeldung)
# Koordinaten an das Air immer „zum Datum“ (JNow), nicht J2000.
# --------------------------------------------------------------------------
AIR_PORT_MAIN = 4700
AIR_PORT_MOUNT = 4400
AIR_MODELS = ("ASIAIR Mini", "ASIAIR Plus", "ASIAIR Pro", "ASI585MC Air", "ASI585MM Air",
              "ASI2600MC Air", "ASI2600MM Air")
AIR_SETTLE = {"pixels": 1.5, "time": 10, "timeout": 60}            # PHD2-Beruhigung nach Guiding-Start
AIR_END_ACTIONS = {"none": "Nichts (Nachführung läuft weiter)", "track_off": "Nachführung aus",
                   "park": "Montierung parken"}
AIR_GUIDE_OK = ("Guiding",)
AIR_MOUNT_MODES = {"eq": "parallaktisch (EQ)", "altaz": "azimutal (Alt-Az)"}
REMOTE_PERMS = {"full": "volle Steuerung", "view": "nur zuschauen"}


def air_ok(resp):
    return isinstance(resp, dict) and "error" not in resp and resp.get("code", 0) in (0, None)


def air_result(resp, default=None):
    return resp.get("result", default) if isinstance(resp, dict) else default


def hour_angle(ra_jnow_h, lon_deg, t=None):
    """Stundenwinkel in Stunden (-12 … +12); positiv = Objekt hat den Meridian schon überschritten."""
    return ((lst_hours(lon_deg, t) - ra_jnow_h + 12) % 24) - 12


def sun_sep(ra_j2000, dec_j2000, t=None):
    """Winkelabstand (°) eines J2000-Ziels zur Sonne – Schutz beim Tagestest."""
    sra, sdec = _ecl_to_eq(sun_ecl(t), 0.0, julian_date(t))
    ra, dec = precess_j2000(ra_j2000, dec_j2000, t)
    return ang_sep(ra, dec, sra, sdec)


AIR_SUN_MIN = 45                                                   # Grad Mindestabstand zur Sonne am Tag


class AirChannel(SeestarWifi):
    """Eine JSON-RPC-Verbindung zum ASIAIR (Port 4700 oder 4400). Nutzt Senden/Antworten von SeestarWifi,
    hat aber eigenen Port, Zeilenende „\\n“, eigene Anmeldung und einen schnelleren Herzschlag
    (Port 4400 trennt still nach ca. 15 s ohne Verkehr)."""

    def __init__(self, port, log, on_event, on_state):
        super().__init__(log, on_event, on_state)
        self.port = port
        self.silence_limit = 40

    def connect(self, host, pem_path="", quiet=False):
        self.disconnect()
        self.host, self.pem_path = host, pem_path
        try:
            self.sock = socket.create_connection((host, self.port), timeout=8)       # unterwegs (VPN) etwas mehr Zeit
            self.sock.settimeout(1.0)
        except Exception as e:
            self.sock = None
            if not quiet:
                self.log(f"ASIAIR: Port {self.port} nicht erreichbar ({e}).", "err")
            return False
        self.running = True
        self.last_rx = time.time()
        self.recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self.recv_thread.start()
        if pem_path:
            self.authenticate()
        self.hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.hb_thread.start()
        self.on_state(True)
        return True

    def disconnect(self):
        was = self.running
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None
        for ev, _ in list(self.pending.values()):
            ev.set()
        self.pending.clear()
        if was:
            self.on_state(False)

    def _recv_loop(self):
        buf = ""
        while self.running and self.sock:
            try:
                chunk = self.sock.recv(65536)
                if not chunk:
                    if self.running:
                        self.log(f"ASIAIR hat die Verbindung (Port {self.port}) geschlossen.", "warn")
                    break
                buf += chunk.decode(errors="ignore")
                self.last_rx = time.time()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.log(f"ASIAIR: Empfangsfehler ({e}).", "err")
                break
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if isinstance(obj, dict) and "Event" in obj:
                    self.on_event(obj)
                elif isinstance(obj, dict) and obj.get("id") in self.pending:
                    ev, box = self.pending[obj["id"]]
                    box.append(obj)
                    ev.set()
        if self.running:
            self.disconnect()

    def send(self, method, params=None, wait=True, timeout=15.0, quiet=False):
        if params is None:
            params = []
        return super().send(method, params, wait=wait, timeout=timeout, quiet=quiet)

    def _heartbeat_loop(self):
        while self.running:
            for _ in range(50):
                if not self.running:
                    return
                time.sleep(0.1)
            if time.time() - self.last_rx > self.silence_limit:
                self.log(f"ASIAIR antwortet seit {self.silence_limit} s nicht (Port {self.port}).", "err")
                self.disconnect()
                return
            self.send("test_connection", wait=False, quiet=True)

    def authenticate(self):
        """RSA-Anmeldung: get_verify_str → signieren (PKCS#1 v1.5 / SHA-1) → verify_client([Signatur, Challenge])."""
        if not HAVE_CRYPTO:
            self.log("Paket 'cryptography' fehlt – pip install cryptography", "err")
            return False
        try:
            key = serialization.load_pem_private_key(Path(self.pem_path).read_bytes(), password=None)
        except Exception as e:
            self.log(f"PEM-Schlüssel konnte nicht geladen werden: {e}", "err")
            return False
        resp = self.send("get_verify_str", timeout=12, quiet=True)
        challenge = (air_result(resp) or {}).get("str", "") if isinstance(air_result(resp), dict) else ""
        if not challenge:
            self.log("ASIAIR: keine Anmelde-Challenge erhalten (ältere Firmware braucht keine Anmeldung).", "warn")
            return False
        sig = base64.b64encode(key.sign(challenge.encode(), padding.PKCS1v15(), hashes.SHA1())).decode()
        self.send("verify_client", [sig, challenge], timeout=12, quiet=True)
        ok = bool(air_result(self.send("pi_is_verified", timeout=12, quiet=True)))
        self.log("ASIAIR: Anmeldung erfolgreich." if ok else
                 "ASIAIR: Anmeldung abgelehnt – passt der Schlüssel aus der ASIAIR-App?", "ok" if ok else "err")
        return ok


class AirRig:
    """Ein ASIAIR mit Montierung: zwei Kanäle, Ereignisse, Warten auf Ereignisse und ein gemeinsamer Zustand."""

    def __init__(self, log, on_change):
        self.log = log
        self.on_change = on_change                 # Oberfläche neu zeichnen (wird aus Threads aufgerufen)
        self.main = AirChannel(AIR_PORT_MAIN, log, lambda o: self._event(4700, o), self._chan_state)
        self.mount = AirChannel(AIR_PORT_MOUNT, log, lambda o: self._event(4400, o), self._chan_state)
        self.host = ""
        self.pem = ""
        self.auto_reconnect = True            # nach Verbindungsabbruch selbst neu verbinden (wichtig unterwegs)
        self._want = False                    # Nutzer möchte verbunden sein
        self._busy = threading.Lock()
        self._rc_thread = None
        self.lost_since = None
        self.model = AIR_MODELS[3]
        self._waiters = []
        self._wlock = threading.Lock()
        self.state = {}                            # ra, dec, alt, az, tracking, pier, guide, seq_frame, seq_total …
        self.poll_thread = None
        self.event_hooks = []                      # z. B. Heimstation: Ereignisse an Ferngeräte weitergeben
        self.quiet_events = False
        self.remote = False

    @property
    def connected(self):
        return self.main.connected and self.mount.connected

    # ---- Verbindung --------------------------------------------------------
    def connect(self, host, pem="", quiet=False):
        with self._busy:
            self.host, self.pem = host, pem
            self._want = True
            ok1 = self.main.connect(host, pem, quiet=quiet)
            ok2 = ok1 and self.mount.connect(host, quiet=quiet)
            if not (ok1 and ok2):
                self.main.disconnect()
                self.mount.disconnect()
                self.on_change()
                return False
            self.lost_since = None
            self.call(4400, "scope_get_info", quiet=True)      # erstes Lesen auf neuem Socket ist laut Doku oft falsch
            if not self.poll_thread or not self.poll_thread.is_alive():
                self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
                self.poll_thread.start()
            return True

    def disconnect(self):
        """Vom Nutzer gewollt: trennen und NICHT selbst neu verbinden."""
        self._want = False
        self.main.disconnect()
        self.mount.disconnect()
        self.on_change()

    def _chan_state(self, up):
        self.on_change()
        if up or not self._want or not self.auto_reconnect or self._busy.locked():
            return
        if self.lost_since is None:
            self.lost_since = time.time()
            self.log("ASIAIR: Verbindung unterbrochen – versuche automatisch neu zu verbinden …", "warn")
        if not self._rc_thread or not self._rc_thread.is_alive():
            self._rc_thread = threading.Thread(target=self._reconnect_loop, daemon=True)
            self._rc_thread.start()

    def _reconnect_loop(self):
        tries = 0
        while self._want and self.auto_reconnect and not self.connected:
            time.sleep(5 if tries == 0 else 20)
            if not self._want:
                return
            tries += 1
            since = self.lost_since or time.time()
            if self.connect(self.host, self.pem, quiet=True):
                gone = int(time.time() - since)
                self.lost_since = None
                self.log(f"ASIAIR: wieder verbunden (nach {gone} s).", "ok")
                self.refresh()
                return

    def call(self, port, method, params=None, timeout=15.0, quiet=False):
        ch = self.main if port == AIR_PORT_MAIN else self.mount
        return ch.send(method, params if params is not None else [], timeout=timeout, quiet=quiet)

    def ok(self, port, method, params=None, timeout=15.0, quiet=False):
        return air_ok(self.call(port, method, params, timeout, quiet))

    # ---- Ereignisse -----------------------------------------------------------
    def _event(self, port, obj):
        name = obj.get("Event", "")
        st = self.state
        if name == "Sequence":
            if obj.get("state") == "frame_complete" and "frame" in obj:
                st["seq_frame"] = obj.get("frame")
            if "total_frame" in obj:
                st["seq_total"] = obj.get("total_frame")
            st["seq_state"] = obj.get("state", "")
        elif name in ("AutoGoto", "AutoGotoStep"):
            st["goto"] = obj.get("state", "")
        for h in self.event_hooks:
            try:
                h(port, obj)
            except Exception:
                pass
        quiet_seq = (name == "Sequence" and obj.get("state") == "frame_start") or name == "Exposure" or self.quiet_events
        if not quiet_seq and name not in ("PiStatus", "Temperature", "GuideStep", "AutoGoto_Step_Info", "Version",
                                          "LockPositionSet"):
            short = {k: v for k, v in obj.items() if k not in ("Event", "Timestamp", "route")}
            self.log(f"ASIAIR ⚡ {name} {json.dumps(short, ensure_ascii=False)[:160]}", "ev")
        with self._wlock:
            for w in list(self._waiters):
                try:
                    if w[0](obj):
                        w[2].append(obj)
                        w[1].set()
                except Exception:
                    pass
        self.on_change()

    def waiter(self, pred):
        """Vor dem auslösenden Befehl anlegen, dann mit wait() abholen – so geht kein schnelles Ereignis verloren."""
        w = (pred, threading.Event(), [])
        with self._wlock:
            self._waiters.append(w)
        return w

    def wait(self, w, timeout, stop=None):
        end = time.time() + timeout
        try:
            while time.time() < end:
                if w[1].wait(1.0):
                    return w[2][0]
                if stop and stop():
                    return None
                if not self.connected:
                    return None
            return None
        finally:
            with self._wlock:
                if w in self._waiters:
                    self._waiters.remove(w)

    # ---- Zustand regelmäßig lesen (hält zugleich Port 4400 wach) ----------
    def _poll_loop(self):
        while True:
            if not self.connected:
                time.sleep(1)
                if not self._want:
                    return
                continue
            self.refresh()
            time.sleep(4)

    def refresh(self):
        st = self.state
        r = air_result(self.call(4400, "scope_get_ra_dec", quiet=True))
        if isinstance(r, (list, tuple)) and len(r) >= 2:
            st["ra"], st["dec"] = float(r[0]), float(r[1])
        r = air_result(self.call(4400, "scope_get_horiz_coord", quiet=True))
        if isinstance(r, (list, tuple)) and len(r) >= 2:
            st["alt"], st["az"] = float(r[0]), float(r[1])
        r = air_result(self.call(4400, "scope_get_track_state", quiet=True))
        if isinstance(r, bool):
            st["tracking"] = r
        r = air_result(self.call(4400, "scope_get_info", quiet=True))
        if isinstance(r, dict):
            for k in ("pier_side", "PierSide", "pierside"):
                if k in r:
                    st["pier"] = r[k]
        r = air_result(self.call(4400, "get_app_state", quiet=True))
        if isinstance(r, str):
            st["guide"] = r
        self.on_change()

    def guide_state(self):
        r = air_result(self.call(4400, "get_app_state", quiet=True))
        return r if isinstance(r, str) else ""

    # ---- Bausteine für Plan und Flip -----------------------------------------
    def send_time_location(self, lat, lon):
        """Zeit (UTC + Standardzeit-Versatz) und Standort senden und nachprüfen. Laut Doku setzt das Air den
        Standort nach dem Anmelden der Montierung manchmal verzögert auf 0/0 zurück – darum mehrfach prüfen."""
        off = -time.timezone / 3600
        self.call(4400, "scope_set_time", [datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"), f"{off:.2f}"])
        for k in range(4):
            self.call(4400, "scope_set_location", [round(lat, 5), round(lon, 5)])
            time.sleep(8 if k < 3 else 2)
            r = air_result(self.call(4400, "scope_get_location", quiet=True))
            if isinstance(r, (list, tuple)) and len(r) >= 2 and abs(float(r[0]) - lat) < 0.01 \
                    and abs(float(r[1]) - lon) < 0.01:
                if k >= 1:
                    self.log("ASIAIR: Zeit und Standort gesendet und bestätigt.", "ok")
                    return True
        self.log("ASIAIR: Standort wurde nicht bestätigt – bitte in der ASIAIR-App prüfen.", "warn")
        return False

    def attach_mount(self):
        r = self.call(4400, "set_connected", [{"mount": True}], timeout=30)
        return air_ok(r)

    def goto(self, ra_j2000, dec_j2000, stop=None, timeout=420, solve=True):
        """GoTo mit Plate Solve und Zentrieren (wie die ASIAIR-App). Ein einzelner Fehlversuch (252) ist normal.
        solve=False (Tagestest): nur Montierung schwenken, ohne Bild und Plate Solve."""
        ra, dec = precess_j2000(ra_j2000, dec_j2000)
        if not solve:
            return self._goto_plain(ra, dec, stop)
        w = self.waiter(lambda o: o.get("Event") == "AutoGoto" and o.get("state") in ("complete", "fail"))
        r = self.call(4700, "start_auto_goto", [round(ra, 6), round(dec, 5)], timeout=20)
        if not air_ok(r):
            self.wait(w, 0)
            self.log(f"ASIAIR: GoTo abgelehnt: {r}", "err")
            return False
        ev = self.wait(w, timeout, stop)
        if ev is None:
            self.log("ASIAIR: GoTo – keine Rückmeldung (Zeitüberschreitung).", "err")
            return False
        if ev.get("state") != "complete":
            self.log(f"ASIAIR: GoTo fehlgeschlagen ({ev.get('error', '?')}, Code {ev.get('code', '?')}).", "err")
            return False
        return True

    def _goto_plain(self, ra, dec, stop=None, timeout=240):
        w = self.waiter(lambda o: o.get("Event") == "ScopeGoto" and o.get("state") in ("complete", "fail"))
        r = self.call(4400, "scope_goto", [round(ra, 6), round(dec, 5)], timeout=20)
        if not air_ok(r):
            self.wait(w, 0)
            self.log(f"ASIAIR: GoTo abgelehnt: {r}", "err")
            return False
        ev = self.wait(w, timeout, stop)
        if ev is not None and ev.get("state") == "fail":
            self.log(f"ASIAIR: GoTo fehlgeschlagen ({ev.get('error', '?')}, Code {ev.get('code', '?')}).", "err")
            return False
        if ev is None:                                   # kein Ereignis: Position prüfen
            p = air_result(self.call(4400, "scope_get_ra_dec", quiet=True))
            if not (isinstance(p, (list, tuple)) and len(p) >= 2 and ang_sep(float(p[0]), float(p[1]), ra, dec) < 1.0):
                self.log("ASIAIR: GoTo – keine Rückmeldung (Zeitüberschreitung).", "err")
                return False
        self.log("ASIAIR: Montierung steht auf dem Ziel (Tagestest, ohne Plate Solve).", "ok")
        return True

    def guide_start(self, recalibrate=False, stop=None, timeout=900):
        self.call(4400, "loop", timeout=20)
        time.sleep(4)
        r = self.call(4400, "guide", [dict(AIR_SETTLE), bool(recalibrate)], timeout=20)
        if not air_ok(r):
            r = self.call(4400, "guide", dict(AIR_SETTLE), timeout=20)            # ältere Form: nacktes Objekt
        if not air_ok(r):
            self.log(f"ASIAIR: Guiding-Start abgelehnt: {r}", "err")
            return False
        end = time.time() + timeout
        while time.time() < end:
            if stop and stop():
                return False
            s = self.guide_state()
            if s in AIR_GUIDE_OK:
                self.log("ASIAIR: Guiding läuft.", "ok")
                return True
            if s in ("Stopped", "LostLock", "Idle") and time.time() > end - timeout + 60:
                break
            time.sleep(5)
        self.log(f"ASIAIR: Guiding kam nicht zustande (Zustand: {self.guide_state() or '?'}).", "err")
        return False

    def guide_stop(self):
        self.call(4400, "stop_capture", timeout=15)

    def set_dither(self, every, pixels):
        """Dithering über den Sequenz-Läufer. Das Format ist nicht offiziell dokumentiert – vorhandene Felder werden
        angepasst, fehlende nicht erfunden."""
        cur = air_result(self.call(4700, "get_dither", quiet=True))
        if not isinstance(cur, dict):
            self.log("ASIAIR: Dithering-Einstellung nicht lesbar – bleibt wie in der ASIAIR-App eingestellt.", "warn")
            return False
        new = dict(cur)
        for k in ("enable", "enabled", "dither_enable"):
            if k in new:
                new[k] = every > 0
        for k in ("amount", "pixel", "pixels", "dither_pixel"):
            if k in new and every > 0:
                new[k] = pixels
        for k in ("interval", "every", "frequency", "dither_frequency", "frame"):
            if k in new and every > 0:
                new[k] = every
        if new == cur:
            return True
        if air_ok(self.call(4700, "set_dither", [new])) or air_ok(self.call(4700, "set_dither", new)):
            return True
        self.log("ASIAIR: Dithering konnte nicht gesetzt werden – bitte in der ASIAIR-App einstellen.", "warn")
        return False

    def sequence_start(self, name, exp, gain, count, filt=0, binning=1):
        """Aufnahmeserie über den Autorun-Läufer des Air (speichert auf dem Air und dithert)."""
        self.call(4700, "stop_exposure")
        time.sleep(1)
        self.call(4700, "set_page", ["autosave"])
        self.call(4700, "reset_sequence_progress", quiet=True)
        self.call(4700, "clear_sequence", quiet=True)
        seq = {"id": 1, "type": "light", "exp": int(exp), "gain": int(gain) if gain is not None else -10000,
               "bin": int(binning), "repeat": int(count), "filter": int(filt), "suffix": "", "enable": True,
               "autoexp": False, "capture_index": 1}
        steps = (("set_sequence", [seq]),
                 ("set_sequence_setting", [{"group_name": re.sub(r"[^\w\- ]", "_", name)[:40] or "Ziel",
                                            "mount_end_action": "none", "delay_first": 0, "delay_between_frame": 0,
                                            "delay_between_sequence": 0, "group_by_slot": True,
                                            "focuser_go_home": False, "caa_go_home": False, "shutdown_pi": False}]),
                 ("start_exposure", ["light"]))
        for m, p in steps:
            r = self.call(4700, m, p, timeout=20)
            if not air_ok(r):
                self.log(f"ASIAIR: {m} abgelehnt: {r}", "err")
                return False
            time.sleep(0.5)
        self.state.update(seq_frame=0, seq_total=int(count), seq_state="start")
        return True

    def sequence_stop(self):
        self.call(4700, "stop_exposure", timeout=15)

    # ---- Fokussierer (ZWO EAF) und Filterrad -----------------------------------
    def focuser_info(self):
        """-> dict mit position, temperature (°C, falls vorhanden), max_step – oder {}."""
        out = {}
        r = air_result(self.call(4700, "get_focuser_info", quiet=True))
        if isinstance(r, dict):
            for k in ("position", "temperature", "max_step", "is_moving", "moving"):
                if k in r:
                    out[k] = r[k]
        if "position" not in out:
            r = air_result(self.call(4700, "get_focuser_position", quiet=True))
            if isinstance(r, (int, float)):
                out["position"] = int(r)
            elif isinstance(r, dict) and "position" in r:
                out["position"] = int(r["position"])
        t = out.get("temperature")
        if isinstance(t, (int, float)) and (t < -60 or t > 80):          # -273 o. Ä. = kein Sensor
            out.pop("temperature")
        return out

    def focuser_pos(self):
        return self.focuser_info().get("position")

    def focuser_move(self, pos, stop=None, timeout=90):
        """Fokussierer auf pos fahren und warten, bis er steht."""
        pos = int(pos)
        r = self.call(4700, "move_focuser", [pos], timeout=20)
        if not air_ok(r):
            self.log(f"ASIAIR: Fokussierer reagiert nicht ({r}).", "err")
            return False
        end, last, same = time.time() + timeout, None, 0
        while time.time() < end:
            if stop and stop():
                return False
            time.sleep(0.7)
            p_ = self.focuser_pos()
            if p_ == pos:
                return True
            same = same + 1 if p_ == last else 0
            last = p_
            if same >= 6 and p_ is not None and abs(p_ - pos) <= 2:
                return True
        self.log(f"ASIAIR: Fokussierer hat {pos} nicht erreicht (steht bei {last}).", "warn")
        return False

    def wheel_move(self, slot, wait=25):
        """Filterrad auf Platz slot (1 …) drehen. Das Format ist nicht dokumentiert – zwei Varianten probieren."""
        if not slot:
            return True
        if not (air_ok(self.call(4700, "set_wheel_position", [int(slot)], timeout=20)) or
                air_ok(self.call(4700, "set_wheel_position", {"position": int(slot)}, timeout=20))):
            self.log(f"ASIAIR: Filterrad ließ sich nicht auf Platz {slot} drehen.", "warn")
            return False
        end = time.time() + wait
        while time.time() < end:
            time.sleep(1)
            r = air_result(self.call(4700, "get_wheel_position", quiet=True))
            if r == int(slot) or (isinstance(r, dict) and r.get("position") == int(slot)):
                return True
        return True                                       # Rückmeldung unklar – weiter, Bild zeigt es

    def autofocus(self, stop=None, timeout=900):
        w = self.waiter(lambda o: "Focus" in str(o.get("Event", "")) and o.get("state") in ("complete", "fail"))
        if not self.ok(4700, "start_auto_focuse", timeout=20):
            self.wait(w, 0)
            self.log("ASIAIR: Autofokus abgelehnt (kein elektronischer Fokussierer?).", "warn")
            return False
        ev = self.wait(w, timeout, stop)
        ok = bool(ev) and ev.get("state") == "complete"
        self.log("ASIAIR: Autofokus fertig." if ok else "ASIAIR: Autofokus ohne Erfolg – es geht trotzdem weiter.",
                 "ok" if ok else "warn")
        return ok



# --------------------------------------------------------------------------
# ASIAIR: Empfehlungen je Filter und eigener Autofokus (V-Kurve mit HFR-Messung)
# Hinweis aus der Community-Doku: das Air-eigene start_auto_focuse ohne Parameter misst nicht neu und kann die
# Kamera in einen Fehlerzustand bringen – darum misst dieses Programm selbst.
# --------------------------------------------------------------------------
AIR_AF_EXP = {1: 1.0, 2: 2.0, 3: 4.0, 4: 8.0}          # Autofokus-Belichtung (s) je Helligkeitsklasse
AIR_SUB_EXP = {1: 60, 2: 120, 3: 180, 4: 300}           # Einzelbild-Belichtung (s) bei parallaktischer Montierung
AIR_ALTAZ_MAX = 30                                      # s – darüber dreht sich das Bildfeld sichtbar (Alt-Az)


def air_filter_reco(fname, color=True, altaz=False):
    """Empfehlungen für einen Filter am ASIAIR. -> dict(exp, af_exp, light, notes[])"""
    f = FILTERS.get(fname) or FILTERS[NO_FILTER]
    kind, light = f.get("art"), int(f.get("light") or 1)
    notes = []
    if color and kind == LINE:
        light = min(4, light + 0)                       # schon in light_class berücksichtigt
    exp = AIR_SUB_EXP.get(light, 120)
    if kind in (IRP, SPEC, NDF):
        exp = 1
        notes.append("Für Mond/Planeten: sehr kurze Belichtungen (Millisekunden bis 1 s), besser als Video aufnehmen.")
    if altaz and exp > AIR_ALTAZ_MAX:
        notes.append(f"Alt-Az: höchstens ca. {AIR_ALTAZ_MAX} s pro Bild (Bildfelddrehung) – dafür mehr Bilder aufnehmen.")
        exp = AIR_ALTAZ_MAX
    if color and kind in (RGBF, PHOT):
        notes.append("Dieser Filter ist für Mono-Kameras gedacht – an der ASI585MC (Farbe) nicht sinnvoll.")
    if not color and kind in (DUAL, TRI, QUAD, UHC):
        notes.append("Mehrband-Filter an einer Mono-Kamera mischen die Linien – für Mono besser Einzellinien-Filter.")
    if kind in (DUAL, TRI, QUAD, LINE) and (f.get("nm") or 99) <= 4:
        notes.append("Sehr schmal (≤ 4 nm): bei schneller Optik (f/2–f/4) kann die Durchlasskurve wandern – "
                     "„Highspeed“-Versionen wählen.")
    if kind == CLEAR:
        notes.append("Klarglas im leeren Filterrad-Platz hält den Fokus gleich wie mit Filter (gleiche Glasdicke).")
    if kind in (DUAL, TRI, QUAD, LINE):
        notes.append("Schmalband ist am unempfindlichsten gegen Mondlicht und Lichtverschmutzung.")
    return {"exp": exp, "af_exp": AIR_AF_EXP.get(light, 2.0), "light": light, "kind": kind, "notes": notes,
            "hint": f.get("hinweis", ""), "band": f.get("band", "")}


def fit_vcurve(points):
    """Parabel durch die gemessenen Punkte (Position, HFR). -> beste Position oder None."""
    pts = [(p, h) for p, h in points if h]
    if len(pts) < 4:
        return None
    xs = np.array([p for p, _ in pts], dtype=float)
    ys = np.array([h for _, h in pts], dtype=float)
    k = int(np.argmin(ys))
    a, b, c = np.polyfit(xs, ys, 2)
    if a <= 0:
        return float(xs[k])
    best = -b / (2 * a)
    if not (xs.min() <= best <= xs.max()):              # Minimum außerhalb – am Rand: lieber bester Messpunkt
        return float(xs[k])
    return float(best)


class AirAutofocus:
    """Fokus-Kurve aufnehmen: Fokussierer in Schritten verfahren, auf der „focus“-Seite (Bildmitte 1:1, freilaufend)
    je Position ein frisches Bild holen, HFR messen, Parabel anpassen, Bestposition anfahren (immer von unten –
    gegen Spiel im Getriebe)."""

    def __init__(self, app, rig, exp, gain, step, n, backlash=0, log=None, on_point=None, stop=None):
        self.app, self.rig = app, rig
        self.exp, self.gain, self.step, self.n, self.backlash = float(exp), int(gain), int(step), int(n), int(backlash)
        self.log = log or app.log
        self.on_point = on_point or (lambda *a: None)
        self.stop = stop or (lambda: False)
        self.points = []
        self.best = None

    def _fresh(self, sig, tries=None):
        tries = tries or int(max(6, (self.exp + 1.5) / 0.4))
        for _ in range(tries):
            if self.stop():
                return None, sig
            got = self.app.air_img_raw()
            if got:
                hdr, payload = got
                s_ = hash(payload[::4001])
                if s_ != sig:
                    return (hdr, payload), s_
            time.sleep(0.4)
        return None, sig

    def run(self):
        rig = self.rig
        pos0 = rig.focuser_pos()
        if pos0 is None:
            self.log("Autofokus: kein Fokussierer gefunden (ZWO EAF am Air angeschlossen und verbunden?).", "err")
            return None
        self.log(f"Autofokus: Start bei {pos0}, {self.n} Positionen im Abstand {self.step}, Belichtung {self.exp:g} s.", "info")
        rig.call(4700, "stop_exposure")
        time.sleep(1)
        rig.call(4700, "set_page", ["focus"])
        rig.call(4700, "set_control_value", ["Exposure", int(self.exp * 1_000_000)])
        rig.call(4700, "set_control_value", ["Gain", self.gain])
        rig.call(4700, "start_exposure", quiet=True)
        sig = None
        try:
            bayer = self.app.cfg.get("air_bayer", "automatisch")
            center, best = pos0, None
            for rnd in range(3):                          # liegt das Minimum am Rand, Kurve verschieben (max. 2×)
                positions = [max(0, center + (k - self.n // 2) * self.step) for k in range(self.n)]
                if self.backlash:
                    rig.focuser_move(max(0, positions[0] - self.backlash), self.stop)
                for p_ in positions:
                    if self.stop():
                        break
                    if any(p_ == q for q, _ in self.points) or not rig.focuser_move(p_, self.stop):
                        continue
                    _, sig = self._fresh(sig)             # ein Bild verwerfen (begann evtl. vor der Bewegung)
                    got, sig = self._fresh(sig)
                    hfr, nstar = None, 0
                    if got:
                        try:
                            hfr, nstar = measure_hfr(air_decode(got[0], got[1], bayer))
                        except Exception:
                            hfr = None
                    self.points.append((p_, hfr))
                    self.on_point(p_, hfr, nstar)
                    self.log(f"Autofokus: {p_} → HFR {hfr:.2f} ({nstar} Sterne)" if hfr else
                             f"Autofokus: {p_} → keine Sterne messbar", "info")
                if self.stop():
                    break
                best = fit_vcurve(self.points)
                good = sorted(p_ for p_, h in self.points if h)
                if best is None or not good or (good[0] < best < good[-1]):
                    break
                center = int(best) + (-1 if best <= good[0] else 1) * (self.n // 2) * self.step
                self.log("Autofokus: Bestwert liegt am Rand der Kurve – messe weiter in diese Richtung.", "info")
            best = best if not self.stop() else None
            if best is None:
                self.log("Autofokus fehlgeschlagen (zu wenige Sterne gemessen) – Fokus zurück auf den Startwert.", "err")
                rig.focuser_move(pos0 - self.backlash if self.backlash else pos0, self.stop)
                if self.backlash:
                    rig.focuser_move(pos0, self.stop)
                return None
            best = int(round(best))
            if self.backlash:
                rig.focuser_move(best - self.backlash, self.stop)
            rig.focuser_move(best, self.stop)
            self.best = best
            hf = [h for _, h in self.points if h]
            self.log(f"Autofokus fertig: Position {best} (bester HFR {min(hf):.2f}).", "ok")
            return best
        finally:
            rig.call(4700, "stop_exposure")
            rig.call(4700, "set_page", ["preview"], quiet=True)

class AirPlanJob:
    """Führt einen ASIAIR-Plan aus: pro Ziel GoTo (Plate Solve) → Guiding → Aufnahmeserie,
    dabei Stundenwinkel überwachen und zur eingestellten Zeit nach dem Meridian automatisch flippen."""

    def __init__(self, rig, plan, opts, site, log, on_status):
        self.rig, self.plan, self.o, self.site = rig, plan, opts, site
        self.log, self.on_status = log, on_status
        self.cancel = False
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.flips = 0

    def start(self):
        self.thread.start()

    def alive(self):
        return self.thread.is_alive()

    def stop(self):
        self.cancel = True

    def _stopped(self):
        return self.cancel

    def _wait_link(self):
        """Bei Verbindungsabbruch auf die automatische Wiederverbindung warten (bis zu o['link_wait'] Minuten).
        Das Air nimmt die laufende Serie in der Zeit selbst weiter auf."""
        if self.rig.connected:
            return True
        limit = time.time() + 60 * float(self.o.get("link_wait", 15))
        while time.time() < limit and not self.cancel:
            self._status("Verbindung zum ASIAIR unterbrochen – warte auf Wiederverbindung")
            time.sleep(3)
            if self.rig.connected:
                time.sleep(2)
                return True
        return False

    def _status(self, text):
        self.on_status(text)

    def _sleep(self, secs):
        end = time.time() + secs
        while time.time() < end and not self._stopped():
            time.sleep(1)

    def _alt(self, t):
        return alt_az(t["ra"], t["dec"], self.site[0], self.site[1])[0]

    def _ha(self, t):
        ra, _ = precess_j2000(t["ra"], t["dec"])
        return hour_angle(ra, self.site[1])

    def _run(self):
        rig, o = self.rig, self.o
        self.log(f"ASIAIR-Plan gestartet: {len(self.plan)} Ziele.", "ok")
        self.log(f"Meridian-Flip: automatisch {o['flip_min']} min nach dem Meridian." if o["flip"] else
                 "Meridian-Flip: aus.", "info")
        try:
            for k, t in enumerate(self.plan, 1):
                if self._stopped():
                    break
                if not self._wait_link():
                    self.lost = True
                    break
                self._target(k, t)
                if getattr(self, "lost", False):
                    break
        except Exception as e:
            self.log(f"ASIAIR-Plan: unerwarteter Fehler: {e}", "err")
        finally:
            if getattr(self, "lost", False) and not self.cancel:
                self.log(f"ASIAIR-Plan beendet: Verbindung seit {self.o.get('link_wait', 15)} min weg. Das Air nimmt "
                         "die laufende Serie selbst zu Ende auf; weitere Ziele werden nicht angefahren.", "err")
            elif self.cancel:
                rig.sequence_stop()
                rig.guide_stop()
                rig.call(4700, "stop_auto_goto", quiet=True)
                self.log("ASIAIR-Plan abgebrochen.", "warn")
            elif rig.connected:
                end = o.get("end", "none")
                if o["guide"]:
                    rig.guide_stop()
                if end == "track_off":
                    rig.call(4400, "scope_set_track_state", [False])
                elif end == "park":
                    rig.call(4400, "scope_park", timeout=30)
                self.log(f"ASIAIR-Plan fertig ({self.flips} Meridian-Flip(s)).", "ok")
            self._status("")

    def _target(self, k, t):
        rig, o = self.rig, self.o
        name = t["name"]
        # 1) warten, bis das Ziel hoch genug steht
        if t.get("min_alt") is not None and self._alt(t) < t["min_alt"]:
            tt = next_time_above(t["ra"], t["dec"], self.site[0], self.site[1], t["min_alt"], horizon_h=8)
            if tt is None:
                self.log(f"{name}: erreicht heute die Mindesthöhe nicht – übersprungen.", "warn")
                return
            self.log(f"{name}: warte bis {datetime.fromtimestamp(tt):%H:%M} (Mindesthöhe {t['min_alt']}°).", "info")
            while time.time() < tt and not self._stopped():
                self._status(f"Ziel {k}/{len(self.plan)} · {name} · warte auf Mindesthöhe")
                time.sleep(5)
        if self._stopped():
            return
        # Sonnenschutz: am Tag nie in die Nähe der Sonne schwenken
        if sun_alt(*self.site) > -6 and sun_sep(t["ra"], t["dec"]) < AIR_SUN_MIN:
            self.log(f"{name}: weniger als {AIR_SUN_MIN}° von der Sonne entfernt – übersprungen.", "warn")
            return
        # 2) GoTo mit Plate Solve
        if o["guide"]:
            rig.guide_stop()
        self._status(f"Ziel {k}/{len(self.plan)} · {name} · GoTo mit Plate Solve")
        self.log(f"{name}: GoTo ohne Plate Solve (Tagestest) …" if o.get("daytest") else f"{name}: GoTo mit Plate Solve …", "info")
        solve = not o.get("daytest")
        if not (rig.goto(t["ra"], t["dec"], self._stopped, solve=solve) or
                (not self._stopped() and self._wait_link() and rig.goto(t["ra"], t["dec"], self._stopped, solve=solve))):
            self.log(f"{name}: GoTo nicht möglich – nächstes Ziel.", "err")
            return
        # Steht das Ziel beim Anfahren schon hinter dem Meridian, setzt die Montierung es bereits auf die
        # richtige Seite – dann ist für dieses Ziel kein Flip mehr nötig.
        flipped = self._ha(t) * 60 >= o["flip_min"]
        # 3) Guiding
        if o["guide"] and not rig.guide_start(recalibrate=False, stop=self._stopped):
            if not o.get("unguided_ok", True):
                self.log(f"{name}: ohne Guiding wird nicht aufgenommen – nächstes Ziel.", "err")
                return
            self.log(f"{name}: nehme ohne Guiding auf.", "warn")
        self._focus_for(t)
        # 4) Aufnahmeserie mit Flip-Überwachung
        done, total = 0, int(t["count"])
        if o.get("dither_every"):
            rig.set_dither(int(o["dither_every"]), float(o.get("dither_px", 5)))
        if not rig.sequence_start(name, t["exp"], t.get("gain"), total, t.get("filter", 0)):
            return
        stall_t, last_frame = time.time(), 0
        zen_warned = False
        while not self._stopped():
            if not rig.connected:
                if not self._wait_link():
                    self.lost = True
                    return
                stall_t = time.time()                        # Bildnummern kommen mit dem nächsten Ereignis wieder
            st = rig.state
            frame = int(st.get("seq_frame") or 0)
            if frame != last_frame:
                last_frame, stall_t = frame, time.time()
            cur = done + frame
            alt, ha = self._alt(t), self._ha(t)
            info = f"Ziel {k}/{len(self.plan)} · {name} · Bild {cur}/{total} · Höhe {alt:.0f}°"
            if o.get("altaz") and alt > o.get("zenith", 85) and not zen_warned:
                zen_warned = True
                self.log(f"{name}: steht über {o.get('zenith', 85)}° – im Alt-Az-Modus dreht die Montierung nahe dem "
                         "Zenit sehr schnell, Bilder können verwischen.", "warn")
            if o["flip"] and not flipped:
                left = o["flip_min"] - ha * 60
                info += f" · Flip in {math.ceil(left)} min" if left > 0 else " · Flip jetzt"
            self._status(info)
            if cur >= total or str(st.get("seq_state", "")).lower() in ("complete", "finish", "finished", "end"):
                self.log(f"{name}: {total} Bilder fertig.", "ok")
                break
            if t.get("min_alt") is not None and alt < t["min_alt"] - 2:
                self.log(f"{name}: unter die Mindesthöhe gesunken – Serie beendet ({cur}/{total}).", "warn")
                rig.sequence_stop()
                break
            if o["flip"] and not flipped and ha * 60 >= o["flip_min"]:
                ok = self.meridian_flip(t)
                done += int(rig.state.get("seq_frame") or 0)        # inkl. der Belichtung, die noch fertig wurde
                flipped = True
                if not ok:
                    self.log(f"{name}: Meridian-Flip fehlgeschlagen – Ziel wird abgebrochen.", "err")
                    rig.sequence_stop()
                    return
                if done >= total:
                    break
                if not rig.sequence_start(name, t["exp"], t.get("gain"), total - done, t.get("filter", 0)):
                    return
                stall_t, last_frame = time.time(), 0
                continue
            if self._temp_refocus_due():
                self.log(f"{name}: Temperatur hat sich geändert – Nachfokussieren nach dem laufenden Bild.", "info")
                w = rig.waiter(lambda e: e.get("Event") == "Sequence" and e.get("state") == "frame_complete")
                rig.wait(w, float(t["exp"]) + 60, self._stopped)
                rig.sequence_stop()
                done += int(rig.state.get("seq_frame") or 0)
                self._af(t)
                if done >= total or self._stopped():
                    break
                if not rig.sequence_start(name, t["exp"], t.get("gain"), total - done, t.get("filter", 0)):
                    return
                stall_t, last_frame = time.time(), 0
                continue
            if time.time() - stall_t > max(600, float(t["exp"]) * 3 + 300):
                self.log(f"{name}: seit {int((time.time() - stall_t) / 60)} min kein neues Bild – Serie wird neu gestartet.", "warn")
                done += frame
                if not rig.sequence_start(name, t["exp"], t.get("gain"), max(1, total - done), t.get("filter", 0)):
                    return
                stall_t, last_frame = time.time(), 0
            time.sleep(3)
        if self._stopped():
            rig.sequence_stop()

    def _af(self, t):
        fn = self.o.get("af_fn")
        if not fn:
            return False
        ok = fn(t.get("fname") or "", self._stopped)
        if ok:
            self.af_temp = self.rig.focuser_info().get("temperature")
        return ok

    def _focus_for(self, t):
        """Vor einer Serie: Filterrad drehen, dann Autofokus oder gemerkte Fokusposition je Filter anfahren."""
        o, rig = self.o, self.rig
        fname, prev = t.get("fname") or "", getattr(self, "last_fname", None)
        changed = prev is not None and fname != prev
        if o.get("wheel") and t.get("filter"):
            rig.wheel_move(t.get("filter"))
        done = False
        if o.get("af_start") or (changed and o.get("af_filter")) or (prev is None and o.get("af_first")):
            done = self._af(t)
        if not done and changed and o.get("use_offsets"):
            pos = (o.get("focus_pos") or {})
            a, b = pos.get(prev), pos.get(fname)
            cur = rig.focuser_pos()
            if a is not None and b is not None and cur is not None and a != b:
                tgt = cur + (b - a)
                self.log(f"Fokus: Filterwechsel {prev} → {fname}, Versatz {b - a:+d} Schritte → {tgt}.", "info")
                rig.focuser_move(tgt, self._stopped)
        self.last_fname = fname

    def _temp_refocus_due(self):
        lim = float(self.o.get("af_temp") or 0)
        if lim <= 0 or not self.o.get("af_fn"):
            return False
        now = time.time()
        if now - getattr(self, "_tcheck", 0) < 120:
            return False
        self._tcheck = now
        t_ = self.rig.focuser_info().get("temperature")
        if t_ is None:
            return False
        if getattr(self, "af_temp", None) is None:
            self.af_temp = t_
            return False
        return abs(t_ - self.af_temp) >= lim

    def meridian_flip(self, t):
        """Ablauf wie in der ASIAIR-App: laufende Belichtung beenden lassen → Serie und Guiding stoppen →
        GoTo auf dasselbe Ziel (die Montierung wechselt dabei die Seite) → Plate Solve/Zentrieren →
        Guiding neu kalibrieren (oder Kalibrierung spiegeln) → optional Autofokus → Serie fortsetzen."""
        rig, o, name = self.rig, self.o, t["name"]
        self.log(f"{name}: Meridian-Flip beginnt (Stundenwinkel {self._ha(t) * 60:+.0f} min).", "ok")
        self._status(f"{name} · Meridian-Flip läuft")
        if o.get("flip_wait", True):
            w = rig.waiter(lambda e: e.get("Event") == "Sequence" and e.get("state") == "frame_complete")
            rig.wait(w, float(t["exp"]) + 60, self._stopped)
        if self._stopped():
            return False
        pier0 = rig.state.get("pier")
        rig.sequence_stop()
        if o["guide"]:
            rig.guide_stop()
        self._sleep(3)
        solve = not o.get("daytest")
        ok = rig.goto(t["ra"], t["dec"], self._stopped, solve=solve)
        if not ok and not self._stopped():
            self._sleep(10)
            ok = rig.goto(t["ra"], t["dec"], self._stopped, solve=solve)
        if not ok:
            return False
        rig.refresh()
        pier1 = rig.state.get("pier")
        if pier0 is not None and pier1 is not None:
            self.log(f"{name}: Montierungsseite {pier0} → {pier1}.", "ok" if pier0 != pier1 else "warn")
        if o["guide"]:
            if o.get("flip_cal") == "mirror":
                if not rig.ok(4400, "flip_calibrate", quiet=True):
                    self.log("ASIAIR: Kalibrierung spiegeln nicht möglich – kalibriere neu.", "warn")
                    recal = True
                else:
                    recal = False
            else:
                recal = True
            if not rig.guide_start(recalibrate=recal, stop=self._stopped):
                if not rig.guide_start(recalibrate=True, stop=self._stopped):
                    self.log(f"{name}: Guiding nach dem Flip nicht möglich.", "err")
                    if not o.get("unguided_ok", True):
                        return False
        if o.get("flip_af"):
            self._af(t)
        self.flips += 1
        self.log(f"{name}: Meridian-Flip erfolgreich – Aufnahme geht weiter.", "ok")
        return True


AIR_PORT_IMG = 4800
AIR_BAYERS = ("automatisch", "RGGB", "GRBG", "GBRG", "BGGR", "einfarbig (Mono)")


def _fits_to_array(data):
    """Minimaler FITS-Leser (BITPIX 8/16, BZERO) – falls das Air ein FITS statt Rohdaten liefert."""
    hdr, pos = {}, 0
    while True:
        block = data[pos:pos + 2880]
        pos += 2880
        if not block:
            raise ValueError("FITS ohne END")
        end = False
        for k in range(0, 2880, 80):
            card = block[k:k + 80].decode("ascii", "ignore")
            key = card[:8].strip()
            if key == "END":
                end = True
                break
            if "=" in card[8:10]:
                hdr[key] = card[10:].split("/")[0].strip().strip("'").strip()
        if end:
            break
    w, h, bp = int(hdr["NAXIS1"]), int(hdr["NAXIS2"]), int(hdr["BITPIX"])
    dt = {8: ">u1", 16: ">i2", 32: ">i4", -32: ">f4"}[bp]
    a = np.frombuffer(data[pos:pos + w * h * abs(bp) // 8], dtype=dt).reshape(h, w).astype(np.float32)
    a += float(hdr.get("BZERO", 0) or 0)
    return a, hdr.get("BAYERPAT", "")


def air_decode(hdr, payload, bayer="automatisch"):
    """Bild vom Air (ZIP mit Rohdaten oder FITS) -> float32 RGB (H, W, 3), 0..1, Farbe per 2×2-Superpixel."""
    data = payload
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            data = z.read(z.namelist()[0])
    w, h = int(hdr.get("width") or 0), int(hdr.get("height") or 0)
    pat = ""
    if data[:6] == b"SIMPLE":
        a, pat = _fits_to_array(data)
        h, w = a.shape
        scale = float(a.max()) if a.max() > 0 else 1.0
        a = a / (65535.0 if scale > 255 else 255.0)
    elif w and h and len(data) >= w * h * 2:
        a = np.frombuffer(data[:w * h * 2], dtype=">u2" if hdr.get("isBigEndian") else "<u2").reshape(h, w)
        a = a.astype(np.float32) / 65535.0
    elif w and h and len(data) >= w * h:
        a = np.frombuffer(data[:w * h], dtype=np.uint8).reshape(h, w).astype(np.float32) / 255.0
    else:
        raise ValueError(f"Unerwartetes Bildformat ({len(data)} Byte für {w}×{h})")
    mono = bayer.startswith("einfarbig") or (bayer == "automatisch" and not hdr.get("canDebayer", 1) and not pat)
    if mono:
        return np.dstack([a, a, a])
    p = pat if (bayer == "automatisch" and pat in AIR_BAYERS) else (bayer if bayer in AIR_BAYERS[1:5] else "RGGB")
    h2, w2 = (a.shape[0] // 2) * 2, (a.shape[1] // 2) * 2
    a = a[:h2, :w2]
    q = {(0, 0): a[0::2, 0::2], (0, 1): a[0::2, 1::2], (1, 0): a[1::2, 0::2], (1, 1): a[1::2, 1::2]}
    pos = {c: [] for c in "RGB"}
    for k, ch in enumerate(p):
        pos[ch].append(q[(k // 2, k % 2)])
    return np.dstack([pos["R"][0], sum(pos["G"]) / len(pos["G"]), pos["B"][0]])


class AirImager:
    """Port 4800: Bild abholen (get_current_img). Braucht alle 4 s einen Herzschlag, sonst trennt das Air."""
    MAGIC = 963

    def __init__(self, log):
        self.log = log
        self.sock = None
        self.host = None
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._stop = threading.Event()

    @property
    def connected(self):
        return self.sock is not None

    def connect(self, host):
        self.close()
        try:
            self.sock = socket.create_connection((host, AIR_PORT_IMG), timeout=10)
            self.sock.settimeout(60)
        except OSError as e:
            self.sock = None
            self.log(f"ASIAIR: Bildkanal (Port 4800) nicht erreichbar ({e}).", "err")
            return False
        self.host = host
        self._stop = threading.Event()
        threading.Thread(target=self._hb, args=(self._stop,), daemon=True).start()
        return True

    def close(self):
        self._stop.set()
        s, self.sock = self.sock, None
        if s:
            try:
                s.close()
            except OSError:
                pass

    def _send(self, cid, method):
        with self._send_lock:
            self.sock.sendall(('{"id":%d,"method":"%s"}\r\n' % (cid, method)).encode())

    def _hb(self, stop):
        while not stop.wait(4.0):
            try:
                self._send(1, "test_connection")
            except Exception:
                return

    def _recv(self, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(min(1 << 20, n - len(buf)))
            if not chunk:
                raise ConnectionError("Bildkanal geschlossen")
            buf += chunk
        return bytes(buf)

    def get(self, method="get_current_img", wait=60):
        """-> (header, payload) oder None (kein Bild vorhanden)."""
        if not self.sock and (not self.host or not self.connect(self.host)):
            return None
        with self._lock:
            try:
                self._send(0, method)
                end = time.time() + wait
                while time.time() < end:
                    h = self._recv(80)
                    if struct.unpack(">H", h[0:2])[0] != self.MAGIC:
                        raise IOError("Bildkanal: unbekanntes Format")
                    hdr = {"length": struct.unpack(">i", h[6:10])[0], "isBigEndian": h[12], "id": h[15],
                           "width": struct.unpack(">H", h[16:18])[0], "height": struct.unpack(">H", h[18:20])[0],
                           "canDebayer": struct.unpack(">H", h[26:28])[0]}
                    payload = self._recv(hdr["length"]) if hdr["length"] > 0 else b""
                    if hdr["id"] == 1:
                        continue                                    # Herzschlag-Antwort
                    if hdr["width"] == 0 and len(payload) < 64:     # Statusmeldung, z. B. „there is no image now“
                        return None
                    return hdr, payload
            except Exception as e:
                self.log(f"ASIAIR: Bild konnte nicht geholt werden ({e}).", "warn")
                self.close()
        return None


# --------------------------------------------------------------------------
# Fernzugriff übers Internet (eigener Nachbau der Idee „Telescope Network“)
#
# Heimstation = dieses Programm auf einem PC beim Teleskop (lokal mit dem Air verbunden).
# Fernzugriff  = dieses Programm unterwegs. Beide verbinden sich NUR ausgehend mit einem MQTT-Vermittlungsserver –
# keine Portfreigabe, kein VPN, kein Browser. Alle Inhalte sind Ende-zu-Ende verschlüsselt (AES-256-GCM, Schlüssel
# aus Geräte-ID + Kopplungscode); der Server sieht nur unlesbare Daten. Befehle sind zeitgestempelt und werden nur
# einmal angenommen (Schutz gegen Wiederholen).
# --------------------------------------------------------------------------
try:
    import paho.mqtt.client as _mqtt
    HAVE_MQTT = True
except Exception:                                    # pragma: no cover
    _mqtt = None
    HAVE_MQTT = False

REMOTE_BROKER_DEFAULT = {"host": "broker.hivemq.com", "port": 8883, "tls": True, "user": "", "pw": ""}
REMOTE_VIEW_OK = ("get_", "scope_get_", "test_connection", "pi_is_verified", "pi_get_")
REMOTE_NEVER = ("pi_shutdown", "pi_reboot", "verify_client", "get_verify_str", "set_wifi", "pi_set_ap")
_B32 = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"                # ohne 0/O/1/I – gut abzulesen


def remote_new_id():
    import secrets
    s = "".join(secrets.choice(_B32) for _ in range(8))
    return f"{s[:4]}-{s[4:]}"


def remote_new_code():
    import secrets
    s = "".join(secrets.choice(_B32) for _ in range(16))
    return "-".join(s[k:k + 4] for k in range(0, 16, 4))


def _norm(x):
    return re.sub(r"[^A-Z0-9]", "", str(x).upper())


class RemoteLink:
    """Verschlüsselte Nachrichten über MQTT für genau eine Heimstation (ID + Kopplungscode)."""

    def __init__(self, station_id, code, broker, log, on_msg, on_link=None, role="remote"):
        if not HAVE_MQTT:
            raise RuntimeError("Paket 'paho-mqtt' fehlt – pip install paho-mqtt")
        if not HAVE_CRYPTO:
            raise RuntimeError("Paket 'cryptography' fehlt – pip install cryptography")
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        self.sid = _norm(station_id)
        key = hashlib.pbkdf2_hmac("sha256", _norm(code).encode(), b"sgcc-remote-v1:" + self.sid.encode(), 200000)
        self.aead = AESGCM(key)
        self.base = "sgcc/v1/" + hashlib.sha256(b"topic:" + key).hexdigest()[:32]
        self.broker = dict(REMOTE_BROKER_DEFAULT, **(broker or {}))
        self.log, self.on_msg, self.on_link, self.role = log, on_msg, on_link, role
        self.cid = remote_new_id().replace("-", "")
        self.up = False
        self._seen = {}
        self._subs = []
        self.client = None

    def t(self, name):
        return f"{self.base}/{name}"

    # ---- Verschlüsselung -------------------------------------------------------
    def seal(self, topic, obj):
        body = json.dumps(dict(obj, ts=time.time(), n=os.urandom(8).hex()), ensure_ascii=False).encode()
        nonce = os.urandom(12)
        return nonce + self.aead.encrypt(nonce, body, topic.encode())

    def open(self, topic, data):
        try:
            obj = json.loads(self.aead.decrypt(data[:12], data[12:], topic.encode()).decode())
        except Exception:
            return None                                        # falscher Code oder fremde Nachricht
        if abs(time.time() - float(obj.get("ts", 0))) > 600:   # zu alt (Uhren dürfen 10 min abweichen)
            return None
        n = obj.get("n")
        now = time.time()
        if n in self._seen:
            return None                                        # wiederholte Nachricht
        self._seen[n] = now
        if len(self._seen) > 2000:
            self._seen = {k: v for k, v in self._seen.items() if now - v < 900}
        return obj

    # ---- Verbindung zum Vermittlungsserver ------------------------------------------
    def start(self, subs, will=None):
        self._subs = list(subs)
        b = self.broker
        if hasattr(_mqtt, "CallbackAPIVersion"):
            c = _mqtt.Client(_mqtt.CallbackAPIVersion.VERSION2, client_id=f"sgcc-{self.role}-{self.cid}")
        else:                                                   # paho-mqtt 1.x
            c = _mqtt.Client(client_id=f"sgcc-{self.role}-{self.cid}")
        if b.get("user"):
            c.username_pw_set(b["user"], b.get("pw") or None)
        if b.get("tls"):
            c.tls_set()
        if will:
            c.will_set(will[0], will[1], qos=1, retain=True)
        c.reconnect_delay_set(2, 30)
        c.on_connect = self._on_connect
        c.on_disconnect = self._on_disconnect
        c.on_message = self._on_message
        self.client = c
        try:
            c.connect_async(b["host"], int(b["port"]), keepalive=30)
            c.loop_start()
        except Exception as e:
            self.log(f"Fernzugriff: Vermittlungsserver nicht erreichbar ({e}).", "err")
            return False
        return True

    def stop(self, last=None):
        c, self.client = self.client, None
        if not c:
            return
        try:
            if last:
                c.publish(last[0], last[1], qos=1, retain=True).wait_for_publish(3)
            c.disconnect()
            c.loop_stop()
        except Exception:
            pass
        self.up = False

    def _on_connect(self, c, userdata, flags, rc, props=None):
        ok = (rc == 0) if isinstance(rc, int) else not getattr(rc, "is_failure", False)
        self.up = ok
        if ok:
            for t in self._subs:
                c.subscribe(t, qos=1)
        else:
            self.log(f"Fernzugriff: Anmeldung am Vermittlungsserver abgelehnt ({rc}).", "err")
        if self.on_link:
            self.on_link(ok)

    def _on_disconnect(self, c, userdata, *a):
        self.up = False
        if self.on_link:
            self.on_link(False)

    def _on_message(self, c, userdata, msg):
        try:
            self.on_msg(msg.topic, msg.payload, msg.retain)
        except Exception as e:
            self.log(f"Fernzugriff: Fehler beim Verarbeiten ({e}).", "err")

    def send(self, name, obj, retain=False):
        if not self.client:
            return False
        t = self.t(name)
        try:
            self.client.publish(t, self.seal(t, obj), qos=1, retain=retain)
            return True
        except Exception:
            return False


class HomeStation:
    """Läuft auf dem PC beim Teleskop: nimmt verschlüsselte Befehle an, leitet sie an das lokale Air weiter und
    meldet Zustand, Ereignisse und Protokoll an die Ferngeräte. Pläne laufen HIER – auch wenn unterwegs die
    Verbindung abreißt."""

    def __init__(self, app, sid, code, name, perm, broker):
        self.app, self.sid, self.name, self.perm = app, sid, name, perm
        self.link = RemoteLink(sid, code, broker, app.log, self._msg, self._linkstate, role="home")
        self.logbuf = []
        self.seq = 0
        self.running = False
        self.remotes = {}                                       # cid -> zuletzt gesehen

    def start(self):
        self.running = True
        ok = self.link.start([self.link.t("c")], will=(self.link.t("p"), b"0"))
        threading.Thread(target=self._state_loop, daemon=True).start()
        return ok

    def stop(self):
        self.running = False
        self.link.stop(last=(self.link.t("p"), b"0"))

    def _linkstate(self, up):
        if up:
            self.link.client.publish(self.link.t("p"), b"1", qos=1, retain=True)
            self.app.log("Fernzugriff: Heimstation ist online.", "ok")
        self.app._air_dirty()

    def add_log(self, text, tag):
        self.seq += 1
        self.logbuf.append((self.seq, time.strftime("%H:%M:%S"), tr(text), tag))
        del self.logbuf[:-60]

    def event(self, port, obj):
        if self.running and self.link.up and self.remotes:
            self.link.send("e", {"port": port, "ev": obj})

    def snapshot(self):
        a = self.app.air
        job = getattr(self.app, "air_job", None)
        return {"name": self.name, "perm": self.perm, "air": bool(a.connected), "model": a.model, "host": a.host,
                "state": dict(a.state), "plan": bool(job and job.alive()), "status": getattr(self.app, "_air_status_txt", ""),
                "log": list(self.logbuf[-30:]), "site": self.app.site_cache}

    def _state_loop(self):
        while self.running:
            if self.link.up:
                self.link.send("s", self.snapshot(), retain=True)
            now = time.time()
            self.remotes = {k: v for k, v in self.remotes.items() if now - v < 120}
            time.sleep(4 if self.remotes else 15)

    def _msg(self, topic, data, retain):
        obj = self.link.open(topic, data)
        if not obj:
            return
        cid = obj.get("cid", "")
        if cid not in self.remotes:
            self.app.log(f"Fernzugriff: Ferngerät verbunden ({cid[:4]}…).", "info")
        self.remotes[cid] = time.time()
        threading.Thread(target=self._handle, args=(obj,), daemon=True).start()

    def _reply(self, obj, **kw):
        self.link.send("r", dict(kw, to=obj.get("cid"), id=obj.get("id")))

    def _handle(self, obj):
        t, app, a = obj.get("t"), self.app, self.app.air
        full = self.perm == "full"
        if t == "hello" or t == "ping":
            self._reply(obj, ok=True, snap=self.snapshot())
        elif t == "rpc":
            m = str(obj.get("m", ""))
            if m in REMOTE_NEVER or (not full and not m.startswith(REMOTE_VIEW_OK)):
                self._reply(obj, ok=False, err="nicht erlaubt (Heimstation: nur zuschauen)" if not full else "nicht erlaubt")
                return
            if not a.connected:
                self._reply(obj, ok=False, err="Heimstation ist nicht mit dem ASIAIR verbunden")
                return
            r = a.call(int(obj.get("port", 4700)), m, obj.get("p"), timeout=float(obj.get("to_s", 15)), quiet=True)
            self._reply(obj, ok=True, r=r)
        elif t == "img":
            if not a.connected:
                self._reply(obj, ok=False, err="Heimstation ist nicht mit dem ASIAIR verbunden")
                return
            r = app.remote_image(obj)
            if r:
                self._reply(obj, ok=True, jpg=r[0], info=r[1])
            else:
                self._reply(obj, ok=False, err="kein Bild")
        elif t in ("plan_start", "plan_cancel", "stop_all"):
            if not full:
                self._reply(obj, ok=False, err="nicht erlaubt (Heimstation: nur zuschauen)")
                return
            done, box = threading.Event(), {}

            def run():
                try:
                    box["r"] = app.remote_command(t, obj)
                finally:
                    done.set()
            app.ui(run)
            done.wait(20)
            ok, msg = box.get("r", (False, "keine Antwort"))
            self._reply(obj, ok=ok, err=None if ok else msg, msg=msg)
        else:
            self._reply(obj, ok=False, err="unbekannter Befehl")


class RemoteRig(AirRig):
    """Ferngerät: sieht für die Oberfläche aus wie ein lokales ASIAIR, schickt aber alles verschlüsselt über
    den Vermittlungsserver an die Heimstation."""

    def __init__(self, log, on_change, sid, code, name, broker):
        super().__init__(log, on_change)
        self.remote = True
        self.quiet_events = True                                # Ereignisse stehen schon im Heim-Protokoll
        self.sname = name
        self.link = RemoteLink(sid, code, broker, log, self._msg, self._linkstate, role="remote")
        self.snap = {}
        self.online = False
        self.last_snap = 0.0
        self._pending = {}
        self._lastlog = 0
        self._rid = 0

    @property
    def connected(self):
        return self.link.up and self.online and bool(self.snap.get("air")) and time.time() - self.last_snap < 90

    @property
    def station_ok(self):
        return self.link.up and self.online

    def connect(self, host=None, pem=None, quiet=False):
        self._want = True
        ok = self.link.start([self.link.t(n) for n in ("p", "r", "e", "s")])
        if not ok:
            return False
        end = time.time() + 20
        while time.time() < end and not self.link.up:
            time.sleep(0.3)
        if not self.link.up:
            self.log("Fernzugriff: Vermittlungsserver nicht erreichbar.", "err")
            return False
        r = self._req({"t": "hello"}, timeout=15)
        if not r:
            self.log("Fernzugriff: Heimstation antwortet nicht – läuft dort das Programm mit eingeschaltetem "
                     "Fernzugriff? Stimmen Geräte-ID und Kopplungscode?", "err")
            return True                                         # Verbindung zum Server bleibt; Station kann noch kommen
        self._snap(r.get("snap") or {})
        threading.Thread(target=self._ping_loop, daemon=True).start()
        return True

    def disconnect(self):
        self._want = False
        self.link.stop()
        self.online = False
        self.on_change()

    def _linkstate(self, up):
        self.on_change()

    def _ping_loop(self):
        while self._want:
            time.sleep(30)
            if self._want and self.link.up:
                self._req({"t": "ping"}, timeout=10)

    def _msg(self, topic, data, retain):
        name = topic.rsplit("/", 1)[-1]
        if name == "p":
            self.online = data == b"1"
            self.on_change()
            return
        obj = self.link.open(topic, data) if not (retain and name == "s") else self._open_retained(topic, data)
        if not obj:
            return
        if name == "r":
            if obj.get("to") != self.link.cid:
                return
            w = self._pending.get(obj.get("id"))
            if w:
                w[1].append(obj)
                w[0].set()
            if obj.get("snap"):
                self._snap(obj["snap"])
        elif name == "e":
            ev = obj.get("ev") or {}
            if isinstance(ev, dict):
                self._event(int(obj.get("port", 4700)), ev)
        elif name == "s":
            self._snap(obj)

    def _open_retained(self, topic, data):
        """Gespeicherter Zustand darf älter sein als die 10-Minuten-Grenze – Zeitprüfung hier lockerer."""
        try:
            return json.loads(self.link.aead.decrypt(data[:12], data[12:], topic.encode()).decode())
        except Exception:
            return None

    def _snap(self, s):
        if not isinstance(s, dict):
            return
        self.snap = s
        self.last_snap = time.time() if time.time() - float(s.get("ts", time.time())) < 120 else self.last_snap
        self.online = self.online or self.last_snap > 0
        if isinstance(s.get("state"), dict):
            self.state.update(s["state"])
        self.model = s.get("model") or self.model
        self.host = f"{self.sname} (fern)"
        for seq, hhmm, text, tag in s.get("log", []):
            if seq > self._lastlog:
                if self._lastlog:                               # beim ersten Mal nicht den ganzen Verlauf
                    self.log(f"🏠 {hhmm} {text}", tag)
                self._lastlog = seq
        self.on_change()

    def _req(self, obj, timeout=15):
        self._rid += 1
        rid = f"{self.link.cid}-{self._rid}"
        ev, box = threading.Event(), []
        self._pending[rid] = (ev, box)
        try:
            if not self.link.send("c", dict(obj, id=rid, cid=self.link.cid)):
                return None
            ev.wait(timeout)
            return box[0] if box else None
        finally:
            self._pending.pop(rid, None)

    def call(self, port, method, params=None, timeout=15.0, quiet=False):
        if not quiet:
            self.log(f"→ (fern) {method} {json.dumps(params, ensure_ascii=False)[:200] if params else ''}", "tx")
        r = self._req({"t": "rpc", "port": port, "m": method, "p": params if params is not None else [],
                       "to_s": timeout}, timeout=timeout + 10)
        if r is None:
            if not quiet:
                self.log(f"Fernzugriff: keine Antwort auf {method}.", "warn")
            return None
        if not r.get("ok"):
            if not quiet:
                self.log(f"Fernzugriff: {method} – {r.get('err')}", "err")
            return {"error": r.get("err"), "code": -1}
        if not quiet:
            self.log(f"← (fern) {json.dumps(r.get('r'), ensure_ascii=False)[:300]}", "rx")
        return r.get("r")

    def refresh(self):
        pass                                                    # Zustand kommt von der Heimstation

    def fetch_image(self, stretch=0.2):
        r = self._req({"t": "img", "stretch": stretch, "max": 1200}, timeout=60)
        if r and r.get("ok") and r.get("jpg"):
            return base64.b64decode(r["jpg"]), r.get("info", "")
        return None

    def command(self, t, **kw):
        r = self._req(dict(kw, t=t), timeout=30)
        if not r:
            return False, "Heimstation antwortet nicht."
        return bool(r.get("ok")), r.get("msg") or r.get("err") or ""


# --------------------------------------------------------------------------
# Bildempfang (TCP 4800, Binärprotokoll: 80-Byte-Header + Nutzdaten)
# --------------------------------------------------------------------------
HDR_FMT = ">HHHIHHBBHH"     # die ersten 20 Bytes des 80-Byte-Headers
ID_PREVIEW, ID_STACK = 21, 23


def raw_to_rgb(data: bytes, w: int, h: int):
    """Seestar-Rohdaten -> float32 RGB (H, W, 3) im Bereich 0..1."""
    n = len(data)
    if n == w * h * 6:                                    # Stack: RGB 16 bit
        img = np.frombuffer(data, dtype="<u2").reshape(h, w, 3).astype(np.float32)
    elif n == w * h * 2:                                  # Vorschau: Bayer GRBG 16 bit
        b = np.frombuffer(data, dtype="<u2").reshape(h, w).astype(np.float32)
        h2, w2 = (h // 2) * 2, (w // 2) * 2
        b = b[:h2, :w2]
        g1, r = b[0::2, 0::2], b[0::2, 1::2]
        bl, g2 = b[1::2, 0::2], b[1::2, 1::2]
        img = np.dstack([r, (g1 + g2) / 2, bl])           # halbe Auflösung, kein Interpolationsrauschen
    else:
        raise ValueError(f"Unerwartete Bildgröße {n} Byte für {w}×{h}")
    return img / 65535.0


def autostretch(img, strength: float = 0.25, linked: bool = False):
    """Einfacher STF-artiger Auto-Stretch (Hintergrund abziehen + Midtones)."""
    out = np.empty_like(img)
    chans = [img.mean(axis=2)] * 3 if linked else [img[..., c] for c in range(3)]
    for c in range(3):
        ch = img[..., c]
        ref = chans[c][::4, ::4]
        med = float(np.median(ref))
        mad = float(np.median(np.abs(ref - med))) * 1.4826 + 1e-6
        lo = max(0.0, med - 2.8 * mad)
        x = np.clip((ch - lo) / max(1e-6, 1.0 - lo), 0, 1)
        m0 = max(1e-6, (med - lo) / max(1e-6, 1.0 - lo))
        m = strength                                       # Ziel-Hintergrund ≈ strength
        mid = m0 * (1 - m) / (m0 * (1 - 2 * m) + m) if m0 > 0 else 0.5
        mid = min(max(mid, 1e-4), 0.9999)
        out[..., c] = ((mid - 1) * x) / ((2 * mid - 1) * x - mid)
    return np.clip(out, 0, 1)


class SeestarImager:
    def __init__(self, log, on_frame):
        self.log = log
        self.on_frame = on_frame          # (kind, rgb_float, w, h)
        self.sock = None
        self.running = False
        self.lock = threading.Lock()
        self.streaming = False
        self.last_frame = 0

    @property
    def connected(self):
        return self.sock is not None and self.running

    def connect(self, host):
        self.close()
        try:
            self.sock = socket.create_connection((host, IMG_PORT), timeout=5)
            self.sock.settimeout(2.0)
        except Exception as e:
            self.sock = None
            self.log(f"Bildkanal {host}:{IMG_PORT} nicht erreichbar: {e}", "err")
            return False
        self.running = True
        threading.Thread(target=self._recv_loop, daemon=True).start()
        threading.Thread(target=self._hb_loop, daemon=True).start()
        self.log("Bildkanal verbunden.", "ok")
        return True

    def close(self):
        self.running = False
        self.streaming = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None

    def _send(self, obj):
        if not self.connected:
            return False
        try:
            with self.lock:
                self.sock.sendall((json.dumps(obj) + "\r\n").encode())
            return True
        except Exception as e:
            self.log(f"Bildkanal: Senden fehlgeschlagen: {e}", "err")
            return False

    def start_preview(self):
        self.streaming = True
        return self._send({"id": ID_PREVIEW, "method": "begin_streaming"})

    def stop_preview(self):
        self.streaming = False
        return self._send({"id": 22, "method": "stop_streaming"})

    def request_stack(self):
        return self._send({"id": ID_STACK, "method": "get_stacked_img"})

    def _hb_loop(self):
        while self.running:
            time.sleep(5)
            self._send({"id": 2, "method": "test_connection"})

    def _recv_exact(self, n):
        buf = bytearray()
        while len(buf) < n and self.running:
            try:
                chunk = self.sock.recv(min(n - len(buf), 1 << 20))
            except socket.timeout:
                continue
            except Exception:
                return None
            if not chunk:
                return None
            buf += chunk
        return bytes(buf) if len(buf) == n else None

    def _recv_loop(self):
        while self.running:
            hdr = self._recv_exact(80)
            if hdr is None:
                break
            try:
                _a, _b, _c, size, _d, _e, _code, fid, w, h = struct.unpack(HDR_FMT, hdr[:20])
            except struct.error:
                continue
            data = self._recv_exact(size) if size else b""
            if data is None:
                break
            if size < 1000:                       # JSON-Antwort / Heartbeat – ignorieren
                continue
            try:
                if fid == ID_STACK:
                    with zipfile.ZipFile(io.BytesIO(data)) as z:
                        data = z.read("raw_data")
                    kind = "stack"
                elif fid == ID_PREVIEW:
                    kind = "preview"
                    self.last_frame = time.time()
                else:
                    continue
                self.on_frame(kind, raw_to_rgb(data, w, h), w, h)
            except Exception as e:
                self.log(f"Bild konnte nicht dekodiert werden: {e}", "warn")
        if self.running:
            self.log("Bildkanal getrennt.", "warn")
        self.close()


# --------------------------------------------------------------------------
# Bluetooth-LE-Client (eigener asyncio-Thread)
# --------------------------------------------------------------------------
class SeestarBLE:
    def __init__(self, log):
        self.log = log
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.client = None
        self.on_lost = None

    def run(self, coro, cb=None):
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        if cb:
            fut.add_done_callback(lambda f: cb(f))
        return fut

    async def scan(self, only_seestar=True, timeout=6.0):
        devs = await BleakScanner.discover(timeout=timeout, return_adv=True)
        out = []
        for addr, (dev, adv) in devs.items():
            name = dev.name or adv.local_name or ""
            if only_seestar and not re.search(r"seestar|s30|s50", name.lower()):
                continue
            out.append((addr, name or "(ohne Namen)", adv.rssi))
        out.sort(key=lambda x: -x[2])
        return out

    async def connect(self, address):
        if self.client and self.client.is_connected:
            await self.client.disconnect()
        self.client = BleakClient(address, disconnected_callback=lambda c: (self.log("BLE getrennt.", "warn"),
                                                                             self.on_lost and self.on_lost()))
        await self.client.connect(timeout=15)
        rows = []
        for svc in self.client.services:
            for ch in svc.characteristics:
                rows.append((svc.uuid, ch.uuid, ",".join(ch.properties), ch.description or ""))
        return rows

    async def disconnect(self):
        if self.client:
            await self.client.disconnect()

    async def read(self, uuid):
        data = await self.client.read_gatt_char(uuid)
        return bytes(data)

    async def write(self, uuid, data: bytes, response=True):
        await self.client.write_gatt_char(uuid, data, response=response)

    async def notify(self, uuid, on_data):
        await self.client.start_notify(uuid, lambda _h, d: on_data(uuid, bytes(d)))


# --------------------------------------------------------------------------
# Ein Seestar = eigene Steuerverbindung + eigener Bildkanal
# --------------------------------------------------------------------------
class Device:
    def __init__(self, app, name, host):
        self.app = app
        self.name = name
        self.host = host
        self.model = None
        self.fw = ""
        self.frames = None
        self.battery = None
        self.temp = None
        self.selected = True                 # Teil der Gruppe „alle markierten“
        self.last_stack_n = None
        self.panels = []                     # angeschlossene Vorschau-Ansichten
        self.frame_listeners = []            # z. B. App-Autofokus: (kind, rgb)
        self.ext_filter = NO_FILTER          # montierter externer Filter
        self.protect = False                 # Arm-Schutz: Parken/Schließen sperren
        self.dewcap = False                  # Taukappe montiert (Arm kann nicht schließen)
        self.accessory = False               # anderes Zubehör vor dem Objektiv
        self.link = "home"                   # "home" = Heimnetz (Stationsmodus), "ap" = direkt im Seestar-WLAN
        self.ap_ssid = ""                    # WLAN-Name des Seestar, z. B. S50_1a2b3c4d
        self.ap_pass = ""                    # WLAN-Passwort (im Speicher im Klartext, gespeichert geschützt)
        self.station = {}                    # Heimnetz-Daten, wie das Seestar sie meldet
        self.pending = {}                    # offline geänderte Einstellungen – werden beim Verbinden gesendet
        self.focus_hold = None               # Stacking für Fokusänderung angehalten: "continue" / "restart"
        self._hold_timer = None
        self.focus_run = None
        self.popup = None
        self.settings = {}                   # letzter get_setting-Stand (+ eigene Änderungen)
        self.values = {}                     # key -> Wert für SETTINGS (UI-Sicht)
        self.settings_panels = []
        self.settings_popup = None
        self.job = None                      # laufender Mosaik-Ablauf
        self.job_text = ""
        self._ev_cond = threading.Condition()
        self._ev_log = []                    # (zeit, Event, state)
        self.eq_mode = None                  # True = EQ, False = Alt-Az, None = unbekannt
        self.focus_pos = None                # Fokusposition (Motorschritte)
        self.storage_free = None             # freier Speicher in MB
        self.charging = None                 # True = lädt
        self.batt_temp = None
        self.tilt = None                     # (x, y, angle) vom Neigungssensor
        self.pa = None                       # letzte Polausrichtung: dict(x, y, total, t)
        self.pa_state = ""                   # working / complete / fail
        self.manual = True                   # True = vom Nutzer getrennt -> nicht neu verbinden
        self.connecting = False
        self.reconnecting = False
        self.pem = ""
        self.wifi = SeestarWifi(self.log, self.on_event, self.on_state)
        self.wifi.on_connected = self.after_connect
        self.wifi.guard = self._guard
        self._batt_warned = set()
        self.imager = SeestarImager(self.log, self.on_frame) if HAVE_IMAGING else None

    def log(self, text, tag="info"):
        self.app.log(f"[{self.name}] {text}", tag)

    ARM_CLOSING = ("scope_park", "pi_shutdown", "pi_reboot")

    @property
    def is_stacking(self):
        """Stackt das Seestar gerade? (Stack-Ereignis in den letzten 90 s, nicht für den Fokus angehalten)"""
        ev = getattr(self, "_last_stack_ev", None)
        return bool(self.connected and ev and time.time() - ev[0] < 90 and self.focus_hold is None)

    @property
    def mounted(self):
        """Ist irgendetwas Externes am Seestar eingetragen?"""
        return self.ext_filter != NO_FILTER or self.dewcap or self.accessory

    def protect_reason(self):
        """Wodurch der Arm blockiert ist – für Meldungen."""
        parts = ([self.ext_filter] if self.ext_filter != NO_FILTER else []) + (["Taukappe"] if self.dewcap else []) \
            + (["Zubehör vor dem Objektiv"] if self.accessory else [])
        return ", ".join(parts) or "von Hand eingeschaltet"

    def _guard(self, method, params):
        """Arm-Schutz: bei montiertem externem Filter keine Befehle, die den Arm schließen."""
        if self.protect and method in self.ARM_CLOSING:
            self.log(f"BLOCKIERT: „{method}“ würde den Arm schließen – Arm-Schutz aktiv ({self.protect_reason()}). "
                     "Filter, Taukappe bzw. Zubehör abnehmen und im Tab „Fokus & Filter“ austragen.", "err")
            return False
        return True

    @property
    def connected(self):
        return self.wifi.connected

    @property
    def status(self):
        if self.connected:
            return "verbunden"
        if self.connecting:
            return "verbinde …"
        return "verbinde neu …" if self.reconnecting else "getrennt"

    def connect(self, pem):
        self.manual = False
        self.pem = pem
        self.connecting = True
        self.app.ui(self.app.device_changed, self)
        self.log(f"Verbinde mit {self.host} …")
        try:
            self.ensure_link()
            ok = self.wifi.connect(self.host, pem)
        finally:
            self.connecting = False
            self.app.ui(self.app.device_changed, self)
        if not ok and self.app.auto_reconnect and not self.manual:
            self._start_reconnect()

    def ensure_link(self, quiet=False):
        """Direktverbindung: ist das Seestar nicht erreichbar, den PC mit seinem WLAN verbinden."""
        if self.link != "ap" or not self.ap_ssid or tcp_reachable(self.host, timeout=1.0):
            return
        if not quiet:
            self.log(f"Verbinde den PC mit dem WLAN „{self.ap_ssid}“ …")
        ok, msg = join_seestar_wifi(self.ap_ssid, self.ap_pass, self.host)
        if not quiet or ok:
            self.log(msg, "ok" if ok else "err")

    def disconnect(self):
        """Vom Nutzer getrennt (oder App beendet): kein Neuverbinden; laufendes Mosaik wird pausiert."""
        self.manual = True
        if self.job:
            self.job.suspend()
        self.wifi.disconnect()
        if self.imager:
            self.imager.close()

    # -- Rückmeldungen aus den Netzwerk-Threads
    def on_state(self, up):
        if not up:
            if self.imager:
                self.imager.close()
            if not self.manual and self.app.auto_reconnect:
                self._start_reconnect()
        self.app.ui(self.app.device_changed, self)

    def _start_reconnect(self):
        if self.reconnecting:
            return
        self.reconnecting = True
        threading.Thread(target=self._reconnect_loop, daemon=True).start()

    def _reconnect_loop(self):
        delay, tries = 5, 0
        self.log("Verbindung unterbrochen – verbinde automatisch neu …", "warn")
        self.app.ui(self.app.device_changed, self)
        try:
            while not self.manual and not self.connected and self.app.auto_reconnect:
                end = time.time() + delay
                while time.time() < end:
                    if self.manual:
                        return
                    time.sleep(0.5)
                tries += 1
                self.ensure_link(quiet=True)
                if self.wifi.connect(self.host, self.pem):
                    time.sleep(4)                      # hält die Verbindung wirklich? (Seestar evtl. noch im Hochfahren)
                    if self.connected:
                        self.log(f"Wieder verbunden (Versuch {tries}).", "ok")
                        return
                    self.log("Verbindung sofort wieder abgebrochen – versuche weiter.", "warn")
                delay = min(delay * 2, 60)
        finally:
            self.reconnecting = False
            self.app.ui(self.app.device_changed, self)

    def open_arm(self, mode="star"):
        """Arm hochfahren. Firmware 9.x öffnet den Arm nur mit scope_move_to_horizon (iscope_start_view allein
        wird mit code 0 bestätigt, der Arm bleibt aber zu – getestet im EQ-Modus). Danach Ansicht starten."""
        since = time.time()
        self.wifi.send("scope_move_to_horizon")
        self.wait_event(("ScopeMoveToHorizon",), timeout=60, since=since)
        if mode:
            self.wifi.send("iscope_start_view", {"mode": mode})

    def stop_all(self):
        """Not-Stopp: Bewegung sofort anhalten (Geschwindigkeit 0 – das stoppt nachweislich), GoTo und Ansicht beenden."""
        self.wifi.send("scope_speed_move", {"speed": 0, "angle": 0, "dur_sec": 1})
        self.wifi.send("scope_abort_slew", quiet=True)
        self.wifi.send("iscope_stop_view")

    def update_device_info(self, res):
        """Zusatzinfos aus get_device_state übernehmen (Fokus, Speicher, Laden)."""
        foc = res.get("focuser") if isinstance(res.get("focuser"), dict) else {}
        if isinstance(foc.get("step"), (int, float)):
            self.focus_pos = int(foc["step"])
        stor = _g(res, "storage.storage_volume")
        if isinstance(stor, list) and stor and isinstance(stor[0], dict):
            cur = _g(res, "storage.cur_storage")
            vol = next((v for v in stor if v.get("name") == cur), stor[0])
            self.storage_free = vol.get("free_mb", vol.get("freeMB"))
        pi = res.get("pi_status") if isinstance(res.get("pi_status"), dict) else {}
        if "charger_status" in pi:
            self.charging = pi.get("charger_status") in ("Charging", "Full") or bool(pi.get("charge_online"))
        self.batt_temp = pi.get("battery_temp", self.batt_temp)
        self.app.ui(self.app.device_changed, self)

    def after_connect(self):
        r = self.wifi.send("get_device_state", {"keys": ["device", "pi_status", "mount", "focuser", "storage",
                                                         "location_lon_lat"]}, quiet=True)
        res = (r or {}).get("result") if isinstance((r or {}).get("result"), dict) else {}
        self.update_device_info(res)
        ll = res.get("location_lon_lat")
        self.seestar_loc = ((float(ll[1]), float(ll[0])) if isinstance(ll, (list, tuple)) and len(ll) == 2
                            and not (ll[0] == 0 and ll[1] == 0) else None)
        if isinstance(res.get("mount"), dict) and "equ_mode" in res["mount"]:
            self.eq_mode = bool(res["mount"]["equ_mode"])
        dev = res.get("device", {}) or {}
        pi = res.get("pi_status", {}) or {}
        pm = dev.get("product_model", "")
        self.fw = dev.get("firmware_ver_string", "")
        self.battery = pi.get("battery_capacity", self.battery)
        self.temp = pi.get("temp", self.temp)
        key = model_key(pm)
        if key:
            self.model = key
            self.log(f"Erkanntes Modell: {pm} (Firmware {self.fw or '?'})", "ok")
        else:
            self.log(f"Modell nicht erkannt ({pm or 'keine Angabe'}).", "warn")
        self.read_access_data()
        self.app.ui(self.app.device_connected, self)

    def read_access_data(self):
        """WLAN-Name/-Passwort und Heimnetz vom Seestar lesen (fehlende Angaben werden übernommen)."""
        r = self.wifi.send("pi_get_ap", quiet=True)
        ap = (r or {}).get("result") if isinstance((r or {}).get("result"), dict) else {}
        if ap.get("ssid"):
            pw = ap.get("passwd") or ""
            if pw.startswith("enc"):                 # neuere Firmware liefert das Passwort verschlüsselt – nie übernehmen
                pw = ""
                if self.ap_pass.startswith("enc"):
                    self.ap_pass = ""                # früher fälschlich übernommenen Wert entfernen
            changed = ap["ssid"] != self.ap_ssid or (pw and pw != self.ap_pass)
            self.ap_ssid = ap["ssid"]
            if pw:
                self.ap_pass = pw
            if changed:
                self.log(f"WLAN-Zugangsdaten vom Seestar übernommen ({self.ap_ssid}).", "ok")
                self.app.ui(self.app.save_devices)
        r = self.wifi.send("pi_station_state", quiet=True)
        st = (r or {}).get("result")
        self.station = st if isinstance(st, dict) else {}

    def on_event(self, ev):
        name = ev.get("Event", "")
        with self._ev_cond:
            self._ev_log.append((time.time(), name, ev.get("state")))
            self._ev_log = self._ev_log[-200:]
            self._ev_cond.notify_all()
        if name == "PiStatus":
            if "battery_capacity" in ev:
                self.battery = ev["battery_capacity"]
                if self.protect and not ev.get("charger_status") in ("Charging", "Full"):
                    for lvl in (20, 10):
                        if self.battery <= lvl and lvl not in self._batt_warned:
                            self._batt_warned.add(lvl)
                            self.app.ui(self.app.battery_warning, self, lvl)
            if "temp" in ev:
                self.temp = ev["temp"]
            if "charger_status" in ev:
                self.charging = ev["charger_status"] in ("Charging", "Full") or bool(ev.get("charge_online"))
            self.app.ui(self.app.device_changed, self)
            if len(ev) <= 4:
                return
        if name == "Setting":                     # Einstellung geändert (auch von der Handy-App) → neu einlesen
            self._setting_ev = time.time()
            if not getattr(self, "_setting_refresh", False):
                self._setting_refresh = True
                def later():
                    try:
                        while time.time() - self._setting_ev < 1.5:
                            time.sleep(0.3)
                        if self.connected:
                            self.refresh_settings()
                    finally:
                        self._setting_refresh = False
                threading.Thread(target=later, daemon=True).start()
        if name == "Stack" and "stacked_frame" in ev:
            self.frames = ev.get("stacked_frame")
        if name == "EqModePA":
            st = ev.get("state", "")
            self.pa_state = st
            if st == "complete" and "x" in ev and "y" in ev:      # 2. complete-Event ohne x/y ignorieren
                self.pa = {"x": float(ev["x"]), "y": float(ev["y"]),
                           "total": float(ev.get("total", math.hypot(ev["x"], ev["y"]))), "t": time.time()}
        self.app.ui(self.app.device_event, self, ev)

    def read_mount_and_tilt(self, quiet=True):
        r = self.wifi.send("get_device_state", {"keys": ["mount", "balance_sensor"]}, quiet=quiet, timeout=5)
        res = _g(r or {}, "result") or {}
        if isinstance(res.get("mount"), dict) and "equ_mode" in res["mount"]:
            self.eq_mode = bool(res["mount"]["equ_mode"])
        b = _g(res, "balance_sensor.data")
        if isinstance(b, dict) and "x" in b and "y" in b:
            self.tilt = (float(b.get("x", 0)), float(b.get("y", 0)), b.get("angle"))
        return res

    # -- Abläufe
    def wait_event(self, names, states=("complete", "fail"), timeout=300, since=None, abort=None):
        """Wartet auf ein Ereignis (z. B. AutoGoto complete). Gibt state oder None (Timeout/Abbruch)."""
        since = since or time.time()
        end = time.time() + timeout
        with self._ev_cond:
            while time.time() < end:
                for t, n, st in reversed(self._ev_log):
                    if t >= since and n in names and (states is None or st in states):
                        return st
                if abort and abort():
                    return None
                self._ev_cond.wait(1.0)
        return None

    def send_variants(self, variants, quiet=False):
        """Probiert Befehlsvarianten (unterschiedliche Firmware) bis eine mit code 0 angenommen wird."""
        last = None
        for method, params in variants:
            r = self.wifi.send(method, params, quiet=quiet)
            last = r
            if isinstance(r, dict) and r.get("code", 0) in (0, None) and "error" not in r:
                return r
        return last

    def refresh_settings(self):
        r = self.wifi.send("get_setting", quiet=True)
        res = r.get("result") if isinstance(r, dict) and isinstance(r.get("result"), dict) else None
        if res is None:
            return False
        r2 = self.wifi.send("get_stack_setting", quiet=True)
        if isinstance(r2, dict) and isinstance(r2.get("result"), dict):
            res.setdefault("stack", {})
            for k, v in r2["result"].items():
                res["stack"].setdefault(k, v)
        r3 = self.wifi.send("get_device_state", quiet=True)
        ds = _g(r3 or {}, "result")
        if isinstance(ds, dict):
            st = ds.get("setting")
            if isinstance(st, dict):
                for k in ("heater", "heater_enable"):
                    if k in st:                                  # Gerätezustand ist maßgeblich (wie Seestar-App)
                        res[k] = st[k]
            res["_camera"] = ds.get("camera") or {}               # Gain steht bei der Kamera (Firmware 9.x)
            self.update_device_info(ds)
        self.settings = res
        for key, _sec, _lbl, _opts, getter, _setter, _only in SETTINGS:
            try:
                v = getter(res)
            except Exception:
                v = None
            if v is not None:
                self.values[key] = v
        self.app.ui(self.app.device_settings_loaded, self)
        return True

    def apply_setting(self, key, value):
        if key == "exp" and value == 60000 and self.eq_mode is False:
            self.log("60 s übersprungen – Gerät ist im Alt-Az-Modus (60 s nur im EQ-Modus).", "warn")
            return False
        if self.protect and key in ARM_CLOSE_SETTINGS and value:
            self.log(f"„{SETTING_LABEL.get(key, key)}“ bleibt aus – Arm-Schutz aktiv ({self.protect_reason()}).", "warn")
            self.values[key] = False
            self.app.ui(self.app.device_settings_loaded, self)
            return False
        if key in ("auto_af", "af_before") and value and getattr(self, "ext_filter", NO_FILTER) != NO_FILTER:
            self.log(f"„{SETTING_LABEL.get(key, key)}“ bleibt aus – hinter dem Filter scheitert der Seestar-Autofokus. "
                     f"Nutze den App-Autofokus (Tab „Fokus & Filter“).", "warn")
            self.values[key] = False
            self.app.ui(self.app.device_settings_loaded, self)
            return False
        spec = next(x for x in SETTINGS if x[0] == key)
        old = self.values.get(key)
        self.values[key] = value
        self.app.ui(self.app.device_settings_loaded, self)     # alle Ansichten (Tab + Fenster) sofort gleich
        r = self.send_variants(spec[5](value, self.values))
        ok = isinstance(r, dict) and r.get("code", 0) in (0, None) and "error" not in r
        if not ok:
            self.log(f"Einstellung „{key}“ wurde nicht angenommen: {r}", "warn")
            if old is None:
                self.values.pop(key, None)                 # Anzeige zeigt wieder den echten Gerätestand
            else:
                self.values[key] = old
            self.app.ui(self.app.device_settings_loaded, self)
        else:
            self._verify_later(key, value, spec)
        return ok

    def _verify_later(self, key, value, spec):
        """Nach dem Setzen vom Gerät zurücklesen: Manche Firmware quittiert mit code 0, übernimmt den Wert aber
        nicht (z. B. DBE, Tauheizung bei 9.75). Dann zeigt die App den echten Stand und sagt es deutlich."""
        self._verify_tok = tok = time.time()

        def job():
            time.sleep(1.5)
            if getattr(self, "_verify_tok", None) != tok or not self.connected:
                return
            if not self.refresh_settings():
                return
            got = self.values.get(key)
            if got is None or got == value:
                return
            names = {v: lbl for lbl, v in spec[3]} if isinstance(spec[3], list) else {}
            self.log(f"„{SETTING_LABEL.get(key, key)}“: Das Seestar hat den Befehl bestätigt, zeigt aber weiterhin "
                     f"„{names.get(got, got)}“. Bitte diesen Schalter vorerst in der Seestar-App umstellen – "
                     f"die App zeigt den echten Stand an.", "warn")
        threading.Thread(target=job, daemon=True).start()

    def flush_pending(self):
        """Offline vorgenommene Änderungen nach dem Verbinden senden."""
        if not self.pending:
            return
        todo, self.pending = dict(self.pending), {}
        sent = 0
        for key, _s, _l, _o, _g, _st, only in SETTINGS:
            if key in todo and (only is None or only(self.model)):
                sent += bool(self.apply_setting(key, todo[key]))
        self.log(f"{sent} offline geänderte Einstellung(en) an das Gerät übertragen.", "ok")
        self.app.ui(self.app.save_devices)
        self.refresh_settings()

    # -- Bildkanal
    def ensure_imager(self):
        if not self.imager:
            return False
        return self.imager.connected or self.imager.connect(self.host)

    def view_running(self):
        """Läuft auf dem Seestar eine Ansicht (Sterne/Mond/Sonne …)? None = unbekannt."""
        r = self.wifi.send("get_view_state", quiet=True, timeout=4)
        v = _g(r or {}, "result.View")
        if isinstance(v, dict):
            return v.get("state") in ("working", "running", "start"), v.get("mode")
        return None, None

    def preview_live(self):
        """Live-Bild starten. Läuft auf dem Seestar keine Ansicht (z. B. nach Planende), startet die App sie selbst –
        sonst käme nur ein einziges Bild und es sähe so aus, als wäre die App kaputt."""
        if not self.ensure_imager():
            return
        running, _mode = self.view_running()
        if running is False:
            r = self.wifi.send("get_device_state", {"keys": ["mount"]}, quiet=True, timeout=4)
            closed = bool(_g(r or {}, "result.mount.close", False))
            if closed:
                if self.protect:
                    self.log("Live-Vorschau: Der Arm ist geschlossen, wegen Arm-Schutz öffnet die App ihn nicht. "
                             "Bitte erst Filter/Taukappe abnehmen oder den Arm im Tab „Steuerung“ öffnen.", "warn")
                    return
                if not self.app.ask_sync(f"„{self.name}“: Der Arm ist geschlossen.\n\n"
                                         "Arm öffnen und Sternenmodus starten, damit Live-Bilder kommen?"):
                    return
                self.log("Öffne den Arm und starte den Sternenmodus für die Live-Vorschau …")
                self.open_arm("star")
            else:
                self.log("Sternenmodus war aus – starte ihn für die Live-Vorschau …")
                self.wifi.send("iscope_start_view", {"mode": "star"})
        self.imager.last_frame = 0
        self.imager.start_preview()
        self.log("Live-Vorschau angefordert (Seestar muss im Sternen-/Mondmodus sein).")
        self._live_token = token = time.time()

        def watchdog():
            t0, retried = time.time(), 0
            while self.imager and self.imager.streaming and getattr(self, "_live_token", None) == token:
                time.sleep(2)
                last = getattr(self.imager, "last_frame", 0) or t0
                if time.time() - last > 8:
                    self.app.ui(self.app.preview_waiting, self)
                    if retried < 3:
                        retried += 1
                        if retried == 2 and self.view_running()[0] is False:
                            self.wifi.send("iscope_start_view", {"mode": "star"}, quiet=True)
                        self.imager.start_preview()
                        t0 = time.time()
                        if retried == 3:
                            self.log("Seit einiger Zeit kommt kein neues Live-Bild. Steht das Seestar im Sternen-/Mondmodus "
                                     "und ist es noch verbunden?", "warn")
        threading.Thread(target=watchdog, daemon=True).start()

    def preview_stack(self, quiet=False):
        if self.ensure_imager():
            if self.imager.streaming:
                self.imager.stop_preview()
            self.imager.request_stack()
            if not quiet:
                self.log("Aktuelles Stack-Bild angefordert …")

    def preview_stop(self):
        self._live_token = None
        if self.imager and self.imager.connected:
            self.imager.stop_preview()

    def wants_auto_stack(self):
        return any(p.auto_stack_flag for p in self.panels) and not (self.imager and self.imager.streaming)

    def on_frame(self, kind, rgb, w, h):
        for cb in list(self.frame_listeners):
            try:
                cb(kind, rgb)
            except Exception:
                pass
        step = max(1, int(np.ceil(max(rgb.shape[:2]) / 1600)))
        small = np.ascontiguousarray(rgb[::step, ::step])
        for p in list(self.panels):
            p.offer(kind, small, w, h)


# --------------------------------------------------------------------------
# Externe Filter & Präzisions-Autofokus
# Ein Filter VOR dem Objektiv verschiebt den Fokus praktisch nicht (paralleler Strahlengang).
# Das Problem ist der Seestar-Autofokus: kurze Belichtung + dunkler Filter = zu wenig Sterne.
# Darum: eigener Autofokus mit längerer Belichtung, Schärfe (HFR) aus den Live-Bildern,
# V-Kurve, Spielausgleich; beste Position wird pro Gerät und Filter gemerkt.
# --------------------------------------------------------------------------
# light: 1 = hell … 4 = sehr dunkel  ->  Belichtung/Mittelung der Live-Bilder für den App-Autofokus
NO_FILTER = "Kein externer Filter"
BB, UVIR, UHC, DUAL, TRI, QUAD, LINE = ("Breitband-LP", "UV/IR-Sperrfilter", "Nebelfilter (UHC)", "Dual-Band",
                                        "Tri-Band", "Quad-Band", "Einzel-Linie")
CLEAR, RGBF, IRP, PHOT, NDF, SPEC = ("Klarglas (Clear)", "Farbfilter R/G/B", "IR-Pass / Planeten", "Photometrie",
                                    "Mond / Neutraldichte", "Spezialfilter")
FILTER_KINDS = [BB, UVIR, UHC, DUAL, TRI, QUAD, LINE, CLEAR, RGBF, IRP, PHOT, NDF, SPEC]
# (Marke, Modell, Art, Durchlass, engste Bandbreite in nm oder None, Quelle)
#  Quelle "H" = Herstellerangabe geprüft · "T" = übliche Handels-/Typangabe (Datenblatt prüfen)
FILTER_DB = [
    # Optolong
    ("Optolong", "L-Pro", BB, "breitbandig, dämpft Natrium-/Quecksilberlinien", None, "T"),
    ("Optolong", "L-eNhance", TRI, "Hα 10 nm · Hβ+OIII ca. 24 nm", 10, "T"),
    ("Optolong", "L-eXtreme", DUAL, "Hα 656,3 + OIII 500,7 nm, je 7 nm", 7, "H"),
    ("Optolong", "L-eXtreme F2", DUAL, "Hα + OIII je 7 nm, für sehr schnelle Optik", 7, "H"),
    ("Optolong", "L-Ultimate", DUAL, "Hα + OIII je 3 nm", 3, "H"),
    ("Optolong", "L-Synergy", DUAL, "SII + OIII je 7 nm", 7, "H"),
    ("Optolong", "L-Para", DUAL, "Hα + OIII je 10 nm", 10, "H"),
    ("Optolong", "L-QEF (L-Quad Enhance)", QUAD, "Hβ, OIII, Hα, SII – breite Bänder", None, "H"),
    ("Optolong", "CLS", BB, "City Light Suppression", None, "T"),
    ("Optolong", "CLS-CCD", BB, "City Light Suppression mit IR-Sperre", None, "T"),
    ("Optolong", "UHC", UHC, "Hβ+OIII und Hα", None, "T"),
    ("Optolong", "Moon & Skyglow", BB, "Neodym-Typ, dämpft Natriumlicht", None, "T"),
    ("Optolong", "UV/IR-Cut", UVIR, "sperrt UV und IR", None, "H"),
    ("Optolong", "H-Alpha 7 nm", LINE, "Hα 7 nm", 7, "T"),
    ("Optolong", "H-Alpha 3 nm", LINE, "Hα 3 nm", 3, "H"),
    ("Optolong", "OIII 6,5 nm", LINE, "OIII 6,5 nm", 6.5, "T"),
    ("Optolong", "OIII 3 nm", LINE, "OIII 3 nm", 3, "H"),
    ("Optolong", "SII 6,5 nm", LINE, "SII 6,5 nm", 6.5, "T"),
    ("Optolong", "SII 3 nm", LINE, "SII 3 nm", 3, "H"),
    ("Optolong", "H-Beta", LINE, "Hβ (eher visuell)", None, "T"),
    # Svbony
    ("Svbony", "SV220 Hα/OIII 7 nm", DUAL, "Hα 656 + OIII 501 nm, je 7 nm", 7, "H"),
    ("Svbony", "SV220 Hα/OIII 3 nm", DUAL, "Hα + OIII je 3 nm", 3, "H"),
    ("Svbony", "SV220 SII/OIII 7 nm", DUAL, "SII + OIII je 7 nm", 7, "H"),
    ("Svbony", "UHC", UHC, "Hβ+OIII und Hα", None, "T"),
    ("Svbony", "CLS", BB, "City Light Suppression", None, "T"),
    ("Svbony", "SV240 Multi-Narrowband", QUAD, "Hβ 486 · OIII 496/501 · Hα 656 · NIR 830–870 nm", 20, "H"),
    ("Svbony", "SV260 Multi-Bandpass", BB, "5 Durchlassbereiche, breitbandiger Lichtverschmutzungsfilter", None, "H"),
    ("Svbony", "SV227 Hα 5 nm", LINE, "Hα 5 nm", 5, "H"),
    ("Svbony", "SV227 OIII 5 nm", LINE, "OIII 5 nm", 5, "H"),
    ("Svbony", "SV227 SII 5 nm", LINE, "SII 5 nm", 5, "H"),
    ("Svbony", "OIII 18 nm", LINE, "OIII 18 nm (eher visuell)", 18, "T"),
    ("Svbony", "UV/IR-Cut", UVIR, "sperrt UV und IR", None, "H"),
    ("Svbony", "SV231 Fringe Killer", BB, "Farbsaum-Korrektur für Mond und Planeten (eher visuell)", None, "T"),
    ("Svbony", "Linear-Polfilter", BB, "dämpft helles Mondlicht (eher visuell)", None, "T"),
    # Antlia
    ("Antlia", "ALP-T Dual Band 5 nm", DUAL, "Hα + OIII je 5 nm", 5, "H"),
    ("Antlia", "ALP-T Dual Band 3 nm", DUAL, "Hα + OIII je 3 nm", 3, "H"),
    ("Antlia", "Triband RGB Ultra (II)", TRI, "Hα+NII, SII, OIII", None, "H"),
    ("Antlia", "Quad Band Anti-Light-Pollution", QUAD, "vier Nebellinien, breit", None, "H"),
    ("Antlia", "V-Pro", BB, "Breitband-Lichtverschmutzungsfilter", None, "T"),
    ("Antlia", "H-Alpha 3 nm Pro", LINE, "Hα 3 nm", 3, "T"),
    ("Antlia", "OIII 3 nm Pro", LINE, "OIII 3 nm", 3, "T"),
    ("Antlia", "SII 3 nm Pro", LINE, "SII 3 nm", 3, "T"),
    ("Antlia", "H-Beta 3 nm Pro", LINE, "Hβ 3 nm", 3, "H"),
    ("Antlia", "H-Alpha 2,5 nm Ultra", LINE, "Hα 2,5 nm", 2.5, "H"),
    ("Antlia", "OIII 2,5 nm Ultra", LINE, "OIII 2,5 nm", 2.5, "H"),
    # ZWO
    ("ZWO", "Duo-Band", DUAL, "Hα 15 nm + OIII 35 nm", 15, "H"),
    ("ZWO", "H-Alpha 7 nm", LINE, "Hα 7 nm", 7, "T"),
    ("ZWO", "OIII 7 nm", LINE, "OIII 7 nm", 7, "T"),
    ("ZWO", "SII 7 nm", LINE, "SII 7 nm", 7, "T"),
    ("ZWO", "UV/IR-Cut", UVIR, "sperrt UV und IR", None, "T"),
    ("ZWO", "IR-Cut", UVIR, "sperrt IR", None, "T"),
    # IDAS
    ("IDAS", "LPS-D1", BB, "Breitband-LP, IR-Sperre", None, "H"),
    ("IDAS", "LPS-D2", BB, "Breitband-LP für LED-Licht, IR-Sperre", None, "H"),
    ("IDAS", "LPS-D3 (NGS1)", BB, "Breitband-LP, IR-Sperre", None, "H"),
    ("IDAS", "LPS-P2", BB, "Breitband-LP", None, "H"),
    ("IDAS", "LPS-V4", UHC, "Nebelfilter, IR-Sperre", None, "H"),
    ("IDAS", "NB1", TRI, "Hα, Hβ, OIII", None, "H"),
    ("IDAS", "NB2", DUAL, "Hα + OIII, 20 nm", 20, "H"),
    ("IDAS", "NB3", DUAL, "OIII + SII, 20 nm", 20, "H"),
    ("IDAS", "NBZ", DUAL, "Hα + OIII/Hβ, 12 nm", 12, "H"),
    # STC
    ("STC", "Astro Duo-Narrowband", DUAL, "Hα + OIII, 7–12 nm", 7, "H"),
    ("STC", "Astro-Multispectra", BB, "Breitband-LP", None, "T"),
    # Altair
    ("Altair", "DualBand Hα/OIII 6 nm", DUAL, "Hα + OIII je 6 nm", 6, "H"),
    ("Altair", "DualBand 4,5 nm", DUAL, "Hα + OIII je 4,5 nm", 4.5, "H"),
    ("Altair", "DualBand Ultra SII/OIII 4 nm", DUAL, "SII + OIII je 4 nm", 4, "H"),
    ("Altair", "TriBand V2", TRI, "Hα · Hβ+OIII", None, "H"),
    ("Altair", "QuadBand V2", QUAD, "495 nm und 660 nm, je 35 nm", 35, "H"),
    # Radian
    ("Radian", "Triad Ultra", QUAD, "Hβ 5 nm, OIII 4 nm, Hα 4 nm, SII 4 nm", 4, "H"),
    # Askar
    ("Askar", "Colour Magic C1 (Hα+OIII)", DUAL, "Hα + OIII, breit", None, "H"),
    ("Askar", "Colour Magic C2 (SII+OIII)", DUAL, "SII 15 nm + OIII 35 nm", 15, "H"),
    ("Askar", "Colour Magic D1 (Hα+OIII)", DUAL, "OIII 6,5 nm + Hα 8,5 nm", 6.5, "H"),
    ("Askar", "Colour Magic D2 (SII+OIII)", DUAL, "OIII 6,5 nm + SII 8,5 nm", 6.5, "H"),
    ("Askar", "Colour Magic Ultra E1 (Hα+OIII)", DUAL, "Hα + OIII je 3 nm", 3, "H"),
    ("Askar", "Colour Magic Ultra E2 (SII+OIII)", DUAL, "SII + OIII je 3 nm", 3, "H"),
    # Baader
    ("Baader", "UHC-S", UHC, "Nebelfilter, recht breit", None, "T"),
    ("Baader", "Moon & Skyglow", BB, "Neodym, dämpft Natriumlicht", None, "T"),
    ("Baader", "Neodymium", BB, "Neodym, dämpft Natriumlicht", None, "T"),
    ("Baader", "UV/IR-Cut L", UVIR, "sperrt UV und IR", None, "H"),
    ("Baader", "H-Alpha 6,5 nm CMOS", LINE, "Hα 6,5 nm", 6.5, "T"),
    ("Baader", "OIII 6,5 nm CMOS", LINE, "OIII 6,5 nm", 6.5, "T"),
    ("Baader", "SII 6,5 nm CMOS", LINE, "SII 6,5 nm", 6.5, "T"),
    ("Baader", "H-Alpha Ultra-Narrowband CMOS", LINE, "Hα 656,3 nm, 3,5–4 nm", 3.5, "H"),
    ("Baader", "OIII Ultra-Narrowband CMOS", LINE, "OIII 500,7 nm, 3,5–4 nm", 3.5, "H"),
    ("Baader", "SII Ultra-Narrowband CMOS", LINE, "SII 671,7 nm, 3,5–4 nm", 3.5, "H"),
    # Astronomik
    ("Astronomik", "CLS", BB, "City Light Suppression", None, "H"),
    ("Astronomik", "CLS-CCD", BB, "City Light Suppression mit IR-Sperre", None, "H"),
    ("Astronomik", "UHC", UHC, "Nebelfilter", None, "H"),
    ("Astronomik", "UHC-E", UHC, "Nebelfilter, etwas breiter", None, "H"),
    ("Astronomik", "L-1 UV-IR Block", UVIR, "sperrt UV und IR", None, "T"),
    ("Astronomik", "L-2 UV-IR Block", UVIR, "sperrt UV und IR", None, "T"),
    ("Astronomik", "L-3 UV-IR Block", UVIR, "sperrt UV und IR", None, "T"),
    ("Astronomik", "H-Alpha 6 nm (auch MaxFR)", LINE, "Hα 6 nm", 6, "H"),
    ("Astronomik", "OIII 6 nm (auch MaxFR)", LINE, "OIII 6 nm", 6, "H"),
    ("Astronomik", "SII 6 nm (auch MaxFR)", LINE, "SII 6 nm", 6, "H"),
    ("Astronomik", "H-Alpha 12 nm (auch MaxFR)", LINE, "Hα 12 nm", 12, "H"),
    ("Astronomik", "OIII 12 nm (auch MaxFR)", LINE, "OIII 12 nm", 12, "H"),
    ("Astronomik", "SII 12 nm (auch MaxFR)", LINE, "SII 12 nm", 12, "H"),
    # visuell gedachte Nebelfilter anderer Marken
    ("Lumicon", "UHC", UHC, "Nebelfilter (visuell)", None, "T"),
    ("Lumicon", "OIII", LINE, "OIII, breit (visuell)", None, "T"),
    ("Lumicon", "H-Beta", LINE, "Hβ, breit (visuell)", None, "T"),
    ("Explore Scientific", "UHC", UHC, "Nebelfilter (visuell)", None, "T"),
    ("Explore Scientific", "OIII", LINE, "OIII, breit (visuell)", None, "T"),
    ("Celestron", "UHC/LPR", UHC, "Nebelfilter", None, "T"),
    ("Orion", "UltraBlock", UHC, "Nebelfilter (visuell)", None, "T"),
    ("Orion", "SkyGlow", BB, "Breitband-LP", None, "T"),
    ("Omegon", "UHC", UHC, "Nebelfilter", None, "T"),
    ("Omegon", "CLS", BB, "City Light Suppression", None, "T"),
    ("TS-Optics", "UHC", UHC, "Nebelfilter", None, "T"),
    ("TS-Optics", "CLS", BB, "City Light Suppression", None, "T"),
    # ---- weitere 2"-Filter (Stand 11/2026; Bandbreiten laut Hersteller/Handel, Datenblatt prüfen) ----
    # Klarglas / Luminanz
    ("Baader", "Clear", CLEAR, "planparalleles Klarglas, hält den Fokus gleich wie mit Filter", None, "H"),
    ("Astronomik", "MC-clear", CLEAR, "Klarglas, mehrschichtvergütet", None, "H"),
    ("IDAS", "Clear ODW", CLEAR, "Klarglas", None, "T"),
    ("Astronomik", "OWB L Typ 3", UVIR, "Luminanz, UV/IR-Sperre", None, "H"),
    ("Astronomik", "IR-Block", UVIR, "sperrt IR", None, "H"),
    ("Astronomik", "L Typ 2c", UVIR, "Luminanz aus dem L-RGB-Satz", None, "H"),
    ("Baader", "L CMOS", UVIR, "Luminanz aus dem LRGB-CMOS-Satz", None, "H"),
    ("Optolong", "L", UVIR, "Luminanz aus dem LRGB-Satz", None, "T"),
    ("Antlia", "L V-Pro", UVIR, "Luminanz aus dem LRGB-V-Pro-Satz", None, "T"),
    ("Chroma", "L", UVIR, "Luminanz aus dem LRGB-Satz", None, "T"),
    ("ZWO", "L", UVIR, "Luminanz aus dem LRGB-Satz", None, "T"),
    # Farbfilter R/G/B (für Mono-Kameras)
    ("Baader", "R CMOS", RGBF, "Rot", None, "H"), ("Baader", "G CMOS", RGBF, "Grün", None, "H"), ("Baader", "B CMOS", RGBF, "Blau", None, "H"),
    ("Astronomik", "R Typ 2c", RGBF, "Rot", None, "H"), ("Astronomik", "G Typ 2c", RGBF, "Grün", None, "H"), ("Astronomik", "B Typ 2c", RGBF, "Blau", None, "H"),
    ("Optolong", "R", RGBF, "Rot", None, "T"), ("Optolong", "G", RGBF, "Grün", None, "T"), ("Optolong", "B", RGBF, "Blau", None, "T"),
    ("Antlia", "R V-Pro", RGBF, "Rot", None, "T"), ("Antlia", "G V-Pro", RGBF, "Grün", None, "T"), ("Antlia", "B V-Pro", RGBF, "Blau", None, "T"),
    ("Chroma", "R", RGBF, "Rot", None, "T"), ("Chroma", "G", RGBF, "Grün", None, "T"), ("Chroma", "B", RGBF, "Blau", None, "T"),
    ("ZWO", "R", RGBF, "Rot", None, "T"), ("ZWO", "G", RGBF, "Grün", None, "T"), ("ZWO", "B", RGBF, "Blau", None, "T"),
    # Schmalband – weitere
    ("Chroma", "H-Alpha 3 nm", LINE, "Hα 3 nm", 3, "H"), ("Chroma", "OIII 3 nm", LINE, "OIII 3 nm", 3, "H"),
    ("Chroma", "SII 3 nm", LINE, "SII 3 nm", 3, "H"), ("Chroma", "H-Alpha 5 nm", LINE, "Hα 5 nm", 5, "H"),
    ("Chroma", "OIII 5 nm", LINE, "OIII 5 nm", 5, "H"), ("Chroma", "SII 5 nm", LINE, "SII 5 nm", 5, "H"),
    ("Chroma", "H-Alpha 8 nm", LINE, "Hα 8 nm", 8, "H"), ("Chroma", "OIII 8 nm", LINE, "OIII 8 nm", 8, "H"),
    ("Chroma", "SII 8 nm", LINE, "SII 8 nm", 8, "H"),
    ("Chroma", "LoGlow", BB, "Breitband-Lichtverschmutzungsfilter", None, "H"),
    ("Antlia", "SII 2,5 nm Ultra", LINE, "SII 2,5 nm", 2.5, "H"),
    ("Antlia", "Edge OIII 4,5 nm", LINE, "OIII 4,5 nm", 4.5, "H"),
    ("Baader", "H-Beta CMOS", LINE, "Hβ, CMOS-optimiert", None, "H"),
    ("Baader", "H-Alpha 6,5 nm f/2 Highspeed", LINE, "Hα, für sehr schnelle Optik (f/2–f/3)", 6.5, "T"),
    ("Baader", "OIII f/2 Highspeed", LINE, "OIII, für sehr schnelle Optik", None, "T"),
    ("Baader", "SII f/2 Highspeed", LINE, "SII, für sehr schnelle Optik", None, "T"),
    ("Baader", "H-Alpha f/2 Ultra-Highspeed", LINE, "Hα schmal, für f/2", 4, "T"),
    ("Baader", "OIII f/2 Ultra-Highspeed", LINE, "OIII schmal, für f/2", 4, "T"),
    ("Baader", "SII f/2 Ultra-Highspeed", LINE, "SII schmal, für f/2", 4, "T"),
    ("Baader", "H-Alpha f/3 Ultra-Highspeed", LINE, "Hα schmal, für f/3", 4, "T"),
    ("Baader", "OIII f/3 Ultra-Highspeed", LINE, "OIII schmal, für f/3", 4, "T"),
    ("Baader", "SII f/3 Ultra-Highspeed", LINE, "SII schmal, für f/3", 4, "T"),
    ("Baader", "H-Alpha 20 nm", LINE, "Hα 20 nm (älteres Modell)", 20, "T"),
    ("Astronomik", "H-Beta CCD", LINE, "Hβ", None, "H"),
    ("IDAS", "NBZ-II", DUAL, "Hα + OIII je 10 nm", 10, "T"),
    ("Player One", "Anti-Halo PRO Dual-Band Hα+OIII", DUAL, "Hα + OIII, gegen Halos um helle Sterne", None, "T"),
    ("Svbony", "SV220 Hα/OIII 3 nm (2\")", DUAL, "Hα + OIII je 3 nm", 3, "H"),
    # IR-Pass / Planeten / Mond
    ("Baader", "IR-Pass 685 nm", IRP, "lässt nur Licht über 685 nm durch – Mond, Planeten, ruhigeres Bild", None, "H"),
    ("Astronomik", "ProPlanet 642 BP", IRP, "642–842 nm, Mond und Planeten", None, "H"),
    ("Astronomik", "ProPlanet 742", IRP, "ab 742 nm, Mond und Planeten", None, "H"),
    ("Astronomik", "ProPlanet 807", IRP, "ab 807 nm, Mond und Planeten", None, "H"),
    ("Baader", "U-Venus", SPEC, "UV 320–380 nm für Wolken auf der Venus", None, "H"),
    ("Baader", "C2 Swan-Band 15 nm", SPEC, "Kometen (C2-Swan-Band)", 15, "T"),
    ("Baader", "ND OD 0,6 (25 %)", NDF, "dämpft gleichmäßig – heller Mond", None, "H"),
    ("Baader", "ND OD 0,9 (12,5 %)", NDF, "dämpft gleichmäßig – heller Mond", None, "H"),
    ("Baader", "ND OD 3,0 (0,1 %)", NDF, "stark dämpfend – KEIN Sonnenfilter!", None, "H"),
    ("Baader", "Polfilter (zweiteilig)", NDF, "variable Dämpfung für den Mond", None, "H"),
    ("Baader", "Contrast Booster", BB, "Farbsaum-Minderung (eher visuell)", None, "T"),
    ("Baader", "Semi-APO", BB, "Farbsaum-Minderung (eher visuell)", None, "T"),
    # Photometrie (wissenschaftlich, für Mono-Kameras)
    ("Baader", "Bessel U", PHOT, "UBVRI-Photometrie U", None, "H"), ("Baader", "Bessel B", PHOT, "UBVRI-Photometrie B", None, "H"),
    ("Baader", "Bessel V", PHOT, "UBVRI-Photometrie V", None, "H"), ("Baader", "Bessel R", PHOT, "UBVRI-Photometrie R", None, "H"),
    ("Baader", "Bessel I", PHOT, "UBVRI-Photometrie I", None, "H"),
    ("Baader", "Sloan/SDSS u'g'r'i'z'", PHOT, "Sloan-Photometrie (Satz)", None, "H"),
    ("Optolong", "UBVRI (Satz)", PHOT, "Photometrie-Satz", None, "T"),
    ("Chroma", "U-Bessel", PHOT, "Photometrie U", None, "T"),
]


def light_class(kind, nm, lines=""):
    """Wie dunkel ist der Filter für den Farbsensor des Seestar? 1 hell … 4 sehr dunkel."""
    if kind in (BB, UVIR, CLEAR):
        c = 1
    elif kind in (RGBF, NDF):
        c = 2
    elif kind in (IRP, PHOT, SPEC):
        c = 3
    elif kind == UHC:
        c = 2
    elif nm is None:
        c = 2 if kind in (QUAD, TRI, DUAL) else 3
    elif nm >= 15:
        c = 2
    elif nm > 4.5:
        c = 3
    else:
        c = 3 if kind in (TRI, QUAD) else 4
    if kind == LINE:                       # nur ein Farbkanal des Bayer-Sensors bekommt Licht
        c = min(4, c + 1)
    return c


def _filter_entry(brand, model, kind, band, nm, src, custom=False):
    light = light_class(kind, nm)
    if kind == LINE:
        red = any(x in band for x in ("Hα", "SII"))
        hint = ("Einzellinien-Filter am Farbsensor: nur die roten Pixel bekommen Licht, das Bild wird einfarbig "
                "und deutlich dunkler. Für den Seestar sind Dual-Band-Filter meist die bessere Wahl." if red else
                "Einzellinien-Filter am Farbsensor: nur die grünen und blauen Pixel bekommen Licht, das Bild wird "
                "einfarbig und deutlich dunkler. Für den Seestar sind Dual-Band-Filter meist die bessere Wahl.")
    elif kind == CLEAR:
        hint = ("Klarglas ändert die Farbe nicht, hält aber den Fokus gleich wie mit einem gleich dicken Filter – "
                "ideal für den leeren Platz im Filterrad.")
    elif kind == RGBF:
        hint = ("Farbfilter für Mono-Kameras (LRGB). An einer Farbkamera wie Seestar oder ASI585MC nicht sinnvoll – "
                "das Bild wird nur einfarbig und dunkler.")
    elif kind == PHOT:
        hint = "Wissenschaftliche Photometrie-Filter, gedacht für Mono-Kameras – für schöne Bilder nicht geeignet."
    elif kind == IRP:
        hint = "Für Mond und Planeten (ruhigeres Bild bei Luftunruhe). Für Nebel und Galaxien nicht geeignet."
    elif kind == NDF:
        hint = "Dämpft nur – für den hellen Mond. Kein Sonnenfilter: nie damit in die Sonne!"
    elif kind == SPEC:
        hint = "Spezialfilter für ein bestimmtes Objekt (Venus, Kometen) – nur dafür verwenden."
    elif kind in (BB, UVIR):
        hint = "Hell genug – der Seestar-Autofokus funktioniert normalerweise."
    elif light >= 4:
        hint = "Sehr dunkel – nur App-Autofokus mit langer Belichtung; für 10-s-Frames oft zu wenig Licht (EQ + 30–60 s)."
    elif light == 3:
        hint = "Seestar-Autofokus scheitert oft – App-Autofokus nutzen."
    else:
        hint = "Seestar-Autofokus klappt teils; App-Autofokus ist zuverlässiger."
    if "visuell" in band:
        hint += " Eigentlich für die visuelle Beobachtung gebaut – fotografisch oft zu breit und mit Reflexen."
    return {"marke": brand, "modell": model, "art": kind, "band": band, "nm": nm, "light": light,
            "lp_intern": None if kind in (BB, UVIR, CLEAR) else False, "hinweis": hint, "quelle": src, "eigen": custom}


FILTERS = {NO_FILTER: {"marke": "–", "modell": NO_FILTER, "art": "–", "band": "", "nm": None, "light": 1,
                       "lp_intern": None, "hinweis": "Seestar-Autofokus funktioniert normal.", "quelle": "", "eigen": False}}
for _b, _m, _k, _band, _nm, _src in FILTER_DB:
    FILTERS[f"{_b} {_m}"] = _filter_entry(_b, _m, _k, _band, _nm, _src)


def filter_brands():
    return sorted({v["marke"] for k, v in FILTERS.items() if k != NO_FILTER}, key=str.lower)


def filter_fit_note(model):
    """Passt ein 2"-Filter vor das Objektiv? (alle Seestar haben einen Farbsensor)"""
    if model in ("S50", "S50 Pro"):
        return ("2\"-Filter (freie Öffnung meist um 46–48 mm) blenden die 50-mm-Öffnung minimal ab – "
                "praktisch kaum Lichtverlust.")
    if model in ("S30", "S30 Pro"):
        return "2\"-Filter decken die 30-mm-Öffnung vollständig ab."
    return "2\"-Filter passen mit passendem Halter an alle Seestar-Modelle."


AF_EXP_MS = {1: 1000, 2: 2000, 3: 3000, 4: 5000}       # Live-Bild-Belichtung für den App-Autofokus
AF_FRAMES = {1: 1, 2: 2, 3: 3, 4: 6}                   # gemittelte Bilder pro Fokusposition


def _maxfilter(a, r):
    out = a.copy()
    p = np.pad(a, r, mode="edge")
    h, w = a.shape
    for dy in range(2 * r + 1):
        for dx in range(2 * r + 1):
            np.maximum(out, p[dy:dy + h, dx:dx + w], out=out)
    return out


def measure_hfr(rgb, max_stars=60):
    """Median-HFR (Pixel) der Sterne im Bild und Anzahl Sterne. None, wenn zu wenige Sterne."""
    g = rgb.mean(axis=2) if rgb.ndim == 3 else rgb
    g = g.astype(np.float32)
    # 3×3-Glättung nur für die Sternsuche: hebt schwache Sterne aus dem Rauschen (Schmalband!)
    p = np.pad(g, 1, mode="edge")
    sm = sum(p[dy:dy + g.shape[0], dx:dx + g.shape[1]] for dy in range(3) for dx in range(3)) / 9.0
    bg = float(np.median(sm[::4, ::4]))
    sig = float(np.median(np.abs(sm[::4, ::4] - bg))) * 1.4826 + 1e-9
    thr = bg + 5 * sig
    lbg = float(np.median(g[::4, ::4]))
    raw_sig = float(np.median(np.abs(g[::4, ::4] - lbg))) * 1.4826 + 1e-9
    mx = _maxfilter(sm, 3)
    ys, xs = np.nonzero((sm >= mx) & (sm > thr))
    R = 12
    h, w = g.shape
    keep = (ys > R) & (ys < h - R - 1) & (xs > R) & (xs < w - R - 1)
    ys, xs = ys[keep], xs[keep]
    if len(ys) == 0:
        return None, 0
    peak = g[ys, xs]
    order = np.argsort(-peak)
    yy, xx = np.mgrid[-R:R + 1, -R:R + 1]
    hfrs = []
    for k in order[: max_stars * 3]:
        y, x = ys[k], xs[k]
        if g[y, x] > 0.97:                     # gesättigt – unbrauchbar
            continue
        if sm[y, x] - bg < 8 * sig:                # zu schwach für eine saubere Messung
            continue
        win = sm[y - R:y + R + 1, x - R:x + R + 1] - bg
        win[win < max(3 * sig, 0.1 * (sm[y, x] - bg))] = 0   # nur Sternlicht, keine Rauschspitzen
        tot = float(win.sum())
        if tot <= 0:
            continue
        cy = float((win * yy).sum() / tot)
        cx = float((win * xx).sum() / tot)
        r = np.hypot(yy - cy, xx - cx)
        hfr = float((win * r).sum() / tot)
        if 0.7 < hfr < R * 0.8:                 # Hotpixel / Überlappungen raus
            hfrs.append(hfr)
        if len(hfrs) >= max_stars:
            break
    if len(hfrs) < 3:
        return None, len(hfrs)
    return float(np.median(hfrs)), len(hfrs)


class FocusRun:
    """Präzisions-Autofokus für ein Gerät (läuft im eigenen Thread)."""

    def __init__(self, device, exp_ms=2000, span=80, step=10, frames=2, backlash=30, on_point=None, fine_half=None):
        self.d = device
        self.exp_ms, self.span, self.step, self.frames, self.backlash = exp_ms, span, step, frames, backlash
        self.fine_half = fine_half            # Breite der Feinsuche (None = automatisch)
        self.at_edge = False                  # Optimum lag am Rand des Suchbereichs
        self.on_point = on_point or (lambda *a: None)
        self.cancelled = False
        self.points = []                      # (position, hfr, sterne)
        self.result = None
        self._frames = queue.Queue()

    def cancel(self):
        self.cancelled = True

    def _on_frame(self, kind, rgb):
        if kind == "preview":
            try:
                self._frames.put_nowait(rgb)
            except queue.Full:
                pass

    def _pos(self):
        r = self.d.wifi.send("get_focuser_position", quiet=True)
        return r.get("result") if isinstance(r, dict) and isinstance(r.get("result"), (int, float)) else None

    def _move(self, target):
        self.d.wifi.send("move_focuser", {"step": int(target), "ret_step": True}, quiet=True)
        for _ in range(40):                    # warten, bis der Fokussierer steht
            time.sleep(0.25)
            p = self._pos()
            if p is not None and abs(p - target) <= 1:
                return p
        return self._pos()

    def _grab(self, n):
        while not self._frames.empty():
            self._frames.get_nowait()
        self._frames.get(timeout=self.exp_ms / 1000 * 3 + 8)      # erstes Bild ist evtl. noch in Bewegung belichtet
        out = []
        for _ in range(n):
            out.append(self._frames.get(timeout=self.exp_ms / 1000 * 3 + 8))
        return out

    def run(self):
        d = self.d
        if not d.ensure_imager():
            raise RuntimeError("Bildkanal nicht erreichbar")
        old_cont = d.values.get("cont_exp")
        start = self._pos()
        if start is None:
            raise RuntimeError("Fokusposition nicht lesbar")
        d.frame_listeners.append(self._on_frame)
        try:
            d.wifi.send("set_setting", {"exp_ms": {"continuous": int(self.exp_ms)}}, quiet=True)
            d.imager.start_preview()
            # 1. Grobsuche über den ganzen Bereich
            self._scan(list(range(int(start - self.span), int(start + self.span) + 1, int(self.step))))
            lo, hi = (min(p[0] for p in self.points), max(p[0] for p in self.points)) if self.points else (start, start)
            coarse = None if self.cancelled else self.fit()
            # 2. Feinsuche: halbe Schrittweite, symmetrisch um das Grobergebnis (auch über den Rand hinaus)
            if coarse is not None and not self.cancelled:
                fine_step = max(2, int(self.step) // 2)
                half = int(self.fine_half) if self.fine_half else max(3 * fine_step, int(self.step) * 2)
                self.points = []
                self.on_point(None, None, 0)                          # Anzeige: Feinsuche beginnt
                self._scan(list(range(coarse - half, coarse + half + 1, fine_step)))
            if self.cancelled:
                self._move(start - self.backlash)
                self._move(start)
                return None
            best = self.fit() if coarse is not None else None
            if best is not None and (best <= lo + self.step or best >= hi - self.step):   # Rand der Grobsuche
                self.at_edge = True
                d.log("Autofokus: Optimum liegt am Rand des Suchbereichs – ggf. mit größerem Bereich wiederholen.", "warn")
            if best is None:
                d.log("Autofokus: zu wenige Sterne gefunden – zurück zur Ausgangsposition.", "err")
                self._move(start - self.backlash)
                self._move(start)
                return None
            self._move(best - self.backlash)
            final = self._move(best)
            check = measure_hfr(np.mean(np.stack(self._grab(self.frames)), axis=0))[0]
            self.result = {"pos": int(final if final is not None else best), "hfr": check}
            return self.result
        finally:
            if self._on_frame in d.frame_listeners:
                d.frame_listeners.remove(self._on_frame)
            d.imager.stop_preview()
            if old_cont:
                d.wifi.send("set_setting", {"exp_ms": {"continuous": int(old_cont)}}, quiet=True)

    def _scan(self, positions):
        self._move(positions[0] - self.backlash)                     # immer von unten anfahren (Spiel)
        for p in positions:
            if self.cancelled:
                return
            real = self._move(p)
            # mehrere Live-Bilder mitteln: Rauschen sinkt um √n – entscheidend hinter Schmalbandfiltern
            avg = np.mean(np.stack(self._grab(self.frames)), axis=0)
            hfr, stars = measure_hfr(avg)
            pos = real if real is not None else p
            if hfr is not None:
                self.points.append((pos, hfr, stars))
            self.on_point(pos, hfr, stars)

    def fit(self):
        pts = sorted(self.points)
        if len(pts) < 3:
            return None
        k = min(range(len(pts)), key=lambda i: pts[i][1])
        lo, hi = max(0, k - 3), min(len(pts), k + 4)
        sub = pts[lo:hi]
        if len(sub) >= 3:
            a, b, c = np.polyfit([p[0] for p in sub], [p[1] for p in sub], 2)
            if a > 0:
                v = -b / (2 * a)
                if pts[0][0] <= v <= pts[-1][0]:
                    return int(round(v))
        return int(pts[k][0])


# --------------------------------------------------------------------------
# Mosaik
# --------------------------------------------------------------------------
def mosaic_centers(ra_h, dec_deg, cols, rows, overlap_pct, model):
    """Panel-Mittelpunkte (RA h, Dec °) in Schlangenlinie, Zeile für Zeile von Nord nach Süd."""
    m = MODELS.get(model or "S50", MODELS["S50"])
    step_dec = m["fov_h"] * (1 - overlap_pct / 100.0)
    step_ra_deg = m["fov_w"] * (1 - overlap_pct / 100.0)
    out = []
    for j in range(rows):
        dec = dec_deg + ((rows - 1) / 2 - j) * step_dec
        dec = max(-89.9, min(89.9, dec))
        cosd = max(0.05, abs(math.cos(math.radians(dec))))
        cols_idx = range(cols) if j % 2 == 0 else range(cols - 1, -1, -1)
        for i in cols_idx:
            ra = ra_h + ((cols - 1) / 2 - i) * step_ra_deg / 15.0 / cosd
            out.append(((ra % 24.0), dec, j, i))
    return out


def mosaic_steps(p, model):
    """Mosaik-Einstellungen -> Liste von Ablaufschritten."""
    if p["mode"] == "frame":
        return [{"t": "frame", "name": p["name"], "ra": p["ra"], "dec": p["dec"], "secs": p["total_min"] * 60,
                 "scale": p["scale"], "angle": p["angle"], "lp": p.get("lp"), "af": p.get("af_mode", "auto")}]
    steps = []
    for ra, dec, j, i in mosaic_centers(p["ra"], p["dec"], p["cols"], p["rows"], p["overlap"], model):
        steps.append({"t": "capture", "name": f"{p['name']}_R{j + 1}C{i + 1}", "ra": ra, "dec": dec,
                      "secs": p["panel_min"] * 60, "lp": p.get("lp"),
                      "af": p.get("af_mode", "auto") if p.get("af") else "none"})
    return steps


REFOCUS_OPTIONS = {"Aus": (0, 0), "ab 2 °C Temperaturänderung": (0, 2), "ab 3 °C Temperaturänderung": (0, 3),
                   "alle 60 min": (60, 0), "alle 90 min": (90, 0), "alle 120 min": (120, 0),
                   "alle 60 min oder ab 2 °C": (60, 2), "alle 90 min oder ab 2 °C": (90, 2)}
REFOCUS_SPAN = 30                    # Suchbereich beim Nachfokussieren während der Aufnahme (± Schritte)
REFOCUS_DEFAULT = "ab 2 °C Temperaturänderung"

END_ACTIONS = {"open": "Stacking stoppen, Arm bleibt offen", "park": "Parken (Arm schließen)",
               "shutdown": "Parken und ausschalten"}


class PlanJob:
    """Ablauf (Zeitplan oder Mosaik) pro Gerät in einem eigenen Thread.

    Übersteht Verbindungsabbrüche: wartet auf die automatische Wiederverbindung, prüft, ob das Seestar
    noch stackt, und macht beim richtigen Schritt weiter. Der Stand (Schritt, Endzeit) wird gespeichert,
    sodass ein Ablauf auch nach einem Neustart der App fortgesetzt werden kann.
    """
    RECONNECT_WAIT = 3600            # so lange auf ein verlorenes Gerät warten, dann pausieren

    def __init__(self, device, plan, start_index=0, resume_deadline=None):
        self.d = device
        self.plan = plan                         # {"name", "kind", "steps": [...], "end": "open"/"park"/"shutdown"}
        self.k = start_index
        self.deadline = resume_deadline
        self.focus_t = time.time()                     # Zeitpunkt / Temperatur des letzten Fokussierens
        self.focus_temp = device.temp
        self.cancelled = False
        self.suspended = False
        self.thread = threading.Thread(target=self._run, daemon=True)

    # -- Steuerung von außen
    def start(self):
        self.d.job = self
        self._persist()
        self.thread.start()

    def cancel(self):
        self.cancelled = True

    def suspend(self):
        self.suspended = True

    def _stop(self):
        return self.cancelled or self.suspended

    # -- Hilfen
    def _status(self, text):
        self.d.job_text = text
        self.d.app.ui(self.d.app.device_changed, self.d)

    def _persist(self):
        self.d.app.save_job(self.d.host, {"plan": self.plan, "k": self.k, "deadline": self.deadline,
                                          "device": self.d.name, "saved": time.time()})

    def _label(self, idx):
        n = len(self.plan["steps"])
        st = self.plan["steps"][idx]
        what = {"capture": st.get("name", ""), "frame": f"Framing {st.get('name', '')}", "af": "Autofokus",
                "wait_until": f"warten bis {st.get('at', '')}"}.get(st["t"], st["t"])
        return f"{self.plan.get('name', 'Plan')} {idx + 1}/{n}: {what}"

    def _wait_connected(self, label):
        t0 = time.time()
        while not self.d.connected:
            if self._stop():
                return False
            waited = int(time.time() - t0)
            if waited > self.RECONNECT_WAIT:
                self.d.log("Gerät kam nicht zurück – Ablauf pausiert. Er kann später fortgesetzt werden.", "err")
                self.suspended = True
                return False
            self._status(f"{label} · Verbindung weg, warte ({waited // 60}:{waited % 60:02d})")
            time.sleep(1)
        return True

    def _send(self, method, params=None, label="", quiet=False):
        for _ in range(3):
            if not self._wait_connected(label):
                return None
            r = self.d.wifi.send(method, params, quiet=quiet)
            if r is not None:
                return r
        return None

    def _goto(self, st, label):
        for _ in range(3):
            since = time.time()
            rn, dn = precess_j2000(st["ra"], st["dec"])          # Plan in J2000, Seestar erwartet Datumskoordinaten
            r = self._send("iscope_start_view", {"mode": "star", "target_ra_dec": [rn, dn], "target_name": st["name"][:40],
                                                 "lp_filter": bool(st.get("lp"))}, label)
            if r is None:
                return False
            if r.get("code", 0) not in (0, None):
                self.d.log(f"GoTo abgelehnt: {r}", "err")
                return False
            res = self.d.wait_event(("AutoGoto",), timeout=300, since=since,
                                    abort=lambda: self._stop() or not self.d.connected)
            if res == "complete":
                return True
            if res == "fail":
                self.d.log(f"GoTo zu {st['name']} fehlgeschlagen.", "err")
                return False
            if self._stop():
                return False
            if not self.d.connected:
                continue                                         # nach Wiederverbindung neu anfahren
            self.d.log("Kein GoTo-Ende gemeldet – fahre trotzdem fort.", "warn")
            return True
        return False

    def _focus(self, mode, label, refocus=False):
        """Fokus vor dem Stacking: auto = mit externem Filter App-Autofokus (sonst gemerkte Position), ohne Seestar-AF."""
        d, app = self.d, self.d.app
        if mode == "none":
            return
        if mode == "auto":
            mode = ("app" if HAVE_IMAGING else "saved") if d.ext_filter != NO_FILTER else "seestar"
        self._status(f"{label} · Fokus ({ {'app': 'App-Autofokus', 'saved': 'gemerkte Position', 'seestar': 'Seestar-AF'}[mode] })")
        if mode == "seestar":
            since = time.time()
            self._send("start_auto_focuse", None, label)
            d.wait_event(("AutoFocus",), timeout=240, since=since, abort=self._stop)
        elif mode == "saved":
            if not app.focus_to_saved(d):
                d.log("Keine gemerkte Fokusposition – Fokus bleibt unverändert.", "warn")
        elif mode == "app":
            if app.run_app_autofocus(d, narrow=refocus) is None and not self._stop():
                if app.focus_to_saved(d):
                    d.log("App-Autofokus ohne Ergebnis – gemerkte Position verwendet.", "warn")

    def _ensure_stacking(self, idx):
        """Nach einer Unterbrechung: stackt das Seestar noch? Sonst Ziel neu anfahren und weiterstacken."""
        label = self._label(idx)
        st = self.plan["steps"][idx]
        self._status(f"{label} · prüfe, ob das Seestar noch stackt …")
        wait = max(15, min(75, (self.deadline or time.time()) - time.time() - 10))   # 75 s deckt 60-s-Frames ab
        ev = self.d.wait_event(("Stack",), states=None, timeout=wait, since=time.time() - 3,
                               abort=lambda: self._stop() or not self.d.connected)
        if ev is not None:
            self.d.log(f"{label}: Seestar hat während der Unterbrechung weiter gestackt – weiter geht's.", "ok")
            return True
        if self._stop() or not self.d.connected:
            return False
        self.d.log(f"{label}: Stacking lief nicht weiter – fahre das Ziel erneut an.", "warn")
        if not self._goto(st, label):
            return False
        if st["t"] == "frame":
            self._send("set_setting", {"mosaic": {"scale": st["scale"], "angle": st["angle"], "star_map_angle": 0.0}}, label)
        self._send("iscope_start_stack", {"restart": False}, label)
        return True

    def _refocus_due(self, st):
        """Ist es Zeit zum Nachfokussieren? (alle X min oder ab Y °C Temperaturänderung)"""
        rf = self.plan.get("refocus") or {}
        if st["t"] != "capture" or st.get("af", "auto") == "none" or not (rf.get("min") or rf.get("dtemp")):
            return False
        if self.deadline - time.time() < 240:                  # kurz vor Schluss lohnt es nicht mehr
            return False
        if rf.get("min") and time.time() - self.focus_t >= rf["min"] * 60:
            return True
        t0, t1 = self.focus_temp, self.d.temp
        return bool(rf.get("dtemp") and isinstance(t0, (int, float)) and isinstance(t1, (int, float))
                    and abs(t1 - t0) >= rf["dtemp"])

    def _refocus(self, idx):
        """Stacking anhalten, nachfokussieren, im selben Stack weitermachen (wie „Weitermachen“ in der Seestar-App)."""
        st, label = self.plan["steps"][idx], self._label(idx)
        rf = self.plan.get("refocus") or {}
        why = (f"{abs(self.d.temp - self.focus_temp):.1f} °C Temperaturänderung"
               if rf.get("dtemp") and isinstance(self.focus_temp, (int, float)) and isinstance(self.d.temp, (int, float))
               and abs(self.d.temp - self.focus_temp) >= rf["dtemp"] else f"{rf.get('min')} min seit dem letzten Fokus")
        self.d.log(f"{label}: Nachfokussieren ({why}) – Stacking kurz angehalten.", "warn")
        t0 = time.time()
        self._send("iscope_stop_view", {"stage": "Stack"}, label, quiet=True)
        time.sleep(3)
        self._focus(st.get("af", "auto"), label, refocus=True)
        if self._stop():
            return
        self._send("iscope_start_stack", {"restart": False}, label)
        self.deadline += time.time() - t0                     # die Pause zählt nicht zur Belichtungszeit
        self.focus_t, self.focus_temp = time.time(), self.d.temp
        self._persist()
        self.d.log(f"{label}: Fokus nachgeführt, Stacking geht im selben Stack weiter.", "ok")

    def _wait_until(self, idx):
        label = self._label(idx)
        st = self.plan["steps"][idx]
        while True:
            if self._stop():
                return False
            if not self.d.connected:
                if not self._wait_connected(label):
                    return False
                if self.deadline - time.time() > 20 and not self._ensure_stacking(idx):
                    if self._stop():
                        return False
                continue
            rest = int(self.deadline - time.time())
            if rest <= 0:
                return True
            if self._below_min_alt(st):
                self.d.log(f"{st.get('name', '')} ist unter {st['min_alt']}° gesunken – Aufnahme beendet, weiter mit dem "
                           f"nächsten Schritt.", "warn")
                return True
            if self.d.focus_hold is None and self._refocus_due(st):
                self._refocus(idx)
                continue
            self._status(f"{label} · noch {rest // 3600}:{rest % 3600 // 60:02d}:{rest % 60:02d}")
            time.sleep(1)

    def _below_min_alt(self, st):
        """Während der Aufnahme höchstens alle 60 s prüfen, ob das Ziel unter die Mindesthöhe gesunken ist."""
        if st.get("t") != "capture" or not st.get("min_alt") or "ra" not in st:
            return False
        now = time.time()
        if now - getattr(self, "_alt_checked", 0) < 60:
            return False
        self._alt_checked = now
        site = self.d.app.site_cache
        if not site:
            return False
        return alt_az(st["ra"], st["dec"], site[0], site[1])[0] < st["min_alt"] - 0.5

    def _wait_clock(self, at, label):
        """Wartet bis Uhrzeit HH:MM (heute oder, falls vorbei, morgen – aber höchstens 18 h)."""
        hh, mm = [int(x) for x in at.split(":")]
        now = datetime.now()
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target < now:
            if (now - target).total_seconds() < 6 * 3600:
                return True                                          # Zeit liegt kurz hinter uns -> sofort weiter
            target = target + timedelta(days=1)
        while datetime.now() < target:
            if self._stop():
                return False
            rest = int((target - datetime.now()).total_seconds())
            self._status(f"{label} · noch {rest // 3600}:{rest % 3600 // 60:02d}:{rest % 60:02d}")
            time.sleep(1)
        return True

    def _wait_altitude(self, st, label):
        """Wartet, bis das Ziel min_alt erreicht (höchstens max_wait). False = überspringen."""
        site = self.d.app.site_cache
        min_alt = st.get("min_alt")
        if not site or min_alt in (None, 0):
            return True
        if alt_az(st["ra"], st["dec"], site[0], site[1])[0] >= min_alt:
            return True
        t_up = next_time_above(st["ra"], st["dec"], site[0], site[1], min_alt, horizon_h=st.get("max_wait_h", 3))
        if not t_up:
            self.d.log(f"{st['name']} erreicht in den nächsten {st.get('max_wait_h', 3)} h keine {min_alt}° – übersprungen.", "warn")
            return False
        while time.time() < t_up:
            if self._stop():
                return False
            rest = int(t_up - time.time())
            self._status(f"{label} · warte auf {min_alt}° Höhe · noch {rest // 3600}:{rest % 3600 // 60:02d}")
            time.sleep(1)
        return True

    # -- Ablauf
    def _run(self):
        p = self.plan
        steps = p["steps"]
        n = len(steps)
        frame_active = False
        try:
            if self.k == 0 and self.deadline is None:
                self.d.log(f"„{p.get('name', 'Plan')}“ gestartet: {n} Schritt(e).", "ok")
            for idx in range(self.k, n):
                self.k = idx
                st = steps[idx]
                label = self._label(idx)
                if st["t"] == "wait_until":
                    if not self._wait_clock(st["at"], label):
                        break
                elif st["t"] == "af":
                    if not self._wait_connected(label):
                        break
                    self._focus(st.get("mode", "auto"), label)
                elif st["t"] in ("capture", "frame"):
                    if self.deadline is not None:                       # Fortsetzen eines laufenden Schritts
                        self._status(f"{label} · setze fort …")
                        if not self._wait_connected(label):
                            break
                        if self.deadline - time.time() > 20 and not self._ensure_stacking(idx):
                            if self._stop():
                                break
                    else:
                        if not self._wait_altitude(st, label):
                            if self._stop():
                                break
                            self.k = idx + 1
                            self._persist()
                            continue
                        if st.get("lp") is not None:
                            self._send("set_setting", {"stack_lenhance": bool(st["lp"])}, label, quiet=True)
                        self._status(f"{label} · GoTo")
                        if not self._goto(st, label):
                            if self._stop():
                                break
                            self.d.log(f"{label} wird übersprungen.", "warn")
                            continue
                        self._focus(st.get("af", "auto"), label)
                        self.focus_t, self.focus_temp = time.time(), self.d.temp
                        if self._stop():
                            break
                        if st["t"] == "frame":
                            self._send("set_setting", {"mosaic": {"scale": st["scale"], "angle": st["angle"],
                                                                  "star_map_angle": 0.0}}, label)
                            frame_active = True
                        self._send("iscope_start_stack", {"restart": True}, label)
                        self.deadline = time.time() + st["secs"]
                        self._persist()
                    if not self._wait_until(idx):
                        break
                    self._send("iscope_stop_view", {"stage": "Stack"}, label)
                    if st["t"] == "frame":
                        self._send("set_setting", {"mosaic": {"scale": 1.0, "angle": 0.0}}, label, quiet=True)
                        frame_active = False
                    self.deadline = None
                if self._stop():
                    break
                self.k = idx + 1
                self._persist()
            else:
                self._finish()
        except Exception as e:
            self.d.log(f"Ablauf-Fehler: {e}", "err")
            self.suspended = True
        finally:
            if self.cancelled:
                if self.d.connected:
                    self.d.wifi.send("iscope_stop_view", {"stage": "Stack"}, quiet=True)
                    if frame_active:
                        self.d.wifi.send("set_setting", {"mosaic": {"scale": 1.0, "angle": 0.0}}, quiet=True)
                self.d.app.save_job(self.d.host, None)
                self.d.log("Ablauf abgebrochen. Arm bleibt offen.", "warn")
            elif self.suspended:
                self._persist()
                self.d.log(f"Ablauf pausiert bei Schritt {self.k + 1}. Das Seestar stackt den aktuellen Schritt weiter; "
                           "beim nächsten Verbinden kannst du fortsetzen.", "warn")
            else:
                self.d.app.save_job(self.d.host, None)
            self.d.job = None
            self._status("")

    def _finish(self):
        end = self.plan.get("end", "open")
        d = self.d
        if end != "open" and d.protect:
            d.log(f"Plan-Ende: „{END_ACTIONS[end]}“ übersprungen – Arm-Schutz aktiv ({d.protect_reason()}). "
                  "Stacking gestoppt, Arm bleibt offen.", "warn")
            end = "open"
        if not self._wait_connected("Plan-Ende"):
            return
        if end == "open":
            d.wifi.send("iscope_stop_view")
            d.log(f"„{self.plan.get('name', 'Plan')}“ fertig – Arm bleibt offen.", "ok")
        elif end == "park":
            d.wifi.send("scope_park")
            d.log(f"„{self.plan.get('name', 'Plan')}“ fertig – Seestar parkt.", "ok")
        elif end == "shutdown":
            d.wifi.send("scope_park")
            time.sleep(20)
            d.wifi.send("pi_shutdown")
            d.log(f"„{self.plan.get('name', 'Plan')}“ fertig – Seestar parkt und schaltet aus.", "ok")


# --------------------------------------------------------------------------
# Geräteeinstellungen (im Tab und als eigenes Fenster pro Gerät)
# --------------------------------------------------------------------------
class SettingsPanel(ttk.Frame):
    def __init__(self, master, app, device=None, follow_active=False):
        super().__init__(master, padding=8)
        self.app = app
        self.device = None
        self.follow_active = follow_active
        self.vars, self.cbs, self.labels = {}, {}, {}
        self._built_for = "init"

        head = ttk.Frame(self)
        head.pack(fill="x")
        self.title_var = tk.StringVar(value="Kein Gerät")
        ttk.Label(head, textvariable=self.title_var, font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Button(head, text="Auf alle markierten übertragen", command=self.copy_to_group).pack(side="right")
        ttk.Button(head, text="Empfohlene Werte", command=self.recommended).pack(side="right", padx=6)
        ttk.Button(head, text="⟳ Vom Gerät lesen", command=self.reload).pack(side="right")
        self.info_var = tk.StringVar()
        self.info2_var = tk.StringVar()
        il = ttk.Frame(self)
        il.pack(anchor="w", pady=(2, 6))
        ttk.Label(il, textvariable=self.info_var, foreground=C["muted"], font=("Consolas", 9)).pack(side="left")
        ttk.Label(il, textvariable=self.info2_var, foreground=C["muted"], font=("Consolas", 9)).pack(side="left", padx=(12, 0))
        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True)
        ttk.Label(self, text="Änderungen gehen sofort an dieses Gerät. „–“ = Wert vom Gerät (noch) nicht gemeldet.",
                  foreground=C["muted"]).pack(anchor="w", pady=(6, 0))
        if device:
            self.set_device(device)
        else:
            self._build()

    def set_device(self, dev):
        if self.device is dev:
            return
        if self.device and self in self.device.settings_panels:
            self.device.settings_panels.remove(self)
        self.device = dev
        if dev:
            dev.settings_panels.append(self)
        self.refresh()

    def detach(self):
        self.set_device(None)

    def _build(self):
        model = self.device.model if self.device else None
        for w in self.body.winfo_children():
            w.destroy()
        self.vars, self.cbs, self.labels = {}, {}, {}
        cols = ttk.Frame(self.body)
        cols.pack(fill="both", expand=True)
        frames = {}
        col_of = {"Stacking": 0, "Fokus": 1, "Gerät": 1, "Live-Ansicht": 2, "Weitwinkel": 2}
        colf = [ttk.Frame(cols) for _ in range(3)]
        for k, f in enumerate(colf):
            f.grid(row=0, column=k, sticky="nw", padx=(0 if k == 0 else 14, 0))
        for sec in SECTIONS:
            items = [x for x in SETTINGS if x[1] == sec and (x[6] is None or x[6](model))]
            if not items:
                continue
            lf = ttk.Labelframe(colf[col_of[sec]], text=sec, padding=8)
            lf.pack(fill="x", pady=(0, 8))
            frames[sec] = lf
            for r, (key, _s, label, opts, _g2, _s2, _o) in enumerate(items):
                text = label.replace("{lp}", MODELS.get(model or "S50")["lp_name"])
                lbl = ttk.Label(lf, text=text + ":")
                lbl.grid(row=r, column=0, sticky="w", pady=2)
                v = tk.StringVar(value="–")
                cb = ttk.Combobox(lf, textvariable=v, values=[o[0] for o in opts], state="readonly", width=15)
                cb.grid(row=r, column=1, sticky="w", padx=6, pady=2)
                cb.bind("<<ComboboxSelected>>", lambda e, k=key: self.on_change(k))
                if key in SETTING_HINTS:
                    hb = ttk.Label(lf, text="ℹ", cursor="hand2", foreground=C["accent"])
                    hb.grid(row=r, column=2, sticky="w")
                    hb.bind("<Button-1>", lambda e, k=key: messagebox.showinfo(APP_NAME, SETTING_HINTS[k]))
                self.vars[key], self.cbs[key], self.labels[key] = v, cb, lbl
        lf = ttk.Labelframe(colf[2], text="Modus starten", padding=8)
        lf.pack(fill="x")
        self.mode_var = tk.StringVar(value="Sterne / Deep Sky")
        ttk.Combobox(lf, textvariable=self.mode_var, values=list(VIEW_MODES), state="readonly", width=24).pack(anchor="w")
        ttk.Button(lf, text="Starten (Arm öffnen)", command=self.start_mode).pack(anchor="w", pady=(6, 0))
        self._built_for = model

    def refresh(self):
        d = self.device
        if (d.model if d else None) != self._built_for:
            self._build()
        if not d:
            self.title_var.set("Kein Gerät ausgewählt")
            self.info_var.set("")
            self.info2_var.set("")
            return
        m = MODELS.get(d.model) if d.model else None
        self.title_var.set(f"{d.name} ({d.host}) · {m['label'] if m else 'Modell unbekannt'}")
        self.info_var.set(f"Optik {m['optik']} · Sensor {m['sensor']} · Feld {m['fov']}" if m else
                          "Modell wird beim Verbinden erkannt oder oben rechts gewählt.")
        self.info2_var.set(f"Speicher frei: {fmt_num(d.storage_free / 1024, 1)} GB" if d.storage_free is not None else "")
        for key, v in self.vars.items():
            spec = next(x for x in SETTINGS if x[0] == key)
            val = d.values.get(key)
            txt = next((o[0] for o in spec[3] if o[1] == val), None)
            if txt is None:
                txt = "–" if val is None else str(val)
            v.set(txt)

    def on_change(self, key):
        d = self.device
        if not d:
            return
        spec = next(x for x in SETTINGS if x[0] == key)
        val = next(o[1] for o in spec[3] if o[0] == self.vars[key].get())
        if key == "exp" and val == 60000 and d.eq_mode is not True:
            messagebox.showwarning(APP_NAME, "60 s Belichtung gibt es nur im EQ-Modus – und 60 s ist dort auch das "
                                             "Maximum.\n\n" + ("Dieses Gerät ist im Alt-Az-Modus." if d.eq_mode is False
                                             else "Der Modus dieses Geräts ist noch unbekannt.") +
                                   "\nWechsle im Tab „EQ-Modus“ in den EQ-Modus und richte das Gerät aus.")
            self.refresh()
            return
        devs = [d]
        if self.follow_active and self.app.target_var.get() == "group":     # „Befehle an: alle markierten“
            devs += [x for x in self.app.group() if x is not d]
        for x in devs:
            spec_only = spec[6]
            if spec_only is not None and not spec_only(x.model):
                x.log(f"„{SETTING_LABEL.get(key, key)}“ gibt es bei diesem Modell nicht – übersprungen.", "warn")
                continue
            if x.connected:
                self.app.bg(x.apply_setting, key, val)
            else:
                self.app.queue_setting(x, key, val)

    def reload(self):
        if self.device and self.device.connected:
            self.app.bg(self.device.refresh_settings)

    def recommended(self):
        d = self.device
        if not d:
            return
        def job():
            for k, v in RECOMMENDED.items():
                if d.connected:
                    d.apply_setting(k, v)
                else:
                    self.app.ui(self.app.queue_setting, d, k, v)
            self.app.ui(self.refresh)
            d.log("Empfohlene Werte gesetzt.", "ok")
        self.app.bg(job)

    def copy_to_group(self):
        src = self.device
        if not src:
            return
        dests = [x for x in self.app.group() if x is not src and x.connected]
        if not dests:
            messagebox.showinfo(APP_NAME, "Keine weiteren verbundenen Geräte in der Gruppe.")
            return
        vals = dict(src.values)
        def job(dst):
            for key, _s, _l, _o, _g2, _s2, only in SETTINGS:
                if key in vals and (only is None or only(dst.model)):
                    dst.apply_setting(key, vals[key])
            dst.log(f"Einstellungen von „{src.name}“ übernommen.", "ok")
            dst.refresh_settings()
        for dst in dests:
            self.app.bg(job, dst)

    def start_mode(self):
        d = self.device
        if not d or not d.connected:
            return
        mode = VIEW_MODES.get(self.mode_var.get(), "star")
        if mode == "sun" and not messagebox.askyesno(APP_NAME, "Sonnenfilter wirklich aufgesetzt?"):
            return
        self.app.bg(d.open_arm, mode)


def stretch8(rgb, params):
    strength, linked, raw = params
    if raw:
        out = rgb / max(1e-6, float(np.percentile(rgb, 99.9)))
    else:
        out = autostretch(rgb, strength, linked)
    return (np.clip(out, 0, 1) * 255).astype(np.uint8)


# --------------------------------------------------------------------------
# Vorschau-Ansicht (im Tab und in jedem Pop-up-Fenster)
# --------------------------------------------------------------------------
class PreviewPanel(ttk.Frame):
    def __init__(self, master, app, device=None, follow_active=False):
        super().__init__(master, padding=8)
        self.app = app
        self.device = None
        self.follow_active = follow_active
        self.last_rgb = None
        self.last_img8 = None
        self.last_kind = ""
        self.photo = None
        self.params = (0.20, False, False)     # Thread-sichere Kopie der Regler
        self.auto_stack_flag = True
        self.pending = queue.Queue(maxsize=1)

        bar = ttk.Frame(self)
        bar.pack(fill="x")
        ttk.Button(bar, text="▶ Live", style="Accent.TButton",
                   command=lambda: self._dev_call("preview_live")).pack(side="left")
        ttk.Button(bar, text="Stack-Bild", command=lambda: self._dev_call("preview_stack")).pack(side="left", padx=4)
        ttk.Button(bar, text="■ Stopp", command=lambda: self._dev_call("preview_stop")).pack(side="left")
        self.auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Stack automatisch", variable=self.auto_var,
                        command=self._sync).pack(side="left", padx=10)
        ttk.Button(bar, text="💾 PNG", command=self.save).pack(side="right")
        if follow_active:
            ttk.Button(bar, text="⧉ Eigenes Fenster", command=lambda: self.device and app.open_popup(self.device)).pack(
                side="right", padx=4)

        bar2 = ttk.Frame(self)
        bar2.pack(fill="x", pady=(6, 4))
        ttk.Label(bar2, text="Stretch:").pack(side="left")
        self.stretch_var = tk.DoubleVar(value=0.20)
        sc = ttk.Scale(bar2, from_=0.05, to=0.45, variable=self.stretch_var, orient="horizontal", length=160)
        sc.pack(side="left", padx=6)
        sc.bind("<ButtonRelease-1>", lambda e: self.restretch())
        self.linked_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar2, text="verknüpft", variable=self.linked_var, command=self.restretch).pack(side="left")
        self.raw_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar2, text="linear", variable=self.raw_var, command=self.restretch).pack(side="left", padx=6)
        if not follow_active:
            top = master.winfo_toplevel()
            bar3 = ttk.Frame(self)
            bar3.pack(fill="x", pady=(0, 4))
            ttk.Button(bar3, text="Vollbild (F11)", style="Small.TButton",
                       command=lambda: getattr(top, "toggle_fullscreen", lambda: None)()).pack(side="left")
            self.ontop_var = tk.BooleanVar(value=False)
            ttk.Checkbutton(bar3, text="Immer im Vordergrund", variable=self.ontop_var,
                            command=lambda: top.attributes("-topmost", bool(self.ontop_var.get()))).pack(side="left", padx=8)
            ttk.Label(bar3, text="Fenster frei verschiebbar, z. B. auf einen zweiten Monitor – Position wird gemerkt.",
                      foreground=C["dim"]).pack(side="left")
        self.info_var = tk.StringVar(value="Kein Bild")
        ttk.Label(bar2, textvariable=self.info_var, foreground=C["muted"]).pack(side="right")

        self.canvas = tk.Canvas(self, bg="#000000", highlightthickness=0, width=420, height=480)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.render())
        if device:
            self.set_device(device)

    def _sync(self):
        self.auto_stack_flag = bool(self.auto_var.get())
        self.params = (float(self.stretch_var.get()), bool(self.linked_var.get()), bool(self.raw_var.get()))

    def _dev_call(self, method):
        if not self.device:
            messagebox.showinfo(APP_NAME, "Kein Gerät ausgewählt.")
            return
        self.app.bg(getattr(self.device, method))

    def set_device(self, dev):
        if self.device is dev:
            return
        if self.device and self in self.device.panels:
            self.device.panels.remove(self)
        self.device = dev
        self.last_rgb = self.last_img8 = None
        self.canvas.delete("all")
        self.info_var.set("Kein Bild" if dev else "Kein Gerät")
        if dev:
            dev.panels.append(self)

    def detach(self):
        self.set_device(None)

    # wird im Bild-Thread aufgerufen
    def offer(self, kind, small, w, h):
        img8 = stretch8(small, self.params)
        self.app.ui(self._show, kind, small, img8, w, h)

    def _show(self, kind, small, img8, w, h):
        self.last_rgb, self.last_img8, self.last_kind = small, img8, kind
        name = "Live" if kind == "preview" else "Stack"
        frames = f" · {self.device.frames} Frames" if self.device and self.device.frames and kind == "stack" else ""
        self.info_var.set(f"{name} · {w}×{h}{frames} · {datetime.now():%H:%M:%S}")
        self.render()

    def restretch(self):
        self._sync()
        if self.last_rgb is None:
            return
        rgb, params, kind = self.last_rgb, self.params, self.last_kind
        def job():
            img8 = stretch8(rgb, params)
            self.app.ui(self._restretched, img8)
        self.app.bg(job)

    def _restretched(self, img8):
        self.last_img8 = img8
        self.render()

    def render(self):
        if self.last_img8 is None or not self.winfo_exists():
            return
        cw, ch = max(10, self.canvas.winfo_width()), max(10, self.canvas.winfo_height())
        im = Image.fromarray(self.last_img8, "RGB")
        im.thumbnail((cw, ch), Image.LANCZOS)
        self.photo = ImageTk.PhotoImage(im)
        self.canvas.delete("all")
        self.canvas.create_image(cw // 2, ch // 2, image=self.photo, anchor="center")

    def save(self):
        if self.last_img8 is None:
            messagebox.showinfo(APP_NAME, "Noch kein Bild vorhanden.")
            return
        dn = re.sub(r"[^\w-]+", "_", self.device.name if self.device else "seestar")
        p = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG", "*.png")],
                                         initialfile=f"{dn}_{self.last_kind}_{datetime.now():%Y%m%d_%H%M%S}.png")
        if p:
            Image.fromarray(self.last_img8, "RGB").save(p)
            self.app.log(f"Gespeichert: {p}", "ok")


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------
class StandbyBlocker:
    """Hält den Rechner wach, solange ein Mosaik läuft (nur dann).

    Windows: SetThreadExecutionState – verhindert Standby/Ruhezustand durch Untätigkeit; der Bildschirm darf
    trotzdem dunkel werden. macOS: caffeinate. Linux: systemd-inhibit. Wird immer aus dem Tk-Hauptthread
    aufgerufen, weil Windows die Sperre an den Thread bindet, der sie gesetzt hat.
    """
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_AWAYMODE_REQUIRED = 0x80000000, 0x00000001, 0x00000040

    def __init__(self):
        self.active = False
        self.proc = None
        self.error = ""

    def _win(self, on):
        import ctypes
        flags = self.ES_CONTINUOUS | (self.ES_SYSTEM_REQUIRED if on else 0)
        if not ctypes.windll.kernel32.SetThreadExecutionState(flags):
            raise OSError("SetThreadExecutionState abgelehnt")

    def set(self, on):
        if on == self.active:
            if on and sys.platform == "win32":          # Leerlauf-Zähler regelmäßig zurücksetzen
                try:
                    self._win(True)
                except Exception:
                    pass
            return True
        self.error = ""
        try:
            if sys.platform == "win32":
                self._win(on)
            elif on:
                import shutil
                import subprocess
                if sys.platform == "darwin" and shutil.which("caffeinate"):
                    cmd = ["caffeinate", "-i", "-w", str(os.getpid())]
                elif shutil.which("systemd-inhibit"):
                    cmd = ["systemd-inhibit", "--what=idle:sleep", f"--who={APP_ID}",
                           "--why=Mosaik läuft", "--mode=block", "sleep", "infinity"]
                else:
                    raise OSError("kein caffeinate/systemd-inhibit gefunden")
                self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif self.proc:
                self.proc.terminate()
                self.proc = None
        except Exception as e:
            self.error = str(e)
            return False
        self.active = on
        return True


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1280x880")
        self.minsize(950, 650)
        self.first_run = not CONFIG_FILE.exists()         # vor allem anderen prüfen – der Aufbau speichert schon
        self.cfg = load_config()
        C.update(THEMES.get(self.cfg.get("theme", "Blau"), THEMES["Blau"]))
        lang = self.cfg.get("lang", "auto")
        I18.set_language(system_language() if lang == "auto" else lang)
        self._base_scaling = float(self.tk.call("tk", "scaling"))
        try:
            self.tk.call("tk", "scaling", self._base_scaling * float(self.cfg.get("ui_scale", 1.0)))
        except Exception:
            pass
        self._win_geom = {}
        self._window_hooks = []            # werden für jedes neue Fenster aufgerufen (z. B. Sprachleiste)
        g = self.cfg.get("geom", {}).get("main")
        if g and self._geom_ok(g):
            self.geometry(g)
        self.ui_q = queue.Queue()
        self.ble = SeestarBLE(self.log) if HAVE_BLEAK else None
        if self.ble:
            self.ble.on_lost = lambda: self.ble_lost()
        self._nowifi = SeestarWifi(self.log, lambda e: None, lambda u: None)   # Platzhalter ohne Gerät
        self.model = self.cfg.get("model", "S50") if self.cfg.get("model") in MODELS else "S50"
        self.devices = []
        self.active = None
        for cf in self.cfg.get("custom_filters", []):                 # eigene Filter
            FILTERS[f"{cf['marke']} {cf['modell']}"] = _filter_entry(cf["marke"], cf["modell"], cf["art"],
                                                                    cf.get("band", ""), cf.get("nm"), "eigen", True)
        self.auto_reconnect = self.cfg.get("auto_reconnect", True)
        self._cfg_lock = threading.Lock()
        self._resume_asked = set()
        self._eq_polling = False
        self._pa_history = {}                # host -> [(zeit, x, y)]
        self.eq_test = None
        self.objects = load_catalog()
        self.objects_extra = load_catalog_extra()
        self.objects_all = self.objects + self.objects_extra
        self.site_cache = (float(self.cfg["lat"]), float(self.cfg["lon"])) \
            if self.cfg.get("lat") not in (None, "") and self.cfg.get("lon") not in (None, "") else None
        self._obj_sort = ("alt", True)
        self.plan_steps = []
        self.preview_tab_panel = None
        self.settings_tab_panel = None
        for d in self.cfg.get("devices", []):
            dev = Device(self, d.get("name") or d["ip"], d["ip"])
            dev.selected = d.get("selected", True)
            dev.ext_filter = d.get("filter", NO_FILTER) if d.get("filter") in FILTERS else NO_FILTER
            dev.dewcap = bool(d.get("dewcap", False))
            dev.link = d.get("link", "home") if d.get("link") in ("home", "ap") else "home"
            dev.ap_ssid = d.get("ap_ssid", "")
            dev.ap_pass = secret_unprotect(d.get("ap_pass", ""))
            if dev.ap_pass.startswith("enc"):           # verschlüsselter Firmware-Wert ist kein Passwort
                dev.ap_pass = ""
            dev.pending = dict(d.get("pending", {})) if isinstance(d.get("pending"), dict) else {}
            dev.values.update(dev.pending)
            dev.accessory = bool(d.get("accessory", False))
            dev.protect = bool(d.get("protect", dev.mounted)) or dev.mounted
            self.devices.append(dev)

        self.lat_var = tk.StringVar(master=self, value=str(self.cfg.get("lat", "")))
        self.lon_var = tk.StringVar(master=self, value=str(self.cfg.get("lon", "")))
        self._style()
        self._build()
        if self.devices:
            self.set_active(self.devices[0])
        self.refresh_overview()
        self.after(100, lambda: titlebar_style(self, self.cfg.get("theme", "Blau")))
        self._fs_state = {}
        def toggle_fs(_e=None):
            toggle_fullscreen(self, self._fs_state)
        self.toggle_fullscreen = toggle_fs
        self.bind("<F11>", toggle_fs)
        self.bind("<Escape>", lambda e: self._fs_state.get("fs") and toggle_fs())
        if self.cfg.get("auto_connect", True) and self.devices:         # beim Start mit bekannten Seestars verbinden
            self.after(1200, self.auto_connect_start)
        for k, host in enumerate(list(self.cfg.get("open_previews", []))):      # Vorschaufenster wie beim letzten Mal
            dev = next((x for x in self.devices if x.host == host), None)
            if dev:
                self.after(600 + 200 * k, lambda dev=dev, k=k: self.open_popup(dev, offset=k))
        self.after(100, self._pump)
        if AUTO_SIGNED:
            self.log("Eigene Fassung des Urhebers erkannt – automatisch neu signiert.", "ok")
        self.standby = StandbyBlocker()
        self.after(2000, self._standby_tick)
        self.after(30000, self._settings_poll)
        if TRIAL_STARTS > 0 and TRIAL_COUNT >= TRIAL_WARN_FROM:
            left = max(0, TRIAL_STARTS - TRIAL_COUNT)
            self.after(1500, lambda: messagebox.showinfo(
                APP_NAME, f"Trial version: this is start {TRIAL_COUNT} of {TRIAL_STARTS} – {left} start(s) left."
                + "\n\n" + TRIAL_CONTACT))
        if self.first_run and EDITION == "asiair":        # ASIAIR-Ausgabe: kein Seestar-Assistent
            self.after(600, lambda: self.nb.select(self._tab_index("Standort" if not self._site() else "ASIAIR")))
            if self.cfg.get("loc_consent") is None:
                self.after(900, self.ask_location_consent)
        elif self.first_run:                             # erster Start: Einrichtungsassistent
            self.after(400, self.setup_wizard)
        elif self.cfg.get("loc_consent") is None:        # einmal fragen (auch bei bestehender Konfiguration)
            self.after(800, self.ask_location_consent)
        elif self.cfg.get("loc_consent") is True:
            self.after(1500, lambda: self.loc_locate(quiet=True))
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---- Fenster -------------------------------------------------------------
    def _geom_ok(self, g):
        """Gespeicherte Position nur verwenden, wenn sie noch auf einem Bildschirm liegt (Monitor abgesteckt?)."""
        m = re.match(r"(\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)$", str(g))
        if not m:
            return bool(re.match(r"\d+x\d+$", str(g)))
        off = lambda t: int(t[1:]) if t.startswith("+") else int(t)   # Windows liefert z. B. "+-7" (Fensterrand links)
        w, h, x, y = int(m.group(1)), int(m.group(2)), off(m.group(3)), off(m.group(4))
        mons = monitor_rects()
        if mons:          # Windows: echte Bildschirme – auch links vom Hauptbildschirm (negative x-Werte)
            for l, t, r, b in mons:
                if min(x + w, r) - max(x, l) >= 120 and min(y + 40, b) - max(y, t) >= 30 and t - 20 <= y < b - 40:
                    return w >= 200 and h >= 150
            return False
        vw, vh = self.winfo_vrootwidth() or 10000, self.winfo_vrootheight() or 10000
        vx, vy = self.winfo_vrootx(), self.winfo_vrooty()
        return w >= 200 and h >= 150 and vx - w + 80 < x < vx + max(vw, 3 * self.winfo_screenwidth()) - 80 \
            and vy - 20 < y < vy + max(vh, 2 * self.winfo_screenheight()) - 60

    def make_window(self, title, key=None, size=None, minsize=(320, 200)):
        """Neues, frei anpassbares Fenster. Mit key merkt sich die App Größe und Position (auch auf Monitor 2)."""
        win = tk.Toplevel(self)
        win.title(title)
        win.configure(bg=C["bg"])
        win.resizable(True, True)
        win.minsize(*minsize)
        g = self.cfg.get("geom", {}).get(key) if key else None
        if g and self._geom_ok(g):
            win.geometry(g)
        elif size:
            win.geometry(size)
        state = {"fs": False}

        def toggle_fs(_e=None):
            toggle_fullscreen(win, state)

        win.bind("<F11>", toggle_fs)
        win.bind("<Escape>", lambda e: state["fs"] and toggle_fs())
        win.toggle_fullscreen = toggle_fs
        win.after(50, lambda: titlebar_style(win, self.cfg.get("theme", "Blau")))
        if key:
            def remember(e):
                if e.widget is win and not state["fs"]:
                    self._win_geom[key] = win.geometry()
            win.bind("<Configure>", remember, add="+")

            def store(e):
                if e.widget is win and key in self._win_geom:
                    self.cfg.setdefault("geom", {})[key] = self._win_geom[key]
                    save_config(self.cfg)
            win.bind("<Destroy>", store, add="+")
        for hook in list(self._window_hooks):
            try:
                hook(win)
            except Exception:
                pass
        return win

    # ---- Sprache --------------------------------------------------------------
    AUTO_LANG = "Automatisch (Systemsprache)"

    def _lang_label(self):
        code = self.cfg.get("lang", "auto")
        return self.AUTO_LANG if code == "auto" else I18.names.get(code, "Deutsch")

    def _lang_values(self):
        return [self.AUTO_LANG] + sorted(I18.names.values(), key=lambda n: (n != "Deutsch", n.lower()))

    def _lang_combo(self, parent):
        ttk.Label(parent, text="Sprache:").pack(side="left", padx=(0, 4))
        cb = ttk.Combobox(parent, textvariable=self.lang_var, state="readonly", width=24, values=self._lang_values())
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self.after_idle(self.set_lang))
        return cb

    def _window_lang_bar(self, win):
        bar = ttk.Frame(win, padding=(8, 4, 8, 0))
        bar.pack(side="top", fill="x")
        inner = ttk.Frame(bar)
        inner.pack(side="right")
        self._lang_combo(inner)

    def set_lang(self):
        name = self.lang_var.get()
        code = "auto" if name == self.AUTO_LANG else next((c for c, n in I18.names.items() if n == name), "de")
        if code == self.cfg.get("lang", "auto") and I18.lang == (system_language() if code == "auto" else code):
            return
        self.cfg["lang"] = code
        save_config(self.cfg)
        keep = {v: k for k, v in (("sofort", tr("sofort")), ("Meine Nacht", tr("Meine Nacht")))}   # Vorgaben mitübersetzen
        I18.set_language(system_language() if code == "auto" else code)
        for var in (getattr(self, "pl_start", None), getattr(self, "pl_name", None)):
            if var is not None and var.get() in keep:
                var.set(tr(keep[var.get()]))
        retranslate_all(self)
        for k, t in enumerate(self.TAB_TITLES):
            try:
                self.nb.tab(k, text=t)
            except Exception:
                pass
        for fn in ("refresh_overview", "obj_fill", "rec_compute", "pl_fill", "fc_refresh", "eq_draw", "draw_mosaic",
                   "fc_draw", "wx_update_all", "loc_refresh_ui", "_ble_list_fill"):
            try:
                getattr(self, fn)()
            except Exception:
                pass
        for d in self.devices:
            for pnl in list(d.settings_panels):
                try:
                    pnl.refresh()
                except Exception:
                    pass
        self.log(f"Sprache: {I18.names.get(I18.lang, I18.lang)}", "ok")

    def export_language_template(self):
        """Datei zum Übersetzen in eine weitere Sprache erzeugen."""
        p = filedialog.asksaveasfilename(title="Neue Sprachdatei speichern", defaultextension=".txt",
                                         initialfile="xx.txt", filetypes=[("Text", "*.txt")])
        if not p:
            return
        en = I18._table("en")
        lines = ["# name: Neue Sprache", "# Je Zeile: Nummer<TAB>Übersetzung. Zum Nachschlagen steht der deutsche und der",
                 "# englische Text als Kommentar darüber. Datei als <Sprachkürzel>.txt (z. B. fi.txt) in den Ordner",
                 "# „lang“ neben der App legen – dann erscheint die Sprache in der Auswahl."]
        for i, src in enumerate(I18.source):
            if src not in en and re.fullmatch(r"[\w.:\-]+", src):   # interne Bezeichner – nichts zu übersetzen
                continue
            lines.append("# de: " + src.replace("\n", "\\n"))
            if src in en:
                lines.append("# en: " + en[src].replace("\n", "\\n"))
            lines.append(f"{i}	")
        Path(p).write_text("\n".join(lines) + "\n", encoding="utf-8")
        messagebox.showinfo(APP_NAME, f"Gespeichert: {p}\n\nÜbersetzungen eintragen, die erste Zeile anpassen "
                                      "(„# name: …“) und die Datei in den Ordner „lang“ legen.")

    def set_ui_scale(self):
        try:
            f = int(self.scale_var.get().split()[0]) / 100
        except ValueError:
            return
        self.cfg["ui_scale"] = f
        save_config(self.cfg)
        messagebox.showinfo(APP_NAME, "Die neue Größe wird beim nächsten Start der App übernommen.")

    # ---- Optik ------------------------------------------------------------
    def _style(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except Exception:
            pass
        bg, fg = C["bg"], C["fg"]
        self.configure(bg=bg)
        s.configure(".", background=bg, foreground=fg, fieldbackground=C["field"], font=("Segoe UI", 10),
                    bordercolor=C["border"], lightcolor=C["border"], darkcolor=C["border"], troughcolor=C["field"],
                    selectbackground=C["sel"], selectforeground="white")
        s.configure("TFrame", background=bg)
        s.configure("TLabelframe", background=bg, foreground=fg, bordercolor=C["border"])
        s.configure("TLabelframe.Label", background=bg, foreground=C["accent"], font=("Segoe UI", 10, "bold"))
        s.configure("TLabel", background=bg, foreground=fg)
        s.configure("TButton", background=C["btn"], foreground=C["btn_fg"], bordercolor=C["btn_border"],
                    lightcolor=C["btn"], darkcolor=C["btn"], padding=6, focuscolor=C["btn_border"])
        s.map("TButton", background=[("disabled", C["panel"]), ("pressed", C["btn_press"]), ("active", C["btn_hover"])],
              foreground=[("disabled", C["dim"])], lightcolor=[("active", C["btn_hover"])],
              darkcolor=[("active", C["btn_hover"])])
        s.configure("Accent.TButton", background=C["primary"], foreground=C["primary_fg"],
                    lightcolor=C["primary"], darkcolor=C["primary"], bordercolor=C["primary_border"])
        s.map("Accent.TButton", background=[("disabled", C["panel"]), ("pressed", C["primary_press"]),
                                            ("active", C["primary_hover"])],
              lightcolor=[("active", C["primary_hover"])], darkcolor=[("active", C["primary_hover"])])
        for name, col, hov in (("Connect", "ok_btn", "ok"), ("Disconnect", "err_btn", "err")):
            s.configure(f"{name}.TButton", background=C[col], foreground="white", padding=(10, 3),
                        lightcolor=C[col], darkcolor=C[col], bordercolor=C[col], font=("Segoe UI", 9, "bold"))
            s.map(f"{name}.TButton", background=[("disabled", C["panel"]), ("active", C[hov])],
                  foreground=[("disabled", C["dim"])])
        s.configure("Small.TButton", padding=(6, 2), font=("Segoe UI", 9))
        s.configure("Danger.TButton", background=C["err_btn"], foreground="white", lightcolor=C["err_btn"],
                    darkcolor=C["err_btn"], bordercolor=C["err"], font=("Segoe UI", 10, "bold"))
        s.map("Danger.TButton", background=[("active", C["err"])])
        for orient in ("Vertical", "Horizontal"):
            s.configure(f"{orient}.TScrollbar", background=C["btn"], troughcolor=C["field"], arrowcolor=C["btn_fg"],
                        bordercolor=C["border"], lightcolor=C["btn"], darkcolor=C["btn"], gripcount=0)
            s.map(f"{orient}.TScrollbar", background=[("active", C["btn_hover"])])
        s.configure("TNotebook", background=bg, bordercolor=C["border"], tabmargins=(2, 4, 2, 0))
        s.configure("TNotebook.Tab", background=C["tab"], foreground=C["muted2"], padding=(10, 5),
                    bordercolor=C["border"], lightcolor=C["tab"])
        s.map("TNotebook.Tab", background=[("selected", C["tab_sel"]), ("active", C["btn_hover"])],
              foreground=[("selected", C["fg"]), ("active", C["fg"])],
              lightcolor=[("selected", C["primary"])])
        s.configure("TEntry", fieldbackground=C["field"], foreground=fg, insertcolor=fg)
        s.map("TEntry", fieldbackground=[("disabled", C["panel"])], foreground=[("disabled", C["dim"])])
        s.configure("TSpinbox", fieldbackground=C["field"], foreground=fg, arrowcolor=C["btn_fg"], background=C["btn"])
        s.configure("TCombobox", fieldbackground=C["field"], foreground=fg, background=C["btn"], arrowcolor=C["btn_fg"],
                    insertcolor=fg)                    # Schreibmarke sichtbar (Suchfelder in Steuerung/Mosaik)
        s.map("TCombobox", fieldbackground=[("readonly", C["field"]), ("disabled", C["panel"])],
              foreground=[("readonly", fg), ("disabled", C["dim"])], background=[("active", C["btn_hover"])],
              selectbackground=[("readonly", C["field"])], selectforeground=[("readonly", fg)])
        self.option_add("*TCombobox*Listbox.background", C["field"])
        self.option_add("*TCombobox*Listbox.foreground", fg)
        self.option_add("*TCombobox*Listbox.selectBackground", C["sel"])
        self.option_add("*TCombobox*Listbox.selectForeground", "white")
        s.configure("TCheckbutton", background=bg, foreground=fg, indicatorbackground=C["field"],
                    indicatorforeground=fg)
        s.map("TCheckbutton", background=[("active", bg)], foreground=[("disabled", C["dim"])],
              indicatorbackground=[("selected", C["primary"]), ("disabled", C["panel"])])
        s.configure("TRadiobutton", background=bg, foreground=fg, indicatorbackground=C["field"])
        s.map("TRadiobutton", background=[("active", bg)], indicatorbackground=[("selected", C["primary"])])
        s.configure("Treeview", background=C["field"], fieldbackground=C["field"], foreground=fg, rowheight=26,
                    bordercolor=C["border"])
        s.map("Treeview", background=[("selected", C["sel"])], foreground=[("selected", "white")])
        s.configure("Treeview.Heading", background=C["tab"], foreground=fg, bordercolor=C["border"])
        s.map("Treeview.Heading", background=[("active", C["btn_hover"])])
        s.configure("Status.TLabel", font=("Segoe UI", 10, "bold"))
        s.configure("Head.TLabel", font=("Segoe UI", 11, "bold"))
        s.configure("Card.TFrame", background=C["panel"])
        s.configure("Card.TLabel", background=C["panel"], foreground=fg)
        s.configure("CardHead.TLabel", background=C["panel"], foreground=fg, font=("Segoe UI", 10, "bold"))
        s.configure("CardMuted.TLabel", background=C["panel"], foreground=C["muted"])
        s.configure("Horizontal.TScale", background=C["btn"], troughcolor=C["field"])
        s.configure("TPanedwindow", background=bg)
        s.configure("Sash", background=C["border"], sashthickness=6)
        s.configure("TSeparator", background=C["border"])

    def apply_theme(self, name):
        """Design live umschalten: Stil neu setzen, klassische Tk-Widgets umfärben, Zeichnungen neu zeichnen."""
        if name not in THEMES:
            return
        old = dict(C)
        C.update(THEMES[name])
        self.cfg["theme"] = name
        save_config(self.cfg)
        self._style()
        remap = {}
        for k, v in old.items():
            remap.setdefault(str(v).lower(), C[k])
        def walk(w):
            for opt in ("background", "bg", "foreground", "fg", "insertbackground", "highlightbackground"):
                try:
                    cur = str(w.cget(opt)).lower()
                except Exception:
                    continue
                if cur in remap:
                    try:
                        w.configure(**{opt: remap[cur]})
                    except Exception:
                        pass
            if isinstance(w, tk.Text):
                for tag in w.tag_names():
                    try:
                        cur = str(w.tag_cget(tag, "foreground")).lower()
                        if cur in remap:
                            w.tag_configure(tag, foreground=remap[cur])
                    except Exception:
                        pass
            for c in w.winfo_children():
                walk(c)
        walk(self)
        titlebar_style(self, name)
        for w in self.winfo_children():
            if isinstance(w, tk.Toplevel):
                titlebar_style(w, name)
        for fn in ("eq_draw", "draw_mosaic", "fc_draw", "wx_draw", "refresh_overview"):
            try:
                getattr(self, fn)()
            except Exception:
                pass

    def _build(self):
        bar = ttk.Frame(self, padding=(10, 6, 10, 0))
        bar.pack(fill="x")
        ttk.Label(bar, text=f"🔭 {APP_NAME}", style="Head.TLabel").pack(side="left")
        if EDITION in EDITION_SUFFIX:
            ttk.Label(bar, text=f"  ·  {EDITION_SUFFIX[EDITION]}", style="Head.TLabel", foreground=C["ok"]).pack(side="left")
        self.appbar = ttk.Frame(bar)
        self.appbar.pack(side="right")
        self.lang_var = tk.StringVar(value=self._lang_label())
        self._lang_combo(self.appbar)
        self._window_hooks.append(self._window_lang_bar)
        ttk.Label(self.appbar, text="Design:").pack(side="left", padx=(12, 0))
        self.theme_var = tk.StringVar(value=self.cfg.get("theme", "Blau"))
        cb = ttk.Combobox(self.appbar, textvariable=self.theme_var, state="readonly", width=12, values=list(THEMES))
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self.apply_theme(self.theme_var.get()))
        ttk.Label(self.appbar, text="Größe:").pack(side="left", padx=(12, 0))
        self.scale_var = tk.StringVar(value=f"{int(round(float(self.cfg.get('ui_scale', 1.0)) * 100))} %")
        cb = ttk.Combobox(self.appbar, textvariable=self.scale_var, state="readonly", width=7,
                          values=["80 %", "90 %", "100 %", "110 %", "125 %", "150 %", "175 %"])
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self.set_ui_scale())
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")
        ttk.Label(top, text="Aktives Gerät:").pack(side="left")
        self.active_var = tk.StringVar()
        self.active_cb = ttk.Combobox(top, textvariable=self.active_var, state="readonly", width=26)
        self.active_cb.pack(side="left", padx=6)
        self.active_cb.bind("<<ComboboxSelected>>", lambda e: self.set_active(self._dev_by_label(self.active_var.get())))
        self.status_var = tk.StringVar(value="● Kein Gerät")
        self.status_lbl = ttk.Label(top, textvariable=self.status_var, style="Status.TLabel", foreground=C["err"])
        self.status_lbl.pack(side="left", padx=(4, 18))
        ttk.Label(top, text="Befehle an:").pack(side="left")
        self.target_var = tk.StringVar(value="active")
        ttk.Radiobutton(top, text="aktives Gerät", value="active", variable=self.target_var).pack(side="left", padx=4)
        self.group_rb_text = tk.StringVar(value="alle markierten")
        ttk.Radiobutton(top, textvariable=self.group_rb_text, value="group", variable=self.target_var).pack(side="left")
        mf = ttk.Frame(top)
        mf.pack(side="right")
        ttk.Button(mf, text="↺ Seite zurücksetzen", style="Small.TButton", command=self.reset_page).pack(
            side="left", padx=(0, 14))
        ttk.Label(mf, text="Modell:").pack(side="left")
        self.model_var = tk.StringVar(value=MODELS[self.model]["label"])
        self.model_cb = ttk.Combobox(mf, textvariable=self.model_var, state="readonly", width=18,
                                     values=[m["label"] for m in MODELS.values()])
        self.model_cb.pack(side="left", padx=6)
        self.model_cb.bind("<<ComboboxSelected>>", lambda e: self.set_model(
            next(k for k, v in MODELS.items() if v["label"] == self.model_var.get()), user=True))
        self.model_auto = tk.BooleanVar(value=self.cfg.get("model_auto", True))
        ttk.Checkbutton(mf, text="beim Verbinden erkennen", variable=self.model_auto).pack(side="left")

        paned = ttk.PanedWindow(self, orient="vertical")
        paned.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        nb = ttk.Notebook(paned)
        paned.add(nb, weight=3)
        self.nb = nb
        nb.bind("<<NotebookTabChanged>>", lambda e: self.after(300, self._tab_hint))
        # Aufbau in der technisch nötigen Reihenfolge (Tabs greifen beim Aufbau aufeinander zu) …
        self._tab_overview(nb)
        self._tab_goto(nb)
        self._tab_weather(nb)
        self._tab_wifi(nb)
        self._tab_location(nb)
        self._tab_control(nb)
        self._tab_settings(nb)
        self._tab_mosaic(nb)
        self._tab_plans(nb)
        self._tab_focus(nb)
        self._tab_eq(nb)
        self._tab_preview(nb)
        self._tab_ble(nb)
        self._tab_asiair(nb)
        self._tab_airnet(nb)
        self._tab_airfocus(nb)
        self._tab_console(nb)
        # … angezeigt in der Reihenfolge von TAB_TITLES
        built = dict(zip(self.BUILD_ORDER, nb.tabs()))
        for pos, key in enumerate(self.TAB_KEYS):
            nb.insert(pos, built[key])
        self._tab_titles = list(self.TAB_TITLES)                 # deutsche Originalnamen (unabhängig von der Sprache)
        assert nb.index("end") == len(self.TAB_KEYS) == len(self.TAB_TITLES), "Tab-Listen passen nicht"
        if EDITION == "asiair":
            self._edition_asiair(top)
        else:                                                    # Seestar-Programm: ASIAIR gibt es als eigene Ausgabe
            for k, key in enumerate(self.TAB_KEYS):
                if key in self.AIR_TABS:
                    self.nb.hide(k)

        logf = ttk.Labelframe(paned, text="Protokoll", padding=4)
        paned.add(logf, weight=1)
        self.logbox = tk.Text(logf, height=9, bg=C["textbg"], fg=C["fg"], insertbackground=C["muted2"],
                              font=("Consolas", 9), relief="flat", wrap="word")
        sb = ttk.Scrollbar(logf, command=self.logbox.yview)
        self.logbox.configure(yscrollcommand=sb.set, state="disabled")
        self.logbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for tag, col in {"ok": C["ok"], "err": C["err"], "warn": C["warn"], "tx": C["tx"],
                         "rx": C["rx"], "ev": C["event"], "info": C["fg"]}.items():
            self.logbox.tag_configure(tag, foreground=col)

    # ---- Tab: Übersicht ---------------------------------------------------
    def _tab_overview(self, nb):
        f = ttk.Frame(nb, padding=12)
        nb.add(f, text="Übersicht")

        add = ttk.Labelframe(f, text="Gerät hinzufügen", padding=10)
        add.pack(fill="x")
        ttk.Label(add, text="Name:").pack(side="left")
        self.new_name = tk.StringVar()
        ttk.Entry(add, textvariable=self.new_name, width=18).pack(side="left", padx=6)
        ttk.Label(add, text="IP-Adresse:").pack(side="left")
        self.new_ip = tk.StringVar()
        e = ttk.Entry(add, textvariable=self.new_ip, width=18)
        e.pack(side="left", padx=6)
        e.bind("<Return>", lambda ev: self.add_device_from_form())
        ttk.Button(add, text="＋ Hinzufügen", style="Accent.TButton", command=self.add_device_from_form).pack(side="left")
        ttk.Button(add, text="🔍 Netzwerk durchsuchen", command=lambda: self.do_discover(add_all=True)).pack(side="left", padx=8)

        lf = ttk.Labelframe(f, text="Geräte", padding=(4, 4))
        lf.pack(fill="both", expand=True, pady=10)
        self._dev_list_build(lf)
        ttk.Label(f, text="Klick auf eine Zeile = aktives Gerät (»)  ·  Doppelklick = Vorschau-Fenster  ·  "
                          "Kästchen = Gerät gehört zur Gruppe", foreground=C["muted"]).pack(anchor="w")

        one = ttk.Labelframe(f, text="Aktives Gerät (»)", padding=8)
        one.pack(fill="x", pady=(8, 0))
        for txt, fn in (("Zugangsdaten …", self.access_dialog), ("Umbenennen", self.rename_device),
                        ("Entfernen", self.remove_device),
                        ("Nach oben", lambda: self.move_device(-1)), ("Nach unten", lambda: self.move_device(1))):
            ttk.Button(one, text=txt, command=fn).pack(side="left", padx=(0, 6))

        grp = ttk.Labelframe(f, text="Gruppe – gilt für alle markierten Geräte gleichzeitig", padding=8)
        grp.pack(fill="x", pady=(8, 0))
        r1 = ttk.Frame(grp)
        r1.pack(fill="x")
        ttk.Button(r1, text="Alle verbinden", style="Accent.TButton", command=self.group_connect).pack(side="left")
        ttk.Button(r1, text="Alle trennen", command=lambda: self.group_each(lambda d: d.disconnect())).pack(side="left", padx=6)
        ttk.Button(r1, text="🖼 Alle Vorschauen öffnen", command=self.group_popups).pack(side="left")
        ttk.Button(r1, text="Zeit + Standort", command=lambda: self.do_init(force_group=True)).pack(side="left", padx=6)
        ttk.Button(r1, text="Einstellungen des aktiven Geräts übertragen",
                   command=lambda: self.settings_tab_panel and self.settings_tab_panel.copy_to_group()).pack(side="left")
        r2 = ttk.Frame(grp)
        r2.pack(fill="x", pady=(8, 0))
        for txt, m, prm in (("Arm öffnen", "open_arm", None),
                            ("Autofokus", None, None),
                            ("▶ Stacking starten", "iscope_start_stack", {"restart": True}),
                            ("■ Stacking stoppen", "iscope_stop_view", {"stage": "Stack"})):
            cmd = ((lambda: self.manual_autofocus(True)) if m is None else
                   (lambda: self.open_arm(True)) if m == "open_arm" else (lambda m=m, prm=prm: self.group_rpc(m, prm)))
            ttk.Button(r2, text=txt, command=cmd).pack(side="left", padx=(0, 6))
        ttk.Button(r2, text="GoTo (Ziel aus „Steuerung“)", command=lambda: self.do_goto(force_group=True)).pack(side="left", padx=(0, 6))
        ttk.Button(r2, text="Parken", command=lambda: messagebox.askyesno(APP_NAME, "Alle markierten Geräte parken?")
                   and self.group_rpc("scope_park")).pack(side="left", padx=(0, 6))
        ttk.Button(r2, text="■ NOT-STOPP alle", style="Danger.TButton",
                   command=lambda: self.stop_all(True)).pack(side="right")

    # ---- Tab: Verbindung --------------------------------------------------
    # ---- Tab: Wetter & Tipps --------------------------------------------------
    def _tab_weather(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="Wetter & Tipps")
        top = ttk.Frame(f)
        top.pack(fill="x")
        self.wx_where = tk.StringVar()
        ttk.Label(top, textvariable=self.wx_where, style="Head.TLabel").pack(side="left")
        ttk.Button(top, text="Aktualisieren", style="Accent.TButton", command=self.wx_refresh).pack(side="right")
        self.wx_ok = tk.BooleanVar(value=self.cfg.get("wx_consent") is True)
        ttk.Checkbutton(top, text="Wetterdaten abrufen (open-meteo.com)", variable=self.wx_ok,
                        command=self.wx_toggle_consent).pack(side="right", padx=10)
        self.wx_stamp = tk.StringVar()
        ttk.Label(f, textvariable=self.wx_stamp, foreground=C["muted"]).pack(anchor="w")

        mid = ttk.PanedWindow(f, orient="horizontal")
        mid.pack(fill="both", expand=True, pady=(6, 0))
        card = ttk.Labelframe(mid, text="Die nächste Nacht", padding=8)
        mid.add(card, weight=1)
        self.wx_verdict = tk.Label(card, text="–", font=("Segoe UI", 13, "bold"), bg=C["bg"], fg=C["fg"], anchor="w")
        self.wx_verdict.pack(fill="x")
        self.wx_sum = tk.StringVar(value="")
        lab = ttk.Label(card, textvariable=self.wx_sum, justify="left", wraplength=300)
        lab.pack(anchor="w", fill="x", pady=(4, 0))
        card.bind("<Configure>", lambda e, lab=lab: lab.configure(wraplength=max(200, e.width - 20)))
        chf = ttk.Labelframe(mid, text="48 Stunden: Wolken, Regen, Dunkelheit, Mond", padding=6)
        mid.add(chf, weight=3)
        self.wx_canvas = tk.Canvas(chf, bg=C["canvas"], highlightthickness=0, height=230)
        self.wx_canvas.pack(fill="both", expand=True)
        self.wx_canvas.bind("<Configure>", lambda e: self.wx_draw())
        self.wx_canvas.bind("<Motion>", self._wx_hover)
        self.wx_canvas.bind("<Leave>", lambda e: self.wx_tip.set(""))
        self.wx_tip = tk.StringVar()
        ttk.Label(chf, textvariable=self.wx_tip, foreground=C["muted2"]).pack(anchor="w")
        ttk.Label(chf, text="Balken: Bewölkung gesamt · Streifen oben: tiefe / mittlere / hohe Wolken · blaue Linie: "
                            "Regenwahrscheinlichkeit · gelbe Linie: Mondhöhe · Hintergrund: je dunkler, desto dunkler "
                            "der Himmel", foreground=C["dim"], wraplength=900, justify="left").pack(anchor="w")

        rec = ttk.Labelframe(f, text="Was lohnt sich heute Nacht?", padding=8)
        rec.pack(fill="both", expand=True, pady=(8, 0))
        r = ttk.Frame(rec)
        r.pack(fill="x")
        self.rec_for = tk.StringVar()
        ttk.Label(r, textvariable=self.rec_for, foreground=C["muted2"]).pack(side="left")
        ttk.Label(r, text="Mind.-Höhe:").pack(side="left", padx=(16, 0))
        self.rec_alt = tk.StringVar(value="30°")
        cb = ttk.Combobox(r, textvariable=self.rec_alt, state="readonly", width=5, values=[f"{a}°" for a in range(10, 55, 5)])
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self.rec_compute())
        ttk.Button(r, text="Neu berechnen", command=self.rec_compute).pack(side="left", padx=6)
        self.rec_nowx = tk.BooleanVar(value=False)
        ttk.Checkbutton(r, text="Wetter ignorieren (als wäre es klar)", variable=self.rec_nowx,
                        command=self.rec_compute).pack(side="left", padx=6)
        ttk.Button(r, text="Plan für heute Nacht erstellen", style="Accent.TButton",
                   command=self.rec_make_plan).pack(side="right")
        self.rec_msg = tk.StringVar(value="")
        ttk.Label(rec, textvariable=self.rec_msg, foreground=C["warn"], wraplength=1100,
                  justify="left").pack(fill="x", anchor="w")
        cols = ("id", "name", "type", "when", "alt", "dir", "hours", "moon", "hint")
        heads = ("Objekt", "Name", "Typ", "beste Zeit", "max. Höhe", "Richtung", "gute Std.", "Mond-Abst.", "Hinweis")
        widths = (90, 190, 140, 110, 80, 90, 75, 85, 300)
        tf = ttk.Frame(rec)
        tf.pack(fill="both", expand=True, pady=6)
        self.rec_tree = ttk.Treeview(tf, columns=cols, show="headings", height=7, selectmode="browse")
        for c, h, w in zip(cols, heads, widths):
            self.rec_tree.heading(c, text=h)
            self.rec_tree.column(c, width=w, anchor="w" if c in ("id", "name", "type", "hint") else "center")
        self.rec_tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(tf, command=self.rec_tree.yview)
        sb.pack(side="right", fill="y")
        self.rec_tree.configure(yscrollcommand=sb.set)
        self.rec_tree.bind("<Double-1>", lambda e: self.rec_goto())
        b = ttk.Frame(rec)
        b.pack(fill="x")
        self.rec_btnbar = b
        ttk.Button(b, text="GoTo (Ziel aus „Befehle an“)", style="Accent.TButton", command=self.rec_goto).pack(side="left")
        ttk.Button(b, text="→ Zeitplan", command=lambda: self._rec_to("plan")).pack(side="left", padx=6)
        ttk.Button(b, text="→ Mosaik", command=lambda: self._rec_to("mosaic")).pack(side="left")
        ttk.Label(b, text="Wetterdaten: Open-Meteo.com (CC BY 4.0) · Sonne/Mond werden lokal berechnet",
                  foreground=C["dim"]).pack(side="right")
        self.wx = self.cfg.get("wx_cache") if self.cfg.get("wx_consent") is True else None
        self.recs, self.rec_win = [], None
        self.after(900, self.wx_update_all)
        self.after(15 * 60 * 1000, self._wx_tick)

    # ---- Wetter: Logik --------------------------------------------------------
    def _wx_tick(self):
        if self.cfg.get("wx_consent") is True and (not self.wx or time.time() - self.wx.get("fetched", 0) > 3600):
            self.wx_refresh(quiet=True)
        else:
            self.wx_update_all()
        self.after(15 * 60 * 1000, self._wx_tick)

    def wx_toggle_consent(self):
        if self.wx_ok.get():
            ok = messagebox.askyesno(APP_NAME, "Wetterdaten abrufen?\n\nDazu sendet die App deinen Standort, auf ca. 1 km "
                                               "gerundet, an den kostenlosen Wetterdienst open-meteo.com (ohne Konto, "
                                               "ohne weitere Daten). Abschalten kannst du das jederzeit hier.")
            self.cfg["wx_consent"] = bool(ok)
            self.wx_ok.set(bool(ok))
            save_config(self.cfg)
            if ok:
                self.wx_refresh()
        else:
            self.cfg["wx_consent"] = False
            self.cfg.pop("wx_cache", None)
            self.wx = None
            save_config(self.cfg)
            self.wx_update_all()

    def wx_refresh(self, quiet=False):
        site = self._site()
        if not site:
            self.wx_stamp.set("Kein Standort – bitte im Tab „Standort“ festlegen.")
            return
        if self.cfg.get("wx_consent") is not True:
            self.wx_update_all()
            return
        self.wx_stamp.set("Wetter wird geladen …")

        def job():
            try:
                wx = fetch_weather(*site)
            except Exception as e:
                self.ui(self.wx_stamp.set, f"Wetter nicht abrufbar: {e}")
                if not quiet:
                    self.log(f"Wetter nicht abrufbar: {e}", "warn")
                return

            def apply():
                self.wx = wx
                self.cfg["wx_cache"] = wx
                save_config(self.cfg)
                self.wx_update_all()
            self.ui(apply)
        self.bg(job)

    def wx_update_all(self):
        site = self._site()
        names = {"windows": "Windows", "seestar": "Seestar", "internet": "Internet", "manuell": "manuell eingegeben"}
        if site:
            self.wx_where.set(f"{self.cfg.get('loc_place') or 'Standort'}: {site[0]:.2f}° / {site[1]:.2f}°")
        else:
            self.wx_where.set("Kein Standort festgelegt")
        if self.cfg.get("wx_consent") is not True:
            self.wx_stamp.set("Wetter aus – Häkchen rechts setzen, um Wolken- und Regenvorhersage zu laden. "
                              "Dunkelheit und Mond werden trotzdem angezeigt.")
        elif self.wx:
            self.wx_stamp.set(f"Wetter vom {datetime.fromtimestamp(self.wx['fetched']):%d.%m. %H:%M} · "
                              f"Standort-Quelle: {names.get(self.cfg.get('loc_src'), '–')}")
        self.wx_summary()
        self.wx_draw()
        self.rec_compute()

    def wx_summary(self):
        site = self._site()
        if not site:
            self.wx_verdict.configure(text="Kein Standort", fg=C["muted"])
            self.wx_sum.set("Im Tab „Standort“ festlegen – dann gibt es Nachtzeiten, Wetter und Empfehlungen.")
            return
        ns = night_summary(self.wx, *site)
        if not ns:
            self.wx_verdict.configure(text="Keine echte Nacht", fg=C["warn"])
            self.wx_sum.set("Die Sonne geht in den nächsten 24 Stunden nicht tief genug unter.")
            return
        lim = {-18.0: "astronomisch dunkel", -12.0: "nur nautische Dämmerung (Sommer)", -6.0: "nur bürgerliche Dämmerung"}
        lines = [f"Dunkel: {wd(ns['start'])} {datetime.fromtimestamp(ns['start']):%H:%M} – {datetime.fromtimestamp(ns['end']):%H:%M} "
                 f"({ns['dark_h']:.1f} h, {lim.get(ns['limit'], '')})"]
        if ns["has_wx"]:
            lines.append(f"Klar (≤ 30 % Wolken): {ns['clear_h']:.1f} h")
            if ns["best"]:
                lines.append(f"Beste Phase: {datetime.fromtimestamp(ns['best'][0]):%H:%M} – "
                             f"{datetime.fromtimestamp(ns['best'][1]):%H:%M}")
            lines.append(f"Regenwahrscheinlichkeit: bis {ns['rain_max']:.0f} %")
            if ns["dew_min"] is not None:
                dew = f"Taupunkt-Abstand: min. {ns['dew_min']:.1f} °C"
                if ns["dew_min"] < 3:
                    dew += " → Anti-Tau-Heizung einschalten!"
                lines.append(dew)
            if ns["wind_max"]:
                lines.append(f"Böen bis {ns['wind_max']:.0f} km/h" + (" → Seestar wackelt, kürzer belichten"
                                                                        if ns["wind_max"] > 30 else ""))
            frac = ns["clear_h"] / max(0.5, ns["dark_h"])
            if frac >= 0.6 and ns["rain_max"] < 30:
                self.wx_verdict.configure(text="● Gute Nacht zum Fotografieren", fg=C["ok"])
            elif frac >= 0.25:
                self.wx_verdict.configure(text="● Teilweise brauchbar", fg=C["warn"])
            else:
                self.wx_verdict.configure(text="● Eher nicht – zu bewölkt", fg=C["err"])
        else:
            self.wx_verdict.configure(text="Dunkelheit & Mond (ohne Wetter)", fg=C["muted2"])
        lines.append(f"Mond: {ns['moon_illum'] * 100:.0f} % beleuchtet, um Mitternacht {ns['moon_alt_mid']:.0f}° hoch"
                     if ns["moon_alt_mid"] > 0 else
                     f"Mond: {ns['moon_illum'] * 100:.0f} % beleuchtet, um Mitternacht unter dem Horizont")
        if ns["moon_illum"] > 0.6 and ns["moon_alt_mid"] > 0:
            lines.append("Heller Mond: Nebel mit Schmalbandfilter, Galaxien besser an anderen Tagen.")
        self.wx_sum.set("\n".join(lines))

    def wx_draw(self):
        c = getattr(self, "wx_canvas", None)
        if c is None:
            return
        c.delete("all")
        W, H = max(200, c.winfo_width()), max(150, c.winfo_height())
        site = self._site()
        if not site:
            c.create_text(W // 2, H // 2, text="Kein Standort", fill=C["dim"])
            return
        lat, lon = site
        t0 = (time.time() // 3600) * 3600
        span = 48 * 3600
        L, R, T, B = 34, 8, 30, 22
        X = lambda t: L + (t - t0) / span * (W - L - R)
        Y = lambda v: (H - B) - v / 100 * (H - B - T)
        tt = t0
        while tt < t0 + span:                                    # Himmelshelligkeit
            a = sun_alt(lat, lon, tt + 450)
            col = C["canvas"] if a < -18 else (C["panel"] if a < -12 else (C["panel2"] if a < -6 else C["btn"]))
            c.create_rectangle(X(tt), T, X(tt + 900) + 1, H - B, fill=col, outline="")
            tt += 900
        for v in (25, 50, 75, 100):
            c.create_line(L, Y(v), W - R, Y(v), fill=C["grid"], dash=(2, 3))
            c.create_text(L - 4, Y(v), text=f"{v}", fill=C["dim"], anchor="e", font=("Segoe UI", 7))
        if self.wx:
            for r in self.wx["rows"]:
                if not t0 <= r["t"] < t0 + span:
                    continue
                cc = r.get("cloud_cover")
                if cc is not None:
                    c.create_rectangle(X(r["t"]) + 1, Y(cc), X(r["t"] + 3600) - 1, H - B, fill=C["muted2"],
                                       outline="", stipple="gray50")
                for k, key in enumerate(("cloud_cover_low", "cloud_cover_mid", "cloud_cover_high")):
                    v = r.get(key)
                    if v is not None:
                        g = int(40 + v * 2.1)
                        c.create_rectangle(X(r["t"]), 4 + k * 8, X(r["t"] + 3600), 11 + k * 8,
                                           fill=f"#{g:02x}{g:02x}{min(255, g + 20):02x}", outline="")
            pts = [(X(r["t"] + 1800), Y(r.get("precipitation_probability") or 0)) for r in self.wx["rows"]
                   if t0 <= r["t"] < t0 + span]
            if len(pts) > 1:
                c.create_line(*[x for p in pts for x in p], fill=C["tx"], width=2)
        else:
            c.create_text(W // 2, T + 20, text="Ohne Wetterdaten – nur Dunkelheit und Mond", fill=C["dim"])
        mp = []
        tt = t0
        while tt <= t0 + span:
            mp.append((X(tt), Y(max(0, moon_info(lat, lon, tt)[0]) / 90 * 100)))
            tt += 1800
        c.create_line(*[x for p in mp for x in p], fill=C["warn"], width=1, dash=(4, 2))
        day = None
        for k in range(0, 49, 3):
            tk_ = t0 + k * 3600
            d = datetime.fromtimestamp(tk_)
            c.create_text(X(tk_), H - B + 4, text=d.strftime("%H"), fill=C["dim"], anchor="n", font=("Segoe UI", 7))
            if d.date() != day and d.hour < 3:
                c.create_line(X(tk_), T, X(tk_), H - B, fill=C["border"])
                c.create_text(X(tk_) + 3, T + 2, text=f"{wd(tk_)} {d:%d.%m.}", fill=C["muted"], anchor="nw",
                              font=("Segoe UI", 8))
                day = d.date()
        c.create_line(X(time.time()), T, X(time.time()), H - B, fill=C["accent"], width=2)
        self._wx_geom = (t0, span, L, R, W)

    def _wx_hover(self, e):
        g = getattr(self, "_wx_geom", None)
        site = self._site()
        if not g or not site:
            return
        t0, span, L, R, W = g
        if not L <= e.x <= W - R:
            return
        t = t0 + (e.x - L) / (W - L - R) * span
        r = wx_at(self.wx, t)
        sa = sun_alt(*site, t)
        malt, mill, _, _ = moon_info(*site, t)
        sky = "dunkel" if sa < -18 else ("Dämmerung" if sa < -6 else ("Tag" if sa > 0 else "Dämmerung"))
        txt = f"{wd(t)} {datetime.fromtimestamp(t):%H:%M} · Himmel: {sky} · Mond {max(0, malt):.0f}° ({mill * 100:.0f} %)"
        if r:
            txt += (f" · Wolken {r.get('cloud_cover', '–')} % (tief {r.get('cloud_cover_low', '–')}, mittel "
                    f"{r.get('cloud_cover_mid', '–')}, hoch {r.get('cloud_cover_high', '–')}) · Regen "
                    f"{r.get('precipitation_probability', '–')} % · {r.get('temperature_2m', '–')} °C, Taupunkt "
                    f"{r.get('dew_point_2m', '–')} °C · Böen {r.get('wind_gusts_10m', '–')} km/h")
        self.wx_tip.set(txt)

    # ---- Empfehlungen --------------------------------------------------------------
    def _rec_device_info(self):
        d = self.active
        model = d.model if d and d.model else self.model
        f = FILTERS.get(d.ext_filter if d else NO_FILTER, FILTERS[NO_FILTER])
        nb = f["art"] in (DUAL, TRI, QUAD, LINE) and (f["nm"] is None or f["nm"] <= 15)
        return model, nb, f

    def rec_compute(self):
        if not hasattr(self, "rec_tree"):
            return
        site = self._site()
        model, nb, f = self._rec_device_info()
        self.rec_for.set(f"Für {MODELS[model]['label']}" + (f" mit {f['modell']}" if f["modell"] != NO_FILTER else
                                                            " ohne externen Filter")
                         + (" · bevorzugt Emissionsnebel" if nb else ""))
        self.rec_tree.delete(*self.rec_tree.get_children())
        if not site:
            self.rec_msg.set("Noch kein Standort festgelegt – Tab „Standort“.")
            return
        min_alt = int(self.rec_alt.get().rstrip("°"))
        objs, wx = self.objects, (None if self.rec_nowx.get() else self.wx)

        def job():
            recs, win = recommend(objs, site[0], site[1], model, wx, nb, min_alt)

            def apply():
                self.recs, self.rec_win = recs, win
                if recs:
                    self.rec_msg.set("Ohne Wetter berechnet – nur sinnvoll, wenn es doch aufklart."
                                     if self.rec_nowx.get() and self.wx else "")
                elif win is None:
                    self.rec_msg.set("Heute wird es an deinem Standort nicht richtig dunkel.")
                elif wx:
                    self.rec_msg.set("Heute Nacht ist keine klare Stunde vorhergesagt – deshalb keine Empfehlungen. "
                                     "Mit „Wetter ignorieren“ siehst du, was ohne Wolken möglich wäre.")
                else:
                    self.rec_msg.set(f"Kein Objekt steht heute lange genug über {min_alt}° – Mindesthöhe verringern.")
                self.rec_tree.delete(*self.rec_tree.get_children())
                for k, r in enumerate(recs):
                    o = r["o"]
                    when = (f"{datetime.fromtimestamp(r['from']):%H:%M}–{datetime.fromtimestamp(r['to']):%H:%M}"
                            if r["from"] else "–")
                    self.rec_tree.insert("", "end", iid=str(k), values=(
                        o[0], o[1], o[3], when, f"{r['max_alt']:.0f}°", self._rec_dir(r, site), f"{r['good_h']:.1f}",
                        f"{r['moon_sep']:.0f}°" if r["moon_sep"] is not None else "–", r["hint"] or "–"))
            self.ui(apply)
        self.bg(job)

    DIRS = ("N", "NO", "O", "SO", "S", "SW", "W", "NW")

    def _rec_dir(self, r, site):
        """Himmelsrichtung zu Beginn und Ende des guten Zeitfensters, z. B. „O → S“."""
        if not r.get("from"):
            return "–"
        o = r["o"]
        dd = []
        for tt in (r["from"], r["to"] - 1800):
            az = alt_az(o[4], o[5], site[0], site[1], tt)[1]
            dd.append(tr(self.DIRS[int((az + 22.5) % 360 // 45)]))
        return dd[0] if dd[0] == dd[1] else f"{dd[0]} → {dd[1]}"

    def _rec_sel(self):
        sel = self.rec_tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Bitte zuerst ein Objekt in der Liste auswählen.")
            return None
        return self.recs[int(sel[0])]

    def rec_goto(self):
        r = self._rec_sel()
        if r:
            self.obj_tree.selection_set(r["o"][0]) if self.obj_tree.exists(r["o"][0]) else None
            oid, name, alias, typ, ra, dec, mag, size = r["o"]
            rn, dn = precess_j2000(ra, dec)
            lp = bool(self.active and self.active.values.get("lp"))
            self.rpc("iscope_start_view", {"mode": "star", "target_ra_dec": [rn, dn],
                                           "target_name": (f"{oid} {name}" if name else oid)[:40], "lp_filter": lp})

    def _rec_to(self, where):
        r = self._rec_sel()
        if not r:
            return
        o = r["o"]
        if where == "plan":
            self.plan_add_target(o)
            self.nb.select(self._tab_index("Zeitpläne"))
        else:
            self.mz_name.set(o[0].replace(" ", ""))
            self.mz_ra.set(f"{o[4]:.5f}")
            self.mz_dec.set(f"{o[5]:.4f}")
            self.nb.select(self._tab_index("Mosaik"))

    def rec_make_plan(self):
        if not self.recs or not self.rec_win:
            messagebox.showinfo(APP_NAME, self.rec_msg.get() or "Noch keine Empfehlungen – Standort festlegen und „Neu berechnen“.")
            return
        min_alt = int(self.rec_alt.get().rstrip("°"))
        plan = auto_plan(self.recs, self.rec_win[0], self.rec_win[1], min_alt=min_alt)
        if not plan:
            messagebox.showinfo(APP_NAME, "Für heute Nacht ließ sich kein sinnvoller Plan bilden.")
            return
        txt = "\n".join(f"{datetime.fromtimestamp(a):%H:%M}–{datetime.fromtimestamp(b):%H:%M}  {r['o'][0]} {r['o'][1]}"
                        for r, a, b in plan)
        if EDITION == "asiair":
            self._air_plan_from_recs(plan, min_alt, txt)
            return
        if not messagebox.askyesno(APP_NAME, f"Vorschlag für heute Nacht:\n\n{txt}\n\nAls neuen Zeitplan übernehmen? "
                                             "(Der bisher geöffnete Plan im Editor wird ersetzt, gespeicherte Pläne "
                                             "bleiben erhalten.)"):
            return
        self.pl_new()
        self.pl_name.set(f"Nacht {datetime.fromtimestamp(self.rec_win[0]):%d.%m.%Y}")
        _secs, _alt, af, lp = self._pl_common()
        first = datetime.fromtimestamp(plan[0][1])
        if plan[0][1] > time.time() + 300:
            self.pl_start.set(first.strftime("%H:%M"))
        for r, a, b in plan:
            o = r["o"]
            self._pl_add({"t": "capture", "name": (f"{o[0]} {o[1]}" if o[1] else o[0])[:40], "ra": o[4], "dec": o[5],
                          "secs": int(b - a - 300), "min_alt": min_alt, "max_wait_h": 1, "af": af, "lp": lp})
        self.nb.select(self._tab_index("Zeitpläne"))
        self.log(f"Plan mit {len(plan)} Zielen für heute Nacht erstellt – bitte prüfen und speichern.", "ok")

    # ---- Grundeinstellung pro Seite ---------------------------------------------
    TAB_KEYS = ("overview", "location", "weather", "control", "focus", "settings", "eq", "goto", "mosaic", "plans",
                "preview", "wifi", "ble", "asiair", "airnet", "airfocus", "console")
    TAB_TITLES = ("Übersicht", "Standort", "Wetter & Tipps", "Steuerung", "Fokus & Filter", "Einstellungen", "EQ-Modus",
                  "GoTo", "Mosaik", "Zeitpläne", "Vorschau", "WLAN", "Bluetooth", "ASIAIR", "ASIAIR-Netzwerk",
                  "ASIAIR-Filter & Fokus", "Konsole")
    AIR_TABS = ("asiair", "airnet", "airfocus")
    BUILD_ORDER = ("overview", "goto", "weather", "wifi", "location", "control", "settings", "mosaic", "plans", "focus",
                   "eq", "preview", "ble", "asiair", "airnet", "airfocus", "console")
    RESET_INFO = {
        "overview": "Alle Geräte wieder in die Gruppe aufnehmen und die Eingabefelder leeren. Die Geräteliste bleibt.",
        "goto": "Suche, Typ- und Höhenfilter sowie die Sortierung auf Standard.",
        "weather": "Mindesthöhe 30°, Empfehlungen neu berechnen. Das Wetter-Einverständnis bleibt, wie es ist.",
        "wifi": "Automatisch verbinden (beim Start und bei Abbruch) und Zeit/Standort beim Verbinden senden wieder an, Feld IP-Adresse leeren, PEM-Schlüssel-Pfad entfernen.",
        "location": "Standort und Einverständnis löschen – die App fragt beim nächsten Start erneut.",
        "control": "Geschwindigkeit 1000, Dauer 2 s, Zielfelder leeren.",
        "settings": "Empfohlene Werte an das aktive Gerät senden (10 s, Gain 80, Dithering 50 px alle 5, "
                    "Dark-Kalibrierung an, nur gute Frames speichern, Heizung aus).",
        "mosaic": "Raster 2×2, 20 % Überlappung, 30 min pro Panel, Framing 2×, 0°, 120 min, Ziel leeren, Standby-Sperre an.",
        "plans": "Editor leeren (neuer Plan) und Eingaben auf Standard. Gespeicherte Pläne bleiben erhalten.",
        "focus": "Autofokus-Einstellungen passend zum Filter, Suchbereich ±80, Schrittweite 10, Kurve leeren. "
                 "Filter, Arm-Schutz und gemerkte Fokuspositionen bleiben.",
        "eq": "Startposition 3, Bereich ±2°, automatisch nachmessen an, Test 60 s / 10 min, Live-Messung aus.",
        "preview": "Stretch 0,20, nicht verknüpft, nicht linear, Stack automatisch an.",
        "ble": "Liste leeren, „Nur Seestar“ an, Schreib-Feld auf Standard.",
        "asiair": "Meridian-Flip an (5 min nach dem Meridian, Belichtung abwarten, ohne Autofokus), Guiding an und nach "
                  "dem Flip neu kalibrieren, Dithering alle 3 Bilder, am Ende nichts tun, 120 s / Gain 252 / 60 Bilder. "
                  "Verbindung und gespeicherte Pläne bleiben.",
        "airnet": "Automatisch neu verbinden an, Plan wartet bei Abbruch bis zu 15 min. Adressen, WLAN-Name und "
                  "Passwort bleiben.",
        "airfocus": "Autofokus-Einstellungen auf Standard (automatische Belichtung, Schrittweite 50, 9 Positionen, Spiel 0), "
                    "Plan-Optionen aus. Filterbelegung und gemerkte Fokuspositionen bleiben.",
        "console": "Methode get_device_state, Parameter und Ausgabe leeren.",
    }

    def reset_page(self):
        idx = self.nb.index(self.nb.select())
        key = self.TAB_KEYS[idx] if idx < len(self.TAB_KEYS) else None
        if not key:
            return
        title = self._tab_titles[idx] if idx < len(self._tab_titles) else key
        if not messagebox.askyesno(APP_NAME, f"Seite „{title}“ auf Grundeinstellung zurücksetzen?\n\n"
                                             f"{self.RESET_INFO[key]}"):
            return
        getattr(self, f"_reset_{key}")()
        self.log(f"Seite „{title}“ auf Grundeinstellung zurückgesetzt.", "ok")

    def _reset_overview(self):
        self.new_name.set("")
        self.new_ip.set("")
        for d in self.devices:
            d.selected = True
        self.save_devices()
        self.refresh_overview()

    def _reset_goto(self):
        self.obj_q.set("")
        self.obj_type.set("Alle")
        self.obj_alt.set("über 20°")
        self.obj_named.set(True)
        self._obj_sort = ("alt", True)
        self.obj_fill()

    def _reset_weather(self):
        self.rec_alt.set("30°")
        self.wx_update_all()

    def _reset_wifi(self):
        self.auto_rc_var.set(True)
        self.auto_reconnect = True
        self.cfg["auto_reconnect"] = True
        self.auto_init_var.set(True)
        self.cfg["auto_init"] = True
        self.auto_conn_var.set(True)
        self.cfg["auto_connect"] = True
        self.ip_var.set("")
        self.pem_var.set("")
        self.cfg["pem"] = ""
        save_config(self.cfg)

    def _reset_location(self):
        for k in ("lat", "lon", "loc_src", "loc_acc_m", "loc_place", "loc_time", "loc_consent", "loc_consent_time",
                  "loc_sources"):
            self.cfg.pop(k, None)
        save_config(self.cfg)
        self.lat_var.set("")
        self.lon_var.set("")
        self.site_cache = None
        for k, v in self.loc_src_vars.items():
            v.set(k != "internet")
        for e in (self.loc_lat_e, self.loc_lon_e, self.loc_place_e):
            e.state(["!disabled"])
            e.delete(0, "end")
        self.loc_status.set("")
        self.loc_refresh_ui()
        self.obj_fill()
        self.wx_update_all()

    def _reset_control(self):
        self.speed_var.set(1000)
        self.dur_var.set(2)
        for v in (self.cat_var, self.tname_var, self.ra_var, self.dec_var):
            v.set("")

    def _reset_settings(self):
        p = self.settings_tab_panel
        if p and p.device:
            p.recommended()
        else:
            messagebox.showinfo(APP_NAME, "Kein aktives Gerät – die Werte werden beim nächsten Gerät gesetzt.")

    def _mz_nosleep_changed(self):
        self.cfg["mz_nosleep"] = bool(self.mz_nosleep.get())
        save_config(self.cfg)
        self.after(50, self._standby_tick_once)

    def _standby_tick_once(self):
        """Sofort neu bewerten (ohne eine zweite Prüfschleife zu starten)."""
        running = self._mosaic_running()
        want = bool(running) and bool(self.mz_nosleep.get())
        if want != self.standby.active:
            was = self.standby.active
            self.standby.set(want)
            if was and not want:
                self.log("Standby wieder erlaubt.", "info")
            elif want and self.standby.active:
                self.log(f"Standby von PC/Laptop gesperrt, solange das Mosaik läuft ({', '.join(running)}).", "ok")

    def _reset_mosaic(self):
        for v, val in ((self.mz_cat, ""), (self.mz_name, "Mosaik"), (self.mz_ra, ""), (self.mz_dec, ""),
                       (self.mz_mode, "grid"), (self.mz_cols, "2"), (self.mz_rows, "2"), (self.mz_ov, "20 %"),
                       (self.mz_pt, "30 min"), (self.mz_scale, "2,0×"), (self.mz_angle, "0°"),
                       (self.mz_total, "120 min"), (self.mz_lp, "Geräteeinstellung")):
            v.set(val)
        self.mz_af.set(True)
        self.rf_var.set(REFOCUS_DEFAULT)
        self._rf_changed()
        self.mz_nosleep.set(True)
        self._mz_nosleep_changed()
        self.draw_mosaic()

    def _reset_plans(self):
        self.pl_new()
        self.rf_var.set(REFOCUS_DEFAULT)
        self._rf_changed()
        for v, val in ((self.pl_dur, "60 min"), (self.pl_alt, "30°"), (self.pl_af, "automatisch"),
                       (self.pl_lp, "Geräteeinstellung"), (self.pl_wait, "22:00"), (self.pl_start, tr("sofort")),
                       (self.pl_end, END_ACTIONS["open"])):
            v.set(val)
        self.pl_name.set(tr("Meine Nacht"))
        self.pl_check_end()
        self.pl_fill()

    def _reset_focus(self):
        d = self.active
        self._fc_load_filter_defaults(d.ext_filter if d else NO_FILTER)
        self.fc_span.set("± 80")
        self.fc_step.set("10")
        self.fc_points = []
        self.fc_status.set("")
        self.fc_draw()

    def _reset_eq(self):
        self.pa_pos.set("3 (Standard, oben)")
        self.pa_range.set("±2°")
        self.pa_repeat.set(True)
        self.et_exp.set("60 s")
        self.et_dur.set("10 min")
        self.lvl_live.set(False)
        self.et_txt.set("")
        self.eq_draw()

    def _reset_preview(self):
        p = self.preview_tab_panel
        if p:
            p.stretch_var.set(0.20)
            p.linked_var.set(False)
            p.raw_var.set(False)
            p.auto_var.set(True)
            p.restretch()

    def _reset_ble(self):
        if not HAVE_BLEAK:
            return
        if self.ble_conn:
            self.ble_toggle(self.ble_conn)
        self.ble_found = []
        self.ble_only.set(True)
        self.ble_payload.set('{"id":1,"method":"get_device_state"}')
        self.ble_tree.delete(*self.ble_tree.get_children())
        self._ble_list_fill()

    def _reset_console(self):
        self.c_method.set("get_device_state")
        self.c_params.set("")
        self.c_out.delete("1.0", "end")

    # ---- Tab: Objekte & GoTo ------------------------------------------------
    def _tab_goto(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="GoTo")
        bar = ttk.Frame(f)
        bar.pack(fill="x")
        ttk.Label(bar, text="Suche:").pack(side="left")
        self.obj_q = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.obj_q, width=24)
        e.pack(side="left", padx=6)
        self.obj_q.trace_add("write", lambda *a: self.obj_fill())
        ttk.Label(bar, text="Typ:").pack(side="left", padx=(8, 0))
        self.obj_type = tk.StringVar(value="Alle")
        cb = ttk.Combobox(bar, textvariable=self.obj_type, state="readonly", width=20,
                          values=["Alle", "Galaxien", "Nebel", "Sternhaufen", "Planetarische Nebel", "Supernovaüberreste"])
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self.obj_fill())
        ttk.Label(bar, text="Höhe jetzt:").pack(side="left", padx=(8, 0))
        self.obj_alt = tk.StringVar(value="über 20°")
        cb = ttk.Combobox(bar, textvariable=self.obj_alt, state="readonly", width=10,
                          values=["alle", "über 0°"] + [f"über {a}°" for a in range(10, 55, 5)])
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self.obj_fill())
        self.obj_named = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="nur Messier & benannte", variable=self.obj_named, command=self.obj_fill).pack(side="left", padx=8)
        self.obj_season = tk.BooleanVar(value=bool(self.cfg.get("obj_season", False)))
        ttk.Checkbutton(bar, text="nur jetzt in Saison (sortiert)", variable=self.obj_season,
                        command=self._obj_season_toggle).pack(side="left")
        self.obj_hint = tk.StringVar()
        self.obj_hint2 = tk.StringVar()
        ttk.Label(bar, textvariable=self.obj_hint2, foreground=C["muted"]).pack(side="right", padx=(8, 0))
        ttk.Label(bar, textvariable=self.obj_hint, foreground=C["muted"]).pack(side="right")

        cols = ("id", "name", "type", "mag", "size", "alt", "az", "trans", "season", "fit")
        heads = ("Objekt", "Name", "Typ", "Hell.", "Größe", "Höhe jetzt", "Richtung", "Kulmination", "beste Monate", "Bildfeld")
        widths = (90, 220, 150, 50, 60, 80, 70, 110, 130, 110)
        tf = ttk.Frame(f)
        tf.pack(fill="both", expand=True, pady=8)
        self.obj_tree = ttk.Treeview(tf, columns=cols, show="headings", selectmode="browse")
        for c, h, w in zip(cols, heads, widths):
            self.obj_tree.heading(c, text=h, command=lambda c=c: self._obj_sort_by(c))
            self.obj_tree.column(c, width=w, anchor="w" if c in ("id", "name", "type", "fit") else "center")
        self.obj_tree.tag_configure("low", foreground=C["dim"])
        self.obj_tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(tf, command=self.obj_tree.yview)
        sb.pack(side="right", fill="y")
        self.obj_tree.configure(yscrollcommand=sb.set)
        self.obj_tree.bind("<<TreeviewSelect>>", lambda e: self._obj_detail())
        self.obj_tree.bind("<Double-1>", lambda e: self.obj_goto())

        self.obj_info = tk.StringVar(value="Objekt auswählen.")
        ttk.Label(f, textvariable=self.obj_info, foreground=C["muted2"], wraplength=1100, justify="left").pack(anchor="w")
        b = ttk.Frame(f)
        b.pack(fill="x", pady=(8, 0))
        self.obj_btnbar = b
        ttk.Button(b, text="▶ GoTo + Live (Ziel aus „Befehle an“)", style="Accent.TButton",
                   command=self.obj_goto).pack(side="left")
        ttk.Button(b, text="GoTo auf allen markierten", command=lambda: self.obj_goto(True)).pack(side="left", padx=6)
        ttk.Button(b, text="Nur schwenken", command=lambda: self.obj_goto(slew=True)).pack(side="left")
        ttk.Button(b, text="→ Zeitplan", command=self.obj_to_plan).pack(side="right")
        ttk.Button(b, text="→ Mosaik", command=self.obj_to_mosaic).pack(side="right", padx=6)
        ttk.Button(b, text="→ Steuerung", command=self.obj_to_control).pack(side="right")
        self.after(500, self.obj_fill)
        self.after(60000, self._obj_tick)

    def _tab_wifi(self, nb):
        f = ttk.Frame(nb, padding=12)
        nb.add(f, text="WLAN")

        box = ttk.Labelframe(f, text="Seestar im Netzwerk", padding=10)
        box.pack(fill="x")
        ttk.Label(box, text="IP-Adresse:").grid(row=0, column=0, sticky="w")
        self.ip_var = tk.StringVar(value=self.cfg.get("ip", ""))
        self.ip_cb = ttk.Combobox(box, textvariable=self.ip_var, width=28)
        self.ip_cb.grid(row=0, column=1, padx=6, sticky="w")
        ttk.Button(box, text="🔍 Suchen", command=self.do_discover).grid(row=0, column=2, padx=4)
        ttk.Label(box, text="(Stationsmodus: IP aus Router/Seestar-App · AP-Modus: 10.0.0.1)",
                  foreground=C["muted"]).grid(row=0, column=3, sticky="w", padx=8)

        ttk.Label(box, text="PEM-Schlüssel:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.pem_var = tk.StringVar(value=self.cfg.get("pem", ""))
        ttk.Entry(box, textvariable=self.pem_var, width=60).grid(row=1, column=1, columnspan=2, sticky="we", padx=6, pady=(8, 0))
        ttk.Button(box, text="…", width=3, command=self.pick_pem).grid(row=1, column=3, sticky="w", pady=(8, 0))
        ttk.Label(box, text="Nur für neuere Firmware nötig – siehe README.", foreground=C["muted"]).grid(
            row=2, column=1, columnspan=3, sticky="w", padx=6)

        btns = ttk.Frame(box)
        btns.grid(row=3, column=0, columnspan=4, sticky="w", pady=(12, 0))
        ttk.Button(btns, text="Verbinden (als aktives Gerät)", style="Accent.TButton", command=self.do_connect).pack(side="left")
        ttk.Button(btns, text="Aktives trennen", command=lambda: self.active and self.bg(self.active.disconnect)).pack(side="left", padx=6)
        ttk.Button(btns, text="Erneut anmelden", command=lambda: self.bg(self.wifi.authenticate)).pack(side="left")
        ttk.Button(btns, text="Einrichtungsassistent", command=self.setup_wizard).pack(side="left", padx=(16, 0))
        ttk.Button(btns, text="Neue Sprache hinzufügen …", command=self.export_language_template).pack(side="left", padx=6)
        ttk.Button(btns, text="Alles zurücksetzen …", command=self.reset_all).pack(side="left", padx=6)
        self.auto_rc_var = tk.BooleanVar(value=self.auto_reconnect)
        def _toggle_rc():
            self.auto_reconnect = bool(self.auto_rc_var.get())
            self.cfg["auto_reconnect"] = self.auto_reconnect
            save_config(self.cfg)
        opts = ttk.Frame(box)
        opts.grid(row=4, column=0, columnspan=4, sticky="w", pady=(8, 0))
        ttk.Checkbutton(opts, text="Bei Abbruch automatisch neu verbinden (alle Geräte)", variable=self.auto_rc_var,
                        command=_toggle_rc).pack(side="left", padx=(0, 16))
        self.auto_conn_var = tk.BooleanVar(value=self.cfg.get("auto_connect", True))
        ttk.Checkbutton(opts, text="Beim Start automatisch verbinden", variable=self.auto_conn_var,
                        command=lambda: (self.cfg.update(auto_connect=bool(self.auto_conn_var.get())),
                                         save_config(self.cfg))).pack(side="left")
        ttk.Button(opts, text="Hinweise wieder anzeigen", style="Small.TButton",
                   command=self.hints_reset).pack(side="left", padx=(16, 0))

        init = ttk.Labelframe(f, text="Initialisierung (Zeit & Standort an Seestar senden)", padding=10)
        init.pack(fill="x", pady=10)
        self.loc_short = tk.StringVar(value="Standort: –")
        ttk.Label(init, textvariable=self.loc_short).grid(row=0, column=0, sticky="w")
        ttk.Button(init, text="Zeit + Standort senden", command=self.do_init).grid(row=0, column=1, padx=10)
        ttk.Button(init, text="Standort ändern …", command=lambda: self.nb.select(self._tab_index("Standort"))).grid(
            row=0, column=2)
        ttk.Label(init, text="(geht an das Ziel aus „Befehle an“)", foreground=C["muted"]).grid(row=0, column=3, padx=8)
        self.auto_init_var = tk.BooleanVar(value=self.cfg.get("auto_init", True))
        ttk.Checkbutton(init, text="Bei jedem Verbinden automatisch senden (wie die Seestar-App)", variable=self.auto_init_var,
                        command=lambda: (self.cfg.update(auto_init=bool(self.auto_init_var.get())),
                                         save_config(self.cfg))).grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))

        st = ttk.Labelframe(f, text="Gerätestatus", padding=10)
        st.pack(fill="both", expand=True)
        ttk.Button(st, text="Status abrufen", command=self.do_state).pack(anchor="w")
        self.state_txt = tk.Text(st, height=10, bg=C["textbg"], fg=C["fg"], font=("Consolas", 9), relief="flat")
        self.state_txt.pack(fill="both", expand=True, pady=(6, 0))

    # ---- Tab: Steuerung ---------------------------------------------------
    # ---- Tab: Standort ---------------------------------------------------------
    def _tab_location(self, nb):
        f = ttk.Frame(nb, padding=12)
        nb.add(f, text="Standort")
        cols = ttk.Frame(f)
        cols.pack(fill="both", expand=True)
        cols.columnconfigure(0, weight=1)
        cols.columnconfigure(1, weight=1)

        cur = ttk.Labelframe(cols, text="Aktuelle Position", padding=10)
        cur.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.loc_big = tk.StringVar(value="Noch kein Standort festgelegt.")
        ttk.Label(cur, textvariable=self.loc_big, font=("Consolas", 12), justify="left").pack(anchor="w")
        self.loc_meta = tk.StringVar()
        ttk.Label(cur, textvariable=self.loc_meta, foreground=C["muted"], justify="left", wraplength=480).pack(anchor="w", pady=(6, 0))
        b = ttk.Frame(cur)
        b.pack(anchor="w", pady=(10, 0))
        ttk.Button(b, text="Zeit + Standort an Seestar senden", style="Accent.TButton", command=self.do_init).pack(side="left")
        ttk.Label(b, text="  (Ziel aus „Befehle an“)", foreground=C["muted"]).pack(side="left")
        ttk.Label(cur, text="Gebraucht für: Zeit und Standort am Seestar, Objekthöhen und Kulmination im GoTo-Tab, "
                            "Mindesthöhe in Zeitplänen, Wedge-Winkel im EQ-Modus.",
                  foreground=C["muted"], wraplength=480, justify="left").pack(anchor="w", pady=(10, 0))
        ttk.Label(cur, text="Hinweis: Ist die Seestar-App auf dem Handy gleichzeitig verbunden, überschreibt sie den "
                            "Standort im Seestar mit der Position des Handys.",
                  foreground=C["muted"], wraplength=480, justify="left").pack(anchor="w", pady=(6, 0))

        au = ttk.Labelframe(cols, text="Automatisch ermitteln", padding=10)
        au.grid(row=0, column=1, sticky="nsew")
        self.loc_auto = tk.BooleanVar(value=self.cfg.get("loc_consent") is True)
        ttk.Checkbutton(au, text="Standort automatisch ermitteln (Einverständnis)", variable=self.loc_auto,
                        command=self.loc_toggle_consent).pack(anchor="w")
        self.loc_consent_txt = tk.StringVar()
        ttk.Label(au, textvariable=self.loc_consent_txt, foreground=C["muted"], wraplength=480).pack(anchor="w", pady=(2, 8))
        self.loc_src_vars, self.loc_src_cbs = {}, []
        srcs = self.cfg.get("loc_sources", {"windows": True, "seestar": True, "internet": False})
        for key, (title, desc) in LOC_SOURCES.items():
            v = tk.BooleanVar(value=bool(srcs.get(key, key != "internet")))
            self.loc_src_vars[key] = v
            cb = ttk.Checkbutton(au, text=title, variable=v, command=self._loc_save_sources)
            cb.pack(anchor="w")
            self.loc_src_cbs.append(cb)
            ttk.Label(au, text=desc, foreground=C["muted"], wraplength=460, justify="left").pack(anchor="w", padx=(22, 0), pady=(0, 6))
        b = ttk.Frame(au)
        b.pack(anchor="w")
        self.loc_now_btn = ttk.Button(b, text="Jetzt ermitteln", command=self.loc_locate)
        self.loc_now_btn.pack(side="left")
        self.loc_status = tk.StringVar()
        ttk.Label(au, textvariable=self.loc_status, wraplength=480, justify="left").pack(anchor="w", pady=(6, 0))

        man = ttk.Labelframe(f, text="Manuell eingeben", padding=10)
        man.pack(fill="x", pady=(10, 0))
        self.loc_man_note = tk.StringVar()
        ttk.Label(man, textvariable=self.loc_man_note, foreground=C["warn"], wraplength=1050).grid(
            row=0, column=0, columnspan=6, sticky="w", pady=(0, 6))
        ttk.Label(man, text="Breite:").grid(row=1, column=0, sticky="w")
        self.loc_lat_e = ttk.Entry(man, width=20)
        self.loc_lat_e.grid(row=1, column=1, padx=6)
        ttk.Label(man, text="Länge:").grid(row=1, column=2, sticky="w")
        self.loc_lon_e = ttk.Entry(man, width=20)
        self.loc_lon_e.grid(row=1, column=3, padx=6)
        ttk.Label(man, text="Ortsname (optional):").grid(row=1, column=4, sticky="w", padx=(10, 0))
        self.loc_place_e = ttk.Entry(man, width=22)
        self.loc_place_e.grid(row=1, column=5, padx=6)
        self.loc_man_btn = ttk.Button(man, text="Übernehmen", style="Accent.TButton", command=self.loc_manual_apply)
        self.loc_man_btn.grid(row=1, column=6, padx=6)
        ttk.Label(man, text="Formate: 52,52 · 52.52 · 52°31'12\" N · 13° 24′ O · Süden und Westen mit „-“ oder S/W. "
                            "Den Standort findest du z. B. in jeder Karten-App (Rechtsklick/langer Druck auf den Ort).",
                  foreground=C["muted"]).grid(row=2, column=0, columnspan=7, sticky="w", pady=(6, 0))
        self.loc_refresh_ui()

    def _tab_control(self, nb):
        f = ttk.Frame(nb, padding=12)
        nb.add(f, text="Steuerung")
        left = ttk.Frame(f)
        left.pack(side="left", fill="y")
        right = ttk.Frame(f)
        right.pack(side="left", fill="both", expand=True, padx=(16, 0))

        arm = ttk.Labelframe(left, text="Arm", padding=10)
        arm.pack(fill="x")
        ttk.Button(arm, text="Arm öffnen / Sternenmodus", command=lambda: self.open_arm()).pack(fill="x")
        ttk.Button(arm, text="Parken (Arm schließen)", command=self.do_park).pack(fill="x", pady=4)
        ttk.Button(arm, text="■ Alles stoppen", style="Danger.TButton", command=lambda: self.stop_all()).pack(fill="x")

        joy = ttk.Labelframe(left, text="Feinjustierung (manuell bewegen)", padding=10)
        joy.pack(fill="x", pady=10)
        self.speed_var = tk.IntVar(value=self.cfg.get("speed", 1000))
        self.dur_var = tk.IntVar(value=2)
        g = ttk.Frame(joy)
        g.pack()
        mk = lambda txt, ang, r, c: ttk.Button(g, text=txt, width=5, command=lambda: self.move(ang)).grid(row=r, column=c, padx=2, pady=2)
        mk("▲", 90, 0, 1)
        mk("◀", 180, 1, 0)
        ttk.Button(g, text="■", width=5, command=lambda: self.move(0, stop=True)).grid(row=1, column=1)
        mk("▶", 0, 1, 2)
        mk("▼", 270, 2, 1)
        ttk.Label(joy, text="Geschwindigkeit").pack(anchor="w", pady=(8, 0))
        ttk.Scale(joy, from_=100, to=5000, variable=self.speed_var, orient="horizontal").pack(fill="x")
        sp = ttk.Frame(joy)
        sp.pack(fill="x")
        ttk.Label(sp, textvariable=self.speed_var).pack(side="left")
        ttk.Label(sp, text="  Dauer (s):").pack(side="left")
        ttk.Spinbox(sp, from_=1, to=10, textvariable=self.dur_var, width=4).pack(side="left")
        ttk.Label(joy, text="Tastatur: Pfeiltasten, Leertaste = Stopp", foreground=C["muted"]).pack(anchor="w", pady=(6, 0))
        for key, ang in (("<Up>", 90), ("<Down>", 270), ("<Left>", 180), ("<Right>", 0)):
            self.bind(key, lambda e, a=ang: self._key_move(e, a))
        self.bind("<space>", lambda e: self._key_move(e, 0, True))

        foc = ttk.Labelframe(left, text="Fokus", padding=10)
        foc.pack(fill="x")
        fr = ttk.Frame(foc)
        fr.pack()
        for txt, st in (("−100", -100), ("−20", -20), ("+20", 20), ("+100", 100)):
            ttk.Button(fr, text=txt, width=6, command=lambda s=st: self.focus_step(s)).pack(side="left", padx=2)
        self.focus_var = tk.StringVar(value="Position: ?")
        ttk.Label(foc, textvariable=self.focus_var).pack(anchor="w", pady=4)
        ttk.Button(foc, text="Autofokus", command=self.manual_autofocus).pack(fill="x")

        go = ttk.Labelframe(right, text="Ziel anfahren (GoTo)", padding=10)
        go.pack(fill="x")
        ttk.Label(go, text="Katalog:").grid(row=0, column=0, sticky="w")
        self.cat_var = tk.StringVar()
        cb = self._obj_combo(go, self.cat_var, 34, self.pick_catalog)
        cb.grid(row=0, column=1, columnspan=3, sticky="w", padx=6)
        ttk.Label(go, text="Name:").grid(row=1, column=0, sticky="w", pady=4)
        self.tname_var = tk.StringVar()
        ttk.Entry(go, textvariable=self.tname_var, width=36).grid(row=1, column=1, columnspan=3, sticky="w", padx=6)
        ttk.Label(go, text="RA (h):").grid(row=2, column=0, sticky="w")
        self.ra_var = tk.StringVar()
        ttk.Entry(go, textvariable=self.ra_var, width=16).grid(row=2, column=1, sticky="w", padx=6)
        ttk.Label(go, text="Dec (°):").grid(row=2, column=2, sticky="w")
        self.dec_var = tk.StringVar()
        ttk.Entry(go, textvariable=self.dec_var, width=16).grid(row=2, column=3, sticky="w", padx=6)
        ttk.Label(go, text="J2000 (Katalogwerte) · 5.588 · 5h35m17s · 5:35:17  |  -5.39 · -5°23'28\"",
                  foreground=C["muted"]).grid(row=3, column=0, columnspan=4, sticky="w", pady=(2, 6))
        ttk.Label(go, text="LP-Filter und Modus kommen aus dem Tab „Einstellungen“.", foreground=C["muted"]).grid(
            row=4, column=0, columnspan=4, sticky="w")
        b = ttk.Frame(go)
        b.grid(row=5, column=0, columnspan=4, sticky="w", pady=(8, 0))
        ttk.Button(b, text="GoTo + Live-Ansicht", style="Accent.TButton", command=self.do_goto).pack(side="left")
        ttk.Button(b, text="Nur schwenken", command=self.do_slew).pack(side="left", padx=6)
        ttk.Button(b, text="Plate Solve", command=lambda: self.rpc("start_solve")).pack(side="left")

        pos = ttk.Labelframe(right, text="Aktuelle Position", padding=10)
        pos.pack(fill="x", pady=10)
        self.pos_var = tk.StringVar(value="RA –  /  Dec –")
        ttk.Label(pos, textvariable=self.pos_var, font=("Consolas", 12)).pack(side="left")
        ttk.Button(pos, text="Aktualisieren", command=self.do_pos).pack(side="right")

        misc = ttk.Labelframe(right, text="Sonstiges", padding=10)
        misc.pack(fill="x")
        ttk.Button(misc, text="🔔 Ton abspielen", command=lambda: self.rpc("play_sound", {"num": 13})).pack(side="left")
        ttk.Button(misc, text="Herunterfahren", command=self.do_shutdown).pack(side="left", padx=6)

    # ---- Tab: Einstellungen -------------------------------------------------
    def _tab_settings(self, nb):
        f = ttk.Frame(nb, padding=4)
        nb.add(f, text="Einstellungen")
        self.settings_tab_panel = SettingsPanel(f, self, follow_active=True)
        self.settings_tab_panel.pack(fill="x")

        st = ttk.Labelframe(f, text="Stacking (Ziel aus „Befehle an“)", padding=8)
        st.pack(fill="x", padx=8, pady=(4, 6))
        ttk.Button(st, text="▶ Stacking starten", style="Accent.TButton",
                   command=lambda: self.rpc("iscope_start_stack", {"restart": True})).pack(side="left")
        ttk.Button(st, text="Fortsetzen", command=lambda: self.rpc("iscope_start_stack", {"restart": False})).pack(side="left", padx=6)
        ttk.Button(st, text="■ Stacking stoppen", command=lambda: self.rpc("iscope_stop_view", {"stage": "Stack"})).pack(side="left")
        ttk.Button(st, text="⧉ Einstellungen als eigenes Fenster",
                   command=lambda: self.active and self.open_settings_popup(self.active)).pack(side="right")

        ev = ttk.Labelframe(f, text="Live-Ereignisse", padding=8)
        ev.pack(fill="both", expand=True, padx=8)
        self.stack_var = tk.StringVar(value="Gestackte Frames: –")
        ttk.Label(ev, textvariable=self.stack_var, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.ev_txt = tk.Text(ev, height=5, bg=C["textbg"], fg=C["event"], font=("Consolas", 9), relief="flat")
        self.ev_txt.pack(fill="both", expand=True, pady=(4, 0))

    # ---- Tab: Vorschau --------------------------------------------------------
    def _tab_mosaic(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="Mosaik")
        left = ttk.Frame(f)
        left.pack(side="left", fill="y")
        right = ttk.Frame(f)
        right.pack(side="left", fill="both", expand=True, padx=(14, 0))

        tg = ttk.Labelframe(left, text="Ziel (Mittelpunkt)", padding=8)
        tg.pack(fill="x")
        self.mz_cat = tk.StringVar()
        cb = self._obj_combo(tg, self.mz_cat, 30, self._mz_pick)
        cb.grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(tg, text="Name:").grid(row=1, column=0, sticky="w", pady=4)
        self.mz_name = tk.StringVar(value="Mosaik")
        ttk.Entry(tg, textvariable=self.mz_name, width=24).grid(row=1, column=1, columnspan=3, sticky="w", padx=4)
        ttk.Label(tg, text="RA (h):").grid(row=2, column=0, sticky="w")
        self.mz_ra = tk.StringVar()
        ttk.Entry(tg, textvariable=self.mz_ra, width=11).grid(row=2, column=1, padx=4)
        ttk.Label(tg, text="Dec (°):").grid(row=2, column=2, sticky="w")
        self.mz_dec = tk.StringVar()
        ttk.Entry(tg, textvariable=self.mz_dec, width=11).grid(row=2, column=3, padx=4)
        ttk.Button(tg, text="Aus „Steuerung“ übernehmen", command=self._mz_from_control).grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))

        md = ttk.Labelframe(left, text="Mosaik-Art", padding=8)
        md.pack(fill="x", pady=8)
        self.mz_mode = tk.StringVar(value="grid")
        ttk.Radiobutton(md, text="Raster-Mosaik (Panels nacheinander)", value="grid", variable=self.mz_mode,
                        command=self.draw_mosaic).pack(anchor="w")
        ttk.Radiobutton(md, text="Framing-Mosaik (Seestar-intern, ein Stack)", value="frame", variable=self.mz_mode,
                        command=self.draw_mosaic).pack(anchor="w")

        gp = ttk.Labelframe(left, text="Raster", padding=8)
        gp.pack(fill="x")
        def row(parent, r, label, var, values, w=8):
            ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", pady=2)
            c = ttk.Combobox(parent, textvariable=var, values=values, state="readonly", width=w)
            c.grid(row=r, column=1, sticky="w", padx=6)
            c.bind("<<ComboboxSelected>>", lambda e: self.draw_mosaic())
        self.mz_cols, self.mz_rows = tk.StringVar(value="2"), tk.StringVar(value="2")
        self.mz_ov, self.mz_pt = tk.StringVar(value="20 %"), tk.StringVar(value="30 min")
        row(gp, 0, "Spalten (RA):", self.mz_cols, [str(x) for x in range(1, 7)])
        row(gp, 1, "Zeilen (Dec):", self.mz_rows, [str(x) for x in range(1, 7)])
        row(gp, 2, "Überlappung:", self.mz_ov, ["10 %", "15 %", "20 %", "25 %", "30 %", "40 %"])
        row(gp, 3, "Zeit pro Panel:", self.mz_pt, ["5 min", "10 min", "15 min", "20 min", "30 min", "45 min", "60 min", "90 min"])
        self.mz_af = tk.BooleanVar(value=True)
        ttk.Checkbutton(gp, text="Autofokus vor jedem Panel", variable=self.mz_af).grid(row=4, column=0, columnspan=2, sticky="w")
        ttk.Label(gp, text="Nachfokussieren:").grid(row=5, column=0, sticky="w", pady=2)
        self._rf_combo(gp).grid(row=5, column=1, sticky="w", padx=6)

        fp = ttk.Labelframe(left, text="Framing", padding=8)
        fp.pack(fill="x", pady=8)
        self.mz_scale, self.mz_angle = tk.StringVar(value="2,0×"), tk.StringVar(value="0°")
        self.mz_total = tk.StringVar(value="120 min")
        row(fp, 0, "Größe (× Bildfeld):", self.mz_scale, ["1,5×", "2,0×", "2,5×", "3,0×", "3,5×", "4,0×"])
        row(fp, 1, "Drehung:", self.mz_angle, [f"{a}°" for a in range(-90, 91, 15)])
        row(fp, 2, "Gesamtzeit:", self.mz_total, ["30 min", "60 min", "90 min", "120 min", "180 min", "240 min", "360 min"])

        self.mz_lp = tk.StringVar(value="Geräteeinstellung")
        lpf = ttk.Frame(left)
        lpf.pack(fill="x")
        ttk.Label(lpf, text="LP-Filter:").pack(side="left")
        ttk.Combobox(lpf, textvariable=self.mz_lp, values=["Geräteeinstellung", "An", "Aus"], state="readonly",
                     width=18).pack(side="left", padx=6)



        bt = ttk.Frame(right)
        bt.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Button(bt, text="▶ Starten (Ziel aus „Befehle an“)", style="Accent.TButton",
                   command=self.start_mosaic).pack(side="left")
        ttk.Button(bt, text="▶ Auf allen markierten starten", command=lambda: self.start_mosaic(True)).pack(side="left", padx=6)
        ttk.Button(bt, text="■ Mosaik abbrechen (Ziel)", command=self.cancel_mosaic).pack(side="right")
        slp = ttk.Labelframe(right, text="PC / Laptop", padding=(8, 4))
        slp.pack(side="bottom", fill="x", pady=(8, 0))
        self.mz_nosleep = tk.BooleanVar(value=self.cfg.get("mz_nosleep", True))
        ttk.Checkbutton(slp, text="Standby verhindern, solange ein Mosaik läuft", variable=self.mz_nosleep,
                        command=self._mz_nosleep_changed).pack(anchor="w")
        self.mz_sleep_txt = tk.StringVar(value="Nur während eines Mosaiks. Laptop aufgeklappt und am Netzteil lassen.")
        ttk.Label(slp, textvariable=self.mz_sleep_txt, foreground=C["muted"], wraplength=820).pack(anchor="w", pady=(2, 0))
        pv = ttk.Labelframe(right, text="Plan (für das aktive Gerät)", padding=6)
        pv.pack(fill="both", expand=True)
        self.mz_info = tk.StringVar()
        ttk.Label(pv, textvariable=self.mz_info, foreground=C["muted2"]).pack(anchor="w")
        self.mz_canvas = tk.Canvas(pv, bg=C["canvas"], highlightthickness=0, height=300)
        self.mz_canvas.pack(fill="both", expand=True, pady=4)
        self.mz_canvas.bind("<Configure>", lambda e: self.draw_mosaic())
        ttk.Label(pv, text="Jedes Gerät rechnet die Panels mit seinem eigenen Bildfeld. Raster-Panels werden als "
                           "eigene Ziele (Name_R1C1 …) gespeichert und später z. B. in Siril/APP zusammengesetzt.",
                  foreground=C["muted"], wraplength=560).pack(anchor="w")
        for v in (self.mz_ra, self.mz_dec):
            v.trace_add("write", lambda *a: self.draw_mosaic())

    def _tab_plans(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="Zeitpläne")
        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Label(top, text="Plan:").pack(side="left")
        self.pl_name = tk.StringVar(value=tr("Meine Nacht"))
        self.pl_cb = ttk.Combobox(top, textvariable=self.pl_name, width=26, values=sorted(self.cfg.get("plans", {})))
        self.pl_cb.pack(side="left", padx=6)
        self.pl_cb.bind("<<ComboboxSelected>>", lambda e: self.pl_load(announce=True))
        ttk.Button(top, text="Neu", command=self.pl_new).pack(side="left")
        ttk.Button(top, text="📂 Laden …", command=self.pl_open).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="💾 Speichern", command=self.pl_save).pack(side="left", padx=6)
        ttk.Button(top, text="Speichern unter …", command=lambda: self.pl_save(ask=True)).pack(side="left")
        ttk.Button(top, text="Löschen", command=self.pl_delete).pack(side="left", padx=6)
        self.pl_sum = tk.StringVar()
        ttk.Label(top, textvariable=self.pl_sum, foreground=C["muted2"]).pack(side="right")

        mid = ttk.Frame(f)
        mid.pack(fill="both", expand=True, pady=8)
        cols = ("n", "art", "ziel", "dauer", "hoehe", "fokus", "zeit")
        heads = ("#", "Schritt", "Ziel / Details", "Dauer", "Mind.-Höhe", "Fokus", "voraussichtlich")
        widths = (30, 110, 300, 70, 80, 120, 200)
        self.pl_tree = ttk.Treeview(mid, columns=cols, show="headings", height=9, selectmode="browse")
        for c, h, w in zip(cols, heads, widths):
            self.pl_tree.heading(c, text=h)
            self.pl_tree.column(c, width=w, anchor="w" if c in ("ziel", "zeit", "art") else "center")
        self.pl_tree.pack(side="left", fill="both", expand=True)
        self.pl_tree.bind("<Double-1>", lambda e: self.pl_edit())
        side = ttk.Frame(mid)
        side.pack(side="left", fill="y", padx=(8, 0))
        for txt, fn in (("Nach oben", lambda: self.pl_move(-1)), ("Nach unten", lambda: self.pl_move(1)), ("Bearbeiten", self.pl_edit),
                        ("Entfernen", self.pl_remove)):
            ttk.Button(side, text=txt, command=fn, width=11).pack(pady=2)

        add = ttk.Labelframe(f, text="Schritt hinzufügen", padding=8)
        add.pack(fill="x")
        r = ttk.Frame(add)
        r.pack(fill="x")
        ttk.Label(r, text="Dauer:").pack(side="left")
        self.pl_dur = tk.StringVar(value="60 min")
        ttk.Combobox(r, textvariable=self.pl_dur, width=8, values=["15 min", "30 min", "45 min", "60 min", "90 min",
                                                                     "120 min", "180 min", "240 min"]).pack(side="left", padx=4)
        ttk.Label(r, text="Mind.-Höhe:").pack(side="left", padx=(8, 0))
        self.pl_alt = tk.StringVar(value="30°")
        ttk.Combobox(r, textvariable=self.pl_alt, width=6, state="readonly",
                     values=["egal"] + [f"{a}°" for a in range(10, 55, 5)]).pack(side="left", padx=4)
        ttk.Label(r, text="Fokus:").pack(side="left", padx=(8, 0))
        self.pl_af = tk.StringVar(value="automatisch")
        ttk.Combobox(r, textvariable=self.pl_af, width=24, state="readonly",
                     values=list(self.AF_MODES)).pack(side="left", padx=4)
        ttk.Label(r, text="LP-Filter:").pack(side="left", padx=(8, 0))
        self.pl_lp = tk.StringVar(value="Geräteeinstellung")
        ttk.Combobox(r, textvariable=self.pl_lp, width=16, state="readonly",
                     values=["Geräteeinstellung", "An", "Aus"]).pack(side="left", padx=4)
        r = ttk.Frame(add)
        r.pack(fill="x", pady=(6, 0))
        ttk.Button(r, text="＋ Ziel aus „GoTo“", command=self.pl_add_selected).pack(side="left")
        ttk.Button(r, text="＋ Mosaik aus Tab „Mosaik“", command=self.pl_add_mosaic).pack(side="left", padx=6)
        ttk.Button(r, text="＋ Autofokus", command=lambda: self._pl_add({"t": "af", "mode": self.AF_MODES[self.pl_af.get()]})).pack(side="left")
        ttk.Label(r, text="   ＋ Warten bis").pack(side="left")
        self.pl_wait = tk.StringVar(value="22:00")
        ttk.Entry(r, textvariable=self.pl_wait, width=6).pack(side="left", padx=4)
        ttk.Button(r, text="hinzufügen", command=self.pl_add_wait).pack(side="left")

        run = ttk.Labelframe(f, text="Ausführen", padding=8)
        run.pack(fill="x", pady=(8, 0))
        r = ttk.Frame(run)
        r.pack(fill="x")
        ttk.Label(r, text="Start:").pack(side="left")
        self.pl_start = tk.StringVar(value=tr("sofort"))
        ttk.Entry(r, textvariable=self.pl_start, width=8).pack(side="left", padx=4)
        ttk.Label(r, text="(„sofort“ oder Uhrzeit HH:MM)").pack(side="left")
        ttk.Label(r, text="Am Ende:").pack(side="left", padx=(16, 0))
        self.pl_end = tk.StringVar(value=END_ACTIONS.get(self.cfg.get("pl_end", "open"), END_ACTIONS["open"]))
        cb = ttk.Combobox(r, textvariable=self.pl_end, width=30, state="readonly", values=list(END_ACTIONS.values()))
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self.pl_check_end())
        ttk.Label(r, text="Nachfokussieren:").pack(side="left", padx=(16, 0))
        self._rf_combo(r).pack(side="left", padx=4)
        self.pl_endnote = tk.StringVar()
        ttk.Label(run, textvariable=self.pl_endnote, foreground=C["warn"], wraplength=1100).pack(anchor="w", pady=(4, 0))
        r = ttk.Frame(run)
        r.pack(fill="x", pady=(6, 0))
        ttk.Button(r, text="▶ Plan starten (Ziel aus „Befehle an“)", style="Accent.TButton",
                   command=self.pl_run).pack(side="left")
        ttk.Button(r, text="▶ Auf allen markierten starten", command=lambda: self.pl_run(True)).pack(side="left", padx=6)
        ttk.Button(r, text="■ Ablauf abbrechen (Ziel)", command=self.cancel_mosaic).pack(side="right")
        if self.cfg.get("plans"):
            self.pl_name.set(sorted(self.cfg["plans"])[0])
            self.pl_load()
        self.pl_check_end()

    def _tab_focus(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="Fokus & Filter")
        self.fc_head = tk.StringVar(value="Kein Gerät")
        ttk.Label(f, textvariable=self.fc_head, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        cols = ttk.Frame(f)
        cols.pack(fill="both", expand=True, pady=(8, 0))
        for k in range(3):
            cols.columnconfigure(k, weight=1)

        fl = ttk.Labelframe(cols, text="Filter & Zubehör an diesem Gerät", padding=8)
        fl.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.fc_filter = tk.StringVar(value=NO_FILTER)
        r = ttk.Frame(fl)
        r.pack(fill="x")
        ttk.Label(r, text="Marke:").grid(row=0, column=0, sticky="w")
        self.fc_brand = tk.StringVar(value="– kein Filter –")
        self.fc_brand_cb = ttk.Combobox(r, textvariable=self.fc_brand, state="readonly", width=24,
                                        values=["– kein Filter –"] + filter_brands())
        self.fc_brand_cb.grid(row=0, column=1, sticky="w", padx=6, pady=2)
        self.fc_brand_cb.bind("<<ComboboxSelected>>", lambda e: self._fc_brand_changed())
        ttk.Label(r, text="Modell:").grid(row=1, column=0, sticky="w")
        self.fc_model = tk.StringVar()
        self.fc_model_cb = ttk.Combobox(r, textvariable=self.fc_model, state="readonly", width=32)
        self.fc_model_cb.grid(row=1, column=1, sticky="w", padx=6, pady=2)
        self.fc_model_cb.bind("<<ComboboxSelected>>", lambda e: self._fc_model_changed())
        b = ttk.Frame(fl)
        b.pack(fill="x", pady=(4, 0))
        ttk.Button(b, text="＋ Eigener Filter …", command=self.fc_custom_dialog).pack(side="left")
        self.fc_del_btn = ttk.Button(b, text="Eigenen löschen", command=self.fc_custom_delete)
        self.fc_del_btn.pack(side="left", padx=6)
        self.fc_finfo = tk.StringVar()
        ttk.Label(fl, textvariable=self.fc_finfo, wraplength=330, justify="left").pack(anchor="w", pady=(6, 0))
        self.fc_dewcap = tk.BooleanVar(value=False)
        ttk.Checkbutton(fl, text="Taukappe montiert", variable=self.fc_dewcap,
                        command=self.fc_set_dewcap).pack(anchor="w", pady=(10, 0))
        self.fc_accessory = tk.BooleanVar(value=False)
        ttk.Checkbutton(fl, text="Anderes Zubehör vor dem Objektiv", variable=self.fc_accessory,
                        command=self.fc_set_dewcap).pack(anchor="w", pady=(2, 0))
        self.fc_protect = tk.BooleanVar(value=False)
        ttk.Checkbutton(fl, text="Arm-Schutz: Parken / Schließen / Ausschalten sperren", variable=self.fc_protect,
                        command=self.fc_set_protect).pack(anchor="w", pady=(2, 0))
        ttk.Label(fl, text="Mit 2\"-Filterhalter oder Taukappe vor dem Objektiv kann das Seestar den Arm nicht "
                           "schließen – der Motor würde dagegen fahren. Der Schutz blockiert alle Befehle, die den Arm "
                           "schließen, und Zeitpläne enden ohne Parken.",
                  foreground=C["muted"], wraplength=320, justify="left").pack(anchor="w", pady=(4, 0))
        ttk.Separator(fl).pack(fill="x", pady=8)
        ttk.Label(fl, text="Warum kein fester Fokuswert pro Filter?", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        ttk.Label(fl, text="Ein Filter vor dem Objektiv verschiebt den Fokus praktisch nicht. Die Fokusposition hängt "
                           "vom einzelnen Gerät und von der Temperatur ab. Das Problem ist der Seestar-Autofokus: "
                           "Er belichtet kurz und sieht hinter dunklen Filtern zu wenige Sterne. Der App-Autofokus "
                           "belichtet länger, mittelt mehrere Bilder und merkt sich das Ergebnis pro Gerät und Filter.",
                  foreground=C["muted"], wraplength=320, justify="left").pack(anchor="w")

        fo = ttk.Labelframe(cols, text="Fokussieren", padding=8)
        fo.grid(row=0, column=1, sticky="nsew", padx=(0, 8))
        self.fc_pos = tk.StringVar(value="Position: –")
        ttk.Label(fo, textvariable=self.fc_pos, font=("Consolas", 11)).pack(anchor="w")
        r = ttk.Frame(fo)
        r.pack(fill="x", pady=4)
        for txt, st in (("−50", -50), ("−10", -10), ("+10", 10), ("+50", 50)):
            ttk.Button(r, text=txt, width=5, command=lambda st=st: self.fc_nudge(st)).pack(side="left", padx=(0, 4))
        ttk.Button(r, text="Lesen", width=6, command=self.fc_read).pack(side="left")
        ttk.Label(fo, text="Präzisions-Autofokus (App)", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(8, 2))
        g = ttk.Frame(fo)
        g.pack(fill="x")
        self.fc_exp, self.fc_frames = tk.StringVar(), tk.StringVar()
        self.fc_span, self.fc_step = tk.StringVar(value="± 80"), tk.StringVar(value="10")
        for row_, (lab, var, vals) in enumerate((("Belichtung Live-Bild:", self.fc_exp, ["1 s", "2 s", "3 s", "5 s", "8 s"]),
                                                 ("Bilder pro Schritt:", self.fc_frames, ["1", "2", "3", "4", "6", "8"]),
                                                 ("Suchbereich:", self.fc_span, ["± 40", "± 80", "± 150", "± 300"]),
                                                 ("Schrittweite:", self.fc_step, ["5", "10", "20", "40"]))):
            ttk.Label(g, text=lab).grid(row=row_, column=0, sticky="w", pady=1)
            ttk.Combobox(g, textvariable=var, values=vals, state="readonly", width=8).grid(row=row_, column=1, sticky="w", padx=6)
        b = ttk.Frame(fo)
        b.pack(fill="x", pady=6)
        ttk.Button(b, text="▶ Autofokus starten", style="Accent.TButton", command=self.fc_run).pack(side="left")
        ttk.Button(b, text="■ Abbrechen", command=self.fc_cancel).pack(side="left", padx=6)
        ttk.Label(fo, text="Vorher ein Sternfeld anfahren (Sternenmodus). Das Seestar darf nicht stacken.",
                  foreground=C["muted"], wraplength=330, justify="left").pack(anchor="w")
        ttk.Separator(fo).pack(fill="x", pady=8)
        b = ttk.Frame(fo)
        b.pack(fill="x")
        ttk.Button(b, text="Gemerkte Position anfahren", command=self.fc_goto_saved).pack(side="left")
        ttk.Button(b, text="Aktuelle Position merken", command=self.fc_save_current).pack(side="left", padx=6)
        ttk.Button(fo, text="Seestar-Autofokus (ohne Filter) + als Referenz merken",
                   command=self.fc_seestar_af).pack(anchor="w", pady=(6, 0))
        self.fc_status = tk.StringVar()
        ttk.Label(fo, textvariable=self.fc_status, wraplength=330, justify="left").pack(anchor="w", pady=(8, 0))

        vc = ttk.Labelframe(cols, text="Schärfekurve (HFR – kleiner ist schärfer)", padding=8)
        vc.grid(row=0, column=2, sticky="nsew")
        self.fc_canvas = tk.Canvas(vc, width=330, height=220, bg=C["canvas"], highlightthickness=0)
        self.fc_canvas.pack(fill="x")
        ttk.Label(vc, text="Gemerkte Fokuspositionen dieses Geräts", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(8, 2))
        self.fc_tree = ttk.Treeview(vc, columns=("f", "pos", "hfr", "temp", "t"), show="headings", height=6)
        for c, h, w in (("f", "Filter", 140), ("pos", "Position", 60), ("hfr", "HFR", 45), ("temp", "Temp.", 50),
                        ("t", "Datum", 90)):
            self.fc_tree.heading(c, text=h)
            self.fc_tree.column(c, width=w, anchor="w" if c == "f" else "center")
        self.fc_tree.pack(fill="x")
        self.fc_points = []
        self._fc_load_filter_defaults(NO_FILTER)

    def _tab_eq(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="EQ-Modus")
        top = ttk.Frame(f)
        top.pack(fill="x")
        self.eq_head = tk.StringVar(value="Kein Gerät")
        ttk.Label(top, textvariable=self.eq_head, font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Button(top, text="⟳ Aktualisieren", command=self.eq_refresh).pack(side="right")
        ttk.Button(top, text="In Alt-Az-Modus wechseln", command=lambda: self.eq_switch(False)).pack(side="right", padx=6)
        ttk.Button(top, text="In EQ-Modus wechseln", style="Accent.TButton",
                   command=lambda: self.eq_switch(True)).pack(side="right")

        cols = ttk.Frame(f)
        cols.pack(fill="both", expand=True, pady=(8, 0))
        for k in range(3):
            cols.columnconfigure(k, weight=1)

        # ① Nivellieren -------------------------------------------------------
        lv = ttk.Labelframe(cols, text="① Nivellieren & Wedge", padding=8)
        lv.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.lvl_canvas = tk.Canvas(lv, width=230, height=230, bg=C["canvas"], highlightthickness=0)
        self.lvl_canvas.pack()
        self.lvl_txt = tk.StringVar(value="Neigung: –")
        ttk.Label(lv, textvariable=self.lvl_txt, font=("Consolas", 10), justify="left").pack(anchor="w", pady=(6, 0))
        self.lvl_zero_var = tk.StringVar(value="")
        ttk.Label(lv, textvariable=self.lvl_zero_var, foreground=C["muted"]).pack(anchor="w")
        self.lvl_live = tk.BooleanVar(value=False)
        ttk.Checkbutton(lv, text="Live-Messung (jede Sekunde)", variable=self.lvl_live,
                        command=self._eq_poll_toggle).pack(anchor="w", pady=(4, 0))
        ttk.Label(lv, text="Ringe: 0,5° (grün) · 1° (gelb) · 2° (rot). Die Libelle ist sehr fein – leichtes Kippen "
                           "von Hand macht oft nur Zehntelgrad aus.", foreground=C["muted"], wraplength=300,
                  justify="left").pack(anchor="w", pady=(4, 0))
        zb = ttk.Frame(lv)
        zb.pack(anchor="w", pady=(4, 0))
        ttk.Button(zb, text="Nullpunkt setzen", style="Small.TButton", command=self.level_zero_set).pack(side="left")
        ttk.Button(zb, text="Nullpunkt löschen", style="Small.TButton", command=self.level_zero_clear).pack(side="left", padx=6)
        ttk.Separator(lv).pack(fill="x", pady=8)
        self.wedge_txt = tk.StringVar()
        ttk.Label(lv, textvariable=self.wedge_txt, justify="left", wraplength=300).pack(anchor="w")
        ttk.Label(lv, text="Ablauf: 1) Stativ mit Wasserwaage grob waagerecht, ein Bein nach Norden. "
                           "2) Hier bis unter 1° nivellieren. 3) Wedge auf den Wert oben stellen, "
                           "Ein-/Aus-Knopf des Seestar zeigt nach oben. 4) Polausrichtung messen.",
                  foreground=C["muted"], wraplength=300, justify="left").pack(anchor="w", pady=(8, 0))

        # ② Polausrichtung -------------------------------------------------------
        pa = ttk.Labelframe(cols, text="② Polausrichtung (3-Punkt)", padding=8)
        pa.grid(row=0, column=1, sticky="nsew", padx=(0, 8))
        r = ttk.Frame(pa)
        r.pack(fill="x")
        ttk.Label(r, text="Startposition:").pack(side="left")
        self.pa_pos = tk.StringVar(value="3 (Standard, oben)")
        ttk.Combobox(r, textvariable=self.pa_pos, state="readonly", width=20,
                     values=["1 (nah)", "2", "3 (Standard, oben)", "4", "5 (fern)"]).pack(side="left", padx=6)
        ttk.Label(r, text="Bereich:").pack(side="left", padx=(8, 0))
        self.pa_range = tk.StringVar(value="±2°")
        cb = ttk.Combobox(r, textvariable=self.pa_range, state="readonly", width=5, values=["±1°", "±2°", "±5°", "±10°"])
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self.eq_draw())
        self.pa_canvas = tk.Canvas(pa, width=260, height=260, bg=C["canvas"], highlightthickness=0)
        self.pa_canvas.pack(pady=6)
        self.pa_txt = tk.StringVar(value="Noch keine Messung.")
        ttk.Label(pa, textvariable=self.pa_txt, font=("Consolas", 10), justify="left").pack(anchor="w")
        b = ttk.Frame(pa)
        b.pack(fill="x", pady=(6, 0))
        ttk.Button(b, text="▶ Abweichung messen", style="Accent.TButton", command=self.pa_start).pack(side="left")
        ttk.Button(b, text="■ Beenden", command=self.pa_stop).pack(side="left", padx=6)
        self.pa_repeat = tk.BooleanVar(value=True)
        ttk.Checkbutton(pa, text="Nach jeder Messung automatisch neu messen (zum Nachjustieren)",
                        variable=self.pa_repeat).pack(anchor="w", pady=(4, 0))
        ttk.Label(pa, text="Ziel: beide Achsen < 0,5° (grün). Die Seestar-App akzeptiert < 1° (gelb). "
                           "Nach jeder Drehung an Höhe/Azimut die Klemmen festziehen und die nächste Messung abwarten.",
                  foreground=C["muted"], wraplength=300, justify="left").pack(anchor="w", pady=(4, 0))

        # ③ Tests & Checkliste ----------------------------------------------------
        ts = ttk.Labelframe(cols, text="③ Kontrolle & Tests", padding=8)
        ts.grid(row=0, column=2, sticky="nsew")
        self.chk_frame = ttk.Frame(ts)
        self.chk_frame.pack(fill="x")
        ttk.Separator(ts).pack(fill="x", pady=8)
        ttk.Label(ts, text="Nachführ- / Belichtungstest", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(ts, text="Vorher ein Ziel anfahren. Der Test stackt mit der gewählten Belichtung und zählt, "
                           "wie viele Frames das Seestar wegen Sternspuren verwirft.",
                  foreground=C["muted"], wraplength=300, justify="left").pack(anchor="w", pady=(2, 6))
        r = ttk.Frame(ts)
        r.pack(fill="x")
        ttk.Label(r, text="Belichtung:").pack(side="left")
        self.et_exp = tk.StringVar(value="60 s")
        ttk.Combobox(r, textvariable=self.et_exp, state="readonly", width=6,
                     values=["20 s", "30 s", "60 s"]).pack(side="left", padx=4)
        ttk.Label(r, text="Dauer:").pack(side="left", padx=(8, 0))
        self.et_dur = tk.StringVar(value="10 min")
        ttk.Combobox(r, textvariable=self.et_dur, state="readonly", width=7,
                     values=["5 min", "10 min", "15 min", "20 min"]).pack(side="left", padx=4)
        b = ttk.Frame(ts)
        b.pack(fill="x", pady=6)
        ttk.Button(b, text="▶ Test starten", style="Accent.TButton", command=self.et_start).pack(side="left")
        ttk.Button(b, text="■ Abbrechen", command=self.et_stop).pack(side="left", padx=6)
        self.et_txt = tk.StringVar(value="")
        ttk.Label(ts, textvariable=self.et_txt, wraplength=300, justify="left").pack(anchor="w")
        self.after(300, self.eq_draw)

    def _tab_preview(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="Vorschau")
        if not HAVE_IMAGING:
            ttk.Label(f, text="Die Bildvorschau benötigt numpy und Pillow:\n\n    pip install numpy pillow\n\n"
                              "Danach die App neu starten.", font=("Segoe UI", 11), padding=12).pack(anchor="w")
            return
        ttk.Label(f, text="Zeigt das aktive Gerät. Für jedes Gerät gibt es zusätzlich ein eigenes Fenster (Übersicht → Doppelklick).",
                  foreground=C["muted"], padding=(8, 6, 0, 0)).pack(anchor="w")
        self.preview_tab_panel = PreviewPanel(f, self, follow_active=True)
        self.preview_tab_panel.pack(fill="both", expand=True)

    # ---- Tab: Bluetooth ---------------------------------------------------
    def _tab_ble(self, nb):
        f = ttk.Frame(nb, padding=12)
        nb.add(f, text="Bluetooth")
        if not HAVE_BLEAK:
            ttk.Label(f, text="Bluetooth benötigt das Paket 'bleak':\n\n    pip install bleak\n\nDanach die App neu starten.",
                      font=("Segoe UI", 11)).pack(anchor="w")
            return
        info = ("Das Seestar nutzt Bluetooth LE vor allem zum Aufwecken und für die WLAN-Einrichtung. "
                "ZWO hat das BLE-Protokoll nicht veröffentlicht – dieser Tab zeigt dir alle Dienste/Characteristics, "
                "liest und schreibt sie und zeichnet Benachrichtigungen auf. Die eigentliche Teleskopsteuerung läuft über WLAN.")
        ttk.Label(f, text=info, wraplength=950, foreground=C["muted"]).pack(anchor="w")

        top = ttk.Frame(f)
        top.pack(fill="x", pady=8)
        self.ble_only = tk.BooleanVar(value=True)
        ttk.Button(top, text="🔍 Scannen", style="Accent.TButton", command=self.ble_scan).pack(side="left")
        ttk.Checkbutton(top, text="Nur Seestar anzeigen", variable=self.ble_only).pack(side="left", padx=8)
        self.ble_found, self.ble_conn, self.ble_busy = [], None, None
        self.ble_list = tk.Frame(f, bg=C["bg"])
        self.ble_list.pack(fill="x")
        for k, wgt in enumerate((3, 2, 1, 0)):
            self.ble_list.columnconfigure(k, weight=wgt)
        self._ble_list_fill()

        cols = ("service", "char", "props", "desc")
        self.ble_tree = ttk.Treeview(f, columns=cols, show="headings", height=10)
        for c, w, t in zip(cols, (290, 290, 200, 160), ("Service", "Characteristic", "Eigenschaften", "Beschreibung")):
            self.ble_tree.heading(c, text=t)
            self.ble_tree.column(c, width=w)
        self.ble_tree.pack(fill="both", expand=True)

        act = ttk.Frame(f)
        act.pack(fill="x", pady=8)
        ttk.Button(act, text="Lesen", command=self.ble_read).pack(side="left")
        ttk.Button(act, text="Benachrichtigungen an", command=self.ble_notify).pack(side="left", padx=6)
        ttk.Label(act, text="Schreiben:").pack(side="left", padx=(16, 4))
        self.ble_payload = tk.StringVar(value='{"id":1,"method":"get_device_state"}')
        ttk.Entry(act, textvariable=self.ble_payload, width=48).pack(side="left")
        self.ble_hex = tk.BooleanVar(value=False)
        ttk.Checkbutton(act, text="Hex", variable=self.ble_hex).pack(side="left", padx=4)
        ttk.Button(act, text="Senden", command=self.ble_write).pack(side="left")

    # ---- Tab: ASIAIR ---------------------------------------------------------
    def _tab_asiair(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="ASIAIR")
        self.air = AirRig(self.log, self._air_dirty)
        self.air_local = self.air
        self.air.event_hooks.append(lambda p_, o_: self.station.event(p_, o_) if getattr(self, "station", None) else None)
        self.air.event_hooks.append(self._air_ev_preview)
        self.station = None
        self._air_status_txt = ""
        self.air_job = None
        self._air_flag = False
        cfg = self.cfg

        con = ttk.Labelframe(f, text="ASIAIR verbinden", padding=8)
        con.pack(fill="x")
        ttk.Label(con, text="Modell:").grid(row=0, column=0, sticky="w")
        self.air_model = tk.StringVar(value=cfg.get("air_model", "ASI585MC Air"))
        ttk.Combobox(con, textvariable=self.air_model, values=list(AIR_MODELS), state="readonly",
                     width=16).grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(con, text="IP-Adresse:").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.air_host = tk.StringVar(value=cfg.get("air_host", "10.0.0.1"))
        ttk.Entry(con, textvariable=self.air_host, width=16).grid(row=0, column=3, sticky="w", padx=6)
        ttk.Button(con, text="Verbinden", style="Accent.TButton", command=self.air_connect).grid(row=0, column=4, padx=4)
        ttk.Button(con, text="Trennen", command=self.air_disconnect).grid(row=0, column=5, padx=4)
        ttk.Label(con, text="PEM-Schlüssel:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.air_pem = tk.StringVar(value=cfg.get("air_pem", ""))
        ttk.Entry(con, textvariable=self.air_pem, width=52).grid(row=1, column=1, columnspan=3, sticky="we", padx=6, pady=(6, 0))
        ttk.Button(con, text="Durchsuchen …", command=self.air_pick_pem).grid(row=1, column=4, padx=4, pady=(6, 0))
        self.air_sendloc = tk.BooleanVar(value=cfg.get("air_sendloc", True))
        ttk.Checkbutton(con, text="Zeit und Standort beim Verbinden senden", variable=self.air_sendloc).grid(
            row=1, column=5, columnspan=2, sticky="w", padx=4, pady=(6, 0))
        ttk.Label(con, text="Schlüssel aus der ASIAIR-App (nicht der Seestar-Schlüssel) – ohne ihn gehen nur Montierung und Guiding.",
                  foreground=C["muted"], wraplength=1000).grid(row=2, column=0, columnspan=7, sticky="w", pady=(6, 0))
        self.air_conn_var = tk.StringVar(value="Nicht verbunden")
        ttk.Label(con, textvariable=self.air_conn_var, font=("Segoe UI", 10, "bold")).grid(row=0, column=6, padx=10, sticky="w")

        st = ttk.Labelframe(f, text="Status", padding=8)
        st.pack(fill="x", pady=(8, 0))
        self.air_stat = tk.StringVar(value="–")
        left = ttk.Frame(st)
        left.pack(side="left", fill="both", expand=True)
        ttk.Label(left, textvariable=self.air_stat, font=("Consolas", 10), justify="left").pack(anchor="w")
        self.air_run_var = tk.StringVar(value="")
        ttk.Label(left, textvariable=self.air_run_var, foreground=C["ok"], font=("Segoe UI", 10, "bold"),
                  wraplength=650).pack(anchor="w", pady=(4, 0))
        r = ttk.Frame(st)
        r.pack(side="right")
        for k, (txt, fn) in enumerate((
                ("GoTo mit Plate Solve", self.air_goto_sel),
                ("Guiding starten", lambda: self.air_bg(self.air.guide_start)),
                ("Guiding stoppen", lambda: self.air_bg(self.air.guide_stop)),
                ("■ Stopp", self.air_stop_all),
                ("Montierung anmelden", lambda: self.air_bg(self.air_attach)),
                ("Nachführung aus", lambda: self.air_bg(self.air.call, 4400, "scope_set_track_state", [False])),
                ("Parken", lambda: self.air_bg(self.air.call, 4400, "scope_park")),
                ("🖼 Vorschau", self.air_preview_open))):
            ttk.Button(r, text=txt, command=fn).grid(row=k // 4, column=k % 4, sticky="we", padx=3, pady=2)

        pl = ttk.Labelframe(f, text="Aufnahmeplan", padding=8)
        pl.pack(fill="both", expand=True, pady=(8, 0))
        top = ttk.Frame(pl)
        top.pack(fill="x")
        ttk.Label(top, text="Plan:").pack(side="left")
        self.air_plan_name = tk.StringVar(value=tr("Meine Nacht"))
        self.air_plan_cb = ttk.Combobox(top, textvariable=self.air_plan_name, width=24,
                                        values=sorted(cfg.get("air_plans", {})))
        self.air_plan_cb.pack(side="left", padx=6)
        self.air_plan_cb.bind("<<ComboboxSelected>>", lambda e: self.air_plan_load())
        ttk.Button(top, text="💾 Speichern", command=self.air_plan_save).pack(side="left")
        ttk.Button(top, text="Löschen", command=self.air_plan_delete).pack(side="left", padx=6)
        for txt, fn in (("Entfernen", self.air_remove), ("Nach unten", lambda: self.air_move(1)),
                        ("Nach oben", lambda: self.air_move(-1))):
            ttk.Button(top, text=txt, command=fn).pack(side="right", padx=(6, 0))
        add = ttk.Frame(pl)
        add.pack(side="bottom", fill="x")
        mid = ttk.Frame(pl)
        mid.pack(fill="both", expand=True, pady=6)
        cols = ("n", "ziel", "exp", "gain", "count", "filt", "alt", "zeit")
        heads = ("#", "Ziel", "Belichtung", "Gain", "Bilder", "Filter", "Mind.-Höhe", "Meridian")
        self.air_tree = ttk.Treeview(mid, columns=cols, show="headings", height=4, selectmode="browse")
        for c, h, w in zip(cols, heads, (30, 220, 80, 60, 60, 80, 80, 200)):
            self.air_tree.heading(c, text=h)
            self.air_tree.column(c, width=w, anchor="w" if c in ("ziel", "zeit") else "center")
        self.air_tree.pack(side="left", fill="both", expand=True)
        self.air_exp = tk.StringVar(value=str(cfg.get("air_exp", 120)))
        self.air_gain = tk.StringVar(value=str(cfg.get("air_gain", 252)))
        self.air_count = tk.StringVar(value=str(cfg.get("air_count", 60)))
        self.air_filt = tk.StringVar(value="")
        self.air_alt = tk.StringVar(value="30°")
        for lbl, var, w, vals in (("Belichtung (s):", self.air_exp, 6, ["10", "30", "60", "120", "180", "300", "600"]),
                                  ("Gain:", self.air_gain, 6, ["0", "100", "200", "252", "300"]),
                                  ("Bilder:", self.air_count, 6, ["10", "30", "60", "100", "200"]),
                                  ("Filter:", self.air_filt, 22, []),
                                  ("Mind.-Höhe:", self.air_alt, 6, ["egal"] + [f"{a}°" for a in range(10, 55, 5)])):
            ttk.Label(add, text=lbl).pack(side="left", padx=(8, 2))
            cb_ = ttk.Combobox(add, textvariable=var, width=w, values=vals,
                               state="readonly" if var is self.air_filt else "normal")
            cb_.pack(side="left")
            if var is self.air_filt:
                self.air_filt_cb = cb_
        ttk.Button(add, text="Empfehlung", command=self.air_apply_reco).pack(side="left", padx=(6, 0))
        ttk.Button(add, text="＋ Ziel aus „GoTo“", command=self.air_add_sel).pack(side="left", padx=10)

        fl = ttk.Labelframe(f, text="Meridian-Flip und Ablauf", padding=8)
        fl.pack(side="bottom", fill="x", pady=(8, 0), before=pl)       # bleibt immer sichtbar, der Plan schrumpft
        r = ttk.Frame(fl)
        r.pack(fill="x")
        ttk.Label(r, text="Montierung:").pack(side="left")
        self.air_mount = tk.StringVar(value=AIR_MOUNT_MODES.get(cfg.get("air_mount", "eq"), AIR_MOUNT_MODES["eq"]))
        cb = ttk.Combobox(r, textvariable=self.air_mount, state="readonly", width=20, values=list(AIR_MOUNT_MODES.values()))
        cb.pack(side="left", padx=(4, 12))
        cb.bind("<<ComboboxSelected>>", lambda e: self._air_mount_changed())
        self.air_flip = tk.BooleanVar(value=cfg.get("air_flip", True))
        self.air_flip_cb = ttk.Checkbutton(r, text="Meridian-Flip automatisch", variable=self.air_flip)
        self.air_flip_cb.pack(side="left")
        ttk.Label(r, text="Minuten nach dem Meridian:").pack(side="left", padx=(12, 2))
        self.air_flip_min = tk.StringVar(value=str(cfg.get("air_flip_min", 5)))
        ttk.Spinbox(r, from_=0, to=60, increment=1, textvariable=self.air_flip_min, width=4).pack(side="left")
        self.air_flip_wait = tk.BooleanVar(value=cfg.get("air_flip_wait", True))
        ttk.Checkbutton(r, text="laufende Belichtung fertig werden lassen", variable=self.air_flip_wait).pack(side="left", padx=10)
        self.air_flip_af = tk.BooleanVar(value=cfg.get("air_flip_af", False))
        ttk.Checkbutton(r, text="Autofokus nach dem Flip", variable=self.air_flip_af).pack(side="left")
        r = ttk.Frame(fl)
        r.pack(fill="x", pady=(6, 0))
        self.air_guide = tk.BooleanVar(value=cfg.get("air_guide", True))
        ttk.Checkbutton(r, text="Guiding verwenden", variable=self.air_guide).pack(side="left")
        ttk.Label(r, text="Guiding nach dem Flip:").pack(side="left", padx=(12, 2))
        self.air_cal = tk.StringVar(value="neu kalibrieren (sicher)" if cfg.get("air_cal", "new") == "new"
                                    else "Kalibrierung spiegeln (schneller)")
        ttk.Combobox(r, textvariable=self.air_cal, state="readonly", width=30,
                     values=["neu kalibrieren (sicher)", "Kalibrierung spiegeln (schneller)"]).pack(side="left")
        ttk.Label(r, text="Dithering alle").pack(side="left", padx=(12, 2))
        self.air_dither = tk.StringVar(value=str(cfg.get("air_dither", 3)))
        ttk.Spinbox(r, from_=0, to=20, textvariable=self.air_dither, width=4).pack(side="left")
        ttk.Label(r, text="Bilder (0 = wie im Air)").pack(side="left", padx=(2, 0))
        ttk.Label(r, text="Am Ende:").pack(side="left", padx=(12, 2))
        self.air_end = tk.StringVar(value=AIR_END_ACTIONS.get(cfg.get("air_end", "none"), AIR_END_ACTIONS["none"]))
        ttk.Combobox(r, textvariable=self.air_end, state="readonly", width=30,
                     values=list(AIR_END_ACTIONS.values())).pack(side="left")
        r = ttk.Frame(fl)
        r.pack(fill="x", pady=(8, 0))
        ttk.Button(r, text="▶ Plan starten", style="Accent.TButton", command=self.air_run).pack(side="left")
        self.air_daytest = tk.BooleanVar(value=False)                  # bewusst nicht gespeichert
        ttk.Checkbutton(r, text="Tagestest: ohne Plate Solve und Guiding – Objektivdeckel drauf!",
                        variable=self.air_daytest).pack(side="right")
        ttk.Button(r, text="■ Plan abbrechen", command=self.air_cancel).pack(side="left", padx=6)
        ttk.Button(r, text="Meridian-Flip jetzt testen", command=self.air_flip_now).pack(side="left", padx=(20, 0))
        if cfg.get("air_plans"):
            self.air_plan_name.set(sorted(cfg["air_plans"])[0])
        self.air_plan_load(quiet=True)
        self._air_mount_changed(quiet=True)
        self.after(1000, self._air_tick)

    def _air_altaz(self):
        return self.air_mount.get() == AIR_MOUNT_MODES["altaz"]

    def _air_mount_changed(self, quiet=False):
        """Alt-Az: es gibt keinen Meridian-Flip – Haken ausschalten und sperren."""
        if self._air_altaz():
            self.air_flip.set(False)
            self.air_flip_cb.state(["disabled"])
            if not quiet:
                self.log("ASIAIR: Montierung azimutal (Alt-Az) – kein Meridian-Flip nötig, dafür Bildfelddrehung und "
                         "Zenit beachten.", "info")
        else:
            self.air_flip_cb.state(["!disabled"])
            if not quiet:
                self.air_flip.set(True)

    def _air_dirty(self):
        self._air_flag = True

    def _air_status(self, s):
        self._air_status_txt = s
        self.ui(self.air_run_var.set, s)

    def _air_is_remote(self):
        return bool(getattr(self.air, "remote", False))

    def _air_back_local(self):
        if self._air_is_remote():
            self.air.disconnect()
            self.air = self.air_local
            self._air_dirty()

    def _air_tick(self):
        if self._air_flag:
            self._air_flag = False
            try:
                self.air_refresh_ui()
            except Exception:
                pass
        if self.air_job and self.air_job.alive():
            self._air_flag = True
        self.after(1000, self._air_tick)

    def air_bg(self, fn, *a):
        if not self.air.connected:
            messagebox.showinfo(APP_NAME, "Zuerst mit dem ASIAIR verbinden.")
            return
        self.bg(fn, *a)

    def air_refresh_ui(self):
        a = self.air
        self._remote_refresh_ui()
        if a.remote:
            self.air_run_var.set(a.snap.get("status", "") if a.station_ok else "")
            if not a.link.up:
                self.air_conn_var.set("🌐 Fernzugriff: Vermittlungsserver nicht erreichbar")
            elif not a.online:
                self.air_conn_var.set(f"🌐 {a.sname}: Heimstation offline")
            elif not a.snap.get("air"):
                self.air_conn_var.set(f"🌐 {a.sname}: Air an der Heimstation nicht verbunden")
        if not a.connected:
            if not a.remote:
                self.air_conn_var.set("Nicht verbunden")
            self.air_stat.set("–")
            return
        self.air_conn_var.set(f"🌐 {a.model} · {a.sname} (fern)" if a.remote else f"✔ {a.model} · {a.host}")
        s = a.state
        site = self._site()
        lines = []
        if "ra" in s:
            ha = f"   {tr('Stundenwinkel')} {hour_angle(s['ra'], site[1]) * 60:+.0f} min" if site else ""
            lines.append(f"RA {s['ra']:.4f} h   Dec {s['dec']:+.3f}°{ha}")
        if "alt" in s:
            lines.append(f"{tr('Höhe')} {s['alt']:.1f}°   Az {s['az']:.1f}°" +
                         (f"   {tr('Nachführung')}: {tr('an') if s.get('tracking') else tr('aus')}" if "tracking" in s else "") +
                         (f"   {tr('Seite')}: {s['pier']}" if s.get("pier") is not None else ""))
        lines.append(f"Guiding: {s.get('guide') or '–'}" +
                     (f"   {tr('Serie')}: {s.get('seq_frame', 0)}/{s['seq_total']}" if s.get("seq_total") else ""))
        self.air_stat.set("\n".join(lines))

    def air_pick_pem(self):
        p = filedialog.askopenfilename(title="PEM-Schlüssel der ASIAIR-App wählen",
                                       filetypes=[("PEM", "*.pem"), ("*", "*.*")])
        if p:
            self.air_pem.set(p)

    def _air_save_cfg(self):
        c = self.cfg
        c.update(air_model=self.air_model.get(), air_host=self.air_host.get().strip(), air_pem=self.air_pem.get().strip(),
                 air_sendloc=bool(self.air_sendloc.get()), air_flip=bool(self.air_flip.get()),
                 air_flip_wait=bool(self.air_flip_wait.get()), air_flip_af=bool(self.air_flip_af.get()),
                 air_guide=bool(self.air_guide.get()),
                 air_mount="altaz" if self._air_altaz() else "eq",
                 air_cal="mirror" if "spiegeln" in self.air_cal.get() else "new",
                 air_end=next((k for k, v in AIR_END_ACTIONS.items() if v == self.air_end.get()), "none"))
        for k, var in (("air_flip_min", self.air_flip_min), ("air_dither", self.air_dither), ("air_exp", self.air_exp),
                       ("air_gain", self.air_gain), ("air_count", self.air_count)):
            try:
                c[k] = int(float(str(var.get()).replace(",", ".")))
            except ValueError:
                pass
        save_config(c)

    def air_connect(self):
        self._air_back_local()
        host = self.air_host.get().strip()
        if not host:
            messagebox.showerror(APP_NAME, "Bitte die IP-Adresse des ASIAIR eingeben (im eigenen WLAN des Air meist 10.0.0.1).")
            return
        pem = self.air_pem.get().strip()
        if pem and not Path(pem).is_file():
            messagebox.showerror(APP_NAME, "Die PEM-Datei wurde nicht gefunden.")
            return
        self._air_save_cfg()
        self.air.model = self.air_model.get()
        self.air.auto_reconnect = self.cfg.get("air_auto_reconnect", True)
        self.air_conn_var.set("verbinde …")

        def work():
            if not self.air.connect(host, pem):
                self.log("ASIAIR: Verbindung fehlgeschlagen – ist das Air eingeschaltet und der PC in seinem WLAN?", "err")
                self._air_dirty()
                return
            self.log(f"ASIAIR verbunden ({self.air.model}, {host}).", "ok")
            site = self._site()
            if self.air_sendloc.get() and site:
                self.air.send_time_location(*site)
            self.air.refresh()
        self.bg(work)

    def air_disconnect(self):
        if self._air_is_remote():
            self._air_back_local()
            self.log("Fernzugriff getrennt.", "warn")
            return
        if self.air_job and self.air_job.alive():
            if not messagebox.askyesno(APP_NAME, "Ein ASIAIR-Plan läuft. Trotzdem trennen? Der Plan wird dann abgebrochen."):
                return
            self.air_job.stop()
        self.air.disconnect()
        self.log("ASIAIR getrennt.", "warn")

    def air_attach(self):
        if self.air.attach_mount():
            self.log("ASIAIR: Montierung angemeldet.", "ok")
            site = self._site()
            if site:
                time.sleep(5)
                self.air.send_time_location(*site)
        else:
            self.log("ASIAIR: Montierung konnte nicht angemeldet werden.", "err")

    def air_goto_sel(self):
        o = self._obj_sel()
        if not o:
            return
        if not self.air.connected:
            messagebox.showinfo(APP_NAME, "Zuerst mit dem ASIAIR verbinden.")
            return
        site = self._site()
        if site and alt_az(o[4], o[5], *site)[0] < 10:
            if not messagebox.askyesno(APP_NAME, "Das Objekt steht gerade unter 10° Höhe. Trotzdem anfahren?"):
                return
        name = f"{o[0]} {o[1]}".strip()
        day = bool(self.air_daytest.get())
        if site and sun_alt(*site) > -6 and sun_sep(o[4], o[5]) < AIR_SUN_MIN:
            messagebox.showerror(APP_NAME, f"Das Ziel steht weniger als {AIR_SUN_MIN}° von der Sonne entfernt – "
                                           "GoTo aus Sicherheitsgründen gesperrt.")
            return
        if day and not messagebox.askyesno(APP_NAME, "Tagestest: Objektivdeckel drauf? Die Montierung schwenkt ohne Plate Solve."):
            return
        if not day:
            self.log(f"ASIAIR: GoTo {name} mit Plate Solve …", "info")

        def work():
            if self.air.goto(o[4], o[5], solve=not day) and not day:
                self.log(f"ASIAIR: {name} ist zentriert.", "ok")
        self.bg(work)

    def air_stop_all(self):
        if self._air_is_remote():
            self.bg(lambda: self.log(self.air.command("stop_all")[1] or "Stopp gesendet.", "warn"))
            return
        if self.air_job and self.air_job.alive():
            self.air_job.stop()
        if not self.air.connected:
            return

        def work():
            self.air.call(4700, "stop_auto_goto", quiet=True)
            self.air.sequence_stop()
            self.air.call(4400, "scope_abort_slew", quiet=True)
            self.log("ASIAIR: alles gestoppt.", "warn")
        self.bg(work)

    # ---- ASIAIR-Plan ------------------------------------------------------------
    def _air_plan(self):
        return getattr(self, "_air_plan_list", [])

    def air_add_sel(self):
        o = self._obj_sel()
        if not o:
            return
        try:
            exp = float(str(self.air_exp.get()).replace(",", "."))
            gain = int(float(self.air_gain.get()))
            count = int(float(self.air_count.get()))
            fname, filt = self._air_filter_of(self.air_filt.get())
        except ValueError:
            messagebox.showerror(APP_NAME, "Belichtung, Gain, Bilder und Filterplatz bitte als Zahlen eingeben.")
            return
        if exp <= 0 or count <= 0:
            messagebox.showerror(APP_NAME, "Belichtung und Anzahl müssen größer als 0 sein.")
            return
        a = self.air_alt.get().replace("°", "").strip()
        min_alt = None if a in ("egal", tr("egal"), "") else int(float(a))
        self._air_plan_list = self._air_plan() + [{"name": (f"{o[0]} {o[1]}" if o[1] else o[0])[:40], "ra": o[4],
                                                    "dec": o[5], "exp": exp, "gain": gain, "count": count,
                                                    "filter": filt, "fname": fname, "min_alt": min_alt}]
        self.air_fill()

    def air_fill(self):
        self.air_tree.delete(*self.air_tree.get_children())
        site = self._site()
        for k, t in enumerate(self._air_plan(), 1):
            mer = "–"
            if site:
                tt, h = transit(t["ra"], t["dec"], *site)
                mer = f"{datetime.fromtimestamp(tt):%H:%M}  ({tr('Höhe')} {h:.0f}°)"
            self.air_tree.insert("", "end", iid=str(k - 1), values=(
                k, t["name"], f"{fmt_num(t['exp'], 0)} s", t["gain"], t["count"],
                (f"{t['filter']}: " if t.get("filter") else "") + (t.get("fname") or "–"),
                tr("egal") if t.get("min_alt") is None else f"{t['min_alt']}°", mer))

    def air_move(self, delta):
        sel = self.air_tree.selection()
        if not sel:
            return
        i = int(sel[0])
        j = i + delta
        lst = self._air_plan()
        if 0 <= j < len(lst):
            lst[i], lst[j] = lst[j], lst[i]
            self.air_fill()
            self.air_tree.selection_set(str(j))

    def air_remove(self):
        sel = self.air_tree.selection()
        if sel:
            del self._air_plan()[int(sel[0])]
            self.air_fill()

    def air_plan_save(self):
        name = self.air_plan_name.get().strip()
        if not name:
            messagebox.showerror(APP_NAME, "Bitte einen Namen für den Plan eingeben.")
            return
        self.cfg.setdefault("air_plans", {})[name] = [dict(t) for t in self._air_plan()]
        self._air_save_cfg()
        self.air_plan_cb.configure(values=sorted(self.cfg["air_plans"]))
        self.log(f"ASIAIR-Plan „{name}“ gespeichert.", "ok")

    def air_plan_load(self, quiet=False):
        plan = self.cfg.get("air_plans", {}).get(self.air_plan_name.get().strip())
        self._air_plan_list = [dict(t) for t in plan] if plan else []
        self.air_fill()
        if plan and not quiet:
            self.log(f"ASIAIR-Plan „{self.air_plan_name.get().strip()}“ geladen.", "ok")

    def air_plan_delete(self):
        name = self.air_plan_name.get().strip()
        if name in self.cfg.get("air_plans", {}) and messagebox.askyesno(APP_NAME, f"Plan „{name}“ löschen?"):
            del self.cfg["air_plans"][name]
            save_config(self.cfg)
            self.air_plan_cb.configure(values=sorted(self.cfg["air_plans"]))
            self.air_plan_name.set(tr("Meine Nacht"))
            self._air_plan_list = []
            self.air_fill()

    def _air_opts(self):
        self._air_save_cfg()
        c = self.cfg
        return {"flip": c.get("air_flip", True), "flip_min": c.get("air_flip_min", 5),
                "flip_wait": c.get("air_flip_wait", True), "flip_af": c.get("air_flip_af", False),
                "flip_cal": c.get("air_cal", "new"), "guide": c.get("air_guide", True),
                "dither_every": c.get("air_dither", 3), "dither_px": 5, "end": c.get("air_end", "none"),
                "unguided_ok": True, "altaz": c.get("air_mount") == "altaz", "zenith": 85,
                "daytest": bool(self.air_daytest.get()), "link_wait": c.get("air_link_wait", 15),
                "wheel": (c.get("air_filters") or {}).get("mode") == "wheel",
                "af_start": c.get("air_af_each", False), "af_filter": c.get("air_af_filter", True),
                "af_first": c.get("air_af_first", False), "use_offsets": c.get("air_use_offsets", True),
                "af_temp": c.get("air_af_temp", 0),
                "focus_pos": {k: v.get("pos") for k, v in (c.get("air_focus") or {}).items() if isinstance(v, dict)}}

    def air_run(self):
        if not self.air.connected:
            messagebox.showinfo(APP_NAME, "Zuerst mit dem ASIAIR verbinden.")
            return
        if self.air_job and self.air_job.alive():
            messagebox.showinfo(APP_NAME, "Es läuft bereits ein ASIAIR-Plan.")
            return
        if self._air_is_remote() and self.air.snap.get("plan"):
            messagebox.showinfo(APP_NAME, "Es läuft bereits ein ASIAIR-Plan.")
            return
        plan, site = self._air_plan(), self._site()
        if not plan:
            messagebox.showinfo(APP_NAME, "Der Plan ist leer – zuerst Ziele aus „GoTo“ hinzufügen.")
            return
        if not site:
            messagebox.showerror(APP_NAME, "Für den Meridian-Flip wird der Standort gebraucht – bitte im Tab „Standort“ festlegen.")
            return
        o = self._air_opts()
        if o["daytest"]:
            o.update(guide=False, flip_af=False, dither_every=0)
        txt = (("TAGESTEST: Objektivdeckel drauf? Die Montierung schwenkt ohne Plate Solve; Ziele näher als "
                f"{AIR_SUN_MIN}° an der Sonne werden übersprungen.\n\n" if o["daytest"] else "")
               + f"ASIAIR-Plan mit {len(plan)} Zielen starten?\n\n"
               + ("Montierung azimutal (Alt-Az): kein Meridian-Flip nötig." if o["altaz"] else
                  f"Meridian-Flip: automatisch {o['flip_min']} min nach dem Meridian." if o["flip"]
                  else "Meridian-Flip: aus.") + "\n\n"
               + ("Bitte vorher prüfen: Kabel lang genug für eine volle Drehung, nichts im Schwenkbereich." if o["altaz"]
                  else "Bitte vorher prüfen: Kabel lang genug für den Seitenwechsel, nichts im Schwenkbereich."))
        if self._air_is_remote():
            txt = "Der Plan läuft auf der Heimstation – auch wenn deine Verbindung unterwegs abbricht.\n\n" + txt
        if not messagebox.askyesno(APP_NAME, txt, default="no"):
            return
        if self._air_is_remote():
            rplan = [dict(t) for t in plan]

            def send():
                ok, msg = self.air.command("plan_start", plan=rplan, opts=o)
                self.log(msg or ("Plan auf der Heimstation gestartet." if ok else "Start abgelehnt."), "ok" if ok else "err")
            self.bg(send)
            return
        o["af_fn"] = self.air_autofocus_run
        self.air_job = AirPlanJob(self.air, [dict(t) for t in plan], o, site, self.log,
                                  self._air_status)
        self.air_job.start()

    def air_cancel(self):
        if self._air_is_remote():
            if messagebox.askyesno(APP_NAME, "ASIAIR-Plan wirklich abbrechen?"):
                self.bg(lambda: self.log(self.air.command("plan_cancel")[1] or "Abbruch gesendet.", "warn"))
            return
        if self.air_job and self.air_job.alive():
            if messagebox.askyesno(APP_NAME, "ASIAIR-Plan wirklich abbrechen?"):
                self.air_job.stop()

    def air_flip_now(self):
        """Zum Ausprobieren am Tag oder am Anfang der Nacht: führt den Flip-Ablauf sofort für das gewählte
        Ziel aus (ohne Aufnahmeserie davor)."""
        if not self.air.connected:
            messagebox.showinfo(APP_NAME, "Zuerst mit dem ASIAIR verbinden.")
            return
        if self.air_job and self.air_job.alive():
            messagebox.showinfo(APP_NAME, "Es läuft bereits ein ASIAIR-Plan.")
            return
        if self._air_altaz():
            messagebox.showinfo(APP_NAME, "Im Alt-Az-Modus gibt es keinen Meridian-Flip – die Montierung fährt einfach "
                                          "über den Meridian weiter.")
            return
        if self._air_is_remote():
            messagebox.showinfo(APP_NAME, "Den Flip-Test bitte direkt an der Heimstation ausführen und dabei am Teleskop sein.")
            return
        sel = self.air_tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Bitte im Aufnahmeplan ein Ziel auswählen.")
            return
        t = dict(self._air_plan()[int(sel[0])])
        site = self._site()
        if not site:
            messagebox.showerror(APP_NAME, "Für den Meridian-Flip wird der Standort gebraucht – bitte im Tab „Standort“ festlegen.")
            return
        if not messagebox.askyesno(APP_NAME, f"Flip-Ablauf jetzt mit „{t['name']}“ ausführen?\n\n"
                                             "Die Montierung fährt dabei. Kabel und Schwenkbereich prüfen.", default="no"):
            return
        o = self._air_opts()
        o["flip_wait"] = False
        o["af_fn"] = self.air_autofocus_run
        job = AirPlanJob(self.air, [t], o, site, self.log, self._air_status)

        def work():
            ok = job.meridian_flip(t)
            self.ui(self.air_run_var.set, "")
            self.log("ASIAIR: Flip-Test erfolgreich." if ok else "ASIAIR: Flip-Test fehlgeschlagen – siehe Protokoll.",
                     "ok" if ok else "err")
        self.air_job = job
        job.thread = threading.Thread(target=work, daemon=True)
        job.start()

    def _reset_asiair(self):
        self.air_mount.set(AIR_MOUNT_MODES["eq"])
        self._air_mount_changed(quiet=True)
        self.air_flip.set(True)
        self.air_flip_min.set("5")
        self.air_flip_wait.set(True)
        self.air_flip_af.set(False)
        self.air_guide.set(True)
        self.air_cal.set("neu kalibrieren (sicher)")
        self.air_dither.set("3")
        self.air_end.set(AIR_END_ACTIONS["none"])
        self.air_exp.set("120")
        self.air_gain.set("252")
        self.air_count.set("60")
        self.air_filt.set(self._air_filter_choices()[0] if self._air_filter_choices() else "")
        self.air_alt.set("30°")
        self._air_save_cfg()

    # ---- ASIAIR-Ausgabe (nur das, was mit einem ASIAIR nutzbar ist) ------------------
    AIR_EDITION_TABS = ("goto", "weather", "location", "asiair", "airnet", "airfocus")

    def _edition_asiair(self, top):
        """Seestar-Teile ausblenden (nicht löschen – so laufen alle Hintergrundfunktionen fehlerfrei weiter)."""
        self.title(f"{APP_NAME} · {EDITION_SUFFIX['asiair']}")
        top.pack_forget()
        ttk.Button(self.appbar, text="↺ Seite zurücksetzen", style="Small.TButton",
                   command=self.reset_page).pack(side="left", padx=(14, 0))
        for k, key in enumerate(self.TAB_KEYS):
            if key not in self.AIR_EDITION_TABS:
                self.nb.hide(k)
        # GoTo: Seestar-Knöpfe durch ASIAIR-Knöpfe ersetzen, Bildfeld-Spalte (Seestar) ausblenden
        bar = ttk.Frame(self.obj_btnbar.master)
        bar.pack(fill="x", pady=(8, 0), before=self.obj_btnbar)
        ttk.Button(bar, text="▶ ASIAIR: GoTo mit Plate Solve", style="Accent.TButton",
                   command=self.air_goto_sel).pack(side="left")
        ttk.Button(bar, text="＋ in den ASIAIR-Aufnahmeplan", command=self._air_add_from_goto).pack(side="left", padx=6)
        self.obj_btnbar.pack_forget()
        self.obj_tree.configure(displaycolumns=[c for c in self.obj_tree["columns"] if c != "fit"])
        self.obj_tree.bind("<Double-1>", lambda e: "break")
        # Wetter & Tipps
        bar = ttk.Frame(self.rec_btnbar.master)
        bar.pack(fill="x", before=self.rec_btnbar)
        ttk.Button(bar, text="▶ ASIAIR: GoTo mit Plate Solve", style="Accent.TButton",
                   command=lambda: self._rec_air("goto")).pack(side="left")
        ttk.Button(bar, text="＋ in den ASIAIR-Aufnahmeplan", command=lambda: self._rec_air("plan")).pack(side="left", padx=6)
        ttk.Label(bar, text="Wetterdaten: Open-Meteo.com (CC BY 4.0) · Sonne/Mond werden lokal berechnet",
                  foreground=C["dim"]).pack(side="right")
        self.rec_btnbar.pack_forget()
        self.rec_tree.bind("<Double-1>", lambda e: "break")
        if not self.first_run:
            self.after(300, lambda: self.nb.select(self._tab_index("ASIAIR")))

    def _air_add_from_goto(self):
        if self.obj_tree.selection():
            self.air_add_sel()
            self.nb.select(self._tab_index("ASIAIR"))
        else:
            messagebox.showinfo(APP_NAME, "Bitte zuerst ein Objekt auswählen.")

    def _rec_air(self, what):
        r = self._rec_sel()
        if not r:
            return
        oid = r["o"][0]
        if not self.obj_tree.exists(oid):                 # Filter im GoTo-Tab blendet es aus → Filter lockern
            self.obj_q.set("")
            self.obj_type.set("Alle")
            self.obj_named.set(False)
            self.obj_fill()
        if not self.obj_tree.exists(oid):
            messagebox.showinfo(APP_NAME, "Das Objekt ist im GoTo-Tab gerade ausgeblendet – bitte dort die Filter lockern.")
            return
        self.obj_tree.selection_set(oid)
        if what == "goto":
            self.air_goto_sel()
        else:
            self.air_add_sel()
            self.nb.select(self._tab_index("ASIAIR"))

    def _air_plan_from_recs(self, plan, min_alt, txt):
        try:
            exp = float(str(self.air_exp.get()).replace(",", "."))
            gain = int(float(self.air_gain.get()))
        except ValueError:
            exp, gain = 30.0, 252
        if not messagebox.askyesno(APP_NAME, f"Vorschlag für heute Nacht:\n\n{txt}\n\nAls neuen ASIAIR-Aufnahmeplan "
                                             "übernehmen? (Der Plan im Editor wird ersetzt, gespeicherte Pläne bleiben.)"):
            return
        self._air_plan_list = []
        for r, a, b in plan:
            o = r["o"]
            count = max(1, int((b - a - 300) / (exp + 3)))
            fname, slot = self._air_filter_of(self.air_filt.get())
            self._air_plan_list.append({"name": (f"{o[0]} {o[1]}" if o[1] else o[0])[:40], "ra": o[4], "dec": o[5],
                                        "exp": exp, "gain": gain, "count": count, "filter": slot, "fname": fname,
                                        "min_alt": min_alt})
        self.air_plan_name.set(f"Nacht {datetime.fromtimestamp(self.rec_win[0]):%d.%m.%Y}")
        self.air_fill()
        self.nb.select(self._tab_index("ASIAIR"))
        self.log(f"Plan mit {len(plan)} Zielen für heute Nacht erstellt – bitte prüfen und speichern.", "ok")

    # ---- Tab: ASIAIR-Netzwerk (Zuhause und unterwegs) ------------------------------------
    def _tab_airnet(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="ASIAIR-Netzwerk")
        cfg = self.cfg

        a = ttk.Labelframe(f, text="Zuhause · direkt mit dem WLAN des Air (Hotspot)", padding=8)
        a.pack(fill="x")
        ttk.Label(a, text="WLAN-Name des Air:").grid(row=0, column=0, sticky="w")
        self.an_ssid = tk.StringVar(value=cfg.get("air_ssid", ""))
        ttk.Entry(a, textvariable=self.an_ssid, width=24).grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(a, text="Passwort:").grid(row=0, column=2, sticky="w", padx=(10, 0))
        self.an_pass = tk.StringVar(value=secret_unprotect(cfg.get("air_wpass", "")))
        ttk.Entry(a, textvariable=self.an_pass, width=20, show="•").grid(row=0, column=3, sticky="w", padx=6)
        ttk.Button(a, text="PC mit Air-WLAN verbinden", style="Accent.TButton", command=self.an_join).grid(row=0, column=4, padx=6)
        ttk.Label(a, text="Steht in der ASIAIR-App (WLAN-Einstellungen). Das Air hat dann meist die Adresse 10.0.0.1. "
                          "Das Passwort wird nur auf diesem PC verschlüsselt gespeichert.",
                  foreground=C["muted"], wraplength=1100).grid(row=1, column=0, columnspan=6, sticky="w", pady=(6, 0))

        b = ttk.Labelframe(f, text="Zuhause · Air im Heimnetz (Station-Modus)", padding=8)
        b.pack(fill="x", pady=(8, 0))
        ttk.Button(b, text="🔍 Air im Netzwerk suchen", command=self.an_scan).pack(side="left")
        self.an_found = tk.StringVar(value="")
        self.an_found_cb = ttk.Combobox(b, textvariable=self.an_found, width=20, state="readonly", values=[])
        self.an_found_cb.pack(side="left", padx=8)
        ttk.Button(b, text="als Adresse „Zuhause“ übernehmen", command=self.an_take_found).pack(side="left")
        self.an_scan_msg = tk.StringVar(value="")
        ttk.Label(b, textvariable=self.an_scan_msg, foreground=C["muted2"]).pack(side="left", padx=10)

        c = ttk.Labelframe(f, text="Adressen", padding=8)
        c.pack(fill="x", pady=(8, 0))
        self.an_home = tk.StringVar(value=cfg.get("air_host_home", cfg.get("air_host", "10.0.0.1")))
        self.an_away = tk.StringVar(value=cfg.get("air_host_away", ""))
        for r_, (lbl, var, key) in enumerate((("Zuhause:", self.an_home, "home"), ("Unterwegs:", self.an_away, "away"))):
            ttk.Label(c, text=lbl).grid(row=r_, column=0, sticky="w", pady=2)
            ttk.Entry(c, textvariable=var, width=26).grid(row=r_, column=1, sticky="w", padx=6)
            ttk.Button(c, text="verwenden und verbinden", command=lambda k=key: self.an_use(k)).grid(row=r_, column=2, padx=4)
            ttk.Button(c, text="Verbindung testen", command=lambda v=var: self.an_test(v.get())).grid(row=r_, column=3, padx=4)
        self.an_test_msg = tk.StringVar(value="")
        ttk.Label(c, textvariable=self.an_test_msg, foreground=C["muted2"], wraplength=1100,
                  justify="left").grid(row=2, column=0, columnspan=5, sticky="w", pady=(6, 0))
        r = ttk.Frame(c)
        r.grid(row=3, column=0, columnspan=5, sticky="w", pady=(6, 0))
        self.an_auto = tk.BooleanVar(value=cfg.get("air_auto_reconnect", True))
        ttk.Checkbutton(r, text="Bei Abbruch automatisch neu verbinden", variable=self.an_auto,
                        command=self._an_save).pack(side="left")
        ttk.Label(r, text="Plan wartet bei Abbruch bis zu").pack(side="left", padx=(14, 2))
        self.an_wait = tk.StringVar(value=str(cfg.get("air_link_wait", 15)))
        sp = ttk.Spinbox(r, from_=1, to=120, textvariable=self.an_wait, width=4, command=self._an_save)
        sp.pack(side="left")
        sp.bind("<FocusOut>", lambda e: self._an_save())
        ttk.Label(r, text="min").pack(side="left", padx=(2, 0))

        self._remote_frame(f)

    def _an_save(self):
        c = self.cfg
        c["air_ssid"] = self.an_ssid.get().strip()
        c["air_wpass"] = secret_protect(self.an_pass.get())
        c["air_host_home"] = self.an_home.get().strip()
        c["air_host_away"] = self.an_away.get().strip()
        c["air_auto_reconnect"] = bool(self.an_auto.get())
        try:
            c["air_link_wait"] = max(1, min(120, int(float(self.an_wait.get()))))
        except ValueError:
            pass
        self.air.auto_reconnect = c["air_auto_reconnect"]
        save_config(c)

    def an_join(self):
        self._an_save()
        ssid, pw = self.an_ssid.get().strip(), self.an_pass.get()
        self.an_test_msg.set("verbinde …")

        def work():
            ok, msg = join_seestar_wifi(ssid, pw, host="10.0.0.1")
            if ok:
                msg = f"PC ist mit dem WLAN „{ssid}“ verbunden."
            elif "Seestar" in msg:
                msg = f"Mit „{ssid}“ verbunden, aber das Air antwortet nicht unter 10.0.0.1. Passwort richtig?"
            self.log(msg, "ok" if ok else "err")
            self.ui(self.an_test_msg.set, msg)
            if ok:
                self.ui(self.an_home.set, "10.0.0.1")
                self.ui(self.an_use, "home")
        self.bg(work)

    def an_scan(self):
        self.an_scan_msg.set("suche … (ca. 5 s)")

        def work():
            local = SeestarWifi.local_ipv4s()
            found = sorted(SeestarWifi.tcp_sweep(local, port=AIR_PORT_MOUNT))
            # nur Geräte, die auch den Kamera-Port haben – das sind sehr wahrscheinlich ASIAIRs
            found = [h for h in found if tcp_reachable(h, AIR_PORT_MAIN, timeout=1.0)]
            def show():
                self.an_found_cb.configure(values=found)
                if found:
                    self.an_found.set(found[0])
                self.an_scan_msg.set(f"{len(found)} gefunden" if found else
                                     "Kein Air gefunden – ist es im selben Netz und eingeschaltet?")
            self.ui(show)
        self.bg(work)

    def an_take_found(self):
        if self.an_found.get():
            self.an_home.set(self.an_found.get())
            self._an_save()

    def an_use(self, which):
        self._an_save()
        host = (self.an_home if which == "home" else self.an_away).get().strip()
        if not host:
            messagebox.showinfo(APP_NAME, "Bitte zuerst eine Adresse eintragen.")
            return
        self.air_host.set(host)
        self.nb.select(self._tab_index("ASIAIR"))
        if self.air.connected and self.air.host == host:
            return
        if self.air.connected:
            self.air.disconnect()
        self.air_connect()

    def an_test(self, host):
        host = host.strip()
        if not host:
            return
        self.an_test_msg.set("teste …")

        def work():
            res = []
            for port in (AIR_PORT_MOUNT, AIR_PORT_MAIN):
                t0 = time.time()
                ok = tcp_reachable(host, port, timeout=5)
                res.append((port, ok, (time.time() - t0) * 1000))
            if all(ok for _, ok, _ in res):
                ms = max(m for _, _, m in res)
                verdict = ("sehr gut" if ms < 50 else "gut" if ms < 250 else "langsam – geht, aber Befehle brauchen länger")
                msg = f"{host}: beide Ports erreichbar, Antwortzeit ca. {ms:.0f} ms ({verdict})."
            elif any(ok for _, ok, _ in res):
                msg = f"{host}: nur ein Port erreichbar – ist das wirklich ein ASIAIR?"
            else:
                msg = f"{host}: nicht erreichbar. Zuhause: richtiges WLAN? Unterwegs: VPN verbunden?"
            self.log(msg, "ok" if all(ok for _, ok, _ in res) else "warn")
            self.ui(self.an_test_msg.set, msg)
        self.bg(work)

    # ---- Tab: ASIAIR-Filter & Fokus ------------------------------------------------------------
    def _air_filter_choices(self):
        """Auswahlliste für den Plan: fester Filter oder die belegten Filterrad-Plätze."""
        fc = self.cfg.get("air_filters") or {}
        if fc.get("mode") == "wheel":
            out = [f"{k}: {v}" for k, v in sorted(((int(k), v) for k, v in (fc.get("slots") or {}).items()
                                                  if v and v != "– leer –"))]
            return out or [NO_FILTER]
        return [fc.get("fixed") or NO_FILTER]

    def _air_filter_of(self, choice):
        """„3: Optolong L-eXtreme“ -> („Optolong L-eXtreme“, 3); fester Filter -> (Name, 0)."""
        m = re.match(r"^(\d+):\s*(.+)$", choice or "")
        if m:
            return m.group(2), int(m.group(1))
        return (choice or NO_FILTER), 0

    def _air_filters_changed(self):
        vals = self._air_filter_choices()
        try:
            self.air_filt_cb.configure(values=vals)
            if self.air_filt.get() not in vals:
                self.air_filt.set(vals[0])
            self.af_fsel_cb.configure(values=[self._air_filter_of(v)[0] for v in vals])
            if self.af_fsel.get() not in [self._air_filter_of(v)[0] for v in vals]:
                self.af_fsel.set(self._air_filter_of(vals[0])[0])
        except Exception:
            pass
        self._af_info()
        self._af_fill()

    def _air_color(self):
        m = (self.cfg.get("air_model") or "").upper()
        return "MM" not in m

    def air_apply_reco(self):
        fname, _ = self._air_filter_of(self.air_filt.get())
        r = air_filter_reco(fname, self._air_color(), self._air_altaz())
        self.air_exp.set(str(r["exp"]))
        self.log(f"Empfehlung für „{fname}“: {r['exp']} s pro Bild." + (" " + r["notes"][0] if r["notes"] else ""), "info")

    def _tab_airfocus(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="ASIAIR-Filter & Fokus")
        cfg = self.cfg
        fc = cfg.setdefault("air_filters", {"mode": "fixed", "fixed": NO_FILTER, "slots": {}})
        allf = [NO_FILTER] + sorted((k for k in FILTERS if k != NO_FILTER), key=str.lower)
        cols = ttk.Frame(f)
        cols.pack(fill="both", expand=True)
        cols.columnconfigure(0, weight=1)
        cols.columnconfigure(1, weight=1)
        left = ttk.Frame(cols)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        right = ttk.Frame(cols)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        a = ttk.Labelframe(left, text="Filter am Teleskop (2\")", padding=8)
        a.pack(fill="x")
        self.af_mode = tk.StringVar(value=fc.get("mode", "fixed"))
        r = ttk.Frame(a)
        r.pack(fill="x")
        ttk.Radiobutton(r, text="ein fester Filter (ohne Filterrad)", value="fixed", variable=self.af_mode,
                        command=self._af_save_filters).pack(side="left")
        ttk.Radiobutton(r, text="Filterrad", value="wheel", variable=self.af_mode,
                        command=self._af_save_filters).pack(side="left", padx=12)
        r = ttk.Frame(a)
        r.pack(fill="x", pady=(6, 0))
        ttk.Label(r, text="Fester Filter:").pack(side="left")
        self.af_fixed = tk.StringVar(value=fc.get("fixed", NO_FILTER))
        cb = ttk.Combobox(r, textvariable=self.af_fixed, state="readonly", width=44, values=allf, height=25)
        cb.pack(side="left", padx=6)
        cb.bind("<<ComboboxSelected>>", lambda e: self._af_save_filters())
        w = ttk.Frame(a)
        w.pack(fill="x", pady=(6, 0))
        self.af_slots = {}
        for k in range(1, 9):
            ttk.Label(w, text=f"Platz {k}:").grid(row=(k - 1) % 4, column=((k - 1) // 4) * 2, sticky="w", pady=1)
            v = tk.StringVar(value=(fc.get("slots") or {}).get(str(k), "– leer –"))
            cb = ttk.Combobox(w, textvariable=v, state="readonly", width=26, values=["– leer –"] + allf, height=25)
            cb.grid(row=(k - 1) % 4, column=((k - 1) // 4) * 2 + 1, sticky="w", padx=(4, 10), pady=1)
            cb.bind("<<ComboboxSelected>>", lambda e: self._af_save_filters())
            self.af_slots[k] = v
        ttk.Label(a, text=f"{len(FILTERS) - 1} Filter von {len(filter_brands())} Marken · Tipp: leerer Platz → "
                          "Klarglas (Clear), dann bleibt der Fokus gleich.", foreground=C["muted"]).pack(anchor="w", pady=(6, 0))

        b = ttk.Labelframe(left, text="Empfehlung für den Filter", padding=8)
        b.pack(fill="both", expand=True, pady=(8, 0))
        r = ttk.Frame(b)
        r.pack(fill="x")
        ttk.Label(r, text="Filter:").pack(side="left")
        self.af_fsel = tk.StringVar()
        self.af_fsel_cb = ttk.Combobox(r, textvariable=self.af_fsel, state="readonly", width=40)
        self.af_fsel_cb.pack(side="left", padx=6)
        self.af_fsel_cb.bind("<<ComboboxSelected>>", lambda e: (self._af_info(), self._af_fill()))
        self.af_info_var = tk.StringVar(value="")
        ttk.Label(b, textvariable=self.af_info_var, wraplength=600, justify="left").pack(anchor="w", pady=(6, 0))

        c = ttk.Labelframe(right, text="Fokussierer (ZWO EAF)", padding=8)
        c.pack(fill="x")
        r = ttk.Frame(c)
        r.pack(fill="x")
        self.af_pos_var = tk.StringVar(value="Position: –")
        ttk.Label(r, textvariable=self.af_pos_var, font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Button(r, text="⟳", width=3, command=self.af_read).pack(side="left", padx=6)
        for d in (-500, -100, -10, 10, 100, 500):
            ttk.Button(r, text=f"{d:+d}", width=5, command=lambda d=d: self.af_nudge(d)).pack(side="left", padx=1)
        r = ttk.Frame(c)
        r.pack(fill="x", pady=(6, 0))
        ttk.Button(r, text="📌 Position für diesen Filter merken", command=self.af_remember).pack(side="left")
        ttk.Button(r, text="Gemerkte Position anfahren", command=self.af_goto_saved).pack(side="left", padx=6)
        ttk.Button(r, text="Löschen", command=self.af_forget).pack(side="left")
        cols_ = ("f", "pos", "off", "temp", "when")
        self.af_tree = ttk.Treeview(c, columns=cols_, show="headings", height=5, selectmode="browse")
        for col, hd, wd in zip(cols_, ("Filter", "Position", "Versatz", "Temperatur", "gemerkt"), (230, 70, 70, 80, 110)):
            self.af_tree.heading(col, text=hd)
            self.af_tree.column(col, width=wd, anchor="w" if col == "f" else "center")
        self.af_tree.pack(fill="x", pady=(6, 0))
        ttk.Label(c, text="Versatz = Unterschied zum Referenzfilter (der zuerst gemerkte). Beim Filterwechsel im Plan "
                          "fährt das Programm den Versatz an, wenn kein Autofokus läuft.", foreground=C["muted"],
                  wraplength=560, justify="left").pack(anchor="w", pady=(4, 0))

        d = ttk.Labelframe(right, text="Autofokus (eigene Fokuskurve)", padding=8)
        d.pack(fill="both", expand=True, pady=(8, 0))
        r = ttk.Frame(d)
        r.pack(fill="x")
        self.af_exp = tk.StringVar(value=str(cfg.get("air_af_exp", "automatisch")))
        self.af_step = tk.StringVar(value=str(cfg.get("air_af_step", 50)))
        self.af_n = tk.StringVar(value=str(cfg.get("air_af_n", 9)))
        self.af_bl = tk.StringVar(value=str(cfg.get("air_af_bl", 0)))
        for lbl, var, wd, vals in (("Belichtung:", self.af_exp, 11, ["automatisch", "1", "2", "4", "8", "15"]),
                                   ("Schrittweite:", self.af_step, 6, ["10", "20", "30", "50", "80", "100", "200"]),
                                   ("Positionen:", self.af_n, 4, ["7", "9", "11", "13"]),
                                   ("Spiel:", self.af_bl, 5, ["0", "20", "50", "100", "200"])):
            ttk.Label(r, text=lbl).pack(side="left", padx=(0 if lbl == "Belichtung:" else 8, 2))
            ttk.Combobox(r, textvariable=var, width=wd, values=vals).pack(side="left")
        r = ttk.Frame(d)
        r.pack(fill="x", pady=(6, 0))
        ttk.Button(r, text="▶ Autofokus starten", style="Accent.TButton", command=self.af_start).pack(side="left")
        ttk.Button(r, text="■ Abbrechen", command=self.af_cancel).pack(side="left", padx=6)
        self.af_res = tk.StringVar(value="")
        ttk.Label(r, textvariable=self.af_res, foreground=C["ok"]).pack(side="left", padx=8)
        self.af_canvas = tk.Canvas(d, height=150, bg=C["textbg"], highlightthickness=0)
        self.af_canvas.pack(fill="both", expand=True, pady=(6, 0))
        e = ttk.Labelframe(right, text="Im Aufnahmeplan", padding=8)
        e.pack(fill="x", pady=(8, 0))
        self.af_each = tk.BooleanVar(value=cfg.get("air_af_each", False))
        self.af_first = tk.BooleanVar(value=cfg.get("air_af_first", False))
        self.af_filter = tk.BooleanVar(value=cfg.get("air_af_filter", True))
        self.af_offsets = tk.BooleanVar(value=cfg.get("air_use_offsets", True))
        r = ttk.Frame(e)
        r.pack(fill="x")
        for txt, var in (("Autofokus vor dem ersten Ziel", self.af_first), ("vor jedem Ziel", self.af_each),
                         ("nach Filterwechsel", self.af_filter)):
            ttk.Checkbutton(r, text=txt, variable=var, command=self._af_save).pack(side="left", padx=(0, 10))
        r = ttk.Frame(e)
        r.pack(fill="x", pady=(4, 0))
        ttk.Checkbutton(r, text="sonst gemerkten Fokus-Versatz je Filter anfahren", variable=self.af_offsets,
                        command=self._af_save).pack(side="left")
        ttk.Label(r, text="Nachfokussieren ab").pack(side="left", padx=(12, 2))
        self.af_temp = tk.StringVar(value=str(cfg.get("air_af_temp", 0)))
        sp = ttk.Spinbox(r, from_=0, to=10, increment=0.5, textvariable=self.af_temp, width=4, command=self._af_save)
        sp.pack(side="left")
        sp.bind("<FocusOut>", lambda e_: self._af_save())
        ttk.Label(r, text="°C Änderung (0 = aus)").pack(side="left", padx=(2, 0))
        self.af_job = None
        self.after(300, self._air_filters_changed)

    def _af_save_filters(self):
        fc = self.cfg.setdefault("air_filters", {})
        fc["mode"] = self.af_mode.get()
        fc["fixed"] = self.af_fixed.get()
        fc["slots"] = {str(k): v.get() for k, v in self.af_slots.items() if v.get() and v.get() != "– leer –"}
        save_config(self.cfg)
        self._air_filters_changed()

    def _af_save(self):
        c = self.cfg
        c.update(air_af_each=bool(self.af_each.get()), air_af_first=bool(self.af_first.get()),
                 air_af_filter=bool(self.af_filter.get()), air_use_offsets=bool(self.af_offsets.get()),
                 air_af_exp=self.af_exp.get().strip() or "automatisch")
        for key, var, cast in (("air_af_temp", self.af_temp, float), ("air_af_step", self.af_step, int),
                               ("air_af_n", self.af_n, int), ("air_af_bl", self.af_bl, int)):
            try:
                c[key] = cast(float(str(var.get()).replace(",", ".")))
            except ValueError:
                pass
        save_config(c)

    def _af_info(self):
        fname = self.af_fsel.get() or NO_FILTER
        r = air_filter_reco(fname, self._air_color(), self._air_altaz() if hasattr(self, "air_mount") else False)
        f = FILTERS.get(fname, FILTERS[NO_FILTER])
        lines = [f"{f.get('art', '–')}" + (f" · {f['band']}" if f.get("band") else ""),
                 f"Belichtung pro Bild: ca. {r['exp']} s · Autofokus-Belichtung: {r['af_exp']:g} s · "
                 f"Helligkeit {r['light']}/4 (1 = hell, 4 = sehr dunkel)"]
        lines += r["notes"]
        if f.get("quelle") == "T":
            lines.append("Daten aus dem Handel – genaue Werte im Datenblatt prüfen.")
        lines.append("Fokus: Ein Filter verschiebt den Fokus um etwa ein Drittel seiner Glasdicke (2 mm Glas ≈ 0,7 mm). "
                     "Gleich dicke (parfokale) Sätze brauchen kaum Korrektur; Schmalband kann wegen der Farbe der "
                     "Optik etwas anders fokussieren – darum Fokus je Filter einmal messen und merken.")
        self.af_info_var.set("\n".join(lines))

    def _af_fill(self):
        try:
            self.af_tree.delete(*self.af_tree.get_children())
        except Exception:
            return
        fp = self.cfg.get("air_focus") or {}
        ref = next(iter(fp.values()), {}).get("pos") if fp else None
        for name, v in fp.items():
            pos = v.get("pos")
            off = f"{pos - ref:+d}" if ref is not None and pos is not None else "–"
            temp = f"{v['temp']:.1f} °C" if isinstance(v.get("temp"), (int, float)) else "–"
            when = datetime.fromtimestamp(v["t"]).strftime("%d.%m. %H:%M") if v.get("t") else "–"
            self.af_tree.insert("", "end", iid=name, values=(name, pos, off, temp, when))

    def _af_need(self):
        if self._air_is_remote():
            messagebox.showinfo(APP_NAME, "Fokussieren bitte direkt an der Heimstation – über den Fernzugriff geht nur "
                                          "der Autofokus im Plan.")
            return False
        if not self.air.connected:
            messagebox.showinfo(APP_NAME, "Zuerst mit dem ASIAIR verbinden.")
            return False
        return True

    def af_read(self):
        if not self._af_need():
            return

        def work():
            i = self.air.focuser_info()
            txt = (f"Position: {i['position']}" if "position" in i else "Position: – (kein Fokussierer?)") + \
                  (f" · {i['temperature']:.1f} °C" if isinstance(i.get("temperature"), (int, float)) else "")
            self.ui(self.af_pos_var.set, txt)
        self.bg(work)

    def af_nudge(self, d):
        if not self._af_need():
            return

        def work():
            p_ = self.air.focuser_pos()
            if p_ is not None:
                self.air.focuser_move(max(0, p_ + d))
            self.af_read()
        self.bg(work)

    def af_remember(self):
        if not self._af_need():
            return
        fname = self.af_fsel.get() or NO_FILTER

        def work():
            i = self.air.focuser_info()
            if "position" not in i:
                self.log("Kein Fokussierer gefunden.", "err")
                return
            self.cfg.setdefault("air_focus", {})[fname] = {"pos": int(i["position"]), "temp": i.get("temperature"),
                                                          "t": time.time()}
            save_config(self.cfg)
            self.log(f"Fokusposition {i['position']} für „{fname}“ gemerkt.", "ok")
            self.ui(self._af_fill)
        self.bg(work)

    def af_goto_saved(self):
        if not self._af_need():
            return
        fname = self.af_fsel.get() or NO_FILTER
        v = (self.cfg.get("air_focus") or {}).get(fname)
        if not v:
            messagebox.showinfo(APP_NAME, "Für diesen Filter ist noch keine Fokusposition gemerkt.")
            return
        bl = int(self.cfg.get("air_af_bl", 0) or 0)

        def work():
            if bl:
                self.air.focuser_move(v["pos"] - bl)
            self.air.focuser_move(v["pos"])
            self.af_read()
        self.bg(work)

    def af_forget(self):
        sel = self.af_tree.selection()
        if sel and messagebox.askyesno(APP_NAME, f"Gemerkte Fokusposition für „{sel[0]}“ löschen?"):
            (self.cfg.get("air_focus") or {}).pop(sel[0], None)
            save_config(self.cfg)
            self._af_fill()

    def _af_draw(self, points, best=None):
        cv = self.af_canvas
        cv.delete("all")
        pts = [(p_, h) for p_, h in points if h]
        if len(pts) < 2:
            return
        W, H = max(200, cv.winfo_width()), max(100, cv.winfo_height())
        xs, ys = [p_ for p_, _ in pts], [h for _, h in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        sx = lambda x: 30 + (x - x0) / max(1, x1 - x0) * (W - 50)
        sy = lambda y: H - 20 - (y - y0) / max(1e-6, y1 - y0) * (H - 40)
        cv.create_line(30, H - 20, W - 10, H - 20, fill=C["muted"])
        for p_, h in pts:
            cv.create_oval(sx(p_) - 4, sy(h) - 4, sx(p_) + 4, sy(h) + 4, fill=C["accent"] if "accent" in C else "#4aa3ff", outline="")
        if best is not None:
            cv.create_line(sx(best), 10, sx(best), H - 20, fill=C["ok"], dash=(4, 3))
            cv.create_text(sx(best), 10, text=str(best), fill=C["ok"], anchor="n")
        cv.create_text(32, 4, text="HFR", fill=C["muted"], anchor="nw")

    def _af_params(self, fname):
        self._af_save()
        r = air_filter_reco(fname, self._air_color(), False)
        e = str(self.cfg.get("air_af_exp", "automatisch"))
        try:
            exp = float(e.replace(",", "."))
        except ValueError:
            exp = r["af_exp"]
        try:
            gain = int(float(self.air_gain.get()))
        except ValueError:
            gain = 200
        return exp, gain, int(self.cfg.get("air_af_step", 50)), int(self.cfg.get("air_af_n", 9)), int(self.cfg.get("air_af_bl", 0))

    def air_autofocus_run(self, fname, stop=None):
        """Autofokus (auch aus dem Plan). Ergebnis wird als Fokusposition für den Filter gemerkt."""
        if self._air_is_remote() or not self.air_local.connected:
            return False
        fname = fname or self._air_filter_of(self._air_filter_choices()[0])[0]
        exp, gain, step, n, bl = self._af_params(fname)
        pts = []

        def on_point(p_, h, nst):
            pts.append((p_, h))
            self.ui(self._af_draw, list(pts))
        job = AirAutofocus(self, self.air_local, exp, gain, step, n, bl, on_point=on_point, stop=stop)
        best = job.run()
        if best is not None:
            temp = self.air_local.focuser_info().get("temperature")
            self.cfg.setdefault("air_focus", {})[fname] = {"pos": best, "temp": temp, "t": time.time()}
            save_config(self.cfg)
            self.ui(self._af_draw, list(pts), best)
            self.ui(self.af_res.set, f"{fname}: {best}")
            self.ui(self._af_fill)
        return best is not None

    def air_img_raw(self):
        a = self.air_local
        if not a.connected:
            return None
        if not hasattr(self, "air_img"):
            self.air_img = AirImager(self.log)
        if self.air_img.host != a.host or not self.air_img.connected:
            if not self.air_img.connect(a.host):
                return None
        return self.air_img.get()

    def af_start(self):
        if not self._af_need():
            return
        if self.air_job and self.air_job.alive():
            messagebox.showinfo(APP_NAME, "Während ein Plan läuft, fokussiert der Plan selbst (siehe „Im Aufnahmeplan“).")
            return
        if self.af_job:
            return
        fname = self.af_fsel.get() or NO_FILTER
        self.af_stop_flag = False
        self.af_res.set("läuft …")

        def work():
            try:
                fc = self.cfg.get("air_filters") or {}
                if fc.get("mode") == "wheel":
                    slot = next((int(k) for k, v in (fc.get("slots") or {}).items() if v == fname), 0)
                    if slot:
                        self.air.wheel_move(slot)
                ok = self.air_autofocus_run(fname, lambda: self.af_stop_flag)
                if not ok:
                    self.ui(self.af_res.set, "fehlgeschlagen – siehe Protokoll")
            finally:
                self.af_job = None
                self.af_read()
        self.af_job = True
        self.bg(work)

    def af_cancel(self):
        self.af_stop_flag = True

    def _reset_airfocus(self):
        self.af_exp.set("automatisch")
        self.af_step.set("50")
        self.af_n.set("9")
        self.af_bl.set("0")
        for v in (self.af_each, self.af_first):
            v.set(False)
        self.af_filter.set(True)
        self.af_offsets.set(True)
        self.af_temp.set("0")
        self._af_save()

    # ---- ASIAIR: Vorschau / Live-Bild ---------------------------------------------------
    def air_get_rgb(self, max_age=0.0):
        """Aktuelles Bild vom lokalen Air holen (oder das gemerkte, wenn jünger als max_age s). -> (rgb, info) oder None."""
        last = getattr(self, "air_last", None)
        if last and max_age and time.time() - last[2] < max_age:
            return last[0], last[1]
        a = self.air_local
        if not a.connected:
            return None
        if not hasattr(self, "air_img"):
            self.air_img = AirImager(self.log)
        if self.air_img.host != a.host or not self.air_img.connected:
            if not self.air_img.connect(a.host):
                return None
        got = self.air_img.get()
        if not got:
            return None
        hdr, payload = got
        bayer = self.cfg.get("air_bayer", "automatisch")
        try:
            rgb = air_decode(hdr, payload, bayer)
        except Exception as e:
            self.log(f"ASIAIR: Bild konnte nicht gelesen werden ({e}).", "warn")
            return None
        info = f"{hdr['width']}×{hdr['height']} · {datetime.now():%H:%M:%S}"
        self.air_last = (rgb, info, time.time())
        return rgb, info

    def remote_image(self, obj):
        """Heimstation: Bild für ein Ferngerät als verkleinertes JPEG (base64)."""
        got = self.air_get_rgb(max_age=float(obj.get("max_age", 8)))
        if not got:
            return None
        rgb, info = got
        try:
            st = float(obj.get("stretch", 0.2))
        except (TypeError, ValueError):
            st = 0.2
        im = Image.fromarray(stretch8(rgb, (st, False, False)))
        mx = int(obj.get("max", 1200))
        im.thumbnail((mx, mx))
        bio = io.BytesIO()
        im.save(bio, "JPEG", quality=75)
        return base64.b64encode(bio.getvalue()).decode(), info

    def air_preview_open(self):
        if not HAVE_IMAGING:
            messagebox.showerror(APP_NAME, "Für die Vorschau fehlen die Pakete numpy und pillow (pip install numpy pillow).")
            return
        pv = getattr(self, "airpv", None)
        if pv and pv["win"].winfo_exists():
            pv["win"].deiconify()
            pv["win"].lift()
            return
        win = self.make_window("ASIAIR – Vorschau", key="airpreview", size="980x700", minsize=(560, 420))
        top = ttk.Frame(win, padding=(10, 8))
        top.pack(fill="x")
        pv = {"win": win, "busy": False, "live": False, "img": None, "rgb": None, "photo": None}
        self.airpv = pv
        ttk.Label(top, text="Farbmuster:").pack(side="left")
        pv["bayer"] = tk.StringVar(value=self.cfg.get("air_bayer", "automatisch"))
        cb = ttk.Combobox(top, textvariable=pv["bayer"], state="readonly", width=16, values=list(AIR_BAYERS))
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self._airpv_bayer())
        ttk.Label(top, text="Stretch:").pack(side="left", padx=(10, 2))
        pv["stretch"] = tk.DoubleVar(value=float(self.cfg.get("air_stretch", 0.2)))
        sc = ttk.Scale(top, from_=0.05, to=0.5, variable=pv["stretch"], length=140,
                       command=lambda e: self._airpv_render())
        sc.pack(side="left")
        pv["auto"] = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="nach jedem Bild aktualisieren", variable=pv["auto"]).pack(side="left", padx=10)
        ttk.Button(top, text="⟳ Jetzt holen", command=self.air_preview_fetch).pack(side="left")
        ttk.Button(top, text="PNG speichern", command=self._airpv_save).pack(side="right")
        live = ttk.Frame(win, padding=(10, 0))
        live.pack(fill="x")
        ttk.Label(live, text="Live zum Ausrichten/Fokussieren – Belichtung (s):").pack(side="left")
        pv["exp"] = tk.StringVar(value=str(self.cfg.get("air_live_exp", 2)))
        ttk.Combobox(live, textvariable=pv["exp"], width=6, values=["0.5", "1", "2", "3", "5", "10"]).pack(side="left", padx=4)
        pv["live_btn"] = tk.StringVar(value="▶ Live starten")
        ttk.Button(live, textvariable=pv["live_btn"], command=self._airpv_live_toggle).pack(side="left", padx=6)
        ttk.Label(live, text="(nicht während eines Plans)", foreground=C["muted"]).pack(side="left")
        pv["info"] = tk.StringVar(value="Noch kein Bild – „Jetzt holen“ oder Live starten.")
        ttk.Label(win, textvariable=pv["info"], foreground=C["muted2"], padding=(10, 4)).pack(anchor="w")
        pv["label"] = tk.Label(win, bg="#000000")
        pv["label"].pack(fill="both", expand=True, padx=10, pady=(0, 10))
        pv["label"].bind("<Configure>", lambda e: self._airpv_render())

        def close():
            pv["live"] = False
            self.cfg["air_stretch"] = round(float(pv["stretch"].get()), 3)
            save_config(self.cfg)
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", close)
        if self.air.connected:
            self.air_preview_fetch()

    def _airpv_bayer(self):
        self.cfg["air_bayer"] = self.airpv["bayer"].get()
        save_config(self.cfg)
        self.air_last = None
        self.air_preview_fetch()

    def _air_ev_preview(self, port, obj):
        """Ereignis-Haken: nach jedem fertigen Bild der Serie die Vorschau nachladen."""
        pv = getattr(self, "airpv", None)
        if pv and obj.get("Event") == "Sequence" and obj.get("state") == "frame_complete":
            self.ui(lambda: pv["win"].winfo_exists() and pv["auto"].get() and not pv["live"] and self.air_preview_fetch())

    def air_preview_fetch(self):
        pv = getattr(self, "airpv", None)
        if not pv or not pv["win"].winfo_exists() or pv["busy"]:
            return
        if not self.air.connected:
            pv["info"].set("Nicht verbunden")
            return
        pv["busy"] = True
        pv["info"].set("hole Bild …")
        remote = self._air_is_remote()
        stretch = float(pv["stretch"].get())

        def work():
            try:
                if remote:
                    r = self.air.fetch_image(stretch)
                    if r:
                        jpg, info = r
                        im = Image.open(io.BytesIO(jpg)).convert("RGB")
                        self.ui(self._airpv_show, None, im, f"{info} · über Fernzugriff (verkleinert)")
                    else:
                        self.ui(pv["info"].set, "Kein Bild vorhanden – läuft gerade eine Aufnahme?")
                else:
                    got = self.air_get_rgb()
                    if got:
                        self.ui(self._airpv_show, got[0], None, got[1])
                    else:
                        self.ui(pv["info"].set, "Kein Bild vorhanden – läuft gerade eine Aufnahme?")
            finally:
                pv["busy"] = False
        self.bg(work)

    def _airpv_show(self, rgb, im, info):
        pv = getattr(self, "airpv", None)
        if not pv or not pv["win"].winfo_exists():
            return
        pv["rgb"], pv["img"] = rgb, im
        pv["info"].set(info)
        self._airpv_render()

    def _airpv_render(self):
        pv = getattr(self, "airpv", None)
        if not pv or not pv["win"].winfo_exists():
            return
        if pv["rgb"] is not None:
            im = Image.fromarray(stretch8(pv["rgb"], (float(pv["stretch"].get()), False, False)))
        elif pv["img"] is not None:
            im = pv["img"].copy()
        else:
            return
        lw, lh = max(100, pv["label"].winfo_width()), max(100, pv["label"].winfo_height())
        im.thumbnail((lw, lh))
        pv["photo"] = ImageTk.PhotoImage(im)
        pv["label"].configure(image=pv["photo"])
        pv["shown"] = im

    def _airpv_save(self):
        pv = getattr(self, "airpv", None)
        if not pv or (pv["rgb"] is None and pv["img"] is None):
            messagebox.showinfo(APP_NAME, "Noch kein Bild vorhanden.")
            return
        p = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG", "*.png")],
                                         initialfile=f"asiair_{datetime.now():%Y%m%d_%H%M%S}.png")
        if not p:
            return
        im = Image.fromarray(stretch8(pv["rgb"], (float(pv["stretch"].get()), False, False))) if pv["rgb"] is not None else pv["img"]
        im.save(p)
        self.log(f"Vorschau gespeichert: {Path(p).name}", "ok")

    def _airpv_live_toggle(self):
        pv = self.airpv
        if pv["live"]:
            pv["live"] = False
            pv["live_btn"].set("▶ Live starten")
            return
        if self._air_is_remote():
            messagebox.showinfo(APP_NAME, "Live zum Ausrichten geht nur direkt an der Heimstation. Über den Fernzugriff "
                                          "gibt es das jeweils letzte Bild der Aufnahme.")
            return
        if not self.air.connected:
            messagebox.showinfo(APP_NAME, "Zuerst mit dem ASIAIR verbinden.")
            return
        if self.air_job and self.air_job.alive():
            messagebox.showinfo(APP_NAME, "Während ein Plan läuft, gibt es kein Live-Bild – die Vorschau zeigt dann "
                                          "automatisch jedes neue Bild der Serie.")
            return
        try:
            exp = max(0.001, float(str(pv["exp"].get()).replace(",", ".")))
            gain = int(float(self.air_gain.get()))
        except ValueError:
            messagebox.showerror(APP_NAME, "Belichtung bitte als Zahl eingeben.")
            return
        self.cfg["air_live_exp"] = exp
        pv["live"] = True
        pv["live_btn"].set("■ Live stoppen")
        a = self.air

        def loop():
            a.call(4700, "stop_exposure")
            time.sleep(1)
            a.call(4700, "set_page", ["preview"])
            a.call(4700, "set_control_value", ["Exposure", int(exp * 1_000_000)])
            a.call(4700, "set_control_value", ["Gain", gain])
            n = 0
            while pv["live"] and a.connected and pv["win"].winfo_exists():
                w = a.waiter(lambda o: o.get("Event") == "Exposure" and o.get("state") in ("complete", "fail"))
                a.call(4700, "start_exposure", quiet=True)
                a.wait(w, exp + 20, stop=lambda: not pv["live"])
                if not pv["live"]:
                    break
                got = self.air_get_rgb()
                if got:
                    n += 1
                    self.ui(self._airpv_show, got[0], None, f"Live #{n} · {exp:g} s · {got[1]}")
            a.call(4700, "stop_exposure")
            pv["live"] = False
            self.ui(pv["live_btn"].set, "▶ Live starten")
        self.bg(loop)

    def remote_command(self, t, obj):
        """Befehl eines Ferngeräts an der Heimstation ausführen (Oberflächen-Thread). -> (ok, Meldung)"""
        a = self.air_local
        if t == "plan_start":
            if self.air_job and self.air_job.alive():
                return False, "Es läuft bereits ein ASIAIR-Plan."
            if not a.connected:
                return False, "Heimstation ist nicht mit dem ASIAIR verbunden"
            site = self._site()
            plan = [x for x in obj.get("plan", []) if isinstance(x, dict) and {"ra", "dec", "exp", "count", "name"} <= set(x)]
            if not plan or not site:
                return False, "Plan leer oder Standort fehlt an der Heimstation."
            o = dict(self._air_opts())
            o.update({k: v for k, v in (obj.get("opts") or {}).items() if k in o})
            o["af_fn"] = self.air_autofocus_run
            self.air_job = AirPlanJob(a, plan, o, site, self.log, self._air_status)
            self.air_job.start()
            self.log(f"Fernzugriff: Plan mit {len(plan)} Zielen von unterwegs gestartet.", "ok")
            return True, "Plan auf der Heimstation gestartet."
        if t == "plan_cancel":
            if self.air_job and self.air_job.alive():
                self.air_job.stop()
                self.log("Fernzugriff: Plan von unterwegs abgebrochen.", "warn")
                return True, "Abbruch gesendet."
            return False, "Kein Plan aktiv."
        if t == "stop_all":
            if self.air_job and self.air_job.alive():
                self.air_job.stop()

            def work():
                a.call(4700, "stop_auto_goto", quiet=True)
                a.sequence_stop()
                a.call(4400, "scope_abort_slew", quiet=True)
            self.bg(work)
            self.log("Fernzugriff: Stopp von unterwegs.", "warn")
            return True, "Stopp gesendet."
        return False, "unbekannter Befehl"

    # ---- Fernzugriff übers Internet ------------------------------------------------------
    def _remote_frame(self, f):
        cfg = self.cfg
        d = ttk.Labelframe(f, text="Fernzugriff übers Internet – ohne VPN, ohne Portfreigabe, ohne Browser", padding=8)
        d.pack(fill="both", expand=True, pady=(8, 0))
        cols = ttk.Frame(d)
        cols.pack(fill="x")
        cols.columnconfigure(0, weight=1)
        cols.columnconfigure(1, weight=1)
        h = ttk.Labelframe(cols, text="Dieser PC steht beim Teleskop (Heimstation)", padding=8)
        h.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        st = cfg.get("air_station") or {}
        self.rs_on = tk.BooleanVar(value=bool(st.get("on")))
        ttk.Checkbutton(h, text="Fernzugriff auf dieses ASIAIR erlauben", variable=self.rs_on,
                        command=self.station_toggle).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(h, text="Name:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.rs_name = tk.StringVar(value=st.get("name", "Sternwarte"))
        ttk.Entry(h, textvariable=self.rs_name, width=18).grid(row=1, column=1, sticky="w", padx=4, pady=(6, 0))
        ttk.Label(h, text="Rechte:").grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.rs_perm = tk.StringVar(value=REMOTE_PERMS.get(st.get("perm", "full"), REMOTE_PERMS["full"]))
        ttk.Combobox(h, textvariable=self.rs_perm, state="readonly", width=22,
                     values=list(REMOTE_PERMS.values())).grid(row=2, column=1, sticky="w", padx=4, pady=(4, 0))
        r = ttk.Frame(h)
        r.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Button(r, text="Kopplungscode anzeigen", command=self.station_show_code).pack(side="left")
        ttk.Button(r, text="Neuen Code erzeugen", command=self.station_new_code).pack(side="left", padx=6)
        self.rs_msg = tk.StringVar(value="")
        ttk.Label(h, textvariable=self.rs_msg, foreground=C["muted2"], wraplength=520).grid(row=4, column=0, columnspan=3, sticky="w", pady=(4, 0))

        u = ttk.Labelframe(cols, text="Von unterwegs verbinden (Ferngerät)", padding=8)
        u.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        ttk.Label(u, text="Gerät:").grid(row=0, column=0, sticky="w")
        self.rr_sel = tk.StringVar()
        self.rr_cb = ttk.Combobox(u, textvariable=self.rr_sel, state="readonly", width=26)
        self.rr_cb.grid(row=0, column=1, sticky="w", padx=4)
        r = ttk.Frame(u)
        r.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Button(r, text="🌐 Verbinden (fern)", style="Accent.TButton", command=self.remote_connect).pack(side="left")
        ttk.Button(r, text="Trennen", command=self.air_disconnect).pack(side="left", padx=6)
        ttk.Button(r, text="Gerät hinzufügen …", command=self.remote_add).pack(side="left")
        ttk.Button(r, text="Entfernen", command=self.remote_del).pack(side="left", padx=6)
        self.rr_msg = tk.StringVar(value="")
        ttk.Label(u, textvariable=self.rr_msg, foreground=C["muted2"], wraplength=520).grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self._remote_fill()

        b = ttk.Frame(d)
        b.pack(fill="x", pady=(8, 0))
        br = dict(REMOTE_BROKER_DEFAULT, **{k: v for k, v in (cfg.get("air_broker") or {}).items() if k != "pw"})
        ttk.Label(b, text="Vermittlungsserver (MQTT):").pack(side="left")
        self.rb_host = tk.StringVar(value=br["host"])
        ttk.Entry(b, textvariable=self.rb_host, width=24).pack(side="left", padx=4)
        ttk.Label(b, text="Port:").pack(side="left")
        self.rb_port = tk.StringVar(value=str(br["port"]))
        ttk.Entry(b, textvariable=self.rb_port, width=6).pack(side="left", padx=4)
        self.rb_tls = tk.BooleanVar(value=bool(br["tls"]))
        ttk.Checkbutton(b, text="TLS", variable=self.rb_tls).pack(side="left", padx=4)
        ttk.Label(b, text="Benutzer:").pack(side="left", padx=(8, 0))
        self.rb_user = tk.StringVar(value=br.get("user", ""))
        ttk.Entry(b, textvariable=self.rb_user, width=14).pack(side="left", padx=4)
        ttk.Label(b, text="Passwort:").pack(side="left")
        self.rb_pw = tk.StringVar(value=secret_unprotect((cfg.get("air_broker") or {}).get("pw", "")))
        ttk.Entry(b, textvariable=self.rb_pw, width=14, show="•").pack(side="left", padx=4)
        ttk.Button(b, text="Speichern", command=self._broker_save).pack(side="left", padx=4)
        ttk.Button(b, text="ℹ So funktioniert's", command=self._remote_info).pack(side="right")
        ttk.Button(b, text="ℹ Andere Wege", command=self._remote_other_ways).pack(side="right", padx=6)
        if not HAVE_MQTT:
            ttk.Label(d, text="Paket fehlt: pip install paho-mqtt (start.bat installiert es beim nächsten Start)",
                      foreground=C["err"]).pack(anchor="w", pady=(4, 0))
        if st.get("on"):
            self.after(2500, lambda: self.station_toggle(quiet=True))

    def _remote_info(self):
        messagebox.showinfo(APP_NAME, (
            "Beide Seiten verbinden sich nur nach außen mit dem Vermittlungsserver. Alles ist Ende-zu-Ende "
            "verschlüsselt (AES-256) – der Server sieht nur unlesbare Daten; ohne Geräte-ID und Kopplungscode kommt "
            "niemand an das Teleskop.\n\n"
            "Voreingestellt ist der öffentliche Server von HiveMQ; für den Dauerbetrieb ist ein eigenes kostenloses "
            "HiveMQ-Cloud-Konto zuverlässiger (eintragen auf beiden PCs gleich).\n\n"
            "Der Plan läuft immer auf der Heimstation – reißt die Verbindung unterwegs ab, geht die Nacht trotzdem weiter. "
            "Die Heimstation (PC beim Teleskop) muss eingeschaltet sein, das Programm laufen und mit dem Air verbunden sein."))

    def _remote_other_ways(self):
        messagebox.showinfo(APP_NAME, (
            "Empfohlen (am sichersten): Das Programm läuft auf einem PC ZUHAUSE im selben Netz wie das Air. Unterwegs "
            "greifst du mit einer Fernwartung (z. B. Windows-Remotedesktop über VPN, Chrome Remote Desktop oder "
            "AnyDesk) auf diesen PC zu. Der Plan läuft dann auch weiter, wenn deine Verbindung unterwegs abbricht.\n\n"
            "Alternative: Dieses Programm unterwegs auf dem Laptop und ein VPN nach Hause (z. B. WireGuard/VPN der "
            "FRITZ!Box oder Tailscale mit einem Gerät zuhause als Subnetz-Router). Dann bei „Unterwegs“ dieselbe "
            "Adresse wie zuhause eintragen (Air im Heimnetz, nicht im Hotspot-Modus). Bricht die Verbindung ab, "
            "nimmt das Air die laufende Serie selbst fertig auf; das Programm verbindet sich neu und macht weiter.\n\n"
            "NIEMALS im Router Ports (4400/4700) zum Air freigeben: Port 4400 hat kein Passwort – jeder im Internet "
            "könnte die Montierung bewegen."))

    def _broker(self):
        b = dict(REMOTE_BROKER_DEFAULT)
        b.update({k: v for k, v in (self.cfg.get("air_broker") or {}).items() if k != "pw"})
        b["pw"] = secret_unprotect((self.cfg.get("air_broker") or {}).get("pw", ""))
        return b

    def _broker_save(self):
        try:
            port = int(self.rb_port.get())
        except ValueError:
            messagebox.showerror(APP_NAME, "Port bitte als Zahl eingeben.")
            return
        self.cfg["air_broker"] = {"host": self.rb_host.get().strip() or REMOTE_BROKER_DEFAULT["host"], "port": port,
                                  "tls": bool(self.rb_tls.get()), "user": self.rb_user.get().strip(),
                                  "pw": secret_protect(self.rb_pw.get())}
        save_config(self.cfg)
        self.log("Vermittlungsserver gespeichert – gilt beim nächsten Verbinden.", "ok")

    # Heimstation
    def _station_cfg(self):
        st = self.cfg.setdefault("air_station", {})
        if not st.get("id"):
            st["id"] = remote_new_id()
        if not st.get("code"):
            st["code"] = secret_protect(remote_new_code())
        st["name"] = self.rs_name.get().strip() or "Sternwarte"
        st["perm"] = next((k for k, v in REMOTE_PERMS.items() if v == self.rs_perm.get()), "full")
        st["on"] = bool(self.rs_on.get())
        save_config(self.cfg)
        return st

    def station_toggle(self, quiet=False):
        st = self._station_cfg()
        if self.station:
            self.station.stop()
            self.station = None
        if not st["on"]:
            self.rs_msg.set("Fernzugriff aus.")
            if not quiet:
                self.log("Fernzugriff auf dieses ASIAIR ausgeschaltet.", "info")
            return
        if not HAVE_MQTT:
            self.rs_on.set(False)
            messagebox.showerror(APP_NAME, "Für den Fernzugriff fehlt das Paket 'paho-mqtt'.\n\npip install paho-mqtt")
            return
        try:
            self.station = HomeStation(self, st["id"], secret_unprotect(st["code"]), st["name"], st["perm"], self._broker())
            self.station.start()
        except Exception as e:
            self.station = None
            self.log(f"Fernzugriff konnte nicht starten: {e}", "err")
            return
        self.rs_msg.set(f"Geräte-ID {st['id']} · verbinde mit dem Vermittlungsserver …")
        if not quiet:
            self.log(f"Fernzugriff eingeschaltet (Geräte-ID {st['id']}). Das Programm muss dafür laufen und mit dem "
                     "ASIAIR verbunden sein.", "ok")

    def station_show_code(self):
        st = self._station_cfg()
        win = self.make_window("Kopplungscode", minsize=(420, 240))
        ttk.Label(win, text="Auf dem Ferngerät unter „Gerät hinzufügen …“ eintragen:", wraplength=460).pack(padx=18, pady=(16, 8), anchor="w")
        txt = f"Geräte-ID:      {st['id']}\nKopplungscode:  {secret_unprotect(st['code'])}"
        ttk.Label(win, text=txt, font=("Consolas", 14, "bold")).pack(padx=18, anchor="w")
        ttk.Label(win, text="Code geheim halten – wer ihn kennt, kann das Teleskop steuern. Bei Verdacht „Neuen Code "
                            "erzeugen“ – alte Ferngeräte müssen dann neu gekoppelt werden.",
                  foreground=C["warn"], wraplength=460).pack(padx=18, pady=10, anchor="w")
        r = ttk.Frame(win)
        r.pack(fill="x", padx=18, pady=(0, 14))

        def copy():
            self.clipboard_clear()
            self.clipboard_append(f"{st['id']} {secret_unprotect(st['code'])}")
        ttk.Button(r, text="Kopieren", command=copy).pack(side="left")
        ttk.Button(r, text="Schließen", style="Accent.TButton", command=win.destroy).pack(side="right")
        win.transient(self)

    def station_new_code(self):
        if not messagebox.askyesno(APP_NAME, "Neuen Kopplungscode erzeugen? Bisher gekoppelte Ferngeräte haben dann "
                                             "keinen Zugriff mehr und müssen neu gekoppelt werden."):
            return
        st = self.cfg.setdefault("air_station", {})
        st["id"] = remote_new_id()
        st["code"] = secret_protect(remote_new_code())
        save_config(self.cfg)
        if self.station:
            self.station_toggle(quiet=True)
        self.station_show_code()

    # Ferngerät
    def _remote_list(self):
        return self.cfg.setdefault("air_remotes", [])

    def _remote_fill(self):
        vals = [f"{r['name']} ({r['id']})" for r in self._remote_list()]
        self.rr_cb.configure(values=vals)
        if vals and self.rr_sel.get() not in vals:
            self.rr_sel.set(vals[0])
        if not vals:
            self.rr_sel.set("")

    def remote_add(self):
        win = self.make_window("Ferngerät hinzufügen", minsize=(420, 260))
        frm = ttk.Frame(win, padding=16)
        frm.pack(fill="both", expand=True)
        v = {k: tk.StringVar() for k in ("name", "id", "code")}
        v["name"].set("Sternwarte")
        for k, (lbl, key) in enumerate((("Name:", "name"), ("Geräte-ID:", "id"), ("Kopplungscode:", "code"))):
            ttk.Label(frm, text=lbl).grid(row=k, column=0, sticky="w", pady=4)
            ttk.Entry(frm, textvariable=v[key], width=30).grid(row=k, column=1, sticky="w", padx=6, pady=4)
        ttk.Label(frm, text="Steht an der Heimstation unter „Kopplungscode anzeigen“.", foreground=C["muted"]).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        def ok():
            sid, code = _norm(v["id"].get()), _norm(v["code"].get())
            if len(sid) != 8 or len(code) != 16:
                messagebox.showerror(APP_NAME, "Geräte-ID (8 Zeichen) oder Kopplungscode (16 Zeichen) unvollständig.")
                return
            sid_f = f"{sid[:4]}-{sid[4:]}"
            lst = [r for r in self._remote_list() if _norm(r["id"]) != sid]
            lst.append({"name": v["name"].get().strip() or sid_f, "id": sid_f, "code": secret_protect(code)})
            self.cfg["air_remotes"] = lst
            save_config(self.cfg)
            self._remote_fill()
            self.rr_sel.set(f"{lst[-1]['name']} ({sid_f})")
            win.destroy()
        ttk.Button(frm, text="Hinzufügen", style="Accent.TButton", command=ok).grid(row=4, column=1, sticky="e", pady=12)
        win.transient(self)

    def _remote_selected(self):
        sel = self.rr_sel.get()
        return next((r for r in self._remote_list() if sel.endswith(f"({r['id']})")), None)

    def remote_del(self):
        r = self._remote_selected()
        if r and messagebox.askyesno(APP_NAME, f"„{r['name']}“ entfernen?"):
            self.cfg["air_remotes"] = [x for x in self._remote_list() if x is not r]
            save_config(self.cfg)
            self._remote_fill()

    def remote_connect(self):
        r = self._remote_selected()
        if not r:
            messagebox.showinfo(APP_NAME, "Zuerst ein Gerät hinzufügen (Geräte-ID und Kopplungscode der Heimstation).")
            return
        if not HAVE_MQTT:
            messagebox.showerror(APP_NAME, "Für den Fernzugriff fehlt das Paket 'paho-mqtt'.\n\npip install paho-mqtt")
            return
        if self.air_local.connected:
            if not messagebox.askyesno(APP_NAME, "Dieser PC ist gerade direkt mit einem ASIAIR verbunden. Trennen und "
                                                 "stattdessen aus der Ferne verbinden?"):
                return
            self.air_local.disconnect()
        self._air_back_local()
        try:
            rig = RemoteRig(self.log, self._air_dirty, r["id"], secret_unprotect(r["code"]), r["name"], self._broker())
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))
            return
        rig.event_hooks.append(self._air_ev_preview)
        self.air = rig
        self.rr_msg.set("verbinde …")
        self.nb.select(self._tab_index("ASIAIR"))

        def work():
            if rig.connect():
                self.log(f"Fernzugriff: mit „{r['name']}“ verbunden." if rig.station_ok else
                         f"Fernzugriff: warte auf „{r['name']}“ …", "ok" if rig.station_ok else "warn")
            self._air_dirty()
        self.bg(work)

    def _remote_refresh_ui(self):
        try:
            st = self.station
            if st:
                n = len(st.remotes)
                self.rs_msg.set(f"Geräte-ID {st.sid} · " + ("online" if st.link.up else "verbinde mit dem Vermittlungsserver …")
                                + (f" · {n} Ferngerät(e) verbunden" if n else ""))
            a = self.air
            if getattr(a, "remote", False):
                self.rr_msg.set("Vermittlungsserver nicht erreichbar" if not a.link.up else
                                "Heimstation offline – läuft dort das Programm?" if not a.online else
                                ("verbunden" if a.snap.get("air") else "verbunden – aber das Air ist an der Heimstation nicht verbunden"))
            else:
                self.rr_msg.set("")
        except Exception:
            pass

    def _reset_airnet(self):
        self.an_auto.set(True)
        self.an_wait.set("15")
        self._an_save()

    # ---- Tab: Konsole -----------------------------------------------------
    def _tab_console(self, nb):
        f = ttk.Frame(nb, padding=12)
        nb.add(f, text="Konsole")
        ttk.Label(f, text="Beliebigen JSON-RPC-Befehl senden (Methode + Parameter als JSON).", foreground=C["muted"]).pack(anchor="w")
        r = ttk.Frame(f)
        r.pack(fill="x", pady=8)
        ttk.Label(r, text="Methode:").pack(side="left")
        self.c_method = tk.StringVar(value="get_device_state")
        ttk.Combobox(r, textvariable=self.c_method, width=28, values=[
            "get_device_state", "get_setting", "get_stack_setting", "get_focuser_position", "scope_get_equ_coord",
            "get_albums", "pi_is_verified", "get_camera_state", "get_view_state", "iscope_start_view",
            "iscope_stop_view", "scope_move_to_horizon", "scope_goto", "scope_speed_move", "scope_sync", "set_setting",
            "start_create_dark", "start_polar_align", "stop_polar_align"]).pack(side="left", padx=6)
        ttk.Label(r, text="Parameter:").pack(side="left")
        self.c_params = tk.StringVar(value="")
        ttk.Entry(r, textvariable=self.c_params, width=50).pack(side="left", padx=6)
        ttk.Button(r, text="Senden", style="Accent.TButton", command=self.console_send).pack(side="left")
        ttk.Button(r, text="Leeren", command=lambda: self.c_out.delete("1.0", "end")).pack(side="left", padx=(6, 0))
        ttk.Button(r, text="Antwort kopieren", command=self.console_copy).pack(side="left", padx=(6, 0))
        self.c_keep = tk.BooleanVar(value=False)
        ttk.Checkbutton(r, text="Ältere Antworten behalten", variable=self.c_keep).pack(side="left", padx=(10, 0))
        self.c_out = tk.Text(f, bg=C["textbg"], fg=C["rx"], font=("Consolas", 9), relief="flat")
        self.c_out.pack(fill="both", expand=True)

    # ======================================================================
    # Logik
    # ======================================================================
    def log(self, text, tag="info"):
        self.ui_q.put(("log", text, tag))
        st = getattr(self, "station", None)
        if st and tag not in ("tx", "rx"):
            st.add_log(text, tag)

    def ui(self, fn, *a):
        self.ui_q.put(("call", fn, a))

    def _pump(self):
        try:
            while True:
                item = self.ui_q.get_nowait()
                if item[0] == "log":
                    _, text, tag = item
                    self.logbox.configure(state="normal")
                    self.logbox.insert("end", f"{datetime.now():%H:%M:%S}  {tr(text)}\n", tag)
                    self.logbox.see("end")
                    self.logbox.configure(state="disabled")
                else:
                    _, fn, a = item
                    fn(*a)
        except queue.Empty:
            pass
        self.after(100, self._pump)

    def bg(self, fn, *a):
        threading.Thread(target=fn, args=a, daemon=True).start()

    def preview_waiting(self, d):
        for p in list(d.panels):
            if isinstance(p, PreviewPanel):
                try:
                    p.info_var.set("Live: warte auf ein neues Bild …")
                except Exception:
                    pass

    def ask_sync(self, text, timeout=120):
        """Aus einem Hintergrund-Thread Ja/Nein fragen (Dialog läuft im Oberflächen-Thread)."""
        done, res = threading.Event(), {"v": False}

        def ask():
            try:
                res["v"] = messagebox.askyesno(APP_NAME, text)
            finally:
                done.set()
        self.ui(ask)
        done.wait(timeout)
        return res["v"]

    # ---- Geräte & Ziele ---------------------------------------------------
    @property
    def wifi(self):
        return self.active.wifi if self.active else self._nowifi

    def group(self):
        return [d for d in self.devices if d.selected]

    def targets(self, force_group=False):
        if force_group or self.target_var.get() == "group":
            return [d for d in self.group() if d.connected]
        return [self.active] if self.active and self.active.connected else []

    def rpc(self, method, params=None, cb=None, force_group=False):
        devs = self.targets(force_group)
        if not devs:
            self.log("Kein verbundenes Zielgerät (Übersicht prüfen).", "warn")
            return
        if method in Device.ARM_CLOSING:
            devs = self.confirm_arm_closing(devs, {"scope_park": "Parken", "pi_shutdown": "Ausschalten"}.get(method, method))
            if not devs:
                return
        for d in devs:
            def job(d=d):
                r = d.wifi.send(method, params)
                if cb and r is not None and d is self.active:
                    self.ui(cb, r)
            self.bg(job)

    def group_rpc(self, method, params=None):
        self.rpc(method, params, force_group=True)

    def open_arm(self, force_group=False, mode="star"):
        devs = self.targets(force_group)
        if not devs:
            self.log("Kein verbundenes Zielgerät (Übersicht prüfen).", "warn")
            return
        for d in devs:
            self.bg(d.open_arm, mode)

    def stop_all(self, force_group=False):
        devs = self.targets(force_group) or [d for d in self.devices if d.connected]
        for d in devs:
            self.bg(d.stop_all)

    def group_each(self, fn):
        for d in self.group():
            self.bg(fn, d)

    def auto_connect_start(self):
        pem = self.pem_var.get().strip() if hasattr(self, "pem_var") else self.cfg.get("pem", "")
        devs = [d for d in self.devices if not d.connected and not d.reconnecting]
        if devs:
            self.log(f"Verbinde automatisch mit {len(devs)} bekannten Seestar(s) …")
        for d in devs:
            self.bg(d.connect, pem)

    def group_connect(self):
        pem = self.pem_var.get().strip()
        for d in self.group():
            if not d.connected:
                self.bg(d.connect, pem)

    def group_popups(self):
        devs = self.group()
        for k, d in enumerate(devs):
            self.open_popup(d, offset=k)

    def _dev_label(self, d):
        return f"{d.name} ({d.host})"

    def _dev_by_label(self, label):
        return next((d for d in self.devices if self._dev_label(d) == label), None)

    def _sel_dev(self):
        return self.active

    def _one(self, action):
        d = self._sel_dev()
        if not d:
            messagebox.showinfo(APP_NAME, "Bitte zuerst ein Gerät in der Liste auswählen.")
            return
        if action == "connect":
            self.bg(d.connect, self.pem_var.get().strip())
        else:
            self.bg(d.disconnect)

    # ---- Geräteliste (Übersicht) ------------------------------------------------
    DEV_COLS = (("", 0), ("Name", 3), ("IP-Adresse", 1), ("Modell", 2), ("Status", 1), ("Frames", 0),
                ("Akku", 0), ("", 0), ("Temp.", 0), ("Speicher frei", 0), ("Auftrag", 4), ("", 0), ("", 0), ("", 0))
    DEV_NCELLS = 10                      # Spalten 1–10 sind Textzellen, 11–13 Knöpfe

    def _dev_list_build(self, parent):
        wrap = ttk.Frame(parent)
        wrap.pack(fill="both", expand=True)
        cv = tk.Canvas(wrap, bg=C["bg"], highlightthickness=0, height=170)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        cv.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(cv, bg=C["bg"])
        win = cv.create_window(0, 0, window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))
        for w in (cv, inner):
            w.bind("<MouseWheel>", lambda e: cv.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        for k, (h, wgt) in enumerate(self.DEV_COLS):
            inner.columnconfigure(k, weight=wgt)
            if h:
                tk.Label(inner, text=h, bg=C["tab"], fg=C["fg"], font=("Segoe UI", 9, "bold"), anchor="w",
                         padx=6, pady=4).grid(row=0, column=k, sticky="ew")
            else:
                tk.Label(inner, text="", bg=C["tab"], pady=4).grid(row=0, column=k, sticky="ew")
        self.dev_inner = inner
        self.dev_rows = {}
        self._dev_order = []
        self.dev_empty = tk.Label(inner, text="Noch kein Gerät – oben IP eintragen oder „Netzwerk durchsuchen“.",
                                  bg=C["bg"], fg=C["muted"], pady=14)

    def _dev_row_build(self, r, d):
        inner = self.dev_inner
        w = {"var": tk.BooleanVar(value=d.selected)}

        def toggle_grp():
            d.selected = bool(w["var"].get())
            self.save_devices()
            self.refresh_overview()
        w["grp"] = ttk.Checkbutton(inner, variable=w["var"], command=toggle_grp)
        w["grp"].grid(row=r, column=0, padx=(6, 2), pady=2)
        cells = []
        for k in range(1, self.DEV_NCELLS + 1):
            lab = tk.Label(inner, text="", anchor="w", padx=0 if k == 7 else 6, pady=5, bg=C["bg"], fg=C["fg"],
                           wraplength=320 if k == self.DEV_NCELLS else 0, justify="left")
            lab.grid(row=r, column=k, sticky="nsew")
            lab.bind("<Button-1>", lambda e, d=d: self.set_active(d))
            lab.bind("<Double-1>", lambda e, d=d: self.open_popup(d))
            cells.append(lab)
        w["cells"] = cells
        w["btn"] = ttk.Button(inner, width=11, command=lambda d=d: self.toggle_connect(d))
        w["btn"].grid(row=r, column=self.DEV_NCELLS + 1, padx=(6, 2), pady=3)
        ttk.Button(inner, text="Vorschau", style="Small.TButton",
                   command=lambda d=d: self.open_popup(d)).grid(row=r, column=self.DEV_NCELLS + 2, padx=2)
        ttk.Button(inner, text="Einstellungen", style="Small.TButton",
                   command=lambda d=d: self.open_settings_popup(d)).grid(row=r, column=self.DEV_NCELLS + 3, padx=(2, 6))
        return w

    def toggle_connect(self, d):
        """Eine Taste pro Gerät: verbinden, wenn getrennt – sonst trennen (stoppt auch das automatische Neuverbinden)."""
        if d.connected or d.reconnecting or d.connecting:
            self.bg(d.disconnect)
        else:
            self.bg(d.connect, self.pem_var.get().strip())

    def move_device(self, delta):
        d = self.active
        if not d or d not in self.devices:
            return
        i = self.devices.index(d)
        j = i + delta
        if 0 <= j < len(self.devices):
            self.devices[i], self.devices[j] = self.devices[j], self.devices[i]
            self.save_devices()
            self.refresh_overview()

    def _dev_list_refresh(self):
        if not hasattr(self, "dev_inner"):
            return
        order = [id(d) for d in self.devices]
        if order != self._dev_order:
            for w in self.dev_inner.grid_slaves():
                if int(w.grid_info().get("row", 0)) > 0:
                    w.destroy()
            self.dev_rows = {}
            self.dev_empty = tk.Label(self.dev_inner, text="Noch kein Gerät – oben IP eintragen oder "
                                                           "„Netzwerk durchsuchen“.", bg=C["bg"], fg=C["muted"], pady=14)
            for r, d in enumerate(self.devices, start=1):
                self.dev_rows[id(d)] = self._dev_row_build(r, d)
            self._dev_order = order
        if not self.devices:
            self.dev_empty.grid(row=1, column=0, columnspan=len(self.DEV_COLS), sticky="w", padx=8)
            return
        for d in self.devices:
            w = self.dev_rows[id(d)]
            w["var"].set(d.selected)
            act = d is self.active
            bg = C["panel2"] if act else C["bg"]
            st = d.status
            stcol = C["ok"] if d.connected else (C["warn"] if (d.connecting or d.reconnecting) else C["muted"])
            vals = (("» " if act else "") + d.name + ("  [Arm-Schutz]" if d.protect else ""), d.host,
                    (MODELS[d.model]["label"] if d.model else "–") + {True: " · EQ", False: " · Alt-Az", None: ""}[d.eq_mode],
                    "● " + st, d.frames if d.frames is not None else "–",
                    f"{d.battery} %" if d.battery is not None else "–",
                    "⚡" if (d.charging and d.battery is not None) else "",
                    f"{d.temp:.0f} °C" if isinstance(d.temp, (int, float)) else "–",
                    f"{fmt_num(d.storage_free / 1024, 1)} GB" if isinstance(d.storage_free, (int, float)) else "–",
                    d.job_text or self._paused_text(d) or "–")
            for k, (lab, v) in enumerate(zip(w["cells"], vals)):
                fg = stcol if k == 3 else (C.get("bolt", "#ffd23f") if k == 6 else C["fg"])
                font = ("Segoe UI", 10, "bold") if (act and k == 0) else ("Segoe UI", 12, "bold") if k == 6 else ("Segoe UI", 10)
                lab.configure(text=str(v), bg=bg, fg=fg, font=font)
            btn = w["btn"]
            if d.connected:
                btn.configure(text="Trennen", style="Disconnect.TButton")
                btn.state(["!disabled"])
            elif d.connecting:
                btn.configure(text="Verbinde …", style="Connect.TButton")
                btn.state(["disabled"])
            elif d.reconnecting:
                btn.configure(text="Abbrechen", style="Disconnect.TButton")
                btn.state(["!disabled"])
            else:
                btn.configure(text="Verbinden", style="Connect.TButton")
                btn.state(["!disabled"])

    def add_device(self, ip, name=""):
        ip = ip.strip()
        if not ip:
            return None
        ex = next((d for d in self.devices if d.host == ip), None)
        if ex:
            return ex
        d = Device(self, name.strip() or f"Seestar {len(self.devices) + 1}", ip)
        self.devices.append(d)
        self.save_devices()
        self.refresh_overview()
        if not self.active:
            self.set_active(d)
        d.log(f"hinzugefügt ({ip}).", "ok")
        return d

    def add_device_from_form(self):
        if self.add_device(self.new_ip.get(), self.new_name.get()):
            self.new_ip.set("")
            self.new_name.set("")

    def remove_device(self):
        d = self._sel_dev()
        if not d or not messagebox.askyesno(APP_NAME, f"„{d.name}“ aus der Liste entfernen?"):
            return
        self.bg(d.disconnect)
        if d.popup:
            d.popup.destroy()
        self.devices.remove(d)
        if self.active is d:
            self.set_active(self.devices[0] if self.devices else None)
        self.save_devices()
        self.refresh_overview()

    def rename_device(self):
        d = self._sel_dev()
        if not d:
            return
        win = self.make_window("Umbenennen", minsize=(260, 110))
        v = tk.StringVar(value=d.name)
        ent = ttk.Entry(win, textvariable=v, width=30)
        ent.pack(padx=14, pady=(14, 8))
        ent.focus_set()
        def ok(_e=None):
            if v.get().strip():
                d.name = v.get().strip()
                self.save_devices()
                self.refresh_overview()
                if d.popup:
                    d.popup.title(f"Vorschau – {self._dev_label(d)}")
            win.destroy()
        ent.bind("<Return>", ok)
        ttk.Button(win, text="OK", style="Accent.TButton", command=ok).pack(pady=(0, 14))

    def access_dialog(self, d=None):
        """Zugangsdaten eines Geräts: Name, Verbindungsart, WLAN-Name und Passwort."""
        d = d or self._sel_dev()
        if not d:
            return
        win = self.make_window(f"Zugangsdaten – {d.name}", minsize=(520, 420))
        frm = ttk.Frame(win, padding=14)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)
        v_name, v_host = tk.StringVar(value=d.name), tk.StringVar(value=d.host)
        v_link = tk.StringVar(value=d.link)
        v_ssid = tk.StringVar(value=d.ap_ssid)
        v_pass = tk.StringVar(value="" if str(d.ap_pass).startswith("enc") else d.ap_pass)
        v_show = tk.BooleanVar(value=False)
        ttk.Label(frm, text="Gerätename (in dieser App):").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(frm, textvariable=v_name, width=30).grid(row=0, column=1, sticky="we", pady=3)

        lk = ttk.Labelframe(frm, text="Verbindung", padding=8)
        lk.grid(row=1, column=0, columnspan=2, sticky="we", pady=(10, 4))
        ttk.Radiobutton(lk, text="Heimnetz – Seestar und PC im selben WLAN (Stationsmodus, empfohlen)",
                        variable=v_link, value="home").pack(anchor="w")
        ttk.Radiobutton(lk, text="Direkt – PC verbindet sich mit dem WLAN des Seestar (immer nur ein Seestar zugleich)",
                        variable=v_link, value="ap").pack(anchor="w")

        ttk.Label(frm, text="IP-Adresse:").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Entry(frm, textvariable=v_host, width=20).grid(row=2, column=1, sticky="w", pady=3)
        ttk.Label(frm, text="WLAN-Name des Seestar:").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Entry(frm, textvariable=v_ssid, width=30).grid(row=3, column=1, sticky="we", pady=3)
        ttk.Label(frm, text="WLAN-Passwort:").grid(row=4, column=0, sticky="w", pady=3)
        pw = ttk.Entry(frm, textvariable=v_pass, width=30, show="•")
        pw.grid(row=4, column=1, sticky="we", pady=3)
        ttk.Checkbutton(frm, text="Passwort anzeigen", variable=v_show,
                        command=lambda: pw.configure(show="" if v_show.get() else "•")).grid(row=5, column=1, sticky="w")
        ttk.Label(frm, text=f"WLAN-Name z. B. S50_1a2b3c4d. Ab Werk ist das Passwort {DEFAULT_AP_PASS}; die Seestar-App "
                            "zeigt beides im Gerätemenü. Den WLAN-Namen liest die App bei verbundenem Gerät selbst aus; das "
                            "Passwort liefert neuere Firmware nur verschlüsselt – bitte einmal selbst eintragen.",
                  foreground=C["muted"], wraplength=470, justify="left").grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        info = tk.StringVar()
        ttk.Label(frm, textvariable=info, foreground=C["muted2"], wraplength=470, justify="left").grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))

        def show_station():
            st = d.station or {}
            if st.get("ssid"):
                info.set(f"Heimnetz laut Seestar: {st.get('ssid')} · IP {st.get('ip', '–')} · Signal {st.get('sig_lev', '–')} dBm")
            elif d.connected:
                info.set("Das Seestar ist mit keinem Heimnetz verbunden (nur eigenes WLAN).")
            else:
                info.set("")
        show_station()

        def on_link(*_a):
            if v_link.get() == "ap" and v_host.get().strip() in ("", d.host) and not d.connected:
                v_host.set(AP_DEFAULT_IP)
        v_link.trace_add("write", on_link)

        def read_from_device():
            if not d.connected:
                messagebox.showinfo(APP_NAME, "Dazu muss das Gerät verbunden sein.")
                return
            def job():
                d.read_access_data()
                self.ui(lambda: (v_ssid.set(d.ap_ssid), d.ap_pass and v_pass.set(d.ap_pass), show_station()))
            self.bg(job)

        def apply(close=True):
            name, host = v_name.get().strip(), v_host.get().strip()
            if not name or not host:
                messagebox.showerror(APP_NAME, "Bitte Gerätename und IP-Adresse angeben.")
                return False
            if v_link.get() == "ap" and not v_ssid.get().strip():
                messagebox.showerror(APP_NAME, "Für die Direktverbindung bitte den WLAN-Namen des Seestar eintragen.")
                return False
            if host != d.host and any(x.host == host for x in self.devices if x is not d):
                messagebox.showerror(APP_NAME, f"Die IP-Adresse {host} ist schon einem anderen Gerät zugeordnet.")
                return False
            if host != d.host and d.connected:
                self.bg(d.disconnect)
            d.name, d.host, d.link = name, host, v_link.get()
            d.ap_ssid, d.ap_pass = v_ssid.get().strip(), v_pass.get()
            self.save_devices()
            self.refresh_overview()
            d.log("Zugangsdaten gespeichert.", "ok")
            if close:
                win.destroy()
            return True

        def join_now():
            if not apply(close=False):
                return
            info.set("Verbinde den PC mit dem Seestar-WLAN …")
            def job():
                ok, msg = join_seestar_wifi(d.ap_ssid, d.ap_pass, d.host)
                d.log(msg, "ok" if ok else "err")
                self.ui(lambda: info.set(msg) if win.winfo_exists() else None)
            self.bg(job)

        b = ttk.Frame(frm)
        b.grid(row=8, column=0, columnspan=2, sticky="we", pady=(14, 0))
        ttk.Button(b, text="Vom Seestar lesen", command=read_from_device).pack(side="left")
        ttk.Button(b, text="PC jetzt mit diesem WLAN verbinden", command=join_now).pack(side="left", padx=6)
        ttk.Button(b, text="Speichern", style="Accent.TButton", command=apply).pack(side="right")

    def save_devices(self):
        self.cfg["devices"] = [{"name": d.name, "ip": d.host, "selected": d.selected, "filter": d.ext_filter,
                                "protect": d.protect, "dewcap": d.dewcap, "accessory": d.accessory, "link": d.link, "ap_ssid": d.ap_ssid,
                                "ap_pass": secret_protect(d.ap_pass), "pending": d.pending} for d in self.devices]
        save_config(self.cfg)

    def set_active(self, d):
        self.active = d
        if d and d.model:
            self.set_model(d.model)
        if self.preview_tab_panel:
            self.preview_tab_panel.set_device(d)
        if self.settings_tab_panel:
            self.settings_tab_panel.set_device(d)
        if hasattr(self, "mz_canvas"):
            self.draw_mosaic()
        if hasattr(self, "lvl_canvas"):
            self.eq_draw()
        if hasattr(self, "fc_tree"):
            self.fc_points = []
            self.fc_refresh()
        if hasattr(self, "rec_tree"):
            self.rec_compute()
        if hasattr(self, "pl_tree"):
            self.pl_fill()
        if d:
            self.ip_var.set(d.host)
        self.refresh_overview()

    def refresh_overview(self):
        n = len(self.group())
        self.group_rb_text.set(f"alle markierten ({n})")
        labels = [self._dev_label(d) for d in self.devices]
        self.active_cb.configure(values=labels)
        self.active_var.set(self._dev_label(self.active) if self.active else "")
        if self.active and self.active.connected:
            self.status_var.set("● verbunden")
            self.status_lbl.configure(foreground=C["ok"])
        else:
            self.status_var.set("● getrennt" if self.active else "● Kein Gerät")
            self.status_lbl.configure(foreground=C["err"])
        self._dev_list_refresh()

    def device_changed(self, d):
        self.refresh_overview()
        if d is self.active:
            self.show_focus_pos()

    def show_focus_pos(self):
        d = self.active
        if hasattr(self, "focus_var"):
            self.focus_var.set(f"Position: {d.focus_pos}" if d and d.focus_pos is not None else "Position: ?")
        if hasattr(self, "fc_pos") and d and d.focus_pos is not None:
            self.fc_pos.set(f"Position: {d.focus_pos}")

    def device_connected(self, d):
        self.refresh_overview()
        if d is self.active and d.model and self.model_auto.get():
            self.set_model(d.model)
        if d is self.active and hasattr(self, "lvl_canvas"):
            self.eq_draw()
        if (self.cfg.get("loc_consent") is True and self.cfg.get("loc_sources", {}).get("seestar", True)
                and (not self._site() or self.cfg.get("loc_src") == "internet")):
            self.after(3000, lambda: self.loc_locate(quiet=True))      # ungenaue/fehlende Position verbessern
        for p in d.settings_panels:
            p.refresh()
        auto_init = self.cfg.get("auto_init", True) and not d.job      # nicht mitten in einem laufenden Ablauf
        site = self._site()
        if self.check_moved(d):
            auto_init = False            # erst die Antwort abwarten – sonst überschreiben wir den neuen Ort im Seestar

        def _load_then_protect(d=d):
            if auto_init:
                self.send_time_location(d, site, quiet=True)
            d.refresh_settings()
            d.flush_pending()
            if d.protect:
                self.ui(self.apply_protection, d)
        self.bg(_load_then_protect)
        if d.panels:
            self.bg(d.preview_stack, True)
        self.after(1500, lambda: self.offer_resume(d))

    def device_event(self, d, ev):
        name = ev.get("Event", "")
        if name == "Stack" and "stacked_frame" in ev:
            d._last_stack_ev = (time.time(), int(ev.get("stacked_frame", 0)), int(ev.get("dropped_frame", 0)))
        if name == "EqModePA":
            self._on_pa_event(d, ev)
        self.ev_txt.insert("end", f"[{d.name}] " + json.dumps(ev, ensure_ascii=False)[:380] + "\n")
        self.ev_txt.see("end")
        if name == "Stack" and "stacked_frame" in ev:
            n = ev.get("stacked_frame")
            if d is self.active:
                self.stack_var.set(f"Gestackte Frames ({d.name}): {n}  (verworfen: {ev.get('dropped_frame', 0)})")
            if HAVE_IMAGING and n and n != d.last_stack_n and d.wants_auto_stack():
                d.last_stack_n = n
                self.bg(d.preview_stack, True)
            self.refresh_overview()
        if name in ("AutoGoto", "AutoFocus", "ScopeGoto", "PlateSolve") and ev.get("state") in ("complete", "fail"):
            d.log(f"Ereignis {name}: {ev.get('state')}", "ok" if ev.get("state") == "complete" else "err")

    def open_popup(self, d, offset=0):
        if not HAVE_IMAGING:
            messagebox.showinfo(APP_NAME, "Für die Vorschau bitte numpy und pillow installieren.")
            return
        if d.popup and d.popup.winfo_exists():
            d.popup.deiconify()
            d.popup.lift()
            return
        win = self.make_window(f"Vorschau – {self._dev_label(d)}", key=f"preview:{d.host}",
                               size=f"560x780+{60 + offset * 40}+{60 + offset * 40}", minsize=(360, 360))
        panel = PreviewPanel(win, self, device=d)
        panel.pack(fill="both", expand=True)
        d.popup = win
        op = self.cfg.setdefault("open_previews", [])
        if d.host not in op:
            op.append(d.host)
            save_config(self.cfg)

        def close(remember_closed=True):
            panel.detach()
            if not d.panels and d.imager and d.imager.streaming:
                self.bg(d.preview_stop)
            d.popup = None
            if remember_closed and d.host in self.cfg.get("open_previews", []):
                self.cfg["open_previews"].remove(d.host)
                save_config(self.cfg)
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", close)
        win.close_keep = lambda: close(False)
        if d.connected and not (d.imager and d.imager.streaming):
            panel.info_var.set("Lade das letzte Stack-Bild …")     # zum Start sofort etwas zeigen, ohne Protokolleintrag
            self.bg(d.preview_stack, True)

    # ---- Verbindung -------------------------------------------------------
    def do_discover(self, add_all=False):
        self.log("Suche Seestar im Netzwerk …")
        def job():
            found = SeestarWifi.discover()
            def apply():
                diag = SeestarWifi.last_scan
                if not found:
                    self.log("Kein Seestar gefunden. IP manuell eintragen (Router oder Seestar-App → Einstellungen).", "warn")
                    self.log(f"Gesucht über diese PC-Adressen: {', '.join(diag.get('local') or []) or 'keine'}", "warn")
                    return
                self.log(f"Suche erfolgreich über {diag.get('via')}.", "ok")
                ips = list(found)
                self.ip_cb.configure(values=ips)
                if not add_all:
                    self.ip_var.set(ips[0])
                for ip, info in found.items():
                    res = info.get("result", {}) if isinstance(info, dict) else {}
                    name = res.get("device_name") or res.get("product_model") or ""
                    self.log(f"Gefunden: {ip} {name}", "ok")
                    if add_all:
                        self.add_device(ip, name)
            self.ui(apply)
        self.bg(job)

    def pick_pem(self):
        p = filedialog.askopenfilename(title="PEM-Schlüssel wählen", filetypes=[("PEM", "*.pem"), ("Alle", "*.*")])
        if p:
            self.pem_var.set(p)

    def do_connect(self):
        ip = self.ip_var.get().strip()
        if not ip:
            return
        self.cfg.update(ip=ip, pem=self.pem_var.get().strip())
        save_config(self.cfg)
        d = self.add_device(ip)
        self.set_active(d)
        self.bg(d.connect, self.pem_var.get().strip())

    def send_time_location(self, d, site=None, quiet=False):
        """Uhrzeit, Zeitzone und Standort an ein Seestar senden (läuft im Hintergrund-Thread)."""
        now = datetime.now().astimezone()
        d.wifi.send("pi_set_time", {"year": now.year, "mon": now.month, "day": now.day, "hour": now.hour,
                                    "min": now.minute, "sec": now.second, "time_zone": local_timezone_name()},
                    quiet=quiet)
        if site:
            d.wifi.send("set_user_location", {"lat": site[0], "lon": site[1], "force": True}, quiet=quiet)
        if quiet:
            d.log("Zeit und Standort an das Seestar gesendet." if site else
                  "Zeit gesendet – Standort fehlt noch (Tab „Standort“).", "ok" if site else "warn")

    def do_init(self, force_group=False):
        try:
            lat, lon = float(self.lat_var.get().replace(",", ".")), float(self.lon_var.get().replace(",", "."))
        except ValueError:
            messagebox.showerror(APP_NAME, "Noch kein Standort festgelegt – bitte im Tab „Standort“ ermitteln oder eingeben.")
            return
        for d in self.targets(force_group):
            self.bg(self.send_time_location, d, (lat, lon))

    def do_state(self):
        def show(r):
            self.state_txt.delete("1.0", "end")
            self.state_txt.insert("end", json.dumps(r.get("result", r), indent=2, ensure_ascii=False))
        self.rpc("get_device_state", None, show)

    # ---- Bewegung ---------------------------------------------------------
    def move(self, angle, stop=False):
        if stop:
            self.rpc("scope_speed_move", {"speed": 0, "angle": 0, "dur_sec": 1})
        else:
            self.rpc("scope_speed_move", {"speed": int(self.speed_var.get()), "angle": angle,
                                          "dur_sec": int(self.dur_var.get())})

    def _key_move(self, e, ang, stop=False):
        if isinstance(e.widget, (tk.Entry, ttk.Entry, tk.Text, ttk.Combobox, ttk.Spinbox)):
            return
        self.move(ang, stop)

    def do_park(self):
        if messagebox.askyesno(APP_NAME, "Seestar parken und Arm schließen?"):
            self.rpc("scope_park")

    def do_shutdown(self):
        if messagebox.askyesno(APP_NAME, "Seestar wirklich herunterfahren?"):
            self.rpc("pi_shutdown")

    # ---- Fokus ändern, während das Seestar stackt (wie in der Seestar-App) ----------
    def focus_pause(self, devs, what="Fokus ändern"):
        """Vor einer Fokusänderung: stackende Geräte kurz anhalten. Gibt die Geräte zurück (None = abgebrochen)."""
        stacking = [d for d in devs if d.is_stacking]
        if stacking:
            names = ", ".join(d.name for d in stacking)
            ans = messagebox.askyesnocancel(
                APP_NAME, f"Auf {names} läuft gerade das Stacking.\n\n„{what}“ – dafür wird das Stacking kurz "
                          "angehalten. Wie soll es danach weitergehen?\n\nJa = weitermachen (gleicher Stack)\n"
                          "Nein = neu starten (neuer Stack)\nAbbrechen = Fokus nicht ändern")
            if ans is None:
                return None
            for d in stacking:
                d.focus_hold = "continue" if ans else "restart"
                d._last_stack_ev = None
                self.bg(d.wifi.send, "iscope_stop_view", {"stage": "Stack"})
                d.log("Stacking für die Fokusänderung angehalten.", "warn")
        return devs

    def focus_resume_later(self, d, delay=8000):
        """Nach der letzten Fokusänderung kurz warten, dann das Stacking wieder aufnehmen."""
        if d.focus_hold is None:
            return
        if d._hold_timer:
            try:
                self.after_cancel(d._hold_timer)
            except Exception:
                pass
        d._hold_timer = self.after(delay, lambda: self._focus_resume(d))

    def _focus_resume(self, d):
        mode, d.focus_hold, d._hold_timer = d.focus_hold, None, None
        if not mode or not d.connected:
            return
        self.bg(d.wifi.send, "iscope_start_stack", {"restart": mode == "restart"})
        d.log("Stacking fortgesetzt (gleicher Stack)." if mode == "continue" else "Stacking neu gestartet (neuer Stack).",
              "ok")

    def refocus_cfg(self):
        mins, dt = REFOCUS_OPTIONS.get(self.rf_var.get(), (0, 0))
        return {"min": mins, "dtemp": dt}

    def _rf_changed(self, _e=None):
        self.cfg["refocus"] = self.rf_var.get()
        save_config(self.cfg)

    def _rf_combo(self, parent):
        if not hasattr(self, "rf_var"):
            v = self.cfg.get("refocus", REFOCUS_DEFAULT)
            self.rf_var = tk.StringVar(value=v if v in REFOCUS_OPTIONS else REFOCUS_DEFAULT)
        cb = ttk.Combobox(parent, textvariable=self.rf_var, values=list(REFOCUS_OPTIONS), state="readonly", width=26)
        cb.bind("<<ComboboxSelected>>", self._rf_changed)
        return cb

    def manual_autofocus(self, force_group=False):
        """Seestar-Autofokus per Knopf – bei laufendem Stacking mit Nachfrage wie in der Seestar-App."""
        devs = self.focus_pause(self.targets(force_group), "Autofokus")
        if not devs:
            if devs is not None:
                self.log("Kein verbundenes Zielgerät (Übersicht prüfen).", "warn")
            return
        for d in devs:
            def job(d=d):
                since = time.time()
                d.wifi.send("start_auto_focuse")
                d.wait_event(("AutoFocus",), timeout=240, since=since)
                self.ui(self.focus_resume_later, d, 1500)
            self.bg(job)

    def focus_step(self, delta):
        devs = self.focus_pause(self.targets())
        if devs is None:
            return
        for d in devs:
            def job(d=d):
                r = d.wifi.send("get_focuser_position")
                if not r or "result" not in r:
                    return
                d.focus_pos = r["result"]
                r2 = d.wifi.send("move_focuser", {"step": r["result"] + delta, "ret_step": True})
                if isinstance(_g(r2 or {}, "result.step"), (int, float)):
                    d.focus_pos = int(r2["result"]["step"])
                time.sleep(1.5)
                r3 = d.wifi.send("get_focuser_position", quiet=True)
                if r3 and isinstance(r3.get("result"), (int, float)):
                    d.focus_pos = int(r3["result"])
                self.ui(self.show_focus_pos)
                self.ui(self.focus_resume_later, d)
            self.bg(job)

    # ---- GoTo -------------------------------------------------------------
    def _obj_combo(self, parent, var, width, on_pick):
        """Objektauswahl mit Suche über den ganzen Katalog (inkl. Siril-Erweiterung): tippen filtert die Liste,
        Enter oder Auswahl übernimmt."""
        cb = ttk.Combobox(parent, textvariable=var, width=width)
        cb.configure(values=[obj_label(o) for o in self.objects[:300]])

        def typed(e):
            if e.keysym in ("Return", "KP_Enter", "Up", "Down", "Escape", "Tab"):
                return
            cb.configure(values=[obj_label(o) for o in obj_search(self.objects_all, var.get())])
        cb.bind("<KeyRelease>", typed)
        cb.bind("<<ComboboxSelected>>", on_pick)
        cb.bind("<Return>", on_pick)
        cb.bind("<KP_Enter>", on_pick)
        return cb

    def _obj_from_text(self, text):
        t = (text or "").strip()
        if not t:
            return None
        for o in self.objects_all:
            if obj_label(o) == t:
                return o
        hits = obj_search(self.objects_all, t.split(" – ")[0], limit=1)
        return hits[0] if hits else None

    def pick_catalog(self, _e=None):
        o = self._obj_from_text(self.cat_var.get())
        if not o:
            return
        self.cat_var.set(obj_label(o))
        self.tname_var.set(o[0])
        self.ra_var.set(f"{o[4]:.4f}")
        self.dec_var.set(f"{o[5]:.3f}")

    def _coords(self):
        try:
            return parse_ra(self.ra_var.get()), parse_dec(self.dec_var.get())
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Koordinaten ungültig: {e}")
            return None

    def do_goto(self, force_group=False):
        c = self._coords()
        if not c:
            return
        name = self.tname_var.get().strip() or "Ziel"
        rn, dn = precess_j2000(c[0], c[1])
        self.rpc("iscope_start_view", {"mode": "star", "target_ra_dec": [rn, dn],
                                       "target_name": name, "lp_filter": bool(self.active and self.active.values.get("lp"))},
                 force_group=force_group)

    def do_slew(self):
        c = self._coords()
        if c:
            rn, dn = precess_j2000(c[0], c[1])
            self.rpc("scope_goto", {"ra": rn, "dec": dn})

    def do_pos(self):
        def show(r):
            res = r.get("result", {})
            if isinstance(res, dict) and "ra" in res:
                ra, dec = res["ra"], res["dec"]
                h, m = int(ra), (ra - int(ra)) * 60
                sgn = "-" if dec < 0 else "+"
                d, dm = int(abs(dec)), (abs(dec) - int(abs(dec))) * 60
                self.pos_var.set(f"RA {h:02d}h{m:05.2f}m  /  Dec {sgn}{d:02d}°{dm:05.2f}'")
        self.rpc("scope_get_equ_coord", None, show)

    # ---- Modell & Einstellungen ------------------------------------------
    def set_model(self, key, user=False):
        if key not in MODELS:
            return
        self.model = key
        self.model_var.set(MODELS[key]["label"])
        if user and self.active:
            self.active.model = key
            self.refresh_overview()
            for p in self.active.settings_panels:
                p.refresh()
        self.cfg["model"] = key
        save_config(self.cfg)
        if hasattr(self, "mz_canvas"):
            self.draw_mosaic()
        if user:
            self.log(f"Modell auf {MODELS[key]['label']} gesetzt.", "ok")

    # ---- Vorschau -------------------------------------------------------
    # ---- Mosaik -------------------------------------------------------------
    def _mz_pick(self, _e=None):
        o = self._obj_from_text(self.mz_cat.get())
        if not o:
            return
        self.mz_cat.set(obj_label(o))
        self.mz_name.set(o[0])
        self.mz_ra.set(f"{o[4]:.4f}")
        self.mz_dec.set(f"{o[5]:.3f}")

    def _mz_from_control(self):
        self.mz_ra.set(self.ra_var.get())
        self.mz_dec.set(self.dec_var.get())
        if self.tname_var.get().strip():
            self.mz_name.set(self.tname_var.get().strip())

    @staticmethod
    def _num(text):
        return float(re.sub(r"[^0-9,.\-]", "", text).replace(",", "."))

    def _mz_plan(self):
        try:
            ra, dec = parse_ra(self.mz_ra.get()), parse_dec(self.mz_dec.get())
        except Exception:
            return None
        lp = {"An": True, "Aus": False}.get(self.mz_lp.get())
        name = re.sub(r"[^\w\- ]+", "", self.mz_name.get().strip()) or "Mosaik"
        if self.mz_mode.get() == "frame":
            return {"mode": "frame", "name": name, "ra": ra, "dec": dec, "lp": lp,
                    "scale": self._num(self.mz_scale.get()), "angle": self._num(self.mz_angle.get()),
                    "total_min": int(self._num(self.mz_total.get()))}
        return {"mode": "grid", "name": name, "ra": ra, "dec": dec, "lp": lp,
                "cols": int(self.mz_cols.get()), "rows": int(self.mz_rows.get()),
                "overlap": self._num(self.mz_ov.get()), "panel_min": int(self._num(self.mz_pt.get())),
                "af": bool(self.mz_af.get()), "af_mode": "auto"}

    def draw_mosaic(self):
        c = getattr(self, "mz_canvas", None)
        if c is None:
            return
        c.delete("all")
        W, H = max(50, c.winfo_width()), max(50, c.winfo_height())
        model = (self.active.model if self.active and self.active.model else self.model)
        m = MODELS[model]
        plan = self._mz_plan()
        if not plan:
            self.mz_info.set("RA/Dec eingeben oder Ziel aus dem Katalog wählen.")
            c.create_text(W // 2, H // 2, text="Kein gültiges Ziel", fill=C["dim"])
            return
        fw, fh = m["fov_w"], m["fov_h"]
        if plan["mode"] == "frame":
            sc = plan["scale"]
            tw, th = fw * sc, fh * sc
            rects = [(0.0, 0.0, tw, th, "")]
            info = (f"{m['label']}: Framing {sc:g}× → ca. {tw:.2f}° × {th:.2f}° · Drehung {plan['angle']:g}° · "
                    f"{plan['total_min']} min")
            ang = plan["angle"]
        else:
            ov = plan["overlap"] / 100
            sx, sy = fw * (1 - ov), fh * (1 - ov)
            rects = []
            k = 0
            for j in range(plan["rows"]):
                order = range(plan["cols"]) if j % 2 == 0 else range(plan["cols"] - 1, -1, -1)
                for i in order:
                    k += 1
                    cx = ((plan["cols"] - 1) / 2 - i) * sx
                    cy = ((plan["rows"] - 1) / 2 - j) * sy
                    rects.append((cx, cy, fw, fh, str(k)))
            tw = fw + sx * (plan["cols"] - 1)
            th = fh + sy * (plan["rows"] - 1)
            n = plan["cols"] * plan["rows"]
            tot = n * plan["panel_min"]
            info = (f"{m['label']}: {plan['cols']}×{plan['rows']} = {n} Panels → ca. {tw:.2f}° × {th:.2f}° · "
                    f"Gesamt {tot // 60} h {tot % 60:02d} min (+ GoTo/AF)")
            ang = 0
        self.mz_info.set(info)
        ca0, sa0 = abs(math.cos(math.radians(ang))), abs(math.sin(math.radians(ang)))
        bw, bh = tw * ca0 + th * sa0, tw * sa0 + th * ca0          # Hülle des gedrehten Rahmens
        scale = min((W - 40) / max(bw, 0.1), (H - 40) / max(bh, 0.1))
        ox, oy = W / 2, H / 2
        ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        for (cx, cy, w, h, lab) in rects:
            pts = []
            for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
                x, y = cx + dx, cy + dy
                xr, yr = x * ca - y * sa, x * sa + y * ca
                pts += [ox - xr * scale, oy - yr * scale]   # Osten links, Norden oben
            c.create_polygon(*pts, outline=C["accent"], fill="", width=2)
            if lab:
                c.create_text(ox - cx * scale, oy - cy * scale, text=lab, fill=C["fg"], font=("Segoe UI", 10, "bold"))
        c.create_text(14, 12, text="N ↑   O ←", fill=C["dim"], anchor="w")

    def start_mosaic(self, force_group=False):
        plan = self._mz_plan()
        if not plan:
            messagebox.showerror(APP_NAME, "Bitte gültige Koordinaten für den Mittelpunkt eingeben.")
            return
        devs = self.targets(force_group)
        if not devs:
            self.log("Kein verbundenes Zielgerät für das Mosaik.", "warn")
            return
        busy = [d.name for d in devs if d.job]
        if busy:
            messagebox.showinfo(APP_NAME, "Läuft bereits auf: " + ", ".join(busy))
            devs = [d for d in devs if not d.job]
        for d in devs:
            self._resume_asked.add(d.host)
            steps = mosaic_steps(plan, d.model)            # jedes Gerät mit seinem eigenen Bildfeld
            art = "Framing" if plan["mode"] == "frame" else f"Mosaik {plan['cols']}×{plan['rows']}"
            PlanJob(d, {"name": f"{plan['name']} ({art})", "kind": "mosaic", "steps": steps, "end": "open",
                        "refocus": self.refocus_cfg()}).start()
        self.refresh_overview()

    # ---- Standby nur während eines Mosaiks sperren ---------------------------
    def _mosaic_running(self):
        return [d.name for d in self.devices
                if d.job and not d.job.cancelled and d.job.plan.get("kind") == "mosaic"]

    HINTS = {
        "mosaic": ("So liest du die Mosaik-Zeichnung",
                   "Jedes Rechteck ist ein Feld (Panel), das das Seestar nacheinander aufnimmt – die Zahl ist die "
                   "Reihenfolge.\n\nDie schmalen Streifen zwischen den Feldern sind die Überlappung (links unter "
                   "„Raster“ einstellbar, üblich 15–20 %). Diese Bereiche nehmen zwei Felder auf, damit Siril oder ein anderes "
                   "Programm die Bilder später nahtlos zusammensetzen kann. Das kleine Kästchen in der Mitte nehmen alle "
                   "angrenzenden Felder auf.\n\nRaster-Mosaik = einzelne Felder nacheinander (größer, mehr Kontrolle). "
                   "Framing-Mosaik = das Seestar macht es selbst in einem einzigen Stack."),
        "asiair": ("ASIAIR – bitte zuerst lesen",
                   "Diese Seite steuert ein ZWO ASIAIR (Mini, Plus, Pro oder eine Kamera mit eingebautem Air wie die "
                   "ASI585MC Air) samt Montierung: GoTo mit Plate Solve, Guiding, Aufnahmeserien und ein automatischer "
                   "Meridian-Flip während des Plans.\n\nWichtig: Die Funktion beruht auf der öffentlichen "
                   "Community-Dokumentation des ASIAIR-Protokolls und ist noch nicht an einem echten Gerät getestet. "
                   "Bitte den Flip zuerst am Abend mit „Meridian-Flip jetzt testen“ beobachten.\n\nFür die Kamera-Befehle "
                   "braucht das Air einen eigenen Schlüssel (PEM) aus der ASIAIR-App – nicht den Seestar-Schlüssel.\n\n"
                   "So läuft der Flip: laufende Belichtung beenden → Guiding stoppen → GoTo mit Plate Solve auf dasselbe "
                   "Ziel (die Montierung wechselt dabei die Seite) → Guiding neu starten → Serie mit den restlichen Bildern "
                   "fortsetzen. Nur für parallaktische Montierungen (z. B. AM5 im EQ-Modus). Den eigenen Autorun-Flip der "
                   "ASIAIR-App dabei nicht zusätzlich einschalten."),
    }

    def _tab_hint(self):
        try:
            idx = self.nb.index(self.nb.select())
            key = self.TAB_KEYS[idx] if idx < len(self.TAB_KEYS) else None
        except Exception:
            return
        if key in self.HINTS and key not in self.cfg.get("hints_seen", []):
            self.show_hint(key)

    def show_hint(self, key):
        title, text = self.HINTS[key]
        win = self.make_window(title, minsize=(420, 260))
        ttk.Label(win, text=text, wraplength=520, justify="left").pack(padx=18, pady=(16, 10), anchor="w")
        never = tk.BooleanVar(value=True)
        ttk.Checkbutton(win, text="Nicht wieder anzeigen", variable=never).pack(padx=18, anchor="w")

        def close():
            if never.get():
                seen = self.cfg.setdefault("hints_seen", [])
                if key not in seen:
                    seen.append(key)
                    save_config(self.cfg)
            win.destroy()
        ttk.Button(win, text="Verstanden", style="Accent.TButton", command=close).pack(padx=18, pady=12, anchor="e")
        win.protocol("WM_DELETE_WINDOW", close)
        win.transient(self)
        try:                                                    # mittig über dem Hauptfenster
            win.update_idletasks()
            x = self.winfo_rootx() + (self.winfo_width() - win.winfo_reqwidth()) // 2
            y = self.winfo_rooty() + (self.winfo_height() - win.winfo_reqheight()) // 3
            win.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def hints_reset(self):
        self.cfg["hints_seen"] = []
        save_config(self.cfg)
        self.log("Hinweise werden wieder angezeigt, wenn du die jeweilige Seite öffnest.", "ok")

    def _settings_poll(self):
        """Alle 30 s Einstellungen nachlesen, solange sie sichtbar sind – Änderungen in der Handy-App melden sich
        bei manchen Firmware-Ständen nicht per Ereignis."""
        try:
            idx = self.nb.index(self.nb.select())
            tab = self.TAB_KEYS[idx] if idx < len(self.TAB_KEYS) else None
            for d in self.devices:
                popup = d.settings_popup is not None and d.settings_popup.winfo_exists()
                if d.connected and not d.job and (popup or (tab == "settings" and d is self.active)):
                    self.bg(d.refresh_settings)
        except Exception:
            pass
        self.after(30000, self._settings_poll)

    def _standby_tick(self):
        try:
            running = self._mosaic_running()
            air = bool(getattr(self, "air_job", None) and self.air_job.alive())
            if air:
                running = list(running) + ["ASIAIR"]
            want = (bool(running) and bool(self.mz_nosleep.get())) or air
            was = self.standby.active
            ok = self.standby.set(want)
            if want and not was:
                if ok and running == ["ASIAIR"]:
                    self.log("Standby von PC/Laptop gesperrt, solange der ASIAIR-Plan läuft.", "ok")
                elif ok:
                    self.log(f"Standby von PC/Laptop gesperrt, solange das Mosaik läuft ({', '.join(running)}).", "ok")
                else:
                    self.log(f"Standby konnte nicht gesperrt werden: {self.standby.error}", "warn")
            elif was and not want:
                self.log("Ablauf beendet – PC/Laptop darf wieder in den Standby.", "info")
            if self.standby.active:
                self.mz_sleep_txt.set(f"● Standby gesperrt – Mosaik läuft auf: {', '.join(running)}")
            elif running and not self.mz_nosleep.get():
                self.mz_sleep_txt.set("Mosaik läuft – Standby ist erlaubt (Häkchen aus).")
            elif want and not ok:
                self.mz_sleep_txt.set(f"Standby-Sperre nicht möglich: {self.standby.error}")
            else:
                self.mz_sleep_txt.set("Nur während eines Mosaiks. Laptop aufgeklappt und am Netzteil lassen.")
        except Exception:
            pass
        self.after(5000, self._standby_tick)

    def cancel_mosaic(self):
        devs = self.group() if self.target_var.get() == "group" else ([self.active] if self.active else [])
        for d in devs:
            if d.job:
                d.job.cancel()
                d.log("Mosaik wird abgebrochen …", "warn")
            elif d.host in self.cfg.get("jobs", {}):
                self.save_job(d.host, None)
                d.log("Pausiertes Mosaik verworfen.", "warn")
                if d.connected:
                    self.bg(d.wifi.send, "iscope_stop_view", {"stage": "Stack"})
        self.refresh_overview()

    # ---- Mosaik-Stände speichern / fortsetzen ------------------------------
    def save_job(self, host, data):
        with self._cfg_lock:
            jobs = self.cfg.setdefault("jobs", {})
            if data is None:
                jobs.pop(host, None)
            else:
                jobs[host] = data
            save_config(self.cfg)

    def _paused_text(self, d):
        j = self.cfg.get("jobs", {}).get(d.host)
        if not j or d.job or "steps" not in j.get("plan", {}):
            return ""
        n = len(j["plan"]["steps"]) or 1
        return f"⏸ pausiert: {j['plan'].get('name', 'Plan')} – Schritt {min(j['k'] + 1, n)}/{n}"

    def offer_resume(self, d):
        j = self.cfg.get("jobs", {}).get(d.host)
        if not j or d.job or not d.connected or d.host in self._resume_asked:
            return
        if "steps" not in j.get("plan", {}):                # unbrauchbarer Speicherstand
            self.save_job(d.host, None)
            return
        self._resume_asked.add(d.host)
        plan = j["plan"]
        n = len(plan["steps"]) or 1
        k = j.get("k", 0)
        if k >= n:
            self.save_job(d.host, None)
            return
        msg = (f"Für „{d.name}“ ist „{plan.get('name', 'Plan')}“ offen (Schritt {k + 1} von {n}).\n\n"
               "Fortsetzen? Bei „Nein“ wird der gespeicherte Stand verworfen.")
        if messagebox.askyesno(APP_NAME, msg):
            PlanJob(d, plan, start_index=k, resume_deadline=j.get("deadline")).start()
            d.log(f"Ablauf wird bei Schritt {k + 1}/{n} fortgesetzt.", "ok")
        else:
            self.save_job(d.host, None)
            d.log("Gespeicherter Ablauf verworfen – das Seestar wird angehalten (Zielsuche/Stacking des Ablaufs).", "warn")

            def halt():                      # sonst sucht das Seestar das letzte Ziel von sich aus weiter
                d.wifi.send("iscope_stop_view", quiet=True)
                d.wifi.send("scope_abort_slew", quiet=True)
            self.bg(halt)
        self.refresh_overview()

    # ---- Standort -------------------------------------------------------------
    def set_location(self, lat, lon, source, acc_m=None, place=""):
        """Zentrale Stelle: Position übernehmen, speichern, überall bekannt machen."""
        self.lat_var.set(f"{lat:.5f}")
        self.lon_var.set(f"{lon:.5f}")
        self.site_cache = (lat, lon)
        self.cfg.update(lat=round(lat, 5), lon=round(lon, 5), loc_src=source, loc_acc_m=acc_m,
                        loc_place=place, loc_time=time.time())
        save_config(self.cfg)
        self.loc_refresh_ui()
        self._season_cache = None
        if hasattr(self, "obj_tree"):
            self.obj_fill()
        if hasattr(self, "rec_tree"):
            self.rec_compute()
        if hasattr(self, "lvl_canvas"):
            self.eq_draw()
        if hasattr(self, "wx_canvas"):
            if self.cfg.get("wx_consent") is True:
                self.wx_refresh(quiet=True)
            else:
                self.wx_update_all()

    def loc_refresh_ui(self):
        if not hasattr(self, "loc_big"):
            return
        site = self._site()
        names = {"windows": "Windows-Standortdienst", "seestar": "Seestar", "internet": "Internet (IP, ungefähr)",
                 "manuell": "manuell eingegeben"}
        if site:
            la, lo = site
            self.loc_big.set(f"Breite  {la:+.5f}°   ({fmt_dms(la, True)})\nLänge   {lo:+.5f}°   ({fmt_dms(lo, False)})")
            meta = f"Quelle: {names.get(self.cfg.get('loc_src'), 'unbekannt')}"
            if self.cfg.get("loc_acc_m"):
                a = self.cfg["loc_acc_m"]
                meta += f" · Genauigkeit ca. {a / 1000:.0f} km" if a >= 1000 else f" · Genauigkeit ca. {a:.0f} m"
            if self.cfg.get("loc_place"):
                meta += f" · {self.cfg['loc_place']}"
            if self.cfg.get("loc_time"):
                meta += f" · Stand {datetime.fromtimestamp(self.cfg['loc_time']):%d.%m.%Y %H:%M}"
            self.loc_meta.set(meta + f"\nZeitzone für das Seestar: {local_timezone_name()}")
            self.loc_short.set(f"Standort: {la:.3f}° / {lo:.3f}°" + (f" ({self.cfg['loc_place']})" if self.cfg.get("loc_place") else ""))
        else:
            self.loc_big.set("Noch kein Standort festgelegt.")
            self.loc_meta.set("Automatisch ermitteln lassen oder unten manuell eingeben.")
            self.loc_short.set("Standort: noch nicht festgelegt")
        c = self.cfg.get("loc_consent")
        auto = c is True
        self.loc_auto.set(auto)
        self.loc_consent_txt.set(
            f"Einverständnis erteilt am {datetime.fromtimestamp(self.cfg.get('loc_consent_time', 0)):%d.%m.%Y}. "
            "Häkchen entfernen, um es zu widerrufen." if auto else
            ("Einverständnis widerrufen – Position wird nur noch manuell festgelegt." if c is False else
             "Noch nicht gefragt. Häkchen setzen, um die automatische Ermittlung zu erlauben."))
        self.loc_now_btn.state(["!disabled"] if auto else ["disabled"])
        for cb in self.loc_src_cbs:
            cb.state(["!disabled"] if auto else ["disabled"])
        for e in (self.loc_lat_e, self.loc_lon_e, self.loc_place_e):
            e.state(["disabled"] if auto else ["!disabled"])
        self.loc_man_btn.state(["disabled"] if auto else ["!disabled"])
        self.loc_man_note.set("Automatische Ermittlung ist an – zum manuellen Eingeben oben das Häkchen entfernen."
                              if auto else "")
        if not auto and site and not self.loc_lat_e.get() and not self.loc_lon_e.get():
            self.loc_lat_e.insert(0, f"{site[0]:.5f}".replace(".", ","))
            self.loc_lon_e.insert(0, f"{site[1]:.5f}".replace(".", ","))
            if self.cfg.get("loc_place"):
                self.loc_place_e.insert(0, self.cfg["loc_place"])

    def _loc_save_sources(self):
        self.cfg["loc_sources"] = {k: bool(v.get()) for k, v in self.loc_src_vars.items()}
        save_config(self.cfg)

    def ask_location_consent(self, then=None):
        """Einmalige Abfrage des Einverständnisses. then(bool) wird danach aufgerufen."""
        win = self.make_window("Standort automatisch ermitteln?")
        win.transient(self)
        frm = ttk.Frame(win, padding=16)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=f"Darf {APP_NAME} deinen Standort automatisch ermitteln?",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(frm, text="Der Standort wird nur auf diesem PC gespeichert und an deine eigenen Seestar-Geräte "
                            "gesendet (für Uhrzeit, Nachführung und Objekthöhen). Wähle, welche Quellen genutzt werden "
                            "dürfen. Du kannst das jederzeit im Tab „Standort“ widerrufen und die Position stattdessen "
                            "von Hand eingeben.", wraplength=560, justify="left", foreground=C["muted2"]).pack(anchor="w", pady=(6, 10))
        vars_ = {}
        for key, (title, desc) in LOC_SOURCES.items():
            v = tk.BooleanVar(value=key != "internet")
            vars_[key] = v
            ttk.Checkbutton(frm, text=title, variable=v).pack(anchor="w")
            ttk.Label(frm, text=desc, foreground=C["muted"], wraplength=530, justify="left").pack(anchor="w", padx=(22, 0), pady=(0, 6))
        bt = ttk.Frame(frm)
        bt.pack(fill="x", pady=(8, 0))

        def decide(ok):
            self.cfg["loc_consent"] = ok
            self.cfg["loc_consent_time"] = time.time()
            if ok:
                self.cfg["loc_sources"] = {k: bool(v.get()) for k, v in vars_.items()}
                for k, v in vars_.items():
                    self.loc_src_vars[k].set(v.get())
            save_config(self.cfg)
            win.destroy()
            self.loc_refresh_ui()
            if ok:
                self.loc_locate()
            elif then is None:
                self.nb.select(self._tab_index("Standort"))
            if then:
                then(ok)

        ttk.Button(bt, text="Erlauben", style="Accent.TButton", command=lambda: decide(True)).pack(side="right")
        ttk.Button(bt, text="Nein – ich gebe ihn selbst ein", command=lambda: decide(False)).pack(side="right", padx=6)
        win.protocol("WM_DELETE_WINDOW", lambda: (win.destroy(), then and then(None)))
        win.grab_set()

    def loc_toggle_consent(self):
        if self.loc_auto.get():
            self.loc_auto.set(False)
            self.ask_location_consent()                 # bewusstes Einverständnis inkl. Quellenauswahl
            return
        keep = messagebox.askyesno(APP_NAME, "Einverständnis widerrufen.\n\nDie zuletzt ermittelte Position behalten "
                                             "(als manuelle Eingabe)?\n„Nein“ löscht sie.")
        self.cfg["loc_consent"] = False
        self.cfg["loc_consent_time"] = time.time()
        if keep:
            self.cfg["loc_src"] = "manuell"
        else:
            for k in ("lat", "lon", "loc_src", "loc_acc_m", "loc_place", "loc_time"):
                self.cfg.pop(k, None)
            self.lat_var.set("")
            self.lon_var.set("")
            self.site_cache = None
            for e in (self.loc_lat_e, self.loc_lon_e, self.loc_place_e):
                e.state(["!disabled"])
                e.delete(0, "end")
        save_config(self.cfg)
        self.loc_status.set("Automatische Ermittlung ist aus.")
        self.loc_refresh_ui()
        self.loc_lat_e.focus_set()

    def loc_locate(self, quiet=False):
        """Quellen der Reihe nach probieren: Windows → Seestar → Internet (nur die erlaubten)."""
        if self.cfg.get("loc_consent") is not True:
            return
        srcs = {k: v.get() for k, v in self.loc_src_vars.items()}
        dev = next((d for d in ([self.active] if self.active else []) + self.devices if d and d.connected), None)
        self.loc_status.set("Ermittle Standort …")

        def job():
            errors = []
            if srcs.get("windows"):
                r, err = locate_windows()
                if r:
                    self.ui(self._loc_candidate, r["lat"], r["lon"], "windows", r.get("acc_m"), "", quiet)
                    self.ui(self.loc_status.set, "Standort vom Windows-Standortdienst übernommen.")
                    return
                errors.append(err)
            if srcs.get("seestar"):
                if dev:
                    rr = dev.wifi.send("get_device_state", {"keys": ["location_lon_lat"]}, quiet=True)
                    ll = _g(rr or {}, "result.location_lon_lat")
                    if isinstance(ll, (list, tuple)) and len(ll) == 2 and not (ll[0] == 0 and ll[1] == 0):
                        self.ui(self._loc_candidate, float(ll[1]), float(ll[0]), "seestar", None, "", quiet)
                        self.ui(self.loc_status.set, f"Standort aus „{dev.name}“ übernommen.")
                        return
                    errors.append(f"„{dev.name}“ hat keinen Standort gespeichert")
                else:
                    errors.append("kein Seestar verbunden")
            if srcs.get("internet"):
                r, err = locate_internet()
                if r:
                    self.ui(self._loc_candidate, r["lat"], r["lon"], "internet", r.get("acc_m"), r.get("place", ""), quiet)
                    self.ui(self.loc_status.set, "Ungefährer Standort über die Internet-Adresse übernommen.")
                    return
                errors.append(err)
            if not any(srcs.values()):
                errors.append("keine Quelle ausgewählt")
            reasons = "; ".join(tr(e) for e in errors)
            msg = f"Standort konnte nicht ermittelt werden: {reasons}"
            self.ui(self.loc_status.set, f"Standort konnte nicht ermittelt werden: {reasons}. Du kannst ihn auch "
                                         "manuell eingeben (Häkchen oben entfernen).")
            if not quiet:
                self.log(msg, "warn")
        self.bg(job)

    @staticmethod
    def dist_km(a, b):
        la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
        h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
        return 6371 * 2 * math.asin(min(1, math.sqrt(h)))

    def check_moved(self, d):
        """Meldet das Seestar (Standort von der Handy-App) einen Ort weit weg vom eingestellten? Dann fragen.
        True = Frage läuft, Zeit/Standort noch nicht senden."""
        site, sl = self._site(), getattr(d, "seestar_loc", None)
        if not site or not sl or getattr(self, "_moved_asked", False):
            return False
        km = self.dist_km(site, sl)
        if km < 20:
            return False
        self._moved_asked = True

        def ask():
            if messagebox.askyesno(APP_NAME, f"„{d.name}“ meldet einen Standort etwa {km:.0f} km von deinem eingestellten "
                                             f"Standort entfernt (meist von der Seestar-App auf dem Handy).\n\n"
                                             f"Bist du gerade woanders? Dann diesen Standort übernehmen – Objektlisten, "
                                             f"Wetter und Empfehlungen werden für den neuen Ort berechnet."):
                self.set_location(sl[0], sl[1], "seestar", None)
                self.log(f"Neuer Standort übernommen ({km:.0f} km vom alten) – alles wird für den neuen Ort berechnet.", "ok")
            if self.cfg.get("auto_init", True) and not d.job:
                self.bg(self.send_time_location, d, self._site(), True)
        self.after(500, ask)
        return True

    def _loc_candidate(self, lat, lon, source, acc_m=None, place="", quiet=False):
        """Automatisch ermittelter Standort: bei großem Sprung (Reise) erst fragen."""
        site = self._site()
        if quiet and site and self.dist_km(site, (lat, lon)) >= 20:
            km = self.dist_km(site, (lat, lon))
            if not messagebox.askyesno(APP_NAME, f"Der automatisch ermittelte Standort liegt etwa {km:.0f} km von deinem "
                                                 f"eingestellten Standort entfernt.\n\nNeuen Standort übernehmen?"):
                return
        elif site and self.dist_km(site, (lat, lon)) >= 20:
            self.log(f"Neuer Standort ({self.dist_km(site, (lat, lon)):.0f} km vom alten) – Objektlisten, Wetter und "
                     f"Empfehlungen werden für den neuen Ort berechnet.", "ok")
        self.set_location(lat, lon, source, acc_m, place)

    def loc_manual_apply(self):
        try:
            la = parse_coord(self.loc_lat_e.get(), True)
            lo = parse_coord(self.loc_lon_e.get(), False)
        except ValueError as e:
            messagebox.showerror(APP_NAME, f"Ungültige Eingabe: {e}.\nBeispiele: 52,52 / 13,40 oder 52°31'12\" N / 13°24' O")
            return
        self.set_location(la, lo, "manuell", None, self.loc_place_e.get().strip())
        self.loc_status.set("")
        self.log(f"Standort manuell festgelegt: {la:.5f}° / {lo:.5f}°.", "ok")

    # ---- Objekte & GoTo -----------------------------------------------------
    def _site(self):
        try:
            lat = float(str(self.lat_var.get()).replace(",", "."))
            lon = float(str(self.lon_var.get()).replace(",", "."))
            return lat, lon
        except (ValueError, AttributeError):
            if self.cfg.get("lat") not in (None, "") and self.cfg.get("lon") not in (None, ""):
                return float(self.cfg["lat"]), float(self.cfg["lon"])
        return None

    def _obj_tick(self):
        self.site_cache = self._site()
        self.obj_fill()
        self.after(60000, self._obj_tick)

    def _season(self, site):
        """Jahreszeiten-Tabelle für den Standort – einmal im Hintergrund rechnen, dann aus dem Zwischenspeicher."""
        key = (round(site[0], 1), round(site[1], 1), datetime.now().year)
        c = getattr(self, "_season_cache", None)
        if c and c[0] == key:
            return c[1]
        if not getattr(self, "_season_busy", False):
            self._season_busy = True
            objs = list(self.objects)

            def job():
                try:
                    tab = season_table(objs, site[0], site[1], 30)
                    self._season_cache = (key, tab)
                finally:
                    self._season_busy = False
                self.ui(self.obj_fill)
            self.bg(job)
        return None

    def _obj_season_toggle(self):
        self.cfg["obj_season"] = bool(self.obj_season.get())
        save_config(self.cfg)
        if self.obj_season.get():
            self._obj_sort = ("id", False)
        self.obj_fill()

    def _obj_sort_by(self, col):
        cur, rev = self._obj_sort
        self._obj_sort = (col, not rev if cur == col else col in ("alt", "size"))
        self.obj_fill()

    @staticmethod
    def _typ_match(t, sel):
        return {"Alle": True, "Galaxien": t.startswith("Galax"), "Nebel": "nebel" in t.lower() and "Planet" not in t,
                "Sternhaufen": "haufen" in t or "assoz" in t, "Planetarische Nebel": t.startswith("Planet"),
                "Supernovaüberreste": t.startswith("Supernova")}.get(sel, True)

    def _fit_text(self, size):
        m = MODELS.get(self.active.model if self.active and self.active.model else self.model)
        if not size:
            return "–"
        deg = size / 60
        if deg <= m["fov_w"] * 0.9:
            return "passt"
        if deg <= m["fov_h"] * 0.9:
            return "passt (hochkant)"
        n = math.ceil(deg / (m["fov_w"] * 0.8))
        return f"Mosaik ≈ {n}×{max(1, math.ceil(deg / (m['fov_h'] * 0.8)))}"

    def obj_fill(self):
        if not hasattr(self, "obj_tree"):
            return
        site = self._site()
        self.site_cache = site
        if site and (self.cfg.get("lat"), self.cfg.get("lon")) != site:
            self.cfg["lat"], self.cfg["lon"] = site
            save_config(self.cfg)
        q = self.obj_q.get().strip().lower().replace(" ", "")
        _m = re.search(r"(\d+)", self.obj_alt.get())
        minalt = int(_m.group(1)) if _m else None
        rows = []
        now = time.time()
        season = self._season(site) if site else None
        month = datetime.now().month - 1
        hidden = 0
        for o in (self.objects_all if q else self.objects):
            oid, name, alias, typ, ra, dec, mag, size = o
            if site and 90 - abs(site[0] - dec) < 10 and not q:
                hidden += 1                                   # steigt an diesem Ort nie über 10°
                continue
            if self.obj_season.get() and season is not None and not q:
                row = season.get(oid) or [0] * 12
                if row[month] < max(1.5, 0.6 * max(row)):
                    continue
            if q and q not in (oid + name + alias).lower().replace(" ", ""):
                continue
            if not self._typ_match(typ, self.obj_type.get()):
                continue
            if self.obj_named.get() and not name and not re.match(r"M\d+$", oid) and not q:
                continue
            alt = az = tt = talt = None
            if site:
                alt, az = alt_az(ra, dec, site[0], site[1], now)
                tt, talt = transit(ra, dec, site[0], site[1], now)
                if minalt is not None and alt < minalt and not q and not self.obj_season.get():
                    continue
            rows.append((o, alt, az, tt, talt))
        col, rev = self._obj_sort
        key = {"id": lambda r: r[0][0], "name": lambda r: (r[0][1] or "~"), "type": lambda r: r[0][3],
               "mag": lambda r: r[0][6] if r[0][6] is not None else 99, "size": lambda r: r[0][7] or 0,
               "alt": lambda r: r[1] if r[1] is not None else -99, "az": lambda r: r[2] or 0,
               "trans": lambda r: r[3] or 0, "fit": lambda r: r[0][7] or 0,
               "season": lambda r: (season or {}).get(r[0][0], [0] * 12)[month]}.get(col, lambda r: r[0][0])
        if self.obj_season.get() and season is not None and not q and col == "id":
            col, rev = "season", True
            key = lambda r: ((season.get(r[0][0], [0] * 12)[month]) * (1.4 if r[0][0] in SHOWPIECES else 1.0)
                             * (1.15 if (r[0][1] or re.match(r"M\d+$", r[0][0])) else 1.0))
        if col in ("id",) and not q:
            rows.sort(key=lambda r: (0 if r[0][0].startswith("M") else 1, int(re.sub(r"\D", "", r[0][0]) or 0)
                                     if r[0][0].startswith("M") else 0, r[0][0]), reverse=rev)
        else:
            rows.sort(key=key, reverse=rev)
        tree = self.obj_tree
        sel = tree.selection()
        tree.delete(*tree.get_children())
        dirs = ["N", "NO", "O", "SO", "S", "SW", "W", "NW"]
        for o, alt, az, tt, talt in rows[:400]:
            oid, name, alias, typ, ra, dec, mag, size = o
            vals = (oid, name, typ, f"{mag:.1f}" if mag is not None else "–", f"{size:g}′" if size else "–",
                    f"{alt:.0f}°" if alt is not None else "–",
                    dirs[int((az + 22.5) % 360 // 45)] if az is not None else "–",
                    f"{datetime.fromtimestamp(tt):%H:%M} ({talt:.0f}°)" if tt else "–",
                    best_months(season[oid]) if season and oid in season else "–", self._fit_text(size))
            tree.insert("", "end", iid=oid, values=vals, tags=("low",) if alt is not None and alt < 20 else ())
        if sel and tree.exists(sel[0]):
            tree.selection_set(sel[0])
        if not site:
            txt = f"{len(rows)} Objekte · Standort im Tab „Standort“ eintragen für Höhe/Kulmination"
        elif season is None:
            txt = f"{len(rows)} Objekte · berechne Jahreszeiten …"
        elif hidden:
            txt = f"{len(rows)} Objekte · {hidden} steigen hier nie über 10°"
        else:
            txt = f"{len(rows)} Objekte"
        self.obj_hint.set(txt)
        self.obj_hint2.set(f"{len(self.objects_extra)} weitere Objekte (Siril: NGC/IC, Sh2, LDN) über die Suche"
                           if self.objects_extra and not q else "")

    def _obj_sel(self):
        sel = self.obj_tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Bitte zuerst ein Objekt auswählen.")
            return None
        return next(o for o in self.objects_all if o[0] == sel[0])

    def _obj_detail(self):
        sel = self.obj_tree.selection()
        if not sel:
            return
        o = next(o for o in self.objects_all if o[0] == sel[0])
        oid, name, alias, typ, ra, dec, mag, size = o
        rn, dn = precess_j2000(ra, dec)
        txt = (f"{oid} {name} – {typ}" + (f" · auch: {alias}" if alias else "") +
               f"\nJ2000: RA {int(ra)}h{(ra % 1) * 60:05.2f}m  Dec {dec:+.3f}°   ·   heute (an das Seestar): "
               f"RA {int(rn)}h{(rn % 1) * 60:05.2f}m  Dec {dn:+.3f}°")
        site = self._site()
        if site:
            t_up = next_time_above(ra, dec, site[0], site[1], 30)
            alt_now = alt_az(ra, dec, site[0], site[1])[0]
            if alt_now >= 30:
                txt += f"   ·   jetzt {alt_now:.0f}° hoch"
            elif t_up:
                txt += f"   ·   über 30° ab {datetime.fromtimestamp(t_up):%H:%M}"
            else:
                txt += "   ·   erreicht heute keine 30°"
        self.obj_info.set(txt)

    def obj_goto(self, force_group=False, slew=False):
        o = self._obj_sel()
        if not o:
            return
        oid, name, alias, typ, ra, dec, mag, size = o
        site = self._site()
        if site and alt_az(ra, dec, site[0], site[1])[0] < 5:
            if not messagebox.askyesno(APP_NAME, f"{oid} steht gerade unter dem Horizont. Trotzdem anfahren?"):
                return
        rn, dn = precess_j2000(ra, dec)
        label = oid if not name else f"{oid} {name}"
        if slew:
            self.rpc("scope_goto", {"ra": rn, "dec": dn}, force_group=force_group)
        else:
            lp = bool(self.active and self.active.values.get("lp"))
            self.rpc("iscope_start_view", {"mode": "star", "target_ra_dec": [rn, dn], "target_name": label[:40],
                                           "lp_filter": lp}, force_group=force_group)
        self.log(f"GoTo {label} gesendet.", "ok")

    def obj_to_control(self):
        o = self._obj_sel()
        if o:
            self.tname_var.set(o[0])
            self.ra_var.set(f"{o[4]:.5f}")
            self.dec_var.set(f"{o[5]:.4f}")
            self.nb.select(self._tab_index("Steuerung"))

    def obj_to_mosaic(self):
        o = self._obj_sel()
        if o:
            self.mz_name.set(o[0].replace(" ", ""))
            self.mz_ra.set(f"{o[4]:.5f}")
            self.mz_dec.set(f"{o[5]:.4f}")
            self.nb.select(self._tab_index("Mosaik"))

    def obj_to_plan(self):
        o = self._obj_sel()
        if o and hasattr(self, "plan_add_target"):
            self.plan_add_target(o)
            self.nb.select(self._tab_index("Zeitpläne"))

    def _tab_index(self, title):
        for k, t in enumerate(getattr(self, "_tab_titles", [])):
            if title in t:
                return k
        for k in range(self.nb.index("end")):
            if title in self.nb.tab(k, "text"):
                return k
        return 0

    # ---- Zeitpläne -------------------------------------------------------------
    AF_MODES = {"automatisch": "auto", "Seestar-Autofokus": "seestar", "App-Autofokus (für Filter)": "app",
                "gemerkte Position": "saved", "kein Fokus": "none"}

    def _pl_af_text(self, mode):
        return next((k for k, v in self.AF_MODES.items() if v == mode), mode)

    def _pl_add(self, step):
        self.plan_steps.append(step)
        self.pl_fill()

    def _pl_common(self):
        try:
            secs = int(float(re.sub(r"[^0-9.,]", "", self.pl_dur.get()).replace(",", ".")) * 60)
        except ValueError:
            secs = 3600
        alt = None if self.pl_alt.get() == "egal" else int(self.pl_alt.get().rstrip("°"))
        lp = {"An": True, "Aus": False}.get(self.pl_lp.get())
        return secs, alt, self.AF_MODES[self.pl_af.get()], lp

    def plan_add_target(self, o):
        secs, alt, af, lp = self._pl_common()
        oid, name = o[0], o[1]
        self._pl_add({"t": "capture", "name": oid.replace(" ", "") if not name else f"{oid} {name}"[:40],
                      "ra": o[4], "dec": o[5], "secs": secs, "min_alt": alt, "max_wait_h": 3, "af": af, "lp": lp})

    def pl_add_selected(self):
        o = self._obj_sel()
        if o:
            self.plan_add_target(o)

    def pl_add_mosaic(self):
        mp = self._mz_plan()
        if not mp:
            messagebox.showinfo(APP_NAME, "Im Tab „Mosaik“ zuerst ein gültiges Ziel einstellen.")
            return
        _secs, alt, af, lp = self._pl_common()
        mp["af_mode"] = af
        if lp is not None:
            mp["lp"] = lp
        self._pl_add({"t": "mosaic", "spec": mp, "min_alt": alt, "name": mp["name"]})

    def pl_add_wait(self):
        t = self.pl_wait.get().strip()
        if not re.match(r"^\d{1,2}:\d{2}$", t):
            messagebox.showerror(APP_NAME, "Uhrzeit bitte als HH:MM eingeben.")
            return
        self._pl_add({"t": "wait_until", "at": t})

    def pl_move(self, delta):
        sel = self.pl_tree.selection()
        if not sel:
            return
        k = int(sel[0])
        j = k + delta
        if 0 <= j < len(self.plan_steps):
            self.plan_steps[k], self.plan_steps[j] = self.plan_steps[j], self.plan_steps[k]
            self.pl_fill()
            self.pl_tree.selection_set(str(j))

    def pl_remove(self):
        sel = self.pl_tree.selection()
        if sel:
            del self.plan_steps[int(sel[0])]
            self.pl_fill()

    def pl_edit(self):
        sel = self.pl_tree.selection()
        if not sel:
            return
        st = self.plan_steps[int(sel[0])]
        win = self.make_window("Schritt bearbeiten")
        frm = ttk.Frame(win, padding=12)
        frm.pack()
        vars_ = {}
        def row(r, label, key, val, values=None):
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=3)
            v = tk.StringVar(value=val)
            (ttk.Combobox(frm, textvariable=v, values=values, width=24) if values else
             ttk.Entry(frm, textvariable=v, width=26)).grid(row=r, column=1, padx=6)
            vars_[key] = v
        if st["t"] == "wait_until":
            row(0, "Uhrzeit (HH:MM):", "at", st["at"])
        elif st["t"] == "af":
            row(0, "Fokus:", "af", self._pl_af_text(st.get("mode", "auto")), list(self.AF_MODES))
        else:
            if st["t"] == "capture":
                row(0, "Name:", "name", st["name"])
                row(1, "Dauer (min):", "min", f"{st['secs'] / 60:g}")
            row(2, "Mind.-Höhe (° oder leer):", "alt", "" if st.get("min_alt") is None else str(st["min_alt"]))
            if st["t"] == "capture":
                row(3, "Fokus:", "af", self._pl_af_text(st.get("af", "auto")), list(self.AF_MODES))
        def ok():
            try:
                if st["t"] == "wait_until":
                    if not re.match(r"^\d{1,2}:\d{2}$", vars_["at"].get().strip()):
                        raise ValueError("Uhrzeit")
                    st["at"] = vars_["at"].get().strip()
                elif st["t"] == "af":
                    st["mode"] = self.AF_MODES.get(vars_["af"].get(), "auto")
                else:
                    if "name" in vars_:
                        st["name"] = vars_["name"].get().strip()[:40] or st["name"]
                        st["secs"] = int(float(vars_["min"].get().replace(",", ".")) * 60)
                        st["af"] = self.AF_MODES.get(vars_["af"].get(), "auto")
                    a = vars_["alt"].get().strip().rstrip("°")
                    st["min_alt"] = int(a) if a else None
            except ValueError as e:
                messagebox.showerror(APP_NAME, f"Ungültige Eingabe: {e}", parent=win)
                return
            win.destroy()
            self.pl_fill()
        ttk.Button(frm, text="OK", style="Accent.TButton", command=ok).grid(row=9, column=0, columnspan=2, pady=(10, 0))

    def _pl_start_time(self):
        t = self.pl_start.get().strip()
        if re.match(r"^\d{1,2}:\d{2}$", t):
            hh, mm = [int(x) for x in t.split(":")]
            now = datetime.now()
            tgt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if tgt < now - timedelta(hours=6):
                tgt += timedelta(days=1)
            return max(tgt, now)
        return datetime.now()

    def pl_fill(self):
        tree = self.pl_tree
        tree.delete(*tree.get_children())
        site = self.site_cache
        model = self.active.model if self.active and self.active.model else self.model
        t = self._pl_start_time()
        total = 0
        for k, st in enumerate(self.plan_steps):
            when = ""
            if st["t"] == "wait_until":
                hh, mm = [int(x) for x in st["at"].split(":")]
                tgt = t.replace(hour=hh, minute=mm, second=0)
                if tgt < t - timedelta(hours=6):
                    tgt += timedelta(days=1)
                t = max(t, tgt)
                vals = (k + 1, "Warten", f"bis {st['at']} Uhr", "–", "–", "–", f"weiter um {t:%H:%M}")
            elif st["t"] == "af":
                t += timedelta(minutes=3)
                vals = (k + 1, "Autofokus", "", "~3 min", "–", self._pl_af_text(st.get("mode", "auto")), f"{t:%H:%M}")
            else:
                if st["t"] == "mosaic":
                    sp = st["spec"]
                    subs = mosaic_steps(sp, model)
                    secs = sum(x["secs"] for x in subs) + 180 * len(subs)
                    detail = (f"{sp['name']} – " + (f"Framing {sp['scale']:g}×" if sp["mode"] == "frame"
                                                    else f"Raster {sp['cols']}×{sp['rows']} ({len(subs)} Panels)"))
                    art, ra, dec, af = "Mosaik", sp["ra"], sp["dec"], self._pl_af_text(sp.get("af_mode", "auto"))
                    dur = f"{sum(x['secs'] for x in subs) / 60:.0f} min"
                else:
                    secs = st["secs"] + 180
                    detail, art, ra, dec = st["name"], "Aufnahme", st["ra"], st["dec"]
                    af = self._pl_af_text(st.get("af", "auto"))
                    dur = f"{st['secs'] / 60:.0f} min"
                start = t
                if site and st.get("min_alt"):
                    tu = next_time_above(ra, dec, site[0], site[1], st["min_alt"], t.timestamp(), 12)
                    if tu is None:
                        when = "erreicht Mind.-Höhe nicht"
                    elif tu > t.timestamp():
                        start = datetime.fromtimestamp(tu)
                end = start + timedelta(seconds=secs)
                short = False
                if site and st.get("min_alt") and st["t"] == "capture" and not when:
                    x = start.timestamp() + 180                      # nach GoTo/Fokus
                    while x < end.timestamp():
                        if alt_az(ra, dec, site[0], site[1], x)[0] < st["min_alt"] - 0.5:
                            end, short = datetime.fromtimestamp(x), True
                            break
                        x += 300
                if not when:
                    when = f"{start:%H:%M}–{end:%H:%M}"
                    if site:
                        a0 = alt_az(ra, dec, site[0], site[1], start.timestamp())[0]
                        a1 = alt_az(ra, dec, site[0], site[1], end.timestamp())[0]
                        when += f" · Höhe {a0:.0f}°→{a1:.0f}°"
                    if short:
                        when += f" · früher fertig (unter {st['min_alt']}°)"
                    t = end
                vals = (k + 1, art, detail, dur, "egal" if not st.get("min_alt") else f"{st['min_alt']}°", af, when)
                total += secs
            tree.insert("", "end", iid=str(k), values=vals)
        self.pl_sum.set(f"{len(self.plan_steps)} Schritte · Aufnahmezeit inkl. GoTo/Fokus ca. {total // 3600} h "
                        f"{total % 3600 // 60:02d} min · Ende ca. {t:%H:%M}" + ("" if site else " · Standort fehlt"))

    def pl_check_end(self):
        end = next(k for k, v in END_ACTIONS.items() if v == self.pl_end.get())
        if self.cfg.get("pl_end") != end:                 # Wahl merken – gilt auch für neue Pläne
            self.cfg["pl_end"] = end
            save_config(self.cfg)
        prot = [d.name for d in self.devices if d.protect]
        if end != "open" and prot:
            self.pl_endnote.set(f"Arm-Schutz aktiv auf: {', '.join(prot)} – dort endet der Plan trotzdem mit offenem Arm "
                                "(Filter/Taukappe). Auf den anderen Geräten wird wie gewählt geparkt.")
        elif prot:
            self.pl_endnote.set(f"Arm-Schutz aktiv auf: {', '.join(prot)} – Plan endet ohne Parken.")
        else:
            self.pl_endnote.set("")

    def _pl_current(self):
        return {"steps": [dict(s) for s in self.plan_steps], "start": self.pl_start.get().strip(),
                "end": next(k for k, v in END_ACTIONS.items() if v == self.pl_end.get())}

    def _ask_name(self, title, text, initial=""):
        """Kleiner Eingabedialog (modal). Gibt den Text oder None zurück."""
        win = self.make_window(title, minsize=(320, 130))
        ttk.Label(win, text=text).pack(padx=14, pady=(14, 4), anchor="w")
        v = tk.StringVar(value=initial)
        ent = ttk.Entry(win, textvariable=v, width=34)
        ent.pack(padx=14, pady=(0, 8))
        ent.focus_set()
        ent.select_range(0, "end")
        res = {"v": None}

        def ok(_e=None):
            if v.get().strip():
                res["v"] = v.get().strip()
            win.destroy()
        b = ttk.Frame(win)
        b.pack(fill="x", padx=14, pady=(0, 12))
        ttk.Button(b, text="OK", style="Accent.TButton", command=ok).pack(side="right")
        ttk.Button(b, text="Abbrechen", command=win.destroy).pack(side="right", padx=6)
        win.bind("<Return>", ok)
        win.bind("<Escape>", lambda e: win.destroy())
        win.transient(self)
        win.grab_set()
        self.wait_window(win)
        return res["v"]

    def pl_save(self, ask=False):
        if not self.plan_steps:
            messagebox.showinfo(APP_NAME, "Der Plan ist leer – es gibt nichts zu speichern.")
            return
        name = self.pl_name.get().strip()
        if ask or not name or name in ("Neuer Plan", tr("Neuer Plan")):
            name = self._ask_name("Plan speichern", "Name für den Plan:", "" if name in ("Neuer Plan", tr("Neuer Plan")) else name)
            if not name:
                return
            if name in self.cfg.get("plans", {}) and not messagebox.askyesno(
                    APP_NAME, f"Es gibt schon einen Plan „{name}“. Überschreiben?"):
                return
            self.pl_name.set(name)
        self.cfg.setdefault("plans", {})[name] = self._pl_current()
        save_config(self.cfg)
        self.pl_cb.configure(values=sorted(self.cfg["plans"]))
        self.log(f"Plan „{name}“ gespeichert.", "ok")

    def pl_open(self):
        plans = self.cfg.get("plans", {})
        if not plans:
            messagebox.showinfo(APP_NAME, "Es gibt noch keine gespeicherten Pläne.")
            return
        win = self.make_window("Plan laden", key="plan_open", size="420x360", minsize=(320, 240))
        ttk.Label(win, text="Gespeicherte Pläne (Doppelklick = laden):").pack(anchor="w", padx=12, pady=(12, 4))
        tv = ttk.Treeview(win, columns=("name", "n"), show="headings", height=10, selectmode="browse")
        tv.heading("name", text="Name")
        tv.heading("n", text="Schritte")
        tv.column("name", width=280)
        tv.column("n", width=80, anchor="center")
        for nm in sorted(plans):
            tv.insert("", "end", iid=nm, values=(nm, len(plans[nm].get("steps", []))))
        tv.pack(fill="both", expand=True, padx=12)
        cur = self.pl_name.get()
        if cur in plans:
            tv.selection_set(cur)

        def load(_e=None):
            sel = tv.selection()
            if sel:
                self.pl_name.set(sel[0])
                self.pl_load(announce=True)
                win.destroy()
        b = ttk.Frame(win)
        b.pack(fill="x", padx=12, pady=10)
        ttk.Button(b, text="Laden", style="Accent.TButton", command=load).pack(side="right")
        ttk.Button(b, text="Abbrechen", command=win.destroy).pack(side="right", padx=6)
        tv.bind("<Double-1>", load)
        win.bind("<Return>", load)

    def pl_load(self, announce=False):
        name = self.pl_name.get()
        p = self.cfg.get("plans", {}).get(name)
        if not p:
            return
        self.plan_steps = [dict(s) for s in p.get("steps", [])]
        self.pl_start.set(p.get("start") or tr("sofort"))
        self.pl_end.set(END_ACTIONS.get(p.get("end", self.cfg.get("pl_end", "open")), END_ACTIONS["open"]))
        self.pl_fill()
        self.pl_check_end()
        if announce:
            self.log(f"Plan „{name}“ geladen ({len(self.plan_steps)} Schritte).", "ok")

    def pl_new(self):
        self.plan_steps = []
        self.pl_name.set("Neuer Plan")
        self.pl_start.set(tr("sofort"))
        self.pl_fill()
        self.log("Neuer, leerer Plan angelegt – Ziele unten hinzufügen, dann „Speichern“.", "ok")

    def pl_delete(self):
        name = self.pl_name.get()
        if name in self.cfg.get("plans", {}) and messagebox.askyesno(APP_NAME, f"Plan „{name}“ löschen?"):
            del self.cfg["plans"][name]
            save_config(self.cfg)
            self.pl_cb.configure(values=sorted(self.cfg["plans"]))
            self.pl_new()

    def pl_run(self, force_group=False):
        if not self.plan_steps:
            messagebox.showinfo(APP_NAME, "Der Plan ist leer.")
            return
        devs = self.targets(force_group)
        if not devs:
            self.log("Kein verbundenes Zielgerät für den Plan.", "warn")
            return
        busy = [d.name for d in devs if d.job]
        if busy:
            messagebox.showinfo(APP_NAME, "Läuft bereits auf: " + ", ".join(busy))
            devs = [d for d in devs if not d.job]
        if not devs:
            return
        cur = self._pl_current()
        name = self.pl_name.get().strip() or "Plan"
        start = cur["start"] if re.match(r"^\d{1,2}:\d{2}$", cur["start"]) else tr("sofort")
        if not messagebox.askyesno(APP_NAME, f"Plan „{name}“ jetzt starten?\n\n{len(cur['steps'])} Schritt(e) auf: "
                                   f"{', '.join(d.name for d in devs)}\nStart: {start}\nAm Ende: {tr(END_ACTIONS[cur['end']])}\n\n"
                                   "Das Seestar fährt dabei selbstständig die Ziele an.", default="no", icon="question"):
            self.log("Plan nicht gestartet.")
            return
        for d in devs:
            steps = []
            if re.match(r"^\d{1,2}:\d{2}$", cur["start"]):
                steps.append({"t": "wait_until", "at": cur["start"]})
            for st in cur["steps"]:
                if st["t"] == "mosaic":
                    sub = mosaic_steps(st["spec"], d.model)
                    for x in sub:
                        x["min_alt"] = st.get("min_alt") if x is sub[0] else None
                    steps += sub
                else:
                    steps.append(dict(st))
            self._resume_asked.add(d.host)
            PlanJob(d, {"name": name, "kind": "plan", "steps": steps, "end": cur["end"],
                        "refocus": self.refocus_cfg()}).start()
        self.refresh_overview()

    # ---- Fokus & Filter ---------------------------------------------------------
    def _focus_db(self, d):
        return self.cfg.setdefault("focus", {}).setdefault(d.host, {})

    def _fc_load_filter_defaults(self, name):
        fdat = FILTERS.get(name, FILTERS[NO_FILTER])
        self.fc_exp.set(f"{AF_EXP_MS[fdat['light']] // 1000} s")
        self.fc_frames.set(str(AF_FRAMES[fdat["light"]]))
        if name == NO_FILTER:
            self.fc_finfo.set(fdat["hinweis"])
            return
        hell = {1: "hell", 2: "mittel", 3: "dunkel", 4: "sehr dunkel"}[fdat["light"]]
        quelle = {"H": "Herstellerangabe", "T": "übliche Handelsangabe – Datenblatt prüfen", "eigen": "eigener Eintrag"}
        txt = (f"Art: {fdat['art']}" + (f"\nDurchlass: {fdat['band']}" if fdat["band"] else "") +
               f"\nHelligkeit: {hell} → Autofokus {AF_EXP_MS[fdat['light']] // 1000} s × {AF_FRAMES[fdat['light']]} Bilder"
               f"\nDaten: {quelle.get(fdat['quelle'], '–')}\n{fdat['hinweis']}")
        if fdat.get("lp_intern") is False:
            txt += "\nEmpfehlung: internen LP-/Duo-Band-Filter ausschalten (doppelte Filterung kostet nur Licht)."
        model = self.active.model if self.active and self.active.model else self.model
        txt += "\n" + filter_fit_note(model)
        self.fc_finfo.set(txt)

    def _fc_sync_selectors(self, key):
        f = FILTERS.get(key, FILTERS[NO_FILTER])
        if key == NO_FILTER:
            self.fc_brand.set("– kein Filter –")
            self.fc_model_cb.configure(values=[])
            self.fc_model.set("")
        else:
            self.fc_brand.set(f["marke"])
            self.fc_model_cb.configure(values=self._fc_models(f["marke"]))
            self.fc_model.set(f["modell"])
        self.fc_del_btn.state(["!disabled"] if f.get("eigen") else ["disabled"])

    @staticmethod
    def _fc_models(brand):
        return [v["modell"] for k, v in FILTERS.items() if v["marke"] == brand and k != NO_FILTER]

    def _fc_brand_changed(self):
        b = self.fc_brand.get()
        if b == "– kein Filter –":
            self.fc_filter.set(NO_FILTER)
            self.fc_set_filter()
            return
        models = self._fc_models(b)
        self.fc_model_cb.configure(values=models)
        self.fc_model.set("")
        self.fc_finfo.set(f"{len(models)} Modelle von {b} – bitte Modell wählen.")

    def _fc_model_changed(self):
        key = f"{self.fc_brand.get()} {self.fc_model.get()}"
        if key in FILTERS:
            self.fc_filter.set(key)
            self.fc_set_filter()

    def fc_custom_dialog(self):
        win = self.make_window("Eigenen Filter anlegen")
        frm = ttk.Frame(win, padding=12)
        frm.pack()
        v = {k: tk.StringVar() for k in ("marke", "modell", "art", "band", "nm")}
        v["art"].set(DUAL)
        rows = (("Marke:", "marke", None), ("Modell:", "modell", None),
                ("Art:", "art", list(FILTER_KINDS)),
                ("Durchlass (Text, optional):", "band", None), ("Engste Bandbreite in nm (leer = unbekannt):", "nm", None))
        for r_, (lab, key, vals) in enumerate(rows):
            ttk.Label(frm, text=lab).grid(row=r_, column=0, sticky="w", pady=3)
            (ttk.Combobox(frm, textvariable=v[key], values=vals, state="readonly", width=26) if vals else
             ttk.Entry(frm, textvariable=v[key], width=28)).grid(row=r_, column=1, padx=6)
        def ok():
            marke, modell = v["marke"].get().strip(), v["modell"].get().strip()
            if not marke or not modell:
                messagebox.showerror(APP_NAME, "Bitte Marke und Modell angeben.", parent=win)
                return
            try:
                nm = float(v["nm"].get().replace(",", ".")) if v["nm"].get().strip() else None
            except ValueError:
                messagebox.showerror(APP_NAME, "Bandbreite bitte als Zahl (z. B. 7).", parent=win)
                return
            cf = {"marke": marke, "modell": modell, "art": v["art"].get(), "band": v["band"].get().strip(), "nm": nm}
            lst = [x for x in self.cfg.get("custom_filters", []) if not (x["marke"] == marke and x["modell"] == modell)]
            lst.append(cf)
            self.cfg["custom_filters"] = lst
            save_config(self.cfg)
            key = f"{marke} {modell}"
            FILTERS[key] = _filter_entry(marke, modell, cf["art"], cf["band"], nm, "eigen", True)
            self.fc_brand_cb.configure(values=["– kein Filter –"] + filter_brands())
            win.destroy()
            self.fc_filter.set(key)
            self._fc_sync_selectors(key)
            self.fc_set_filter()
        ttk.Button(frm, text="Speichern & verwenden", style="Accent.TButton", command=ok).grid(
            row=9, column=0, columnspan=2, pady=(10, 0))

    def fc_custom_delete(self):
        key = self.fc_filter.get()
        f = FILTERS.get(key)
        if not f or not f.get("eigen") or not messagebox.askyesno(APP_NAME, f"Eigenen Filter „{key}“ löschen?"):
            return
        self.cfg["custom_filters"] = [x for x in self.cfg.get("custom_filters", [])
                                      if f"{x['marke']} {x['modell']}" != key]
        save_config(self.cfg)
        del FILTERS[key]
        self.fc_brand_cb.configure(values=["– kein Filter –"] + filter_brands())
        self.fc_filter.set(NO_FILTER)
        self.fc_set_filter()

    def fc_refresh(self):
        if not hasattr(self, "fc_tree"):
            return
        d = self.active
        self.fc_head.set(f"{d.name} ({d.host})" + (f" · Filter: {d.ext_filter}" if d and d.ext_filter != NO_FILTER else "")
                         + (" · Taukappe" if d and d.dewcap else "") + (" · Zubehör" if d and d.accessory else "")
                         + (" · Arm-Schutz aktiv" if d and d.protect else "") if d else "Kein Gerät ausgewählt")
        if not d:
            return
        self.fc_filter.set(d.ext_filter)
        self._fc_sync_selectors(d.ext_filter)
        self.fc_protect.set(d.protect)
        self.fc_dewcap.set(d.dewcap)
        self.fc_accessory.set(d.accessory)
        self._fc_load_filter_defaults(d.ext_filter)
        self.fc_tree.delete(*self.fc_tree.get_children())
        for fname, v in sorted(self._focus_db(d).items()):
            self.fc_tree.insert("", "end", values=(fname, v.get("pos"), f"{v['hfr']:.2f}" if v.get("hfr") else "–",
                                                   f"{v['temp']:.0f} °C" if isinstance(v.get("temp"), (int, float)) else "–",
                                                   datetime.fromtimestamp(v.get("t", 0)).strftime("%d.%m. %H:%M")))
        self.fc_draw()

    def fc_set_filter(self):
        d = self.active
        if not d:
            return
        name = self.fc_filter.get()
        d.ext_filter = name
        self._fc_sync_selectors(name)
        self._fc_load_filter_defaults(name)
        if name != NO_FILTER and not d.protect:
            d.protect = True
            self.fc_protect.set(True)
            self.apply_protection(d)
        elif name == NO_FILTER and d.protect and not (d.dewcap or d.accessory):
            if messagebox.askyesno(APP_NAME, "Filter abgenommen – Arm-Schutz ausschalten?\n"
                                             "Danach kann das Seestar wieder parken und den Arm schließen."):
                d.protect = False
                self.fc_protect.set(False)
                self.apply_protection(d)
        self.save_devices()
        fdat = FILTERS[name]
        if d.connected and fdat.get("lp_intern") is False and d.values.get("lp"):
            if messagebox.askyesno(APP_NAME, "Internen LP-/Duo-Band-Filter ausschalten? (empfohlen bei Schmalbandfilter)"):
                self.bg(d.apply_setting, "lp", False)
        saved = self._focus_db(d).get(name)
        if saved and d.connected and messagebox.askyesno(APP_NAME, f"Für „{name}“ ist Fokusposition {saved['pos']} "
                                                                   "gemerkt. Jetzt anfahren?"):
            self.fc_goto_saved()
        self.fc_refresh()
        self.refresh_overview()

    def fc_set_dewcap(self):
        d = self.active
        if not d:
            self.fc_dewcap.set(False)
            self.fc_accessory.set(False)
            return
        d.dewcap = bool(self.fc_dewcap.get())
        d.accessory = bool(self.fc_accessory.get())
        if d.mounted and not d.protect:
            d.protect = True
            self.fc_protect.set(True)
            self.apply_protection(d)
        elif not d.mounted and d.protect:
            if messagebox.askyesno(APP_NAME, "Nichts mehr vor dem Objektiv – Arm-Schutz ausschalten?\n"
                                             "Danach kann das Seestar wieder parken und den Arm schließen."):
                d.protect = False
                self.fc_protect.set(False)
                self.apply_protection(d)
        self.save_devices()
        self.fc_refresh()
        self.refresh_overview()

    def fc_set_protect(self):
        d = self.active
        if not d:
            return
        want = bool(self.fc_protect.get())
        if not want and d.mounted and not messagebox.askyesno(
                APP_NAME, f"Laut App ist noch „{d.protect_reason()}“ montiert.\nArm-Schutz wirklich ausschalten?"):
            self.fc_protect.set(True)
            return
        d.protect = want
        self.apply_protection(d)
        self.save_devices()
        self.fc_refresh()
        self.refresh_overview()

    def fc_read(self):
        d = self.active
        if not d or not d.connected:
            return
        def job():
            r = d.wifi.send("get_focuser_position", quiet=True)
            if isinstance(r, dict) and r.get("result") is not None:
                self.ui(self.fc_pos.set, f"Position: {r['result']}" +
                        (f"   ·   {d.temp:.0f} °C" if isinstance(d.temp, (int, float)) else ""))
        self.bg(job)

    def fc_nudge(self, delta):
        d = self.active
        if not d or not d.connected or self.focus_pause([d]) is None:
            return
        def job():
            r = d.wifi.send("get_focuser_position", quiet=True)
            if isinstance(r, dict) and isinstance(r.get("result"), (int, float)):
                d.wifi.send("move_focuser", {"step": int(r["result"] + delta), "ret_step": True}, quiet=True)
                time.sleep(1.2)
                self.fc_read()
            self.ui(self.focus_resume_later, d)
        self.bg(job)

    def _fc_store(self, d, pos, hfr=None):
        self._focus_db(d)[d.ext_filter] = {"pos": int(pos), "hfr": hfr, "temp": d.temp, "t": time.time()}
        save_config(self.cfg)
        self.ui(self.fc_refresh)

    def fc_save_current(self):
        d = self.active
        if not d or not d.connected:
            return
        def job():
            r = d.wifi.send("get_focuser_position", quiet=True)
            if isinstance(r, dict) and isinstance(r.get("result"), (int, float)):
                self._fc_store(d, r["result"])
                d.log(f"Fokusposition {r['result']} für „{d.ext_filter}“ gemerkt.", "ok")
        self.bg(job)

    def focus_to_saved(self, d, backlash=30):
        """Fährt die gemerkte Position für den montierten Filter an (immer von unten). True, wenn vorhanden."""
        v = self._focus_db(d).get(d.ext_filter) or self._focus_db(d).get(NO_FILTER)
        if not v:
            return False
        d.wifi.send("move_focuser", {"step": int(v["pos"]) - backlash, "ret_step": True}, quiet=True)
        time.sleep(1.5)
        d.wifi.send("move_focuser", {"step": int(v["pos"]), "ret_step": True}, quiet=True)
        time.sleep(1.0)
        if isinstance(v.get("temp"), (int, float)) and isinstance(d.temp, (int, float)) and abs(d.temp - v["temp"]) > 4:
            d.log(f"Hinweis: Temperatur seit der Fokussierung um {abs(d.temp - v['temp']):.0f} °C geändert – "
                  "App-Autofokus empfohlen.", "warn")
        d.log(f"Gemerkte Fokusposition {v['pos']} angefahren.", "ok")
        return True

    def fc_goto_saved(self):
        d = self.active
        if not d or not d.connected or self.focus_pause([d]) is None:
            return
        def job():
            if not self.focus_to_saved(d):
                d.log(f"Für „{d.ext_filter}“ ist noch keine Fokusposition gemerkt.", "warn")
            self.fc_read()
            self.ui(self.focus_resume_later, d, 2000)
        self.bg(job)

    def fc_seestar_af(self):
        d = self.active
        if not d or not d.connected:
            return
        if d.ext_filter != NO_FILTER and not messagebox.askyesno(
                APP_NAME, "Der Seestar-Autofokus ist für den Betrieb OHNE externen Filter gedacht.\n"
                          "Ist der Filter gerade abgenommen?"):
            return
        if self.focus_pause([d], "Autofokus") is None:
            return
        def job():
            self.ui(self.fc_status.set, "Seestar-Autofokus läuft …")
            since = time.time()
            d.wifi.send("start_auto_focuse")
            st = d.wait_event(("AutoFocus",), timeout=240, since=since)
            self.ui(self.focus_resume_later, d, 1500)
            r = d.wifi.send("get_focuser_position", quiet=True)
            if st == "complete" and isinstance(r, dict) and isinstance(r.get("result"), (int, float)):
                self._focus_db(d)[NO_FILTER] = {"pos": int(r["result"]), "hfr": None, "temp": d.temp, "t": time.time()}
                save_config(self.cfg)
                self.ui(self.fc_status.set, f"Referenz ohne Filter: {r['result']}. Filter aufsetzen, dann "
                                            "„Gemerkte Position anfahren“ oder den App-Autofokus starten.")
            else:
                self.ui(self.fc_status.set, f"Seestar-Autofokus: {st or 'keine Rückmeldung'}")
            self.ui(self.fc_refresh)
            self.fc_read()
        self.bg(job)

    def _fc_params(self):
        """Autofokus-Parameter aus der Oberfläche (nur im Hauptthread aufrufen)."""
        try:
            return {"exp_ms": int(float(self.fc_exp.get().split()[0]) * 1000), "frames": int(self.fc_frames.get()),
                    "span": int(self.fc_span.get().replace("±", "").strip()), "step": int(self.fc_step.get())}
        except ValueError:
            return None

    def run_app_autofocus(self, d, on_point=None, params=None, narrow=False):
        """Blockierend (im Hintergrund-Thread aufrufen). Gibt Ergebnis-dict oder None.
        narrow=True: Nachfokussieren während der Aufnahme – nur ±30 Schritte um die aktuelle Position;
        liegt das Optimum am Rand, wird automatisch mit dem vollen Bereich wiederholt."""
        fdat = FILTERS.get(d.ext_filter, FILTERS[NO_FILTER])
        prm = params or {"exp_ms": AF_EXP_MS[fdat["light"]], "frames": AF_FRAMES[fdat["light"]], "span": 80, "step": 10}
        if narrow:
            prm = dict(prm, span=REFOCUS_SPAN)
        run = FocusRun(d, exp_ms=prm["exp_ms"], span=prm["span"], step=prm["step"], frames=prm["frames"],
                       on_point=on_point, fine_half=10 if narrow else None)
        d.focus_run = run
        try:
            res = run.run()
        except Exception as e:
            d.log(f"Autofokus nicht möglich: {e}", "err")
            res = None
        finally:
            d.focus_run = None
        if narrow and (res is None or run.at_edge) and not run.cancelled and not (d.job and d.job._stop()):
            d.log("Nachfokussieren: Optimum nicht im engen Bereich – suche im vollen Bereich (± 80).", "warn")
            return self.run_app_autofocus(d, on_point, params, narrow=False)
        if res:
            self._fc_store(d, res["pos"], res.get("hfr"))
            d.log(f"App-Autofokus: beste Position {res['pos']}" +
                  (f" (HFR {res['hfr']:.2f})" if res.get("hfr") else "") + f" für „{d.ext_filter}“ gemerkt.", "ok")
        return res

    def fc_run(self):
        d = self.active
        if not d or not d.connected:
            messagebox.showinfo(APP_NAME, "Kein verbundenes aktives Gerät.")
            return
        if not HAVE_IMAGING:
            messagebox.showinfo(APP_NAME, "Der App-Autofokus braucht numpy und pillow.")
            return
        if d.focus_run or d.job:
            messagebox.showinfo(APP_NAME, "Auf diesem Gerät läuft gerade ein Autofokus oder ein Ablauf.")
            return
        self.fc_points = []
        self.fc_draw()
        prm = self._fc_params()
        def on_point(pos, hfr, n):
            if pos is None:                                   # Feinsuche beginnt: Kurve neu zeichnen
                self.fc_points.clear()
                self.ui(self.fc_status.set, "Feinsuche …")
                return
            self.fc_points.append((pos, hfr, n))
            self.ui(self.fc_draw)
            self.ui(self.fc_status.set, f"Position {pos}: " + (f"HFR {hfr:.2f} ({n} Sterne)" if hfr else "keine Sterne"))
        def job():
            self.ui(self.fc_status.set, "Autofokus läuft …")
            res = self.run_app_autofocus(d, on_point, prm)
            self.ui(self.fc_status.set, f"Fertig: Position {res['pos']}" + (f", HFR {res['hfr']:.2f}" if res.get("hfr") else "")
                    if res else "Autofokus ohne Ergebnis – Sternfeld? Belichtung/Bilder erhöhen, Bereich vergrößern.")
            self.ui(self.fc_draw)
            self.fc_read()
        self.bg(job)

    def fc_cancel(self):
        d = self.active
        if d and d.focus_run:
            d.focus_run.cancel()

    def fc_draw(self):
        c = getattr(self, "fc_canvas", None)
        if c is None:
            return
        c.delete("all")
        W, H = 330, 220
        pts = [p for p in self.fc_points if p[1] is not None]
        if not pts:
            c.create_text(W // 2, H // 2, text="Noch keine Messung", fill=C["dim"])
            return
        xs = [p[0] for p in self.fc_points]
        ys = [p[1] for p in pts]
        x0, x1 = min(xs), max(xs) or 1
        y0, y1 = 0, max(ys) * 1.15
        def X(v): return 30 + (v - x0) / max(1, x1 - x0) * (W - 45)
        def Y(v): return H - 25 - v / max(1e-6, y1) * (H - 40)
        c.create_line(30, H - 25, W - 10, H - 25, fill=C["grid"])
        c.create_line(30, 10, 30, H - 25, fill=C["grid"])
        c.create_text(32, 10, text=f"{y1:.1f}", fill=C["dim"], anchor="nw", font=("Segoe UI", 7))
        c.create_text(30, H - 12, text=str(x0), fill=C["dim"], anchor="w", font=("Segoe UI", 7))
        c.create_text(W - 10, H - 12, text=str(x1), fill=C["dim"], anchor="e", font=("Segoe UI", 7))
        last = None
        for pos, hfr, n in sorted(self.fc_points):
            if hfr is None:
                c.create_text(X(pos), H - 30, text="·", fill=C["err"])
                continue
            pt = (X(pos), Y(hfr))
            if last:
                c.create_line(*last, *pt, fill=C["accent"], width=2)
            c.create_oval(pt[0] - 3, pt[1] - 3, pt[0] + 3, pt[1] + 3, fill=C["fg"], outline="")
            last = pt
        best = min(pts, key=lambda p: p[1])
        c.create_line(X(best[0]), 10, X(best[0]), H - 25, fill=C["ok"], dash=(3, 2))
        c.create_text(X(best[0]) + 3, 14, text=str(best[0]), fill=C["ok"], anchor="nw", font=("Segoe UI", 8))

    # ---- EQ-Modus -----------------------------------------------------------
    def _lat(self):
        try:
            return float(str(self.lat_var.get()).replace(",", "."))
        except ValueError:
            return self.cfg.get("lat")

    def eq_switch(self, eq):
        d = self.active
        if not d or not d.connected:
            messagebox.showinfo(APP_NAME, "Kein verbundenes aktives Gerät.")
            return
        if not self.confirm_arm_closing([d], "Moduswechsel (parkt)"):
            return
        art = "EQ-Modus (äquatorial, mit Wedge)" if eq else "Alt-Az-Modus"
        if not messagebox.askyesno(APP_NAME, f"„{d.name}“ in den {art} umschalten?\n\n"
                                             "Das Seestar fährt dazu in die Parkposition (Arm schließt sich)."):
            return
        def job():
            r = d.wifi.send("scope_park", {"equ_mode": bool(eq)})
            if r is not None and r.get("code", 0) in (0, None):
                d.log(f"Umschalten auf {'EQ' if eq else 'Alt-Az'} angefordert.", "ok")
            time.sleep(4)
            d.read_mount_and_tilt()
            self.ui(self.eq_draw)
            self.ui(self.refresh_overview)
        self.bg(job)

    def eq_refresh(self):
        d = self.active
        if d and d.connected:
            def job():
                d.read_mount_and_tilt(quiet=False)
                self.ui(self.eq_draw)
            self.bg(job)

    def _eq_poll_toggle(self):
        if self.lvl_live.get() and not self._eq_polling:
            self._eq_polling = True
            self.after(200, self._eq_poll)

    def _eq_poll(self):
        if not self.lvl_live.get():
            self._eq_polling = False
            return
        d = self.active
        if d and d.connected:
            def job():
                d.read_mount_and_tilt()
                self.ui(self.eq_draw)
            self.bg(job)
        self.after(1000, self._eq_poll)

    @staticmethod
    def _amp(val, good, ok):
        if val is None:
            return C["dim"], "–"
        return (C["ok"], "gut") if val < good else ((C["warn"], "geht") if val < ok else (C["err"], "zu groß"))

    def level_zero_set(self):
        d = self.active
        if not d or not d.tilt:
            messagebox.showinfo(APP_NAME, "Erst die Live-Messung einschalten, damit ein Messwert da ist.")
            return
        if not messagebox.askyesno(APP_NAME, "Steht das Seestar jetzt genau waagerecht (mit einer Wasserwaage geprüft)?\n\n"
                                             "Dann merkt sich die App den aktuellen Messwert als Nullpunkt für dieses Gerät."):
            return
        self.cfg.setdefault("level_zero", {})[d.host] = [float(d.tilt[0]), float(d.tilt[1])]
        save_config(self.cfg)
        self.log("Nullpunkt der Libelle gespeichert.", "ok")
        self.eq_draw()

    def level_zero_clear(self):
        d = self.active
        if d and self.cfg.get("level_zero", {}).pop(d.host, None) is not None:
            save_config(self.cfg)
            self.log("Nullpunkt der Libelle gelöscht – es gilt wieder der Sensorwert.", "ok")
        self.eq_draw()

    def eq_draw(self):
        if not hasattr(self, "lvl_canvas"):
            return
        d = self.active
        mode = "–" if not d else {True: "EQ (äquatorial)", False: "Alt-Az", None: "unbekannt"}[d.eq_mode]
        self.eq_head.set(f"{d.name} ({d.host}) · Montierungsmodus: {mode}" if d else "Kein Gerät ausgewählt")

        # Libelle
        c = self.lvl_canvas
        c.delete("all")
        W = 230
        R = 100
        cx = cy = W // 2
        maxdeg = 3.0
        for deg, col in ((2.0, C["ring_err"]), (1.0, C["ring_warn"]), (0.5, C["ring_ok"])):
            rr = R * deg / maxdeg
            c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, outline=col, width=2)
        c.create_oval(cx - R, cy - R, cx + R, cy + R, outline=C["grid"])
        c.create_line(cx - R, cy, cx + R, cy, fill=C["panel2"])
        c.create_line(cx, cy - R, cx, cy + R, fill=C["panel2"])
        for deg in (0.5, 1, 2):
            off = R * deg / maxdeg * 0.7071
            c.create_text(cx + off + 3, cy + off + 3, text=f"{deg:g}°", fill=C["dim"], anchor="nw", font=("Segoe UI", 7))
        tilt = d.tilt if d else None
        zero = self.cfg.get("level_zero", {}).get(d.host) if d else None
        if tilt:
            x, y, ang = tilt
            if zero:
                x, y = x - zero[0], y - zero[1]
            tot = math.hypot(x, y)
            k = min(1.0, maxdeg / max(tot, 1e-9)) if tot > maxdeg else 1.0
            px, py = cx + x * k * R / maxdeg, cy - y * k * R / maxdeg
            col, word = self._amp(tot, 0.5, 1.0)
            c.create_oval(px - 11, py - 11, px + 11, py + 11, fill=col, outline="")
            self.lvl_txt.set(f"X: {x:+.2f}°   Y: {y:+.2f}°\nGesamt: {tot:.2f}°  ({word})" +
                             (f"\nSensor-Winkel: {float(ang):.1f}°" if ang is not None else ""))
            self.lvl_zero_var.set("Nullpunkt: eigener Wert" if zero else "")
        else:
            c.create_text(cx, cy - R - 6 + 20, text="keine Sensordaten", fill=C["dim"])
            self.lvl_txt.set("Neigung: –  (Live-Messung einschalten)")
        lat = self._lat()
        if lat not in (None, ""):
            lat = float(lat)
            self.wedge_txt.set(f"Breitengrad {lat:.1f}° → Wedge-Skala ab Horizont: {abs(lat):.1f}°, "
                               f"ab Senkrechte: {90 - abs(lat):.1f}°.\nWelche Skala dein Wedge hat, steht auf ihm "
                               "(im Zweifel: die Polachse soll um den Breitengrad über den Horizont zeigen).")
        else:
            self.wedge_txt.set("Breitengrad im Tab „Standort“ eintragen, dann steht hier der Wedge-Winkel.")

        # Zielscheibe Polausrichtung
        c = self.pa_canvas
        c.delete("all")
        W = 260
        R = 115
        cx = cy = W // 2
        rng = float(self.pa_range.get().strip("±°"))
        for deg, col in ((1.0, C["ring_warn"]), (0.5, C["ring_ok"])):
            if deg <= rng:
                rr = R * deg / rng
                c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, outline=col, width=2)
        c.create_oval(cx - R, cy - R, cx + R, cy + R, outline=C["grid"])
        c.create_line(cx - R, cy, cx + R, cy, fill=C["panel2"])
        c.create_line(cx, cy - R, cx, cy + R, fill=C["panel2"])
        c.create_text(cx + R - 2, cy - 8, text="Azimut", fill=C["dim"], anchor="e", font=("Segoe UI", 8))
        c.create_text(cx + 4, cy - R + 8, text="Höhe", fill=C["dim"], anchor="w", font=("Segoe UI", 8))
        hist = self._pa_history.get(d.host, []) if d else []
        pts = []
        for _t, x, y in hist[-6:]:
            k = min(1.0, rng / max(math.hypot(x, y), 1e-9))
            pts.append((cx + x * k * R / rng, cy - y * k * R / rng))
        for a, b2 in zip(pts, pts[1:]):
            c.create_line(*a, *b2, fill=C["grid"], dash=(3, 2))
        for n, (px, py) in enumerate(pts):
            last = n == len(pts) - 1
            col = self._amp(max(abs(hist[-len(pts) + n][1]), abs(hist[-len(pts) + n][2])), 0.5, 1.0)[0] if last else C["dim"]
            rr = 9 if last else 4
            c.create_oval(px - rr, py - rr, px + rr, py + rr, fill=col, outline="")
        st = d.pa_state if d else ""
        if d and d.pa:
            p = d.pa
            worst = max(abs(p["x"]), abs(p["y"]))
            col, word = self._amp(worst, 0.5, 1.0)
            age = int((time.time() - p["t"]) / 60)
            self.pa_txt.set(f"Höhe:   {p['y']:+.2f}°  ({p['y'] * 60:+.0f}′)\nAzimut: {p['x']:+.2f}°  ({p['x'] * 60:+.0f}′)\n"
                            f"Gesamt: {p['total']:.2f}° → {word}  · vor {age} min" +
                            ("\nMessung läuft …" if st == "working" else ""))
        else:
            self.pa_txt.set({"working": "Messung läuft … (das Seestar dreht sich zu mehreren Positionen)",
                             "fail": "Messung fehlgeschlagen – freie Sicht? Sterne scharf? Startposition wechseln."}
                            .get(st, "Noch keine Messung."))
        self._eq_checklist()

    def _eq_checklist(self):
        for w in self.chk_frame.winfo_children():
            w.destroy()
        d = self.active
        z = self.cfg.get("level_zero", {}).get(d.host) if d else None
        tilt = math.hypot(d.tilt[0] - (z[0] if z else 0), d.tilt[1] - (z[1] if z else 0)) if d and d.tilt else None
        pa = max(abs(d.pa["x"]), abs(d.pa["y"])) if d and d.pa else None
        exp = d.values.get("exp") if d else None
        rows = [
            ("Verbunden", (C["ok"], "ja") if d and d.connected else (C["err"], "nein")),
            ("Montierungsmodus EQ", (C["dim"], "unbekannt") if not d or d.eq_mode is None
             else ((C["ok"], "ja") if d.eq_mode else (C["err"], "Alt-Az"))),
            ("Neigung < 1°", self._amp(tilt, 0.5, 1.0) if tilt is not None else (C["dim"], "–")),
            ("Polausrichtung < 0,5°", self._amp(pa, 0.5, 1.0) if pa is not None else (C["dim"], "nicht gemessen")),
            ("Belichtung", (C["dim"], "–") if exp is None else
             ((C["ok"], f"{exp // 1000} s") if exp < 60000 or (d.eq_mode and (pa or 9) < 1.0)
              else (C["warn"], "60 s – erst testen"))),
        ]
        for k, (label, (col, txt)) in enumerate(rows):
            dot = tk.Canvas(self.chk_frame, width=14, height=14, bg=C["bg"], highlightthickness=0)
            dot.create_oval(2, 2, 12, 12, fill=col, outline="")
            dot.grid(row=k, column=0, pady=2)
            ttk.Label(self.chk_frame, text=label).grid(row=k, column=1, sticky="w", padx=6)
            ttk.Label(self.chk_frame, text=txt, foreground=col).grid(row=k, column=2, sticky="w")

    def pa_start(self):
        d = self.active
        if not d or not d.connected:
            messagebox.showinfo(APP_NAME, "Kein verbundenes aktives Gerät.")
            return
        if d.eq_mode is False and not messagebox.askyesno(
                APP_NAME, "Das Gerät ist im Alt-Az-Modus. Polausrichtung ergibt nur im EQ-Modus Sinn.\n\nTrotzdem starten?"):
            return
        pos = int(self.pa_pos.get()[0])
        d.pa_auto = bool(self.pa_repeat.get())
        d.pa_running = True
        d.pa_state = "working"
        self.eq_draw()
        self.bg(d.wifi.send, "start_polar_align", {"restart": True, "dec_pos_index": pos})
        d.log(f"Polausrichtung gestartet (Startposition {pos}).", "ok")

    def pa_stop(self):
        d = self.active
        if not d:
            return
        d.pa_running = False
        def job():
            d.wifi.send("stop_polar_align")
            d.wifi.send("iscope_stop_view")
        if d.connected:
            self.bg(job)
        if d.pa_state == "working":
            d.pa_state = ""
        d.log("Polausrichtung beendet.", "ok")
        self.eq_draw()

    def _on_pa_event(self, d, ev):
        st = ev.get("state")
        if st == "complete" and "x" in ev and "y" in ev:
            self._pa_history.setdefault(d.host, []).append((time.time(), float(ev["x"]), float(ev["y"])))
            worst = max(abs(float(ev["x"])), abs(float(ev["y"])))
            d.log(f"Polausrichtung: Höhe {float(ev['y']):+.2f}°, Azimut {float(ev['x']):+.2f}°",
                  "ok" if worst < 0.5 else "warn")
            if getattr(d, "pa_running", False) and getattr(d, "pa_auto", False) and worst >= 0.5:
                pos = int(self.pa_pos.get()[0])
                def again():
                    time.sleep(3)
                    if getattr(d, "pa_running", False) and d.connected:
                        d.pa_state = "working"
                        d.wifi.send("start_polar_align", {"restart": True, "dec_pos_index": pos}, quiet=True)
                        self.ui(self.eq_draw)
                self.bg(again)
            elif worst < 0.5:
                d.pa_running = False
                d.log("Polausrichtung unter 0,5° – fertig. Klemmen fest, Gerät nicht mehr bewegen.", "ok")
        elif st == "fail":
            d.pa_running = False
            d.log(f"Polausrichtung fehlgeschlagen: {ev.get('error', '')}", "err")
        if d is self.active:
            self.eq_draw()

    def et_start(self):
        d = self.active
        if not d or not d.connected:
            messagebox.showinfo(APP_NAME, "Kein verbundenes aktives Gerät.")
            return
        if self.eq_test and self.eq_test.get("running"):
            return
        exp = int(self.et_exp.get().split()[0]) * 1000
        if exp == 60000 and d.eq_mode is not True:
            messagebox.showwarning(APP_NAME, "60 s gibt es nur im EQ-Modus. Bitte zuerst umschalten und ausrichten.")
            return
        dur = int(self.et_dur.get().split()[0]) * 60
        t = {"running": True, "dev": d, "exp": exp, "dur": dur, "old": d.values.get("exp"), "cancel": False}
        self.eq_test = t
        def job():
            d.apply_setting("exp", exp)
            since = time.time()
            d.wifi.send("iscope_start_stack", {"restart": True})
            end = time.time() + dur
            last = (0, 0)
            while time.time() < end and not t["cancel"] and d.connected:
                ev = getattr(d, "_last_stack_ev", None)
                if ev and ev[0] >= since:
                    last = (ev[1], ev[2])          # gestackt / verworfen seit Neustart des Stacks
                rest = int(end - time.time())
                good, bad = last
                tot = good + bad
                self.ui(self.et_txt.set, f"Läuft … noch {rest // 60}:{rest % 60:02d} · "
                                         f"gut {good}, verworfen {bad}" + (f" ({good * 100 // tot} % gut)" if tot else ""))
                time.sleep(1)
            d.wifi.send("iscope_stop_view", {"stage": "Stack"})
            if t["old"] and t["old"] != exp:
                d.apply_setting("exp", t["old"])
            good, bad = last
            tot = good + bad
            if t["cancel"]:
                msg = "Test abgebrochen."
            elif tot == 0:
                msg = "Keine Frames gezählt – war ein Ziel angefahren und stackte das Seestar?"
            else:
                q = good * 100 / tot
                verdict = ("passt – diese Belichtung kannst du nutzen." if q >= 90 else
                           "geht, aber Polausrichtung verbessern oder kürzer belichten." if q >= 70 else
                           "zu viele verworfene Frames: Polausrichtung, Wind, Stabilität prüfen oder kürzer belichten.")
                msg = f"Ergebnis {exp // 1000} s: {good} von {tot} Frames gut ({q:.0f} %) → {verdict}"
            d.log(msg, "ok" if "passt" in msg else "warn")
            self.ui(self.et_txt.set, msg)
            t["running"] = False
            self.ui(self.eq_draw)
        self.bg(job)

    def et_stop(self):
        if self.eq_test:
            self.eq_test["cancel"] = True

    # ---- Einstellungsfenster pro Gerät -----------------------------------
    def open_settings_popup(self, d):
        if d.settings_popup and d.settings_popup.winfo_exists():
            d.settings_popup.deiconify()
            d.settings_popup.lift()
            return
        win = self.make_window(f"Einstellungen – {self._dev_label(d)}", key=f"settings:{d.host}", size="1120x620")
        panel = SettingsPanel(win, self, device=d)
        panel.pack(fill="both", expand=True)
        d.settings_popup = win
        def close():
            panel.detach()
            d.settings_popup = None
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", close)
        if d.connected:
            self.bg(d.refresh_settings)

    PROTECT_SETTINGS = (("power_off", False, "Automatisch ausschalten"),
                        ("gohome", False, "Nach Seestar-Plan Arm schließen"),
                        ("auto_af", False, "Smart-AF (scheitert hinter Schmalbandfiltern)"),
                        ("af_before", False, "Seestar-Autofokus vor dem Stacking"))

    def apply_protection(self, d):
        """Arm-Schutz an: Einstellungen setzen, die sonst den Arm schließen oder den Fokus verstellen würden."""
        self.refresh_overview()
        if hasattr(self, "pl_endnote"):
            self.pl_check_end()
        if not d.protect:
            d.log("Arm-Schutz aus – Parken und Schließen wieder möglich. Auto-Aus, Go-Home und Smart-AF "
                  "kannst du in den Einstellungen wieder einschalten.", "ok")
            return
        d.log(f"Arm-Schutz an ({d.protect_reason()}). Parken, Ausschalten und Moduswechsel sind gesperrt.", "ok")
        if not d.connected:
            return
        todo = [x for x in self.PROTECT_SETTINGS
                if x[0] in ("power_off", "gohome") or d.ext_filter != NO_FILTER]   # AF nur hinter Filtern ändern
        def job():
            changed = []
            for key, val, label in todo:
                if d.values.get(key) != val:
                    if d.apply_setting(key, val):
                        changed.append(label)
            if changed:
                d.log("Für den Arm-Schutz ausgeschaltet: " + ", ".join(changed) + ".", "ok")
            self.ui(self.device_settings_loaded, d)
        self.bg(job)

    def battery_warning(self, d, lvl):
        msg = (f"„{d.name}“: Akku bei {d.battery} %.\n\nWenn das Seestar wegen leerem Akku abschaltet, kann es den Arm "
               "schließen – das kann die App nicht verhindern. Bitte Strom anschließen oder Filter/Taukappe abnehmen.")
        d.log(msg.replace("\n\n", " "), "err")
        messagebox.showwarning(APP_NAME, msg)

    def confirm_arm_closing(self, devs, action="Arm schließen"):
        """Vor Park/Aus/Moduswechsel: geschützte Geräte abfragen. Gibt die Geräte zurück, die ausführen dürfen."""
        prot = [d for d in devs if d.protect]
        if not prot:
            return devs
        names = ", ".join(f"{d.name} ({d.protect_reason()})" for d in prot)
        if messagebox.askyesno(APP_NAME, f"Arm-Schutz aktiv: {names}\n\n„{action}“ würde den Arm gegen "
                                         "Filterhalter bzw. Taukappe fahren.\n\nIst alles abgenommen? "
                                         "(„Ja“ hebt den Schutz für diese Geräte auf)"):
            for d in prot:
                d.ext_filter = NO_FILTER
                d.dewcap = False
                d.accessory = False
                d.protect = False
                self.apply_protection(d)
            self.save_devices()
            if hasattr(self, "fc_tree"):
                self.fc_refresh()
            return devs
        return [d for d in devs if not d.protect]

    def queue_setting(self, d, key, val):
        """Gerät nicht verbunden: Änderung merken und beim nächsten Verbinden senden (bleibt auch nach Neustart)."""
        if d.protect and key in ARM_CLOSE_SETTINGS and val:
            d.log(f"„{SETTING_LABEL.get(key, key)}“ bleibt aus – Arm-Schutz aktiv ({d.protect_reason()}).", "warn")
            val = False
        d.values[key] = val
        d.pending[key] = val
        self.save_devices()
        for p in list(d.settings_panels):
            p.refresh()
        d.log(f"nicht verbunden – „{SETTING_LABEL.get(key, key)}“ wird beim nächsten Verbinden gesendet.", "warn")

    def device_settings_loaded(self, d):
        for p in list(d.settings_panels):
            p.refresh()

    # ---- Ersteinrichtung ----------------------------------------------------------
    def reset_all(self):
        if not messagebox.askyesno(APP_NAME, "Alle gespeicherten Daten löschen?\n\nGeräteliste, Standort, PEM-Pfad, "
                                             "Filter, gemerkte Fokuspositionen, Zeitpläne, eigene Filter und offene "
                                             "Abläufe werden entfernt. Die App startet danach wie neu installiert."):
            return
        running = [d.name for d in self.devices if d.job]
        names = ", ".join(running)
        if running and not messagebox.askyesno(APP_NAME, f"Auf {names} läuft noch ein Ablauf. "
                                                         "Trotzdem zurücksetzen? (Das Seestar stackt dann weiter.)"):
            return
        for d in self.devices:
            d.disconnect()
        try:
            CONFIG_FILE.unlink()
        except FileNotFoundError:
            pass
        messagebox.showinfo(APP_NAME, "Alles zurückgesetzt. Die App wird jetzt beendet – beim nächsten Start "
                                      "begrüßt dich der Einrichtungsassistent.")
        self.destroy()

    def setup_wizard(self):
        win = self.make_window("Willkommen – Einrichtung", key="wizard", size="660x520", minsize=(560, 440))
        win.transient(self)
        body = ttk.Frame(win, padding=16)
        body.pack(fill="both", expand=True)
        nav = ttk.Frame(win, padding=(16, 0, 16, 14))
        nav.pack(fill="x")
        st = {"page": 0}
        lat = tk.StringVar(value=str(self.cfg.get("lat", "")))
        lon = tk.StringVar(value=str(self.cfg.get("lon", "")))
        pem = tk.StringVar(value=self.cfg.get("pem", ""))
        name, ip = tk.StringVar(value=f"Seestar {len(self.devices) + 1}"), tk.StringVar()
        found = tk.StringVar(value="")

        def h(t):
            ttk.Label(body, text=t, font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(0, 8))

        def p(t):
            ttk.Label(body, text=t, wraplength=570, justify="left", foreground=C["muted2"]).pack(anchor="w", pady=(0, 8))

        def page0():
            h(f"Willkommen bei {APP_NAME}")
            p("In drei kurzen Schritten ist alles eingerichtet: Standort, deine Seestar(s) und – nur bei neuerer "
              "Firmware – der Anmeldeschlüssel. Alles lässt sich später ändern; den Assistenten findest du im Tab „WLAN“.")
            p("Unterstützt werden Seestar S30, S30 Pro, S50 und S50 Pro, auch mehrere gleichzeitig. Das Modell "
              "erkennt die App beim Verbinden selbst.")

        def page1():
            h("1 · Standort")
            p("Wird für Zeit und Standort am Seestar, die Höhe der Objekte im GoTo-Tab und die Zeitpläne gebraucht.")
            def auto_done(ok):
                if ok:
                    self.after(2500, lambda: (lat.set(self.lat_var.get()), lon.set(self.lon_var.get()))
                               if win.winfo_exists() else None)
            ttk.Button(body, text="📍 Automatisch ermitteln …", command=lambda: self.ask_location_consent(auto_done)
                       if self.cfg.get("loc_consent") is not True else (self.loc_locate(), auto_done(True))).pack(anchor="w")
            ttk.Label(body, textvariable=self.loc_status, foreground=C["muted"], wraplength=570).pack(anchor="w", pady=(4, 8))
            p("Oder von Hand (Dezimalgrad oder Grad/Minuten/Sekunden; Berlin z. B. 52,52 / 13,40):")
            g = ttk.Frame(body)
            g.pack(anchor="w")
            ttk.Label(g, text="Breite (°N):").grid(row=0, column=0, sticky="w", pady=4)
            ttk.Entry(g, textvariable=lat, width=12).grid(row=0, column=1, padx=6)
            ttk.Label(g, text="Länge (°O):").grid(row=1, column=0, sticky="w", pady=4)
            ttk.Entry(g, textvariable=lon, width=12).grid(row=1, column=1, padx=6)

        def page2():
            h("2 · Seestar hinzufügen")
            p("Am einfachsten im selben WLAN: In der Seestar-App das Heimnetz eintragen (Stationsmodus), dann hier "
              "suchen. Alternativ die IP-Adresse aus dem Router eintragen. Weitere Geräte kannst du später im Tab "
              "„Übersicht“ hinzufügen.")
            ttk.Button(body, text="🔍 Im Netzwerk suchen", command=search).pack(anchor="w")
            ttk.Label(body, textvariable=found, foreground=C["ok"], wraplength=570, justify="left").pack(anchor="w", pady=6)
            g = ttk.Frame(body)
            g.pack(anchor="w", pady=(4, 0))
            ttk.Label(g, text="Name:").grid(row=0, column=0, sticky="w", pady=4)
            ttk.Entry(g, textvariable=name, width=22).grid(row=0, column=1, padx=6)
            ttk.Label(g, text="IP-Adresse:").grid(row=1, column=0, sticky="w", pady=4)
            ttk.Entry(g, textvariable=ip, width=22).grid(row=1, column=1, padx=6)
            ttk.Button(g, text="＋ Hinzufügen", command=add).grid(row=1, column=2, padx=6)
            lst = ", ".join(f"{d.name} ({d.host})" for d in self.devices)
            ttk.Label(body, text=("Bereits eingetragen: " + lst) if lst else "Noch kein Gerät eingetragen.",
                      foreground=C["muted"], wraplength=570).pack(anchor="w", pady=(8, 0))

        def page3():
            h("3 · Anmeldeschlüssel (nur neuere Firmware)")
            p("Ab etwa Firmware 7.18 nimmt das Seestar Befehle nur nach einer Anmeldung mit einem Schlüssel aus der "
              "offiziellen Seestar-App an. Den Schlüssel liefert diese App nicht mit. Mit dem „Seestar tool“ aus dem "
              "Projekt seestar_alp („Extract PEM“) erzeugst du ihn aus deiner eigenen Seestar-App. Ohne Schlüssel "
              "funktioniert die App bei älterer Firmware trotzdem – du kannst ihn auch später im Tab „WLAN“ eintragen.")
            g = ttk.Frame(body)
            g.pack(anchor="w", fill="x")
            ttk.Entry(g, textvariable=pem, width=56).pack(side="left")
            ttk.Button(g, text="…", width=3, command=lambda: pem.set(
                filedialog.askopenfilename(parent=win, title="PEM-Schlüssel wählen",
                                           filetypes=[("PEM", "*.pem"), ("Alle", "*.*")]) or pem.get())).pack(side="left", padx=6)

        def page4():
            h("Fertig")
            p("Beim Klick auf „Verbinden“ verbindet sich die App mit allen eingetragenen Geräten und erkennt das Modell.")
            p("Nächste Schritte:\n• Tab „GoTo“: Objekt aussuchen und anfahren\n• Tab „Vorschau“: Live-Bild ansehen\n"
              "• Tab „Fokus & Filter“: externen 2\"-Filter eintragen, falls du einen nutzt – dann schützt die App "
              "auch den Arm vor dem Schließen\n• Tab „EQ-Modus“: nur mit Wedge für 60-s-Belichtungen")

        def search():
            found.set("Suche läuft …")
            def job():
                res = SeestarWifi.discover()
                def apply():
                    if not res:
                        found.set("Kein Seestar gefunden. Ist es eingeschaltet und im selben Netz? IP sonst manuell eintragen.")
                        return
                    n = 0
                    for fip, info in res.items():
                        r = info.get("result", {}) if isinstance(info, dict) else {}
                        if self.add_device(fip, r.get("device_name") or r.get("product_model") or ""):
                            n += 1
                    found.set(f"{n} Gerät(e) gefunden und eingetragen: " + ", ".join(res))
                    if st["page"] == 2 and win.winfo_exists():
                        show(2)
                self.ui(apply)
            self.bg(job)

        def add():
            if ip.get().strip():
                self.add_device(ip.get().strip(), name.get().strip())
                found.set(f"„{name.get().strip() or ip.get().strip()}“ eingetragen.")
                ip.set("")
                name.set(f"Seestar {len(self.devices) + 1}")
                show(2)

        pages = [page0, page1, page2, page3, page4]

        def save_step():
            if st["page"] == 1 and (lat.get().strip() or lon.get().strip()):
                try:
                    la, lo = parse_coord(lat.get(), True), parse_coord(lon.get(), False)
                except ValueError as e:
                    messagebox.showerror(APP_NAME, f"Ungültiger Standort: {e} (z. B. 52,52 / 13,40).", parent=win)
                    return False
                if (round(la, 4), round(lo, 4)) != (round(float(self.cfg.get("lat", 999)), 4), round(float(self.cfg.get("lon", 999)), 4)):
                    self.set_location(la, lo, "manuell")
            if st["page"] == 3:
                self.cfg["pem"] = pem.get().strip()
                self.pem_var.set(pem.get().strip())
            save_config(self.cfg)
            return True

        def show(k):
            for w in body.winfo_children():
                w.destroy()
            for w in nav.winfo_children():
                w.destroy()
            st["page"] = k
            pages[k]()
            ttk.Label(nav, text=f"Schritt {k + 1} von {len(pages)}", foreground=C["dim"]).pack(side="left")
            if k == len(pages) - 1:
                ttk.Button(nav, text="Verbinden", style="Accent.TButton", command=finish).pack(side="right")
                ttk.Button(nav, text="Schließen", command=close).pack(side="right", padx=6)
            else:
                ttk.Button(nav, text="Weiter", style="Accent.TButton",
                           command=lambda: save_step() and show(k + 1)).pack(side="right")
                ttk.Button(nav, text="Überspringen", command=close).pack(side="right", padx=6)
            if k > 0:
                ttk.Button(nav, text="Zurück", command=lambda: show(k - 1)).pack(side="right")

        def close():
            save_config(self.cfg)
            self.obj_fill()
            win.destroy()

        def finish():
            close()
            self.group_connect()

        show(0)

    # ---- Konsole ----------------------------------------------------------
    def console_send(self):
        m = self.c_method.get().strip()
        p = self.c_params.get().strip()
        params = None
        if p:
            try:
                params = json.loads(p)
            except Exception as e:
                messagebox.showerror(APP_NAME, f"Parameter sind kein gültiges JSON: {e}")
                return
        if not self.c_keep.get():
            self.c_out.delete("1.0", "end")                   # jede Anfrage beginnt mit leerer Ausgabe
        def show(r):
            self.c_out.insert("end", json.dumps(r, indent=2, ensure_ascii=False) + "\n\n")
            self.c_out.see("end")
        self.rpc(m, params, show)

    def console_copy(self):
        txt = self.c_out.get("1.0", "end").strip()
        if txt:
            self.clipboard_clear()
            self.clipboard_append(txt)
            self.log("Konsolen-Antwort in die Zwischenablage kopiert.", "ok")

    # ---- Bluetooth --------------------------------------------------------
    def _ble_done(self, fut, ok_msg=None, then=None):
        try:
            res = fut.result()
        except Exception as e:
            self.log(f"BLE-Fehler: {e}", "err")
            return
        if ok_msg:
            self.log(ok_msg, "ok")
        if then:
            self.ui(then, res)

    def _ble_list_fill(self):
        L = self.ble_list
        for w in L.winfo_children():
            w.destroy()
        for k, h in enumerate(("Gerät", "Adresse", "Signal", "")):
            tk.Label(L, text=h, bg=C["tab"], fg=C["fg"], font=("Segoe UI", 9, "bold"), anchor="w", padx=6,
                     pady=4).grid(row=0, column=k, sticky="ew")
        if not self.ble_found:
            tk.Label(L, text="Noch kein Scan – „Scannen“ drücken.", bg=C["bg"], fg=C["muted"], pady=8).grid(
                row=1, column=0, columnspan=4, sticky="w", padx=6)
            return
        for r, (addr, name, rssi) in enumerate(self.ble_found, start=1):
            con = addr == self.ble_conn
            bg = C["panel2"] if con else C["bg"]
            for k, v in enumerate((("● " if con else "") + name, addr, f"{rssi} dBm")):
                tk.Label(L, text=v, bg=bg, fg=C["ok"] if con and k == 0 else C["fg"], anchor="w", padx=6,
                         pady=4).grid(row=r, column=k, sticky="nsew")
            b = ttk.Button(L, width=11, command=lambda a=addr: self.ble_toggle(a))
            if self.ble_busy == addr:
                b.configure(text="Verbinde …", style="Connect.TButton")
                b.state(["disabled"])
            elif con:
                b.configure(text="Trennen", style="Disconnect.TButton")
            else:
                b.configure(text="Verbinden", style="Connect.TButton")
            b.grid(row=r, column=3, padx=6, pady=2)

    def ble_scan(self):
        self.log("BLE-Scan läuft (6 s) …")
        def fill(devs):
            keep = [x for x in self.ble_found if x[0] == self.ble_conn]
            self.ble_found = keep + [x for x in devs if x[0] != self.ble_conn]
            self._ble_list_fill()
            if devs:
                self.log(f"{len(devs)} Gerät(e) gefunden.", "ok")
            else:
                self.log("Nichts gefunden. Seestar eingeschaltet? Ggf. 'Nur Seestar' abhaken.", "warn")
        self.ble.run(self.ble.scan(self.ble_only.get()), lambda f: self._ble_done(f, then=fill))

    def ble_toggle(self, addr):
        if addr == self.ble_conn:
            self.ble_conn = None
            self.ble.run(self.ble.disconnect(), lambda f: self._ble_done(f, "BLE getrennt."))
            self.ble_tree.delete(*self.ble_tree.get_children())
            self._ble_list_fill()
            return
        self.ble_busy = addr
        self._ble_list_fill()
        self.log(f"BLE: verbinde mit {addr} …")

        def fill(rows):
            self.ble_conn = addr
            self.ble_tree.delete(*self.ble_tree.get_children())
            for r in rows:
                self.ble_tree.insert("", "end", values=r)

        def done(fut):
            self.ble_busy = None
            if fut.exception() is not None:
                self.ui(self._ble_list_fill)
            self._ble_done(fut, "BLE verbunden – Dienste geladen.", lambda rows: (fill(rows), self._ble_list_fill()))
        self.ble.run(self.ble.connect(addr), done)

    def ble_lost(self):
        """Aufruf aus dem BLE-Thread, wenn die Verbindung abreißt."""
        def apply():
            self.ble_conn = None
            self._ble_list_fill()
        self.ui(apply)

    def _sel_char(self):
        sel = self.ble_tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Bitte zuerst eine Characteristic in der Liste auswählen.")
            return None
        return self.ble_tree.item(sel[0], "values")[1]

    @staticmethod
    def _fmt(data: bytes) -> str:
        try:
            txt = data.decode("utf-8")
            if txt.isprintable():
                return f'"{txt}"  ({data.hex(" ")})'
        except Exception:
            pass
        return data.hex(" ")

    def ble_read(self):
        u = self._sel_char()
        if u:
            self.ble.run(self.ble.read(u), lambda f: self._ble_done(
                f, then=lambda d: self.log(f"BLE {u[:8]} gelesen: {self._fmt(d)}", "rx")))

    def ble_notify(self):
        u = self._sel_char()
        if u:
            self.ble.run(self.ble.notify(u, lambda uu, d: self.log(f"BLE-Notify {uu[:8]}: {self._fmt(d)}", "ev")),
                         lambda f: self._ble_done(f, f"Benachrichtigungen für {u[:8]} aktiv."))

    def ble_write(self):
        u = self._sel_char()
        if not u:
            return
        txt = self.ble_payload.get()
        try:
            data = bytes.fromhex(txt) if self.ble_hex.get() else txt.encode()
        except ValueError:
            messagebox.showerror(APP_NAME, "Ungültiger Hex-String.")
            return
        self.ble.run(self.ble.write(u, data), lambda f: self._ble_done(f, f"BLE {u[:8]}: {len(data)} Byte gesendet."))

    # ---- Ende -------------------------------------------------------------
    def on_close(self):
        if getattr(self, "air_job", None) and self.air_job.alive() and not messagebox.askyesno(
                APP_NAME, "Ein ASIAIR-Plan läuft. Beim Schließen wird er abgebrochen (das Air beendet die laufende "
                          "Serie nicht von selbst).\n\nTrotzdem schließen?"):
            return
        try:
            if self.station:
                self.station.stop()
            self._air_back_local()
        except Exception:
            pass
        try:
            self._air_save_cfg()
            if self.air_job and self.air_job.alive():
                self.air_job.stop()
                self.air.sequence_stop()
                self.air.guide_stop()
        except Exception:
            pass
        running = [d.name for d in self.devices if d.job]
        if running and not messagebox.askyesno(
                APP_NAME, f"Ablauf läuft auf: {', '.join(running)}\n\nBeim Schließen wird er pausiert. "
                "Das Seestar stackt das aktuelle Panel weiter, wechselt aber nicht zum nächsten. "
                "Beim nächsten Start kannst du fortsetzen.\n\nTrotzdem schließen?"):
            return
        if self.state() == "normal" and not self._fs_state.get("fs"):
            self.cfg.setdefault("geom", {})["main"] = self.geometry()
        else:            # maximiert/Vollbild: beim nächsten Start normal groß, aber auf DEMSELBEN Bildschirm
            l, t, r, b = window_monitor(self)
            w, h = int((r - l) * 0.85), int((b - t) * 0.85)
            self.cfg.setdefault("geom", {})["main"] = f"{w}x{h}+{l + (r - l - w) // 2}+{t + (b - t - h) // 2}"
        for d in self.devices:
            if d.popup and d.popup.winfo_exists():
                self.cfg.setdefault("geom", {})[f"preview:{d.host}"] = d.popup.geometry()
        self.cfg["speed"] = int(self.speed_var.get())
        save_config(self.cfg)
        self.cfg["model_auto"] = bool(self.model_auto.get())
        save_config(self.cfg)
        self.save_devices()
        try:
            self.standby.set(False)                     # Standby-Sperre beim Beenden immer aufheben
        except Exception:
            pass
        for d in self.devices:
            d.disconnect()
        if self.ble:
            try:
                self.ble.run(self.ble.disconnect()).result(timeout=3)
            except Exception:
                pass
        self.destroy()


def _startfehler(exc):
    """Fehler beim Start sichtbar machen (start.bat nutzt pythonw – dort gibt es kein Konsolenfenster)."""
    import traceback
    txt = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    log = Path(__file__).with_name("startfehler.txt")
    try:
        log.write_text(time.strftime("%Y-%m-%d %H:%M:%S") + "\n" + txt, encoding="utf-8")
    except OSError:
        log = Path.home() / "star_gazing_startfehler.txt"
        try:
            log.write_text(txt, encoding="utf-8")
        except OSError:
            pass
    try:
        r = tk.Tk(); r.withdraw()
        messagebox.showerror("Star Gazing Control Center",
                             f"Das Programm konnte nicht starten.\n\n{type(exc).__name__}: {exc}\n\n"
                             f"Details stehen in:\n{log}")
        r.destroy()
    except Exception:
        print(txt, file=sys.stderr)


def trial_blocked():
    """Testversion abgelaufen: nur der Hinweis, das Programm öffnet sich nicht."""
    try:
        lang = load_config().get("lang", "auto")
        I18.set_language(system_language() if lang == "auto" else lang)
    except Exception:
        pass
    r = tk.Tk(); r.withdraw()
    messagebox.showinfo(APP_NAME, f"The trial version has expired ({TRIAL_STARTS} starts).\n\n"
                        "Thank you for testing! If you like the program:\n" + TRIAL_CONTACT)
    r.destroy()


if __name__ == "__main__":
    if TRIAL_STARTS > 0 and TRIAL_COUNT > TRIAL_STARTS:
        trial_blocked()
        sys.exit(0)
    try:
        App().mainloop()
    except Exception as e:
        _startfehler(e)
        sys.exit(1)
