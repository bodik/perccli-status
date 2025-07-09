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
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from enum import IntEnum
from argparse import ArgumentParser
from dataclasses import dataclass


__version__ = "0.3"
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class ExitCode(IntEnum):
    """nagios return codes enum"""

    OK = 0
    WARNING = 1
    CRITICAL = 2
    UNKNOWN = 3


def format_table(headers, rows):
    """print table"""

    # Determine the width of each column
    column_widths = [len(header) for header in headers]
    for row in rows:
        for idx, name in enumerate(headers):
            column_widths[idx] = max(column_widths[idx], len(str(getattr(row, name))))

    # Create a format string based on the column widths
    format_string = " | ".join([f"{{:<{width}}}" for width in column_widths])
    separator = "-+-".join(["-" * width for width in column_widths])

    # Collect lines instead of printing
    lines = []
    lines.append(format_string.format(*headers))
    lines.append(separator)

    # Process each row
    for row in rows:
        for idx, name in enumerate(headers):
            value = getattr(row, name)
            if isinstance(value, list):
                setattr(row, name, ",".join(value))
        lines.append(format_string.format(*[getattr(row, name) for name in headers]))

    return "\n".join(lines)


class JsonCommandError(Exception):
    """json command exception"""


def json_command(cmd):
    """run command, parse output at json"""

    try:
        return json.loads(subprocess.check_output(cmd, text=True))
    except (json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        logger.error("perccli output parsing error: %s", exc)
        raise JsonCommandError(str(exc)) from None


def find_perccli():
    """Find perccli from a list of default paths."""

    for path in [
        "/opt/MegaRAID/perccli/perccli64",
        "/opt/MegaRAID/perccli2/perccli2",
    ]:
        if resolved := shutil.which(path):
            return resolved
    raise RuntimeError("perccli not found")  # pragma: nocover


def parse_version(perccli_path):
    """Extract perccli major version number."""

    # PercCli2 SAS Customization Utility Ver 008.0004.0000.0022 Apr 28, 2023
    output = subprocess.check_output([perccli_path, "v"], text=True)
    if match := re.search(r"PercCli.*SAS Customization Utility Ver (\d+)\.\d+\.\d+\.\d+", output):
        return int(match.group(1))
    raise RuntimeError("perccli version not parsed")  # pragma: nocover


def manager_factory(perccli_path):
    """returns perccli manager by version"""

    if not perccli_path:
        perccli_path = find_perccli()
    perccli_version = parse_version(perccli_path)

    if perccli_version == 7:
        return Perccli7Manager(perccli_path)
    if perccli_version == 8:
        return Perccli8Manager(perccli_path)
    raise RuntimeError("perccli version not supported")  # pragma: nocover


@dataclass
class ControllerInfo:  # pylint: disable=missing-class-docstring
    cid: str
    status: str
    model: str
    ram: str
    temp: str
    firmware: str
    bbu: list


@dataclass
class VdiskInfo:  # pylint: disable=missing-class-docstring
    vid: str
    type: str
    size: str
    strip: str
    status: str
    ospath: str


@dataclass
class PdiskInfo:  # pylint: disable=missing-class-docstring
    did: str
    type: str
    model: str
    size: str
    status: str
    speed: str
    temp: str


class Perccli7Manager:
    """perccli 7 manager"""

    def __init__(self, perccli_path):
        self.perccli_path = perccli_path

    def check_controllers(self):
        """check controllers"""

        try:
            controller_data = json_command([self.perccli_path, "/call", "show", "all", "j"])
        except JsonCommandError:
            return ExitCode.CRITICAL, []

        all_controllers = []
        exit_code = ExitCode.OK

        for controller in controller_data["Controllers"]:
            resp = controller["Response Data"]

            cinfo = ControllerInfo(
                f'C{controller["Command Status"]["Controller"]}',
                resp["Status"]["Controller Status"],
                resp["Basics"]["Model"],
                resp["HwCfg"]["On Board Memory Size"],
                resp["HwCfg"]["Ctrl temperature(Degree Celsius)"],
                resp["Version"]["Firmware Version"],
                [bbu_item["State"] for bbu_item in resp["BBU_Info"]],
            )

            if cinfo.status != "Optimal":
                exit_code = ExitCode.CRITICAL  # pragma: nocover
            if not all(item == "Optimal" for item in cinfo.bbu):
                exit_code = ExitCode.CRITICAL  # pragma: nocover

            all_controllers.append(cinfo)

        return exit_code, all_controllers

    def check_virtual_disks(self):
        """check virtual disks"""

        try:
            virtual_data = json_command([self.perccli_path, "/call/vall", "show", "all", "j"])
        except JsonCommandError:
            return ExitCode.CRITICAL, []

        all_vdisks = []
        exit_code = ExitCode.OK

        for controller in virtual_data["Controllers"]:
            resp = controller["Response Data"]

            for name, vdisk in resp.items():
                if not name.startswith("/c"):
                    # skip if not vdisk info block
                    continue

                vdisk_props = f"VD{vdisk[0]['DG/VD'].split('/')[-1]} Properties"

                vinfo = VdiskInfo(
                    f"C{controller['Command Status']['Controller']} V{vdisk[0]['DG/VD']}",
                    vdisk[0]["TYPE"],
                    vdisk[0]["Size"],
                    resp[vdisk_props]["Strip Size"],
                    vdisk[0]["State"],
                    resp[vdisk_props]["OS Drive Name"],
                )

                if vinfo.status != "Optl":
                    exit_code = ExitCode.CRITICAL  # pragma: nocover

                all_vdisks.append(vinfo)

        return exit_code, all_vdisks

    def _phys_disks_data(self):  # pragma: nocover
        """handle different flavors of perccli64 7.x"""

        # R540, H740P, perccli64 007.2313.0000.0000
        disk_data = json_command([self.perccli_path, "/call/eall/sall", "show", "all", "j"])
        if disk_data["Controllers"][0]["Command Status"]["Status"] == "Success":
            return disk_data

        # R430, H730P, perccli64 007.2616.0000.0000
        disk_data = json_command([self.perccli_path, "/call/sall", "show", "all", "j"])
        if disk_data["Controllers"][0]["Command Status"]["Status"] == "Success":
            return disk_data

        raise JsonCommandError("_phys_disks_data failed")

    def check_phys_disks(self):
        """check physical disks"""

        try:
            disk_data = self._phys_disks_data()
        except (JsonCommandError, KeyError):
            return ExitCode.CRITICAL, []

        all_disks = []
        exit_code = ExitCode.OK

        for controller in disk_data["Controllers"]:
            resp = controller["Response Data"]

            for name, pdisk in resp.items():
                if not re.match(r"^Drive /c[0-9]+(/e[0-9]+)?/s[0-9]+$", name):
                    # skip any detail element
                    continue

                pinfo = PdiskInfo(
                    f"C{controller['Command Status']['Controller']} P{pdisk[0]['EID:Slt']}",
                    f"{pdisk[0]['Intf']} {pdisk[0]['Med']}",
                    pdisk[0]["Model"],
                    pdisk[0]["Size"],
                    pdisk[0]["State"],
                    resp[f"{name} - Detailed Information"][f"{name} Device attributes"][
                        "Link Speed"
                    ],
                    resp[f"{name} - Detailed Information"][f"{name} State"][
                        "Drive Temperature"
                    ].strip(),
                )

                if pinfo.status not in ["Onln", "GHS"]:
                    exit_code = ExitCode.CRITICAL  # pragma: nocover

                all_disks.append(pinfo)

        return exit_code, all_disks


class Perccli8Manager:
    """perccli 8 manager"""

    def __init__(self, perccli_path):
        self.perccli_path = perccli_path

    def check_controllers(self):
        """check controllers"""

        try:
            controller_data = json_command([self.perccli_path, "/call", "show", "all", "j"])
        except JsonCommandError:
            return ExitCode.CRITICAL, []

        all_controllers = []
        exit_code = ExitCode.OK

        for controller in controller_data["Controllers"]:
            resp = controller["Response Data"]

            cinfo = ControllerInfo(
                f'C{controller["Command Status"]["Controller"]}',
                resp["Status"]["Controller Status"],
                resp["Basics"]["Product Name"],
                resp["HwCfg"]["DDR Memory Size(MiB)"],
                resp["HwCfg"]["Chip temperature(C)"],
                resp["Version"]["Firmware Version"],
                [epack["Status"] for epack in resp["Energy Pack Info"]],
            )

            if cinfo.status != "Optimal":
                exit_code = ExitCode.CRITICAL  # pragma: nocover
            if not all(item == "Optimal" for item in cinfo.bbu):
                exit_code = ExitCode.CRITICAL  # pragma: nocover

            all_controllers.append(cinfo)

        return exit_code, all_controllers

    def check_virtual_disks(self):
        """check virtual disks"""

        try:
            virtual_data = json_command([self.perccli_path, "/call/vall", "show", "all", "j"])
        except JsonCommandError:
            return ExitCode.CRITICAL, []

        all_vdisks = []
        exit_code = ExitCode.OK

        for controller in virtual_data["Controllers"]:
            resp = controller["Response Data"]

            for vdisk in resp["Virtual Drives"]:
                vinfo = VdiskInfo(
                    f"C{controller['Command Status']['Controller']} V{vdisk['VD Info']['DG/VD']}",
                    vdisk["VD Info"]["TYPE"],
                    vdisk["VD Info"]["Size"],
                    vdisk["VD Properties"]["Strip Size"],
                    vdisk["VD Info"]["State"],
                    vdisk["VD Properties"]["OS Drive Name"],
                )

                if vinfo.status != "Optl":
                    exit_code = ExitCode.CRITICAL  # pragma: nocover

                all_vdisks.append(vinfo)

        return exit_code, all_vdisks

    def check_phys_disks(self):
        """check physical disks"""

        try:
            disk_data = json_command([self.perccli_path, "/call/eall/sall", "show", "all", "j"])
        except JsonCommandError:
            return ExitCode.CRITICAL, []

        all_disks = []
        exit_code = ExitCode.OK

        for controller in disk_data["Controllers"]:
            resp = controller["Response Data"]

            for pdisk in resp["Drives List"]:
                pinfo = PdiskInfo(
                    f"C{controller['Command Status']['Controller']} P{pdisk['Drive Information']['EID:Slt']}",
                    f"{pdisk['Drive Information']['Intf']} {pdisk['Drive Information']['Med']}",
                    pdisk["Drive Information"]["Model"],
                    pdisk["Drive Information"]["Size"],
                    pdisk["Drive Information"]["Status"],
                    pdisk["Drive Detailed Information"]["Path Information"][0]["Negotiated Speed"],
                    pdisk["Drive Detailed Information"]["Temperature(C)"],
                )

                if pinfo.status not in ["Online", "Good"]:
                    exit_code = ExitCode.CRITICAL  # pragma: nocover

                all_disks.append(pinfo)

        return exit_code, all_disks


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
    parser.add_argument("--debug", action="store_true", dest="debug", help="debugging mode")
    parser.add_argument(
        "--perccli-path",
        dest="perccli_path",
        help="Path to perccli",
    )
    parser.add_argument("--nagios", action="store_true", help="Nagios/Icinga-like output")

    return parser.parse_args(argv)


def main(argv=None):
    """main"""

    args = parse_arguments(argv)
    if args.debug:  # pragma: nocover
        logger.setLevel(logging.DEBUG)

    manager = manager_factory(args.perccli_path)
    ctrl_ret, ctrl_info = manager.check_controllers()
    virtual_ret, virtual_info = manager.check_virtual_disks()
    pdisk_ret, pdisk_info = manager.check_phys_disks()
    exit_code = max(ctrl_ret, virtual_ret, pdisk_ret)

    if args.nagios:
        arrays = dict(Counter(x.status for x in virtual_info))
        disks = dict(Counter(x.status for x in pdisk_info))
        print(f"RAID {exit_code.name}: Arrays {arrays} Disks {disks}")
        return exit_code

    # megaclisas-status ref
    #         -- Controller information --
    # -- ID | H/W Model          | RAM    | Temp | BBU    | Firmware
    # c0    | PERC H730P Adapter | 2048MB | 51C  | Good   | FW: 25.5.5.0005
    #
    # -- Array information --
    # -- ID | Type   |    Size |  Strpsz | Flags | DskCache |   Status |  OS Path | CacheCade |InProgress
    # c0u0  | RAID-6 |   7276G |   64 KB | RA,WB |  Default |  Optimal | /dev/sda | None      |None
    #
    # -- Disk information --
    # -- ID   | Type | Drive Model                          | Size     | Status          | Speed    | Temp | Slot ID  | LSI ID
    # c0u0p0  | HDD  | 67xxxxxxxxxxTOSHIBA MG04xxxxxxx FJ2D | 3.637 TB | Online, Spun Up | 6.0Gb/s  | 32C  | [32:0]   | 0

    print("-- controller info")
    print(format_table(["cid", "status", "model", "ram", "temp", "bbu", "firmware"], ctrl_info))
    print("\n-- virtual disk info")
    print(format_table(["vid", "status", "type", "size", "strip", "ospath"], virtual_info))
    print("\n-- disk info")
    print(format_table(["did", "status", "type", "model", "size", "speed", "temp"], pdisk_info))
    return exit_code


if __name__ == "__main__":  # pragma: nocover
    sys.exit(main())
