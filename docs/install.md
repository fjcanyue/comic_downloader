# Installation

## 从源码安装

1. 克隆仓库：

    ```bash
    git clone https://github.com/fjcanyue/comic_downloader.git
    ```

2. 进入项目目录：

    ```bash
    cd comic_downloader
    ```

3. 使用 uv 安装依赖：

    ```bash
    uv sync
    ```

4. （可选）安装文档构建依赖：

    ```bash
    uv sync --group docs
    ```

## 下载二进制文件

访问 [Releases 页面](https://github.com/fjcanyue/comic_downloader/releases/latest) 下载 `comic_downloader.exe`，直接运行即可。

## 运行

```bash
uv run main.py <下载路径>
```

不传路径时默认保存到当前工作目录。
