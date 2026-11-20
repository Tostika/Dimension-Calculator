# განზომილების საზომი მოწყობილობა (desktop app)

## Run it (Windows)
**Easiest:** open [Releases](https://github.com/Tostika/Dimension-Calculator/releases), download
`DimensionDevice-windows.zip`, unzip it and run `DimensionDevice.exe`. No Python needed.

**From the code:** install Python 3.11 or newer from python.org (tick "Add python.exe to PATH"),
then double-click `run.bat`. The first time it installs the libraries (needs internet, a few minutes).

Without the camera or the ESP32 plugged in, the app still opens: it shows a **demo camera**
(a drawn base with a phone on it) and a demo ESP32, so the whole flow can be tried.

## Project layout
```
main.py                     start here
app/i18n.py                 every label, Georgian and English  (fix wording here only)
app/theme.py                themes and the user's own colours
app/config.py               settings and their defaults (settings.json)
app/storage.py              library database (item1, item2, ... and renaming)
app/export.py               DXF and JSON files
app/vision/                 markers, measuring, lens calibration, demo scene
app/devices/                camera thread, ESP32 serial
app/ui/                     main window and the four tabs
firmware/esp32_dimension/   Arduino sketch for the ESP32
tools/make_markers.py       printable markers, height card, checkerboard
tools/freecad_import.FCMacro  turns an itemN.json into a FreeCAD solid
tests/                      python -m tests.test_vision   /   python -m tests.test_ui_smoke
```
Settings, the library (`library.db`), `calibration.json` and exports are kept in
`%APPDATA%\DimensionDevice`.

## Print the sheets
The PDFs in `print/` are made at exact size and the app is set up for exactly these sheets
(nothing to measure or learn). Print at **100 % / "Actual size"**, never "Fit to page", and check
the 100 mm line on each sheet with a ruler.
- `base_A3.pdf`: the base (A3, any print shop). Markers 0-3, 30 mm, centres 300 x 190 mm apart.
  Lay it flat and tape it down; the item goes inside the four markers.
- `height_card_A4.pdf`: the 100 x 70 mm height card (markers 4-7, 26 mm). Cut on the grey line, glue on
  a flat rigid plate, enter paper + plate thickness in Calibration > Height card.
- `checkerboard_A4.pdf`: lens calibration board. Glue it on cardboard so it stays flat.
To remake them: `python tools/make_markers.py`.

## ESP32
Open `firmware/esp32_dimension/esp32_dimension.ino` in Arduino IDE, board "ESP32 Dev Module", upload.
Pins: LED PWM 25, STEP 26, DIR 27, EN 14, limit switch 33 (to GND). After building, measure the lens
height above the base when the limit switch clicks and put it in `Z_HOME_MM`.

## New release
Change the number in `VERSION` (for example to `0.2.0`) and push to main. GitHub Actions builds
`DimensionDevice.exe` on Windows, creates the Release `v0.2.0` and attaches
`DimensionDevice-windows.zip` (app, print sheets, firmware, FreeCAD macro) to a new Release.
