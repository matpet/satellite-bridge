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
OUTPUT = ROOT / "output/pdf/Satellite-Bridge-Guide-1.0.5.pdf"
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
    c.setTitle("Satellite Bridge - Purpose and User Guide - 1.0.5")
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
        c.drawString(LEFT, 29, "1.0.5 public preview  |  Matthias Peter  |  26 October 2026")
        c.drawRightString(RIGHT, 29, f"{page_no} / 6")
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
    text("The bridge also uses RUMlogNG's panel through macOS Accessibility for SAT, RF power, the RX filter and feedback. It never opens the radio's serial device.", "small")
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
    text("Click a saved row. The bridge selects QO-100 authority, cancels pending MacDoppler work, and sends one batch of RX/TX frequencies and modes. It then checks feedback without a frequency retry. Selecting the row again is an explicit request to reapply it.")
    text("Manual tuning is left alone and appears in RUMlogNG readback. USB/USB-D select <b>RX filter 1</b>; CW/CW-R select <b>RX filter 2</b>. The TX filter is not changed.")
    section("MacDoppler")
    text("Click MacDoppler to forward its live downlink and uplink independently. Only changed fields are sent during ongoing corrections. A cached report is accepted for up to eight seconds; otherwise the app waits. Invalid or same-band On Exit reports are rejected.")
    text("Frequency-only corrections may continue during operator-keyed TX. Source/mode changes wait for PTT release. The app has no PTT-on or PTT-off operation. CTCSS fields are not forwarded in 1.0.5.")
    section("Return, pause and observe")
    text("Select any QO-100 row to block MacDoppler again and apply that pair once. Pause tuning stops frequency/mode writes while feedback and packet display continue. Use the packet checkbox to show actual incoming messages with forwarded/blocked/rejected labels.")
    section("Power is separate from tuning")
    text("The 5% QO-100 ceiling is verified before tuning, checked afterward and monitored while QO-100 remains selected, including while paused. The tested radio commonly reports 4% after a 5% request.")
    text("Temporary power-read failures hold output and retry verification. A pending selection that has sent no tuning commands can then be sent once. A batch already sent is never replayed by power recovery. An explicit Pause or source change takes precedence.")
    section("Readback is not command history")
    text("The main line displays values read from RUMlogNG's panel, normally each second. Missing data says waiting; old data is marked stale. Missing TX modes are not invented. A QO-100 selection is checked for stable feedback, but a mismatch never triggers automatic retuning.")

    page("Evidence and limitations", "A station-tested preview, with current behavior described explicitly.")
    callout("Known issue in 1.0.5: Toggle", "Feedback reads automatically enable RUMlogNG's Toggle control. Turning it off manually is not preserved. Removing this override is planned. QO-100 frequency/mode writes are one-shot, but the overall feedback path is not completely free of control actions.")
    table([
        ["Test environment", "Observed configuration"],
        ["Computer", "Intel Mac; macOS 15.7.3"],
        ["Applications", "Repair: RUMlogNG 6.6.1; earlier UDP: 6.5.1 / MacDoppler 2.48"],
        ["Radio connection", "IC-9700 as RUMlogNG TRX2; USB at 19200 baud"],
        ["Bundled runtime", "Python 3.12.14; Tcl/Tk 9.0.4"],
    ], [172, WIDTH - 172])
    section("What was checked")
    text("<b>60 local tests</b> use simulated endpoints/control models, including compact VFO labels, omitted fields and selected-VFO mode fallback. Earlier live UDP tests separately used operator confirmation of independent RX/TX changes. No new live UDP test was performed for 1.0.5.")
    text("The installed 1.0.5 build passed Digital startup with exactly four tuning setters: frequency and mode per side. Feedback verified 433.540000 / 144.040000 MHz, RX filter 1, SAT on and power 4%, with no repeated setters. Placeholder RX mode was checked from the selected-VFO buttons for filter verification; unavailable mode text remains unknown.")
    section("Why stable confirmation matters")
    text("An Amsat selection briefly showed requested TX 144.240000 MHz, then RUMlogNG reported the previous 144.198770 MHz. No later bridge frequency setter appeared, and MacDoppler packets were blocked. A separate diagnostic TX setter restored 144.240000. The exact cause was not established.")
    text("The app now reports unconfirmed feedback without automatically resending frequencies. Readback is still RUMlogNG's report, not an independent CAT connection or RF measurement.")
    section("Permissions and saved data")
    text("Ad-hoc-signed executable updates may require removing and re-adding the app's Accessibility entry. Settings and rotating logs live outside the bundle in ~/Library/Application Support/Satellite Bridge/. App updates preserve saved pairs.")

    page("Planned next steps", "The following requirements are not implemented in the 1.0.5 download.")
    section("A third operating mode: Terrestrial")
    text("Add named repeater and simplex profiles with the same Settings editor / one-click Operations model as QO-100. Repeater entries hold RX (repeater output), TX (repeater input), duplex direction/offset including DUP-, mode, and a TX CTCSS opening tone or none.")
    text("Simplex entries use equal RX/TX frequencies and no duplex offset, with voice/data settings. One requested example is a <b>144.800 MHz packet-radio channel</b>. Selecting Terrestrial should disable SAT, block MacDoppler and apply the profile once, then allow manual tuning.")
    section("Planned power defaults")
    table([
        ["Mode", "Planned behavior"],
        ["QO-100", "Maximum 5%; verify before tuning and monitor"],
        ["MacDoppler", "Default 80%, applied once on mode entry"],
        ["Terrestrial", "Default 80%, applied once on mode entry"],
    ], [155, WIDTH - 155])
    text("Outside QO-100, subsequent manual power adjustment remains possible. Incoming Doppler reports must not repeatedly reset power. Version 1.0.5 does not raise power on entry to MacDoppler. Respecting the operator's Toggle setting is also pending.")
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
