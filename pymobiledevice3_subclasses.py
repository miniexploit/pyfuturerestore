from pymobiledevice3.restore.restore import Restore
from pyipatcher.logger import get_my_logger
import requests
from ipsw_parser.build_manifest import BuildManifest
from remotezip import RemoteZip
import binascii
import hashlib
import logging
import os
import plistlib
import struct
import tempfile
import traceback
import zipfile
from typing import Mapping, Optional
from m1n1Exception import retassure
from pymobiledevice3.irecv import IRecv

from pymobiledevice3.exceptions import ConnectionFailedError, NoDeviceConnectedError, PyMobileDevice3Exception
from pymobiledevice3.restore.asr import ASRClient
from pymobiledevice3.restore.base_restore import RESTORE_VARIANT_ERASE_INSTALL, RESTORE_VARIANT_MACOS_RECOVERY_OS, \
    RESTORE_VARIANT_UPGRADE_INSTALL, BaseRestore
from pymobiledevice3.restore.consts import PROGRESS_BAR_OPERATIONS, lpol_file
from pymobiledevice3.restore.device import Device
from pymobiledevice3.restore.fdr import FDRClient, fdr_type, start_fdr_thread
from pymobiledevice3.restore.ftab import Ftab
from pymobiledevice3.restore.recovery import Behavior, Recovery
from pymobiledevice3.restore.restore_options import RestoreOptions
from pymobiledevice3.restore.restored_client import RestoredClient
from pymobiledevice3.restore.tss import TSSRequest, TSSResponse
from pymobiledevice3.service_connection import ServiceConnection
from pymobiledevice3.utils import plist_access_path

class PyFuturerestore:
    def __init__(self, ipsw, client: IRecv, verbose):
        self.logger = get_my_logger(verbose, name='pyfuturerestore')
        self.client = client
        self.sepfw = None
        self.sepbm = None
        self.bbfw = None
        self.bbbm = None
        self.has_get_latest_fwurl = False
        self.latest_bm = None

    def download_buffer(self, url, pz_path):
        try:
            with RemoteZip(url) as z:
                return z.read(pz_path)
        except:
            return -1

    def get_latest_fwurl(self):
        try:
            r = requests.get(f'http://api.ipsw.me/v2.1/{self.device.irecv.product_type}/latest/url')
            self.has_get_latest_fwurl = True
            return r.content
        except:
            return -1

    def load_latest_sep(self):
        if not self.has_get_latest_fwurl:
            self.logger.info(f'Getting latest firmware URL for {self.device.irecv.product_type}')
            retassure((latest_url := self.get_latest_fwurl()) != -1, 'Could not get latest firmware URL')
            retassure((self.latest_bm := self.download_buffer(latest_url, 'BuildManifest.plist')) != -1, 'Could not download latest BuildManifest.plist')
        bm = BuildManifest(None, self.latest_bm)
        sep_path = bm.get

    def load_sep(self, data, bm):
        self.sepfw = data
        self.sepbm = bm

    def load_baseband(self, data, bm):
        self.bbfw = data
        self.bbbm = bm


class restore_subclass(Restore):
    def __init__(self, ipsw: zipfile.ZipFile, device: Device, tss=None, behavior: Behavior = Behavior.Erase,
                 ignore_fdr=False, verbose=False):
        super().__init__(ipsw, device, tss, behavior, logger=get_my_logger(verbose, name='restore_subclass'))


    def pyfr_send_nor(self, message: Mapping):
        self.logger.info('About to send NORData...')
        flash_version_1 = False
        llb_path = self.build_identity.get_component('LLB', tss=self.recovery.tss).path
        llb_filename_offset = llb_path.find('LLB')

        arguments = message.get('Arguments')
        if arguments:
            flash_version_1 = arguments.get('FlashVersion1', False)

        if llb_filename_offset == -1:
            raise PyMobileDevice3Exception('Unable to extract firmware path from LLB filename')

        firmware_path = llb_path[:llb_filename_offset - 1]
        self.logger.info(f'Found firmware path: {firmware_path}')

        firmware_files = dict()
        try:
            firmware = self.ipsw.get_firmware(firmware_path)
            firmware_files = firmware.get_files()
        except KeyError:
            self.logger.info('Getting firmware manifest from build identity')
            build_id_manifest = self.build_identity['Manifest']
            for component, manifest_entry in build_id_manifest.items():
                if isinstance(manifest_entry, dict):
                    is_fw = plist_access_path(manifest_entry, ('Info', 'IsFirmwarePayload'), bool)
                    loaded_by_iboot = plist_access_path(manifest_entry, ('Info', 'IsLoadedByiBoot'), bool)
                    is_secondary_fw = plist_access_path(manifest_entry, ('Info', 'IsSecondaryFirmwarePayload'), bool)

                    if is_fw or (is_secondary_fw and loaded_by_iboot):
                        comp_path = plist_access_path(manifest_entry, ('Info', 'Path'))
                        if comp_path:
                            firmware_files[component] = comp_path

        if not firmware_files:
            raise PyMobileDevice3Exception('Unable to get list of firmware files.')

        component = 'LLB'
        llb_data = self.build_identity.get_component(component, tss=self.recovery.tss,
                                                     path=llb_path).personalized_data
        req = {'LlbImageData': llb_data}

        if flash_version_1:
            norimage = {}
        else:
            norimage = []

        for component, comppath in firmware_files.items():
            if component in ('LLB', 'RestoreSEP'):
                # skip LLB, it's already passed in LlbImageData
                # skip RestoreSEP, it's passed in RestoreSEPImageData
                continue

            nor_data = self.build_identity.get_component(component, tss=self.recovery.tss,
                                                         path=comppath).personalized_data

            if flash_version_1:
                norimage[component] = nor_data
            else:
                # make sure iBoot is the first entry in the array
                if component.startswith('iBoot'):
                    norimage = [nor_data] + norimage
                else:
                    norimage.append(nor_data)

        req['NorImageData'] = norimage

        for component in ('RestoreSEP', 'SEP'):
            # not sure if this needs modification
            comp = self.build_identity.get_component(component, tss=self.recovery.tss)
            if comp.path:
                req[f'{component}ImageData'] = comp.personalized_data

        self.logger.info('Sending NORData now...')
        self._restored.send(req)