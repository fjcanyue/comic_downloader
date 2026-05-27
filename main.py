# ruff: noqa: I001
import os
import signal
import sys

from loguru import logger

# Disable Selenium Manager stats to Plausible
os.environ['SE_AVOID_STATS'] = 'true'

from downloader.shell import Shell


USAGE = """用法:
  comic_downloader [下载路径]
  comic_downloader [下载路径] search <关键词>
  comic_downloader [下载路径] info <漫画URL或搜索结果序号>
  comic_downloader [下载路径] download <漫画URL或搜索结果序号>
  comic_downloader [下载路径] download_vols <漫画URL> <章节序号> [起始序号] [截止序号]

选项:
  -d, --debug     输出调试日志到终端
  --overwrite     覆盖已存在的下载文件
  -h, --help      显示帮助
"""


def main():
    signal.signal(signal.SIGINT, _handle_interrupt)
    args = sys.argv[1:]

    if '-h' in args or '--help' in args:
        print(USAGE)
        return

    overwrite = _configure_runtime(args)
    output_path, subcommand, subcommand_args = _parse_command(args)
    shell = Shell(output_path, overwrite=overwrite)

    try:
        _run_command(shell, subcommand, subcommand_args)
    finally:
        shell.context.destroy()


def _configure_runtime(args: list[str]) -> bool:
    logger.remove()
    if '-d' in args:
        logger.add(sys.stderr, level='DEBUG')
        args.remove('-d')
    if '--debug' in args:
        logger.add(sys.stderr, level='DEBUG')
        args.remove('--debug')

    overwrite = False
    if '--overwrite' in args:
        overwrite = True
        args.remove('--overwrite')

    logger.add('comic_downloader.log', rotation='500 MB', level='INFO')
    return overwrite


def _parse_command(args: list[str]) -> tuple[str, str | None, list[str]]:
    subcommands = {'search', 'info', 'download', 'download_vols'}
    subcommand = None
    subcommand_args = []
    output_path = os.getcwd()

    if args:
        if args[0] in subcommands:
            subcommand = args[0]
            subcommand_args = args[1:]
        else:
            output_path = args[0]
            if len(args) > 1 and args[1] in subcommands:
                subcommand = args[1]
                subcommand_args = args[2:]
    return output_path, subcommand, subcommand_args


def _run_command(shell: Shell, subcommand: str | None, subcommand_args: list[str]) -> None:
    if subcommand == 'search':
        _require_args(subcommand_args, '错误：请输入搜索关键字！例如: comic_downloader search 猎人')
        shell.do_s(' '.join(subcommand_args))
    elif subcommand == 'info':
        _require_args(
            subcommand_args, '错误：请输入动漫URL地址！例如: comic_downloader info https://...'
        )
        shell.do_i(' '.join(subcommand_args))
    elif subcommand == 'download':
        _require_args(
            subcommand_args, '错误：请输入动漫URL地址！例如: comic_downloader download https://...'
        )
        shell.do_d(' '.join(subcommand_args))
    elif subcommand == 'download_vols':
        _run_download_vols(shell, subcommand_args)
    else:
        shell.cmdloop()


def _run_download_vols(shell: Shell, subcommand_args: list[str]) -> None:
    _require_args(
        subcommand_args,
        '错误：请输入下载范围参数！例如: comic_downloader download_vols <url> <book_index> [start_index] [end_index]',
    )
    url = subcommand_args[0]
    vols_args = ' '.join(subcommand_args[1:])

    shell.do_i(url)

    if shell.context.comic is None:
        print('获取动漫详情失败，无法下载章节。')
        sys.exit(1)

    _require_args(subcommand_args[1:], '错误：缺少章节序号！')
    shell.do_v(vols_args)


def _require_args(args: list[str], message: str) -> None:
    if not args:
        print(message)
        sys.exit(1)


def _handle_interrupt(signum, frame):
    print('感谢使用，再会！')
    sys.exit(1)


if __name__ == '__main__':
    main()
