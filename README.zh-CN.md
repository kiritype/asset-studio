# Asset Studio

[English](README.md) · [한국어](README.ko.md) · [日本語](README.ja.md) · 简体中文

**[使用手册(英文·韩文)](https://kiritype.github.io/asset-studio/)** — 按画面配图讲解用法。

> 本文档为机器翻译。如有错误欢迎指正。

Asset Studio 是一个本地 Web 应用，用 [ComfyUI](https://github.com/comfyanonymous/ComfyUI) 制作风格
一致的角色图像。你可以把提示词作为可复用的片段(服装、表情·动作、构图、画师标签、质量标签)来管理，
一次生成所需的全部组合并审核结果，再用通过审核的图像为每个角色训练 LoRA。应用在你自己的电脑上运行，
并与你自己的 ComfyUI 通信。

主要功能:

- **提示词编辑**: 作品 › 角色 › 服装套装、表情·动作、构图、画师·通用标签。片段可以是全局、作品共用或
  角色专属，并标记为 Anima 用、SDXL/Illustrious 用或通用。输入时有 Danbooru 标签自动补全。
- **任务**: 选择角色、服装和表情·动作后，应用会计算张数并加入队列。支持 Anima 和 SDXL/Illustrious
  两种图。
- **图库**: 将图像标记为通过/未通过，按作品、角色、服装、表情或模型筛选，用新种子重新生成，并将通过
  的图像导出为 ZIP。
- **实验室**: 用多个种子或某一个设置值(CFG、步数、采样器、调度器、CLIP skip、LoRA 强度)生成同一
  提示词，并排或用滑块对比结果。
- **图像工具**: 上传图像或从图库导入，读取制作信息(Asset Studio 记录、ComfyUI 图、A1111 parameters、
  EXIF)，进行 WD14 标签分析、背景透明化、放大、重绘面部和手部(细节修复)、用可绘制的遮罩进行遮挡处理，
  以及转换为 WebP。
- **LoRA**: 用通过审核的图像创建数据集、修改标注，用 [anima_lora](https://github.com/sorryhyun/anima_lora)
  训练，注册结果后在生成该角色时自动应用。

图像以嵌入了 ComfyUI `prompt` 和 `workflow` 的 PNG 保存，因此可以在 ComfyUI 中把任何结果作为工作流
打开。

界面支持韩语、英语、日语和简体中文(**设置 › 常规**)，并可选择浅色、深色或跟随系统的主题。日语和中文
为机器翻译，欢迎指正。

## 环境要求

- Windows 10 或 11。启动脚本和进程管理仅支持 Windows。
- NVIDIA GPU。在 RTX 4090(24GB)上开发；LoRA 训练需要大显存 GPU。
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI)，已在 0.38.0 上验证。
  [Stability Matrix](https://github.com/LykosAI/StabilityMatrix)、便携版或 git clone 均可。
- 带 [Pillow](https://pypi.org/project/pillow/) 的 Python 3.12 或更高版本。ComfyUI 自带的 Python 已有
  Pillow，可以直接使用。
- 用于安装和更新的 [Git](https://git-scm.com/)。

## 安装

1. 安装 ComfyUI 和生成用模型(见[依赖](#依赖))。先启动一次 ComfyUI，确认 http://127.0.0.1:8188 能打开。
2. 获取 Asset Studio:

   ```bat
   git clone https://github.com/kiritype/asset-studio.git
   cd asset-studio
   ```

3. 指定启动所用的 Python。在 `launch.bat` 旁边新建 `launch.local.bat`，写一行指向 `pythonw.exe`(不弹出
   控制台)，例如 ComfyUI 的 Python:

   ```bat
   set "STUDIO_PYTHON=C:\path\to\ComfyUI\venv\Scripts\pythonw.exe"
   ```

   没有此文件时使用 `PATH` 中的 `pythonw`。
4. 可选功能需要 ComfyUI 自定义节点和模型。`tools/install_comfy_nodes.py` 会按[已验证版本](#已验证版本)
   安装自定义节点，并把 Asset Studio 的节点包链接到 ComfyUI。请用 ComfyUI 的 Python 运行(便携版为
   `python_embeded\python.exe`)；只输入 `python` 可能会打开 Microsoft Store。它会自动找到正在运行的 ComfyUI 及其 Python，在加上 `--yes` 之前只显示计划:

   ```bat
   C:\path\to\ComfyUI\venv\Scripts\python.exe tools\install_comfy_nodes.py
   C:\path\to\ComfyUI\venv\Scripts\python.exe tools\install_comfy_nodes.py --yes
   ```

   用 `--only tagger,alpha` 选择功能(`autocomplete`、`tagger`、`alpha`、`detect`、`detailer`)；ComfyUI
   未运行或装有多个时，用 `--comfy` 和 `--python` 指定。已安装的节点不会被改动。完成后重启 ComfyUI，
   再放好[依赖](#依赖)中的模型。

## 启动与停止

- `launch.bat`: 启动 Asset Studio(若未运行)并在浏览器中打开 http://127.0.0.1:8195 。
- `stop.bat` 停止，`restart.bat` 重启。有图像正在生成或等待，或 LoRA 正在训练时，会先询问。
- 生成和图像工具需要 ComfyUI 正在运行。页面顶部显示连接状态。在**设置**中也可以启动、停止、重启由
  Asset Studio 自己启动的 ComfyUI(需要填写 ComfyUI 文件夹和 Python)。

服务器只接受来自 127.0.0.1 的连接。你创建的一切都保存在 Asset Studio 文件夹的 `data/` 和 `outputs/` 中。

## 入门

1. **设置**
   - **常规**: 语言、主题、标签自动补全。
   - **ComfyUI 连接信息**: 确认地址(默认 `http://127.0.0.1:8188`)。若要让 Asset Studio 启动/停止
     ComfyUI 并查找 Danbooru 标签数据，还需填写 ComfyUI 文件夹和 Python。点击**自动查找**会找出本机的
     ComfyUI(正在运行的、Stability Matrix、便携版、git 安装)并自动填写。
2. **提示词编辑**: 点击**导入示例**即可得到一个可直接试用的示例作品("Starlight Academy": 2 个角色、
   校服、5 个表情)。若要自己创建:
   1. 用 **+ 作品** 新建作品，再用 **+ 角色** 添加角色及其外貌提示词。
   2. 用 **+ 片段** 添加服装部位(手、上衣、下装、鞋或整套服装)、表情·动作、构图、画师标签以及通用
      正向/负向标签。
   3. 用 **+ 服装套装** 把服装部位组合成一套服装。
   4. 范围按钮(全局 / 作品共用 / 角色)决定谁可以使用该片段。代码相同时，角色专属片段优先于共用片段。
3. **任务**: 勾选角色、服装、表情·动作以及要加入的片段，选择模型和设置(Anima 或 SDXL·IL 标签页)，
   查看预览后加入队列。进度可在顶部的队列按钮中查看。
4. **图库**: 打开图像并标记为通过(P)或未通过(F)。通过的图像用于导出和训练。
5. **LoRA**: 选择角色，用其图像创建数据集并训练，注册满意的轮次并开启**自动应用**，此后该角色的新任务
   就会使用它。

### 图像工具一览

- **WebP 转换**: 质量、无损、调整尺寸。"保留元数据"默认关闭，分享的文件不会带有提示词和工作流。
- **标签分析**: 将 WD14 标签与图像的提示词对比(一致、仅在图中识别、图中未识别)。可设置排除的标签，
  复制标签或发送到实验室，也可将所选图片的标签导出为 TXT(LoRA 标注)或 JSON。所选图片可打包为 ZIP 下载。
- **后期处理**: 放大、细节修复。放大会丢失透明度，因此请在放大之后再做背景透明化。
- **遮挡处理**: (1) 需要时检测部位，(2) 用画笔和橡皮擦修改红色遮罩(可撤销)，(3) 以马赛克、模糊或纯色
  应用，可选遮罩扩展和边缘柔化。
- **背景透明化**: (1) 自动分离背景，(2) 修改要保留的部分(蓝色遮罩)并用结果预览确认，(3) 应用。
- **局部重绘**: 涂抹要重绘的部分(绿色遮罩)，用该图像自己的模型、LoRA 和记录的提示词(可修改)只重绘
  那部分。未涂抹的部分保留原始像素。仅适用于 Asset Studio 生成的图像。
- 原图不会改变。作业图片(作品/角色/服装文件夹)的结果会作为新候选保存在原图旁边，在图库中设为通过即可
  成为该表情的采用图。其他结果保存在 `outputs/_tools/`。

## 依赖

以下内容均不随附，请从各自页面下载并放到 ComfyUI 读取的文件夹中。模型文件夹指 ComfyUI `models/` 的子
文件夹(或 Stability Matrix 的共享模型文件夹)。

### 生成(必需)

| 项目 | 获取地址 | ComfyUI 文件夹 |
|---|---|---|
| Anima 扩散模型，例如 `anima-aesthetic-v1.1.safetensors` 或 `anima-base-v1.0.safetensors` | [circlestone-labs/Anima](https://huggingface.co/circlestone-labs/Anima/tree/main/split_files/diffusion_models)(也在 [Civitai](https://civitai.com/models/2458426)) | `diffusion_models` |
| 文本编码器 `qwen_3_06b_base.safetensors` | [circlestone-labs/Anima](https://huggingface.co/circlestone-labs/Anima/tree/main/split_files/text_encoders) | `text_encoders` |
| VAE `qwen_image_vae.safetensors` | [circlestone-labs/Anima](https://huggingface.co/circlestone-labs/Anima/tree/main/split_files/vae) | `vae` |

带有自己文本编码器的检查点形式 Anima 微调模型(例如 [MiaoMiao Harem](https://civitai.com/models/934764))
也可以使用：在生成设置中选择该检查点及其文本编码器。SDXL/Illustrious 可使用 `checkpoints` 中的任意
Illustrious 或 NoobAI 检查点。

提示：把 Anima 文件放在 `anima` 子文件夹、SDXL 文件放在 `sdxl` 子文件夹(例如 `loras/anima/`)，Asset
Studio 就能识别每个文件的模型系列并只显示匹配的文件。`tools/organize_models.py` 可以帮你移动现有文件
(默认只预览)。

### 可选功能

| 功能 | 自定义节点 | 模型 |
|---|---|---|
| 标签自动补全和标签检查 | [ComfyUI-EasyUseAnima](https://github.com/n0va39/ComfyUI-EasyUseAnima)(只读取其 Danbooru 标签文件) | — |
| WD14 标签分析(图像工具) | [ComfyUI-WD14-Tagger](https://github.com/pythongosssss/ComfyUI-WD14-Tagger) | 首次使用时由节点下载，例如 [wd-eva02-large-tagger-v3](https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3) |
| 背景透明化 | [ComfyUI_essentials](https://github.com/cubiq/ComfyUI_essentials)(其 requirements 会安装 `rembg`)、Asset Studio 节点包 | `isnet-anime` 首次使用时由 rembg 下载 |
| 遮挡部位检测 | Asset Studio 节点包、ComfyUI Python 中的 `ultralytics`(由 Impact Subpack 安装) | [Anime NSFW Detection](https://civitai.com/models/1313556) 的 `ntd11_anime_nsfw_segm_v5-variant1.pt` → `ultralytics/segm` |
| 人物遮罩(背景透明化的替代方式) | Asset Studio 节点包、`ultralytics` | [Bingsu/adetailer](https://huggingface.co/Bingsu/adetailer) 的 `person_yolov8n-seg.pt` → `ultralytics/segm` |
| 放大 | Asset Studio 节点包 | 例如 [2x-AnimeSharpV4](https://huggingface.co/Kim2091/2x-AnimeSharpV4)、[4x-UltraSharp](https://huggingface.co/Kim2091/UltraSharp) → `upscale_models` |
| 细节修复(脸、眼睛、嘴、手) | [ComfyUI-Impact-Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack)、[ComfyUI-Impact-Subpack](https://github.com/ltdrdata/ComfyUI-Impact-Subpack)、Asset Studio 节点包 | [Bingsu/adetailer](https://huggingface.co/Bingsu/adetailer) 的 `face_yolov8m.pt`、`hand_yolov8s.pt` → `ultralytics/bbox`；[Eye Detailer/Segmentation](https://civitai.com/models/334668) 的 `PitEyeDetailer-v2-seg.pt` → `ultralytics/segm`；[sam_vit_b_01ec64.pth](https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth) → `sams` |
| 视觉模型自动审核 | 本地 OpenAI 兼容服务器(例如 [LM Studio](https://lmstudio.ai/)) | 任选一个视觉语言模型 |
| LoRA 训练 | — | 见 [LoRA 训练](#lora-训练) |

Civitai 上的检测模型是 ZIP 文件，请解压出 `.pt` 文件放到表中所示文件夹。Asset Studio 节点包就是在
[安装](#安装)第 4 步中链接的 `comfy_nodes/asset_studio_nodes` 文件夹。遮挡处理本身(马赛克·模糊·纯色)不需要
节点，只有自动检测需要。

### 已验证版本

节点安装脚本会安装这些版本；其他版本也许可用，但未经验证。

| 组件 | 版本 | 提交 | 许可证 |
|---|---|---|---|
| ComfyUI | 0.38.0 | — | GPL-3.0 |
| [ComfyUI-EasyUseAnima](https://github.com/n0va39/ComfyUI-EasyUseAnima) | 1.1.1 | `66ae8b6` | MIT |
| [ComfyUI-WD14-Tagger](https://github.com/pythongosssss/ComfyUI-WD14-Tagger) | 1.0.1 | `9e0a6e7` | MIT |
| [ComfyUI_essentials](https://github.com/cubiq/ComfyUI_essentials) | 1.1.0 | `9d9f4be` | MIT |
| [ComfyUI-Impact-Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) | 8.28.3 | `429d015` | GPL-3.0 |
| [ComfyUI-Impact-Subpack](https://github.com/ltdrdata/ComfyUI-Impact-Subpack) | 1.3.5 | `50c7b71` | AGPL-3.0 |
| Python 包(由节点安装) | ultralytics 8.4.150, rembg 2.0.85, onnxruntime 1.30.0 | — | AGPL-3.0 · MIT · MIT |

## LoRA 训练

训练会在独立的 Python 环境中运行 [anima_lora](https://github.com/sorryhyun/anima_lora)，需要单独安装:

1. 安装 [uv](https://docs.astral.sh/uv/)，把 anima_lora 克隆到 Asset Studio 文件夹内的
   `vendor/anima_lora`。Asset Studio 已用提交 `69ff962` 验证，该提交还需要配套的 `anime_tools`(v0.7.5)
   位于 `vendor/anime_tools`:

   ```bat
   git clone https://github.com/sorryhyun/anime_tools.git vendor\anime_tools
   git -C vendor\anime_tools checkout v0.7.5
   git clone https://github.com/sorryhyun/anima_lora.git vendor\anima_lora
   cd vendor\anima_lora
   git checkout 69ff962
   uv sync
   ```

   若 `uv sync` 还需要其他东西，请按 anima_lora 自己的 [Setup](https://github.com/sorryhyun/anima_lora#setup)
   操作(它使用 Python 3.13 和 CUDA 版 PyTorch，需要较新的 NVIDIA 驱动)。
2. 应用 Asset Studio 的小补丁，让预处理使用你指定的模型文件，而不是 anima_lora 的 `models/` 文件夹:

   ```bat
   git apply ..\..\trainer\anima_lora\preprocess-model-paths.patch
   ```

3. 在**设置 › LoRA 训练**中填写:
   - **LoRA 保存文件夹**: ComfyUI 的 LoRA 文件夹(例如 `.../loras/anima`)。完成的轮次会复制到这里。
   - **官方 Anima base**: 官方 [Anima base](https://huggingface.co/circlestone-labs/Anima/tree/main/split_files)
     的文件(`anima-base-v1.0.safetensors`、`qwen_3_06b_base.safetensors`、`qwen_image_vae.safetensors`)。
   - **生成模型**(可选): 改用某个 Anima 微调模型进行训练。

   每个路径都会显示是否找到了文件。

每次训练前，Asset Studio 会自动写入训练工具的预设(`vendor/anima_lora/configs/presets.toml` 中标有
`asset-studio` 的部分)和方式文件。LoRA 训练期间不会生成新图像，队列中的图像会在训练结束后继续生成。

## 设置

所有设置都在**设置**页面中修改，并保存在服务器的 `data/settings/` 中，因此同一台电脑上的所有浏览器看到
的设置相同。

| 项目 | 内容 |
|---|---|
| 常规 | 语言、主题、标签自动补全 |
| ComfyUI 连接信息 | ComfyUI 的地址、文件夹和 Python |
| Danbooru 标签数据 | 标签文件不在 ComfyUI-EasyUseAnima 中时的文件夹 |
| LoRA 训练 | 训练工具文件夹、其 Python、LoRA 保存文件夹、训练用模型 |
| GPU 使用 / GPU 等待条件 | 其他程序占用 GPU 时等待(剩余显存、程序名) |
| VLM 服务器 / VLM 审核 | 可选的自动审核：服务器地址、模型、加载和卸载模型的命令(例如 LM Studio 的 `lms load` / `lms unload` / `lms ps`)，以及开关 |

`config/models.example.json`(复制为 `data/settings/models.json`)用于指定共享模型文件夹和手动模型系列，
大多数情况下不需要。

## 数据

- `data/` 存放提示词库、审核结果、数据集、LoRA 记录和设置；`outputs/` 存放生成和处理后的图像。请备份
  这两个文件夹，它们都不包含在 git 仓库中。
- 删除提示词会把它移到库的回收站，可从那里恢复。
- `outputs/_lab/` 存放实验室图像，`outputs/_tools/` 存放图像工具的结果；图库会显示 `outputs/` 下的所有
  图像。

## 故障排除

- **无法连接 ComfyUI**: 启动 ComfyUI，并检查设置中的地址。
- **模型或节点"不在列表中"**: 安装后重启 ComfyUI 并刷新页面。图像工具会显示缺少的节点名称。
- **队列已暂停**: 任务失败时队列会暂停，以免丢失任何内容。请在队列面板中查看错误，修复后继续。
- **日志**: `logs/studio.log`(服务器)、`logs/launcher.log`(启动)、`logs/lora/<run>/trainer.log`(训练)。

## 许可证

Asset Studio 以 [MIT 许可证](LICENSE)发布。不包含任何模型权重或他人的自定义节点；所用项目及其许可证见
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

### 关于 Anima 模型和你训练的 LoRA

Anima 由 CircleStone Labs 以
[CircleStone Labs Non-Commercial License](https://huggingface.co/circlestone-labs/Anima/blob/main/LICENSE.md)
发布，且由于基于 NVIDIA Cosmos-Predict2，也适用 NVIDIA Open Model License。概括如下(确切条款请阅读
许可证原文):

- 由 Anima 权重制作的 LoRA、微调和合并模型(包括用 Asset Studio 训练的 LoRA 和 Anima 微调模型)属于该
  许可证中的**衍生作品(Derivative)**，适用其非商业条款。
- 分享此类 LoRA 时，需说明它修改了 CircleStone 模型，并附上许可证要求的声明。
- 个人可以出售自己制作的衍生作品；以付费服务提供或嵌入付费产品则需要 CircleStone Labs 的单独许可。
- CircleStone Labs 不主张对你生成的图像拥有所有权。

你使用的其他模型(放大模型、检测模型、检查点)遵循各自下载页面上的许可证；例如 2x-AnimeSharpV4 和
4x-UltraSharp 放大模型为 CC BY-NC-SA 4.0。

## 参与贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。
