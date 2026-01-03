import os
import signal
import sys

from loguru import logger

from downloader.shell import Shell


def main():
    signal.signal(signal.SIGINT, __handler__)
    args = sys.argv[1:]

    # Check for debug flag
    if '-d' in args:
        logger.add(sys.stderr, level="INFO")
        args.remove('-d')

    if len(args) == 0:
        path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_path = path
    else:
        output_path = args[0]

    Shell(output_path).cmdloop()


def __handler__(signum, frame):
    print('感谢使用，再会！')
    sys.exit(1)


if __name__ == '__main__':
    main()
