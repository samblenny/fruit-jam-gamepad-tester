# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright 2025 Sam Blenny
#
# Helpers for HID report descriptor and HID report parsing
#
# Related Documentation:
# - https://www.usb.org/sites/default/files/documents/hid1_11.pdf
#   (USB Device Class Definition for HID Devices)
# - https://www.usb.org/sites/default/files/hut1_4.pdf
#   (HID Usage Tables for USB)
#
import adafruit_logging as logging

# Configure logging
logger = logging.getLogger('usb_descriptor')
logger.setLevel(logging.DEBUG)


class HIDReportDesc:
    def __init__(self, data):
        # Hold HID report descriptor details (parsed from bDescriptorType=0x22)
        # - data: bytearray with HID descriptor
        #
        pass # TODO: implement this

    def __str__(self):
        # TODO: finish this (note: indent=8)
        return "        [TODO: parse report descriptor]"
