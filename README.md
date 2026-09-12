# DataSheet A股/美股/韩股桌面数据工作台

Windows 10/11 与 macOS 桌面行情工具，采用无涨跌色的黑白灰办公表格界面。行情只用于个人查看，不包含交易功能。

## Windows 构建与运行

安装 Python 3.12 后，在 PowerShell 中运行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

构建后的程序位于 `dist-windows\DataSheet\DataSheet.exe`。

直接双击即可运行。关闭主窗口会最小化到系统托盘；请从托盘菜单选择“退出”以彻底关闭。

`DataSheet.exe` 与旁边的 `_internal` 文件夹共同组成免安装程序，请保留整个 `DataSheet` 文件夹；可以为 `DataSheet.exe` 创建桌面快捷方式。

## macOS 构建

PyInstaller 不能在 Windows 上直接生成 macOS 应用，因此需要同事在 Mac 上从源码构建：

1. 安装 Python 3.12（Apple 芯片请选择 arm64 版本，Intel Mac 请选择 x86_64 版本）。
2. 解压源码包并打开“终端”。
3. 进入源码目录后运行：

```bash
chmod +x build_macos.sh
./build_macos.sh
```

脚本会自行创建隔离的 Python 环境并安装依赖，成品位于 `dist-macos/DataSheet.app`。首次打开未签名的本地构建应用时，如果 macOS 拦截，请在“系统设置 → 隐私与安全性”中选择仍要打开。

源码运行方式：

```bash
python3 -m venv .venv-macos
.venv-macos/bin/python -m pip install -r requirements.txt
.venv-macos/bin/python run_datasheet.py
```

## 功能

- 固定展示上证指数、深证成指、创业板指、道琼斯、标普 500、纳斯达克综合、KOSPI 和 KOSDAQ。
- 支持输入 `600519`、`600519.SH`、`AAPL`、`005930.KR`、`005930.KS` 或 `KR:005930` 等代码维护自选股。
- 完整表格与紧凑侧栏切换，自动记忆窗口状态。
- 所有涨跌、状态、按钮与图标均采用黑白灰显示，不使用红绿涨跌色。
- A股与美股常规时段使用东方财富与腾讯，韩股使用 Naver 与 Yahoo；连续失败两次后切换，五分钟后探测恢复。
- 美股自选股支持盘前（纽约时间 04:00–09:30）与盘后（16:00–20:00）价格，扩展时段由 Yahoo 批量行情补充。
- 支持 IBKR 美股隔夜盘（周日至周四纽约时间 20:00–次日 03:50），通过本机已登录的 Client Portal Gateway 读取 `OVERNIGHT` 专属行情；自动处理美国夏令时。固定美股指数仍只显示常规指数行情。
- 交易时段默认每 3 秒刷新，闭市默认每 30 秒刷新。
- 离线时保留最后一次缓存，并明确标注数据可能过期。

## Windows 开发与测试

```powershell
$env:PYTHONPATH = "."
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

Windows 状态保存在 `%LOCALAPPDATA%\DataSheet\state.json`；macOS 状态保存在 `~/Library/Application Support/DataSheet/state.json`。

## 启用 IBKR 隔夜行情

IBKR 的隔夜盘是独立于常规 `SMART` 行情的交易场所，因此必须使用明确带有 `@OVERNIGHT` 的 IBKR 行情请求，普通公共行情源无法可靠替代。

1. 准备已开通并可正常登录的 IBKR 账户以及现代 Java 运行环境。
2. 从 [IBKR 官方地址下载 Client Portal Gateway](https://download2.interactivebrokers.com/portal/clientportal.gw.zip) 并解压。
3. Windows 在解压目录运行 `bin\run.bat root\conf.yaml`；macOS 在终端运行 `bin/run.sh root/conf.yaml`，使用 DataSheet 时保持网关运行。
4. 浏览器打开 `https://localhost:5000`，接受仅限本机的证书提示并完成 IBKR 登录。IBKR 要求人工登录，通常需要每日重新认证。
5. 启动 DataSheet。隔夜交易时段的美股自选股状态会由“隔夜待连接”变为“隔夜”，行情来源显示“IBKR隔夜”。

程序默认连接 `https://localhost:5000/v1/api`。如果 macOS 的 5000 端口被其他软件占用，可按 IBKR 网关说明改用其他端口，再到 DataSheet“设置 → IBKR 网关地址”填写对应的本机地址。

DataSheet 只调用登录状态、证券代码解析和行情快照三个只读接口，不调用下单、撤单、账户或凭证接口。网关未运行、登录失效、代码不支持隔夜交易或没有可用报价时，程序保留常规盘缓存并明确显示“隔夜待连接”，不会把旧价格标成隔夜实时价。

## 分享源码

分享源码压缩包即可，不要把 `.venv`、`build`、`dist` 或 Windows 的 `DataSheet.exe` 混入源码包。源码包应包含 `datasheet`、`tests`、`tools`、`run_datasheet.py`、`requirements.txt`、`build.ps1`、`build_macos.sh` 与本说明。

## 数据说明

公共行情接口没有服务等级或交易所级实时保证，可能出现延迟、限流或接口变化。若用于商业展示、多人分发或需要严格授权行情，应更换正式授权的数据服务。

美股盘前、盘后和隔夜盘的流动性通常低于常规时段。界面的“状态”列会明确显示“盘前”“盘后”“隔夜”或“待连接/待更新”，鼠标悬停可查看价格阶段和实际行情来源；扩展时段价格仅适用于有成交且相应数据源支持的美股或 ETF。
