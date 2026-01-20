import os
import signal
import sys
from loguru import logger

# Disable Selenium Manager stats to Plausible
os.environ['SE_AVOID_STATS'] = 'true'

from downloader.shell import Shell


def main():
    signal.signal(signal.SIGINT, __handler__)
    args = sys.argv[1:]

    # Configure logging
    logger.remove()

    # Check for debug flag
    log_level = "INFO"
    if '-d' in args:
        logger.add(sys.stderr, level="DEBUG")
        args.remove('-d')

    overwrite = False
    if '--overwrite' in args:
        overwrite = True
        args.remove('--overwrite')

    logger.add("comic_downloader.log", rotation="500 MB", level="INFO")

    if len(args) == 0:
        path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_path = path
    else:
        output_path = args[0]

    Shell(output_path, overwrite=overwrite).cmdloop()


def __handler__(signum, frame):
    print('感谢使用，再会！')
    sys.exit(1)


if __name__ == '__main__':
    main()
