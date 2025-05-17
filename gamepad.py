# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright 2025 Sam Blenny
#
# Gamepad driver for XInput (Xbox360 compatible), DInput (generic HID), or
# Nintendo Switch Pro Controller compatible USB wired gamepads.
#
# This also does:
# - Device type detection and reporting for USB HID devices, including mice and
#   keyboards, to the extent that it's useful for telling them apart from HID
#   game controller devices
# - USB device, configuration, and HID report descriptor parsing to help with
#   device type detection and with understanding details of unfamiliar devices
#
# The button names used here match the Nintendo SNES style button cluster
# layout (A on the right). This is meant to work with some of the widely
# available USB wired xinput compatible gamepads, with an emphasis on
# inexpensive controllers for the retrogaming market.
#
# Support for XInput gamepads from 8BitDo is currently the most robust because
# that's what I use for my primary testing. Switch Pro compatible doesn't work
# yet. Generic HID (DInput) doesn't work yet. By the time you read this, that
# implementation status report may not be accurate, depending on whether I
# remember to update this comment.
#
# Related docs:
# - https://docs.circuitpython.org/projects/logging/en/latest/api.html
# - https://learn.adafruit.com/a-logger-for-circuitpython/overview
# - https://docs.python.org/3/glossary.html#term-generator
# - https://docs.python.org/3/glossary.html#term-iterable
# - https://docs.micropython.org/en/latest/reference/speed_python.html
#
from micropython import const
from struct import unpack, unpack_from
from supervisor import ticks_ms
from time import sleep
from usb import core
from usb.core import USBError, USBTimeoutError

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

# USB detected device types
TYPE_SWITCH_PRO    = const(1)
TYPE_XINPUT        = const(2)
TYPE_BOOT_MOUSE    = const(3)
TYPE_BOOT_KEYBOARD = const(4)
TYPE_HID_GAMEPAD   = const(5)
TYPE_HID           = const(6)
TYPE_OTHER         = const(7)


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
            int0_outs = desc.int0_output_endpoints()
            int0_ins = desc.int0_input_endpoints()
            logger.info(desc)
            dev_type = TYPE_OTHER
            tag = ''
            if (vid, pid) == (0x057e, 0x2009):
                dev_type = TYPE_SWITCH_PRO
                tag = 'SwitchPro'
            elif is_xinput_gamepad(desc):
                dev_type = TYPE_XINPUT
                tag = 'XInput'
            elif is_hid_gamepad(desc):
                dev_type = TYPE_HID_GAMEPAD
                tag = 'HIDGamepad'
            elif int0_info == (0x03, 0x01, 0x01):
                dev_type = TYPE_BOOT_KEYBOARD
                tag = 'BootKeyboard'
            elif int0_info == (0x03, 0x01, 0x02):
                dev_type = TYPE_BOOT_MOUSE
                tag = 'BootMouse'
            elif int0_info == (0x03, 0x00, 0x00):
                dev_type = TYPE_HID
                tag = 'HID'
            return ScanResult(device, dev_type, vid, pid, tag,
                dev_info, int0_info, int0_outs, int0_ins)
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
    def __init__(self, device, dev_type, vid, pid, tag, dev_info, int0_info,
        int0_outs, int0_ins
        ):
        if len(dev_info) != 3:
            raise ValueError("Expected (class,subclass,protocol) for dev_info")
        if len(int0_info) != 3:
            raise ValueError("Expected (class,subclass,protocol) for int0_info")
        self.device = device
        self.dev_type = dev_type
        self.vid = vid
        self.pid = pid
        self.tag = tag
        self.dev_info = dev_info
        self.int0_info = int0_info
        self.int0_outs = int0_outs
        self.int0_ins = int0_ins


def is_hid_gamepad(descriptor):
    # Return True if descriptor details match pattern for generic HID gamepad
    # - descriptor: usb_descriptor.Descriptor instance
    #
    # This should generally work for PC style DInput gamepads and other types
    # of vanilla HID gamepads, such as inexpensive (non-Pro) USB wired Switch
    # controllers.
    #
    # CAUTION! Button, dpad, stick, and trigger mappings for this type of
    # gamepad are notoriously quirky. Control layout within the HID reports is
    # up to the manufacturer. Some devices may send HID reports that do not
    # match what's listed in their HID report descriptors.
    dev_info = descriptor.dev_class_subclass_protocol()
    int0_info = descriptor.int0_class_subclass_protocol()
    if dev_info != (0x00, 0x00, 0x00):
        return False
    if int0_info == (0x03, 0x00, 0x00):
        # This is a composite HID interface. Might be gamepad. Might not.
        # TODO: actually look inside the HID descriptor for gamepad/joystick
        logger.error('TODO: CHECK HID REPORT DESCRIPTOR. GAMEPAD?')
        return True
    return False

def is_xinput_gamepad(descriptor):
    # Return True if descriptor details match pattern for an XInput gamepad
    # - descriptor: usb_descriptor.Descriptor instance
    d = descriptor
    dev_info = descriptor.dev_class_subclass_protocol()
    int0_info = descriptor.int0_class_subclass_protocol()
    if dev_info != (0xff, 0xff, 0xff):
        return False
    if d.configs[0].bNumInterfaces != 4:
        return False
    if int0_info == (0xff, 0x5d, 0x01):
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

def elapsed_ms_generator():
    # This can be used to measure time intervals efficiently.
    # - returns: an iterator
    # - iterator yields: ms since last call to next(iterator)
    #
    # Technically speaking, this is a generator function that returns an
    # iterator. The iterator is a generator. The generator yields a time
    # interval in milliseconds each time next() is called on the iterator. The
    # interval is the elapsed time between the current and previous iterations.
    #
    # This is intended to help throttle USB device access to avoid tying the
    # CPU up with too much interrupt handling or irritating the USB device by
    # polling it too frequently.
    #
    ms = ticks_ms      # caching function ref avoids dictionary lookups
    mask = 0x3fffffff  # (2**29)-1 because ticks_ms rolls over at 2**29
    t0 = ms()
    while True:
        t1 = ms()
        delta = (t1 - t0) & mask  # handle possible timer rollover gracefully
        t0 = t1
        yield delta


class InputDevice:
    def __init__(self, scan_result, player=1):
        # Initialize buffers used in polling USB gamepad events
        # - scan_result: a ScanResult instance
        # - player: player number for setting gamepad LEDs (in range 1..4)
        # Exceptions:
        # - may raise usb.core.USBError
        #
        device = scan_result.device
        dev_type = scan_result.dev_type
        self._prev = 0
        self.buf64 = bytearray(64)
        self.device = device
        self.player = player
        self.dev_type = dev_type
        # Make sure CircuitPython core is not claiming the device
        interface = 0
        if device.is_kernel_driver_active(interface):
            logger.debug('Detaching interface %d from kernel' % interface)
            device.detach_kernel_driver(interface)
        # Set configuration
        device.set_configuration()
        # Figure out which endpoints to use
        sr = scan_result
        endpoint_in  = None if (len(sr.int0_ins ) < 1) else sr.int0_ins[0]
        endpoint_out = None if (len(sr.int0_outs) < 1) else sr.int0_outs[0]
        logger.debug('INT0 IN: %s' % endpoint_in)
        logger.debug('INT0 OUT: %s' % endpoint_out)
        self.int0_endpoint_in = endpoint_in
        self.int0_endpoint_out = endpoint_out
        # Initialize USB device if needed (e.g. handshake or set gamepad LEDs)
        if dev_type == TYPE_SWITCH_PRO:
            # Make sure interface 0 has endpoints for handshake and reading
            if self.int0_endpoint_in is None or self.int0_endpoint_out is None:
                raise ValueError("Interface 0 descriptor is missing endpoints")
            self.init_switch_pro_gamepad()
        elif dev_type == TYPE_XINPUT:
            # Make sure interface 0 has endpoints for handshake and reading
            if self.int0_endpoint_in is None or self.int0_endpoint_out is None:
                raise ValueError("Interface 0 descriptor is missing endpoints")
            self.init_xinput()
        elif dev_type == TYPE_BOOT_MOUSE:
            # TODO: maybe implement something for this. maybe.
            logger.info('Initializing Boot-Compatible Mouse')
        elif dev_type == TYPE_BOOT_KEYBOARD:
            # TODO: maybe implement something for this. maybe.
            logger.info('Initializing Boot-Compatible Keyboard')
        elif dev_type == TYPE_HID_GAMEPAD:
            # This covers PC style "DirectInput" or "DInput" along with other
            # types of generic HID gamepads (e.g. non-Pro Switch controllers)
            # Make sure interface 0 has endpoint for reading
            if self.int0_endpoint_in is None:
                raise ValueError("Interface 0 descriptor is missing endpoint")
        elif dev_type == TYPE_HID:
            # TODO: maybe dump some HID descriptor info?
            logger.info('Initializing HID device')
        elif dev_type == TYPE_OTHER:
            # ignore these
            pass
        else:
            raise ValueError('Unknown dev_type: %d' % dev_type)

    def init_switch_pro_gamepad(self):
        # Prepare Switch Pro compatible gamepad for use.
        # Exceptions: may raise usb.core.USBError and usb.core.USBTimeoutError
        #
        # Control messages:
        # - 0x80 0x01: get device type and mac address
        # - 0x80 0x02: handshake
        # - 0x80 0x03: use faster baud rate
        # - 0x80 0x04: switch to USB HID mode with no timeout
        #
        logger.info('Initializing SwitchPro gamepad')
        # Output Stuff
        out_addr = self.int0_endpoint_out.bEndpointAddress
        out_interval = self.int0_endpoint_out.bInterval
        # Input Stuff
        in_addr = self.int0_endpoint_in.bEndpointAddress
        in_interval = self.int0_endpoint_in.bInterval
        max_packet = min(64, self.int0_endpoint_in.wMaxPacketSize)
        data = bytearray(max_packet)

        # Send handshake messages
        msg = bytearray(2)
        for code in [0x8001, 0x8002, 0x8003, 0x8002, 0x8004]:
            msg[0] = (code >> 8) & 0xff
            msg[1] = code & 0xff
            try:
                logger.info('SEND: 0x%04x' % code)
                self.device.write(out_addr, msg, out_interval)
            except USBTimeoutError:
                # Attempt 1 retry if first write timed out
                logger.info('RETRY: 0x%04x' % code)
                self.device.write(out_addr, msg, out_interval)
            # Wait for ACK (mostly same as msg with 0x81 in place of 0x80)
            okay = False
            for _ in range(8):
                try:
                    self.device.read(in_addr, data, timeout=in_interval)
                    (reply,) = unpack_from('>H', data, 0)
                    expect = (code | 0x0100) if (code != 0x8004) else 0x8102
                    if reply == expect:
                        if reply == 0x8101:
                            logger.info('ACK STATUS %s' % ' '.join(
                                ['%02x' % b for b in data]))
                        elif reply == 0x8102:
                            logger.info('ACK HANDSHAKE')
                        elif reply == 0x8103:
                            logger.info('ACK BAUD RATE')
                        else:
                            logger.info('ACK: 0x%04x' % reply)
                        okay = True
                        break
                    else:
                        logger.info('UNEXPECTED: %s' % data)
                except USBTimeoutError:
                    logger.debug('READ TIMEOUT')
                    pass
            if not okay:
                logger.error("HANDSHAKE FAILED")
                return

    def init_xinput(self):
        # Prepare XInput gamepad for use.
        # Exceptions: may raise usb.core.USBError
        logger.info('Initializing XInput gamepad')
        # Input Stuff
        in_addr = self.int0_endpoint_in.bEndpointAddress
        in_interval = self.int0_endpoint_in.bInterval
        max_packet = min(64, self.int0_endpoint_in.wMaxPacketSize)
        data = bytearray(max_packet)
        # LED
        set_xinput_led(self.device, self.player)
        # Some XInput gamepads send a bunch of stuff initially before normal
        # reports begin, so drain the input pipe
        for _ in range(8):
            try:
                self.device.read(in_addr, data, timeout=in_interval)
            except USBTimeoutError as e:
                # Ignore timeouts
                pass

    def input_event_generator(self):
        # This is a generator that makes an iterable for reading input events.
        # - returns: iterable that can be used with a for loop
        # - yields: uint16 bitfield of current button state. In case of read
        #   timeout or timer throttle, yield value is None.
        # Exceptions: may raise usb.core.USBError
        #
        # This allows calling code to use a for loop to read a stream of input
        # events from a USB device without having to worry about which backend
        # driver is creating the events.
        #
        # The advantage of this mildly convoluted implementation, compared to
        # a typical Python object oriented approach, is improved efficiency.
        # Other methods of dynamically switching between back-end IO drivers
        # would generally use far more of heap allocations and dictionary
        # lookups.
        #
        # Related Docs:
        # - https://docs.python.org/3/glossary.html#term-generator
        # - https://docs.python.org/3/glossary.html#term-iterable
        # - https://docs.micropython.org/en/latest/reference/speed_python.html
        #
        if self.device is None:
            # caller is trying to poll when device is not connected
            pass
        elif self.dev_type == TYPE_SWITCH_PRO:
            return self.switchpro_event_generator()
        elif self.dev_type == TYPE_XINPUT:
            return self.xinput_event_generator()
        elif self.dev_type == TYPE_HID_GAMEPAD:
            pass
        # Default fallback generator (yield raw report data)
        return self.generic_hid_event_generator()

    def generic_hid_event_generator(self):
        # Generator function: read from interface 0 and yield raw report data
        # - yields: memoryview of bytes
        # Exceptions: may raise core.usb.USBError
        #
        # The point of this is get report data from an unknown HID device.

        # Input Stuff
        # This uses two data buffers so its possible to compare the previous
        # report value with the most recent report value
        in_addr = self.int0_endpoint_in.bEndpointAddress
        interval = self.int0_endpoint_in.bInterval
        max_packet = min(64, self.int0_endpoint_in.wMaxPacketSize)
        odd = True
        data_odd  = bytearray(max_packet)
        data_even = bytearray(max_packet)
        mv_odd    = memoryview(data_odd)  # memoryview reduces heap allocations
        mv_even   = memoryview(data_even)
        prev_report = mv_even
        delay = 0
        delta_ms = elapsed_ms_generator()  # call generator to make iterator
        dev_read = self.device.read  # cache function to avoid dictionary lookups
        # Start polling for input.
        # NOTE: To understand what this does, you need to understand the Python
        # concepts of generator functions, iterators, and generators. The point
        # of this is to reduce memory pressure from lots of heap allocations
        # and to reduce CPU time spent on dictionary lookups.
        while True:
            # Respect the USB device's polling interval
            delay += next(delta_ms)
            if delay < interval:
                yield None
                continue
            else:
                delay = 0
            # Okay, now enough time has passed, so poll the endpoint
            curr_data = data_odd if odd else data_even
            try:
                # Read report and compare its trimmed data to that of the
                # previous report. If they differ, then update the previous
                # value, swap the the active buffer, and yield a memoryview
                # into the most recent trimmed report data. The even/odd buffer
                # swapping is necessary for the memoryview stuff to work
                # properly.
                if odd:
                    n = dev_read(in_addr, data_odd, timeout=interval)
                    report = mv_odd[:n]
                    if report != prev_report:
                        prev_report = report
                        odd = False
                        yield report
                    else:
                        yield None
                else:
                    n = dev_read(in_addr, data_even, timeout=interval)
                    report = mv_even[:n]
                    if report != prev_report:
                        prev_report = report
                        odd = True
                        yield report
                    else:
                        yield None
            except USBTimeoutError as e:
                # This is normal. Timeouts happen fairly often.
                yield None
            except USBError as e:
                # This may happen when device is unplugged (or might time out)
                raise e

    def switchpro_event_generator(self):
        # Generator function to make an iterable for reading SwitchPro events
        # - returns: iterable that can be used with a for loop
        # - yields: uint16 bitfield of current button state. In case of read
        #   timeout or timer throttle, yield value is None.
        # Exceptions: may raise usb.core.USBError
        #
        in_addr = self.int0_endpoint_in.bEndpointAddress
        interval = self.int0_endpoint_in.bInterval
        max_packet = min(64, self.int0_endpoint_in.wMaxPacketSize)
        data = bytearray(max_packet)
        data_mv = memoryview(data)  # use memoryview to reduce heap allocations
        delay = 0
        delta_ms = elapsed_ms_generator()  # call generator to make iterator
        dev_read = self.device.read  # cache function to avoid dictionary lookups
        # Start polling for input.
        # NOTE: To understand what this does, you need to understand the Python
        # concepts of generator functions, iterators, and generators. The point
        # of this is to reduce memory pressure from lots of heap allocations
        # and to reduce CPU time spent on dictionary lookups.
        while True:
            # Respect the USB device's polling interval
            delay += next(delta_ms)
            if delay < interval:
                yield None
                continue
            else:
                delay = 0
            # Okay, now enough time has passed, so poll the endpoint
            try:
                # Poll gamepad endpoint and extract only the button state,
                # ignoring sticks and triggers
                dev_read(in_addr, data, timeout=interval)
                logger.info(' '.join(['%02x' % b for b in data_mv[:20]]))
                (buttons,) = unpack_from('<H', data, 2)
                yield buttons
            except USBTimeoutError as e:
                # This is normal. Timeouts happen fairly often.
                yield None
            except USBError as e:
                # This may happen when device is unplugged (or might time out)
                raise e

    def xinput_event_generator(self):
        # Generator function to make an iterable for reading XInput events
        # - returns: iterable that can be used with a for loop
        # - yields: uint16 bitfield of current button state. In case of read
        #   timeout or timer throttle, yield value is None.
        # Exceptions: may raise usb.core.USBError
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

        # Input Stuff
        in_addr = self.int0_endpoint_in.bEndpointAddress
        interval = self.int0_endpoint_in.bInterval
        max_packet = min(64, self.int0_endpoint_in.wMaxPacketSize)
        data = bytearray(max_packet)
        delay = 0
        delta_ms = elapsed_ms_generator()  # call generator to make iterator
        dev_read = self.device.read  # cache function to avoid dictionary lookups
        # Start polling for input.
        # NOTE: To understand what this does, you need to understand the Python
        # concepts of generator functions, iterators, and generators. The point
        # of this is to reduce memory pressure from lots of heap allocations
        # and to reduce CPU time spent on dictionary lookups.
        while True:
            # Respect the USB device's polling interval
            delay += next(delta_ms)
            if delay < interval:
                yield None
                continue
            else:
                delay = 0
            # Okay, now enough time has passed, so poll the endpoint
            try:
                # Poll gamepad endpoint and extract only the button state,
                # ignoring sticks and triggers
                dev_read(in_addr, data, timeout=interval)
                (buttons,) = unpack_from('<H', data, 2)
                yield buttons
            except USBTimeoutError as e:
                # This is normal. Timeouts happen fairly often.
                yield None
            except USBError as e:
                # This may happen when device is unplugged (or might time out)
                raise e
