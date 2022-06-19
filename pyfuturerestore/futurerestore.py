from m1n1Exception import *
import os
import time
import plistlib
import logging
from pyfuturerestore.ipsw import IPSW
from pyfuturerestore import download
from pymobiledevice3.irecv import IRecv, Mode
from pymobiledevice3.lockdown import LockdownClient
from pymobiledevice3.restore.device import Device
from pymobiledevice3.usbmux import list_devices
from pymobiledevice3.restore.recovery import Behavior
from pymobiledevice3.restore import restore, tss

def strmode(mode: Mode):
	match mode:
		case Mode.RECOVERY_MODE_1:
			return "Recovery"
		case Mode.RECOVERY_MODE_2:
			return "Recovery"
		case Mode.RECOVERY_MODE_3:
			return "Recovery"
		case Mode.RECOVERY_MODE_4:
			return "Recovery"
		case Mode.DFU_MODE:
			return "DFU"
		case Mode.NORMAL_MODE:
			return "Normal"
		case Mode.WTF_MODE:
			return "WTF"	

class PyFuturerestore:
	def __init__(self):
		if not os.path.isdir("/tmp/pyfuturerestore"):
			os.makedirs("/tmp/pyfuturerestore")
		self.tss = None
		self.sepfwdata = None
		self.sepbuildmanifest = None
		self.bbfwdata = None
		self.basebandbuildmanifest = None
		self.deviceProductType = None
		self.deviceHardwareModel = None

	def init(self, is_recovery=False):
		self.lockdownCli = None
		self.irecv = None
		self.initMode = IRecv(get_mode=True).mode
		if is_recovery:
			while self.initMode not in (Mode.RECOVERY_MODE_1, Mode.RECOVERY_MODE_2, Mode.RECOVERY_MODE_3, Mode.RECOVERY_MODE_4):
				self.initMode = IRecv(get_mode=True).mode
		print(f"Found device in {strmode(self.initMode)} mode")
		if(self.initMode == Mode.NORMAL_MODE):
			usbmux_devices = list_devices()
			try:
				self.lockdownCli = LockdownClient(udid=usbmux_devices[0].serial)
			except:
				reterror("could not create lockdown client, no device was detected by usbmux")
		else:
			self.irecv = IRecv()
		self.setDeviceInfo()
		self.device = Device(irecv=self.irecv, lockdown=self.lockdownCli)

	def setDeviceInfo(self):
		if self.initMode == Mode.NORMAL_MODE:
			device_info = self.lockdownCli.device_info
			self.deviceProductType = device_info["ProductType"]
			self.deviceHardwareModel = device_info["HardwareModel"]
		else:
			self.deviceProductType = self.irecv.product_type
			self.deviceHardwareModel = self.irecv.hardware_model

	def loadAPTicket(self, APTicketPath):
		retassure(os.path.isfile(APTicketPath), f"APTicket not found at path: {APTicketPath}")
		try:
			with open(APTicketPath, "rb") as f:
				self.tss = plistlib.load(f)
		except:
			reterror("failed to load APTicket")		
		self.im4m = pyimg4.IM4M(self.tss["ApImg4Ticket"])
		print(f"done reading signing ticket {APTicketPath}")

	def loadSepAtPath(self, sepPath):
		retassure(os.path.isfile(sepPath), f"SEP firmware not found at path: {sepPath}")
		try:
			with open(sepPath, "rb") as f:
				self.sepfwdata = f.read()
		except:
			reterror("failed to read SEP")

	def loadSepManifest(self, sepManifestPath):	
		retassure(os.path.isfile(sepManifestPath), f"SEP BuildManifest not found at path: {sepManifestPath}")
		try:
			with open(sepManifestPath, "rb") as f:
				self.sepbuildmanifest = f.read()
		except:
			reterror("failed to read SEP BuildManifest")

	def loadLatestSep(self):
		print(f"Getting latest firmware URL for {self.deviceProductType}")
		latestURL = download.getLatestFirmwareURL(self.deviceProductType)
		retassure(download.pzDownloadFile(latestURL, "BuildManifest.plist", "/tmp/pyfuturerestore") == 0, "Could not download BuildManifest.plist")
		tempipsw = IPSW(hardware_model=self.deviceHardwareModel)
		sepRemotePath = tempipsw.getIPSWComponent("SEP", custom_path="/tmp/pyfuturerestore/BuildManifest.plist")
		print("Downloading SEP")
		retassure(download.pzDownloadFile(latestURL, sepRemotePath, "/tmp/pyfuturerestore") == 0, "Could not download latest SEP")
		self.loadSepAtPath(f"/tmp/pyfuturerestore/{sepRemotePath}")
		self.loadSepManifest("/tmp/pyfuturerestore/BuildManifest.plist")
		print("done loading latest SEP")

	def loadBasebandAtPath(self, basebandPath):
		retassure(os.path.isfile(basebandPath), f"Baseband firmware not found at path: {basebandPath}")
		try:
			with open(basebandPath, "rb") as f:
				self.bbfwdata = f.read()
		except:
			reterror("failed to read Baseband")

	def loadBasebandManifest(self, basebandManifestPath):	
		retassure(os.path.isfile(basebandManifestPath), f"Baseband BuildManifest not found at path: {basebandManifestPath}")
		try:
			with open(basebandManifestPath, "rb") as f:
				self.basebandbuildmanifest = f.read()
		except:
			reterror("failed to read SEP BuildManifest")

	def loadLatestBaseband(self):
		print(f"Getting latest firmware URL for {self.deviceProductType}")
		latestURL = download.getLatestFirmwareURL(self.deviceProductType)
		tempipsw = IPSW(hardware_model=self.deviceHardwareModel)
		retassure(download.pzDownloadFile(latestURL, "BuildManifest.plist", "/tmp/pyfuturerestore") == 0, "Could not download BuildManifest.plist")
		basebandRemotePath = tempipsw.getIPSWComponent("BasebandFirmware", custom_path="/tmp/pyfuturerestore/BuildManifest.plist")
		print("Downloading Baseband")
		retassure(download.pzDownloadFile(latestURL, basebandRemotePath, "/tmp/pyfuturerestore") == 0, "Could not download latest Baseband")
		self.loadBasebandAtPath(f"/tmp/pyfuturerestore/{basebandRemotePath}")
		self.loadBasebandManifest("/tmp/pyfuturerestore/BuildManifest.plist")
		print("done loading latest Baseband")

	def enterRecovery(self, ipsw: IPSW):
		print("Entering Recovery mode")
		if self.initMode in (Mode.RECOVERY_MODE_1, Mode.RECOVERY_MODE_2, Mode.RECOVERY_MODE_3, Mode.RECOVERY_MODE_4):
			print("Device is already in Recovery mode, no need to enter it again")
			return
		elif self.initMode == Mode.DFU_MODE:
			reterror("Device is in unsupported mode. Please connect the device in Normal or Recovery mode")
		elif self.initMode == Mode.NORMAL_MODE:
			retassure(self.lockdownCli, "lockdown client has not been created, cannot enter Recovery Mode from Normal Mode")
			self.lockdownCli.enter_recovery()
		print("waiting for device to enter Recovery mode")
		self.init(is_recovery=True)
		print("Reinit done")
		print("done entering Recovery mode")

	def exitRecovery(self):
		retassure(self.irecv or self.initMode in (Mode.RECOVERY_MODE_1, Mode.RECOVERY_MODE_2, Mode.RECOVERY_MODE_3, Mode.RECOVERY_MODE_4), "--exit-recovery was specified, but device is not in Recovery mode")
		self.irecv.set_autoboot(True)
		self.irecv.reboot()

	def doRestore(self, path):
		ipsw = IPSW(self.deviceHardwareModel, ipsw=path)
		retassure(self.sepfwdata, "SEP was not loaded")
		retassure(self.sepbuildmanifest, "SEP was not loaded")
		retassure(self.bbfwdata, "Baseband was not loaded")
		retassure(self.basebandbuildmanifest, "Baseband was not loaded")
		self.enterRecovery(ipsw)
		print("About to restore device")
		time.sleep(5)
		#try:
		restore.Restore(ipsw._BytesIO(), self.device, tss=self.tss, sepfwdata=self.sepfwdata, bbfwdata=self.bbfwdata, sepbuildmanifest=self.sepbuildmanifest, basebandbuildmanifest=self.basebandbuildmanifest, behavior=Behavior.Erase).update()
		#except:
		#reterror(f"pymobiledevice3 failed with reason {None}")



