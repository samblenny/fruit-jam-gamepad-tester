# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright 2025 Sam Blenny
#
# Gamepad driver for DInput or XInput compatible USB wired gamepads
#
# The button names used here match the Nintendo SNES style button
# cluster layout, but the USB IDs and protocol match the Xbox 360 USB
# wired controller. This is meant to work with widely available USB
# wired xinput compatible gamepads for the retrogaming market. In
# particular, I tested this package using my 8BitDo SN30 Pro USB wired
# gamepad.
#
# Related docs:
# - https://docs.circuitpython.org/projects/logging/en/latest/api.html
# - https://learn.adafruit.com/a-logger-for-circuitpython/overview
#
from struct import unpack
from usb import core
from usb.core import USBError, USBTimeoutError
from micropython import const

import adafruit_logging as logging

import usb_descriptor


# Configure logging
logger = logging.getLogger('gamepad')
logger.setLevel(logging.DEBUG)


# Gamepad button bitmask constants
UP     = const(0x0001)  # dpad: Up
DOWN   = const(0x0002)  # dpad: Down
LEFT   = const(0x0004)  # dpad: Left
RIGHT  = const(0x0008)  # dpad: Right
START  = const(0x0010)
SELECT = const(0x0020)
L      = const(0x0100)  # Left shoulder button
R      = const(0x0200)  # Right shoulder button
B      = const(0x1000)  # button cluster: bottom button (Nintendo B, Xbox A)
A      = const(0x2000)  # button cluster: right button  (Nintendo A, Xbox B)
Y      = const(0x4000)  # button cluster: left button   (Nintendo Y, Xbox X)
X      = const(0x8000)  # button cluster: top button    (Nintendo X, Xbox Y)

# Gamepad USB protocol type constants
DINPUT = const(1)
XINPUT = const(2)

# Configure logging
logger = logging.getLogger('gamepad')
logger.setLevel(logging.DEBUG)


def find_gamepad_device():
    # Find a USB wired gamepad by inspecting usb device descriptors
    # - return: (usb.core.Device, gamepad_type constant) or (None, None)
    # Exceptions: may raise usb.core.USBError or usb.core.USBTimeoutError
    #
    for device in core.find(find_all=True):
        # Read device and configuration descriptors to find details
        # to help identify DInput or XInput gamepads
        try:
            desc = usb_descriptor.Descriptor(device)
            logger.info(desc)
            if is_xinput_gamepad(desc):
                return (device, XINPUT)
        except ValueError as e:
            # This happens for errors during descriptor parsing
            logger.error(e)
            pass
        except USBError as e:
            # USBError can happen when device first connects
            logger.error("USBError: '%s', %s, '%s'" % (e, type(e), e.errno))
            pass
    return (None, None)

def is_xinput_gamepad(descriptor):
    # Return True if descriptor details match pattern for an XInput gamepad
    # - descriptor: usb_descriptor.Descriptor instance
    d = descriptor
    if d.bDeviceClass != 0xff or len(d.configs) < 1:
        return False
    if d.configs[0].bNumInterfaces != 4:
        return False
    for i in d.interfaces:
        a = i.bInterfaceNumber   == 0
        b = i.bInterfaceClass    == 0xff
        c = i.bInterfaceSubClass == 0x5d
        if a and b and c:
            return True
    return False

def set_xinput_led(device, player):
    # Set player number LEDs on XInput gamepad
    # - device: usb.core.Device
    # - player: player number in range 1..4
    report = None
    if player == 1:
        report = bytearray(b'\x01\x03\x02')
    elif player == 2:
        report = bytearray(b'\x01\x03\x03')
    elif player == 3:
        report = bytearray(b'\x01\x03\x04')
    elif player == 4:
        report = bytearray(b'\x01\x03\x05')
    else:
        raise ValueError("Player number must be in range 1..4")
    # write(endpoint, data, timeout)
    device.write(0x02, report, 100)


class Gamepad:
    def __init__(self, device, gamepad_type, player):
        # Initialize buffers used in polling USB gamepad events
        # - device: usb.core.Device
        # - gamepad_type: XINPUT or DINPUT
        # - player: player number for setting gamepad LEDs (in range 1..4)
        # Exceptions:
        # - may raise usb.core.USBError
        #
        self._prev = 0
        self.buf64 = bytearray(64)
        self.device = device
        self.player = player
        if gamepad_type not in [DINPUT, XINPUT]:
            raise ValueError('Unknown gamepad_type: %d' % gamepad_type)
        self.gamepad_type = gamepad_type
        # Make sure CircuitPython core is not claiming the device
        interface = 0
        if device.is_kernel_driver_active(interface):
            logger.debug('Detaching interface %d from kernel' % interface)
            device.detach_kernel_driver(interface)
        # Set configuration
        device.set_configuration()
        # Initialize gamepad (set LEDs, drain buffer, etc)
        if gamepad_type == DINPUT:
            self.init_dinput()
        elif gamepad_type == XINPUT:
            self.init_xinput()
        else:
            raise ValueError('Unknown gamepad_type: %d' % gamepad_type)

    def init_dinput(self):
        # Prepare DInput gamepad for use.
        logger.debug('Initializing DInput gamepad')
        raise ValueError("TODO: IMPLEMENT DINPUT SUPPORT")

    def init_xinput(self):
        # Prepare XInput gamepad for use.
        # Initial reads may give old data, so drain gamepad's buffer.
        logger.debug('Initializing XInput gamepad')
        timeout_ms = 5
        try:
            for _ in range(8):
                self.device.read(0x81, self.buf64, timeout=timeout_ms)
        except USBError as e:
            # Ignore exceptions (can happen if there's nothing to read)
            pass
        set_xinput_led(self.device, self.player)

    def poll(self):
        # Poll gamepad for button changes (ignore sticks and triggers)
        #
        # Returns a tuple of (valid, changed, buttons):
        #   connected: True if gamepad is still connected, else False
        #   changed: True if buttons changed since last call, else False
        #   buttons: Uint16 containing bitfield of individual button values
        # Exceptions: may raise usb.core.USBError or usb.core.USBTimeoutError
        #
        # Expected endpoint 0x81 report format:
        #  bytes 0,1:    prefix that doesn't change      [ignored]
        #  bytes 2,3:    button bitfield for dpad, ABXY, etc (uint16)
        #  byte  4:      L2 left trigger (analog uint8)  [ignored]
        #  byte  5:      R2 right trigger (analog uint8) [ignored]
        #  bytes 6,7:    LX left stick X axis (int16)    [ignored]
        #  bytes 8,9:    LY left stick Y axis (int16)    [ignored]
        #  bytes 10,11:  RX right stick X axis (int16)   [ignored]
        #  bytes 12,13:  RY right stick Y axis (int16)   [ignored]
        #  bytes 14..19: ???, but they don't change
        #
        if self.device is None:
            # caller is trying to poll when gamepad is not connected
            return (False, False, None)
        endpoint = 0x81
        timeout_ms = 5
        try:
            # Poll gamepad endpoint to get button and joystick status bytes
            n = self.device.read(endpoint, self.buf64, timeout=timeout_ms)
            if n < 14:
                # skip unexpected responses (too short to be a full report)
                return (True, False, None)
            # Only bytes 2 and 3 are interesting (ignore sticks/triggers)
            (buttons,) = unpack('<H', self.buf64[2:4])
            if buttons != self._prev:
                # button state has changed since previous polling
                self._prev = buttons
                return (True, True, buttons)
            else:
                # button state is the same as it was last time
                return (True, False, buttons)
        except USBTimeoutError as e:
            # This sometimes happens when the device is unplugged. It can also
            # happen under normal conditions. For example, I have a wireless
            # gamepad that, even when connected by USB-C cable, will start
            # timing out after a short time with no button presses. But, it
            # starts responding as soon as you press a button. I'm not aware of
            # a way to distinguish between the device being unplugged and just
            # a normal timeout. So, for now, just treat both the same.
            #
            # TODO: After the next TinyUSB update, perhaps re-consider if this
            #       should be treated as the device having been unplugged
            raise e
        except USBError as e:
            # TODO: After the next TinyUSB update, perhaps re-consider if this
            #       should be treated as the device having been unplugged
            raise e
