#!/usr/bin/env python3
"""Nagios/Opsview plugin to check status of PowerEdge RAID Controller

Author: Radoslav Bodó <radoslav.bodo@igalileo.cz>
Author: Peter Pakos <peter.pakos@wandisco.com>

Copyright (C) 2024 Galileo Corporation
Copyright (C) 2019 WANdisco

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

from collections import Counter
import os
import json
import logging
import subprocess
import sys
from argparse import ArgumentParser


__version__ = "0.2"
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

STATUS_OK = 0
STATUS_WARNING = 1
STATUS_CRITICAL = 2
STATUS_UNKNOWN = 3
EXIT_CODES = {
    "OK": 0,
    "WARNING": 1,
    "CRITICAL": 2,
    "UNKNOWN": 3,
}


def print_table(headers, rows):
    """print table"""

    # Determine the width of each column
    column_widths = [len(header) for header in headers]
    for row in rows:
        for i, item in enumerate(row):
            column_widths[i] = max(column_widths[i], len(str(item)))

    # Create a format string based on the column widths
    format_string = " | ".join([f"{{:<{width}}}" for width in column_widths])
    separator = "-+-".join(["-" * width for width in column_widths])

    # Print the header
    print(format_string.format(*headers))
    print(separator)

    # Print each row
    for row in rows:
        for idx, item in enumerate(row):
            if isinstance(item, list):
                row[idx] = ",".join(item)
        print(format_string.format(*row))


def json_command(cmd):
    """run command, parse output at json"""

    try:
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        logger.error("PERCCLI output parsing error: %s", exc)
        return None


def check_controllers(args):
    """check controllers"""
    # megaclisas-status ref
    #         -- Controller information --
    # -- ID | H/W Model          | RAM    | Temp | BBU    | Firmware
    # c0    | PERC H730P Adapter | 2048MB | 51C  | Good   | FW: 25.5.5.0005

    if not (
        controller_data := json_command(
            [args.perccli_path, "/call", "show", "all", "j"]
        )
    ):
        return "CRITICAL", []

    controller_info = []
    exit_code = "OK"
    for controller in controller_data["Controllers"]:
        resp = controller["Response Data"]

        cid = f'C{controller["Command Status"]["Controller"]}'
        status = resp["Status"]["Controller Status"]
        model = resp["Basics"]["Product Name"]
        ram = resp["HwCfg"]["DDR Memory Size(MiB)"]
        temp = resp["HwCfg"]["Chip temperature(C)"]
        firmware = resp["Version"]["Firmware Version"]
        bbu = [x["Status"] for x in resp["Energy Pack Info"]]

        if status != "Optimal":
            exit_code = "CRITICAL"
        if any(x != "Optimal" for x in bbu):
            exit_code = "CRITICAL"

        controller_info.append([cid, status, model, ram, temp, bbu, firmware])

    return exit_code, controller_info


def check_virtual_disks(args):
    """check virtual disks"""
    # megaclisas-status ref
    # -- Array information --
    # -- ID | Type   |    Size |  Strpsz | Flags | DskCache |   Status |  OS Path | CacheCade |InProgress
    # c0u0  | RAID-6 |   7276G |   64 KB | RA,WB |  Default |  Optimal | /dev/sda | None      |None

    if not (
        virtual_data := json_command(
            [args.perccli_path, "/call/vall", "show", "all", "j"]
        )
    ):
        return "CRITICAL", []

    virtual_info = []
    exit_code = "OK"
    for controller in virtual_data["Controllers"]:
        resp = controller["Response Data"]

        for vdisk in resp["Virtual Drives"]:
            vid = f'C{controller["Command Status"]["Controller"]} V{vdisk["VD Info"]["DG/VD"]}'
            type_ = vdisk["VD Info"]["TYPE"]
            size = vdisk["VD Info"]["Size"]
            strip = vdisk["VD Properties"]["Strip Size"]
            status = vdisk["VD Info"]["State"]
            ospath = vdisk["VD Properties"]["OS Drive Name"]

            if status != "Optl":
                exit_code = "CRITICAL"

            virtual_info.append([vid, status, type_, size, strip, ospath])

    return exit_code, virtual_info


def check_phys_disks(args):
    """check physical disks"""
    # megaclisas-status ref
    # -- Disk information --
    # -- ID   | Type | Drive Model                          | Size     | Status          | Speed    | Temp | Slot ID  | LSI ID
    # c0u0p0  | HDD  | 67xxxxxxxxxxTOSHIBA MG04xxxxxxx FJ2D | 3.637 TB | Online, Spun Up | 6.0Gb/s  | 32C  | [32:0]   | 0

    if not (
        disk_data := json_command(
            [args.perccli_path, "/call/eall/sall", "show", "all", "j"]
        )
    ):
        return "CRITICAL", []

    disk_info = []
    exit_code = "OK"
    for controller in disk_data["Controllers"]:
        resp = controller["Response Data"]

        for disk in resp["Drives List"]:
            did = f'C{controller["Command Status"]["Controller"]} P{disk["Drive Information"]["EID:Slt"]}'
            type_ = f'{disk["Drive Information"]["Intf"]} {disk["Drive Information"]["Med"]}'
            model = disk["Drive Information"]["Model"]
            size = disk["Drive Information"]["Size"]
            status = disk["Drive Information"]["Status"]
            speed = disk["Drive Detailed Information"]["Path Information"][0][
                "Negotiated Speed"
            ]
            temp = disk["Drive Detailed Information"]["Temperature(C)"]

            if status not in ["Online", "Good"]:
                exit_code = "CRITICAL"

            disk_info.append([did, status, type_, model, size, speed, temp])

    return exit_code, disk_info


def parse_arguments(argv):
    """parse arguments"""

    parser = ArgumentParser(
        description="Nagios/Opsview plugin to check status of PowerEdge RAID Controller",
        add_help=False,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{os.path.basename(__file__)} {__version__}",
    )
    parser.add_argument(
        "--debug", action="store_true", dest="debug", help="debugging mode"
    )
    parser.add_argument(
        "--perccli-path",
        dest="perccli_path",
        help="Path to perccli (default: %(default)s)",
        default="/opt/MegaRAID/perccli2/perccli2",
    )
    parser.add_argument(
        "--nagios", action="store_true", help="Nagios/Icinga-like output"
    )

    return parser.parse_args(argv)


def main(argv=None):
    """main"""

    args = parse_arguments(argv)
    if args.debug:  # pragma: nocover
        logger.setLevel(logging.DEBUG)

    ctrl_ret, ctrl_info = check_controllers(args)
    virtual_ret, virtual_info = check_virtual_disks(args)
    disk_ret, disk_info = check_phys_disks(args)
    exit_code = max(EXIT_CODES[x] for x in [ctrl_ret, virtual_ret, disk_ret])

    if args.nagios:
        exit_status = next(k for k, v in EXIT_CODES.items() if v == exit_code)
        arrays = dict(Counter(x[1] for x in virtual_info))
        disks = dict(Counter(x[1] for x in disk_info))
        print(f"RAID {exit_status}: Arrays {arrays} Disks {disks}")

    else:
        print("-- controller info")
        print_table(
            ["id", "status", "model", "ram", "temp", "bbu", "firmware"], ctrl_info
        )

        print()
        print("-- virtual disk info")
        print_table(["id", "status", "type", "size", "strip", "ospath"], virtual_info)

        print()
        print("-- disk info")
        print_table(
            ["id", "status", "type", "model", "size", "speed", "temp"], disk_info
        )

    return exit_code


if __name__ == "__main__":  # pragma: nocover
    sys.exit(main())
