# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright 2025 Sam Blenny
#
# Gamepad driver for various USB wired gamepads.
#
# NOTE: This code does a lot of IO very quickly (by CircuitPython standards),
# so it uses performance boosting tricks to avoid bogging down the CPU or
# making a lot of heap allocations. To learn more about caching function
# references, caching instance variables, and making iterators with generator
# functions, check out the links below.
#
# Related docs:
# - https://docs.circuitpython.org/projects/logging/en/latest/api.html
# - https://learn.adafruit.com/a-logger-for-circuitpython/overview
# - https://docs.python.org/3/glossary.html#term-generator
# - https://docs.python.org/3/glossary.html#term-iterable
# - https://docs.micropython.org/en/latest/reference/speed_python.html
#
import binascii
import gc
from micropython import const
from struct import unpack, unpack_from
from supervisor import ticks_ms
from time import sleep
from usb import core
from usb.core import USBError, USBTimeoutError
from usb.util import SPEED_LOW, SPEED_FULL, SPEED_HIGH

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
TYPE_SWITCH_PRO    = const(1)  # 057e:2009 clones of Switch Pro Controller
TYPE_ADAFRUIT_SNES = const(2)  # 081f:e401 generic SNES layout HID, low-speed
TYPE_8BITDO_ZERO2  = const(3)  # 2dc8:9018 mini SNES layout, HID over USB-C
TYPE_XINPUT        = const(4)  # (vid:pid vary) Clones of Xbox360 controller
TYPE_BOOT_MOUSE    = const(5)
TYPE_BOOT_KEYBOARD = const(6)
TYPE_HID_COMPOSITE = const(7)
TYPE_HID           = const(8)


def find_usb_device(device_cache):
    # Find a USB wired gamepad by inspecting usb device descriptors
    # - device_cache: dictionary of previously checked device descriptors
    # - return: ScanResult object for success or None for failure.
    # Exceptions: may raise usb.core.USBError or usb.core.USBTimeoutError
    #
    for device in core.find(find_all=True):
        # Read descriptors to identify devices by type
        try:
            desc = usb_descriptor.Descriptor(device)
            k = str(desc.to_bytes())
            if k in device_cache:
                return None
            # Remember this device to avoid repeatedly checking it later
            device_cache[k] = True
            # Compare descriptor to known device type fingerprints
            desc.read_configuration(device)
            vid, pid = desc.vid_pid()
            int0_info = desc.int0_class_subclass_protocol()
            logger.info(desc)
            dev = device
            if (vid, pid) == (0x057e, 0x2009):
                return ScanResult(dev, TYPE_SWITCH_PRO, 'SwitchPro', desc)
            elif (vid, pid) == (0x081f, 0xe401):
                # Generic SNES layout HID gamepad sold by Adafruit
                return ScanResult(dev, TYPE_ADAFRUIT_SNES, 'AdafruitSNES', desc)
            elif (vid, pid) == (0x2dc8, 0x9018):
                # This one is HID but quirky, so it needs special handling
                return ScanResult(dev, TYPE_8BITDO_ZERO2, '8BitDoZero2', desc)
            elif is_xinput_gamepad(desc):
                return ScanResult(dev, TYPE_XINPUT, 'XInput', desc)
            elif is_hid_composite(desc):
                return ScanResult(dev, TYPE_HID_COMPOSITE, 'HIDComposite', desc)
            elif int0_info == (0x03, 0x01, 0x01):
                return ScanResult(dev, TYPE_BOOT_KEYBOARD, 'BootKeyboard', desc)
            elif int0_info == (0x03, 0x01, 0x02):
                return ScanResult(dev, TYPE_BOOT_MOUSE, 'BootMouse', desc)
            elif int0_info == (0x03, 0x00, 0x00):
                return ScanResult(dev, TYPE_HID, 'HID', desc)
            else:
                logger.info("IGNORING UNRECOGNIZED DEVICE")
                return None
        except ValueError as e:
            logger.info(e)
        except USBError as e:
            logger.info("find_usb_device() USBError: '%s'" % e)
    return None


class ScanResult:
    def __init__(self, device, dev_type, tag, descriptor):
        self.device = device
        self.dev_type = dev_type
        self.tag = tag
        self.descriptor = descriptor
        self.vid = descriptor.idVendor
        self.pid = descriptor.idProduct
        self.dev_info = descriptor.dev_class_subclass_protocol()
        self.int0_info = descriptor.int0_class_subclass_protocol()



def is_hid_composite(descriptor):
    # Return True if descriptor details look like a composite HID device.
    # - descriptor: usb_descriptor.Descriptor instance
    #
    # This could be a gamepad. Or, might be another type of HID input device.
    #
    dev_info = descriptor.dev_class_subclass_protocol()
    int0_info = descriptor.int0_class_subclass_protocol()
    return dev_info == (0x00, 0x00, 0x00) and int0_info == (0x03, 0x00, 0x00)

def is_xinput_gamepad(descriptor):
    # Return True if descriptor details match pattern for an XInput gamepad
    # - descriptor: usb_descriptor.Descriptor instance
    d = descriptor
    dev_info = descriptor.dev_class_subclass_protocol()
    int0_info = descriptor.int0_class_subclass_protocol()
    if dev_info != (0xff, 0xff, 0xff):
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
        int0_ins = scan_result.descriptor.int0_input_endpoints()
        int0_outs = scan_result.descriptor.int0_output_endpoints()
        endpoint_in  = None if (len(int0_ins) < 1) else int0_ins[0]
        endpoint_out = None if (len(int0_outs) < 1) else int0_outs[0]
        logger.debug('INT0 IN: %s' % endpoint_in)
        logger.debug('INT0 OUT: %s' % endpoint_out)
        self.int0_endpoint_in = endpoint_in
        self.int0_endpoint_out = endpoint_out
        # Initialize USB device if needed (e.g. handshake or set gamepad LEDs)
        if dev_type == TYPE_SWITCH_PRO:
            self.init_switch_pro_gamepad()
        elif dev_type == TYPE_ADAFRUIT_SNES:
            logger.info('Initializing Adafruit SNES-like gamepad')
        elif dev_type == TYPE_8BITDO_ZERO2:
            logger.info('Initializing 8BitDo Zero 2 gamepad')
        elif dev_type == TYPE_XINPUT:
            self.init_xinput()
        elif dev_type == TYPE_BOOT_MOUSE:
            logger.info('Initializing Boot-Compatible Mouse')
        elif dev_type == TYPE_BOOT_KEYBOARD:
            logger.info('Initializing Boot-Compatible Keyboard')
        elif dev_type == TYPE_HID_COMPOSITE:
            logger.info('Initializing HID composite device')
        elif dev_type == TYPE_HID:
            logger.info('Initializing HID device')
        else:
            raise ValueError('Unknown dev_type: %d' % dev_type)

    def init_switch_pro_gamepad(self):
        # Prepare Switch Pro compatible gamepad for use.
        # Exceptions: may raise usb.core.USBError and usb.core.USBTimeoutError
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
        data_mv = memoryview(data)

        messages = (
            bytes(b'\x80\x01'),  # get device type and mac address
            bytes(b'\x80\x02'),  # handshake
            bytes(b'\x80\x03'),  # set faster baud rate
            bytes(b'\x80\x02'),  # handshake
            bytes(b'\x80\x04'),  # use USB HID only and disable timeout
            # set input report mode to standard
            bytes(b'\x01\x06\x00\x00\x00\x00\x00\x00\x00\x00\x03\x30'),
            # set player LED1 to on (for LED1+LED2 do 30 03, etc.)
            bytes(b'\x01\x0a\x00\x00\x00\x00\x00\x00\x00\x00\x30\x01'),
            # set home LED
            bytes(b'\x01\x0b\x00\x00\x00\x00\x00\x00\x00\x00\x38\x01\x00\x00\x11\x11'),
        )
        # Send handshake messages
        hexdump = binascii.hexlify  # cache hexdumper function
        for msg in messages:
            try:
                self.device.write(out_addr, msg, timeout=2*out_interval)
            except USBTimeoutError as e:
                logger.error('SWITCH WRITE TIMEOUT %s' % hexdump(msg))
                raise ValueError("SwitchPro HANDSHAKE GLITCH (wr)")
            # Wait for ACK
            okay = False
            for _ in range(8):
                try:
                    self.device.read(in_addr, data, timeout=2*in_interval)
                    logger.info('ACK %s' % hexdump(data_mv[:2]))
                    # This just totally ignores the contents of gamepad's
                    # response. In practice, just waiting for any response
                    # seems to work?
                    okay = True
                    break
                except USBTimeoutError:
                    pass
            if not okay:
                # This happens pretty much every time with my 8BitDo Ultimate
                # Bluetooth Controller's 2.4 GHz USB adapter. The handshake
                # goes fine until I try to set the Home LED mode, but then it
                # times out. I must be missing some subtle aspect of the
                # handshake that isn't a problem for wired controllers. Result
                # is that the adapter resets several times then switches to
                # XInput mode with vid:pid 045e:028e. That works fine, so
                # whatever. TODO: Maybe research why this is glitching?
                raise ValueError("SwitchPro HANDSHAKE GLITCH (rd)")

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
        # - yields: (3 possibilities)
        #   1. Normalized 16-bit integer with XInput style button bitfield
        #   2. A memoryview(bytearray(...)) with raw or filtered data from
        #      polling the default endpoint.
        #   3. None in the case of a timeout or rate limit throttle
        # Exceptions: may raise usb.core.USBError
        #
        # This allows calling code to use a for loop to read a stream of input
        # events from a USB device without having to worry about which backend
        # driver is creating the events. The point of using generators is to
        # boost performance by avoiding heap allocations and dictionary lookups.
        #
        dev_type = self.dev_type  # cache this as we use it several times
        int0_gen = self.int0_read_generator  # cache to make shorter lines
        if self.device is None:
            # caller is trying to poll when device is not connected
            return None
        elif dev_type == TYPE_SWITCH_PRO:
            # Expected report format (cluster layout: A on right)
            # byte     0: report ID
            # byte     1: sequence number
            # byte     2: 0x01=Y, 0x02=X, 0x04=B, 0x08=A, 0x40=R, 0x80=R2
            # byte     3: 0x01=Select, 0x02=Start, 0x04=R_stick_btn,
            #             0x08=L_stick_btn, 0x10=Home=0x10, 0x20=Share
            # byte     4: DpadDn=0x01, DpadUp=0x02, DpadR=0x04, DpadL=0x08,
            #             0x40=L, 0x80=L2
            # bytes  6-8: Left stick X and Y (maybe 12 bits each ???)
            # bytes 9-11: Right stick X and Y (maybe 12 bits each ???)
            #
            # Generator function converts byte array to an XInput format uint16
            # - data: an iterator that yields memoryview(bytearray(...))
            def normalize_switchpro(data):
                for d in data:
                    if d is None:
                        yield None
                        continue
                    v = 0
                    d2 = d[0]      # byte 2 of the unfiltered report
                    d3 = d[1]      # byte 3 of the unfiltered report
                    d4 = d[2]      # byte 4 of the unfiltered report
                    if d2 == 0x01:
                        v |= Y
                    if d2 == 0x02:
                        v |= X
                    if d2 == 0x04:
                        v |= B
                    if d2 == 0x08:
                        v |= A
                    if d2 & 0x40:
                        v |= R
                    if d3 & 0x01:
                        v |= SELECT
                    if d3 & 0x02:
                        v |= START
                    if d4 & 0x01:
                        v |= DOWN
                    if d4 & 0x02:
                        v |= UP
                    if d4 & 0x04:
                        v |= RIGHT
                    if d4 & 0x08:
                        v |= LEFT
                    if d4 & 0x40:
                        v |= L
                    yield v
            # This filter lambda returns None when report ID is not 0x30.
            # For report ID 0x30, the filter trims off report ID, sequence
            # number, and IMU data, leaving just the bytes for buttons, dpad,
            # and sticks.
            filter_fn = lambda d: None if (d[0] != 0x30) else d[3:6]
            return normalize_switchpro(int0_gen(filter_fn=filter_fn))
        elif dev_type == TYPE_ADAFRUIT_SNES:
            # Expected report format (SNES cluster layout, A on right)
            # byte 0: (analog dpad) 0x00=dPadL, 0x7f=dPadCenter, 0xff=dPadR
            # byte 1: (analog dpad) 0x00=dPadUp, 0x7f=dPadCenter, 0xff=dPadDn
            # byte 2: unused (0x00)
            # byte 3: unused (0x80)
            # byte 4: unused (0x80)
            # byte 5: (bitfield) 0x10=X, 0x20=A, 0x40=B, 0x80=Y
            # byte 6: (bitfield) 0x01=L, 0x02=R, 0x10=Select, 0x20=Start
            # byte 7: unused (0x00)
            #
            # Generator function converts byte array to an XInput format uint16
            # - data: an iterator that yields memoryview(bytearray(...))
            def normalize_adasnes(data):
                for d in data:
                    if d is None:
                        yield None
                        continue
                    v = 0
                    d0 = d[0]
                    d1 = d[1]
                    d5 = d[5]
                    d6 = d[6]
                    if d0 == 0x00:
                        v |= LEFT
                    if d0 == 0xff:
                        v |= RIGHT
                    if d1 == 0x00:
                        v |= UP
                    if d1 == 0xff:
                        v |= DOWN
                    if d5 & 0x10:
                        v |= X
                    if d5 & 0x20:
                        v |= A
                    if d5 & 0x40:
                        v |= B
                    if d5 & 0x80:
                        v |= Y
                    if d6 & 0x01:
                        v |= L
                    if d6 & 0x02:
                        v |= R
                    if d6 & 0x10:
                        v |= SELECT
                    if d6 & 0x20:
                        v |= START
                    yield v
            return normalize_adasnes(int0_gen(filter_fn=lambda d: d[:7]))
        elif dev_type == TYPE_8BITDO_ZERO2:
            # This device is quirky because it alternates between 8 byte and
            # 24 byte HID reports. The 24 byte reports seem to be three of the
            # 8 byte reports stuck together. Also, the only interesting stuff
            # happens in the first 3 bytes.
            #
            # Expected report format (note dpad is 4-bit BCD style):
            # byte 0: 0x01=A, 0x02=B, 0x08=X, 0x10=Y, 0x40=L, 0x80=R
            # byte 1: 0x04=Select, 0x08=Start
            # byte 2: 0x00=dPadN, 0x01=dPadNE, 0x02=dPadE, 0x03=dPadSE,
            #         0x04=dPadS, 0x05=dPadSW, 0x06=dPadW, 0x07=dPadNW,
            #         0x0f=dPadCenter
            # bytes 3+: whatever... don't care
            #
            # Generator function converts byte array to an XInput format uint16
            # - data: an iterator that yields memoryview(bytearray(...))
            def normalize_zero2(data):
                for d in data:
                    if d is None:
                        yield None
                        continue
                    v = 0
                    d0 = d[0]      # byte 0 of the unfiltered report
                    d1 = d[1]      # byte 1 of the unfiltered report
                    d2 = d[2]      # byte 2 of the unfiltered report
                    if d0 & 0x01:
                        v |= A
                    if d0 & 0x02:
                        v |= B
                    if d0 & 0x08:
                        v |= X
                    if d0 & 0x10:
                        v |= Y
                    if d0 & 0x40:
                        v |= L
                    if d0 & 0x80:
                        v |= R
                    if d1 & 0x04:
                        v |= SELECT
                    if d1 & 0x08:
                        v |= START
                    # Decode 4-bit BCD style Dpad
                    if d2 == 0x00:        # N
                        v |= UP
                    elif d2 == 0x01:      # NE
                        v |= UP | RIGHT
                    elif d2 == 0x02:      # E
                        v |= RIGHT
                    elif d2 == 0x03:      # SE
                        v |= DOWN | RIGHT
                    elif d2 == 0x04:      # S
                        v |= DOWN
                    elif d2 == 0x05:      # SW
                        v |= DOWN | LEFT
                    elif d2 == 0x06:      # W
                        v |= LEFT
                    elif d2 == 0x07:      # NW
                        v |= UP | LEFT
                    yield v
            return normalize_zero2(int0_gen(filter_fn=lambda d: d[:3]))
        elif dev_type == TYPE_XINPUT:
            # Expected report format (clone w/ SNES cluster layout, A on right):
            #  bytes 0,1:    prefix that doesn't change
            #  bytes 2,3:    button bitfield for dpad, ABXY, etc (uint16)
            #  byte  4:      L2 left trigger (analog uint8)
            #  byte  5:      R2 right trigger (analog uint8)
            #  bytes 6,7:    LX left stick X axis (int16)
            #  bytes 8,9:    LY left stick Y axis (int16)
            #  bytes 10,11:  RX right stick X axis (int16)
            #  bytes 12,13:  RY right stick Y axis (int16)
            #  bytes 14..19: ???, but they don't change
            #
            # This filter trims off all the analog stuff (helps keep FPS up)
            filter_fn = lambda data: data[2:4]
            # Generator function converts byte array to an XInput format uint16
            # - data: an iterator that yields memoryview(bytearray(...))
            def normalize_xinput(data):
                for d in data:
                    yield None if d is None else unpack_from('<H', d, 0)[0]
            return normalize_xinput(int0_gen(filter_fn=filter_fn))
        elif dev_type == TYPE_BOOT_MOUSE:
            return int0_gen()
        elif dev_type == TYPE_BOOT_KEYBOARD:
            return int0_gen()
        elif dev_type == TYPE_HID_COMPOSITE:
            return int0_gen()
        elif dev_type == TYPE_HID:
            return int0_gen()
        elif dev_type == TYPE_OTHER:
            # Don't mess with unknown non-HID devices
            logger.info("Ignoring unknown device type")
            return
        else:
            logger.error('UNEXPECTED VALUE FOR dev_type: %d' % dev_type)

    def int0_read_generator(self, filter_fn=lambda d: d):
        # Generator function: read from interface 0 and yield raw report data
        # - filter_fn: Optional lambda function to modify raw reports. For
        #   example, this can slice off the incrementing sequence number
        #   included in SwitchPro reports (helping to detect input changes).
        # - yields: memoryview of bytes
        # Exceptions: may raise core.usb.USBError
        #
        # CAUTION: Polling frequency affects system stability. Poll too fast,
        # and CircuitPython seems more likely to crash. Too slow, and some USB
        # devices may reset.
        #
        # CAUTION: The meaning of bInterval is tricky and it depends on on the
        # the actual negotiated speed. For details, see USB 2.0 spec:
        #  - 5.6.4 Isochronous Transfer Bus Access Constraints
        #  - 9.6.6 Endpoint (table 9-13. Standard Endpoint Descriptor)
        # Meaning of bInterval based on connection speed (`^` here means
        # "raised to the power of"):
        #  - Low-speed: max time between polling requests = bInterval * 1 ms
        #  - Full-speed: max time = bInterval * 1 ms
        #  - High-speed: max time = 2^(bInterval-1) * 125 µs

        # Input Endpoint Stuff
        # This uses two data buffers so it's possible to compare the previous
        # report value with the most recent report value.
        in_addr = self.int0_endpoint_in.bEndpointAddress
        interval = self.int0_endpoint_in.bInterval
        if self.device.speed == SPEED_LOW:
            logger.info('LOW SPEED, period = %d ms' % interval)
        elif self.device.speed == SPEED_FULL:
            logger.info('FULL SPEED, period = %d ms' % interval)
        elif self.device.speed == SPEED_HIGH:
            # Units here are 125 µs or (1 ms)/8. Since timer resolution we have
            # available is 1 ms, quantize the requested interval to 1 ms units
            # (left shift 3 to divide by 8).
            interval = (2 << (interval - 1)) >> 3
            logger.info('HIGH SPEED, period = %d ms' % interval)
        max_packet = min(64, self.int0_endpoint_in.wMaxPacketSize)
        odd = True
        data_odd  = bytearray(max_packet)
        data_even = bytearray(max_packet)
        mv_odd    = memoryview(data_odd)  # memoryview reduces heap allocations
        mv_even   = memoryview(data_even)
        prev_report = mv_even
        dev_read = self.device.read  # cache function to avoid dictionary lookups

        # Make timer to throttle the polling rate because...
        # 1. Reading USB too much bogs down the system and fights with DVI
        # 2. Waiting too long to read USB will upset some devices
        poll_ms = 0
        poll_dt = elapsed_ms_generator()

        # Start polling loop
        #
        # NOTE: To understand what this does, you need to understand the Python
        # concepts of generator functions, iterators, and generators. The point
        # of this is to reduce memory pressure from lots of heap allocations
        # and to reduce CPU time spent on dictionary lookups.
        #
        while True:
            # Respect the USB device's polling interval
            poll_ms += next(poll_dt)
            if poll_ms < interval:
                yield None
                continue
            else:
                poll_ms = 0

            # Enough time has passed, so poll endpoint and compare report data
            # to that of the previous report. If they differ, update the
            # previous value, swap the active buffer, and yield a memoryview
            # into the most recent trimmed report data. The even/odd buffer
            # swapping is necessary for the memoryview stuff to work properly.
            #
            # NOTE: This is using a lambda function provided by the caller to
            # filter the raw data read from the endpoint. The lambda function
            # can return None when the current read should be skipped (e.g. HID
            # report with boring report ID).
            #
            curr_data = data_odd if odd else data_even
            try:
                if odd:
                    n = dev_read(in_addr, data_odd, timeout=interval)
                    report = filter_fn(mv_odd[:n])
                    if (report is None) or (report == prev_report):
                        yield None
                    else:
                        prev_report = report
                        odd = False
                        yield report
                else:
                    n = dev_read(in_addr, data_even, timeout=interval)
                    report = filter_fn(mv_even[:n])
                    if (report is None) or (report == prev_report):
                        yield None
                    else:
                        prev_report = report
                        odd = True
                        yield report
            except USBTimeoutError as e:
                # This is normal. Timeouts happen fairly often.
                yield None
            except USBError as e:
                # This may happen when device is unplugged (not always though)
                raise e
