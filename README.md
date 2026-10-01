# TuneFetch — 曲目批量获取工具

一开始写这个其实只是为了玩gtaol的时候能导入自己的歌曲创建子电台，但发现需要歌曲的未加密的mp3格式，网上苦苦搜寻一顿发现没有相关开源程序（也许是我没找到），于是整了一个这自用感觉还挺好的，遂开源。

选的下载网站是歌曲海。

安全声明：仅用于测试，任何版权责任问题概不负责。

根据 CSV 中的歌曲名和歌手名批量检索歌曲，并将结果保存到指定目录。

## 目录结构

```text
tunefetch/
├─ src/
│  └─ gequhai_downloader.py   # 主程序
├─ examples/
│  └─ songs.example.csv       # 输入格式示例
├─ input/
│  └─ songs.csv               # 当前歌曲清单
├─ downloads/                 # 下载输出（Git 忽略）
├─ .gitignore
├─ requirements.txt
└─ run.bat                    # Windows 快速启动
```

## 环境要求

- Windows 10/11
- Python 3.10+
- Microsoft Edge（默认浏览器通道）
- 系统自带或可调用的 `curl.exe`

## 安装

```powershell
cd "tunefetch"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 输入格式

CSV 使用 UTF-8 编码，表头为：

```csv
song,artist
Let Go,Beau Young Prince
```

## 使用

直接运行：

```powershell
python .\src\gequhai_downloader.py .\input\songs.csv -o .\downloads
```

或者双击 `run.bat`。

仅检查匹配结果，不下载：

```powershell
python .\src\gequhai_downloader.py .\examples\songs.example.csv --dry-run
```

显示浏览器窗口：

```powershell
python .\src\gequhai_downloader.py .\input\songs.csv --show-browser
```

程序会在输出目录生成 `report.csv`，记录每首歌曲的处理状态。


