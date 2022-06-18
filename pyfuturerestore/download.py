import requests
from remotezip import RemoteZip
from pyfuturerestore.ipsw import IPSW

def pzDownloadFile(url, path, dest):
	try:
		with RemoteZip(url) as zurl:
			zurl.extract(path, dest)
	except:
		return -1
	return 0

def getLatestFirmwareURL(product_type):
	try:
		r = requests.get(f'http://api.ipsw.me/v2.1/{product_type}/latest/url')
		return r.content
	except:
		return -1
	return 0
