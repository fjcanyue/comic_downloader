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
    log_level = 'INFO'
    if '-d' in args:
        logger.add(sys.stderr, level='DEBUG')
        args.remove('-d')

    overwrite = False
    if '--overwrite' in args:
        overwrite = True
        args.remove('--overwrite')

    logger.add('comic_downloader.log', rotation='500 MB', level='INFO')

    # 检查是否包含子命令
    subcommands = ['search', 'info', 'download', 'download_vols']
    subcommand = None
    subcommand_args = []
    output_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 解析参数，区分 output_path 和 subcommand
    if len(args) > 0:
        if args[0] in subcommands:
            subcommand = args[0]
            subcommand_args = args[1:]
        else:
            output_path = args[0]
            if len(args) > 1 and args[1] in subcommands:
                subcommand = args[1]
                subcommand_args = args[2:]

    shell = Shell(output_path, overwrite=overwrite)

    try:
        if subcommand == 'search':
            if not subcommand_args:
                print("错误：请输入搜索关键字！例如: comic_downloader search 猎人")
                sys.exit(1)
            shell.do_s(" ".join(subcommand_args))
        elif subcommand == 'info':
            if not subcommand_args:
                print("错误：请输入动漫URL地址！例如: comic_downloader info https://...")
                sys.exit(1)
            shell.do_i(" ".join(subcommand_args))
        elif subcommand == 'download':
            if not subcommand_args:
                print("错误：请输入动漫URL地址！例如: comic_downloader download https://...")
                sys.exit(1)
            shell.do_d(" ".join(subcommand_args))
        elif subcommand == 'download_vols':
            if not subcommand_args:
                print("错误：请输入下载范围参数！例如: comic_downloader download_vols <url> <book_index> [start_index] [end_index]")
                sys.exit(1)
            # URL 需要被传递进去供 info 使用
            url = subcommand_args[0]
            vols_args = " ".join(subcommand_args[1:])

            # 首先调用 info 获取漫画对象到上下文中
            shell.do_i(url)

            if shell.context.comic is None:
                print("获取动漫详情失败，无法下载章节。")
                sys.exit(1)

            if not vols_args:
                print("错误：缺少章节序号！")
                sys.exit(1)

            shell.do_v(vols_args)
        else:
            # 交互式模式
            shell.cmdloop()
    finally:
        shell.context.destroy()


def __handler__(signum, frame):
    print('感谢使用，再会！')
    sys.exit(1)


if __name__ == '__main__':
    main()
