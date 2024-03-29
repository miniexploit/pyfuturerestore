from pyfuturerestore.pyfuturerestore import PyFuturerestore
import argparse
from pyipatcher.logger import get_my_logger
from m1n1Exception import *
from zipfile import ZipFile
from time import sleep

set_package_name('pyfuturerestore')

class blank:
    def __init__(self):
        pass

def _main():
    parser = argparse.ArgumentParser(description='pyfuturerestore - A re-implementation of futurerestore in Python', usage='pyfuturerestore [OPTIONS] IPSW')
    parser.add_argument('-t','--apticket',metavar='PATH',nargs=1,help='Signing tickets used for restoring',required=True)
    parser.add_argument('--exit-recovery',help='Exit from Recovery mode',action='store_true')
    parser.add_argument('--use-pwndfu',help='Restoring devices with Odysseus method. Device needs to be in pwned DFU mode already',action='store_true')
    parser.add_argument('--no-ibss',
                        help='Restoring devices with Odysseus method. For checkm8/iPwnder32 specifically, bootrom needs to be patched already with unless iPwnder',
                        action='store_true')
    parser.add_argument('--rdsk',metavar='PATH',nargs=1,
                        help='Set custom restore ramdisk for entering restore mode (requires use-pwndfu)')
    parser.add_argument('--rkrn', metavar='PATH', nargs=1,
                        help='Set custom restore kernelcache for entering restore mode (requires use-pwndfu)')
    parser.add_argument('--set-nonce',metavar='NONCE',help='Set custom nonce from your blob then exit recovery (set nonce from your blob if no nonce is provided) (requires use-pwndfu)',nargs='?',const=blank())
    parser.add_argument('--ignore-nonce-matching',help='Ignore device\'s post-hax ApNonce being unmatched with blob\'s ApNonce (PROCEED WITH CAUTION) (requires use-pwndfu)',action='store_true')
    parser.add_argument('--serial',help='Enable serial during boot (requires serial cable and use-pwndfu)',action='store_true')
    parser.add_argument('--boot-args',metavar='BOOTARGS',nargs=1,help='Set custom restore boot-args (PROCEED WITH CAUTION) (requires use-pwndfu)')
    parser.add_argument('--no-cache', help='Disable cached patched iBSS/iBEC (requires use-pwndfu)',action='store_true')
    parser.add_argument('--skip-blob',help='Skip SHSH blob validation (PROCEED WITH CAUTION) (requires use-pwndfu)',action='store_true')
    parser.add_argument('--latest-sep',help='Use latest signed SEP instead of manually specifying one',action='store_true')
    parser.add_argument('--latest-baseband',help='Use latest signed Baseband instead of manually specifying one',action='store_true')
    parser.add_argument('--no-baseband',help='Skip checks and don\'t flash baseband',action='store_true')
    parser.add_argument('-d', '--debug',help='More debug information during restore',action='store_true')
    parser.add_argument('--usb-backend',metavar='PATH',help='Customize USB backend for use',nargs=1)
    parser.add_argument('ipsw',metavar='iPSW',nargs=1)
    args = parser.parse_args()
    logger = get_my_logger(args.debug, name='pyfuturerestore')
    # args checks
    retassure(args.latest_sep, 'SEP was not specified')
    if not args.no_baseband:
        retassure(args.latest_baseband, 'Baseband was not specified')
    if args.rdsk:
        retassure(args.use_pwndfu, '--rdsk requires --use-pwndfu')
    if args.rkrn:
        retassure(args.use_pwndfu, '--rkrn requires --use-pwndfu')
    if args.serial:
        retassure(args.use_pwndfu, '--serial requires --use-pwndfu')
    if args.boot_args:
        retassure(args.use_pwndfu, '--boot-args requires --use-pwndfu')
    if args.no_cache:
        retassure(args.use_pwndfu, '--no-cache requires --use-pwndfu')
    if args.skip_blob:
        retassure(args.use_pwndfu, '--skip-blob requires --use-pwndfu')
    if not args.set_nonce:
        args.set_nonce = blank()
    ipsw = ZipFile(args.ipsw[0])
    client = PyFuturerestore(ipsw, logger, setnonce=(not isinstance(args.set_nonce, blank)), serial=args.serial, custom_gen=args.set_nonce[0] if not isinstance(args.set_nonce, blank) else None, ignore_nonce_matching=args.ignore_nonce_matching, noibss=args.no_ibss, skip_blob=args.skip_blob, pwndfu=args.use_pwndfu, custom_usb_backend=args.usb_backend[0] if args.usb_backend else None, no_cache=args.no_cache, verbose=args.debug)
    client.init()
    logger.info('pyfuturerestore init done')
    if args.exit_recovery:
        client.exit_recovery()
        logger.info('Done')
        return
    client.load_ap_ticket(args.apticket[0])

    if args.no_baseband:
        logger.warning('User specified is not to flash a baseband. This can make the restore fail if the device needs a baseband!')
        i = 10
        while i:
            print('Continuing restore in ', end='')
            print(i, end='\r')
            i -= 1
            sleep(1)
        print('')

    if args.rdsk:
        client.load_ramdisk(args.rdsk[0])
    if args.rkrn:
        client.load_rkrn(args.rkrn[0])
    if args.boot_args:
        client.set_bootargs(args.boot_args[0])

    try:
        client.do_restore()
        logger.info('Done: restoring succeeded!')
    except m1n1Exception as e:
        logger.error('Exception raised during restore:')
        logger.error(e)
        logger.error('Done: restoring failed!')


def main():
    try:
        _main()
    except m1n1Exception as e:
        print(f'Exception raised: {e}')