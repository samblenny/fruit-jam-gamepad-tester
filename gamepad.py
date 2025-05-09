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
from time import sleep
from struct import unpack
from usb import core
from usb.core import USBError, USBTimeoutError
from micropython import const

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

RETRIES = const(25)
DEBUG = True

def find_gamepad_device():
    # Find a USB wired gamepad by inspecting usb device descriptors
    # Returns: (usb.core.Device, gamepad_type constant) or (None, None)
    # Exceptions: may raise usb.core.USBError or usb.core.USBTimeoutError
    #
    for device in core.find(find_all=True):
        if DEBUG:
            print("Finding gamepad device...")
        if device:
            sleep(0.1)
            # Read device and configuration descriptors to find details
            # to help identify DInput or XInput gamepads
            journal = {}
            try:
                for i in range(RETRIES):
                    if get_device_descriptor(device, journal):
                        break
                    sleep(0.1)
            except USBError:
                # USBError can happen when device first connects
                print("[E4]")
                return (None, None)
            keys_ = sorted(journal)
            if DEBUG:
                print('\n'.join([f"{k}: {journal[k]}" for k in keys_]))
            # Decide whether to ignore or claim this device
            # This may may raise usb.core.USBError
            if is_xinput_gamepad(journal):
                return (device, XINPUT)
            elif journal.get('Interface 0', None) == 'HID':
                return (device, DINPUT)
            else:
                print
        else:
            sleep(0.5)
    # Reaching this point means no matching USB gamepad was found
    return (None, None)

def is_xinput_gamepad(journal):
    # Check descriptor details for pattern matching XInput gamepad
    if journal.get('num_interfaces', None) != 4:
        return False
    return journal.get('Interface 0', None) == 'XInput'

def get_device_descriptor(device, journal):
    # Read and parse USB device descriptor which is always 18 bytes
    # Return True if descriptor seems okay or False if it looks invalid
    data = bytearray(18)
    device.ctrl_transfer(0x80, 6, 1 << 8, 0, data, 100)
    if data[0] == 0:
        # Sometimes the descriptor response is all zeros
        return False
    if DEBUG:
        print('Device Descriptor:')
        print(' ', ' '.join(['%02x' % b for b in data]))
    device_class = data[4]
    max_packet_size = data[7]
    num_configs = data[17]
    if max_packet_size == 0 or num_configs == 0:
        return False
    journal['max_packet_size'] = max_packet_size
    # This only checks the first config
    return get_config_descriptor(device, journal, device_class)

def get_config_descriptor(device, journal, dev_class):
    # Read & parse first configuration's descriptor (up to 256 bytes)
    # NOTE: return value of ctrl_transfer is not useful (always len(data))
    data = bytearray(256)
    device.ctrl_transfer(0x80, 6, 2 << 8, 0, data, 500)
    if data[0] == 0:
        return False
    if DEBUG:
        print('Configuration Descriptor:')
    # Loop over the configuration descriptor bytes, splitting them into
    # slices for each sub-descriptor. First byte of each slice is a byte
    # length for that sub-descriptor.
    cursor = 0
    limit = len(data)
    for i in range(limit):
        if cursor == limit:
            break
        length = data[cursor]
        if length == 0:
            break
        if cursor + length > limit:
            print(f"Invalid descriptor length: data[{i}] = {length}")
            return False
        desc = data[cursor:cursor+length]
        if DEBUG:
            print(' ', ' '.join(['%02x' % b for b in desc]))
        cursor += length
        # Parse the descriptor
        if len(desc) < 2:
            continue
        desc_type = desc[1]
        tag = (length << 8) | desc_type
        if tag == 0x0902:
            # Configuration descriptor header
            journal['num_interfaces'] = data[4]
        elif tag == 0x0904:
            # Interface descriptor
            interface_num = desc[2]
            num_endpoints = desc[4]
            class_ = desc[5]
            subclass = desc[6]
            if interface_num == 0:
                if dev_class == 0xff and class_ == 0xff and subclass == 0x5d:
                    journal['Interface 0'] = 'XInput'
                elif dev_class == 0x00 and class_ == 0x03 and subclass == 0x00:
                    journal['Interface 0'] = 'HID'
        elif tag == 0x0705:
            # Endpoint descriptor
            endpoints = journal.get('endpoints', [])
            endpoints.append((
                '0x%02x' % desc[2],        # address
                desc[3],                   # attributes
                (desc[5] << 8) | desc[4],  # max packet size
                desc[6]                    # polling interval (ms)
                ))
            journal['endpoints'] = endpoints
        elif dev_class == 0x00 and tag == 0x0921:
            # HID descriptor
            hid = journal.get('HID', [])
            hid.append({
                'num_descriptors': desc[4],
                'report_type': desc[6],
                'report_length': (desc[8] << 8) | desc[7]
                })
            journal['HID'] = hid
    return True

# def get_hid_report_descriptor(self, device, journal, length):
#     # Get HID report descriptor
#     # Don't attempt to call this prior to set_configuration()
#     data = bytearray(length)
#     device.ctrl_transfer(0x81, 6, 0x22 << 8, 0, data, 500)
#     print(' '.join(['%02x ' % b for b in data]))

class Gamepad:
    def __init__(self, device, gamepad_type):
        # Initialize buffers used in polling USB gamepad events
        self._prev = 0
        self.buf64 = bytearray(64)
        self.timeout_count = 0
        # Set up the gamepad device
        self.device = device
        self.gamepad_type = gamepad_type
        self._configure(device, gamepad_type)

    def _configure(self, device, gamepad_type):
        # Prepare USB gamepad for use (set configuration, drain buffer, etc)
        # Exceptions: may raise usb.core.USBError or usb.core.USBTimeoutError
        if DEBUG:
            if gamepad_type == DINPUT:
                print("Configuring gamepad of type: DInput")
            if gamepad_type == XINPUT:
                print("Configuring gamepad of type: XInput")
        interface = 0
        timeout_ms = 5
        try:
            # Make sure CircuitPython core is not claiming the device
            if device.is_kernel_driver_active(interface):
                device.detach_kernel_driver(interface)
            # Make sure that configuration is set
            device.set_configuration()
            sleep(0.01)
        except USBError as e:
            print("[E1]: '%s', %s, '%s'" % (e, type(e), e.errno))
            self._reset()
            raise e
        if gamepad_type != XINPUT:
            print("TODO: IMPLEMENT DINPUT SUPPORT")
            return
        else:
            # Initial reads may give old data, so drain gamepad's buffer. This
            # may raise an exception (with no string description nor errno!)
            # when buffer is already empty. If that happens, ignore it.
            try:
                sleep(0.1)
                for _ in range(8):
                    __ = device.read(0x81, self.buf64, timeout=timeout_ms)
                    self._prev = 0
            except USBError as e:
                if e.errno is None:
                    pass  # this is okay
                else:
                    print("[E2]: '%s', %s, '%s'" % (e, type(e), e.errno))
                    self._reset()
                    raise e

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
        timeout_ms = 5
        endpoint = 0x81
        try:
            # Poll gamepad endpoint to get button and joystick status bytes
            n = self.device.read(endpoint, self.buf64, timeout=timeout_ms)
            self.timeout_count = 0
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
            self.timeout_count += 1
            if self.timeout_count < 100:
                return (True, False, None)
            else:
                print("\n[E3]: '%s', %s, '%s'" % (e, type(e), e.errno))
                self._reset()
                raise e
        except USBError as e:
            print("\n[E3]: '%s', %s, '%s'" % (e, type(e), e.errno))
            self._reset()
            raise e

    def _reset(self):
        # Reset USB device and gamepad button polling state
        self.device = None
        self._prev = 0
