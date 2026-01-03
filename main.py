import os
import signal
import sys
import argparse

from loguru import logger

from downloader.shell import Shell
from downloader.tui_app import ComicApp


def main():
    signal.signal(signal.SIGINT, __handler__)

    parser = argparse.ArgumentParser(description="Comic Downloader")
    parser.add_argument("path", nargs="?", help="Output directory path for downloads")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--cli", action="store_true", help="Run in CLI mode (legacy shell)")
    parser.add_argument("--tui", action="store_true", help="Run in TUI mode (default)")

    args = parser.parse_args()

    # Configure logging
    if args.debug:
        logger.add(sys.stderr, level="INFO")

    # Determine output path
    if args.path:
        output_path = args.path
    else:
        # Default to project root or current directory
        # The original code did: path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # which assumes main.py is in src/ or similar. But main.py is at root in file list.
        # If main.py is at root, dirname(abspath) is root. dirname(dirname(abspath)) is parent of root.
        # Let's check where main.py is. It is in root.
        # So os.path.dirname(os.path.abspath(__file__)) is the root dir.
        output_path = os.path.dirname(os.path.abspath(__file__))

    # Run mode
    if args.cli:
        Shell(output_path).cmdloop()
    else:
        # Default to TUI
        app = ComicApp(output_path)
        app.run()


def __handler__(signum, frame):
    print('感谢使用，再会！')
    sys.exit(1)


if __name__ == '__main__':
    main()
