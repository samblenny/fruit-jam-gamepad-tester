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
from struct import unpack_from

from micropython import const
import adafruit_logging as logging

# Configure logging
logger = logging.getLogger('usb_descriptor')
logger.setLevel(logging.DEBUG)


# Global Items
HID_USAGE_PAGE       = const(0x04)
HID_LOGICAL_MIN      = const(0x14)
HID_LOGICAL_MAX      = const(0x24)
HID_PHYSICAL_MIN     = const(0x34)
HID_PHYSICAL_MAX     = const(0x44)
HID_UNIT_EXPONENT    = const(0x54)
HID_UNIT             = const(0x64)
HID_REPORT_SIZE      = const(0x74)
HID_REPORT_ID        = const(0x84)
HID_REPORT_COUNT     = const(0x94)
HID_PUSH             = const(0xA4)
HID_POP              = const(0xB4)

# Local Items
HID_USAGE            = const(0x08)
HID_USAGE_MIN        = const(0x18)
HID_USAGE_MAX        = const(0x28)
HID_DESIGNATOR_IDX   = const(0x38)
HID_DESIGNATOR_MIN   = const(0x48)
HID_DESIGNATOR_MAX   = const(0x58)
HID_STRING_IDX       = const(0x78)
HID_STRING_MIN       = const(0x88)
HID_STRING_MAX       = const(0x98)
HID_DELIMITER        = const(0xA8)

# Main Items
HID_INPUT            = const(0x80)
HID_OUTPUT           = const(0x90)
HID_FEATURE          = const(0xB0)
HID_COLLECTION       = const(0xA0)
HID_END_COLLECTION   = const(0xC0)

# Reserved/NOP
HID_MAIN_00_NOP      = const(0x00)

# Long Item Prefix
HID_LONG_ITEM_PREFIX = const(0xFE)

# Bitfield Masks
HID_SIZE_MASK = const(0x03)  # 0b0000_0011
HID_TYPE_MASK = const(0x0C)  # 0b0000_1100
HID_TAG_MASK  = const(0xF0)  # 0b1111_0000

# Usage Pages
USAGE_PAGE_GENERIC_DESKTOP = const(0x01)
USAGE_PAGE_SIMULATION      = const(0x02)
USAGE_PAGE_GENERIC_DEVICE  = const(0x06)
USAGE_PAGE_KEYBOARD        = const(0x07)
USAGE_PAGE_LEDS            = const(0x08)
USAGE_PAGE_BUTTON          = const(0x09)
USAGE_PAGE_CONSUMER        = const(0x0C)
USAGE_PAGE_PHYSICAL_INPUT  = const(0x0f)

# Usage Within Generic Desktop Page
USAGE_POINTER          = const(0x01)
USAGE_MOUSE            = const(0x02)
USAGE_JOYSTICK         = const(0x04)
USAGE_GAMEPAD          = const(0x05)
USAGE_KEYBOARD         = const(0x06)
USAGE_MULTI_AXIS_CTRL  = const(0x08)
USAGE_X                = const(0x30)
USAGE_Y                = const(0x31)
USAGE_Z                = const(0x32)
USAGE_RX               = const(0x33)
USAGE_RY               = const(0x34)
USAGE_RZ               = const(0x35)
USAGE_SLIDER           = const(0x36)
USAGE_DIAL             = const(0x37)
USAGE_WHEEL            = const(0x38)
USAGE_HAT_SWITCH       = const(0x39)
USAGE_SYSTEM_CONTROL   = const(0x80)

# Usage Within LEDs Page (zero 2 uses these
USAGE_SLOW_BLINK_ON_T  = const(0x43)
USAGE_SLOW_BLINK_OFF_T = const(0x44)
USAGE_FAST_BLINK_ON_T  = const(0x45)
USAGE_FAST_BLING_OFF_T = const(0x46)

# Usage Within Simulation Controls Page (SN30 Pro Bluetooth uses these)
USAGE_ACCELERATOR      = const(0xc4)
USAGE_BRAKE            = const(0xc5)

# Usage Within Generic Device Controls Page (SN30 Pro Bluetooth uses this)
USAGE_BATTERY_STRENGTH = const(0x20)

# Collection Types
COLLECTION_PHYSICAL       = const(0x00)
COLLECTION_APPLICATION    = const(0x01)
COLLECTION_LOGICAL        = const(0x02)
COLLECTION_REPORT         = const(0x03)
COLLECTION_NAMED_ARRAY    = const(0x04)
COLLECTION_USAGE_SWITCH   = const(0x05)
COLLECTION_USAGE_MODIFIER = const(0x06)

# Local Delimiter Values
LOCAL_DELIMETER_OPEN  = const(0x01)
LOCAL_DELIMETER_CLOSE = const(0x00)

def dump_desc(data, message=None, indent=1):
    # Hexdump a descriptor
    # - data: bytearray or [bytes, ...] with descriptor from ctrl_transfer()
    # - message: header message to print before the hexdump
    # - indent: number of spaces to put at the start of each line
    # - returns: hexdump string
    arr = [message] if message else []
    if isinstance(data, list):
        for row in data:
            arr.append((' ' * indent) + ' '.join(['%02x' % b for b in row]))
    elif isinstance(data, bytearray):
        # Wrap hexdump to fit in 80 columns
        bytes_per_line = (80 - indent) // 3
        for offset in range(0, len(data), bytes_per_line):
            chunk = data[offset:offset+bytes_per_line]
            arr.append((' ' * indent) + ' '.join(['%02x' % b for b in chunk]))
    else:
        logger.error("Unexpected dump_desc arg type %s" % type(data))
    return "\n".join(arr)


class HIDReportDesc:
    def __init__(self, data, indent=8):
        # Hold HID report descriptor details (parsed from bDescriptorType=0x22)
        # - data: bytearray with HID descriptor
        # Exceptions: can raise ValueError for malformed descriptor
        #
        self.context = {
            'report_id': 0,
        }
        self.report_id = None
        self.report_size = None
        self.report_count = None
        self.indent = indent
        self.items_ = []
        cursor = 0
        limit = len(data)
        for i in range(limit):
            prefix = data[cursor]
            size = prefix & HID_SIZE_MASK
            tag_type = prefix & (HID_TAG_MASK | HID_TYPE_MASK)
            next_cursor = cursor + size + 1
            if next_cursor > limit:
                raise ValueError("HID Report descriptor: item size too big")
            item_data = None
            if size == 1:
                # uint8
                item_data = data[cursor+1]
            elif size == 2:
                # little endian uint16
                (item_data,) = unpack_from('<H', data, cursor+1)
            elif size == 3:
                # little endian uint32
                (item_data,) = unpack_from('<I', data, cursor+1)
            self.parse_item(tag_type, size, item_data)
            cursor = next_cursor
            if cursor == limit:
                # normal ending. all is well
                return

    def __str__(self):
        return '\n'.join(self.items_)

    def note(self, item, data):
        # Record human readable description of a report descriptor item
        if data is None:
            self.items_.append('%s%s' % (' ' * self.indent, item))
        elif isinstance(data, str):
            self.items_.append('%s%s (%s)' % (' ' * self.indent, item, data))
        else:
            self.items_.append('%s%s (%u)' % (' ' * self.indent, item, data))

    def parse_usage_page(self, data):
        # Return string description of a usage page
        if data == USAGE_PAGE_GENERIC_DESKTOP:
            return 'Generic Desktop'
        elif data == USAGE_PAGE_SIMULATION:
            return 'Simulation Controls'
        elif data == USAGE_PAGE_GENERIC_DEVICE:
            return 'Generic Device Controls'
        elif data == USAGE_PAGE_KEYBOARD:
            return 'Keyboard/Keypad'
        elif data == USAGE_PAGE_LEDS:
            return 'LEDs'
        elif data == USAGE_PAGE_BUTTON:
            return 'Button'
        elif data == USAGE_PAGE_CONSUMER:
            return 'Consumer'
        elif data == USAGE_PAGE_PHYSICAL_INPUT:
            return 'Physical Input Device'
        elif 0xff00 <= data <= 0xffff:
            return 'Vendor Defined 0x%04x' % data
        else:
            return '%08x' % data

    def parse_generic_desktop_usage(self, data):
        # Return string description of a usage (within Generic Desktop page)
        if data == USAGE_POINTER:
            return 'Pointer'
        elif data == USAGE_MOUSE:
            return 'Mouse'
        elif data == USAGE_JOYSTICK:
            return 'Joystick'
        elif data == USAGE_GAMEPAD:
            return 'Gamepad'
        elif data == USAGE_KEYBOARD:
            return 'Keyboard'
        elif data == USAGE_MULTI_AXIS_CTRL:
            return 'Multi-axis Controller'
        elif data == USAGE_X:
            return 'X Axis'
        elif data == USAGE_Y:
            return 'Y Axis'
        elif data == USAGE_Z:
            return 'Z Axis'
        elif data == USAGE_RX:
            return 'Rx Axis'
        elif data == USAGE_RY:
            return 'Ry Axis'
        elif data == USAGE_RZ:
            return 'Rz Axis'
        elif data == USAGE_SLIDER:
            return 'Slider'
        elif data == USAGE_DIAL:
            return 'Dial'
        elif data == USAGE_WHEEL:
            return 'Wheel'
        elif data == USAGE_HAT_SWITCH:
            return 'Hat Switch'
        elif data == USAGE_SYSTEM_CONTROL:
            return 'System Control'
        else:
            return '%08x' % data

    def parse_usage(self, size, data):
        # Convert usage page data to a human readable description.
        # This is tricky: for size 1 or 2 bytes, this is a usage ID from within
        # a previously set usage page. But, for 4 bytes (size 3), the data
        # contains both a usage page and a usage ID.
        page = self.usage_page
        id_ = data
        if size == 3:
            page = data >> 16
            id_ = data & 0xffff
        if page == USAGE_PAGE_GENERIC_DESKTOP:  # gamepad/keyboard/mouse
            return self.parse_generic_desktop_usage(id_)
        elif page == USAGE_PAGE_SIMULATION:     # accel/brake
            if id_ == USAGE_ACCELERATOR:
                return 'Accelerator'
            elif id_ == USAGE_BRAKE:
                return 'Brake'
            else:
                return '0x%04x' % id_
        elif page == USAGE_PAGE_GENERIC_DEVICE:  # battery
            if id_ == USAGE_BATTERY_STRENGTH:
                return 'Battery Strength'
            else:
                return '0x%04x' % id_
        elif page == USAGE_PAGE_KEYBOARD:
            return 'Keyboard 0x%04x' % id_
        elif page == USAGE_PAGE_LEDS:
            if id_ == USAGE_SLOW_BLINK_ON_T:
                return 'Slow Blink On Time'
            if id_ == USAGE_SLOW_BLINK_OFF_T:
                return 'Slow Blink Off Time'
            if id_ == USAGE_FAST_BLINK_ON_T:
                return 'Fast Blink On Time'
            if id_ == USAGE_FAST_BLING_OFF_T:
                return 'Fast Blink Off Time'
            else:
                return '0x%04x' % id_
        elif page == USAGE_PAGE_BUTTON:
            return 'Button 0x%04x' % id_
        elif page == USAGE_PAGE_CONSUMER:
            return 'Consumer 0x%04x' % id_
        elif page == USAGE_PAGE_PHYSICAL_INPUT:  # force feedback (ignore)
            return '0x%04x' % id_
        else:
            return '0x%04x' % id_

    def parse_collection_type(self, data):
        # Return string description of a collection type
        if data == COLLECTION_PHYSICAL:
            return 'Physical'
        elif data == COLLECTION_APPLICATION:
            return 'Application'
        elif data == COLLECTION_LOGICAL:
            return 'Logical'
        elif data == COLLECTION_REPORT:
            return 'Report'
        elif data == COLLECTION_NAMED_ARRAY:
            return 'Named Array'
        elif data == COLLECTION_USAGE_SWITCH:
            return 'Usage Switch'
        elif data == COLLECTION_USAGE_MODIFIER:
            return 'Usage Modifier'
        else:
            return 'Unknown 0x%02x' % data

    def parse_item(self, tag_type, size, data):
        tt = tag_type
        # Long items aren't supported
        if tt == HID_LONG_ITEM_PREFIX:
            raise ValueError("HID Descriptor parser: Long items not supported")

        # 0x00 is reserved / NOP. It shows up some, so just ignore it
        elif tt == HID_MAIN_00_NOP:
            pass

        # Global Items
        elif tt == HID_USAGE_PAGE:          # USAGE PAGE
            page = self.parse_usage_page(data)
            self.usage_page = data
            self.note('Usage Page', page)
        elif tt == HID_LOGICAL_MIN:
            pass  # ignore this
        elif tt == HID_LOGICAL_MAX:
            pass  # ignore this
        elif tt == HID_PHYSICAL_MIN:
            pass  # ignore this
        elif tt == HID_PHYSICAL_MAX:
            pass  # ignore this
        elif tt == HID_UNIT_EXPONENT:
            pass  # ignore this
        elif tt == HID_UNIT:
            pass  # ignore this
        elif tt == HID_REPORT_SIZE:          # SIZE OF REPORT FIELD IN BITS
            self.report_size = data
            self.note('Report Size', data)
        elif tt == HID_REPORT_ID:            # REPORT ID (IMPORTANT: OPTIONAL!)
            if not (self.report_id is None):
                self.indent -= 2
            self.note('Report ID', '0x%02x' % data)
            self.indent += 2
            self.report_id = data
        elif tt == HID_REPORT_COUNT:         # NUMBER OF FIELDS IN THIS REPORT
            self.note('Report Count', data)
            self.report_count = data
        elif tt == HID_PUSH:                 # TODO?
            self.note('Push', data)
        elif tt == HID_POP:                  # TODO?
            self.note('Pop', data)

        # Local Items
        elif tt == HID_USAGE:
            # This is tricky: for size 1 or 2 bytes, this is a usage ID from
            # within a previously set usage page. But, for 4 bytes (size 3),
            # the data contains both a usage page and a usage ID.
            self.note('Usage', self.parse_usage(size, data))
        elif tt == HID_USAGE_MIN:
            self.note('Usage Min', data)
        elif tt == HID_USAGE_MAX:
            self.note('Usage Max', data)
        elif tt == HID_DESIGNATOR_IDX:
            pass  # ignore this
        elif tt == HID_DESIGNATOR_MIN:
            pass  # ignore this
        elif tt == HID_DESIGNATOR_MAX:
            pass  # ignore this
        elif tt == HID_STRING_IDX:
            pass  # ignore this
        elif tt == HID_STRING_MIN:
            pass  # ignore this
        elif tt == HID_STRING_MAX:
            pass  # ignore this
        elif tt == HID_DELIMITER:
            self.note('Delimiter', data)

        # Main Items
        elif tt == HID_INPUT:
            self.note('Input', data)
        elif tt == HID_OUTPUT:
            self.note('Output', data)
        elif tt == HID_FEATURE:
            self.note('Feature', data)
        elif tt == HID_COLLECTION:
            self.note('Collection', self.parse_collection_type(data))
            self.indent += 2
        elif tt == HID_END_COLLECTION:
            self.indent -= 2
            self.note('End Collection', data)

        # Unknown Item tag/type
        else:
            self.note('0x%02x' % (tag_type | size), data)
