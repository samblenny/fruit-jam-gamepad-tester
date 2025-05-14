# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright 2025 Sam Blenny
#
# USB gamepad descriptor data for testing gamepad type detection.
#
# This list is not remotely comprehensive, but it's better than nothing. These
# are from some assorted gamepads and HID devices that I had laying around.
#


def make_array(hex_str):
    # convert a string full of space separate hex bytes into a bytearray
    return bytearray.fromhex(hex_str.replace(' ', ''))


# Compact USB wired keyboard (US QWERTY layout)
COMPACT_KEYBOARD = {
    'vid': 0x2222,
    'pid': 0x0099,
    'class': 0x00,
    'subclass': 0x00,
    'protocol': 0x00,
    'interfaces': {
        0: {'class': 0x03, 'subclass': 0x01, 'protocol': 0x01, 'endpoints': [0x81],
            'hidreport': make_array(
                "05 01 09 06 a1 01 05 08 19 01 29 03 15 00 25 01 75 01 95 03 91 02 95 05"
                "91 01 05 07 19 e0 29 e7 95 08 81 02 75 08 95 01 81 01 19 00 2a ff 00 26"
                "ff 00 95 06 81 00 c0"
            ),
        },
        1: {'class': 0x03, 'subclass': 0x00, 'protocol': 0x00, 'endpoints': [0x82],
            'hidreport': make_array(
                "05 0c 09 01 a1 01 85 01 19 00 2a 3c 02 15 00 26 3c 02 95 01 75 10 81 00"
                "c0 05 01 09 80 a1 01 85 02 19 81 29 83 25 01 75 01 95 03 81 02 95 05 81"
                "01 c0"
            ),
        },
    },
}


# Cheap USB wired scrollwheel mouse
CHEAP_MOUSE = {
    'vid': 0x413c,
    'pid': 0x301a,
    'class': 0x00,
    'subclass': 0x00,
    'protocol': 0x00,
    'interfaces': {
        0: {'class': 0x03, 'subclass': 0x01, 'protocol': 0x02, 'endpoints': [0x81],
            'hidreport': make_array(
                "05 01 09 02 a1 01 09 01 a1 00 05 09 19 01 29 03 15 00 25 01 75 01 95 03"
                "81 02 75 05 95 01 81 03 06 00 ff 09 40 95 02 75 08 15 81 25 7f 81 02 05"
                "01 09 38 15 81 25 7f 75 08 95 01 81 06 09 30 09 31 16 01 80 26 ff 7f 75"
                "10 95 02 81 06 c0 c0"
            ),
        },
    },
}


# PowerA Wired Controller (marketed for use with Switch)
POWERA = {
    'vid': 0x20d6,
    'pid': 0xa711,
    'class': 0x00,
    'subclass': 0x00,
    'protocol': 0x00,
    'interfaces': {
        0: {'class': 0x03, 'subclass': 0x00, 'protocol': 0x00, 'endpoints': [0x02, 0x81],
            'hidreport': make_array(
                "05 01 09 05 a1 01 15 00 25 01 35 00 45 01 75 01 95 0e 05 09 19 01 29 0e"
                "81 02 95 02 81 01 05 01 25 07 46 3b 01 75 04 95 01 65 14 09 39 81 42 65"
                "00 95 01 81 01 26 ff 00 46 ff 00 09 30 09 31 09 32 09 35 75 08 95 04 81"
                "02 75 08 95 01 81 01 05 0c 09 00 15 80 25 7f 75 08 95 40 b1 02 c0"
            ),
        },
    },
}

# 8BitDo Ultimate Bluetooth Controller USB adapter (Switch Pro compatible)
ULTIMATE_BT = {
    'vid': 0x057e,
    'pid': 0x2009,
    'class': 0x00,
    'subclass': 0x00,
    'protocol': 0x00,
    'interfaces': {
        0: {'class': 0x03, 'subclass': 0x00, 'protocol': 0x00, 'endpoints': [0x81, 0x02],
            'hidreport': make_array(
                "05 01 15 00 09 04 a1 01 85 30 05 01 05 09 19 01 29 0a 15 00 25 01 75 01"
                "95 0a 55 00 65 00 81 02 05 09 19 0b 29 0e 15 00 25 01 75 01 95 04 81 02"
                "75 01 95 02 81 03 0b 01 00 01 00 a1 00 0b 30 00 01 00 0b 31 00 01 00 0b"
                "32 00 01 00 0b 35 00 01 00 15 00 27 ff ff 00 00 75 10 95 04 81 02 c0 0b"
                "39 00 01 00 15 00 25 07 35 00 46 3b 01 65 14 75 04 95 01 81 02 05 09 19"
                "0f 29 12 15 00 25 01 75 01 95 04 81 02 75 08 95 34 81 03 06 00 ff 85 21"
                "09 01 75 08 95 3f 81 03 85 81 09 02 75 08 95 3f 81 03 85 01 09 03 75 08"
                "95 3f 91 83 85 10 09 04 75 08 95 3f 91 83 85 80 09 05 75 08 95 3f 91 83"
                "85 82 09 06 75 08 95 3f 91 83 c0"
            ),
        },
    },
}

# 8BitDo Zero 2 (connected by USB-C, generic HID)
ZERO2 = {
    'vid': 0x2dc8,
    'pid': 0x9018,
    'class': 0x00,
    'subclass': 0x00,
    'protocol': 0x00,
    'interfaces': {
        0: {'class': 0x03, 'subclass': 0x00, 'protocol': 0x00, 'endpoints': [0x81, 0x02],
            'hidreport': make_array(
                "05 01 09 05 a1 01 15 00 25 01 35 00 45 01 75 01 95 0f 05 09 19 01 29 0f"
                "81 02 95 01 81 01 05 01 25 07 46 3b 01 75 04 95 01 65 14 09 39 81 42 65"
                "00 95 01 81 01 26 ff 00 46 ff 00 09 30 09 31 09 32 09 35 75 08 95 04 81"
                "02 65 00 75 08 95 02 81 01 05 08 09 43 15 00 26 ff 00 35 00 46 ff 00 75"
                "08 95 02 91 82 09 44 91 82 09 45 91 82 09 46 91 82 c0"
            ),
        },
    },
}

# 8BitDo SN30 Pro Bluetooth gamepad (USB-C + DInput mode)
SN30PRO_BT_DINPUT = {
    'vid': 0x2dc8,
    'pid': 0x6001,
    'class': 0x00,
    'subclass': 0x00,
    'protocol': 0x00,
    'interfaces': {
        0: {'class': 0x03, 'subclass': 0x00, 'protocol': 0x00, 'endpoints': [0x81, 0x02],
            'hidreport': make_array(
                "05 01 09 05 a1 01 85 03 05 01 15 00 25 07 46 3b 01 95 01 75 04 65 14 09"
                "39 81 42 75 01 95 04 81 01 15 00 26 ff 00 09 30 09 31 09 32 09 35 95 04"
                "75 08 81 02 05 02 15 00 26 ff 00 09 c4 09 c5 95 02 75 08 81 02 05 09 19"
                "01 29 10 15 00 25 01 75 01 95 10 81 02 05 06 09 20 15 00 25 64 75 08 95"
                "01 81 02 05 0f 09 70 85 05 15 00 25 64 75 08 95 04 91 02 85 02 09 02 75"
                "08 95 3f 81 03 85 81 09 03 75 08 95 3f 91 83 c0"
            ),
        },
    },
}

# 8BitDo SN30 Pro Bluetooth gamepad (USB-C + Switch mode)
SN30PRO_BT_SWITCH = {
    'vid': 0x057e,
    'pid': 0x2009,
    'class': 0x00,
    'subclass': 0x00,
    'protocol': 0x00,
    'interfaces': {
        0: {'class': 0x03, 'subclass': 0x00, 'protocol': 0x00, 'endpoints': [0x81, 0x02],
            'hidreport': make_array(
                "05 01 15 00 09 04 a1 01 85 30 05 01 05 09 19 01 29 0a 15 00 25 01 75 01"
                "95 0a 55 00 65 00 81 02 05 09 19 0b 29 0e 15 00 25 01 75 01 95 04 81 02"
                "75 01 95 02 81 03 0b 01 00 01 00 a1 00 0b 30 00 01 00 0b 31 00 01 00 0b"
                "32 00 01 00 0b 35 00 01 00 15 00 27 ff ff 00 00 75 10 95 04 81 02 c0 0b"
                "39 00 01 00 15 00 25 07 35 00 46 3b 01 65 14 75 04 95 01 81 02 05 09 19"
                "0f 29 12 15 00 25 01 75 01 95 04 81 02 75 08 95 34 81 03 06 00 ff 85 21"
                "09 01 75 08 95 3f 81 03 85 81 09 02 75 08 95 3f 81 03 85 01 09 03 75 08"
                "95 3f 91 83 85 10 09 04 75 08 95 3f 91 83 85 80 09 05 75 08 95 3f 91 83"
                "85 82 09 06 75 08 95 3f 91 83 c0"
            ),
        },
    },
}

# 8BitDo SN30 Pro Bluetooth gamepad (USB-C + XInput mode)
SN30PRO_BT_XINPUT = {
    'vid': 0x045e,
    'pid': 0x028e,
    'class': 0xff,
    'subclass': 0xff,
    'protocol': 0xff,
    'interfaces': {
        0: {'class': 0xff, 'subclass': 0x5d, 'protocol': 0x01, 'endpoints': [0x81, 0x01]},
        1: {'class': 0xff, 'subclass': 0x5d, 'protocol': 0x03, 'endpoints': [0x82, 0x02, 0x83, 0x03]},
        2: {'class': 0xff, 'subclass': 0x5d, 'protocol': 0x02, 'endpoints': [0x84]},
        3: {'class': 0xff, 'subclass': 0xfd, 'protocol': 0x13, 'endpoints': []},
    },
}

# 8BitDo SN30 Pro USB gamepad (this is the wired XInput version)
SN30PRO_USB = {
    'vid': 0x045e,
    'pid': 0x028e,
    'class': 0xff,
    'subclass': 0xff,
    'protocol': 0xff,
    'interfaces': {
        0: {'class': 0xff, 'subclass': 0x5d, 'protocol': 0x01, 'endpoints': [0x81, 0x02]},
        1: {'class': 0xff, 'subclass': 0x5d, 'protocol': 0x03, 'endpoints': [0x83, 0x04]},
        2: {'class': 0xff, 'subclass': 0x5d, 'protocol': 0x02, 'endpoints': [0x86]},
        3: {'class': 0xff, 'subclass': 0xfd, 'protocol': 0x13, 'endpoints': []},
    },
}

# This is the full set of test data
TEST_DATA = {
    'Compact Keyboard': COMPACT_KEYBOARD,
    'Cheap Mouse': CHEAP_MOUSE,
    'PowerA Wired Controller (marketed for Switch)': POWERA,
    '8BitDo Ultimate Bluetooth Controller (Switch Pro compatible)': ULTIMATE_BT,
    '8BitDo Zero 2 (USB-C, BT mode has no effect on USB descriptor)': ZERO2,
    '8BitDo SN30 Pro Bluetooth (USB-C + DInput mode)': SN30PRO_BT_DINPUT,
    '8BitDo SN30 Pro Bluetooth (USB-C + Switch mode)': SN30PRO_BT_SWITCH,
    '8BitDo SN30 Pro Bluetooth (USB-C + XInput mode)': SN30PRO_BT_XINPUT,
    '8BitDo SN30 Pro USB (XInput)': SN30PRO_USB,
}
