# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright 2024 Sam Blenny
#
from board import BUTTON1, CKP, CKN, D0P, D0N, D1P, D1N, D2P, D2N
from digitalio import DigitalInOut, Direction, Pull
from displayio import (Bitmap, Group, OnDiskBitmap, Palette, TileGrid,
    release_displays)
from framebufferio import FramebufferDisplay
import gc
from picodvi import Framebuffer
import supervisor
from terminalio import FONT
from time import sleep
from usb.core import USBError, USBTimeoutError
import usb_host

from adafruit_display_text import bitmap_label
import adafruit_imageload
import adafruit_logging as logging

from gamepad import (
    find_usb_device, InputDevice,
    UP, DOWN, LEFT, RIGHT, START, SELECT, L, R, A, B, X, Y,
    TYPE_SWITCH_PRO, TYPE_XINPUT, TYPE_HID_GAMEPAD)


# Configure logging
logger = logging.getLogger('code.py')
logger.setLevel(logging.DEBUG)


def update_GUI(scene, buttons, diff, status):
    # Update TileGrid sprites to reflect changed state of gamepad buttons
    # Scene is 10 sprites wide by 5 sprites tall:
    #  Y
    #  0 . L . . . . . . R .
    #  1 . . dU. . . . X . .
    #  2 . dL. dR. . Y . A .
    #  3 . . dD. SeSt. B . .
    #  4 . . . . . . . . . .
    #    0 1 2 3 4 5 6 7 8 9 X
    #
    x, y = status.anchored_position
    xy_changed = False
    if diff & A:
        scene[8, 2] = 15 if (buttons & A) else 17
    if diff & B:
        scene[7, 3] = 15 if (buttons & B) else 17
    if diff & X:
        scene[7, 1] = 15 if (buttons & X) else 17
    if diff & Y:
        scene[6, 2] = 15 if (buttons & Y) else 17
    if diff & L:
        scene[1, 0] = 1 if (buttons & L) else 5
    if diff & R:
        scene[8, 0] = 1 if (buttons & R) else 5
    if diff & UP:
        if buttons & UP:
            scene[2, 1] = 8
            if buttons & B:
                # B + UP: move status label up
                y = max(0, y-2)
                xy_changed = True
        else:
            scene[2, 1] = 12
    if diff & DOWN:
        if buttons & DOWN:
            scene[2, 3] = 22
            if buttons & B:
                # B + DOWN: move status label down
                y = min(120, y+2)
                xy_changed = True
        else:
            scene[2, 3] = 26
    if diff & LEFT:
        if buttons & LEFT:
            scene[1, 2] = 14
            if buttons & B:
                # B + LEFT: move status label left
                x = max(0, x-2)
                xy_changed = True
        else:
            scene[1, 2] = 18
    if diff & RIGHT:
        if buttons & RIGHT:
            scene[3, 2] = 16
            if buttons & B:
                # B + RIGHT: move status label right
                x = min(160, x+2)
                xy_changed = True
        else:
            scene[3, 2] = 20
    if diff & SELECT:
        scene[4, 3] = 10 if (buttons & SELECT) else 24
    if diff & START:
        scene[5, 3] = 11 if (buttons & START) else 25
    if xy_changed:
        print(' x: %3d, y: %3d' % (x, y), end='')
    status.anchored_position = x, y

def print_bits(buttons):
    # Print binary representation of the buttton state bitfield
    # CAUTION: This uses CR ('\r') to overwrite the same line so the bits
    # change in place. It looks better that way, but you need to be sure to
    # end the line with a LF ('\n') before printing other things.
    print(f"\rbutton bits: {buttons:016b}", end='')

def main():

    # Make sure display is configured for 320x240 8-bit
    display = supervisor.runtime.display
    if (display is None) or display.width != 320:
        logger.info("Re-initializing display for 320x240")
        release_displays()
        gc.collect()
        fb = Framebuffer(320, 240, clk_dp=CKP, clk_dn=CKN,
            red_dp=D0P, red_dn=D0N, green_dp=D1P, green_dn=D1N,
            blue_dp=D2P, blue_dn=D2N, color_depth=8)
        display = FramebufferDisplay(fb)
        supervisor.runtime.display = display
    else:
        logger.info("Using existing display")
    display.auto_refresh = False

    # load spritesheet and palette
    (bitmap, palette) = adafruit_imageload.load("sprites.bmp", bitmap=Bitmap,
        palette=Palette)
    # assemble TileGrid with gamepad using sprites from the spritesheet
    scene = TileGrid(bitmap, pixel_shader=palette, width=10, height=5,
        tile_width=8, tile_height=8, default_tile=9, x=8, y=8)
    tilemap = (
        (0, 5, 2, 3, 3, 3, 3, 4, 5, 6),            # . L . . . . . . R .
        (7, 9, 12, 9, 9, 9, 9, 17, 9, 13),         # . . dU. . . . X . .
        (7, 18, 19, 20, 9, 9, 17, 9, 17, 13),      # . dL. dR. . Y . A .
        (7, 9, 26, 9, 24, 25, 9, 17, 9, 13),       # . . dD. SeSt. B . .
        (21, 23, 23, 23, 23, 23, 23, 23, 23, 27),  # . . . . . . . . . .
    )
    for (y, row) in enumerate(tilemap):
        for (x, sprite) in enumerate(row):
            scene[x, y] = sprite
    grp = Group(scale=2)  # 2x zoom
    grp.append(scene)
    display.root_group = grp

    # Make a text label for status messages
    status = bitmap_label.Label(FONT, text="", color=0xFFFFFF, scale=1)
    status.line_spacing = 1.0
    status.anchor_point = (0, 0)
    status.anchored_position = (8, 54)
    grp.append(status)

    # Configure button #1 as input to trigger USB bus re-connect
    button_1 = DigitalInOut(BUTTON1)
    button_1.direction = Direction.INPUT
    button_1.pull = Pull.UP

    # Define status updater with access to local vars from main()
    def set_status(msg):
        logger.info(msg.replace('\n', ' '))
        status.text = msg

    # MAIN EVENT LOOP
    # Establish and maintain a gamepad connection
    set_status("Scanning USB bus...")
    display.refresh()
    device_cache = {}
    while True:
        gc.collect()
        sleep(0.1)
        need_LF = False
        try:
            # The point of device_cache is to avoid repeatedly checking the
            # same non-gamepad device once it's been identified as something
            # other than a gamepad.
            scan_result = find_usb_device(device_cache)
            if scan_result is None:
                # No connection yet, so sleep briefly then try the find again
                sleep(0.4)
                continue
            # Found an input device, so try to configure it and start polling
            logger.info("Found device. Connecting...")
            # CAUTION! Allowing a display refresh between the calls to
            # usb.core.find() and usb.core.Device.set_configuration() may
            # cause unpredictable behavior.
            dev = InputDevice(scan_result)
            sr = scan_result
            status_str = (
                "%04X:%04X %s\n"            # vid:pid tag
                "dev  %02X:%02X:%02X\n"     # device class:subclass:protocol
                "int0 %02X:%02X:%02X\n"     # interface 0 class:subclass:proto.
                "(button 1: rescan bus)"
                ) % (
                (sr.vid, sr.pid, sr.tag) + sr.dev_info + sr.int0_info)
            display.refresh()

            # Poll for input events until Button #1 is pressed or until there
            # is a USB error.
            need_LF = False
            prev = 0 & 0xffff      # previous input event state
            for data in dev.input_event_generator():
                if not button_1.value:
                    # End polling if Fruit Jam board's Button #1 was pressed
                    break
                if data is None:
                    # This means request was throttled or USB read timed out.
                    # both are normal and fine. Just try again.
                    continue
                if isinstance(data, memoryview) or isinstance(data, bytes):
                    # Handle bytes from HID report
                    if data is not None:
                        # Only update GUI when something actually changed
                        hexdump = ' '.join(['%02x' % b for b in data])
                        set_status('%s\n%s' % (status_str, hexdump))
                        need_LF = True
                        display.refresh()
                else:
                    # Handle uint16 button bitfield
                    diff = prev ^ data   # Use bitwise XOR to find changes
                    prev = data
                    if diff or (not need_LF):
                        # Only update GUI when something actually changed
                        update_GUI(scene, data, diff, status)
                        print_bits(data)  # NOTE: uses print(..., end='')
                        need_LF = True
                        display.refresh()
            # Loop stops if somebody pressed button #1 asking for a re-scan
            if need_LF:
                # Clean up after print_bits()
                print()
            logger.info("=== BUTTON 1 PRESSED ===")
            set_status("Scanning USB bus...")
            display.refresh()
            device_cache = {}
        except USBError as e:
            # This happens sometimes, but not always, when USB device is
            # unplugged. Can also be caused by other low-level USB stuff. Log
            # the error and stay in the loop to re-scan the USB bus.
            if need_LF:
                print()  # clean up after print_bits()
            logger.error("USBError: '%s', %s, '%s'" % (e, type(e), e.errno))
            set_status("Scanning USB bus...")
            display.refresh()
            device_cache = {}


main()
