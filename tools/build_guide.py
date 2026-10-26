#!/usr/bin/env python3
"""Create the public PDF guide. Does not start the bridge or contact a radio."""

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output/pdf/Satellite-Bridge-Guide-1.0.6.pdf"
W, H = A4
LEFT, RIGHT = 44, W - 44
WIDTH = RIGHT - LEFT
INK = colors.HexColor("#173448")
TEAL = colors.HexColor("#147780")
MUTED = colors.HexColor("#526778")
PALE = colors.HexColor("#edf5f6")
AMBER = colors.HexColor("#fff0cb")
STYLES = {
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=14, textColor=INK, alignment=TA_LEFT, spaceAfter=0),
    "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8.5, leading=11.5, textColor=MUTED),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=9, leading=12, textColor=INK),
    "headcell": ParagraphStyle("headcell", fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=colors.white),
}


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUTPUT), pagesize=A4, invariant=1)
    c.setTitle("Satellite Bridge - Purpose and User Guide - 1.0.6")
    c.setAuthor("Matthias Peter")
    c.setSubject("MacDoppler UDP to RUMlogNG TRX2, with RUMlogNG as sole IC-9700 CAT controller")
    page_no, y = 0, 0

    def text(value, style="body", after=8):
        nonlocal y
        p = Paragraph(value, STYLES[style])
        _, height = p.wrap(WIDTH, H)
        if y - height < 58:
            raise RuntimeError(f"PDF page {page_no} overflow at {value[:60]}")
        p.drawOn(c, LEFT, y - height)
        y -= height + after

    def section(value):
        nonlocal y
        y -= 6
        c.setFillColor(TEAL)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(LEFT, y, value)
        y -= 20

    def table(rows, widths):
        nonlocal y
        data = [[Paragraph(escape(str(v)), STYLES["headcell" if i == 0 else "cell"]) for v in row] for i, row in enumerate(rows)]
        t = Table(data, colWidths=widths, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), TEAL),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LINEBELOW", (0, 0), (-1, 0), .6, TEAL),
        ]))
        _, height = t.wrap(WIDTH, H)
        if y - height < 58:
            raise RuntimeError(f"PDF page {page_no} table overflow")
        t.drawOn(c, LEFT, y - height)
        y -= height + 12

    def callout(title, value):
        nonlocal y
        p = Paragraph(f"<b>{title}</b><br/>{value}", STYLES["body"])
        _, height = p.wrap(WIDTH - 24, H)
        height += 22
        c.setFillColor(AMBER)
        c.roundRect(LEFT, y - height, WIDTH, height, 7, fill=1, stroke=0)
        p.drawOn(c, LEFT + 12, y - height + 11)
        y -= height + 12

    def page(title, subtitle):
        nonlocal page_no, y
        if page_no:
            c.showPage()
        page_no += 1
        c.setFillColor(TEAL)
        c.rect(0, H - 14, W, 14, fill=1, stroke=0)
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(TEAL)
        c.drawString(LEFT, H - 44, "SATELLITE BRIDGE  /  IC-9700")
        c.setFont("Helvetica-Bold", 23)
        c.setFillColor(INK)
        c.drawString(LEFT, H - 80, title)
        c.setFont("Helvetica", 10)
        c.setFillColor(MUTED)
        c.drawString(LEFT, H - 101, subtitle)
        c.setStrokeColor(colors.HexColor("#dce6eb"))
        c.line(LEFT, 43, RIGHT, 43)
        c.setFont("Helvetica", 8)
        c.drawString(LEFT, 29, "1.0.6 public preview  |  Matthias Peter  |  26 October 2026")
        c.drawRightString(RIGHT, 29, f"{page_no} / 7")
        y = H - 128

    page("Why this app exists", "One CAT owner. Deliberate source selection. Independent RX and TX.")
    text("My IC-9700 is already <b>TRX2 in RUMlogNG</b>. I wanted RUMlogNG to remain the sole application connected to its CAT/USB port while MacDoppler supplied satellite frequencies upstream.")
    section("QO-100 is the home operating environment")
    text("Named pairs cover digital operation, different SSB meeting frequencies and CW. One click applies a pair once; afterward, manual radio tuning remains possible. Pair editing belongs in Settings, keeping Operations compact.")
    section("Check a LEO without surrendering the home setup")
    text("MacDoppler can track and broadcast in the background while I operate on QO-100. Its packets are displayed but blocked until I select MacDoppler. Returning to a QO-100 row revokes that authority and applies the selected pair once.")
    section("The signal path")
    box_width, gap = (WIDTH - 27) / 4, 9
    labels = [("MacDoppler", "UDP 9932"), ("Bridge", "Source selection"), ("RUMlogNG", "TRX2 / TCP 7400"), ("IC-9700", "CAT / USB")]
    for i, (title, subtitle) in enumerate(labels):
        x = LEFT + i * (box_width + gap)
        c.setFillColor(PALE if i != 2 else TEAL)
        c.roundRect(x, y - 55, box_width, 55, 5, fill=1, stroke=0)
        c.setFillColor(colors.white if i == 2 else INK)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(x + box_width / 2, y - 21, title)
        c.setFont("Helvetica", 8)
        c.drawCentredString(x + box_width / 2, y - 39, subtitle)
        if i < 3:
            c.setStrokeColor(TEAL)
            c.line(x + box_width + 1, y - 27, x + box_width + gap - 1, y - 27)
    y -= 72
    text("The bridge also uses RUMlogNG's panel through macOS Accessibility for VFO modes, tones, receiver settings, SAT, RF power, RX filters and feedback. It never opens the radio's serial device.", "small")
    section("Independent frequencies and converter protection")
    text("Downlink controls RX; uplink controls TX. Neither is calculated from the other. The QO-100 TX output feeds a converter, so this mode requires a maximum RF power setting of <b>5%</b>. The guard is software with feedback latency, not a hardware RF limiter.")

    page("Operations at a glance", "An actual screenshot of version 1.0.4 on the original station.")
    image = ImageReader(str(ROOT / "docs/images/satellite-bridge-1.0.4.png"))
    iw, ih = image.getSize()
    image_height = WIDTH * ih / iw
    c.drawImage(image, LEFT, y - image_height, width=WIDTH, height=image_height, mask="auto")
    y -= image_height + 16
    text("QO-100 Digital is selected, all four saved pairs remain available, and the readback shows RX 433.540000 MHz / TX 144.040000 MHz with power at 4%. The source button and banner identify QO-100 authority; MacDoppler is blocked.")
    text("The packet feed is open. No MacDoppler packets were arriving at capture time, so the screenshot is not evidence of an active UDP test. Separate live tests are summarized later in this guide.", "small")

    page("Install and connect", "Intel app with bundled Python/Tk; no Terminal needed for normal operation.")
    text("Download the Intel ZIP from the GitHub release, extract it, and copy <b>Satellite Bridge.app</b> into an Applications folder. Add it to the Dock if desired.")
    callout("First launch on a different station", "The example pairs are the original station's dial/transverter IF values. Keep RUMlogNG closed while first editing them in Settings. Retain exactly one pair named <b>Digital</b>. Every subsequent new launch applies Digital automatically once access and power verification are ready.")
    table([
        ["Connection", "Setting"],
        ["MacDoppler to bridge", "UDP 127.0.0.1:9932"],
        ["Bridge to RUMlogNG TRX2", "TCP 127.0.0.1:7400"],
        ["RUMlogNG to IC-9700", "Existing CAT/USB connection; RUMlogNG owns it"],
    ], [205, WIDTH - 205])
    text("<b>RUMlogNG:</b> configure the IC-9700 as TRX2, enable its DXLab Commander server on TCP 7400, and make the ICOM IC-9700 control window available.")
    text("<b>MacDoppler:</b> select the UDP Broadcast radio driver, set address 127.0.0.1 and port 9932, and enable Radio output. Do not add another direct CAT connection to this radio.")
    text("<b>macOS:</b> enable Satellite Bridge under System Settings &gt; Privacy &amp; Security &gt; Accessibility. This release is ad-hoc signed, not Developer ID signed or notarized; a downloaded copy can be blocked. See Apple's guidance linked on the last page.")
    section("Supplied dial-frequency examples")
    table([
        ["Pair", "RX MHz", "TX MHz", "Both modes"],
        ["Digital", "433.540000", "144.040000", "USB-D"],
        ["SSB HB Amsat", "433.740000", "144.240000", "USB"],
        ["SSB DX", "433.900000", "144.400000", "USB"],
        ["CW", "433.512000", "144.012000", "CW"],
    ], [154, 115, 115, WIDTH - 384])
    text("These are IC-9700 IF/dial values, not 10 GHz / 2.4 GHz frequencies. No transverter offset is inferred.", "small")

    page("Daily operation", "QO-100 writes once. MacDoppler forwards its continuing Doppler corrections.")
    section("QO-100")
    text("Click a saved row. SAT stays enabled for native manual dial tracking. The bridge stops alternating polling, selects Main/RX and Sub/TX in turn, writes each frequency once and sets its mode/Data buttons. It verifies each side, restores the prior control view and polling, and never retries frequencies automatically.")
    text("Manual tuning is left alone and appears in RUMlogNG readback. USB/USB-D select <b>RX filter 1</b>; CW/CW-R select <b>RX filter 2</b>. The same RX rule applies to MacDoppler-imposed modes. The TX filter is not changed.")
    section("MacDoppler")
    text("Click MacDoppler to forward its live downlink and uplink independently. Only changed fields are sent during ongoing corrections. A cached report is accepted for up to eight seconds; otherwise the app waits. Invalid or same-band On Exit reports are rejected.")
    text("Frequency-only corrections may continue during operator-keyed TX. Source/mode changes wait for PTT release. The app has no PTT-on or PTT-off operation. Use MacDoppler's own tuning aids during passes; UDP does not supply radio-dial tracking.")
    section("Return, pause and observe")
    text("Select any QO-100 row to block MacDoppler again and apply that pair once. Pause tuning stops frequency/mode writes while feedback and packet display continue. Use the packet checkbox to show actual incoming messages with forwarded/blocked/rejected labels.")
    section("Power is separate from tuning")
    text("The 5% QO-100 ceiling is verified before tuning, checked afterward and monitored while QO-100 remains selected, including while paused. The tested radio commonly reports 4% after a 5% request.")
    text("Temporary power-read failures hold output and retry verification. A pending selection that has sent no tuning commands can then be sent once. A batch already sent is never replayed by power recovery. An explicit Pause or source change takes precedence.")
    section("Readback is not command history")
    text("The main line displays values read from RUMlogNG's panel, normally each second. Missing data says waiting; old data is marked stale. Missing TX modes are not invented. A QO-100 selection is checked for stable feedback, but a mismatch never triggers automatic retuning.")

    page("Split, tones and RX profiles", "Explicit controls; the radio connection still belongs to RUMlogNG.")
    section("QO-100 virtual split")
    table([
        ["TX mode", "Selectable positive offset"],
        ["USB / USB-D", "Off, +5, +10 or +15 kHz"],
        ["CW / CW-R", "Off, +1, +2 or +3 kHz"],
    ], [155, WIDTH - 155])
    text("Enabling split saves the actual TX frequency, including manual tuning since the preset. Each choice uses that same base; offsets never stack. <b>Off restores the saved TX base exactly.</b> RX, modes and filters are preserved. A new preset or MacDoppler selection clears split state.")
    text("Example: a manually tuned base of 144.040220 MHz gives 144.045220 at +5 kHz and 144.050220 at +10 kHz. Off restores 144.040220. Release PTT before changing split. Normal app startup still selects Digital.", "small")
    section("Receiver and power profiles")
    table([
        ["Source", "RX front end", "TX power"],
        ["QO-100", "ATT on; internal/external preamps off", "Maximum 5%"],
        ["MacDoppler", "ATT off; internal preamp on; external preamp for a 70 cm downlink", "Default 80%"],
    ], [95, 280, WIDTH - 375])
    text("MacDoppler's 80% default is applied after its TX frequency/mode verifies, on entry or a TX band/mode change. Frequency-only corrections preserve subsequent manual power adjustment. QO-100 continues monitoring its 5% ceiling.")
    text("Receiver setup uses three exact receiver-only macros in unused RUMlogNG manual slots. Existing manual and automatic macros are preserved. These commands currently use default IC-9700 CI-V address A2. External-preamp activation is commanded; the external amplifier is not independently measured.", "small")
    section("TX CTCSS and RX tone squelch are separate")
    text("MacDoppler's Tone value controls the TX encoder through its panel popup/button. Its CTCSS/decode value controls RX TSQL separately. Zero disables the corresponding function; omission leaves it unchanged. SO-50's 74.4 and 67.0 Hz settings are passed as requested. The bridge never keys a transmission.")

    page("Evidence and limitations", "A station-tested preview, with current behavior described explicitly.")
    callout("Desktop access and polling", "Panel controls require an unlocked macOS session and Accessibility access. MacDoppler holds alternating polling off across its stream; QO-100 return restores the earlier setting. QO-100 feedback still enables Toggle. The bridge retains SAT and explicit Main/RX and Sub/TX control.")
    table([
        ["Test environment", "Observed configuration"],
        ["Computer", "Intel Mac; macOS 15.7.3"],
        ["Applications", "RUMlogNG 6.6.1; MacDoppler 2.48 reports; earlier checks also used 6.5.1"],
        ["Radio connection", "IC-9700 as RUMlogNG TRX2; USB at 19200 baud"],
        ["Bundled runtime", "Python 3.12.14; Tcl/Tk 9.0.4"],
    ], [172, WIDTH - 172])
    section("What was checked")
    text("<b>118 local tests</b> cover parsing, selected VFOs, independent modes, tones, receiver macros, power, RX filters, virtual split and failure recovery. These tests use simulated endpoints. A separate controlled UDP replay applied 13 updates to the real IC-9700 through RUMlogNG, including captured FO-29 reports and TX tone transitions.")
    text("The source check verified 80% MacDoppler defaults, RX filters without TX-filter changes, receiver profiles, both split ranges and exact base restoration. A +220 Hz QO-100 dial adjustment was preserved with no additional bridge setters. Installed build 10 also verified Digital/CW, SAT, 4% power and split/base restoration after Accessibility renewal. No over-the-air QSO or external-amplifier measurement is claimed.")
    section("Why stable confirmation matters")
    text("An Amsat selection briefly showed requested TX 144.240000 MHz, then RUMlogNG reported the previous 144.198770 MHz. No later bridge frequency setter appeared, and MacDoppler packets were blocked. A separate diagnostic TX setter restored 144.240000. The exact cause was not established.")
    text("The app now reports unconfirmed feedback without automatically resending frequencies. Readback is still RUMlogNG's report, not an independent CAT connection or RF measurement.")
    section("Permissions and saved data")
    text("Ad-hoc-signed executable updates may require removing and re-adding the app's Accessibility entry. Settings and rotating logs live outside the bundle in ~/Library/Application Support/Satellite Bridge/. App updates preserve saved pairs.")

    page("Planned next steps", "Terrestrial profiles remain planned; MacDoppler power defaults are implemented.")
    section("A third operating mode: Terrestrial")
    text("Add named repeater and simplex profiles with the same Settings editor / one-click Operations model as QO-100. Repeater entries hold RX (repeater output), TX (repeater input), duplex direction/offset including DUP-, mode, and a TX CTCSS opening tone or none.")
    text("Simplex entries use equal RX/TX frequencies and no duplex offset, with voice/data settings. One requested example is a <b>144.800 MHz packet-radio channel</b>. Selecting Terrestrial should disable SAT, block MacDoppler and apply the profile once, then allow manual tuning.")
    section("Current and planned power defaults")
    table([
        ["Mode", "Planned behavior"],
        ["QO-100", "Maximum 5%; verify before tuning and monitor"],
        ["MacDoppler", "Implemented: 80% after target verification on entry / TX band or mode change"],
        ["Terrestrial", "Default 80%, applied once on mode entry"],
    ], [155, WIDTH - 155])
    text("MacDoppler's 80% default is implemented in 1.0.6; terrestrial profiles and their default remain planned. Later manual MacDoppler power adjustment is preserved during frequency-only updates. QO-100 feedback still forces Toggle on; respecting its manual setting there remains pending.")
    section("Project, licensing and references")
    text('<link href="https://github.com/matpet/satellite-bridge" color="#147780"><b>github.com/matpet/satellite-bridge</b></link><br/>Source, setup guide, design rationale, validation summary, issues and releases.')
    text("Original bridge code and documentation: MIT, copyright 2026 Matthias Peter. Bundled Python, Tcl, Tk and the PyInstaller bootloader retain their own licenses; complete notices accompany the release.", "small")
    text('<link href="https://dl2rum.de/RUMlogNG/docs/en/pages/CAT-IC9700.html" color="#147780">RUMlogNG IC-9700 control documentation</link><br/>Recommends 115200 baud for USB. Both ends must be configured together; the bridge does not change baud rates.', "small")
    text('<link href="https://support.apple.com/en-us/102445" color="#147780">Apple: Safely open apps on your Mac</link><br/>Explains macOS handling of downloaded, unidentified or unnotarized apps.', "small")
    text("RUMlogNG, MacDoppler and Icom products are external interoperability targets and are not included in this release.", "small")
    c.save()
    print(OUTPUT)


if __name__ == "__main__":
    main()
