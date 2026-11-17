# Wisland · Windows 液态灵动岛

<p align="center">
  <strong>贴在 Windows 屏幕边缘的液态毛玻璃胶囊</strong><br>
  音乐、歌词、消息、系统控制、Clash Verge、实时字幕与快捷工具集中在一处。
</p>

<p align="center">
  <img alt="Windows 10/11" src="https://img.shields.io/badge/Windows-10%20%2F%2011-0078D4?logo=windows">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white">
  <img alt="PySide6" src="https://img.shields.io/badge/UI-PySide6-41CD52?logo=qt&logoColor=white">
  <img alt="License MIT" src="https://img.shields.io/badge/License-MIT-green">
</p>

<p align="center"><img src="screenshots/home.png" width="900" alt="Wisland 主页"></p>

> 本仓库是 Wisland 的深度改造版本，保留液态形变、毛玻璃和边缘吸附体验，并针对音乐、贴纸、控制中心、消息提醒、Clash Verge、性能和 Windows 使用习惯进行了大量调整。

## 亮点

- **液态灵动岛**：悬停弹性展开，拖动时拉丝、断开并吸附到最近的屏幕边缘；切页改变高度时自动边界夹紧防背景光带闪烁。
- **三种收起态**：时钟天气、用户贴纸、音乐歌词；滚轮可手动切换。
- **音乐体验**：播放器控制、进度条点击/拖动跳转、网易云红心状态与漫游/心动模式一键切换、漫游切歌无缝过渡、封面悬停多色 Bloom 光晕、固定宽度滚动歌词、暂停 5 秒自动切贴纸，并可在设置中自由调节播放器刷新间隔。
- **自定义贴纸**：主页和收起态共用同一图片目录，文件夹里放什么就随机显示什么。
- **控制中心**：音量、亮度、WLAN、蓝牙、热点、输出设备和分应用音量合成器（支持静音滑块平滑收空与回弹）。
- **Clash Verge Rev**：规则 / 全局 / 直连模式、系统代理、TUN、节点选择和实时速度。
- **消息提醒**：QQ、微信、邮件；切到 QQ / 微信前台后自动清除对应未读数。
- **实时字幕与学习**：系统声音日语识别、翻译、查词、单词本和 Anki 同步。
- **低常驻开销**：实时字幕模型与日语词典按需加载，避免未使用时占用数百 MB 内存。
- **独立可执行入口与原生进程名**：提供带托盘同款图标的 `Wisland.exe` 启动器与托盘「退出并重启」，后台进程直接显示为 `Wisland.exe`。

## 效果图

<p align="center"><img src="screenshots/controls.png" width="820" alt="Wisland 控制中心"></p>

<p align="center">
  <img src="docs/compact_clock.png" height="58" alt="时钟收起态">&nbsp;
  <img src="docs/compact_music.png" height="58" alt="音乐收起态">
</p>

<p align="center"><img src="docs/subtitles.png" width="640" alt="实时字幕"></p>

<p align="center">
  <img src="docs/theme_light.png" width="285" alt="浅色主题">
  <img src="docs/theme_rouge.png" width="285" alt="胭脂主题">
  <img src="docs/theme_sky.png" width="285" alt="晴空主题">
</p>

> 部分截图来自早期版本；当前贴纸、控制页布局和部分交互以实际运行效果为准。

## 系统要求

- Windows 10 / Windows 11
- Python 3.10 或更新版本
- 推荐使用 64 位 Python
- 建议解压或克隆到当前用户可写目录；配置、日志、模型和运行数据都保存在项目目录中，不建议放进受保护的系统目录。
- 部分能力取决于硬件或第三方软件：
  - 亮度控制需要显示器支持 DDC/CI、WMI 或配置 Twinkle Tray。
  - 蓝牙和移动热点需要系统与驱动支持。
  - Clash 控制针对 Clash Verge Rev / Mihomo。
  - 实时字幕首次使用需要下载约 630–660 MB 的识别模型。

## 安装

### 方法一：下载源码

1. 安装 [Python 3.10+](https://www.python.org/downloads/windows/)，安装时建议勾选 **Add python.exe to PATH**。
2. 下载本仓库并解压，或执行：

```bash
git clone https://github.com/MomoCyann/wisland.git
cd wisland
```

3. 双击 `setup.bat`。
   - 自动创建 `.venv`。
   - 自动补齐 pip 并安装依赖。
   - PyPI 无法连接时会尝试清华镜像。
   - 自动生成用于后台运行的 `.venv\Scripts\Wisland.exe`。
4. 双击 `Wisland.exe`（或 `wisland.vbs`）启动。

首次启动会在项目目录生成：

- `config.json`：用户配置。
- `data/`：日志、缓存和运行数据。

### 启动方式

| 方式 | 用途 |
| --- | --- |
| 双击 `Wisland.exe` | 推荐，独立无控制台 EXE 启动器（与托盘同款图标，开机自启默认调用） |
| 双击 `wisland.vbs` | 兼容静默启动脚本 |
| `run.bat` | 后台启动 |
| `run.bat /r` | 停止旧实例并重新启动 |
| `run.bat /s` | 启动并打开设置 |
| `run.bat /d` | 控制台调试模式 |

开机自启可在 Wisland 设置或系统托盘右键菜单中开启，托盘右键亦提供「退出并重启」。

## 基本操作

| 操作 | 结果 |
| --- | --- |
| 鼠标悬停 | 展开灵动岛 |
| 鼠标离开 | 延迟收起 |
| 收起态滚轮 | 切换时钟、贴纸、音乐视图 |
| 按住拖动 | 脱离当前边缘并吸附到最近边缘 |
| 双击灵动岛 | 在“悬停展开”和“长关”之间切换；可在设置中关闭此行为 |
| 右键灵动岛 | 打开设置窗口 |
| 系统托盘左键 | 展开 / 收起灵动岛；点击展开后若非“常驻展开”模式，鼠标移入灵动岛再离开会自动延迟收起 |
| 系统托盘右键 | 打开主题、展开方式、可穿透、开机自启、退出并重启和退出菜单 |
| 可穿透状态下右键 | 直接退出可穿透状态 |
| 点击专辑封面 | 打开或唤出网易云音乐（仅悬停专辑封面时触发放大与 Bloom 光晕） |
| 点击/拖动进度条 | 跳转音乐播放进度（SMTC 与网易云均支持） |
| 点击漫游/心动按钮 | 播放栏最右侧按钮，在网易云漫游模式与心动模式之间互相切换 |
| 点击主页贴纸 | 随机切换下一张贴纸 |

## 收起态与音乐

### 时钟与天气

- 时间始终以胶囊中心为基准显示。
- 右侧可显示天气与消息角标。
- 可按设置的间隔在时钟与贴纸之间自动轮换。

### 自定义贴纸

默认贴纸目录为：

```text
march7stickers/
```

仓库只保留目录说明，不附带三月七或其他第三方角色贴纸图片；请自行放入拥有使用权的素材。

支持：

```text
.png  .jpg  .jpeg  .webp  .gif  .bmp
```

GIF 当前按静态帧显示。可在 **设置 → 外观 → 动效 → 贴纸图片文件夹** 中选择任意目录。主页和收起态共用该目录；添加或删除图片后会在后续随机切换时自动重新扫描。

### 音乐与歌词

支持两类媒体来源：

- **网易云音乐**：读取本地 `cloudmusic.elog`，无需安装插件，可获得歌曲、歌手、进度、播放状态和红心状态。
- **SMTC 播放器**：QQ 音乐、Spotify、浏览器、B 站等，需要播放器接入 Windows 系统媒体控制。

行为说明：

- 开始播放时自动切换到音乐视图。
- 暂停后保留歌曲界面 5 秒，随后切换为贴纸。
- 恢复播放后立即切回歌曲界面。
- 可穿透状态下也遵循同样逻辑。
- 收起态音乐宽度可在 `360–760 px` 之间调整。
- 歌名或歌词超出设定宽度时，会在胶囊内部横向滚动，不再无限拉长灵动岛。
- 网易云红心按钮会读取真实喜欢状态（含漫游切心动时的预加载状态），并支持添加 / 取消喜欢；漫游切歌时结合本地缓存缩略图与状态兜底，避免短暂闪出“未在播放”或空封面。
- 支持点击或拖动进度条跳进度，以及右侧按钮一键在网易云漫游模式与心动模式间切换（通过区域剪枝与坐标缓存后台无感触发，托盘隐藏时不抢焦点也不闪现任务栏图标）。
- 设置中可调 `media.poll_ms`（`100–3000 ms`）控制播放器同步刷新频率，修改后实时生效。

## 页面功能

### 主页

- 专辑封面（仅悬停封面区域时放大并扩散封面原色 Bloom 光晕）、歌名、歌手、可点击/拖动进度条与播放控制。
- 网易云红心状态与漫游/心动模式切换按钮。
- 自定义贴纸与鼠标跟随效果。
- 展开方式、可穿透、静音、截图可见性、全屏显示等快捷开关。
- 自定义快速启动应用，支持新增、编辑、删除和总开关。

### 消息

- QQ、微信、Thunderbird / 邮件提醒。
- 数据来源包括 Windows 通知数据库和任务栏闪烁事件。
- 不读取或上传聊天正文。
- 手动切换到 QQ / 微信前台后，自动清除对应的 Wisland 未读数量；这不等同于向聊天服务器发送已读回执。
- 消息历史只保留当前运行期间最近 50 条，不做跨启动持久化。
- 没有消息历史时自动缩短页面，不保留大块空白。

### 股票

- A 股、港股、美股行情与分时。
- 搜索添加、右键删除自选。
- 支持涨跌幅、目标价和提醒。

### 天气

- 默认使用 Open-Meteo，无需 API Key。
- 可选 OpenWeather。
- 支持多城市、逐小时和多日预报。

### 控制中心

- 主音量与静音。
- 显示器亮度。
- WLAN、蓝牙、移动热点。
- 完整音频输出设备名称与快速切换。
- 分应用音量合成器：最多同时显示 3 项，更多应用在卡片内滚动。
- 控制项可在设置中单独显示或隐藏。

### Clash Verge Rev

检测到 Clash Verge Rev 后，控制页会显示：

- 规则 / 全局 / 直连模式。
- 系统代理。
- TUN 模式。
- 当前节点与节点切换。
- 上传 / 下载速度。
- 打开或唤出 Clash Verge。

模式、系统代理和 TUN 优先读取并触发 Clash Verge 自己在 `verge.yaml` 中配置的全局快捷键，让 Clash 前端、托盘和后端状态保持同步；节点选择使用 Mihomo 控制接口。

默认配置目录：

```text
%APPDATA%\io.github.clash-verge-rev.clash-verge-rev
```

如果安装位置或配置目录不同，可在 Wisland 设置中修改。

### 剪贴板与翻译

- 最近文字 / 图片剪贴板历史。
- 点击条目重新复制。
- 全局热键打开剪贴板页或翻译当前剪贴板文本。
- 翻译服务支持自定义 OpenAI 兼容接口，默认配置为 DeepSeek。

### 实时字幕、查词与 Anki

流程：

```text
系统声音 → VAD 断句 → 日语识别 → 中文翻译 → 字幕历史 / 查词 / 单词本
```

- 第一次点击“开始聆听”会下载识别模型。
- 未配置翻译 API Key 时仍可显示日语识别结果。
- 支持点击单词查词、加入单词本、导出和同步到 AnkiConnect。
- 实时字幕依赖与日语词典均为按需加载，平时不会提前占用大量内存。

## 设置与配置

大部分功能可直接在设置窗口修改。完整配置保存在项目根目录的 `config.json`，首次启动自动生成。

常用配置：

| 配置 | 说明 |
| --- | --- |
| `island.edge` | 吸附边缘：`top` / `bottom` / `left` / `right` |
| `island.expand_mode` | `hover` 悬停展开、`always` 常驻展开、`never` 长关 |
| `island.compact_view` | 默认收起态：`clock` / `pet` / `music` |
| `island.compact_media_width` | 收起态音乐宽度，默认 `640` |
| `island.sticker_dir` | 主页和收起态共用的贴纸目录 |
| `island.double_click_long_off` | 是否允许双击切换长关 |
| `island.passthrough` | 是否启用鼠标穿透 |
| `media.auto_show` | 播放时是否自动显示音乐视图 |
| `media.lyrics` | 是否获取并显示歌词 |
| `media.poll_ms` | 播放器刷新间隔（毫秒，`100–3000`，默认 `700`） |
| `controls.show_mixer` | 是否显示分应用音量合成器 |
| `clash.config_dir` | Clash Verge 配置目录 |
| `translate.api_key` | 翻译 API Key |
| `hotkeys.*` | 全局快捷键 |

修改 `config.json` 前建议先退出 Wisland，或通过设置界面修改，避免运行中的配置保存覆盖手工编辑。

## 全局快捷键

默认快捷键：

| 功能 | 默认值 |
| --- | --- |
| 展开 / 收起 | `Ctrl+Alt+I` |
| 翻译剪贴板 | `Ctrl+Alt+J` |
| 剪贴板历史 | `Ctrl+Alt+V` |

快捷键被其他软件占用时，可在设置中修改并立即重新注册。

## 性能说明与优化历史

本仓库历经三轮系统性性能与体验优化：

### 第一阶段：常驻资源瘦身与按需加载（DeepSeek Harness 早期迭代）
- **重型依赖按需加载**：实时字幕的 `sherpa-onnx` 等识别依赖仅在点击“开始聆听”时加载；日语分词 `fugashi` / `unidic`（会映射数百 MB 词典数据）仅在首次分词或查词时加载。
- **高频调用节流与隐私友好**：音频峰值查询 `peak()` 增加 150ms 短时缓存，避免每个绘制帧跨 COM 调用；移除 `netsh wlan` 轮询，消除 Windows 11 任务栏位置图标频繁闪烁；隐藏页面（如关闭股票页）自动停止后台轮询。
- **原生进程入口**：使用独立无窗口 `Wisland.exe`，避免额外转启动控制台进程。

### 第二阶段：交互去卡顿与动画/轮询调优（DeepSeek Harness `问候` 会话）
- **音量合成器去卡顿**：`AudioService._iter_sessions()` 复用随设备缓存的 `IAudioSessionManager2` 替代每次耗时约 90ms 的 `AudioUtilities.GetAllSessions()`（降至约 0.1ms），消除打开控制中心与拖动音量条时的主线程卡顿。
- **滑块静音动效与圆角裁剪**：`Slider` 引入独立 `fill` 弹簧并与容器圆角路径求交（`fp.intersected(path)`），解决静音收缩尾帧跳变与左端圆角溢出。
- **可调播放器刷新间隔**：新增 `media.poll_ms`（`100–3000 ms` 分段睡眠，修改实时生效无需重启），并在媒体操作后跟进短轮询；歌词与网易云请求统一 `trust_env=False` 规避异常代理环境变量阻塞。
- **托盘智能收起与独立启动器**：托盘左键展开引入独立 `"enter"` 锁（移入灵动岛解锁、再移出自动收起），提供根目录带图标 `Wisland.exe` 启动器与托盘「退出并重启」。

### 第三阶段：全项目 CPU / 内存 / I/O 深度审查与优化
- **修复 `numpy` / OpenBLAS 启动泄露**：移除 `learn/wordbook.py` 顶层 `import numpy as np`（改为 `save_wav()` 内按需导入），延迟 `LearnService` 的 `wordbook.db` 连接与同步定时器初始化，彻底消除未开启字幕时常驻加载 `libscipy_openblas64.dll` 及其约 20 个工作线程的问题。
- **收起静止态自适应帧率**：收起且弹簧静止时，时钟、暂停音乐与远离光标的贴纸视图自动降至约 `9 FPS`（`110ms`）维持边缘微弱流光；鼠标靠近贴纸、播放滚动歌词或展开/拖拽时即时切回 `45–60 FPS`。
- **绘制热路径缓存**：`ui_font()` / `icon_font()` 增加 `@lru_cache` 并过滤本机未安装字体族；`CompactView` 缓存歌词行像素宽度并移除无效渐变构造；`sticker_paths()` 按目录 `st_mtime_ns` 缓存并修复空目录每帧扫盘；`Island._inside()` 增加包围盒快速粗筛；切页高度变化改用边界夹紧绘制防壁纸回绕闪烁。
- **后台服务按需降频与连接/线程复用**：控制中心未展开时 `ClashService` 跳过 `/connections` 大列表拉取并放宽至 `3s`、`HotspotService` 放宽至 `20s`、`AudioService` 主音量轮询放宽至 `500ms`；`RadioService` 与 `HotspotService` 合并共用单一 `winrt_loop()` 后台线程；抽取公共 `http_client()` 复用连接池；`NotifyService` 先校验 `wpndatabase.db` / `-wal` 的 `mtime` 再查询 SQLite。
- **内存峰值与缓存上限治理**：`netease.py` 启动日志预读 `PRELOAD_BYTES` 从 `32 MB` 下调至 `2 MB`（消除启动瞬间约 96MB 的解码堆峰值）；为封面、歌曲元数据、应用图标缓存加上淘汰上限；剪贴板图片改为打开页面时按需解码缩略图并缓存缩放后 `QPixmap`，主页收起时自动释放多余大图贴纸缓存。

> **开发机同机实测参考**：首轮按需加载后常驻内存由早期约 `670 MB` 明显回落；第三阶段深度优化后，同一运行环境下进程私有提交内存（Private / VMS）由 **`691.3 MB` 进一步降至 `160.5 MB`（-76.8%）**，常驻线程数由 **`59` 降至 `46`**，收起态 3 秒采样总体 CPU 由 **`19.3%` 单核降至 `5.21%` 单核（用户态 CPU -91%）**，周期性读 I/O 减少 **95%**（实际数值随字体、页面、实时字幕、词典、播放器和驱动而异）。

## 网络与隐私

| 功能 | 可能访问的资源 |
| --- | --- |
| 天气 | Open-Meteo 或用户配置的 OpenWeather |
| 股票 | 腾讯财经公开接口 |
| 歌词 | 网易云公开歌词接口 |
| 翻译 | 用户配置的翻译 API |
| 实时字幕模型 | Hugging Face / hf-mirror |
| Clash | 本机 Mihomo HTTP 或命名管道控制接口 |

- 网易云播放信息来自本机日志。
- QQ / 微信提醒来自 Windows 通知和窗口闪烁事件。
- Wisland 不会主动上传聊天记录、剪贴板历史或本地贴纸。

## 常见问题

### 双击 `wisland.vbs` 没反应，或提示缺少 PySide6

运行 `setup.bat`。不要只在全局 Python 中执行 `pip install`。仍然失败时，可删除 `.venv` 后重新运行安装。

日志位置：

```text
data\wisland.log
```

### 任务管理器仍显示 Python

重新运行一次 `setup.bat`，确认存在：

```text
.venv\Scripts\Wisland.exe
```

之后使用 `wisland.vbs` 或 `run.bat` 启动，不要直接运行 `pythonw.exe run.pyw`。

### 没有显示正在播放

- 网易云音乐默认通过本地日志读取。
- QQ 音乐需要在设置中启用 SMTC / 系统媒体控制。
- 浏览器媒体是否可用取决于浏览器和网页是否注册系统媒体会话。

### 没有歌词

- 确认 `media.lyrics` 为 `true`。
- 部分歌曲没有可用歌词或翻译。
- 网络不可用时不会获取在线歌词。

### Clash 按钮没有反应

- 确认 Clash Verge Rev 已开启全局快捷键。
- 检查 `clash.config_dir` 是否指向正确的配置目录。
- 节点切换还需要 Mihomo 控制器和 secret 可被读取。

### 亮度调节无效

部分外接显示器需要在显示器菜单中开启 DDC/CI；不支持时可在设置中指定 Twinkle Tray。

### 实时字幕第一次启动较慢

模型和重型依赖采用按需加载。第一次使用需要下载模型并初始化识别器，之后会更快。

## 项目结构

```text
wisland/
├─ Wisland.exe              # 独立桌面启动器（无控制台窗口）
├─ wisland.ico              # 应用与托盘图标
├─ run.pyw                  # 程序入口
├─ wisland.vbs              # 兼容启动脚本
├─ run.bat                  # 启动 / 重启 / 调试
├─ setup.bat                # 一键安装
├─ config.example.json      # 配置示例
├─ march7stickers/          # 默认贴纸目录
├─ screenshots/             # 当前版本截图
├─ docs/                    # 其他 README 图片
├─ scripts/                 # 模型与辅助脚本
├─ tests/                   # 单元测试
└─ wisland/
   ├─ app.py
   ├─ core/                 # 配置、重启辅助与后台任务
   ├─ services/             # 音频、媒体、消息、天气、Clash 等
   ├─ live/                 # 实时字幕流水线
   ├─ learn/                # 查词、单词本、Anki
   └─ ui/                   # 灵动岛、页面、设置和组件
```

## 开发

```bash
git clone https://github.com/MomoCyann/wisland.git
cd wisland
setup.bat
run.bat /d
```

提交前建议至少运行：

```bash
.venv\Scripts\python.exe -m compileall wisland
.venv\Scripts\python.exe -X utf8 -m unittest tests.test_netease_liked tests.test_netease_fm_and_mode -v
```

本项目目前以 Windows API、Core Audio、WinRT 和 PySide6 为核心，不支持 Linux / macOS。

## 致谢

- 原项目：[AsamiAkito/wisland](https://github.com/AsamiAkito/wisland)
- 实时字幕与单词本流水线移植自：[YishengTranslator-White](https://github.com/kayson-39/YishengTranslator-White)
- Clash Verge Rev：[clash-verge-rev/clash-verge-rev](https://github.com/clash-verge-rev/clash-verge-rev)

## License 与素材说明

程序代码采用 [MIT License](LICENSE)。

仓库不附带三月七或其他第三方角色贴纸图片。用户自行添加的图片不因程序代码采用 MIT License 而自动获得 MIT 授权，请确保素材拥有合法使用与分发许可。
