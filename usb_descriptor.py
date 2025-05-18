# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright 2025 Sam Blenny
#
# Descriptor parser for USB devices
#
# Related Documentation:
# - https://docs.circuitpython.org/en/latest/shared-bindings/usb/core/index.html
# - https://docs.circuitpython.org/projects/logging/en/latest/api.html
# - https://learn.adafruit.com/a-logger-for-circuitpython/overview
#
from usb import core
from usb.core import USBError, USBTimeoutError

import adafruit_logging as logging

from hid_report import HIDReportDesc


# Configure logging
logger = logging.getLogger('usb_descriptor')
logger.setLevel(logging.DEBUG)


def test_hid_report_descriptor_parser():
    # Call this if you want to test the HID report descriptor parser
    # CAUTION: This import will use a lot of memory for strings and bytearrays
    import test_data
#     device = test_data.COMPACT_KEYBOARD
#     device = test_data.CHEAP_MOUSE
#     device = test_data.POWERA
#     device = test_data.ULTIMATE_BT
#     device = test_data.ZERO2
    device = test_data.SN30PRO_BT_DINPUT
#     device = test_data.SN30PRO_BT_SWITCH
    hid_report_desc = device['interfaces'][0]['hidreport']
    print()
    print(HIDReportDesc(hid_report_desc, indent=0))

def get_desc(device, desc_type, bmRequestType=0x80, wIndex=0, length=256):
    # Read USB descriptor of type specified by desc_type (index always 0).
    # - device: a usb.core.Device
    # - desc_type: uint8 value for the descriptor type field of wValue
    # - wIndex: uint8 value for selecting interface to use
    # - returns: bytearray with results from ctrl_transfer()
    if not (18 <= length <= 512):
        raise ValueError("Bad descriptor length: %d" % length)
    data = bytearray(length)
    # ctrl_transfer(bmRequestType, bRequest, wValue, wIndex, data, timeout)
    wValue = (desc_type << 8) | 0
    device.ctrl_transfer(bmRequestType, 6, wValue, wIndex, data, 300)
    return data

def split_desc(data):
    # Split a combined descriptor into its individual sub-descriptors
    # - data: a bytearray of descriptor data from ctrl_transfer()
    # - returns: array of bytearrays (first byte of each is length)
    slices = []
    cursor = 0
    limit = len(data)
    data_mv = memoryview(data)  # use memoryview to reduce heap allocations
    for i in range(limit):
        if cursor == limit:
            break
        length = data[cursor]
        if length == 0:
            break
        if cursor + length > limit:
            logger.error('Bad descriptor length: data[%d]=%d' % (i, length))
            break
        slices.append(data_mv[cursor:cursor+length])
        cursor += length
    return slices

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
        data_mv = memoryview(data)  # use memoryview to reduce heap allocations
        for offset in range(0, len(data_mv), bytes_per_line):
            chunk = data_mv[offset:offset+bytes_per_line]
            arr.append((' ' * indent) + ' '.join(['%02x' % b for b in chunk]))
    else:
        log.error("Unexpected dump_desc arg type %s" % type(data))
    return "\n".join(arr)


class ConfigDesc:
    def __init__(self, d):
        # Parse a configuration descriptor
        # - d: bytearray containing a 9 byte configuration descriptor
        if len(d) != 9 or d[0] != 0x09 or d[1] != 0x02:
            raise ValueError("Bad configuration descriptor")
        self.bNumInterfaces      = d[4]
        self.bConfigurationValue = d[5]  # for set_configuration()
        self.bMaxPower           = d[8]  # units are 2 mA

    def __str__(self):
        fmt = '  Config %d: NumInterfaces: %d, MaxPower: %d mA'
        return fmt % (
            self.bConfigurationValue,
            self.bNumInterfaces,
            self.bMaxPower * 2)


class InterfaceDesc:
    def __init__(self, d):
        # Parse an interface descriptor
        # - d: bytearray containing a 9 byte interface descriptor
        if len(d) != 9 or d[0] != 0x09 or d[1] != 0x04:
            raise ValueError("Bad interface descriptor")
        self.bInterfaceNumber   = d[2]
        self.bNumEndpoints      = d[4]
        self.bInterfaceClass    = d[5]
        self.bInterfaceSubClass = d[6]
        self.bInterfaceProtocol = d[7]
        self.endpoint = []
        self.hid = []

    def add_endpoint_descriptor(self, data):
        self.endpoint.append(EndpointDesc(data))

    def add_hid_descriptor(self, data, device):
        self.hid.append(HIDDesc(data, device, self.bInterfaceNumber))

    def __str__(self):
        fmt = ('  Interface %d: '
            'Endpoints: %d, Class: 0x%02x, SubClass: 0x%02x, Protocol: 0x%02x')
        chunks = [fmt % (
            self.bInterfaceNumber,
            self.bNumEndpoints,
            self.bInterfaceClass,
            self.bInterfaceSubClass,
            self.bInterfaceProtocol)]
        for e in self.endpoint:
            chunks.append(str(e))
        for h in self.hid:
            chunks.append(str(h))
        return '\n'.join(chunks)


class EndpointDesc:
    def __init__(self, d):
        # Parse an endpoint descriptor
        # - d: bytearray containing a 7 byte endpoint descriptor
        if len(d) != 7 or d[0] != 0x07 or d[1] != 0x05:
            raise ValueError("Bad endpoint descriptor")
        self.bEndpointAddress   = d[2]
        # bmAttributes low 2 bits: 0:control, 1:iso., 2:bulk, 3:interrupt
        self.bmAttributes       = d[3]
        self.wMaxPacketSize     = (d[5] << 8) | d[4]
        self.bInterval          = d[6]

    def __str__(self):
        fmt = ('    Endpoint 0x%02x: '
            'bmAttributes: 0x%02x, wMaxPacketSize: %d, bInterval: %d ms')
        return fmt % (
            self.bEndpointAddress,
            self.bmAttributes,
            self.wMaxPacketSize,
            self.bInterval)


class HIDDesc:
    def __init__(self, d, device, bInterfaceNumber):
        # Parse an HID descriptor
        # - d: bytearray containing an HID descriptor (9 or more bytes)
        # - bInterfaceNumber: number of parent interface
        if (len(d) < 9) or (d[0] < 9) or (d[1] != 0x21):
            raise ValueError("Bad HID descriptor")
        bLength         = d[0]
        bNumDescriptors = d[5]
        # Parse list of bDescriptorType + wDescriptorLength pairs with length
        # determined by value of bNumDescriptors
        if 6 + (bNumDescriptors * 3) != bLength:
            raise ValueError("Bad HID descriptor (bNumDescriptors)")
        sub_descriptors = []
        self.bLength         = bLength
        self.bNumDescriptors = bNumDescriptors
        self.sub_descriptors = sub_descriptors
        for i in range(bNumDescriptors):
            base = 6 + (i * 3)
            bDescriptorType = d[base]
            wDescriptorLength = (d[base+2] << 8) | d[base+1]
            data = bytearray(0)
            # Fetch HID Report descriptor if it's not too huge. The other
            # possibility for bDescriptorType is 0x23 (physical descriptor)
            # which we can safely ignore.
            if bDescriptorType == 0x22 and wDescriptorLength <= 512:
                data = get_desc(device, bDescriptorType, bmRequestType=0x81,
                    wIndex=bInterfaceNumber, length=wDescriptorLength)
            else:
                logger.error(
                    "Ignoring long HID descriptor: %d" % wDescriptorLength)
            sub_descriptors.append(
                HIDSubDesc(bDescriptorType, wDescriptorLength, data))

    def __str__(self):
        fmt = '    HID: bNumDescriptors: %d'
        chunks = [fmt % self.bNumDescriptors]
        for subd in self.sub_descriptors:
            chunks.append(str(subd))
        return '\n'.join(chunks)


class HIDSubDesc:
    def __init__(self, bDescriptorType, wDescriptorLength, data):
        self.bDescriptorType = bDescriptorType
        self.wDescriptorLength = wDescriptorLength
        self.data = data
        # data is a bytearray that can be 0 length for an HID physical
        # descriptor (bDescriptorType = 0x23) or when the configuration parser
        # decides to skip a very long HID report descriptor (type 0x22).
        if len(data) == 0:
            self.hid_report_desc = None
        else:
            self.hid_report_desc = HIDReportDesc(data)

    def __str__(self):
        fmt = """      bDescriptorType: 0x%02x, wDescriptorLength: %d
      HID Report Descriptor Bytes:
%s"""
        chunks = [fmt % (
            self.bDescriptorType,
            self.wDescriptorLength,
            dump_desc(self.data, indent=8))]
        if self.hid_report_desc:
            chunks.append(str(self.hid_report_desc))
        return '\n'.join(chunks)


class Descriptor:
    def __init__(self, device):
        # Read and parse USB device descriptor
        # - device: usb.core.Device
        #
        # CAUTION: This does not read the configuration descriptor. You do that
        # by calling read_configuration(). The point of splitting the work into
        # two functions is to let the calling code quickly check the device
        # descriptor before deciding to spend the time and memory on parsing
        # the whole configuration.
        #
        device_desc = get_desc(device, 0x01, length=18)
        length = device_desc[0]
        if length == 0:
            raise ValueError("Empty Device Descriptor")
        elif length != 18:
            raise ValueError('Bad Device Descriptor Length: %d' % length)
        # Parse device descriptor (should be 18 bytes long)
        d = device_desc
        self.device_desc_bytes = d
        self.bcdUSB             = (d[ 3] << 8) | d[ 2]
        self.bDeviceClass       = d[4]
        self.bDeviceSubClass    = d[5]
        self.bDeviceProtocol    = d[6]
        self.bMaxPacketSize0    = d[7]
        self.idVendor           = (d[ 9] << 8) | d[ 8]
        self.idProduct          = (d[11] << 8) | d[10]
        self.iManufacturer      = d[14]
        self.iProduct           = d[15]
        self.iSerialNumber      = d[16]
        self.bNumConfigurations = d[17]
        # Make an empty placeholder configuration
        self.config_desc_list = []
        self.configs = []
        self.interfaces = []

    def vid_pid(self):
        # Return tuble with USB device vendor and product IDs
        return (self.idVendor, self.idProduct)

    def dev_class_subclass_protocol(self):
        # Return class, subclass, and protocol from devic descriptor
        return (self.bDeviceClass, self.bDeviceSubClass, self.bDeviceProtocol)

    def int0_class_subclass_protocol(self):
        # Return class, subclass, and protocol for interface 0
        for i in self.interfaces:
            if i.bInterfaceNumber == 0:
                return (
                    i.bInterfaceClass,
                    i.bInterfaceSubClass,
                    i.bInterfaceProtocol)
        return (None, None, None)

    def int0_output_endpoints(self):
        # Return list of output endpoints for interface 0
        arr = []
        input_mask = 0x80
        for i in self.interfaces:
            if i.bInterfaceNumber == 0:
                for e in i.endpoint:
                    if not (e.bEndpointAddress & input_mask):
                        arr.append(e)
        return arr

    def int0_input_endpoints(self):
        # Return list of input endpoints for interface 0
        arr = []
        input_mask = 0x80
        for i in self.interfaces:
            if i.bInterfaceNumber == 0:
                for e in i.endpoint:
                    if (e.bEndpointAddress & input_mask):
                        arr.append(e)
        return arr

    def read_configuration(self, device):
        # Read and parse USB configuration descriptor
        # - device: usb.core.Device
        config_desc_list = split_desc(get_desc(device, 0x02, length=256))
        if len(config_desc_list) == 0:
            raise ValueError("Empty Configuration Descriptor")
        self.config_desc_list = config_desc_list
        self.configs    = []
        self.interfaces = []
        i = -1
        for d in config_desc_list:
            if len(d) < 2:
                continue
            bLength = d[0]
            bDescriptorType = d[1]
            tag = (bLength << 8) | bDescriptorType
            try:
                if tag == 0x0902:
                    # Configuration
                    self.configs.append(ConfigDesc(d))
                elif tag == 0x0904:
                    # Interface
                    self.interfaces.append(InterfaceDesc(d))
                    # Remember interface index for associating endpoint & HID
                    i += 1
                elif tag == 0x0705:
                    # Endpoint
                    if i >= 0:
                        self.interfaces[i].add_endpoint_descriptor(d)
                    else:
                        raise ValueError("Found endpoint before interface")
                elif self.bDeviceClass == 0x00 and bDescriptorType == 0x21:
                    # HID
                    if i >= 0:
                        self.interfaces[i].add_hid_descriptor(d, device)
                    else:
                        raise ValueError("Found HID before interface")
            except ValueError as e:
                logger.error(dump_desc(d, str(e)))
                raise e

    def to_bytes(self):
        return self.device_desc_bytes

    def __str__(self):
        fmt = """Descriptor:
  Device Descriptor Bytes:
%s
  Config Descriptor Bytes:
%s
  bcdUSB: 0x%04x
  bDeviceClass: 0x%02x
  bDeviceSubClass: 0x%02x
  bDeviceProtocol: 0x%02x
  bMaxPacketSize0: %d
  idVendor: 0x%04x
  idProduct: 0x%04x
  iManufacturer: %d
  iProduct: %d
  iSerialNumber: %d
  bNumConfigurations: %d"""
        chunks = [fmt % (
            dump_desc(self.device_desc_bytes, indent=4),
            dump_desc(self.config_desc_list, indent=4),
            self.bcdUSB,
            self.bDeviceClass,
            self.bDeviceSubClass,
            self.bDeviceProtocol,
            self.bMaxPacketSize0,
            self.idVendor,
            self.idProduct,
            self.iManufacturer,
            self.iProduct,
            self.iSerialNumber,
            self.bNumConfigurations)]
        for lst in [self.configs, self.interfaces]:
            for item in lst:
                chunks.append(str(item))
        return "\n".join(chunks)
