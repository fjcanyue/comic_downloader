import os
import sys

from downloader.shell import Shell

if __name__ == '__main__':
    args = sys.argv[1:]
    if len(args) == 0:
        path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_path = path
    else:
        output_path = args[0]

    Shell(output_path).cmdloop()
