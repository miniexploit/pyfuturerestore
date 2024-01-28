import binascii
import pyimg4
from pymobiledevice3.restore import tss, asr, fdr
from pyfuturerestore.restore import Restore
from pyipatcher.ipatcher import IPatcher
import logging
from pathlib import Path
import requests
import typing
from zipfile import ZipFile
from remotezip import RemoteZip
import sys
import plistlib
from time import sleep

from usb.core import find
from usb.backend.libusb1 import get_backend

from typing import Mapping, Optional
from m1n1Exception import retassure, reterror
from pymobiledevice3.irecv import IRecv, Mode
from pymobiledevice3.restore.device import Device
from pymobiledevice3.exceptions import IncorrectModeError
from pymobiledevice3.usbmux import list_devices
from pymobiledevice3.lockdown import LockdownClient, create_using_usbmux
from ipsw_parser.ipsw import IPSW
from pymobiledevice3.restore.recovery import Behavior

import os


Mode.NORMAL_MODE_1 = 0x12a8
Mode.NORMAL_MODE_2 = 0x12ab

# ---------------------------------

PYFUTURERESTORE_TEMP_PATH = '/tmp/pyfuturerestore/'
def strmode(mode: Mode):
    if mode in (Mode.RECOVERY_MODE_1, Mode.RECOVERY_MODE_2, Mode.RECOVERY_MODE_3, Mode.RECOVERY_MODE_4):
        return 'Recovery'
    elif mode == Mode.DFU_MODE:
        return 'DFU'
    elif mode in  (Mode.NORMAL_MODE_1, Mode.NORMAL_MODE_2):
        return 'Normal'
    elif mode == Mode.WTF_MODE:
        return 'WTF'
    else:
        return None

# thx m1sta
def _get_backend():  # Attempt to find a libusb 1.0 library to use as pyusb's backend, exit if one isn't found.
    directories = (
        '/usr/local/lib',
        '/opt/procursus/lib',
        '/usr/lib',
        '/opt/homebrew/lib' # this works on my M2 Mac, tell me to add more if libusb is in a different path on your computer
    )  # Common library directories to search

    libusb1 = None
    for libdir in directories:
        for file in Path(libdir).glob('libusb-1.0.0.*'):
            if not file.is_file() or (file.suffix not in ('.so', '.dylib')):
                continue

            libusb1 = file
            break

        else:
            continue

        break

    if libusb1 is None:
        return -1

    return str(libusb1)

class PyFuturerestore:
    def __init__(self, ipsw: ZipFile, logger, setnonce=False, serial=False, custom_gen=None, ignore_nonce_matching=False, noibss=False, skip_blob=False, pwndfu=False, no_cache=False, custom_usb_backend=None, verbose=False):
        if not os.path.isdir(PYFUTURERESTORE_TEMP_PATH):
            os.makedirs(PYFUTURERESTORE_TEMP_PATH)
        self.no_cache = no_cache
        self.serial = serial
        self._bootargs = None
        self.ramdiskdata = None
        self.rkrndata = None
        self.usb_backend = custom_usb_backend
        self.zipipsw = ipsw
        self.skip_blob = skip_blob
        self.setnonce = setnonce
        self.ignore_nonce_matching = ignore_nonce_matching
        self.pwndfu = pwndfu
        self.custom_gen = custom_gen
        self.tss = None
        self.ipsw: IPSW = IPSW(ipsw)
        self.latest_bm = None
        self.latest_url = None
        self.verbose = verbose
        self.logger = logger
        asr.logger = logger
        fdr.logger = logger
        tss.logger = logger
        self.noibss = noibss

    def reconnect_irecv(self, is_recovery=None):
        self.logger.debug('waiting for device to reconnect...')
        self.irecv = IRecv(ecid=self.device.ecid, is_recovery=is_recovery)
        self.logger.debug(f'connected mode: {self.irecv.mode}')

    def get_mode(self):
        try:
            for device in find(find_all=True):
                try:
                    if device.idVendor is None:
                        continue
                    if device.idVendor == 0x05ac:
                        mode = Mode.get_mode_from_value(device.idProduct)
                        if device.idProduct == 0x12a8:  return Mode.NORMAL_MODE_1
                        elif device.idProduct == 0x12ab:    return Mode.NORMAL_MODE_2
                        if mode is None:    continue
                        return mode
                except ValueError:
                    pass
        except Exception as e:
            if 'No backend available' in str(e):
                if self.usb_backend:
                    backend = self.usb_backend
                else:
                    retassure((backend := _get_backend()) != -1, 'Could not find backend for libusb')
                self.logger.debug(f'USB backend: {backend}')
                for device in find(find_all=True, backend=get_backend(find_library=lambda _: backend)):
                    try:
                        if device.idVendor is None:
                            continue
                        if device.idVendor == 0x05ac:
                            mode = Mode.get_mode_from_value(device.idProduct)
                            if device.idProduct == 0x12a8:  return Mode.NORMAL_MODE_1
                            elif device.idProduct == 0x12ab:    return Mode.NORMAL_MODE_2
                            if mode is None:    continue
                            return mode
                    except ValueError:
                        pass
            else:
                reterror(f'Could not get mode: {e}')

    def init(self):
        self.lockdown_cli: LockdownClient = None
        self.irecv: IRecv = None
        self.init_mode = self.get_mode()
        retassure(self.init_mode, 'Can\'t init, no device found')
        self.logger.info(f'Found device in {strmode(self.init_mode)} mode')
        if self.init_mode in (Mode.NORMAL_MODE_1, Mode.NORMAL_MODE_2):
            for device in list_devices():
                try:
                    lockdown = create_using_usbmux(serial=device.serial)
                except IncorrectModeError:
                    continue
                if True: # no idea
                    self.lockdown_cli = lockdown
                    break
        else:
            self.irecv = IRecv()
        self.device = Device(irecv=self.irecv, lockdown=self.lockdown_cli)

    def download_buffer(self, url, pz_path):
        data: bytes = b''
        try:
            with RemoteZip(url) as z:
                return z.read(pz_path)
        except:
            return -1

    def get_latest_fwurl(self):
        try:
            if self.device.irecv:
                r = requests.get(f'http://api.ipsw.me/v2.1/{self.device.irecv.product_type}/latest/url')
                return r.content
            else:
                r = requests.get(f'http://api.ipsw.me/v2.1/{self.device.lockdown.product_type}/latest/url')
                return r.content
        except:
            return -1

    def load_ap_ticket(self, path):
        retassure(os.path.isfile(path), f'APTicket not found at {path}')
        with open(path, 'rb') as f:
            self.tss = plistlib.load(f)
        self.im4m = pyimg4.IM4M(self.tss['ApImg4Ticket'])
        self.logger.info(f'Done reading signing ticket {path}')

    def set_bootargs(self, bootargs):
        self._bootargs = bootargs

    def load_ramdisk(self, path):
        retassure(os.path.isfile(path), f'RestoreRamdisk not found at {path}')
        self.logger.warning('Custom RestoreRamdisk won\'t be verified')
        with open(path, 'rb') as f:
            self.ramdiskdata = f.read()

    def load_rkrn(self, path):
        retassure(os.path.isfile(path), f'RestoreKernelCache not found at {path}')
        self.logger.warning('Custom RestoreKernelCache won\'t be verified')
        with open(path, 'rb') as f:
            self.rkrndata = f.read()

    def enter_recovery(self):
        self.logger.info('Entering Recovery Mode')
        if self.init_mode in (Mode.RECOVERY_MODE_1, Mode.RECOVERY_MODE_2, Mode.RECOVERY_MODE_3, Mode.RECOVERY_MODE_4):
            self.logger.info('Device is already in Recovery Mode')
            return
        elif self.init_mode in (Mode.NORMAL_MODE_1, Mode.NORMAL_MODE_2):
            retassure(self.lockdown_cli, 'Lockdown client has not been created, cannot enter Recovery Mode from Normal Mode')
            self.lockdown_cli.enter_recovery()
        elif self.init_mode == Mode.DFU_MODE:
            retassure(self.pwndfu, '--use-pwndfu was not specified but device is found in DFU Mode')
            self.logger.info('--use-pwndfu specified, entering pwnRecovery later')
            return
        else:
            reterror('Device is in unsupported mode')
        self.logger.info('Waiting for device to enter Recovery Mode')
        self.reconnect_irecv(is_recovery=True)
        self.init()

    def exit_recovery(self):
        retassure(self.irecv or self.initMode in (
        Mode.RECOVERY_MODE_1, Mode.RECOVERY_MODE_2, Mode.RECOVERY_MODE_3, Mode.RECOVERY_MODE_4),
                  "--exit-recovery was specified, but device is not in Recovery mode")
        self.irecv.set_autoboot(True)
        self.irecv.reboot()

    def get_ap_nonce_from_im4m(self):
        if isinstance(self.im4m, pyimg4.IM4M):
            return self.im4m.apnonce.hex()

    def get_generator_from_shsh2(self):
        return self.tss['generator']

    def get_hex_ap_nonce(self):
        ap_nonce = binascii.hexlify(self.irecv.ap_nonce)
        return ap_nonce.decode()

    def enter_pwnrecovery(self, build_identity, bootargs=None):
        cache1 = False
        cache2 = False
        try:
            retassure(self.irecv, 'No IRecv client')
        except:
            reterror('No IRecv client')
        ibss_name = PYFUTURERESTORE_TEMP_PATH + 'ibss.' + self.irecv.product_type + '.' + self.irecv.hardware_model + '.patched.img4'
        ibec_name = PYFUTURERESTORE_TEMP_PATH + 'ibec.' + self.irecv.product_type + '.' + self.irecv.hardware_model + '.patched.img4'
        _ibss = None
        _ibec = None
        if not self.no_cache:
            try:
                with open(ibss_name, 'rb') as f:
                    _ibss = f.read()
                cache1 = True
            except:
                cache1 = False
            try:
                with open(ibec_name, 'rb') as f:
                    _ibec = f.read()
                cache2 = True
            except:
                cache2 = False

        if (not cache1) and (not cache2):
            ipc = IPatcher(self.verbose)
            self.logger.info(f'Getting firmware keys for {self.irecv.hardware_model}')
            retassure((ibss_keys := ipc.get_keys(self.irecv.product_type, self.ipsw.build_manifest.product_build_version, 'iBSS')) != -1,  'Could not get iBSS keys')
            retassure((ibec_keys := ipc.get_keys(self.irecv.product_type, self.ipsw.build_manifest.product_build_version, 'iBEC')) != -1, 'Could not get iBEC keys')
            self.logger.info('Patching iBSS')
            _ibss = build_identity.get_component('iBSS').data
            retassure((_ibss := ipc.patch_iboot(_ibss, bootargs, kbag=ibss_keys)) != -1, 'Failed to patch iBSS')
            retassure((_ibss := ipc.pack_into_img4(_ibss, self.im4m, 'ibss')) != -1, 'Failed to repack iBSS')
            with open(ibss_name, 'wb') as f:
                f.write(_ibss)
            self.logger.info('Patching iBEC')
            _ibec = build_identity.get_component('iBEC').data
            retassure((_ibec := ipc.patch_iboot(_ibec, bootargs, kbag=ibec_keys)) != -1, 'Failed to patch iBEC')
            retassure((_ibec := ipc.pack_into_img4(_ibec, self.im4m, 'ibec')) != -1, 'Failed to repack iBEC')
            with open(ibec_name, 'wb') as f:
                f.write(_ibec)
        dfu = False
        if not self.noibss:
            self.logger.info('Sending iBSS (then unplug and replug USB cable from Mac if on Apple Silicon)')
            self.irecv.send_buffer(_ibss)
            self.logger.info('waiting for reconnect')
            self.reconnect_irecv()
        if (0x7000 <= self.irecv.chip_id <= 0x8004) or (0x8900 <= self.irecv.chip_id <= 0x8965):
            retassure(self.device.irecv.mode == Mode.DFU_MODE, 'Unable to connect to device in DFU mode')
            self.irecv.set_configuration(1)
            self.logger.info('Sending iBEC (then unplug and replug USB cable from Mac if on Apple Silicon)')
            self.irecv.send_buffer(_ibec)
            self.logger.info('waiting for reconnect in Recovery mode')
            self.reconnect_irecv(is_recovery=True)
        elif (0x8006 <= self.irecv.chip_id <= 0x8030) or (0x8101 <= self.irecv.chip_id <= 0x8301):
            dfu = True
            self.reconnect_irecv(is_recovery=True)
        else:
            reterror('Device not supported!')
        if self.irecv.is_image4_supported:
            if self.irecv.chip_id < 0x8015:
                self.irecv.send_command('bgcolor 255 0 0')
                sleep(2)
        self.logger.info(f'ApNonce pre-hax:\n {self.get_hex_ap_nonce()}')
        generator = self.custom_gen if self.custom_gen else self.get_generator_from_shsh2()
        if not self.setnonce:
            self.logger.info('ApNonce from device doesn\'t match IM4M nonce, applying hax')
        self.logger.info(f'generator={generator}, writing to nvram')
        self.irecv.send_command(f'setenv com.apple.System.boot-nonce {generator}')
        self.irecv.send_command('saveenv')
        if not self.setnonce:
            sleep(2)
            self.irecv.reset()
            self.irecv.set_configuration(1)
            self.logger.info('Sending iBEC (then unplug and replug USB cable from Mac if on Apple Silicon)')
            self.irecv.send_buffer(_ibec)
            self.logger.info('waiting for reconnect in Recovery mode')
            self.reconnect_irecv(is_recovery=True)
            self.logger.info(f'ApNonce post-hax:\n {self.get_hex_ap_nonce()}')
            self.irecv.send_command('bgcolor 255 255 0')
            retassure(self.get_hex_ap_nonce() == self.get_ap_nonce_from_im4m() or self.ignore_nonce_matching, 'ApNonce from device doesn\'t match IM4M nonce after applying ApNonce hax')
            if self.ignore_nonce_matching:
                self.logger.warning('IGNORING SETTING NONCE FAILURE! RESTORE MAY FAIL!')
        self.irecv.reset()
        if self.setnonce:
            self.logger.info('Done setting nonce!')
            self.logger.info('Use pyfuturerestore --exit-recovery to go back to normal mode if you aren\'t restoring.')
            self.irecv.set_autoboot(False)
            self.irecv.reboot()
            sys.exit(0)
        sleep(2)

    def do_restore(self):
        retassure((latest_url := self.get_latest_fwurl()) != -1, 'Could not get latest firmware URL')
        latest_ipsw = RemoteZip(latest_url)
        restore = Restore(
            self.zipipsw, 
            latest_ipsw, 
            self.device, 
            self.tss, 
            behavior = Behavior.Erase
        )
        self.enter_recovery()
        self.logger.info('Checking if the APTicket is valid for this restore')
        if not self.skip_blob:
            retassure(self.irecv.ecid == self.im4m.ecid, 'Device\'s ECID does not match APTicket\'s ECID')
            self.logger.info('Verified ECID in APTicket matches the device\'s ECID')
        else:
            self.logger.warning('NOT VALIDATING SHSH BLOBS ECID!')
        if self.pwndfu:
            if self._bootargs:
                bootargs = self._bootargs
            else:
                bootargs = ''
                if self.serial:
                    bootargs += 'serial=0x3 '
                bootargs += 'rd=md0 '
                # Currently pyfuturerestore does not support update install
                bootargs += '-v -restore debug=0x2014e keepsyms=0x1 amfi=0xff amfi_allow_any_signature=0x1 amfi_get_out_of_my_way=0x1 cs_enforcement_disable=0x1'
            self.enter_pwnrecovery(restore.build_identity, bootargs=bootargs)
            self.logger.info('waiting for reconnect in Recovery mode')
            self.reconnect_irecv(is_recovery=True)
        else:
            retassure(self.get_hex_ap_nonce() == self.get_ap_nonce_from_im4m(), 'ApNonce from device doesn\'t match IM4M nonce')
        self.logger.info('Verified device\'s APNonce matches IM4M\'s APNonce')
        # reinit restore
        self.reconnect_irecv()
        restore = Restore(
            self.zipipsw, 
            latest_ipsw, 
            self.device, 
            self.tss, 
            rdskdata = self.ramdiskdata,
            rkrndata = self.rkrndata,
            behavior = Behavior.Erase
        )
        
        restore.recovery.device = Device(irecv=self.irecv)
        self.logger.info('Booting ramdisk')
        restore.recovery.boot_ramdisk()
        self.logger.info('About to restore device')
        sleep(5)
        self.logger.info('Starting restore')
        restore.restore_device()

