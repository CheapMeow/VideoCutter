# VideoCutter

VideoCutter 是一个用 Python 和 Qt 编写的桌面工具，用来裁剪视频并把视频段落拼到轨道上。

## 运行

需要 64 位 Windows，以及 Python 3.11 或更高版本。下面的命令使用 Python 3.13，并在仓库根目录执行。

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m videocutter
```

## 打包

打包在 Windows 上进行。环境要求：

- Windows 10 或更高版本
- Python 3.11 或更高版本，建议使用 3.12 或 3.13
- 已用上面的命令安装 `requirements.txt` 里的依赖，其中包含 PyInstaller

打包使用的 Python 解释器通过环境变量 `VIDEOCUTTER_PYTHON` 指定，值是 `python.exe` 的完整路径。本机路径放在 `local/paths.ps1`。这个文件只在本机使用，不会进入版本库。可以把它写成：

```powershell
$env:VIDEOCUTTER_PYTHON = "D:\VideoCutter\.venv\Scripts\python.exe"
```

在仓库根目录执行：

```powershell
. .\local\paths.ps1
.\scripts\build.ps1
```

打包脚本是 [scripts/build.ps1](scripts/build.ps1)。脚本会检查 `VIDEOCUTTER_PYTHON` 指向的解释器至少是 Python 3.11，并且已经安装 PySide6、opencv-python、PyAV 和 PyInstaller。

打包完成后，程序位于 `dist\VideoCutter\VideoCutter.exe`。`build` 和 `dist` 是构建目录，已经写在 `.gitignore` 里。
