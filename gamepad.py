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
logger.setLevel(logging.INFO)


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
OTHER  = const(3)


def find_usb_device(device_cache):
    # Find a USB wired gamepad by inspecting usb device descriptors
    # - device_cache: dictionary of previously checked device descriptors
    # - return: ScanResult object for success or None for failure.
    # Exceptions: may raise usb.core.USBError or usb.core.USBTimeoutError
    #
    for device in core.find(find_all=True):
        # Read device and configuration descriptors to find details
        # to help identify DInput or XInput gamepads
        try:
            desc = usb_descriptor.Descriptor(device)
            k = str(desc.to_bytes())
            if k in device_cache:
                # Ignore previously checked devices. The point of this is to
                # avoid repeatedly spewing log output about devices that are
                # not interesting (e.g. want a gamepad but found a keyboard)
                logger.debug("Ignoring cached device")
                return None
            # Remember this device to avoid repeatedly checking it later
            device_cache[k] = True
            # Read and parse the device's configuration descriptor
            desc.read_configuration(device)
            vid, pid = desc.vid_pid()
            dev_info = desc.dev_class_subclass_protocol()
            int0_info = desc.int0_class_subclass_protocol()
            logger.info(desc)
            dev_type = OTHER
            if is_xinput_gamepad(desc):
                dev_type = XINPUT
            elif is_dinput_gamepad(desc):
                dev_type = DINPUT
            return ScanResult(device, dev_type, vid, pid, dev_info, int0_info)
        except ValueError as e:
            # This happens for errors during descriptor parsing
            logger.error(e)
            pass
        except USBError as e:
            # USBError can happen when device first connects
            logger.error("USBError: '%s', %s, '%s'" % (e, type(e), e.errno))
            pass
    return None


class ScanResult:
    def __init__(self, device, dev_type, vid, pid, dev_info, int0_info):
        if len(dev_info) != 3:
            raise ValueError("Expected (class,subclass,protocol) for dev_info")
        if len(int0_info) != 3:
            raise ValueError("Expected (class,subclass,protocol) for int0_info")
        self.device = device
        self.dev_type = dev_type
        self.vid = vid
        self.pid = pid
        self.dev_info = dev_info
        self.int0_info = int0_info


def is_dinput_gamepad(descriptor):
    # Return True if descriptor details match pattern for an DInput gamepad
    # - descriptor: usb_descriptor.Descriptor instance
    d = descriptor
    if d.bDeviceClass != 0x00 or len(d.configs) < 1:
        return False
    if d.configs[0].bNumInterfaces < 1:
        return False
    ifc0_generic = False
    for i in d.interfaces:
        n = i.bInterfaceNumber
        t = (i.bInterfaceClass, i.bInterfaceSubClass, i.bInterfaceProtocol)
        if t == (0x03, 0x01, 0x01):
            logger.info('Interface %d is boot-compatible keyboard' % n)
        if t == (0x03, 0x01, 0x02):
            logger.info('Interface %d is boot-compatible mouse' % n)
        if t == (0x03, 0x00, 0x00):
            # This is a generic HID endpoint which might be a gamepad, but if
            # the interface number is not 0, that's a lot less likely
            logger.info('Interface %d is generic HID' % n)
            logger.error('TODO: CHECK HID DESCRIPTOR. IS IT A JOYSTICK?')
            if n == 0:
                # TODO: actually look inside the HID descriptor for joystick
                ifc0_generic = True
    return ifc0_generic

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


class InputDevice:
    def __init__(self, device, device_type, player):
        # Initialize buffers used in polling USB gamepad events
        # - device: usb.core.Device
        # - device_type: XINPUT, DINPUT, OTHER
        # - player: player number for setting gamepad LEDs (in range 1..4)
        # Exceptions:
        # - may raise usb.core.USBError
        #
        self._prev = 0
        self.buf64 = bytearray(64)
        self.device = device
        self.player = player
        if device_type not in [DINPUT, XINPUT, OTHER]:
            raise ValueError('Unknown device_type: %d' % device_type)
        self.device_type = device_type
        # Make sure CircuitPython core is not claiming the device
        interface = 0
        if device.is_kernel_driver_active(interface):
            logger.debug('Detaching interface %d from kernel' % interface)
            device.detach_kernel_driver(interface)
        # Set configuration
        device.set_configuration()
        # Initialize gamepad (set LEDs, drain buffer, etc)
        if device_type == DINPUT:
            self.init_dinput()
        elif device_type == XINPUT:
            self.init_xinput()
        elif device_type == OTHER:
            logger.error("TODO: divide OTHER into Switch/kbd/mouse/generic/etc")
        else:
            raise ValueError('Unknown device_type: %d' % device_type)

    def init_dinput(self):
        # Prepare DInput gamepad for use.
        logger.info('Initializing DInput gamepad')
        logger.error("TODO: IMPLEMENT DINPUT SUPPORT")

    def init_xinput(self):
        # Prepare XInput gamepad for use.
        # Initial reads may give old data, so drain gamepad's buffer.
        logger.info('Initializing XInput gamepad')
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
        if self.device_type != XINPUT:
            # TODO: deal with the other device types
            return (True, False, None)
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
