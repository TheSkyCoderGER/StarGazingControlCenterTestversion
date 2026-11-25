# Star Gazing Control Center by TheSkyCoder

> **Trial version** – stops working after 10 starts (a reminder appears from start 8).  
> For the full version: Facebook profile **“Bönn Ingstedt”** – easiest to find by searching for **“TheSkyCoder”**.

PC control for ZWO Seestar S30, S30 Pro, S50 and S50 Pro. © 2026 TheSkyCoder.

Unofficial desktop app (Windows, macOS, Linux) for controlling all current Seestar models over **Wi-Fi** (same network) and **Bluetooth LE**. Not made by ZWO – use at your own risk.

*Deutsche Fassung: [README.de.md](README.de.md)*

## Installation (Windows)

1. Install Python 3.10 or newer from python.org (tick “Add Python to PATH”).
2. Unzip the folder and double-click `start.bat`. On the first start the required packages are installed automatically.

Manually: `pip install -r requirements.txt`, then `python star_gazing_control_center.py`.

## Getting started

On the first start a **setup assistant** opens with three steps:

1. **Location** – detect it automatically (with your consent, see below) or type in latitude/longitude.
2. **Add Seestar** – search the network or enter the IP address; as many devices as you like.
3. **Login key** – only needed with newer firmware (see below); can also be added later.

Then “Connect”: the app connects all devices and detects the model by itself. Nothing is preset – no filter, no device, no plan. You only enter an external 2" filter if you use one (tab “Focus & Filter”).

You can reopen the assistant at any time in the “Wi-Fi” tab. There you also find **“Reset everything …”**: it deletes the device list, location, filters, saved focus positions, schedules and custom filters – the app then starts as if freshly installed.

## Features

| Tab | What it does |
|---|---|
| Overview | Manage several Seestars by IP address, a Connect/Disconnect button for each device, status/model/frames/battery (⚡ while charging)/free storage per device, group control for all ticked devices at once, preview window per device |
| Location | Detect your position automatically (Windows location service, Seestar, optionally internet) with one-time, revocable consent – or enter it manually; send time + location to the Seestar |
| Weather & Tips | Cloud (low/mid/high) and rain forecast for 48 h, darkness and moon, rating of the night and suggestions for what is worth shooting at your location tonight – optionally as a ready-made schedule |
| Control | Open arm, park, emergency stop, joystick (also arrow keys), focus ±, autofocus, GoTo from the catalogue or RA/Dec, plate solve, current position |
| Focus & Filter | Set an external filter per device, precision autofocus (app) with focus curve, saved positions per device and filter, arm protection |
| Settings & Capture | All device settings as in the Seestar app, per device (see below) · start/stop stacking · frame counter |
| EQ mode | Switch Alt-Az ↔ EQ, live bubble level (tilt sensor), wedge angle from your latitude, 3-point polar alignment with target display and automatic re-measuring, traffic-light checklist, tracking/exposure test with frame ratio |
| GoTo | Object catalogue (all Messier, nebulae, bright NGC/IC, common names; via search additionally all NGC/IC, Sh2, LDN) with search, current altitude, direction, culmination and field-of-view check; GoTo for the active device or all ticked devices |
| Mosaic | Grid mosaic (columns × rows, overlap, time per panel, autofocus per panel) and framing mosaic (Seestar built-in, size and rotation) – per device, with plan view and progress |
| Schedules | Sequences of targets, mosaics, waiting times and autofocus; minimum altitude per target; start time; end action; save/load; per device or group; resumable |
| Preview | Live preview and current stack image with auto-stretch (adjustable strength), automatic refresh on every new stack frame, save as PNG |
| Wi-Fi | Find Seestars via UDP broadcast, connect, login, send time + location, device status |
| Bluetooth | Find Seestars via BLE, connect/disconnect each one, list all services/characteristics, read, write, record notifications |
| Console | Send any JSON-RPC command |

Everything you set (device list, location, PEM path, filters, focus positions, schedules) is stored in `%USERPROFILE%\.star_gazing_control_center.json` – on your own PC, never inside the program folder. Settings from an earlier version (`.seestar_control.json`) are taken over on the first start.

## Look, language, windows

**Theme:** Top right under “Theme” choose *Blue* (default, buttons in a lighter blue), *Dark* or *Night (red)* for observing at the telescope. “Size” scales the whole interface (takes effect after a restart).

**Language:** On the first start the app uses your system language. You can change it at any time with the **“Language”** box – in the app bar and at the top of every other window (preview, settings, assistant …). The change applies immediately, no restart.

Included: Deutsch, English, Français, Español, Italiano, Nederlands, Polski, Português, 中文（简体）, 日本語. If a text is missing in a language, it appears in English.

*Add another language:* tab “Wi-Fi” → **“Add new language …”** saves a template with all texts (German and English as a guide). Enter the translations, adjust the first line `# name: …` and put the file as `<language code>.txt` (e.g. `fi.txt`, `sv.txt`, `tr.txt`) into the `lang` folder next to the app. On the next start it appears in the list; if it matches the system language it is chosen automatically.

**Windows:** All windows can be resized freely; position and size are remembered, also across several monitors. **F11** switches to full screen. The **preview images** of each telescope open in their own windows (Overview → “Preview” or double-click), which you can move e.g. to a second monitor – with “Always on top” and full screen. On the next start they reopen in the same place.

**Reset page:** The **“↺ Reset page”** button at the top right only resets the page you are looking at (it shows beforehand exactly what will be reset). Saved plans, filters and focus positions are kept; to delete everything at once use “Reset everything …” in the “Wi-Fi” tab.

## Weather & Tips

For your location the tab shows the next 48 hours: total cloud cover and separately low, mid and high clouds, chance of rain, dew point (hint for the dew heater), gusts, plus twilight/darkness and moon altitude. From this the app rates the coming night (good / partly / rather not) and names the best period.

**What is worth shooting tonight?** From the object catalogue the app calculates for your active device which objects are high enough for long enough tonight, when they culminate, how far away the moon is, whether they fit into the field of view (otherwise a mosaic hint) and whether your external filter suits them (with a narrowband filter emission nebulae are preferred, also with a bright moon). If weather data is available, only clear hours count. “Create plan for tonight” turns this into a schedule that you can check and start in the “Schedules” tab; individual objects go straight to GoTo, Schedules or Mosaic.

**Privacy:** Weather data comes from the free service **Open-Meteo.com** (data under CC BY 4.0). It is only fetched after you have agreed once; only your location, rounded to about 1 km, is sent – no account, no other data. The “Fetch weather data” tick box turns it off again at any time. Sun and moon are calculated by the app itself, nothing goes to the internet for that.

## Location

The location is needed for time and tracking on the Seestar, object altitudes and culmination in the GoTo tab, minimum altitude in schedules and the wedge angle in EQ mode.

**Automatic – only with your consent.** When it is first needed, the app asks **once** whether it may determine your location itself, and which sources it may use:

| Source | Accuracy | What happens with the data |
|---|---|---|
| Windows location service | usually metres to a few km | stays on your PC. Access for desktop apps must be allowed in Windows under *Settings › Privacy › Location*. |
| Location from the Seestar | as set in the Seestar app | read only from your own telescope |
| Approximate via internet address | city/region, approx. 5–50 km | your public IP address goes to freeipapi.com or ipwho.is – **off by default** |

The sources are tried in this order; the first successful one wins. With consent the location is updated on every start; an inaccurate (internet) position is replaced automatically by the Seestar’s as soon as one is connected.

**Revoke** at any time in the **“Location”** tab: untick “Determine location automatically”. The app asks whether the last position should be kept as a manual entry or deleted, and then stops determining it itself.

**Enter manually** (“Location” tab, once automatic detection is off): latitude and longitude as decimal degrees (`52.52`) or in degrees/minutes/seconds (`52°31'12" N`, `13° 24′ E`); south and west with “-” or S/W. Optionally a place name. You find the values in any map app.

The app takes the time zone for the Seestar from your PC’s settings.

## Time and location

On every connection the app – like the Seestar app – automatically sends time, time zone and location to the Seestar, which matters for accurate GoTos. Can be switched off in the “Wi-Fi” tab under “Initialisation”. If a sequence (schedule/mosaic) is running on the device, nothing is sent when reconnecting. If no location is set yet, only the time is sent.

## Several Seestars at once

In the **Overview** tab you enter each Seestar with name and IP address (or “Search network” adds all that are found). The list is saved.

- **Click on a row** makes the device the *active device*. The Control, Settings, Preview and Console tabs refer to it.
- **The tick box at the start of the row** adds the device to the group or removes it.
- **Connect / Disconnect** behind each device: the button changes with the state (green “Connect”, red “Disconnect”, “Cancel” while connecting). The “Bluetooth” tab offers the same for each BLE device found.
- **“Commands to”** at the top switches between *active device* and *all ticked*. With “all ticked”, joystick, GoTo, focus, settings etc. from all tabs go to the whole group at once.
- The buttons in the **Group** box always act on all ticked devices, whatever is set at the top: connect, open arm, GoTo, start/stop stacking, autofocus, park, emergency stop.
- **Double-click** on a device (or “Open all previews”) opens a separate preview window per Seestar with its own stretch setting and PNG export.

Each device has its own connection; all use the same PEM key from the “Wi-Fi” tab.

## Settings per device

Each Seestar has its own settings. The “Settings & Capture” tab shows those of the active device; “⚙ Settings” in the Overview opens a separate window for each device. When connecting, the app reads the current values from the device; every change goes immediately to exactly this device.

| Section | Settings |
|---|---|
| Stacking | Exposure (2/5/10/20/30 s, 60 s only in EQ mode = maximum), gain, LP or dual-band filter, choose filter automatically, dithering (on/off, distance, interval), dark calibration, save individual frames (no / good only / all), burst capture (no stacking), 4K mode (drizzle 2×), background extraction (DBE), star correction, remove airplane/satellite trails, stack automatically after GoTo |
| Focus | Smart AF (after GoTo / on temperature drift), autofocus before each target |
| Device | Dew heater (on/off – the firmware has no levels), automatic power-off, temperature unit, calibrate EQ polar alignment, expert mode |
| Live view | Zoom 1× / 2× / 4× (sun, moon, planets), exposure of the live image |
| Wide angle (S30, S30 Pro, S50 Pro) | Use wide-angle camera, wide angle in 4K, wide-angle denoise |

“–” means the device does not report this value (e.g. gain, or the function does not exist in your firmware yet). “Copy to all ticked” copies the settings of one device to the whole group; wide-angle options only where there is a wide-angle camera.

- **Commands to “all ticked”:** a change in the “Settings” tab then goes to all ticked devices; options a model does not have are skipped there. In a device’s own settings window a change always applies only to that device.
- **Device not connected:** the change is remembered (even across an app restart) and sent on the next connection; the log says how many settings were sent afterwards.
- **All views in sync:** the “Settings” tab and the device’s own settings window always show the same state. If someone changes something in the Seestar app on the phone, the app re-reads the settings automatically.
- **Phone app shows old values:** the Seestar phone app does not refresh by itself when you change something on the PC. For background extraction (DBE), close and reopen the settings page in the phone app; for the dew heater, close the phone app completely and reconnect.
- **Not accepted:** if the Seestar rejects a value, the app shows the device’s real state again. After every change the app also reads the value back and tells you in the log if the device did not take it over.
- **Re-reading:** while the “Settings” tab or a settings window is open, the app re-reads the values every 30 s – including changes from the phone app that the Seestar does not report by itself.
- **Arm protection:** “Automatic power-off” and “Close arm after Seestar plan” cannot be switched on while arm protection is active – not even via “Copy to all ticked”. With a filter entered this also applies to Smart AF and “Autofocus before each target”.

## Mosaic

When you open the tab for the first time, a short note explains the drawing (fields, order, overlap strips). “Don’t show again” hides it; **“Show hints again”** in the “Wi-Fi” tab brings it back.

In the “Mosaic” tab you choose the centre (type into the search box to pick from the whole catalogue, enter RA/Dec, or take it from “Control”) and one of two types:

- **Grid mosaic:** columns × rows (up to 6 × 6), overlap, time per panel, optional autofocus before each panel. The Seestar visits the panels in a snake pattern and saves each as a separate target (`Name_R1C1`, `Name_R1C2` …). Stitch them afterwards e.g. in Siril or Astro Pixel Processor.
- **Framing mosaic:** the mosaic function of the Seestar firmware – size 1.5× to 4× the field of view, rotation −90° to +90°, one total time. The result is a single stack.

Each device calculates with its own field of view, so an S30 Pro covers a much larger area with 2 × 2 than an S50. Progress is shown in the Overview in the “Job” column. Starting goes to the target from “Commands to” or to all ticked devices; each runs independently. The plan view shows the field of view of the active device (north up, east left). Field sizes are approximations; in Alt-Az mode the field rotates during the night.

### Keep the PC/laptop from going to sleep

As long as a mosaic is running on at least one device, the app prevents the PC or laptop from going to standby or hibernation due to inactivity – otherwise the control would fall asleep in the middle of the mosaic. This applies **only to mosaics** (not to normal schedules or single captures). When the last mosaic is finished, cancelled or paused, the app releases the lock immediately, also when quitting. The screen may still go dark.

You can switch this off in the “Mosaic” tab under **“PC / Laptop”**; it also shows whether the lock is currently active. Technically: Windows `SetThreadExecutionState`, macOS `caffeinate`, Linux `systemd-inhibit`.

Limits: closing the laptop lid, the power button or an almost empty battery still trigger standby. So keep the laptop open and on the charger (or choose “When I close the lid: Do nothing” in the Windows power options).

### Connection drops and resuming

The app runs the sequence (go to panel, stack, move on after the time), so it should keep running during a mosaic. It is protected against interruptions, though:

- **Reconnect automatically** (switch in the “Wi-Fi” tab, on by default): if the connection drops – even “silently”, e.g. after the laptop was asleep (after 45 s without a reply) – the app reconnects each device by itself, with increasing intervals up to 1 minute.
- **The mosaic carries on:** during the interruption the sequence waits up to one hour. Then it checks whether the Seestar is still stacking. If so, it continues seamlessly; if not (e.g. after a Seestar restart), it goes to the panel again and continues stacking without discarding the previous stack. Time keeps running by the clock, so an interruption does not make the mosaic longer.
- **Resume after an app restart:** the state (panel, end time) is saved continuously. If you close the app in the middle of a mosaic or the PC crashes, the app asks on the next connection: “Resume mosaic?”. Paused mosaics are listed in the Overview in the “Job” column.
- **“Disconnect”** also pauses a running mosaic (resumable). **“Cancel mosaic”** ends it for good and stops stacking.

Still recommended: laptop on the charger and sleep turned off for the night – otherwise the Seestar keeps stacking during the pause but does not move on to the next panel.

## GoTo and object catalogue

The **“GoTo”** tab lists about 1,100 objects: all Messier objects, all nebulae, star clusters and galaxies down to about magnitude 11, and named objects (Horsehead, Double Cluster, Stephan’s Quintet …) – plus the **southern sky** (Omega Centauri, 47 Tucanae, Magellanic Clouds, Carina and Tarantula nebulae …) for trips to the south. With a location (“Location” tab) the list shows current altitude and direction, culmination, and whether the object fits into the active device’s field of view or needs a mosaic. Double-click or “GoTo + Live” slews to it – the active device or all ticked.

**Adapts to your location:** objects that never rise above 10° at your location are hidden – after a change of location (e.g. on holiday) the objects visible there appear automatically. The **“best months”** column shows when an object stays high enough for longest at night at your location; with **“in season now only (sorted)”** you only see objects that are in season right now – the best first. Everything is calculated offline.

If a connected Seestar (usually set by the phone app) or the automatic location reports a position more than 20 km away from the one set, the app asks whether it should take over the new location.

Important: catalogues are given in J2000, but the Seestar expects coordinates for today’s date. The app converts this on **every** GoTo (precession; in 2026 this is about 0.3° – almost half an S50 field of view).

Object data: [OpenNGC](https://github.com/mattiaverga/OpenNGC) by Mattia Verga, licence CC BY-SA 4.0. The file `catalog.json` is derived from it and is under the same licence.

**Extended catalogue (via search):** in addition to the well-suited targets the app knows about 12,500 more objects – all NGC/IC objects (type, magnitude and size from OpenNGC), the Sharpless emission nebulae (Sh2) and the Lynds dark nebulae (LDN), compiled from the object lists shipped with Siril. They only appear when you search for them (e.g. “Sh2-101”, “LDN 1235”, “Tulip”), so that lists and recommendations stay clear. In “Control” and “Mosaic” you can type into the selection box and choose from the whole catalogue (Enter takes it over).

## External filters & focus

**Why there is no fixed focus value per filter:** a 2" filter in front of the lens sits in the parallel beam and practically does not shift the focus. The right focus position depends on the individual Seestar (motor steps) and on the temperature. The real problem: the Seestar autofocus uses very short exposures – behind a narrowband filter (e.g. dual-band with 3–7 nm) it sees too few stars and fails or misses.

That is why the app has its own **precision autofocus** in the **“Focus & Filter”** tab:

1. Choose the filter for the device (brand and model from the filter database or a custom filter, see below). The app sets suitable values: live-image exposure 1–5 s and 1–6 averaged images per focus position, depending on how dark the filter is.
2. Slew to a star field, “Start autofocus”. The app steps through the focus range, averages several live images per position (this reduces noise by √n), measures star sharpness (HFR) and then does a fine search with half the step size around the optimum. It always approaches a position from below to compensate for backlash. The focus curve is drawn live.
3. The result is saved **per device and filter** (with temperature). “Go to saved position” sets it directly later; if the temperature differs by more than 4 °C, the app recommends a new autofocus.

Alternatively: “Seestar autofocus (without filter) + save as reference”, then put the filter on and go to the saved position.

In simulations with realistically dark star fields the app autofocus hit the optimum on average within 1–2 motor steps; without averaging several images it found no stars at all behind 3–7 nm filters. This has not been verified on a real device yet.

## Schedules

In the **“Schedules”** tab you build a sequence of steps:

- **Capture:** target from the GoTo tab, duration, minimum altitude (the plan waits until the target is high enough, at most 3 h, otherwise it is skipped; if it sinks below during the capture, the capture ends and the plan continues with the next step – the “expected” column shows this in advance), focus and LP filter.
- **Mosaic:** takes the settings from the “Mosaic” tab; each device calculates the panels with its own field of view.
- **Wait until time** and **Autofocus** as separate steps.

Focus per step: *automatic* (with an external filter the app autofocus, without filter the Seestar autofocus), Seestar autofocus, app autofocus, saved position or no focus. The list shows the expected time and the target’s altitude for each step. Plans can be saved (“Save”, “Save as …”) and reopened with **“Load …”**, started “now” or at a start time – the app always asks before starting (name, steps, end action), so that no plan starts by accident – on the active device or all ticked. Progress, reconnecting and resuming after an app restart work as for mosaics.

**At the end:** your choice – “Stop stacking, arm stays open” (default), “Park (close arm)” or “Park and power off”. The app remembers your last choice for new plans too. Devices with arm protection (filter or dew shield, see below) always end with the arm open, whatever is chosen. Mosaics always end with the arm open.

## Focus during capture

**Refocusing during the night:** as it cools down, focus shifts. In the “Schedules” (under “Run”) and “Mosaic” (grid) tabs you set when the app refocuses automatically: after 2 °C or 3 °C temperature change (default 2 °C), every 60/90/120 minutes, a combination or “Off”. It then pauses stacking briefly, focuses as set for the step (with an external filter the app autofocus, otherwise the Seestar autofocus) and **continues in the same stack** – like “Continue” in the Seestar app. The pause does not count towards the exposure time. There is no refocusing in the last 4 minutes of a step, for steps with “no focus”, or for the framing mosaic (the Seestar controls that itself).

**With an external filter** the app autofocus only searches a narrow range (± 30 steps) around the current position when refocusing, because focus shifts only slightly during the night. This roughly halves the pause – important for dark narrowband filters with long live exposures. If the optimum lies at the edge of this range or none is found, the app searches again over the full range (± 80). If that also fails (e.g. clouds), it goes to the last saved position for this filter. The first focus at the start of a target always uses the full range.

**Changing focus by hand while the Seestar is stacking:** like the Seestar app, the app asks beforehand whether it should **continue** afterwards (same stack) or **start again** – also for the autofocus button. Stacking is paused; a few seconds after the last focus change (or after the autofocus) it resumes as chosen. Further clicks during this time do not ask again.

The app does not take new dark frames for this: the Seestar makes its darks itself with the internal dark filter (the arm does not move), and with 10–30 s exposures retaking them brings little. Dithering and individual frames for Siril are the more effective tools.

## Filter database (2")

In the “Focus & Filter” tab you choose **brand** and **model** – 185 filters from 19 brands available in a 2" mount that fit in front of every Seestar (S30, S30 Pro, S50, S50 Pro) with a 2" filter holder: broadband, UHC, dual/tri/quad-band, narrowband, luminance, clear, R/G/B, IR-pass, moon/ND, photometric and special filters. If yours is missing, create it with **“Custom filter …”** (brand, model, type, narrowest bandwidth) – it is saved and treated the same way.

From type and bandwidth the app derives the **brightness** and sets the app autofocus accordingly (live-image exposure × averaged images): bright 1 s × 1 · medium 2 s × 2 · dark 3 s × 3 · very dark 5 s × 6.

Good to know for the Seestar (colour sensor):
- **Dual-, tri- and quad-band filters** are the right choice for nebulae: every colour channel gets light.
- **Single-line filters** (only Hα, OIII or SII) let only part of the colour pixels work – the image becomes monochrome and much darker. They are therefore rated one level darker.
- **Visual nebula filters** (Lumicon, Explore Scientific, Orion UltraBlock …) work, but are often too broad for imaging and can show reflections.
- With narrowband filters the app recommends **switching off the internal LP/dual-band filter** – filtering twice only costs light.
- **S50 / S50 Pro:** 2" filters usually have a clear aperture of about 46–48 mm and stop down the 50 mm aperture very slightly. **S30 / S30 Pro:** fully covered.

“Data: manufacturer” means the bandwidth comes from a checked manufacturer specification. “Trade” is the usual type designation – ranges and values change; when in doubt, your filter’s data sheet applies. Solar filters do not belong here: for the sun always use the Seestar’s matching objective solar filter.

<details><summary>Show a selection of filters</summary>

| Brand | Model | Type | Passband | Brightness | Data |
|---|---|---|---|---|---|
| Optolong | L-Pro | Broadband LP | broadband, suppresses sodium/mercury lines | bright | trade |
| Optolong | L-eNhance | Tri-band | Hα 10 nm · Hβ+OIII approx. 24 nm | dark | trade |
| Optolong | L-eXtreme | Dual-band | Hα 656.3 + OIII 500.7 nm, 7 nm each | dark | manufacturer |
| Optolong | L-eXtreme F2 | Dual-band | Hα + OIII 7 nm each, for very fast optics | dark | manufacturer |
| Optolong | L-Ultimate | Dual-band | Hα + OIII 3 nm each | very dark | manufacturer |
| Optolong | L-Synergy | Dual-band | SII + OIII 7 nm each | dark | manufacturer |
| Optolong | L-Para | Dual-band | Hα + OIII 10 nm each | dark | manufacturer |
| Optolong | L-QEF (L-Quad Enhance) | Quad-band | Hβ, OIII, Hα, SII – broad bands | medium | manufacturer |
| Optolong | CLS | Broadband LP | City Light Suppression | bright | trade |
| Optolong | CLS-CCD | Broadband LP | City Light Suppression with IR cut | bright | trade |
| Optolong | UHC | Nebula filter (UHC) | Hβ+OIII and Hα | medium | trade |
| Optolong | Moon & Skyglow | Broadband LP | neodymium type, suppresses sodium light | bright | trade |
| Optolong | UV/IR-Cut | UV/IR cut | blocks UV and IR | bright | manufacturer |
| Optolong | H-Alpha 7 nm | Single line | Hα 7 nm | very dark | trade |
| Optolong | H-Alpha 3 nm | Single line | Hα 3 nm | very dark | manufacturer |
| Optolong | OIII 6.5 nm | Single line | OIII 6.5 nm | very dark | trade |
| Optolong | OIII 3 nm | Single line | OIII 3 nm | very dark | manufacturer |
| Optolong | SII 6.5 nm | Single line | SII 6.5 nm | very dark | trade |
| Optolong | SII 3 nm | Single line | SII 3 nm | very dark | manufacturer |
| Optolong | H-Beta | Single line | Hβ (mainly visual) | very dark | trade |
| Svbony | SV220 Hα/OIII 7 nm | Dual-band | Hα 656 + OIII 501 nm, 7 nm each | dark | manufacturer |
| Svbony | SV220 Hα/OIII 3 nm | Dual-band | Hα + OIII 3 nm each | very dark | manufacturer |
| Svbony | SV220 SII/OIII 7 nm | Dual-band | SII + OIII 7 nm each | dark | manufacturer |
| Svbony | UHC | Nebula filter (UHC) | Hβ+OIII and Hα | medium | trade |
| Svbony | CLS | Broadband LP | City Light Suppression | bright | trade |
| Antlia | ALP-T Dual Band 5 nm | Dual-band | Hα + OIII 5 nm each | dark | manufacturer |
| Antlia | ALP-T Dual Band 3 nm | Dual-band | Hα + OIII 3 nm each | very dark | manufacturer |
| Antlia | Triband RGB Ultra (II) | Tri-band | Hα+NII, SII, OIII | medium | manufacturer |
| Antlia | Quad Band Anti-Light-Pollution | Quad-band | four nebula lines, broad | medium | manufacturer |
| Antlia | V-Pro | Broadband LP | broadband light-pollution filter | bright | trade |
| Antlia | H-Alpha 3 nm Pro | Single line | Hα 3 nm | very dark | trade |
| Antlia | OIII 3 nm Pro | Single line | OIII 3 nm | very dark | trade |
| Antlia | SII 3 nm Pro | Single line | SII 3 nm | very dark | trade |
| Antlia | H-Beta 3 nm Pro | Single line | Hβ 3 nm | very dark | manufacturer |
| Antlia | H-Alpha 2.5 nm Ultra | Single line | Hα 2.5 nm | very dark | manufacturer |
| Antlia | OIII 2.5 nm Ultra | Single line | OIII 2.5 nm | very dark | manufacturer |
| ZWO | Duo-Band | Dual-band | Hα 15 nm + OIII 35 nm | medium | manufacturer |
| ZWO | H-Alpha 7 nm | Single line | Hα 7 nm | very dark | trade |
| ZWO | OIII 7 nm | Single line | OIII 7 nm | very dark | trade |
| ZWO | SII 7 nm | Single line | SII 7 nm | very dark | trade |
| ZWO | UV/IR-Cut | UV/IR cut | blocks UV and IR | bright | trade |
| ZWO | IR-Cut | UV/IR cut | blocks IR | bright | trade |
| IDAS | LPS-D1 | Broadband LP | broadband LP, IR cut | bright | manufacturer |
| IDAS | LPS-D2 | Broadband LP | broadband LP for LED light, IR cut | bright | manufacturer |
| IDAS | LPS-D3 (NGS1) | Broadband LP | broadband LP, IR cut | bright | manufacturer |
| IDAS | LPS-P2 | Broadband LP | broadband LP | bright | manufacturer |
| IDAS | LPS-V4 | Nebula filter (UHC) | nebula filter, IR cut | medium | manufacturer |
| IDAS | NB1 | Tri-band | Hα, Hβ, OIII | medium | manufacturer |
| IDAS | NB2 | Dual-band | Hα + OIII, 20 nm | medium | manufacturer |
| IDAS | NB3 | Dual-band | OIII + SII, 20 nm | medium | manufacturer |
| IDAS | NBZ | Dual-band | Hα + OIII/Hβ, 12 nm | dark | manufacturer |
| STC | Astro Duo-Narrowband | Dual-band | Hα + OIII, 7–12 nm | dark | manufacturer |
| STC | Astro-Multispectra | Broadband LP | broadband LP | bright | trade |
| Altair | DualBand Hα/OIII 6 nm | Dual-band | Hα + OIII 6 nm each | dark | manufacturer |
| Altair | DualBand 4.5 nm | Dual-band | Hα + OIII 4.5 nm each | very dark | manufacturer |
| Altair | DualBand Ultra SII/OIII 4 nm | Dual-band | SII + OIII 4 nm each | very dark | manufacturer |
| Altair | TriBand V2 | Tri-band | Hα · Hβ+OIII | medium | manufacturer |
| Altair | QuadBand V2 | Quad-band | 495 nm and 660 nm, 35 nm each | medium | manufacturer |
| Radian | Triad Ultra | Quad-band | Hβ 5 nm, OIII 4 nm, Hα 4 nm, SII 4 nm | dark | manufacturer |
| Askar | Colour Magic C1 (Hα+OIII) | Dual-band | Hα + OIII, broad | medium | manufacturer |
| Askar | Colour Magic C2 (SII+OIII) | Dual-band | SII 15 nm + OIII 35 nm | medium | manufacturer |
| Askar | Colour Magic D1 (Hα+OIII) | Dual-band | OIII 6.5 nm + Hα 8.5 nm | dark | manufacturer |
| Askar | Colour Magic D2 (SII+OIII) | Dual-band | OIII 6.5 nm + SII 8.5 nm | dark | manufacturer |
| Askar | Colour Magic Ultra E1 (Hα+OIII) | Dual-band | Hα + OIII 3 nm each | very dark | manufacturer |
| Askar | Colour Magic Ultra E2 (SII+OIII) | Dual-band | SII + OIII 3 nm each | very dark | manufacturer |
| Baader | UHC-S | Nebula filter (UHC) | nebula filter, fairly broad | medium | trade |
| Baader | Moon & Skyglow | Broadband LP | neodymium, suppresses sodium light | bright | trade |
| Baader | Neodymium | Broadband LP | neodymium, suppresses sodium light | bright | trade |
| Baader | UV/IR-Cut L | UV/IR cut | blocks UV and IR | bright | manufacturer |
| Baader | H-Alpha 6.5 nm CMOS | Single line | Hα 6.5 nm | very dark | trade |
| Baader | OIII 6.5 nm CMOS | Single line | OIII 6.5 nm | very dark | trade |
| Baader | SII 6.5 nm CMOS | Single line | SII 6.5 nm | very dark | trade |
| Baader | H-Alpha Ultra-Narrowband CMOS | Single line | Hα 656.3 nm, 3.5–4 nm | very dark | manufacturer |
| Baader | OIII Ultra-Narrowband CMOS | Single line | OIII 500.7 nm, 3.5–4 nm | very dark | manufacturer |
| Baader | SII Ultra-Narrowband CMOS | Single line | SII 671.7 nm, 3.5–4 nm | very dark | manufacturer |
| Astronomik | CLS | Broadband LP | City Light Suppression | bright | manufacturer |
| Astronomik | CLS-CCD | Broadband LP | City Light Suppression with IR cut | bright | manufacturer |
| Astronomik | UHC | Nebula filter (UHC) | nebula filter | medium | manufacturer |
| Astronomik | UHC-E | Nebula filter (UHC) | nebula filter, somewhat broader | medium | manufacturer |
| Astronomik | L-1 UV-IR Block | UV/IR cut | blocks UV and IR | bright | trade |
| Astronomik | L-2 UV-IR Block | UV/IR cut | blocks UV and IR | bright | trade |
| Astronomik | L-3 UV-IR Block | UV/IR cut | blocks UV and IR | bright | trade |
| Astronomik | H-Alpha 6 nm (also MaxFR) | Single line | Hα 6 nm | very dark | manufacturer |
| Astronomik | OIII 6 nm (also MaxFR) | Single line | OIII 6 nm | very dark | manufacturer |
| Astronomik | SII 6 nm (also MaxFR) | Single line | SII 6 nm | very dark | manufacturer |
| Astronomik | H-Alpha 12 nm (also MaxFR) | Single line | Hα 12 nm | very dark | manufacturer |
| Astronomik | OIII 12 nm (also MaxFR) | Single line | OIII 12 nm | very dark | manufacturer |
| Astronomik | SII 12 nm (also MaxFR) | Single line | SII 12 nm | very dark | manufacturer |
| Lumicon | UHC | Nebula filter (UHC) | nebula filter (visual) | medium | trade |
| Lumicon | OIII | Single line | OIII, broad (visual) | very dark | trade |
| Lumicon | H-Beta | Single line | Hβ, broad (visual) | very dark | trade |
| Explore Scientific | UHC | Nebula filter (UHC) | nebula filter (visual) | medium | trade |
| Explore Scientific | OIII | Single line | OIII, broad (visual) | very dark | trade |
| Celestron | UHC/LPR | Nebula filter (UHC) | nebula filter | medium | trade |
| Orion | UltraBlock | Nebula filter (UHC) | nebula filter (visual) | medium | trade |
| Orion | SkyGlow | Broadband LP | broadband LP | bright | trade |
| Omegon | UHC | Nebula filter (UHC) | nebula filter | medium | trade |
| Omegon | CLS | Broadband LP | City Light Suppression | bright | trade |
| TS-Optics | UHC | Nebula filter (UHC) | nebula filter | medium | trade |
| TS-Optics | CLS | Broadband LP | City Light Suppression | bright | trade |

</details>

## Arm protection with an external filter or dew shield

With a 2" filter holder or a dew shield in front of the lens the Seestar cannot close its arm – the motor would drive against it. As soon as you enter a filter in the “Focus & Filter” tab or tick **“Dew shield fitted”** or **“Other accessory in front of the lens”**, **arm protection** switches on for this device (per device, also entirely without a filter):

- Parking, power-off, restart and switching Alt-Az ↔ EQ (which parks) are **blocked directly in the connection** – whether from a tab, a plan, a mosaic or the console. Anyone who triggers it anyway is asked whether the filter has been removed.
- Schedules on this device always end with the arm open, even if “Park” is set; other devices park as chosen.
- Switched off on the device: *Automatic power-off* and *Close arm after Seestar plan* (for plans from the Seestar app); with a filter also *Smart AF* and *Autofocus before stacking* (these fail behind narrowband filters). With a dew shield or other accessory but no filter, autofocus stays unchanged. While protection is active, *Automatic power-off* and *Close arm after Seestar plan* cannot be switched back on – and while a filter is entered, neither can the Seestar autofocus (the app then points you to its own autofocus).
- At 20 % and 10 % battery the app warns: if the Seestar powers off by itself because the battery is empty, it may close the arm – no app can prevent that.

In the Overview, protected devices show “[Arm protection]”. Filter or dew shield removed? Choose “No external filter” in the “Focus & Filter” tab or untick “Dew shield fitted” – the app then asks whether arm protection should be turned off.

## EQ mode (wedge)

In EQ mode the Seestar can expose up to **60 s per frame** – no more. In Alt-Az mode the maximum is 30 s; the app does not allow 60 s there at all (not even when copying settings to other devices).

The **“EQ mode”** tab guides you through setup and checks in three steps, each for the active device:

1. **Levelling & wedge:** “Live measurement” shows the built-in tilt sensor as a bubble level (green < 0.5°, yellow < 1°). Below it is the wedge angle from your latitude (“Location” tab) – for scales measured from the horizon and from the vertical, because wedges label this differently. Switching Alt-Az ↔ EQ is done with the buttons at the top; the Seestar moves to the park position for this.
2. **Polar alignment (3-point):** choose a start position (1 = near, 5 = far; 3 is the default, use another one if there are obstacles), “Measure error”. The target display shows the error in altitude and azimuth; the last measurements are joined by a dashed line. With “re-measure automatically” the app measures again after each measurement while you turn the altitude/azimuth knobs – until both axes are below 0.5°. The Seestar app already accepts < 1°.
3. **Checks & tests:** traffic-light checklist (EQ mode, tilt, polar alignment, exposure) and a **tracking test**: slew to a target, choose exposure (20/30/60 s) and duration, start. The app counts stacked and rejected frames and tells you whether the exposure is fine (≥ 90 % good frames), borderline, or whether you should expose shorter or align better. Afterwards the previous exposure is restored.

Note: the meaning of the tilt sensor’s raw values (X/Y in degrees) comes from community analyses of the firmware. Compare once with a spirit level. If the bubble shows a small constant offset with the Seestar exactly level, **“Set zero point”** stores the current value as zero (per device; “Clear zero point” removes it).

## Model selection

At the top right you choose the model of the active device (S30, S30 Pro, S50, S50 Pro). With “detect when connecting” the app reads the model from the Seestar automatically and sets drop-downs, filter label and model data (optics, sensor, field of view) accordingly. At the same time the current settings are taken over from the device.

The “recommended values” are starting values (10 s, gain 80, standard dithering, internal filter off). 60 s exposure only works in EQ mode with polar alignment.

## Preview image

The “Preview” tab connects to the Seestar’s image channel (TCP port 4800). “Live preview” shows the running single frames (debayered at half resolution), “Get stack image” the current stacked image. With the tick box on, the stack image is reloaded automatically after every new frame. The display is only stretched for the screen – the raw data on the Seestar stays untouched. If no view is running on the Seestar (e.g. after a plan has ended), “Live” starts star mode itself (asking first if the arm is closed); if no new image arrives for a while, the app requests one itself and shows “waiting for a new image …”.

## Wi-Fi: putting the Seestar on your home network

Easiest in **station mode**: in the Seestar app enter your home network under the Wi-Fi settings. The Seestar is then in the same network as the PC; you see the IP in your router or in the app. Alternatively the PC connects directly to the Seestar hotspot (then usually `10.0.0.1`).

Control runs via JSON-RPC on TCP port 4700, images via TCP port 4800, discovery via UDP port 4720. Allow them in the Windows firewall if necessary.

## Access data per Seestar (Wi-Fi name and password)

Each Seestar has its own Wi-Fi with a name like `S50_1a2b3c4d` (or `S30_…`) and a password – `12345678` from the factory, changeable in the Seestar app under the device. In the Overview, **“Access data …”** (box “Active device”) opens for each device:

- **Device name** in the app and **IP address**
- **Connection:** *Home network* (Seestar and PC in the same Wi-Fi, recommended and required for several devices at once) or *Direct* (the PC connects to the Seestar’s Wi-Fi, address then usually `10.0.0.1`; only works with one Seestar at a time, because a PC can only be in one Wi-Fi)
- **Wi-Fi name** and **Wi-Fi password** of the Seestar

With “Direct” the app connects the PC (Windows) to the Seestar Wi-Fi automatically when connecting, also when reconnecting automatically; “Connect PC to this Wi-Fi now” does it immediately. When a device is connected, the app reads the Wi-Fi name and password from the Seestar itself (`pi_get_ap`) and shows which home network it is in (`pi_station_state`).

On Windows the password is stored with Windows data protection (DPAPI) – readable only by your Windows user account. Note: newer Windows 11 versions require location access for desktop apps for Wi-Fi commands; the app tells you if this is missing.

Putting the Seestar on your home network (station mode) still has to be done in the Seestar app.

## Important: login with newer firmware

From firmware 6.45, and mandatory from about 7.18, the Seestar requires a challenge-response login with an RSA key from the official Seestar Android app. This key is **not** included – it belongs to ZWO.

How to get it: the **seestar_alp** project (github.com/smart-underworld/seestar_alp) has a “Seestar tool” with an **Extract PEM** function that extracts the key from the APK of your Seestar app. Then select the `.pem` file in the “PEM key” field.

Without a key the app still connects, but newer firmware then rejects most commands.

## Bluetooth: what is realistic

The Seestar uses BLE only for waking up and for the initial Wi-Fi setup. ZWO has not published this protocol, and there is no public documentation for it so far. The Bluetooth tab is therefore an explorer: connect, list all characteristics, read, write, log notifications. The actual telescope control (GoTo, stacking etc.) runs over Wi-Fi.

On Windows, Bluetooth needs Windows 10 (version 1709) or newer and a BLE-capable adapter.

## ZWO ASIAIR

ASIAIR control is available as a separate edition, **“ASIAIR Control Center”** (own folder, start it with its own `start.bat`). In the Seestar program the ASIAIR tabs are hidden.

## Notes

- The joystick directions (0° = right, 90° = up …) follow the community convention. If they are swapped for you, let me know and I will adjust the angles.
- With an external filter (e.g. Hα/OIII) leave the internal LP filter switched off for GoTo.
- ZWO occasionally changes the protocol with firmware updates. If something stops working after an update, first look for error codes in the log window.

## Program name & authenticity

The name **“Star Gazing Control Center by TheSkyCoder”** belongs to the program and must not be changed (see `LICENSE.md`).

Every version released by the author is digitally signed (file `SIGNATUR.txt`). On start the program checks whether program code, object catalogue and included language files are unchanged. If the signature does not match – because something was changed, the name was altered or a file was removed – the addition **“(modified)”** appears after the name everywhere, in the selected language (e.g. “(modifiziert)”, “(modifié)”). The name appears without the addition only in versions signed with the author’s private key.

A language file you add yourself to the `lang` folder does not count as a change.

Note: the check makes changes visible, but it cannot technically stop someone who deliberately rewrites the program code. Legally, the licence applies.
