# Builds

项目使用 PyInstaller 打包为单个可执行文件。

## 打包为 EXE

```bash
uv run pyinstaller downloader.spec
```

打包产物在 `dist/comic_downloader.exe`。

## Python 源码构建

```bash
uv build
```

构建产物在 `dist/` 目录下（`.whl` 和 `.tar.gz`）。
