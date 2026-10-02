# Asset Studio

[English](README.md) · [한국어](README.ko.md) · 日本語 · [简体中文](README.zh-CN.md)

**[ユーザーマニュアル(英語・韓国語)](https://kiritype.github.io/asset-studio/)** — 画面ごとの使い方をスクリーンショット付きで説明します。

> この文書は機械翻訳です。誤りがあればお知らせください。

Asset Studio は [ComfyUI](https://github.com/comfyanonymous/ComfyUI) で一貫したキャラクター画像を作る
ためのローカル Web アプリです。プロンプトを再利用できるピース(衣装、表情・動作、構図、作者タグ、品質
タグ)として管理し、必要な組み合わせをまとめて生成してレビューし、合格した画像からキャラクターごとの
LoRA を学習します。自分の PC で動き、自分の ComfyUI と通信します。

主な機能:

- **プロンプト編集**: 作品 › キャラクター › 衣装セット、表情・動作、構図、作者・共通タグ。ピースは
  グローバル、作品共通、キャラクター専用に分けられ、Anima 用・SDXL/Illustrious 用・共通として表示
  できます。入力中は Danbooru タグの自動補完が使えます。
- **ジョブ**: キャラクター、衣装、表情・動作を選ぶと枚数を計算してキューに入れます。Anima と
  SDXL/Illustrious のグラフに対応します。
- **ギャラリー**: 画像を合格/不合格でレビューし、作品・キャラクター・衣装・表情・モデルで絞り込み、
  新しいシードで再生成し、合格画像を ZIP で書き出します。
- **ラボ**: 1つのプロンプトを複数のシードや1つの設定値(CFG、ステップ、サンプラー、スケジューラー、
  CLIP skip、LoRA 強度)で生成し、並べて表示またはスライダーで比較します。
- **画像ツール**: 画像をアップロードするかギャラリーから取り込み、制作情報(Asset Studio の記録、
  ComfyUI グラフ、A1111 parameters、EXIF)を読み、WD14 タグ解析、背景透過、アップスケール、顔・手の
  描き直し(ディテイラー)、塗って直せるマスクでのモザイク処理、WebP 変換を行います。
- **LoRA**: 合格画像からデータセットを作り、キャプションを直して
  [anima_lora](https://github.com/sorryhyun/anima_lora) で学習し、結果を登録してそのキャラクターの生成
  時に自動で適用します。

画像は ComfyUI の `prompt` と `workflow` を埋め込んだ PNG で保存されるため、ComfyUI で結果をワーク
フローとして開けます。

画面の言語は韓国語、英語、日本語、簡体字中国語に対応し(**設定 › 一般**)、ライト・ダーク・システムの
テーマを選べます。日本語と中国語は機械翻訳です。修正を歓迎します。

## 動作環境

- Windows 10 または 11。起動スクリプトとプロセス管理は Windows 専用です。
- NVIDIA GPU。RTX 4090(24GB)で開発しました。LoRA 学習には大きな GPU が必要です。
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI)、0.38.0 で確認しました。
  [Stability Matrix](https://github.com/LykosAI/StabilityMatrix)、ポータブル版、git clone のどれでも動きます。
- [Pillow](https://pypi.org/project/pillow/) を含む Python 3.12 以降。ComfyUI の Python には Pillow が
  あるので、それを使えます。
- インストールと更新用の [Git](https://git-scm.com/)。

## インストール

1. ComfyUI と生成用モデルをインストールします([依存関係](#依存関係)を参照)。ComfyUI を一度起動し、
   http://127.0.0.1:8188 が開くことを確認します。
2. Asset Studio を取得します。

   ```bat
   git clone https://github.com/kiritype/asset-studio.git
   cd asset-studio
   ```

3. 起動に使う Python を指定します。`launch.bat` の隣に `launch.local.bat` を作り、`pythonw.exe`
   (コンソールを開かない)を指す1行を書きます。例として ComfyUI の Python:

   ```bat
   set "STUDIO_PYTHON=C:\path\to\ComfyUI\venv\Scripts\pythonw.exe"
   ```

   このファイルがなければ `PATH` の `pythonw` を使います。
4. 追加機能には ComfyUI のカスタムノードとモデルが必要です。`tools/install_comfy_nodes.py` が
   カスタムノードを[確認済みバージョン](#確認済みバージョン)で入れ、Asset Studio のノードパックを ComfyUI に
   リンクします。どの Python 3 で実行してもかまいません(ComfyUI の Python でも可)。起動中の ComfyUI
   とその Python を自動で見つけ、`--yes` を付けるまでは計画だけを表示します。

   ```bat
   python tools\install_comfy_nodes.py
   python tools\install_comfy_nodes.py --yes
   ```

   `--only tagger,alpha` で機能を選び(`autocomplete`、`tagger`、`alpha`、`detect`、`detailer`)、
   ComfyUI が起動していないときや複数あるときは `--comfy` と `--python` で指定します。すでに入っている
   ノードは変更しません。終わったら ComfyUI を再起動し、[依存関係](#依存関係)のモデルを置いてください。

## 起動と終了

- `launch.bat`: Asset Studio を起動し(起動していなければ)、ブラウザーで http://127.0.0.1:8195 を
  開きます。
- `stop.bat` で終了、`restart.bat` で再起動します。画像の生成中・待機中や LoRA 学習中は先に確認します。
- 生成と画像ツールには ComfyUI の起動が必要です。画面上部に接続状態が表示されます。**設定**から、
  Asset Studio 自身が起動した ComfyUI を起動・終了・再起動することもできます(ComfyUI フォルダーと
  Python の入力が必要です)。

サーバーは 127.0.0.1 からの接続のみ受け付けます。作ったものはすべて Asset Studio フォルダーの
`data/` と `outputs/` に保存されます。

## はじめに

1. **設定**
   - **一般**: 言語、テーマ、タグの自動補完。
   - **ComfyUI 接続情報**: アドレスを確認します(既定 `http://127.0.0.1:8188`)。Asset Studio から
     ComfyUI を起動・終了したり Danbooru タグデータを探させたりするには、ComfyUI フォルダーと Python
     も入力します。**自動で探す**を押すと、この PC の ComfyUI(起動中のもの、Stability Matrix、
     ポータブル版、git インストール)を探して入力します。
2. **プロンプト編集**: **サンプルを読み込む**を押すと、すぐに試せるサンプル作品(「Starlight Academy」:
   キャラクター2人、制服、表情5つ)ができます。自分で作る場合:
   1. **+ 作品**で作品を作り、**+ キャラクター**で外見プロンプトとともにキャラクターを追加します。
   2. **+ ピース**で衣装の部位(手、トップス、ボトムス、靴、または衣装全体)、表情・動作、構図、作者
      タグ、共通のポジティブ・ネガティブタグを追加します。
   3. **+ 衣装セット**で衣装の部位をまとめて衣装を作ります。
   4. 範囲ボタン(グローバル / 作品共通 / キャラクター)で、誰がそのピースを使うかを決めます。同じ
      コードならキャラクター専用のピースが共通のピースより優先されます。
3. **ジョブ**: キャラクター、衣装、表情・動作と追加するピースをチェックし、モデルと設定(Anima または
   SDXL·IL タブ)を選び、プレビューを確認してキューに入れます。進行状況は上部のキューボタンで見られます。
4. **ギャラリー**: 画像を開いて合格(P)または不合格(F)を付けます。合格画像を書き出しや学習に使います。
5. **LoRA**: キャラクターを選び、その画像からデータセットを作って学習します。気に入ったエポックを登録し
   **自動適用**をオンにすると、そのキャラクターの新しいジョブに使われます。

### 画像ツールの概要

- **WebP 変換**: 品質、ロスレス、サイズ変更。「メタデータを保持」は既定でオフなので、共有するファイルに
  プロンプトやワークフローは残りません。
- **タグ解析**: WD14 タグを画像のプロンプトと比較します(一致、画像からのみ検出、画像から読み取れず)。
  除外するタグを決めておき、タグのコピーやラボへの送信、選んだ画像のタグを TXT(LoRA キャプション)や
  JSON で書き出せます。選んだ画像は ZIP でまとめてダウンロードできます。
- **後処理**: アップスケール、ディテイラー。アップスケールすると透過が失われるので、背景透過は
  アップスケールの後に行ってください。
- **モザイク処理**: (1) 必要なら部位を検出し、(2) 赤いマスクをブラシと消しゴムで直し(元に戻すも可)、
  (3) モザイク、ぼかし、単色のいずれかで適用します。マスクの拡張と境界のぼかしも選べます。
- **背景透過**: (1) 背景を自動で分離し、(2) 残す部分(青いマスク)を直して結果プレビューで確認し、
  (3) 適用します。
- **インペイント**: 描き直す部分(緑のマスク)を塗ると、その画像のモデル・LoRA と記録されたプロンプト
  (編集可)でその部分だけを描き直します。塗っていない部分は元のピクセルのまま残ります。Asset Studio で
  作った画像にだけ使えます。
- 原本は変わりません。作業画像(作品/キャラクター/衣装フォルダー)の結果は元画像の隣に新しい候補として
  保存され、ギャラリーで合格にするとその表情の採用画像になります。それ以外の結果は `outputs/_tools/` に
  保存されます。

## 依存関係

以下は同梱されていません。各ページから入手し、ComfyUI が参照するフォルダーに置いてください。モデル
フォルダーは ComfyUI の `models/` のサブフォルダー(または Stability Matrix の共有モデルフォルダー)です。

### 生成(必須)

| 項目 | 入手先 | ComfyUI フォルダー |
|---|---|---|
| Anima 拡散モデル、例: `anima-aesthetic-v1.1.safetensors` または `anima-base-v1.0.safetensors` | [circlestone-labs/Anima](https://huggingface.co/circlestone-labs/Anima/tree/main/split_files/diffusion_models)([Civitai](https://civitai.com/models/2458426) にもあり) | `diffusion_models` |
| テキストエンコーダー `qwen_3_06b_base.safetensors` | [circlestone-labs/Anima](https://huggingface.co/circlestone-labs/Anima/tree/main/split_files/text_encoders) | `text_encoders` |
| VAE `qwen_image_vae.safetensors` | [circlestone-labs/Anima](https://huggingface.co/circlestone-labs/Anima/tree/main/split_files/vae) | `vae` |

独自のテキストエンコーダーを持つチェックポイント形式の Anima ファインチューン(例:
[MiaoMiao Harem](https://civitai.com/models/934764))も使えます。生成設定でチェックポイントとその
テキストエンコーダーを選んでください。SDXL/Illustrious は `checkpoints` にある Illustrious または
NoobAI のチェックポイントで動きます。

ヒント: Anima のファイルは `anima` サブフォルダー、SDXL のファイルは `sdxl` サブフォルダーに置くと
(例: `loras/anima/`)、Asset Studio がファイルごとのモデル系統を判別し、合うファイルだけを表示します。
`tools/organize_models.py` で既存ファイルを移動できます(既定はプレビューのみ)。

### 追加機能

| 機能 | カスタムノード | モデル |
|---|---|---|
| タグの自動補完・タグ確認 | [ComfyUI-EasyUseAnima](https://github.com/n0va39/ComfyUI-EasyUseAnima)(Danbooru タグファイルのみ読み込み) | — |
| WD14 タグ解析(画像ツール) | [ComfyUI-WD14-Tagger](https://github.com/pythongosssss/ComfyUI-WD14-Tagger) | 初回使用時にノードがダウンロード、例: [wd-eva02-large-tagger-v3](https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3) |
| 背景透過 | [ComfyUI_essentials](https://github.com/cubiq/ComfyUI_essentials)(requirements で `rembg` を導入)、Asset Studio のノードパック | `isnet-anime` は初回使用時に rembg がダウンロード |
| 隠す部位の検出 | Asset Studio のノードパック、ComfyUI の Python の `ultralytics`(Impact Subpack が導入) | [Anime NSFW Detection](https://civitai.com/models/1313556) の `ntd11_anime_nsfw_segm_v5-variant1.pt` → `ultralytics/segm` |
| 人物マスク(背景透過の代替) | Asset Studio のノードパック、`ultralytics` | [Bingsu/adetailer](https://huggingface.co/Bingsu/adetailer) の `person_yolov8n-seg.pt` → `ultralytics/segm` |
| アップスケール | Asset Studio のノードパック | 例: [2x-AnimeSharpV4](https://huggingface.co/Kim2091/2x-AnimeSharpV4)、[4x-UltraSharp](https://huggingface.co/Kim2091/UltraSharp) → `upscale_models` |
| ディテイラー(顔、目、口、手) | [ComfyUI-Impact-Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack)、[ComfyUI-Impact-Subpack](https://github.com/ltdrdata/ComfyUI-Impact-Subpack)、Asset Studio のノードパック | [Bingsu/adetailer](https://huggingface.co/Bingsu/adetailer) の `face_yolov8m.pt`、`hand_yolov8s.pt` → `ultralytics/bbox`; [Eye Detailer/Segmentation](https://civitai.com/models/334668) の `PitEyeDetailer-v2-seg.pt` → `ultralytics/segm`; [sam_vit_b_01ec64.pth](https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth) → `sams` |
| ビジョンモデルによる自動レビュー | ローカルの OpenAI 互換サーバー(例: [LM Studio](https://lmstudio.ai/)) | 任意のビジョン言語モデル |
| LoRA 学習 | — | [LoRA 学習](#lora-学習)を参照 |

Civitai の検出モデルは ZIP ファイルです。`.pt` ファイルを展開して表のフォルダーに置いてください。
Asset Studio のノードパックは[インストール](#インストール)の手順4でリンクした
`comfy_nodes/asset_studio_nodes` フォルダーです。モザイク処理そのもの(モザイク・ぼかし・単色)にノードは不要で、
自動検出にのみ必要です。

### 確認済みバージョン

ノードのインストールスクリプトはこのバージョンを入れます。ほかのバージョンでも動く可能性はありますが、確認していません。

| 構成要素 | バージョン | コミット | ライセンス |
|---|---|---|---|
| ComfyUI | 0.38.0 | — | GPL-3.0 |
| [ComfyUI-EasyUseAnima](https://github.com/n0va39/ComfyUI-EasyUseAnima) | 1.1.1 | `66ae8b6` | MIT |
| [ComfyUI-WD14-Tagger](https://github.com/pythongosssss/ComfyUI-WD14-Tagger) | 1.0.1 | `9e0a6e7` | MIT |
| [ComfyUI_essentials](https://github.com/cubiq/ComfyUI_essentials) | 1.1.0 | `9d9f4be` | MIT |
| [ComfyUI-Impact-Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) | 8.28.3 | `429d015` | GPL-3.0 |
| [ComfyUI-Impact-Subpack](https://github.com/ltdrdata/ComfyUI-Impact-Subpack) | 1.3.5 | `50c7b71` | AGPL-3.0 |
| Python パッケージ(ノードが導入) | ultralytics 8.4.150, rembg 2.0.85, onnxruntime 1.30.0 | — | AGPL-3.0 · MIT · MIT |

## LoRA 学習

学習は [anima_lora](https://github.com/sorryhyun/anima_lora) を専用の Python 環境で実行します。別途
インストールが必要です。

1. [uv](https://docs.astral.sh/uv/) をインストールし、anima_lora を Asset Studio フォルダー内の
   `vendor/anima_lora` に取得します。Asset Studio はコミット `69ff962` で確認しました。

   ```bat
   git clone https://github.com/sorryhyun/anima_lora.git vendor\anima_lora
   cd vendor\anima_lora
   git checkout 69ff962
   uv sync
   ```

   `uv sync` で足りないものがあれば anima_lora の
   [Setup](https://github.com/sorryhyun/anima_lora#setup) に従ってください(Python 3.13 と CUDA 版
   PyTorch を使うため、新しい NVIDIA ドライバーが必要です)。
2. Asset Studio の小さなパッチを適用します。前処理が anima_lora の `models/` フォルダーではなく指定した
   モデルファイルを使うようになります。

   ```bat
   git apply ..\..\trainer\anima_lora\preprocess-model-paths.patch
   ```

3. **設定 › LoRA 学習**で入力します。
   - **LoRA 保存フォルダー**: ComfyUI の LoRA フォルダー(例: `.../loras/anima`)。完了したエポックが
     ここにコピーされます。
   - **公式 Anima base**: 公式 [Anima base](https://huggingface.co/circlestone-labs/Anima/tree/main/split_files)
     のファイル(`anima-base-v1.0.safetensors`、`qwen_3_06b_base.safetensors`、
     `qwen_image_vae.safetensors`)。
   - **生成モデル**(任意): 代わりに学習に使う Anima ファインチューン。

   パスごとにファイルが見つかったかが表示されます。

Asset Studio は学習のたびに学習ツールのプリセット(`vendor/anima_lora/configs/presets.toml` の
`asset-studio` 部分)と方式ファイルを自動で書き込みます。LoRA 学習中は新しい画像を生成せず、待機中の
画像は学習後に続けて生成します。

## 設定

すべての設定は**設定**画面で変更し、サーバーの `data/settings/` に保存されるため、同じ PC のすべての
ブラウザーで同じ設定になります。

| 項目 | 内容 |
|---|---|
| 一般 | 言語、テーマ、タグの自動補完 |
| ComfyUI 接続情報 | ComfyUI のアドレス、フォルダー、Python |
| Danbooru タグデータ | タグファイルが ComfyUI-EasyUseAnima にない場合のフォルダー |
| LoRA 学習 | 学習ツールのフォルダー、その Python、LoRA 保存フォルダー、学習用モデル |
| GPU の使用 / GPU 待機条件 | 他のプログラムが GPU を使っている間は待機(空き VRAM、プログラム名) |
| VLM サーバー / VLM レビュー | 任意の自動レビュー: サーバーのアドレス、モデル、モデルを載せ降ろしするコマンド(例: LM Studio の `lms load` / `lms unload` / `lms ps`)、オン・オフ |

`config/models.example.json`(`data/settings/models.json` にコピー)は共有モデルフォルダーと手動の
モデル系統を指定します。多くの場合は不要です。

## データ

- `data/` にはプロンプトライブラリ、レビュー結果、データセット、LoRA の記録、設定があり、`outputs/`
  には生成・処理した画像があります。両方をバックアップしてください。どちらも git リポジトリには含まれ
  ません。
- プロンプトを削除するとライブラリのゴミ箱に移り、そこから復元できます。
- `outputs/_lab/` にはラボの画像、`outputs/_tools/` には画像ツールの結果があります。ギャラリーは
  `outputs/` 以下のすべての画像を表示します。

## トラブルシューティング

- **ComfyUI に接続できない**: ComfyUI を起動し、設定のアドレスを確認してください。
- **モデルやノードが「一覧にない」**: インストールしてから ComfyUI を再起動し、ページを再読み込みして
  ください。画像ツールは足りないノード名を表示します。
- **キューが一時停止**: ジョブが失敗すると、何も失われないようにキューが止まります。キューのパネルで
  エラーを読み、直してから再開してください。
- **ログ**: `logs/studio.log`(サーバー)、`logs/launcher.log`(起動)、`logs/lora/<run>/trainer.log`
  (学習)。

## ライセンス

Asset Studio は [MIT ライセンス](LICENSE)で公開しています。モデルの重みや他者のカスタムノードは含み
ません。使用しているプロジェクトとそのライセンスは [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
を参照してください。

### Anima モデルと自分で学習した LoRA について

Anima は CircleStone Labs が
[CircleStone Labs Non-Commercial License](https://huggingface.co/circlestone-labs/Anima/blob/main/LICENSE.md)
で公開しており、NVIDIA Cosmos-Predict2 をベースにしているため NVIDIA Open Model License も適用されます。
要約すると次のとおりです(正確な条件はライセンス原文を確認してください)。

- Anima の重みから作った LoRA、ファインチューン、マージモデルはそのライセンス上の**派生物
  (Derivative)**であり、非商用の条件に従います。Asset Studio で学習した LoRA や Anima のファイン
  チューンモデルも含まれます。
- そのような LoRA を共有するときは、CircleStone のモデルを改変したことと、ライセンスが求める表示を
  含めてください。
- 個人は自分で作った派生物を販売できます。有料サービスとして提供したり有料製品に組み込んだりするには
  CircleStone Labs の別ライセンスが必要です。
- 生成した画像について CircleStone Labs は所有権を主張しません。

その他のモデル(アップスケーラー、検出モデル、チェックポイント)はそれぞれの配布ページのライセンスに
従います。例えば 2x-AnimeSharpV4 と 4x-UltraSharp のアップスケーラーは CC BY-NC-SA 4.0 です。

## コントリビュート

[CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。
