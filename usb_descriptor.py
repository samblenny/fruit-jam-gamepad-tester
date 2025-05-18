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


# Configure logging
logger = logging.getLogger('usb_descriptor')
logger.setLevel(logging.DEBUG)


def get_desc(device, desc_type, bmRequestType=0x80, wIndex=0, length=256):
    # Read USB descriptor of type specified by desc_type (index always 0).
    # - device: a usb.core.Device
    # - desc_type: uint8 value for the descriptor type field of wValue
    # - wIndex: uint8 value for selecting interface to use
    # - returns: bytearray with results from ctrl_transfer()
    if not (18 <= length <= 512):
        raise ValueError("Bad descriptor length: %d" % length)
    data = bytearray(length)
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

    def add_endpoint_descriptor(self, data):
        self.endpoint.append(EndpointDesc(data))

    def __str__(self):
        fmt = ('  Interface %d: '
            '(Class, SubClass, Protocol): (0x%02x, 0x%02x, 0x%02x)')
        chunks = [fmt % (
            self.bInterfaceNumber,
            self.bInterfaceClass,
            self.bInterfaceSubClass,
            self.bInterfaceProtocol)]
        for e in self.endpoint:
            chunks.append(str(e))
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
        fmt = ('    Endpoint 0x%02x: wMaxPacketSize: %d, bInterval: %d ms')
        return fmt % (
            self.bEndpointAddress,
            self.wMaxPacketSize,
            self.bInterval)


class Descriptor:
    def __init__(self, device):
        # Read and parse USB device descriptor
        # - device: usb.core.Device
        #
        # NOTE: This does not read the configuration descriptor. You do that
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
        self.idVendor           = (d[ 9] << 8) | d[ 8]
        self.idProduct          = (d[11] << 8) | d[10]
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
                    # Remember interface index for associating endpoint
                    i += 1
                elif tag == 0x0705:
                    # Endpoint
                    if i >= 0:
                        self.interfaces[i].add_endpoint_descriptor(d)
                    else:
                        raise ValueError("Found endpoint before interface")
            except ValueError as e:
                logger.error(e)
                raise e

    def to_bytes(self):
        return self.device_desc_bytes

    def __str__(self):
        fmt = """Descriptor:
  idVendor:idProduct: %04x:%04x
  bcdUSB: 0x%04x
  (bDeviceClass, bDeviceSubClass, bDeviceProtocol): (0x%02x, 0x%02x, 0x%02x)"""
        chunks = [fmt % (
            self.idVendor,
            self.idProduct,
            self.bcdUSB,
            self.bDeviceClass,
            self.bDeviceSubClass,
            self.bDeviceProtocol)]
        for lst in [self.configs, self.interfaces]:
            for item in lst:
                chunks.append(str(item))
        return "\n".join(chunks)
