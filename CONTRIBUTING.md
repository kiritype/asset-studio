# Contributing

English · [한국어](CONTRIBUTING.ko.md)

Thank you for your interest in Asset Studio. Bug reports, translation fixes and code are
all welcome. This page collects what to keep in mind when you contribute.

## Bug reports and ideas

- Open an [issue](https://github.com/kiritype/asset-studio/issues).
- Say what you did, what you expected and what happened. Your Windows version, GPU,
  ComfyUI version and how ComfyUI is installed (Stability Matrix, portable, git) help too.
- Attach the logs: `logs/studio.log` (server), `logs/launcher.log` (start-up) and, for LoRA
  training, `logs/lora/<run name>/trainer.log`.
- Before posting, remove anything you do not want public: personal paths, user names,
  your images or prompts.

## Translations

The interface supports Korean, English, Japanese and Simplified Chinese. The Japanese and
Chinese texts are machine translations and read awkwardly in places; corrections are
welcome.

- Interface: `static/i18n/<language>.json` (keys are the Korean source text)
- README: `README.ja.md`, `README.zh-CN.md`
- Web manual: `manual/<language>/`

## Development setup

You need what the README lists under [Requirements](README.md#requirements). The server
itself uses only the Python standard library and Pillow.

To keep your real work untouched, run a development server on another port with an empty
data folder:

```bat
python -m asset_studio --port 8197 --root C:\temp\studio-dev --static-root static
```

- `--root`: where `data/`, `outputs/` and `logs/` are created
- `--static-root`: the interface files (the repository's `static`). Changes to them show
  after a page reload; Python changes need a server restart.

## Repository layout

```
asset_studio/      Python package (server and domain logic)
static/            Interface (HTML, CSS, ES modules, i18n catalogs)
manual/            Web manual (VitePress)
comfy_nodes/       Asset Studio's ComfyUI node pack and the list of third-party nodes (nodes.json)
trainer/           Patch and method files applied to the trainer (anima_lora)
samples/           Sample works
config/            Example settings (*.example.json)
tools/             Command-line tools (node installer, translation check, model tidy-up, migrations)
tests/             Automated tests
launch.py, *.bat   Start, stop, restart
```

Inside `asset_studio/`:

```
app.py             Studio object and entry point
compose.py         Prompt pieces → final positive and negative prompts
http/              HTTP routes and access control
library/           Prompt library (works, characters, pieces, outfit sets, presets)
generation/        ComfyUI client, generation queue, job runner, workflow graphs, lab
gallery/           Output listing and review records
lora/              Datasets, captions, training runs, LoRA registry and auto-apply
tools/             Image tools (metadata, WD14 tags, conversion, post-processing, masks)
validation/        Optional review with a local vision model
settings_api.py    Saving and checking the settings page
comfy_locate.py    Finding ComfyUI installs and model folders
samples.py         Importing sample works
gpu.py             GPU scheduling
models.py          Model family (Anima / SDXL) of model files
tags.py            Danbooru tag autocomplete and check
util.py            Shared helpers such as atomic writes
```

## Design principles

- **Keep the work › character hierarchy.** Character codes are unique only within a work.
  Anything that points at a character also takes the work code (`W001/C041`,
  `W001/C041/001`).
- **Keep code and data apart.** The repository holds code, documents and example settings
  only. What is created at run time (`data/`, `outputs/`, `logs/` and so on) is never
  committed.
- **No personal values in code.** Paths, model file names, addresses and keys belong in the
  settings (`data/settings/`); the repository has `config/*.example.json` only.
- **Never destroy user data.** Library items go to the trash; source images are never
  changed and results are saved as new files.
- **People make the final call.** Automated review is advisory and never overrides a
  person's verdict.
- **The server listens on 127.0.0.1 only.** Please discuss any change that would make it
  reachable from elsewhere in an issue first.

## Python

- It must run on Python 3.12 or newer.
- Discuss a new dependency for the server in an issue before adding it. Training
  dependencies stay separate from the server.
- Format with `ruff format` and check with `ruff check` (`ruff.toml`: 100 characters per
  line, single quotes).
- Names: `snake_case` for modules, functions and variables, `PascalCase` for classes. Prefer
  clear names over abbreviations.
- Give public functions and classes a one- or two-line docstring. Comments explain why, not
  what.
- Write files atomically (write a temporary file, then replace): `util.atomic_json`,
  `util.replace_file`.
- Raise `ValueError` for invalid input and `ConflictError` for concurrent edits; the HTTP
  layer turns them into 400 and 409.
- Error messages the server returns are written in Korean source text and translated (see
  "Interface text").

## Interface (JavaScript / CSS)

- No framework and no build step: plain ES modules the browser loads directly.
- One module per menu in `static/js/views/<menu>.js`; shared code in `static/js/core/`.
- Format with Prettier 3 (`.prettierrc.json`: 100 characters per line, single quotes):

  ```bat
  npx prettier@3 --write "static/js/**/*.js" "static/css/*.css"
  ```

- Insert text that comes from the server with `textContent` (no `innerHTML`).
- Code identifiers and comments are in English.

### Interface text

- Wrap the Korean source text in `t('...')`; show text that came from the server with
  `tr(...)`.
- Add the English, Japanese and Chinese translations with every new string:

  ```bat
  python tools\i18n_check.py
  python tools\i18n_add.py entries.json
  ```

  `entries.json` looks like `{"한국어 원문": ["English", "日本語", "简体中文"]}`. Tests fail
  when a translation is missing.

## Data

- JSON records carry a `schema_version`. When a format changes, raise the version and add a
  migration script with tests to `tools/migrations/`.
- Codes: works `W###`, characters `C###`, outfit sets `###`, expressions `###`. A code that
  was used is never reused for something else.
- Generated images keep the full composition and settings as metadata.
- References to image files record both the path and the SHA-256.

## API

- Paths are `/api/<resource>[/<action>]`. GET reads, POST changes.
- Responses are JSON; failures are `{"error": "a readable explanation"}`.
- Editable items exchange a `revision` to prevent concurrent edits from clashing.

## Tests

- All of these must pass:

  ```bat
  python -m unittest discover -s tests
  node tests\test_character_seeds.mjs
  node tests\test_library_helpers.mjs
  node tests\test_prompt_format.mjs
  node tests\test_tags.mjs
  ```

- Tests never use the network, the GPU or a real `data/` folder (they use temporary folders
  and a fake ComfyUI).
- Add tests with every feature and bug fix.

## Documentation

Update the documents together with the feature:

- the four READMEs (`README.md`, `README.ko.md`, `README.ja.md`, `README.zh-CN.md`)
- the web manual (`manual/`): change the Korean pages (`manual/ko/`) first, then carry the
  change to the other languages.

## Third-party code

- Do not copy other people's repositories in. ComfyUI nodes are listed with a pinned
  version (commit) in `comfy_nodes/nodes.json` and installed by
  `tools/install_comfy_nodes.py`. When a version changes, update the "Tested versions" table
  in the READMEs as well (a test checks it).
- `comfy_nodes/asset_studio_nodes` is the exception: it comes from another project by the
  same author (AtelierX); its origin is in that folder's `SOURCE.md`.
- For the trainer (anima_lora) only the pinned commit and our changes (the patch in
  `trainer/`) are kept.
- Licenses and origins go in `THIRD_PARTY_NOTICES.md`.
- No model weights in the repository; documents give the name, a link, the purpose and the
  license.

## Commits and pull requests

- Commit messages: `<area>: <what and why>`, in English (for example
  `lora: add dataset export from approved images`).
- One change per commit; do not mix refactoring with feature changes.
- Before committing, run the tests, `ruff check` and Prettier.
- Make sure no run-time data, generated images, personal settings, model files or logs slip
  in.
- Commit and PR messages describe the change only: no tool credits, generated signatures or
  co-author lines.
- In a pull request, say what you changed, why, and how you checked it. Add screenshots when
  the interface changes.

## License

Contributions are released under the same [MIT License](LICENSE) as the repository.
