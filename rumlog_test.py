#!/usr/bin/env python3
"""Read RUMlogNG TRX #2, or briefly test and restore its two frequencies.

The DXLab Commander service is TCP. Frequencies on the wire are in kHz.
SAT must already be enabled on the radio for RX/TX to mean downlink/uplink.
No command that enables PTT is implemented.
"""

import argparse
import json
import re
import socket
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


QUERIES = {
    "rx_khz": ("CmdGetFreq", "CmdFreq"),
    "tx_khz": ("CmdGetTXFreq", "CmdTXFreq"),
    "mode": ("CmdSendMode", "CmdMode"),
    "split": ("CmdSendSplit", "CmdSplit"),
    "ptt": ("CmdSendTx", "CmdTX"),
}
ALLOWED = {cmd for cmd, _ in QUERIES.values()} | {"CmdSetFreq", "CmdSetTXFreq"}


def field(name, value):
    return f"<{name}:{len(value.encode('ascii'))}>{value}"


def first_field(data):
    match = re.match(rb"<([^:<>]+):(\d+)>", data)
    if not match:
        return None
    end = match.end() + int(match[2])
    if len(data) < end:
        return None
    return match[1].decode("ascii"), data[match.end():end].decode("ascii")


class Commander:
    def __init__(self, host, port, events):
        self.host, self.port, self.events = host, port, events

    def command(self, name, params="", reply=None):
        if name not in ALLOWED:
            raise ValueError(f"Command is not implemented: {name}")
        message = field("command", name) + field("parameters", params)
        event = {"utc": datetime.now(timezone.utc).isoformat(), "sent": message}
        self.events.append(event)
        with socket.create_connection((self.host, self.port), 3) as connection:
            connection.settimeout(3)
            connection.sendall(message.encode("ascii"))
            if reply is None:
                # Setters do not acknowledge. Only a subsequent query verifies them.
                return
            data = bytearray()
            while True:
                chunk = connection.recv(4096)
                if not chunk:
                    raise RuntimeError(f"Connection closed before {reply} arrived")
                data.extend(chunk)
                if len(data) > 65536:
                    raise RuntimeError("Oversized server reply")
                parsed = first_field(data)
                if parsed is not None:
                    event["received"] = bytes(data).decode("ascii", "replace")
                    if parsed[0].lower() != reply.lower():
                        raise RuntimeError(f"Unexpected reply to {name}: {parsed}")
                    return parsed[1]

    def state(self):
        state = {}
        for key, (command, reply) in QUERIES.items():
            value = self.command(command, reply=reply)
            if key.endswith("_khz"):
                value = str(Decimal(value.replace(",", "")))
            state[key] = value
        return state

    def set_frequency(self, command, khz):
        self.command(command, field("xcvrfreq", format(khz, ".3f")))


def mhz(value):
    try:
        result = Decimal(value) * 1000
        if not result.is_finite() or result <= 0 or result != result.quantize(Decimal(".001")):
            raise ValueError
        if not any(low <= result <= high for low, high in ((144000, 148000), (430000, 450000), (1240000, 1300000))):
            raise ValueError
        return result
    except (InvalidOperation, ValueError):
        raise argparse.ArgumentTypeError("Use an IC-9700 amateur-band frequency in MHz, to whole-Hz precision")


def require_rx(state):
    if state["ptt"].upper() != "OFF":
        raise RuntimeError("Test stopped: RUMlogNG does not report PTT OFF")


def matches(state, rx, tx):
    return Decimal(state["rx_khz"]) == rx and Decimal(state["tx_khz"]) == tx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7400)
    parser.add_argument("--downlink-mhz", type=mhz)
    parser.add_argument("--uplink-mhz", type=mhz)
    parser.add_argument("--original-downlink-mhz", type=mhz, help="Operator-observed RX baseline when RUMlogNG reports zero")
    parser.add_argument("--original-uplink-mhz", type=mhz, help="Operator-observed TX baseline when RUMlogNG reports zero")
    parser.add_argument("--sat-already-on", action="store_true", help="Operator has checked SAT is enabled; the server cannot verify it")
    parser.add_argument("--output", type=Path, help="Save requests, replies, and results as JSON")
    args = parser.parse_args()
    changing = args.downlink_mhz is not None or args.uplink_mhz is not None
    if changing and (args.downlink_mhz is None or args.uplink_mhz is None or not args.sat_already_on):
        parser.error("A test requires both frequencies and --sat-already-on")

    result = {"endpoint": f"tcp://{args.host}:{args.port}", "events": []}
    client = Commander(args.host, args.port, result["events"])
    status = 0
    try:
        before = client.state()
        result["before"] = before
        print("Before:", json.dumps(before), flush=True)
        if changing:
            require_rx(before)
            reported_rx, reported_tx = Decimal(before["rx_khz"]), Decimal(before["tx_khz"])
            old_rx = args.original_downlink_mhz if args.original_downlink_mhz is not None else reported_rx
            old_tx = args.original_uplink_mhz if args.original_uplink_mhz is not None else reported_tx
            if (reported_rx > 0 and reported_rx != old_rx) or (reported_tx > 0 and reported_tx != old_tx):
                raise RuntimeError("Test stopped: operator-observed baseline differs from the server")
            if old_rx <= 0 or old_tx <= 0:
                raise RuntimeError("Test stopped: a zero/unknown frequency prevents reliable verification and restoration")
            result["restoration_target"] = {"rx_khz": str(old_rx), "tx_khz": str(old_tx)}
            result["operator_supplied_baseline"] = reported_rx <= 0 or reported_tx <= 0
            baseline = client.state()
            require_rx(baseline)
            if baseline != before:
                raise RuntimeError("Test stopped: radio state changed during the baseline check")
            try:
                client.set_frequency("CmdSetFreq", args.downlink_mhz)
                time.sleep(0.7)
                after_rx = client.state()
                result["after_downlink"] = after_rx
                require_rx(after_rx)
                if not matches(after_rx, args.downlink_mhz, old_tx):
                    raise RuntimeError("Downlink command failed verification or also changed the uplink")
                if after_rx["mode"] != before["mode"]:
                    raise RuntimeError("Operating mode changed during the downlink test")
                print("After downlink:", json.dumps(after_rx), flush=True)
                client.set_frequency("CmdSetTXFreq", args.uplink_mhz)
                time.sleep(0.7)
                after_tx = client.state()
                result["after_uplink"] = after_tx
                require_rx(after_tx)
                if not matches(after_tx, args.downlink_mhz, args.uplink_mhz):
                    raise RuntimeError("Uplink command failed verification or also changed the downlink")
                if after_tx["mode"] != before["mode"]:
                    raise RuntimeError("Operating mode changed during the uplink test")
                print("After uplink:", json.dumps(after_tx), flush=True)
                result["frequency_test"] = "PASS: independent downlink/uplink server readbacks matched; physical radio confirmation is separate"
                print(result["frequency_test"], flush=True)
                time.sleep(10)
            finally:
                # Avoid retuning if the operator began a transmission mid-test.
                require_rx(client.state())
                client.set_frequency("CmdSetFreq", old_rx)
                time.sleep(0.7)
                client.set_frequency("CmdSetTXFreq", old_tx)
                time.sleep(0.7)
                restored = client.state()
                result["restored"] = restored
                print("Restored:", json.dumps(restored), flush=True)
                if not matches(restored, old_rx, old_tx):
                    raise RuntimeError("Restoration did not verify; check both frequencies on the radio")
        result["satellite_mode"] = "Not tested: this interface has no documented SAT on/off command"
    except (OSError, RuntimeError, InvalidOperation) as error:
        result["error"] = str(error)
        print(str(error), file=sys.stderr, flush=True)
        status = 1
    finally:
        if args.output:
            args.output.write_text(json.dumps(result, indent=2) + "\n")
    return status


if __name__ == "__main__":
    sys.exit(main())
