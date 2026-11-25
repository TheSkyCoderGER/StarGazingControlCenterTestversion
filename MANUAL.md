# User Manual – Star Gazing Control Center by TheSkyCoder

Step-by-step guide for all functions. For a short feature overview see [README.md](README.md).

> Unofficial software, not made by ZWO. Use at your own risk – especially with anything mounted in front of the lens (filters, dew shields).

---

## Contents

1. [Installation](#1-installation)
2. [First start (setup assistant)](#2-first-start-setup-assistant)
3. [The main window](#3-the-main-window)
4. [Overview – managing your Seestars](#4-overview--managing-your-seestars)
5. [Location](#5-location)
6. [Weather & Tips](#6-weather--tips)
7. [Control](#7-control)
8. [Focus & Filter](#8-focus--filter)
9. [Settings](#9-settings)
10. [EQ mode](#10-eq-mode)
11. [GoTo and the object catalogue](#11-goto-and-the-object-catalogue)
12. [Mosaic](#12-mosaic)
13. [Schedules](#13-schedules)
14. [Preview](#14-preview)
15. [Wi-Fi](#15-wi-fi)
16. [Bluetooth](#16-bluetooth)
17. [Console](#17-console)
18. [A typical night – checklist](#18-a-typical-night--checklist)
19. [Troubleshooting](#19-troubleshooting)
20. [Trial version](#20-trial-version)

---

## 1. Installation

**Windows**

1. Install **Python 3.10 or newer** from [python.org](https://www.python.org/downloads/). In the installer, tick **“Add Python to PATH”**.
2. Download the program (GitHub: green **Code** button → **Download ZIP**) and unzip it into a folder of your choice, e.g. `Desktop\StarGazingControlCenter`.
3. Double-click **`start.bat`**. On the first start the required packages are installed automatically (internet needed, takes a minute).
4. If the program does not start, double-click **`start_diagnose.bat`** – it shows the error message. A file `startfehler.txt` with details is also written into the program folder.

**macOS / Linux:** `pip install -r requirements.txt`, then `python3 star_gazing_control_center.py`.

**Updating:** unzip the new version over the old folder (or into a new folder). Your settings are stored separately (`%USERPROFILE%\.star_gazing_control_center.json`) and are kept.

**Firewall:** if Windows asks, allow Python access to the **private network**. The app uses TCP ports 4700 (control) and 4800 (images) and UDP port 4720 (search).

---

## 2. First start (setup assistant)

The assistant opens automatically on the first start and has three steps. Everything can be changed later.

1. **Location** – choose “Determine automatically” (asks for your consent, see [Location](#5-location)) or type in latitude/longitude.
2. **Add Seestar** – click **“Search network”** (the Seestar must be switched on and in the same network as the PC) or enter the IP address by hand. You can add as many devices as you like.
3. **Login key (PEM)** – newer Seestar firmware requires a key from the official Seestar app (see [Wi-Fi → PEM key](#pem-key-login-with-newer-firmware)). You can skip this step and add it later.

Then click **“Connect”**. The app connects, detects the model (S30, S30 Pro, S50, S50 Pro) and reads all settings from the device.

You can reopen the assistant at any time in the **Wi-Fi** tab.

---

## 3. The main window

| Area | What it is |
|---|---|
| Top bar | **Language**, **Theme** (Blue, Dark, Night red), **Size** (scaling, after restart) |
| Second row | **Active device** (drop-down), connection state, **Commands to**: *active device* or *all ticked*, **↺ Reset page**, **Model** |
| Tabs | Overview · Location · Weather & Tips · Control · Focus & Filter · Settings · EQ mode · GoTo · Mosaic · Schedules · Preview · Wi-Fi · Bluetooth · Console |
| Log (bottom) | Everything the app does, with time. Errors in red, warnings in yellow. |

**Useful keys:** **F11** full screen (also in every sub-window), **Esc** leaves full screen. In the Control tab the **arrow keys** move the telescope and the **space bar** stops it.

**Reset page:** resets only the tab you are looking at. The app first shows exactly what will be reset. Saved plans, filters and focus positions are kept.

**Night mode (red):** for observing in the dark – everything including the Windows title bar turns dark red.

---

## 4. Overview – managing your Seestars

**Add a device:** enter name and IP address → **“+ Add”**, or **“Search network”**.

**Device list:** each row shows name, IP, model, status, frames, battery (⚡ = charging), temperature, free storage and the current job (plan/mosaic).

- **Click a row** → this device becomes the **active device** (»). Control, Settings, Preview and Console act on it.
- **Tick box** at the start of the row → the device belongs to the **group**.
- **Connect / Disconnect** button behind each device (red “Cancel” while connecting).
- **Preview** → opens a separate preview window for this device. **Double-click** a row does the same.
- **Settings** → opens a separate settings window for this device.

**Active device box:** *Access data …* (Wi-Fi name/password, home network or direct, see [Wi-Fi](#15-wi-fi)), *Rename*, *Remove*, *Move up/down*.

**Group box** – always acts on **all ticked devices**: Connect all, Disconnect all, Open all previews, Time + location, Copy settings of the active device, Open arm, Autofocus, Start stacking, Stop stacking, GoTo (target from “Control”), Park, **EMERGENCY STOP all**.

**Commands to “all ticked”** (top bar): then joystick, GoTo, focus and settings from all tabs go to the whole group at once.

---

## 5. Location

The location is needed for object altitudes, “best months”, the night plan, the wedge angle and for correct GoTos on the Seestar.

**Automatic (only with your consent):** tick **“Determine location automatically”**. Sources, in this order:

1. Windows location service (stays on your PC; must be allowed in Windows under *Settings › Privacy › Location*),
2. the location stored in your Seestar,
3. optionally your approximate position from your internet address (off by default; sends your IP to freeipapi.com / ipwho.is).

**Manual:** untick automatic, then enter latitude and longitude, e.g. `53.65` or `53°39'00" N`; south and west with “-” or S/W. Optionally a place name.

**Send to Seestar:** “Time + location” sends both to the active device. This also happens automatically on every connection (can be switched off in the Wi-Fi tab).

> If the Seestar phone app is connected at the same time, it may overwrite the Seestar’s location with the phone’s position. If a device reports a location more than 20 km away, the app asks whether to take it over.

---

## 6. Weather & Tips

1. Tick **“Fetch weather data”** once (consent; only your location rounded to ~1 km goes to Open-Meteo.com).
2. The chart shows 48 hours of clouds (low/mid/high), rain chance, darkness and moon. Below: rating of the night, dew point and gust warnings.
3. **“What is worth shooting tonight?”** lists the best targets for your active device: time window, maximum altitude, direction, moon distance, whether the object fits the field of view, and whether your filter suits it.
   - **Min. altitude**: 10°–50° in 5° steps.
   - **“Ignore weather”**: shows suggestions even when the forecast is cloudy.
4. **“Create plan for tonight”** turns the suggestions into a schedule (tab **Schedules**). Single objects can be sent directly to GoTo, Schedules or Mosaic.

---

## 7. Control

**Arm:** *Open arm / star mode*, *Park (close arm)* – with a safety question – and **■ Stop everything** (stops any movement immediately).

**Fine adjustment (move manually):** arrow buttons or keyboard arrow keys move the telescope; **speed** slider and **duration** (seconds). **■** in the middle or the **space bar** stops at once.

**Focus:** −100, −20, +20, +100 steps; the current **position** is shown. **Autofocus** runs the Seestar autofocus. If the Seestar is stacking, the app first asks whether to **continue the same stack** or **start a new one** afterwards.

**Go to target (GoTo):**

1. Click into the **Catalogue** box and **type** a name or number, e.g. `M31`, `Andromeda`, `NGC 7000`, `Sh2-101`, `Tulip`. The list filters while you type.
2. Press **Enter** or choose from the list → name, RA and Dec are filled in.
3. Or type RA (hours) and Dec (degrees) yourself – decimal or `5h35m17s` / `-5°23'28"`.
4. **“GoTo + Live view”** slews, plate-solves and starts the live view. **“Only slew”** just moves. **“Plate solve”** determines the current position.

**Current position:** RA/Dec of the telescope (“Refresh”). **Other:** play a sound (find the device), shut down.

---

## 8. Focus & Filter

Use this tab if you mount an **external 2" filter** or a **dew shield** in front of the lens.

1. **Filter:** choose **brand** and **model** (185 filters from 19 brands) or create your own with **“Custom filter …”** (brand, model, type, narrowest bandwidth). Choose **“No external filter”** when you remove it.
2. **Dew shield fitted** / **Other accessory in front of the lens:** tick if applicable.
3. As soon as a filter or accessory is entered, **arm protection** switches on for this device:
   - parking, power-off, restart and the Alt-Az ↔ EQ switch are blocked (the arm would hit the accessory),
   - schedules end with the arm **open**,
   - with a filter, the Seestar autofocus options are switched off (they fail behind narrowband filters).
4. **Precision autofocus (app):** slew to a star field, click **“Start autofocus”**. The app steps through the focus range, averages several images per position, measures star sharpness and draws the focus curve. The result is **saved per device and filter** (with temperature).
5. **“Go to saved position”** sets the saved focus directly. If the temperature differs by more than 4 °C, the app recommends a new autofocus.
6. Alternative: **“Seestar autofocus (without filter) + save as reference”**, then fit the filter and go to the saved position.

---

## 9. Settings

All settings as in the Seestar app, **per device**. The tab shows the active device; the Overview button **“Settings”** opens a separate window for any device. Both always show the same state.

| Section | Settings |
|---|---|
| Stacking | Exposure (2–30 s, 60 s only in EQ mode), gain, LP/dual-band filter, choose filter automatically, dithering (on/off, distance, every … frames), dark calibration, save individual frames (no / good only / all), **burst capture (no stacking)** ℹ, 4K mode (drizzle 2×), background extraction (DBE), star correction, remove airplane/satellite trails, stack automatically after GoTo |
| Focus | Smart AF, autofocus before each target |
| Device | Dew heater (on/off), automatic power-off, temperature unit, calibrate EQ polar alignment, expert mode |
| Live view | Zoom 1×/2×/4×, exposure of the live image |
| Wide angle (S30, S30 Pro, S50 Pro) | Use wide-angle camera, 4K, denoise |
| Start mode | Stars/deep sky, moon, sun (**solar filter only!**), landscape → “Start (open arm)” |

**How changes work**

- A change is sent **immediately**. The app then reads the value back from the device; if the Seestar did not accept it, the display returns to the real value and the log says so.
- **Not connected?** The change is remembered and sent on the next connection.
- **Every 30 s** the app re-reads the settings while the tab or a settings window is open – including changes made in the phone app.
- **Burst capture** (ℹ): the Seestar only takes single frames and does **not** stack them. Leave it **off** for normal imaging.
- **Phone app shows old values?** The Seestar phone app does not refresh by itself:
  - **DBE:** close and reopen the settings page in the phone app.
  - **Dew heater:** close the phone app completely (also swipe it away from recent apps), restart it and reconnect.
- **Dew heater:** the S50 heater is weak and hardly noticeable by touch. Check it via the switch in this app – it shows the real state reported by the device.

---

## 10. EQ mode

For use on an **equatorial wedge**. In EQ mode exposures of up to **60 s** are possible.

1. **Levelling & wedge:** “Live measurement” shows the built-in tilt sensor as a bubble level (rings at 0.5°/1°/2°). The **wedge angle** for your latitude is shown for both scale types (from horizon / from vertical). If the bubble shows a small fixed offset although the Seestar is level, use **“Set zero point”**.
2. **Switch Alt-Az ↔ EQ** with the buttons at the top (the Seestar parks for this – blocked while arm protection is active).
3. **Polar alignment (3-point):** choose a start position (3 = default), click **“Measure error”**. The target shows the altitude and azimuth error. With **“re-measure automatically”** keep turning the knobs until both axes are below 0.5°.
4. **Checks & tracking test:** traffic-light checklist; then slew to a target, choose exposure (20/30/60 s) and duration, start. The app counts good and rejected frames and tells you whether the exposure is fine. Afterwards the previous exposure is restored.

---

## 11. GoTo and the object catalogue

The list shows about **1,100 well-suited targets** (all Messier objects, bright NGC/IC, named objects, southern sky). Another **~12,500 objects** (all NGC/IC, Sharpless Sh2, Lynds LDN) appear **only when you search** for them.

- **Search:** type a name or number (`m 31`, `Rosette`, `Sh2-129`, `LDN 1235`).
- **Type:** all, galaxies, nebulae, star clusters, planetary nebulae, supernova remnants.
- **Altitude now:** all, above 0°, 10°–50° in 5° steps.
- **Messier & named only:** hides unnamed objects.
- **In season now (sorted):** only objects that are well placed this month at your location, best first.
- Columns: object, name, type, magnitude, size, altitude now, direction, culmination (time and altitude), **best months**, **field of view** (“fits”, or the mosaic size needed for the active model). Click a column header to sort.
- Objects that never rise above 10° at your location are hidden (shown at the top right). Everything updates every minute and adapts automatically when you change the location.

**Buttons:** **GoTo + Live** (target from “Commands to”), **GoTo on all ticked**, **Only slew**, **→ Control**, **→ Mosaic**, **→ Schedule**. Double-click a row = GoTo + Live.

The app converts the catalogue coordinates (J2000) to today’s date on every GoTo.

---

## 12. Mosaic

1. **Centre:** type into the box at the top (whole catalogue, Enter), enter RA/Dec, or take the target from “Control”.
2. **Type:**
   - **Grid mosaic** – columns × rows (up to 6 × 6), overlap (usually 15–20 %), time per panel (min. 5 min), autofocus before each panel. Each panel is saved as its own target (`Name_R1C1`, `Name_R1C2` …) – stitch them later, e.g. in Siril.
   - **Framing mosaic** – the Seestar’s built-in mosaic: size 1.5×–4×, rotation −90° to +90°, one total time, one single stack.
3. The drawing shows the panels for the active device (north up, east left; numbers = order; strips = overlap).
4. **Start** – on the active device or all ticked devices (each with its own field of view). Progress is shown in the Overview (“Job” column).

**PC standby:** while a mosaic is running, the app prevents the PC/laptop from going to sleep (option “PC / Laptop”). Keep a laptop open and on the charger.

**Interruptions:** if the connection drops, the app reconnects and continues. If you close the app or it crashes, it asks **“Resume mosaic?”** on the next connection. “Disconnect” pauses, “Cancel mosaic” ends it for good.

**Refocusing:** optional automatic refocus after 2 °C / 3 °C temperature change and/or every 60/90/120 min – in the same stack.

---

## 13. Schedules

A schedule is a list of steps that runs automatically.

1. **New** → **Add step:**
   - **Capture:** target (from GoTo), duration, **minimum altitude** (the plan waits up to 3 h for the target to rise, otherwise skips it; if it sinks below during capture, the step ends early), focus mode, LP filter.
   - **Mosaic:** uses the settings from the Mosaic tab.
   - **Wait until time** and **Autofocus**.
2. **Focus per step:** automatic, Seestar autofocus, app autofocus, saved position, or none.
3. The list shows the **expected time** and altitude for each step.
4. **Save**, **Save as …**, **Load …**.
5. **Run:** start **now** or at a **start time**, on the active device or all ticked. Choose the **end action**: stop stacking (arm stays open), park, or park and power off. The app always asks for confirmation before starting.
6. **Refocusing during the night** as in Mosaic.

Devices with arm protection always end with the arm open. A running plan survives connection drops and can be resumed after an app restart.

---

## 14. Preview

- **Live preview** – the running single frames. If no view is running on the Seestar, the app starts star mode itself (asks first if the arm is closed).
- **Get stack image** – the current stacked image; with **“automatically”** it reloads after every new frame.
- **Stretch** slider, linked/unlinked channels, linear display.
- **Save PNG.**
- Separate **preview windows per device** (Overview → Preview / double-click): “Always on top”, full screen (F11), position remembered – handy on a second monitor.

The stretch is for the screen only; the data on the Seestar is not changed.

---

## 15. Wi-Fi

- **Search** finds Seestars in the network. **Connect** / **Disconnect**, device status.
- **Initialisation:** send time and location on every connection (on by default).
- **Connect automatically at start** and **reconnect automatically** after a drop (both on by default).
- **Setup assistant**, **Add new language …** (template for your own translation), **Show hints again**, **Reset everything …**

### Getting the Seestar into your home network

Easiest: in the Seestar phone app enter your home Wi-Fi (station mode). Then PC and Seestar are in the same network. Alternatively connect the PC directly to the Seestar’s own Wi-Fi (address usually `10.0.0.1`).

**Access data per device** (Overview → *Access data …*): connection *Home network* or *Direct*, Wi-Fi name (`S50_…`) and password (factory default `12345678`). With *Direct* the app connects Windows to the Seestar Wi-Fi automatically. The password is stored encrypted for your Windows user only.

### PEM key (login with newer firmware)

From firmware ~7.18 the Seestar requires a login with an RSA key from the official Seestar Android app. **This key belongs to ZWO and is not included.**

1. Get the free **seestar-tool** (github.com/bguthro/seestar-tool → Releases, Windows version).
2. Use it to read the key from the Seestar APK and save it as a `.pem` file. **Do not use the tool’s firmware upload function.**
3. In the app: Wi-Fi tab → **PEM key** → choose the file → connect.

Keep the key private. Never pass it on and never put it into the program folder.

---

## 16. Bluetooth

The Seestar uses Bluetooth only for waking up and the first Wi-Fi setup; ZWO has not published the protocol. This tab is an **explorer**: search, connect/disconnect, list services and characteristics, read, write (text or hex), record notifications. Telescope control runs over Wi-Fi.

Requires Windows 10 (1709) or newer and a BLE adapter.

---

## 17. Console

For advanced users: send any JSON-RPC command to the active device, e.g. method `get_device_state`, parameters `{"keys": ["setting"]}`. Buttons: **Send**, **Clear**, **Copy reply**, option **“Keep older replies”**.

> Replies can contain private data (IP addresses, Wi-Fi names, the device password). Do not post them publicly.

---

## 18. A typical night – checklist

1. Set up the Seestar level (outdoors, cooled down to ambient temperature). Fit filter/dew shield if used.
2. Start the app → devices connect automatically. Check battery and free storage in the **Overview**.
3. **Focus & Filter:** enter filter / dew shield → arm protection on.
4. **Weather & Tips:** check the night, look at the suggestions, optionally **“Create plan for tonight”**.
5. **GoTo** a bright star field → **Focus & Filter:** autofocus (app autofocus with a filter).
6. **Settings:** exposure (10–20 s Alt-Az, up to 60 s EQ), dithering, save individual frames if you process in Siril.
7. Start a **schedule** or **mosaic**. Laptop on the charger.
8. In the morning: remove filter/dew shield, untick them in the app, **park**.

---

## 19. Troubleshooting

| Problem | Solution |
|---|---|
| App does not start | Run `start_diagnose.bat`; check that Python is installed with “Add to PATH”. |
| Seestar not found | Same network? Firewall allowed for Python (private network)? Enter the IP manually (see router or phone app). |
| Connected, but commands are rejected | Newer firmware needs the **PEM key** (Wi-Fi tab). |
| A setting jumps back | The device did not accept it – see the log. Some functions depend on the firmware version. |
| Phone app shows different values | The phone app does not refresh by itself – reopen the page or restart the phone app (see [Settings](#9-settings)). |
| GoTo slightly off | Set the correct location and time (Location tab → Time + location). |
| Autofocus fails behind a filter | Use the **app autofocus** in Focus & Filter (longer exposures, averaging). |
| Live preview shows only one image | The app restarts star mode automatically; if the arm is closed it asks first. |
| Name shows “(modified)” | The program files were changed. Download the original version again. |
| PC went to sleep during a plan | Only mosaics block standby automatically; disable sleep in Windows for the night and use the charger. |

---

## 20. Trial version

The trial version is fully functional but stops working after **10 starts** (a reminder appears from start 8). For the full version, contact the author on Facebook: profile **“Bönn Ingstedt”** – easiest to find by searching for **“TheSkyCoder”**.

---

© 2026 TheSkyCoder. See [LICENSE.md](LICENSE.md). ZWO and Seestar are names or trademarks of their respective owners; this software is not affiliated with ZWO.
