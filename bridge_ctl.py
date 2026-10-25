#!/usr/bin/env python3
"""Control the running bridge UI through its private local socket."""

import argparse
import json
from bridge_rpc import request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "follow", "pause", "save-preset", "qo100", "activate", "quit", "check-access"))
    parser.add_argument("--name")
    parser.add_argument("--rx")
    parser.add_argument("--tx")
    parser.add_argument("--rx-mode", default="USB-D")
    parser.add_argument("--tx-mode", default="USB-D")
    args = parser.parse_args()
    print(json.dumps(request(vars(args)), indent=2))


if __name__ == "__main__":
    main()
