from m1n1Exception import *
from zipfile import ZipFile
from remotezip import RemoteZip
import plistlib

class IPSW:
	def __init__(self, hardware_model, ipsw=None):
		if ipsw:
			self.ipsw = ipsw
			self.bm = plistlib.loads(self.readFile('BuildManifest.plist'))
		self.hardwareModel = hardware_model.lower()

	def _BytesIO(self):
		self.bytesIOFile = open(self.ipsw, "rb")
		return self.bytesIOFile

	def close(self):
		self.bytesIOFile.close()

	def readFile(self, filename):
		with ZipFile(self.ipsw) as z:
			try:
				return z.read(filename)
			except:
				reterror(f'Could not extract {filename}')

	def getIPSWComponent(self, component_name, custom_path=None):
		if custom_path:
			with open(custom_path, 'rb') as f:
				custom_buildmanifest = plistlib.load(f)
			for build_identity in custom_buildmanifest['BuildIdentities']:
				if build_identity['Info']['DeviceClass'] == self.hardwareModel:
					try:
						return build_identity['Manifest'][component_name]['Info']['Path']
					except:
						reterror(f'Could not find path for component {component_name}')
		else:
			for build_identity in self.bm['BuildIdentities']:
				if build_identity['Info']['DeviceClass'] == self.hardwareModel:
					try:
						return build_identity['Manifest'][component_name]['Info']['Path']
					except:
						reterror(f'Could not find path for component {component_name}')

	def readIPSWComponent(self, component_name):
		compPath = self.getIPSWComponent(component_name)
		return self.readFile(compPath)



