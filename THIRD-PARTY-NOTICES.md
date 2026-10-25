# Third-party notices

The bridge's original code and documentation use the root MIT license. The packaged macOS application includes runtime components under their respective licenses:

| Component | Version used | Notice |
| --- | --- | --- |
| CPython / standard library | 3.12.14 | [Python license and included notices](docs/licenses/Python-3.12.14.txt) |
| Tcl | 9.0.4 | [Tcl license](docs/licenses/Tcl-9.0.4.txt) |
| Tk | 9.0.4 | [Tk license](docs/licenses/Tk-9.0.4.txt) |
| PyInstaller bootloader | 6.22.3 | [PyInstaller license and bootloader exception](docs/licenses/PyInstaller-6.22.3.txt) |

RUMlogNG, MacDoppler, Icom firmware and macOS are external requirements, not redistributed with this project. Their names identify interoperability targets; this project is independent of those products.

The macOS release ZIP includes these complete license files alongside the app. PyInstaller and ReportLab are build/documentation tools, not new runtime Python dependencies of the bridge source.
