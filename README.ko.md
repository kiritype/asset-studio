# Asset Studio

[English](README.md) · 한국어 · [日本語](README.ja.md) · [简体中文](README.zh-CN.md)

**[사용 설명서](https://kiritype.github.io/asset-studio/ko/)** — 화면별 사용법을 캡처와 함께 안내합니다.

Asset Studio는 [ComfyUI](https://github.com/comfyanonymous/ComfyUI)로 일관된 캐릭터 이미지를
만드는 로컬 웹 앱입니다. 프롬프트를 다시 쓸 수 있는 조각(의상, 감정·동작, 구도, 작가 태그, 품질
태그)으로 관리하고, 필요한 조합을 한 번에 생성해 검수한 뒤, 통과한 이미지로 캐릭터별 LoRA를
학습합니다. 내 PC에서 실행되며 내 ComfyUI와 통신합니다.

주요 기능:

- **프롬프트 수정**: 작품 › 캐릭터 › 의상 세트, 감정·동작, 구도, 작가·공통 태그. 조각은 전역, 작품
  공용, 캐릭터 전용으로 나눌 수 있고, Anima용·SDXL/Illustrious용·공용으로 표시합니다. 입력할 때
  Danbooru 태그 자동완성이 도와줍니다.
- **작업**: 캐릭터, 의상, 감정·동작을 고르면 장수를 계산해 대기열에 넣습니다. Anima와
  SDXL/Illustrious 그래프를 모두 지원합니다.
- **갤러리**: 이미지를 통과/실패로 검수하고, 작품·캐릭터·의상·감정·모델로 거르며, 새 시드로 다시
  생성하고, 통과한 이미지를 ZIP으로 내보냅니다.
- **실험실**: 한 프롬프트를 여러 시드나 한 가지 설정값(CFG, 스텝, 샘플러, 스케줄러, CLIP skip,
  LoRA 강도)으로 생성해 나란히 또는 슬라이더로 비교합니다.
- **이미지 도구**: 이미지를 올리거나 갤러리에서 가져와 제작 정보(Asset Studio 기록, ComfyUI 그래프,
  A1111 parameters, EXIF)를 읽고, WD14 태그 분석, 배경 투명화, 업스케일, 얼굴·손 다시 그리기
  (디테일러), 직접 칠할 수 있는 마스크로 가림 처리, WebP 변환을 합니다.
- **LoRA**: 통과한 이미지로 데이터셋을 만들고 캡션을 고친 뒤
  [anima_lora](https://github.com/sorryhyun/anima_lora)로 학습하고, 결과를 등록해 그 캐릭터를 생성할
  때 자동으로 적용합니다.

이미지는 ComfyUI의 `prompt`와 `workflow`를 담은 PNG로 저장되므로, ComfyUI에서 결과 이미지를
워크플로로 열 수 있습니다.

화면 언어는 한국어, 영어, 일본어, 중국어(간체)를 지원하며(**설정 › 일반**) 라이트, 다크, 시스템
테마를 고를 수 있습니다. 일본어와 중국어는 기계 번역이므로 고쳐 주시면 반영하겠습니다.

## 요구 사항

- Windows 10 또는 11. 실행 스크립트와 프로세스 관리는 Windows 전용입니다.
- NVIDIA GPU. RTX 4090(24GB)에서 개발했고, LoRA 학습에는 큰 GPU가 필요합니다.
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI), 0.38.0에서 확인했습니다.
  [Stability Matrix](https://github.com/LykosAI/StabilityMatrix), 포터블, git clone 모두 됩니다.
- [Pillow](https://pypi.org/project/pillow/)가 있는 Python 3.12 이상. ComfyUI의 Python에 이미
  Pillow가 있으니 그것을 써도 됩니다.
- 설치와 업데이트용 [Git](https://git-scm.com/).

## 설치

1. ComfyUI와 생성용 모델을 설치합니다([의존성](#의존성) 참고). ComfyUI를 한 번 켜서
   http://127.0.0.1:8188 이 열리는지 확인합니다.
2. Asset Studio를 받습니다.

   ```bat
   git clone https://github.com/kiritype/asset-studio.git
   cd asset-studio
   ```

3. 실행에 쓸 Python을 지정합니다. `launch.bat` 옆에 `launch.local.bat`를 만들고 `pythonw.exe`(콘솔
   창이 뜨지 않음)를 가리키는 한 줄을 적습니다. 예를 들어 ComfyUI의 Python:

   ```bat
   set "STUDIO_PYTHON=C:\path\to\ComfyUI\venv\Scripts\pythonw.exe"
   ```

   이 파일이 없으면 `PATH`의 `pythonw`를 씁니다.
4. 선택 기능에는 ComfyUI 커스텀 노드와 모델이 필요합니다. `tools/install_comfy_nodes.py`가 커스텀
   노드를 [확인한 버전](#확인한-버전)으로 설치하고 Asset Studio 노드 묶음을 ComfyUI에 연결합니다. ComfyUI의
   Python으로 실행하세요(포터블은 `python_embeded\python.exe`). 그냥 `python`이라고 치면 Microsoft
   Store가 열릴 수 있습니다. 켜져 있는 ComfyUI와 그 Python을 스스로
   찾고, `--yes`를 붙이기 전에는 할 일만 보여 줍니다.

   ```bat
   C:\path\to\ComfyUI\venv\Scripts\python.exe tools\install_comfy_nodes.py
   C:\path\to\ComfyUI\venv\Scripts\python.exe tools\install_comfy_nodes.py --yes
   ```

   `--only tagger,alpha`로 기능을 고르고(`autocomplete`, `tagger`, `alpha`, `detect`, `detailer`),
   ComfyUI가 꺼져 있거나 여러 개 설치되어 있으면 `--comfy`와 `--python`으로 알려 줍니다. 이미 있는
   노드는 건드리지 않습니다. 끝나면 ComfyUI를 재시작하고 [의존성](#의존성)의 모델을 넣으세요.

## 시작과 종료

- `launch.bat`: Asset Studio를 시작하고(이미 실행 중이 아니면) 브라우저에서
  http://127.0.0.1:8195 를 엽니다.
- `stop.bat`은 종료, `restart.bat`은 재시작입니다. 이미지가 생성 중이거나 대기 중일 때, LoRA를 학습
  중일 때는 먼저 물어봅니다.
- 생성과 이미지 도구에는 ComfyUI가 켜져 있어야 합니다. 화면 위쪽에 연결 상태가 보입니다. **설정**에서
  Asset Studio가 직접 시작한 ComfyUI를 시작·종료·재시작할 수도 있습니다(ComfyUI 폴더와 Python을
  적어야 합니다).

서버는 127.0.0.1에서만 접속을 받습니다. 만든 것은 모두 Asset Studio 폴더의 `data/`와 `outputs/`에
저장됩니다.

## 처음 사용하기

1. **설정**
   - **일반**: 언어, 테마, 태그 자동완성.
   - **ComfyUI 연결 정보**: 주소를 확인합니다(기본 `http://127.0.0.1:8188`). Asset Studio에서
     ComfyUI를 켜고 끄거나 Danbooru 태그 데이터를 찾게 하려면 ComfyUI 폴더와 Python도 적습니다.
     **자동으로 찾기**를 누르면 이 PC의 ComfyUI(실행 중인 것, Stability Matrix, 포터블, git 설치)를
     찾아 채워 줍니다.
2. **프롬프트 수정**: **샘플 가져오기**를 누르면 바로 써 볼 수 있는 예시 작품("Starlight Academy":
   캐릭터 2명, 교복, 감정 5개)이 생깁니다. 직접 만들려면:
   1. **+ 작품**으로 작품을 만들고 **+ 캐릭터**로 외형 프롬프트와 함께 캐릭터를 추가합니다.
   2. **+ 조각**으로 의상 부위(손, 상의, 하의, 신발 또는 의상 전체), 감정·동작, 구도, 작가 태그, 공통
      긍정·제외 태그를 추가합니다.
   3. **+ 의상 세트**로 의상 부위를 묶어 의상을 만듭니다.
   4. 범위 버튼(전역 / 작품 공용 / 캐릭터)으로 누가 그 조각을 쓸지 정합니다. 같은 코드면 캐릭터
      전용 조각이 공용 조각보다 우선합니다.
3. **작업**: 캐릭터, 의상, 감정·동작과 추가할 조각을 체크하고, 모델과 설정(Anima 또는 SDXL·IL 탭)을
   고른 뒤 미리보기를 확인하고 대기열에 넣습니다. 진행 상황은 위쪽 대기열 버튼에서 봅니다.
4. **갤러리**: 이미지를 열고 통과(P) 또는 실패(F)로 표시합니다. 통과한 이미지를 내보내고 학습에
   씁니다.
5. **LoRA**: 캐릭터를 고르고 그 캐릭터의 이미지로 데이터셋을 만든 뒤 학습합니다. 마음에 드는 에폭을
   등록하고 **자동 적용**을 켜면 그 캐릭터의 새 작업에 적용됩니다.

### 이미지 도구 한눈에 보기

- **WebP 변환**: 품질, 무손실, 크기 조절. "메타데이터 유지"는 기본으로 꺼져 있어 공유하는 파일에
  프롬프트와 워크플로가 남지 않습니다.
- **태그 분석**: WD14 태그를 이미지의 프롬프트와 비교합니다(일치, 그림에서만 읽힘, 그림에서 안 읽힘).
  제외할 태그를 정해 두고, 태그를 복사하거나 실험실로 보내거나, 고른 이미지의 태그를 TXT(LoRA 캡션)나
  JSON으로 내보낼 수 있습니다. 고른 이미지는 ZIP으로 한 번에 내려받을 수 있습니다.
- **후처리**: 업스케일, 디테일러. 업스케일하면 투명도가 사라지므로 배경 투명화는 업스케일 뒤에 하세요.
- **가림 처리**: (1) 필요하면 부위를 검출하고, (2) 빨간 마스크를 브러시와 지우개로 고친 뒤(되돌리기
  가능), (3) 모자이크, 흐림, 단색 중 하나로 적용합니다. 마스크 확장과 경계 부드럽게를 고를 수 있습니다.
- **배경 투명화**: (1) 배경을 자동으로 분리하고, (2) 남길 부분(파란 마스크)을 고친 뒤 결과 미리보기로
  확인하고, (3) 적용합니다.
- **인페인트**: 다시 그릴 부분(초록 마스크)을 칠하고, 그 이미지의 모델·LoRA와 기록된 프롬프트(고칠 수
  있음)로 그 부분만 다시 그립니다. 칠하지 않은 부분은 원본 픽셀 그대로 남습니다. Asset Studio로 만든
  이미지에만 쓸 수 있습니다.
- 원본은 바뀌지 않습니다. 작업 이미지(작품/캐릭터/의상 폴더)의 결과는 원본 옆에 새 후보로 저장되어
  갤러리에서 통과시키면 그 표정의 채택본이 됩니다. 그 밖의 결과는 `outputs/_tools/`에 저장됩니다.

## 의존성

아래 항목은 함께 배포되지 않습니다. 각 페이지에서 받아 ComfyUI가 찾는 폴더에 넣으세요. 모델 폴더는
ComfyUI `models/`의 하위 폴더(또는 Stability Matrix의 공유 모델 폴더)입니다.

### 생성 (필수)

| 항목 | 받는 곳 | ComfyUI 폴더 |
|---|---|---|
| Anima 확산 모델, 예: `anima-aesthetic-v1.1.safetensors` 또는 `anima-base-v1.0.safetensors` | [circlestone-labs/Anima](https://huggingface.co/circlestone-labs/Anima/tree/main/split_files/diffusion_models) ([Civitai](https://civitai.com/models/2458426)에도 있음) | `diffusion_models` |
| 텍스트 인코더 `qwen_3_06b_base.safetensors` | [circlestone-labs/Anima](https://huggingface.co/circlestone-labs/Anima/tree/main/split_files/text_encoders) | `text_encoders` |
| VAE `qwen_image_vae.safetensors` | [circlestone-labs/Anima](https://huggingface.co/circlestone-labs/Anima/tree/main/split_files/vae) | `vae` |

자체 텍스트 인코더가 있는 체크포인트형 Anima 파인튜닝(예: [MiaoMiao Harem](https://civitai.com/models/934764))도
됩니다. 생성 설정에서 체크포인트와 그 텍스트 인코더를 고르세요. SDXL/Illustrious는 `checkpoints`에
있는 Illustrious나 NoobAI 체크포인트면 됩니다.

팁: Anima 파일은 `anima` 하위 폴더, SDXL 파일은 `sdxl` 하위 폴더에 두세요(예: `loras/anima/`). 그러면
Asset Studio가 파일별 모델 계열을 알고 맞는 파일만 보여 줍니다. `tools/organize_models.py`가 기존
파일을 옮겨 줍니다(기본은 미리보기만).

### 선택 기능

| 기능 | 커스텀 노드 | 모델 |
|---|---|---|
| 태그 자동완성·태그 확인 | [ComfyUI-EasyUseAnima](https://github.com/n0va39/ComfyUI-EasyUseAnima) (Danbooru 태그 파일만 읽음) | — |
| WD14 태그 분석 (이미지 도구) | [ComfyUI-WD14-Tagger](https://github.com/pythongosssss/ComfyUI-WD14-Tagger) | 처음 쓸 때 노드가 내려받음, 예: [wd-eva02-large-tagger-v3](https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3) |
| 배경 투명화 | [ComfyUI_essentials](https://github.com/cubiq/ComfyUI_essentials) (requirements로 `rembg` 설치), Asset Studio 노드 묶음 | `isnet-anime`은 처음 쓸 때 rembg가 내려받음 |
| 가림 부위 검출 | Asset Studio 노드 묶음, ComfyUI Python의 `ultralytics` (Impact Subpack이 설치) | [Anime NSFW Detection](https://civitai.com/models/1313556)의 `ntd11_anime_nsfw_segm_v5-variant1.pt` → `ultralytics/segm` |
| 인물 마스크 (배경 투명화 대안) | Asset Studio 노드 묶음, `ultralytics` | [Bingsu/adetailer](https://huggingface.co/Bingsu/adetailer)의 `person_yolov8n-seg.pt` → `ultralytics/segm` |
| 업스케일 | Asset Studio 노드 묶음 | 예: [2x-AnimeSharpV4](https://huggingface.co/Kim2091/2x-AnimeSharpV4), [4x-UltraSharp](https://huggingface.co/Kim2091/UltraSharp) → `upscale_models` |
| 디테일러 (얼굴, 눈, 입, 손) | [ComfyUI-Impact-Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack), [ComfyUI-Impact-Subpack](https://github.com/ltdrdata/ComfyUI-Impact-Subpack), Asset Studio 노드 묶음 | [Bingsu/adetailer](https://huggingface.co/Bingsu/adetailer)의 `face_yolov8m.pt`, `hand_yolov8s.pt` → `ultralytics/bbox`; [Eye Detailer/Segmentation](https://civitai.com/models/334668)의 `PitEyeDetailer-v2-seg.pt` → `ultralytics/segm`; [sam_vit_b_01ec64.pth](https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth) → `sams` |
| 비전 모델 자동 검수 | 로컬 OpenAI 호환 서버(예: [LM Studio](https://lmstudio.ai/)) | 원하는 비전-언어 모델 |
| LoRA 학습 | — | [LoRA 학습](#lora-학습) 참고 |

Civitai의 검출 모델은 ZIP 파일입니다. `.pt` 파일을 풀어 표의 폴더에 넣으세요. Asset Studio 노드
묶음은 [설치](#설치) 4단계에서 연결한 `comfy_nodes/asset_studio_nodes` 폴더입니다. 가림 처리
자체(모자이크·흐림·단색)에는 노드가 필요 없고, 자동 검출에만 필요합니다.

### 확인한 버전

노드 설치 스크립트는 이 버전을 설치합니다. 다른 버전도 될 수 있지만 확인하지 않았습니다.

| 구성 요소 | 버전 | 커밋 | 라이선스 |
|---|---|---|---|
| ComfyUI | 0.38.0 | — | GPL-3.0 |
| [ComfyUI-EasyUseAnima](https://github.com/n0va39/ComfyUI-EasyUseAnima) | 1.1.1 | `66ae8b6` | MIT |
| [ComfyUI-WD14-Tagger](https://github.com/pythongosssss/ComfyUI-WD14-Tagger) | 1.0.1 | `9e0a6e7` | MIT |
| [ComfyUI_essentials](https://github.com/cubiq/ComfyUI_essentials) | 1.1.0 | `9d9f4be` | MIT |
| [ComfyUI-Impact-Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) | 8.28.3 | `429d015` | GPL-3.0 |
| [ComfyUI-Impact-Subpack](https://github.com/ltdrdata/ComfyUI-Impact-Subpack) | 1.3.5 | `50c7b71` | AGPL-3.0 |
| Python 패키지 (노드가 설치) | ultralytics 8.4.150, rembg 2.0.85, onnxruntime 1.30.0 | — | AGPL-3.0 · MIT · MIT |

## LoRA 학습

학습은 [anima_lora](https://github.com/sorryhyun/anima_lora)를 자체 Python 환경에서 실행합니다. 따로
설치합니다.

1. [uv](https://docs.astral.sh/uv/)를 설치하고 anima_lora를 Asset Studio 폴더 안의
   `vendor/anima_lora`에 받습니다. Asset Studio는 커밋 `69ff962`로 확인했고, 이 커밋은 짝이 되는
   `anime_tools`(v0.7.5)가 `vendor/anime_tools`에 있어야 합니다.

   ```bat
   git clone https://github.com/sorryhyun/anime_tools.git vendor\anime_tools
   git -C vendor\anime_tools checkout v0.7.5
   git clone https://github.com/sorryhyun/anima_lora.git vendor\anima_lora
   cd vendor\anima_lora
   git checkout 69ff962
   uv sync
   ```

   `uv sync`에 더 필요한 것이 있으면 anima_lora의 [Setup](https://github.com/sorryhyun/anima_lora#setup)을
   따르세요(Python 3.13과 CUDA용 PyTorch를 쓰므로 최신 NVIDIA 드라이버가 필요합니다).
2. Asset Studio의 작은 패치를 적용합니다. 전처리가 anima_lora의 `models/` 폴더 대신 지정한 모델
   파일을 쓰게 합니다.

   ```bat
   git apply ..\..\trainer\anima_lora\preprocess-model-paths.patch
   ```

3. **설정 › LoRA 학습**에서 채웁니다.
   - **LoRA 저장 폴더**: ComfyUI LoRA 폴더(예: `.../loras/anima`). 끝난 에폭이 여기로 복사됩니다.
   - **공식 Anima base**: 공식 [Anima base](https://huggingface.co/circlestone-labs/Anima/tree/main/split_files)
     파일(`anima-base-v1.0.safetensors`, `qwen_3_06b_base.safetensors`, `qwen_image_vae.safetensors`).
   - **생성 모델** (선택): 대신 학습에 쓸 Anima 파인튜닝 모델.

   경로마다 파일을 찾았는지 표시됩니다.

Asset Studio가 학습할 때마다 학습 도구의 프리셋(`vendor/anima_lora/configs/presets.toml`의
`asset-studio` 표시 부분)과 방식 파일을 직접 씁니다. LoRA를 학습하는 동안에는 새 이미지를 생성하지
않고, 대기 중인 이미지는 학습이 끝난 뒤 이어서 생성합니다.

## 설정

모든 설정은 **설정** 화면에서 바꾸고 서버의 `data/settings/`에 저장되므로, 같은 PC의 모든 브라우저에서
같은 설정이 보입니다.

| 항목 | 내용 |
|---|---|
| 일반 | 언어, 테마, 태그 자동완성 |
| ComfyUI 연결 정보 | ComfyUI 주소, 폴더, Python |
| Danbooru 태그 데이터 | 태그 파일이 ComfyUI-EasyUseAnima에 없을 때의 폴더 |
| LoRA 학습 | 학습 도구 폴더, 그 Python, LoRA 저장 폴더, 학습용 모델 |
| GPU 사용 / GPU 대기 조건 | 다른 프로그램이 GPU를 쓸 때 기다림(남은 VRAM, 프로그램 이름) |
| VLM 서버 / VLM 검증 | 선택 기능인 자동 검수: 서버 주소, 모델, 모델을 올리고 내리는 명령(예: LM Studio의 `lms load` / `lms unload` / `lms ps`), 켜기·끄기 |

`config/models.example.json`(`data/settings/models.json`으로 복사)은 공유 모델 폴더와 수동 모델 계열을
지정합니다. 대부분은 필요하지 않습니다.

## 내 데이터

- `data/`에는 프롬프트 라이브러리, 검수 결과, 데이터셋, LoRA 기록, 설정이 있고, `outputs/`에는
  생성·처리한 이미지가 있습니다. 두 폴더를 백업하세요. 둘 다 git 저장소에 포함되지 않습니다.
- 프롬프트를 지우면 라이브러리 휴지통으로 가며, 거기서 되살릴 수 있습니다.
- `outputs/_lab/`에는 실험실 이미지, `outputs/_tools/`에는 이미지 도구 결과가 있습니다. 갤러리는
  `outputs/` 아래의 모든 이미지를 보여 줍니다.

## 문제 해결

- **ComfyUI에 연결할 수 없음**: ComfyUI를 켜고 설정의 주소를 확인하세요.
- **모델이나 노드가 "목록에 없음"**: 설치한 뒤 ComfyUI를 재시작하고 페이지를 새로고침하세요. 이미지
  도구는 없는 노드 이름을 알려 줍니다.
- **대기열 일시정지**: 작업이 실패하면 잃는 것이 없도록 대기열이 멈춥니다. 대기열 창에서 오류를 읽고
  고친 뒤 다시 시작하세요.
- **로그**: `logs/studio.log`(서버), `logs/launcher.log`(시작), `logs/lora/<run>/trainer.log`(학습).

## 라이선스

Asset Studio는 [MIT 라이선스](LICENSE)로 공개합니다. 모델 가중치나 다른 사람의 커스텀 노드는 포함하지
않습니다. 사용하는 프로젝트와 라이선스는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 보세요.

### Anima 모델과 직접 학습한 LoRA에 대해

Anima는 CircleStone Labs가
[CircleStone Labs Non-Commercial License](https://huggingface.co/circlestone-labs/Anima/blob/main/LICENSE.md)로
공개했고, NVIDIA Cosmos-Predict2를 바탕으로 하므로 NVIDIA Open Model License도 적용됩니다. 요약하면
다음과 같습니다(정확한 조건은 라이선스 원문을 보세요).

- Anima 가중치로 만든 LoRA, 파인튜닝, 병합 모델은 그 라이선스의 **파생물(Derivative)**이며 비상업
  조건을 따릅니다. Asset Studio로 학습한 LoRA와 Anima 파인튜닝 모델도 포함됩니다.
- 그런 LoRA를 공유할 때는 CircleStone 모델을 수정했다는 사실과 라이선스가 요구하는 고지 문구를 함께
  넣어야 합니다.
- 개인은 직접 만든 파생물을 판매할 수 있습니다. 유료 서비스로 제공하거나 유료 제품에 넣으려면
  CircleStone Labs의 별도 라이선스가 필요합니다.
- 생성한 이미지에 대해 CircleStone Labs는 소유권을 주장하지 않습니다.

그 밖의 모델(업스케일러, 검출 모델, 체크포인트)은 각 배포 페이지의 라이선스를 따릅니다. 예를 들어
2x-AnimeSharpV4와 4x-UltraSharp 업스케일러는 CC BY-NC-SA 4.0입니다.

## 기여

[CONTRIBUTING.ko.md](CONTRIBUTING.ko.md)를 보세요.
