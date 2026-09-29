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
USAGE_ERROR_EXIT_CODE = 2


USAGE = """用法:
  comic_downloader [下载路径]
  comic_downloader [下载路径] search <关键词>
  comic_downloader [下载路径] info <漫画URL>
  comic_downloader [下载路径] download <漫画URL>
  comic_downloader [下载路径] download_vols <漫画URL> <章节序号> [起始序号] [截止序号]
  comic_downloader [下载路径] tasks [任务ID]
  comic_downloader [下载路径] sources
  comic_downloader [下载路径] check [动漫源序号|代码名|all]
  comic_downloader [下载路径] retry [任务序号|任务ID|all]

选项:
  -d, --debug     输出调试日志到终端
  -c, --config <文件>  指定运行配置文件
  --overwrite     覆盖已存在的下载文件
  -h, --help      显示帮助

直接子命令使用完整 URL；搜索结果序号仅在交互式 shell 内有效。
download_vols 的一个范围参数表示截止序号，两个表示起始和截止，均从 1 开始。
退出码: 0 成功；1 执行/配置失败；2 参数错误；130 用户中断。
"""


@dataclass(frozen=True)
class RuntimeOptions:
    overwrite: bool
    runtime_config: RuntimeConfig | None


class RuntimeConfigLoadError(Exception):
    pass


class CommandUsageError(ValueError):
    pass


def main() -> int:
    args = sys.argv[1:]

    if '-h' in args or '--help' in args:
        print(USAGE)
        return 0

    try:
        runtime_options = _configure_runtime(args)
        output_path, subcommand, subcommand_args = _parse_command(args)
    except RuntimeConfigLoadError as e:
        print(e)
        return CONFIG_ERROR_EXIT_CODE
    except CommandUsageError as e:
        print(f'参数错误：{e}\n使用 --help 查看用法。')
        return USAGE_ERROR_EXIT_CODE

    shell = Shell(
        output_path,
        overwrite=runtime_options.overwrite,
        runtime_config=runtime_options.runtime_config,
    )

    try:
        return _run_command(shell, subcommand, subcommand_args)
    except KeyboardInterrupt:
        shell.presenter.farewell()
        return INTERRUPT_EXIT_CODE
    except Exception as e:
        logger.exception('命令执行失败')
        print(f'操作失败：{e}。详细信息见 comic_downloader.log。')
        return CONFIG_ERROR_EXIT_CODE
    finally:
        shell.context.destroy()


def _configure_runtime(args: list[str]) -> RuntimeOptions:
    logger.remove()
    if '-d' in args or '--debug' in args:
        logger.add(sys.stderr, level='DEBUG')
        args[:] = [arg for arg in args if arg not in {'-d', '--debug'}]

    overwrite = False
    if '--overwrite' in args:
        overwrite = True
        args[:] = [arg for arg in args if arg != '--overwrite']

    config_path = _pop_config_path(args)
    if any(arg in {'-c', '--config'} or arg.startswith('--config=') for arg in args):
        raise CommandUsageError('--config 只能指定一次。')
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
            if index + 1 >= len(args) or args[index + 1].startswith('-'):
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
    subcommands = {
        'search',
        'info',
        'download',
        'download_vols',
        'tasks',
        'sources',
        'check',
        'retry',
    }
    subcommand = None
    subcommand_args = []
    output_path = os.getcwd()

    if any(arg.startswith('-') for arg in args):
        raise CommandUsageError('存在未知选项；请检查选项拼写。')
    if args:
        if args[0] in subcommands:
            subcommand = args[0]
            subcommand_args = args[1:]
        else:
            output_path = args[0]
            if len(args) > 1 and args[1] in subcommands:
                subcommand = args[1]
                subcommand_args = args[2:]
            elif len(args) > 1:
                raise CommandUsageError(f'未知子命令：{args[1]}')
    _validate_command(subcommand, subcommand_args)
    return output_path, subcommand, subcommand_args


def _validate_command(subcommand: str | None, args: list[str]) -> None:
    if subcommand is None:
        return
    optional_commands = {'sources': 0, 'tasks': 1, 'retry': 1, 'check': 1}
    if subcommand in optional_commands:
        if len(args) > optional_commands[subcommand]:
            raise CommandUsageError(
                f'{subcommand} 最多接受 {optional_commands[subcommand]} 个参数。'
            )
        return
    if not args or not ' '.join(args).strip():
        raise CommandUsageError(f'{subcommand} 缺少参数。')
    if subcommand == 'search':
        return
    if not args[0].startswith(('https://', 'http://')):
        raise CommandUsageError('直接子命令需要完整的漫画 URL；序号仅用于交互式 shell。')
    if subcommand in {'info', 'download'}:
        if len(args) != 1:
            raise CommandUsageError(f'{subcommand} 只接受一个漫画 URL。')
        return
    if not 2 <= len(args) <= 4:  # noqa: PLR2004 - URL plus group and optional range
        raise CommandUsageError('download_vols 需要 URL、分组序号，以及可选的截止或起始/截止序号。')
    try:
        indices = [int(value) for value in args[1:]]
    except ValueError:
        raise CommandUsageError('分组和范围序号必须是正整数。') from None
    if any(value < 1 for value in indices):
        raise CommandUsageError('序号从 1 开始，必须是正整数。')
    if len(indices) == 3 and indices[1] > indices[2]:  # noqa: PLR2004
        raise CommandUsageError('起始序号不能大于截止序号。')


def _run_command(shell: Shell, subcommand: str | None, subcommand_args: list[str]) -> int:
    shell.paginate_output = subcommand is None
    if subcommand == 'search':
        shell.do_s(' '.join(subcommand_args))
    elif subcommand == 'info':
        shell.do_i(' '.join(subcommand_args))
    elif subcommand == 'download':
        shell.do_d(' '.join(subcommand_args))
    elif subcommand == 'download_vols':
        _run_download_vols(shell, subcommand_args)
    elif subcommand == 'tasks':
        shell.do_tasks(' '.join(subcommand_args))
    elif subcommand == 'sources':
        shell.do_sources('')
    elif subcommand == 'check':
        shell.do_check(' '.join(subcommand_args))
    elif subcommand == 'retry':
        shell.do_retry(' '.join(subcommand_args))
    else:
        shell.cmdloop()
        return 0
    return 0 if shell.last_command_ok else CONFIG_ERROR_EXIT_CODE


def _run_download_vols(shell: Shell, subcommand_args: list[str]) -> None:
    url = subcommand_args[0]
    vols_args = ' '.join(subcommand_args[1:])

    shell.do_i(url)

    if shell.context.comic is None:
        print('获取动漫详情失败，无法下载章节。')
        shell.last_command_ok = False
        return

    shell.do_v(vols_args)


if __name__ == '__main__':
    raise SystemExit(main())
