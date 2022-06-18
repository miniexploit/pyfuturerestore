from m1n1Exception import *
from pyfuturerestore import futurerestore
import argparse

def main():
	parser = argparse.ArgumentParser(description="pyfuturerestore - A re-implementation of futurerestore in Python", usage="pyfuturerestore [OPTIONS] IPSW")
	parser.add_argument("-t","--apticket",metavar="PATH",nargs=1,help="Signing tickets used for restoring")
	parser.add_argument("--exit-recovery",help="Exit from Recovery mode",action='store_true')
	parser.add_argument("--latest-sep",help="Use latest signed SEP instead of manually specifying one",action='store_true')
	parser.add_argument("-s","--sep",metavar="PATH",nargs=1,help="SEP to be flashed")
	parser.add_argument("-m","--sep-manifest",metavar="PATH",nargs=1,help="BuildManifest for requesting SEP ticket")
	parser.add_argument("--latest-baseband",help="Use latest signed SEP instead of manually specifying one",action='store_true')
	parser.add_argument("-b","--baseband",metavar="PATH",nargs=1,help="Baseband to be flashed")
	parser.add_argument("-p","--baseband-manifest",metavar="PATH",nargs=1,help="BuildManifest for requesting baseband ticket")
	parser.add_argument("ipsw",metavar="iPSW",nargs=1)
	args = parser.parse_args()

	client = futurerestore.PyFuturerestore()
	client.init()
	print("pyfuturerestore init done")
	if args.exit_recovery:
		client.exitRecovery()
		print("Done")
		return

	# args checks
	retassure(args.sep or args.latest_sep, "SEP was not specified")
	retassure(args.baseband or args.latest_baseband, "Baseband was not specified")
	if args.latest_sep:
		retassure(not args.sep, "can't specify --latest-sep and -s/--sep at once")
	if args.sep:
		retassure(not args.latest_sep, "can't specify --latest-sep and -s/--sep at once")
	if args.latest_baseband:
		retassure(not args.baseband, "can't specify --latest-baseband and -b/--baseband at once")
	if args.baseband:
		retassure(not args.latest_baseband, "can't specify --latest-baseband and -b/--baseband at once")

	if args.sep:
		retassure(args.sep_manifest, "-s/--sep requires -m/--sep-manifest")
	if args.sep_manifest:
		retassure(args.sep, "-m/--sep-manifest requires -s/--sep")
	if args.baseband:
		retassure(args.baseband_manifest, "-b/--baseband requires -p/--baseband-manifest")
	if args.baseband_manifest:
		retassure(args.baseband, " -p/--baseband-manifest requires -b/--baseband")

	client.loadAPTicket(args.apticket[0])

	if args.latest_sep:
		client.loadLatestSep()
	else:
		client.loadSepAtPath(args.sep[0])
		client.loadSepManifest(args.sep_manifest[0])

	if args.latest_baseband:
		client.loadLatestBaseband()
	else:
		client.loadBasebandAtPath(args.baseband[0])
		client.loadBasebandManifest(args.baseband_manifest[0])

	ipsw = args.ipsw[0]

	try:
		client.doRestore(ipsw)
		print("Done: restoring succeeded!")
	except m1n1Exception as e:
		print(e)
		print("Done: restoring failed!")

