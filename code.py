# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright 2024 Sam Blenny
#
from board import BUTTON1, CKP, CKN, D0P, D0N, D1P, D1N, D2P, D2N
from digitalio import DigitalInOut
from displayio import (Bitmap, Group, OnDiskBitmap, Palette, TileGrid,
    release_displays)
from framebufferio import FramebufferDisplay
import gc
from picodvi import Framebuffer
import supervisor
from time import sleep
from usb.core import USBError, USBTimeoutError
import usb_host

import adafruit_imageload
import adafruit_logging as logging

from gamepad import (
    find_gamepad_device, Gamepad,
    UP, DOWN, LEFT, RIGHT, START, SELECT, L, R, A, B, X, Y)


# Configure logging
logger = logging.getLogger('code.py')
logger.setLevel(logging.DEBUG)

BUTTON_DEBUG = const(True)


def update_GUI(scene, prev, buttons):
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
    diff = prev ^  buttons
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
        scene[2, 1] = 8 if (buttons & UP) else 12
    if diff & DOWN:
        scene[2, 3] = 22 if (buttons & DOWN) else 26
    if diff & LEFT:
        scene[1, 2] = 14 if (buttons & LEFT) else 18
    if diff & RIGHT:
        scene[3, 2] = 16 if (buttons & RIGHT) else 20
    if diff & SELECT:
        scene[4, 3] = 10 if (buttons & SELECT) else 24
    if diff & START:
        scene[5, 3] = 11 if (buttons & START) else 25
    if BUTTON_DEBUG:
        print_bits(buttons)

def print_bits(buttons):
    # Print binary representation of the buttton state bitfield
    # CAUTION: This uses CR ('\r') to overwrite the same line so the bits
    # change in place. It looks better that way, but you need to be sure to
    # end the line with a LF ('\n') before printing other things.
    print(f"\rbutton bits: {buttons:016b}", end='')

def main():
    sleep(0.5)

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
        tile_width=8, tile_height=8, default_tile=9, x=13, y=5)
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
    grp = Group(scale=3)  # 3x zoom
    grp.append(scene)
    display.root_group = grp
    display.refresh()

    # Configure button #1 as input to trigger USB bus re-connect
    button_1 = DigitalInOut(BUTTON1)

    # MAIN EVENT LOOP
    # Establish and maintain a gamepad connection
    logger.info("Looking for USB gamepad...")
    while True:
        gc.collect()
        need_LF = False
        try:
            (device, gamepad_type) = find_gamepad_device()
            if device and gamepad_type:
                # Found a gamepad, so configure it and start polling
                logger.info("Found device. Connecting...")
                logger.info("  (to rescan USB bus, press Button #1)")
                player = 1
                gp = Gamepad(device, gamepad_type, player)
                logger.debug("Connected")
                connected = True
                prev = 0
                print_bits(prev)
                while connected and button_1.value:
                    try:
                        (connected, changed, buttons) = gp.poll()
                        if connected and changed:
                            update_GUI(scene, prev, buttons)
                            display.refresh()
                            prev = buttons
                    except USBTimeoutError:
                        # Intentionally ignore timeouts because currently there
                        # is no good way to distinguish between a normal timeout
                        # and the device being unplugged. So, rely on button #1
                        # to manually re-scan the USB bus.
                        pass
                # If loop stopped, gamepad connection was lost or somebody
                # pressed button #1 to request a USB bus re-scan. We need to
                # flush the line with a LF to clean up after print_bits()
                print()
                logger.info("Gamepad disconnected. Looking for gamepad...")
            else:
                # No connection yet, so sleep briefly then try again
                sleep(0.3)
        except USBError as e:
            # This might mean gamepad was unplugged, or maybe some other
            # low-level USB thing happened which this driver does not yet
            # know how to deal with. So, log the error and keep going
            print()  # clean up after print_bits()
            logger.error("USBError: '%s', %s, '%s'" % (e, type(e), e.errno))
            logger.info("Gamepad connection error. Looking for gamepad...")


main()
