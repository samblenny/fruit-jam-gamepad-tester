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
from usb.core import USBError

# Gamepad button bitmask constants
UP     = 0x0001  # dpad: Up
DOWN   = 0x0002  # dpad: Down
LEFT   = 0x0004  # dpad: Left
RIGHT  = 0x0008  # dpad: Right
START  = 0x0010
SELECT = 0x0020
L      = 0x0100  # Left shoulder button
R      = 0x0200  # Right shoulder button
B      = 0x1000  # button cluster: bottom button (Nintendo B, Xbox A)
A      = 0x2000  # button cluster: right button  (Nintendo A, Xbox B)
Y      = 0x4000  # button cluster: left button   (Nintendo Y, Xbox X)
X      = 0x8000  # button cluster: top button    (Nintendo X, Xbox Y)

class Gamepad:
    def __init__(self, debug):
        # Initialize buffers used in polling USB gamepad events
        self._prev = 0
        self.buf64 = bytearray(64)
        # Variable to hold the gamepad's usb.core.Device object
        self.device = None
        self.debug = debug
        self.gamepad_type = None

    def find_and_configure(self, retries=25):
        # Connect to a USB wired Xbox 360 style gamepad (vid:pid=045e:028e)
        #
        # retries: max number of attempts to find device (100ms retry interval)
        #
        # Returns: True = success, False = device not found or config failed
        # Exceptions: may raise usb.core.USBError or usb.core.USBTimeoutError
        #
        for _ in range(retries):
            for device in core.find(find_all=True):
                if device and device.idVendor != 0:
                    sleep(0.1)
                    # Read device and configuration descriptors to find details
                    # to help identify DInput or XInput gamepads
                    journal = {}
                    self.get_device_descriptor(device, journal)
                    keys_ = sorted(journal)
                    print('\n'.join([f"{k}: {journal[k]}" for k in keys_]))
                    # Decide whether to skip or claim this device
                    if self.is_xinput_gamepad(journal):
                        # may raise usb.core.USBError
                        self._configure(device, 'XInput')
                        # end retry loop
                        return True
                    elif self.is_dinput_gamepad(journal):
                        # may raise usb.core.USBError
                        self._configure(device, 'DInput')
                        # end retry loop
                        return True
                else:
                    sleep(0.1)
        # Reaching this point means no matching USB gamepad was found
        self._reset()
        return False

    def is_xinput_gamepad(self, journal):
        # Check descriptor details for pattern matching XInput gamepad
        if journal['device_class'] != 0xff:
            return False
        if journal['num_interfaces'] != 4:
            return False
        subclass_match = False
        interfaces = journal.get('interfaces', [])
        for i in interfaces:
            if i['interface_num'] == 0:
                if i['class'] == '0xff' and i['subclass'] == '0x5d':
                    subclass_match = True
        if not subclass_match:
            return False
        endpoint_match = False
        endpoints = journal.get('endpoints', [])
        for e in endpoints:
            if e['addr'] == '0x81' and e['attrs'] == 3:
                endpoint_match = True
        return endpoint_match

    def is_dinput_gamepad(self, journal):
        # Check descriptor details for pattern matching DInput gamepad
        if journal['device_class'] != 0x00:
            return False
        subclass_match = False
        interfaces = journal.get('interfaces', [])
        for i in interfaces:
            if i['interface_num'] == 0:
                if i['class'] == '0x03' and i['subclass'] == '0x00':
                    subclass_match = True
        if not subclass_match:
            return False
        endpoint_match = False
        endpoints = journal.get('endpoints', [])
        for e in endpoints:
            if e['addr'] == '0x81' and e['attrs'] == 3:
                endpoint_match = True
        return endpoint_match


#     def get_hid_report_descriptor(self, device, journal, length):
#         # Get HID report descriptor
#         # Don't attempt to call this prior to set_configuration()
#         data = bytearray(length)
#         device.ctrl_transfer(0x81, 6, 0x22 << 8, 0, data, 500)
#         print(' '.join(['%02x ' % b for b in data]))


    def get_config_descriptor(self, device, config_num, journal, dev_class):
        # Read & parse configuration descriptor (up to 256 bytes)
        data = bytearray(256)
        device.ctrl_transfer(0x80, 6, 2 << 8, 0, data, 500)
        # NOTE: return value of ctrl_transfer is not useful (always len(data))
        print(f"Configuration {config_num}:")
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
            descriptor = data[cursor:cursor+length]
            print(' '.join(['%02x' % b for b in descriptor]))
            cursor += length
            # Parse the descriptor
            if len(descriptor) < 2:
                continue
            desc_type = descriptor[1]
            if length == 9 and desc_type == 0x02:
                # Parse a type=0x02 chunk of the configuration descriptor
                journal['num_interfaces'] = data[4]
            elif length == 9 and desc_type == 0x04:
                self.parse_desc_interface(journal, descriptor)
            elif length == 7 and desc_type == 0x05:
                self.parse_desc_endpoint(journal, descriptor)
            elif dev_class == 0x00 and length == 9 and desc_type == 0x21:
                self.parse_desc_hid(journal, descriptor)
        return True

    def parse_desc_hid(self, journal, data):
        # Parse a type0x21 (HID) chunk of the configuration descriptor
        # This should not be called for device class 0xff
        num_descriptors = data[4]
        report_type = data[6]
        report_length = (data[8] << 8) | data[7]
        hid = journal.get('HID', [])
        hid.append({
            'num_descriptors': num_descriptors,
            'report_type': report_type,
            'report_length': report_length
            })
        journal['HID'] = hid

    def parse_desc_interface(self, journal, data):
        # Parse a type=0x04 chunk of the configuration descriptor
        interfaces = journal.get('interfaces', [])
        # (interface_number, endpoint_count, subclass)
        interface_num = data[2]
        num_endpoints = data[4]
        # class 0x03 is HID game controller
        class_ = data[5]
        subclass = data[6]
        interfaces.append({
            'interface_num': interface_num,
            'num_endpoints': num_endpoints,
            'class': '0x%02x' % class_,
            'subclass': '0x%02x' % subclass
            })
        journal['interfaces'] = interfaces

    def parse_desc_endpoint(self, journal, data):
        # Parse a type=0x05 chunk of the configuration descriptor
        # If bit 7 is set (0x80), direction is input
        addr = data[2]
        # 3 is interrupt
        attrs = data[3]
        max_packet = (data[5] << 8) | data[4]
        interval_ms = data[6]
        endpoints = journal.get('endpoints', [])
        endpoints.append({
            'addr': '0x%02x' % addr,
            'attrs': attrs,
            'max_packet': max_packet,
            'interval_ms': interval_ms
            })
        journal['endpoints'] = endpoints

    def get_device_descriptor(self, device, journal):
        # Read USB device descriptor which is always 18 bytes
        data = bytearray(18)
        length = device.ctrl_transfer(0x80, 6, 1 << 8, 0, data, 100)
        if length != len(data):
            return False
        device_class = data[4]
        max_packet_size = data[7]
        num_configs = data[17]
        journal['device_class'] = device_class
        journal['max_packet_size'] = max_packet_size
        journal['num_configs'] = num_configs
        if device_class == 0x00:
            # For HID device, need to check interface descriptors for more info
            # This might be a DInput game controller, or maybe something else
            print(f"device class 0x00: probably a HID device")
        elif device_class == 0xff:
            # This could be an XInput gamepad
            print(f"device class 0xff: vendor specific protocol")
        for c in range(num_configs):
            self.get_config_descriptor(device, c, journal, device_class)

    def _configure(self, device, gamepad_type):
        # Prepare USB gamepad for use (set configuration, drain buffer, etc)
        #
        # Exceptions: may raise usb.core.USBError or usb.core.USBTimeoutError
        #
        self.gamepad_type = gamepad_type
        if self.debug:
            print(f"Configuring gamepad of type: {gamepad_type}")
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
        self.device = device
        if gamepad_type != 'XInput':
            print("TODO: IMPLEMENT DINPUT SUPPORT")
            return
        # Initial reads may give old data, so drain gamepad's buffer. This
        # may raise an exception (with no string description nor errno!)
        # when buffer is already empty. If that happens, ignore it.
        try:
            if self.debug:
                print(f"attempting to drain old reports from buffer...")
            sleep(0.1)
            for _ in range(8):
                __ = device.read(0x81, self.buf64, timeout=timeout_ms)
                self._prev = 0
            if self.debug:
                print(f"   done")
        except USBError as e:
            if e.errno is None:
                pass  # this is okay
            else:
                print("[E2]: '%s', %s, '%s'" % (e, type(e), e.errno))
                self._reset()
                raise e
        # All good, so save a reference to the device object
        self.device = device

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
        except USBError as e:
            print("[E3]: '%s', %s, '%s'" % (e, type(e), e.errno))
            self._reset()
            raise e

    def device_info_str(self):
        # Return string describing gamepad device (or lack thereof)
        d = self.device
        if d is None:
            return "[Gamepad not connected]"
        (v, pi, pr, m) = (d.idVendor, d.idProduct, d.product, d.manufacturer)
        if (v is None) or (pi is None):
            # Sometimes the usb.core or Max3421E will return 0000:0000 for
            # reasons that I do not understand
            return "[bad vid:pid]: vid=%s, pid=%s, prod='%s', mfg='%s'" % (
                v, pi, pr, m)
        else:
            return "Connected: %04x:%04x prod='%s' mfg='%s'" % (v, pi, pr, m)

    def _reset(self):
        # Reset USB device and gamepad button polling state
        self.device = None
        self._prev = 0
