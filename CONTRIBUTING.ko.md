# 기여 안내

[English](CONTRIBUTING.md) · 한국어

Asset Studio에 관심을 가져 주셔서 고맙습니다. 버그 신고, 번역 수정, 코드 기여 모두 환영합니다.
이 문서는 기여할 때 지켜 주셨으면 하는 내용을 정리한 것입니다.

## 버그 신고와 제안

- [Issues](https://github.com/kiritype/asset-studio/issues)에 올려 주세요.
- 무엇을 했고, 무엇을 기대했고, 실제로 무엇이 일어났는지 적어 주세요. Windows 버전, GPU, ComfyUI
  버전과 설치 방식(Stability Matrix, 포터블, git)도 알려 주시면 도움이 됩니다.
- 로그를 붙여 주세요: `logs/studio.log`(서버), `logs/launcher.log`(시작), LoRA 학습이면
  `logs/lora/<학습 이름>/trainer.log`.
- 올리기 전에 개인 경로, 사용자 이름, 개인 이미지, 프롬프트처럼 공개하고 싶지 않은 내용은 지워 주세요.

## 번역

화면은 한국어, 영어, 일본어, 중국어(간체)를 지원합니다. 일본어와 중국어는 기계 번역이라 어색한 곳이
있습니다. 고쳐 주시면 반영합니다.

- 화면 문구: `static/i18n/<언어>.json` (`ko.json`, `en.json`, `ja.json`, `zh-CN.json`)
- README: `README.ja.md`, `README.zh-CN.md`
- 웹 매뉴얼: `manual/<언어>/`

## 개발 환경

필요한 것은 README의 [요구 사항](README.ko.md#요구-사항)과 같습니다. 서버 본체는 Python 표준
라이브러리와 Pillow만 씁니다.

실제 작업 데이터를 건드리지 않도록 개발할 때는 다른 포트와 빈 데이터 폴더로 띄우세요.

```bat
python -m asset_studio --port 8197 --root C:\temp\studio-dev --static-root static
```

- `--root`: `data/`, `outputs/`, `logs/`가 생길 폴더
- `--static-root`: 화면 파일 위치(저장소의 `static`). 화면 파일은 새로고침만 하면 바뀐 내용이 보이고,
  Python 코드를 바꾸면 서버를 다시 시작해야 합니다.

## 저장소 구성

```
asset_studio/      Python 패키지 (서버와 도메인 로직)
static/            화면 (HTML, CSS, ES 모듈, i18n 번역)
manual/            웹 매뉴얼 (VitePress)
comfy_nodes/       ComfyUI에 연결해 쓰는 Asset Studio 노드 묶음, 외부 노드 목록(nodes.json)
trainer/           학습 도구(anima_lora)에 적용하는 패치와 방식 설정
samples/           샘플 작품
config/            예시 설정 (*.example.json)
tools/             명령줄 도구 (노드 설치, 번역 확인, 모델 정리, 데이터 변환)
tests/             자동 테스트
launch.py, *.bat   시작·종료·재시작
```

`asset_studio/` 안:

```
app.py             Studio 객체와 실행 진입점
compose.py         프롬프트 조각 → 최종 긍정·제외 프롬프트
http/              HTTP 라우트와 접근 제한
library/           프롬프트 라이브러리 (작품·캐릭터·조각·의상 세트·프리셋)
generation/        ComfyUI 연결, 생성 대기열, 작업 실행, 워크플로 그래프, 실험실
gallery/           출력 이미지 목록과 검수 기록
lora/              데이터셋, 캡션, 학습 실행, LoRA 등록과 자동 적용
tools/             이미지 도구 (메타데이터, WD14 태그, 변환, 후처리, 마스크)
validation/        로컬 비전 모델 자동 검수 (선택)
settings_api.py    설정 화면의 저장과 확인
comfy_locate.py    설치된 ComfyUI와 모델 폴더 찾기
samples.py         샘플 작품 가져오기
gpu.py             GPU 사용 순서 관리
models.py          모델 파일의 계열(Anima·SDXL) 판별
tags.py            Danbooru 태그 자동완성·확인
util.py            원자적 쓰기 등 공용 함수
```

## 설계 원칙

- **작품 > 캐릭터 구조를 유지합니다.** 캐릭터 코드는 작품 안에서만 고유합니다. 캐릭터를 가리키는
  코드·API·파일은 작품 코드를 함께 받습니다(`W001/C041`, `W001/C041/001`).
- **코드와 데이터를 분리합니다.** 저장소에는 코드·문서·예시 설정만 둡니다. 실행 중 생기는
  것(`data/`, `outputs/`, `logs/` 등)은 커밋하지 않습니다.
- **개인 환경 값을 코드에 넣지 않습니다.** 경로, 모델 파일명, 주소, 키는 설정(`data/settings/`)에 두고
  저장소에는 `config/*.example.json`만 둡니다.
- **사용자 데이터를 지우지 않습니다.** 라이브러리 항목은 휴지통으로 보내고, 원본 이미지는 바꾸지 않고
  결과를 새 파일로 저장합니다.
- **사람이 최종 판정합니다.** 자동 검수 결과는 참고용이며 사람의 판정을 덮어쓰지 않습니다.
- **서버는 127.0.0.1에서만 접속을 받습니다.** 외부에서 접속할 수 있게 하는 변경은 이슈에서 먼저
  논의해 주세요.

## Python

- Python 3.12 이상에서 동작해야 합니다.
- 서버 본체에 새 의존성을 추가하려면 먼저 이슈에서 이유를 논의해 주세요. 학습 관련 의존성은 본체와
  분리합니다.
- 형식은 `ruff format`, 검사는 `ruff check` 기준입니다(`ruff.toml`, 한 줄 100자, 작은따옴표).
- 이름은 모듈·함수·변수 `snake_case`, 클래스 `PascalCase`. 줄임말보다 뜻이 드러나는 이름을 씁니다.
- 공개 함수와 클래스에는 한두 줄의 docstring을 씁니다. 주석은 "무엇"이 아니라 "왜"를 적습니다.
- 파일은 임시 파일에 쓴 뒤 교체하는 원자적 쓰기(`util.atomic_json`, `util.replace_file`)로 씁니다.
- 입력 검증 실패는 `ValueError`, 동시 수정 충돌은 `ConflictError`로 올리면 HTTP 계층이 400/409로 바꿉니다.
- 화면에 보일 서버 문구(오류, 상태, 라벨)는 `Msg('server.<모듈>.<이름>', 'English text', 값=...)`로
  만듭니다. 서버 안에서는 영어 문자열로 쓰이고, 화면에는 번역 키로 전달됩니다(아래 "화면 문구").

## 화면 (JavaScript / CSS)

- 프레임워크와 빌드 단계를 쓰지 않습니다. 브라우저가 직접 읽는 ES 모듈로 씁니다.
- 메뉴마다 `static/js/views/<메뉴>.js`, 공통 기능은 `static/js/core/`에 둡니다.
- 형식은 Prettier 3 기준입니다(`.prettierrc.json`, 한 줄 100자, 작은따옴표).

  ```bat
  npx prettier@3 --write "static/js/**/*.js" "static/css/*.css"
  ```

- 서버에서 받은 문자열은 `textContent`로 넣습니다(`innerHTML` 금지).
- 코드 식별자와 주석은 영어로 씁니다.

### 화면 문구

- 코드에는 한국어를 직접 쓰지 않습니다. 화면 문구는 `t('<화면>.<이름>')` 키로 쓰고(예:
  `t('jobs.queue_n', [count])`), 여러 화면에서 쓰는 문구는 `common.` 키로 둡니다.
- 서버에서 온 문구는 `tr(...)`로 표시합니다. 서버 문구는 `{i18n, params, text}` 객체로 오고, 사람이 적은
  이름 같은 문자열은 그대로 보입니다.
- 키를 새로 쓰면 네 언어(`ko`, `en`, `ja`, `zh-CN`)의 번역을 함께 넣습니다. 번역이 빠진 언어는 영어로,
  영어도 없으면 키 그대로 보입니다.

  ```bat
  python tools\i18n_check.py
  python tools\i18n_add.py entries.json
  ```

  `entries.json` 형식: `{"jobs.queue_n": {"ko": "…", "en": "…", "ja": "…", "zh-CN": "…"}}`. 서버 키의
  `en`은 `Msg()`에 쓴 영어와 같아야 합니다. 번역이 빠지거나, 값 자리(`{0}`, `{name}`)가 언어마다
  다르거나, 코드에 한국어가 남으면 테스트가 실패합니다.

## 데이터

- JSON 기록에는 `schema_version`을 둡니다. 형식을 바꾸면 버전을 올리고 `tools/migrations/`에 변환
  스크립트와 테스트를 추가합니다.
- 항목 코드: 작품 `W###`, 캐릭터 `C###`, 의상 세트 `###`, 감정 `###`. 한 번 쓴 코드는 다른 뜻으로
  다시 쓰지 않습니다.
- 생성한 이미지에는 조합 결과와 설정 전체를 메타데이터로 남깁니다.
- 이미지 파일을 가리킬 때는 경로와 SHA-256을 함께 기록합니다.

## API

- 경로는 `/api/<자원>[/<동작>]`. 조회는 GET, 변경은 POST입니다.
- 응답은 JSON이고, 실패는 `{"error": "사람이 읽을 수 있는 설명"}`입니다.
- 편집할 수 있는 항목은 `revision`을 주고받아 동시 수정 충돌을 막습니다.

## 테스트

- 아래 명령이 모두 통과해야 합니다.

  ```bat
  python -m unittest discover -s tests
  node tests\test_character_seeds.mjs
  node tests\test_library_helpers.mjs
  node tests\test_prompt_format.mjs
  node tests\test_tags.mjs
  ```

- 테스트는 네트워크, GPU, 실제 `data/`를 쓰지 않습니다(임시 폴더와 가짜 ComfyUI 사용).
- 기능을 추가하거나 버그를 고치면 테스트를 함께 추가합니다.

## 문서

기능을 바꾸면 문서도 함께 고칩니다.

- README 네 개(`README.md`, `README.ko.md`, `README.ja.md`, `README.zh-CN.md`)
- 웹 매뉴얼(`manual/`): 한국어(`manual/ko/`)를 먼저 고치고 다른 언어에 옮깁니다.

## 외부 코드

- 다른 사람의 저장소를 복사해 넣지 않습니다. 필요한 ComfyUI 노드는 `comfy_nodes/nodes.json`에 고정한
  버전(커밋)으로 적고, `tools/install_comfy_nodes.py`가 설치합니다. 버전을 바꾸면 README의
  "확인한 버전" 표도 함께 고칩니다(테스트가 확인합니다).
- `comfy_nodes/asset_studio_nodes`는 같은 작성자의 다른 프로젝트(AtelierX)에서 가져온 것이라 예외입니다.
  출처는 그 폴더의 `SOURCE.md`에 있습니다.
- 학습 도구(anima_lora)는 고정한 커밋과 우리가 고친 부분(`trainer/`의 패치)만 둡니다.
- 라이선스와 출처는 `THIRD_PARTY_NOTICES.md`에 적습니다.
- 모델 가중치는 저장소에 넣지 않습니다. 이름, 출처 링크, 용도, 라이선스만 문서에 적습니다.

## 커밋과 Pull Request

- 커밋 메시지: `<영역>: <무엇을 왜>`, 영어로 씁니다(예: `lora: add dataset export from approved images`).
- 한 커밋에는 한 가지 변경만 담습니다. 리팩터링과 기능 변경을 섞지 않습니다.
- 커밋 전에 테스트, `ruff check`, Prettier를 확인합니다.
- 실행 데이터, 생성 이미지, 개인 설정, 모델 파일, 로그가 섞이지 않았는지 확인합니다.
- 커밋과 PR 메시지에는 변경 내용만 적습니다. 작성 도구 표기, 자동 생성 서명, 공동 작성자 줄은 넣지
  않습니다.
- PR에는 무엇을 왜 바꿨는지, 어떻게 확인했는지 적어 주세요. 화면이 바뀌면 캡처를 붙여 주세요.

## 라이선스

기여한 내용은 이 저장소와 같은 [MIT 라이선스](LICENSE)로 공개됩니다.
