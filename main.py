import os
import sys
from dataclasses import dataclass
from json import JSONDecodeError

from loguru import logger

# Disable Selenium Manager stats to Plausible
os.environ['SE_AVOID_STATS'] = 'true'

from downloader.runtime_config import RuntimeConfig
from downloader.shell import Shell
from downloader.sources import validate_runtime_config_sources

INTERRUPT_EXIT_CODE = 130
CONFIG_ERROR_EXIT_CODE = 1


USAGE = """用法:
  comic_downloader [下载路径]
  comic_downloader [下载路径] search <关键词>
  comic_downloader [下载路径] info <漫画URL或搜索结果序号>
  comic_downloader [下载路径] download <漫画URL或搜索结果序号>
  comic_downloader [下载路径] download_vols <漫画URL> <章节序号> [起始序号] [截止序号]

选项:
  -d, --debug     输出调试日志到终端
  -c, --config <文件>  指定运行配置文件
  --overwrite     覆盖已存在的下载文件
  -h, --help      显示帮助
"""


@dataclass(frozen=True)
class RuntimeOptions:
    overwrite: bool
    runtime_config: RuntimeConfig | None


class RuntimeConfigLoadError(Exception):
    pass


def main() -> int:
    args = sys.argv[1:]

    if '-h' in args or '--help' in args:
        print(USAGE)
        return 0

    try:
        runtime_options = _configure_runtime(args)
    except RuntimeConfigLoadError as e:
        print(e)
        return CONFIG_ERROR_EXIT_CODE

    output_path, subcommand, subcommand_args = _parse_command(args)
    shell = Shell(
        output_path,
        overwrite=runtime_options.overwrite,
        runtime_config=runtime_options.runtime_config,
    )

    try:
        _run_command(shell, subcommand, subcommand_args)
    except KeyboardInterrupt:
        print()
        print('感谢使用，再会！')
        return INTERRUPT_EXIT_CODE
    finally:
        shell.context.destroy()
    return 0


def _configure_runtime(args: list[str]) -> RuntimeOptions:
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

    config_path = _pop_config_path(args)
    runtime_config = _load_runtime_config(config_path) if config_path else None

    logger.add('comic_downloader.log', rotation='500 MB', level='INFO')
    return RuntimeOptions(overwrite=overwrite, runtime_config=runtime_config)


def _load_runtime_config(config_path: str) -> RuntimeConfig:
    try:
        runtime_config = RuntimeConfig.load(config_path)
        validate_runtime_config_sources(runtime_config)
        return runtime_config
    except (OSError, JSONDecodeError, ValueError) as e:
        raise RuntimeConfigLoadError(f'配置文件加载失败: {e}') from e


def _pop_config_path(args: list[str]) -> str | None:
    for index, arg in enumerate(list(args)):
        if arg in {'-c', '--config'}:
            if index + 1 >= len(args):
                raise RuntimeConfigLoadError('配置文件加载失败: --config 需要指定配置文件路径')
            config_path = args[index + 1]
            del args[index : index + 2]
            return config_path
        if arg.startswith('--config='):
            config_path = arg.split('=', 1)[1]
            if not config_path:
                raise RuntimeConfigLoadError('配置文件加载失败: --config 需要指定配置文件路径')
            del args[index]
            return config_path
    return None


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


if __name__ == '__main__':
    raise SystemExit(main())
