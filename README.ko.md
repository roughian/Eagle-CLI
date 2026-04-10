# CLI-Anything Eagle

[English](./README.md) | [한국어](./README.ko.md)

`cli-anything-eagle`은 Eagle 데스크톱 앱을 위한 폭넓은 커맨드라인 인터페이스입니다.
Eagle의 로컬 HTTP API를 대상으로 하며, 앱 정보 조회, 라이브러리 관리, 폴더 워크플로우,
스마트 폴더 규칙 점검, 아이템 가져오기, 일괄 수정, 재사용 가능한 프리셋, 프리셋 번들,
아이템 내보내기, 작업 계획(plan), 쿼리 통계, 롤백 스냅샷, 스냅샷 diff, 중복 및 정리 audit,
중복 정리 plan 생성, 태그 audit 및 정규화, 저장된 selection 세트, 재사용 가능한 리포트,
선언형 workflow, manifest 기반 가져오기, 증분 import watch, plan merge/filter/split/validate,
셸 completion, 문서 schema, 영구 config 기본값, 대시보드 리포트, 고수준 organize 흐름,
에이전트 관찰과 plan/apply/verify 루프를 제공합니다.

또한 로컬 HTTP API만으로는 어려운 selection, open, 태그, 이름, 폴더 조작을 위해 companion
bridge plugin도 함께 지원하며, bridge 상태 진단과 정리 도구도 포함합니다.

## 요구 사항

- 로컬에서 실행 중인 Eagle 데스크톱 앱
- `http://localhost:41595`에서 응답하는 Eagle API
- Python 3.10 이상
- 로컬 머신에서 사용 가능한 `curl`

## 설치

일반 사용자에게 권장하는 설치:

```bash
python3 -m pip install "git+https://github.com/roughian/CLI-Anything-Eagle.git"
```

CLI 전용으로 깔끔하게 쓰고 싶다면:

```bash
pipx install "git+https://github.com/roughian/CLI-Anything-Eagle.git"
```

로컬 개발용 설치:

```bash
git clone https://github.com/roughian/CLI-Anything-Eagle.git
cd CLI-Anything-Eagle
python3 -m pip install -e ".[dev]"
```

companion bridge plugin 템플릿은 설치된 Python 패키지 안에도 번들되어 있으므로,
일반 `pip` 또는 `pipx` 설치에서도 `bridge export-plugin`, `bridge install-plugin`을 그대로 사용할 수 있습니다.

셸 `PATH`에 `cli-anything-eagle`이 없다면 아래처럼 실행해도 됩니다.

```bash
python3 -m cli_anything.eagle.eagle_cli --help
```

## 빠른 시작

```bash
cli-anything-eagle doctor
cli-anything-eagle app info
cli-anything-eagle app show
cli-anything-eagle library summary
cli-anything-eagle library info
cli-anything-eagle smart-folder audit
cli-anything-eagle smart-folder run --name "Camera JPG"
cli-anything-eagle folder tree
cli-anything-eagle folder find Reference
cli-anything-eagle --json item list --limit 10 --tag reference
cli-anything-eagle --json audit duplicates --all --top 5
cli-anything-eagle --json audit dedupe-plan ./plans/duplicates.json --keyword logo
cli-anything-eagle --json plan stats ./plans/duplicates.json
cli-anything-eagle --json tag stats --all --top 10
cli-anything-eagle --json tag recent-live
cli-anything-eagle --json tag starred-live
cli-anything-eagle --json select list
cli-anything-eagle --json config show
cli-anything-eagle --json workflow template --list
cli-anything-eagle workflow template review-batch ./workflow.yml
cli-anything-eagle --json plan explain ./plans/duplicates.json --output ./plans/duplicates.md --format md
cli-anything-eagle report index ./reports/index.md ./reports ./plans
cli-anything-eagle report dashboard ./reports/dashboard.md --format md --all
cli-anything-eagle --json workflow validate ./workflow.yml
cli-anything-eagle --json agent observe --output ./reports/agent-observe.json
cli-anything-eagle --json agent plan ./plans/review-selection.json --goal "Review current selection" --current-selection --add-tag reviewed
cli-anything-eagle --json agent plan ./plans/review-folder.json --goal "Review current folder" --current-folder --add-tag reviewed
cli-anything-eagle --json --dry-run agent apply ./plans/review-selection.json --save-results ./plans/review-selection-preview.json
cli-anything-eagle --json agent verify ./plans/review-selection.json
cli-anything-eagle --json bridge status
cli-anything-eagle --json bridge selected-item-ids
cli-anything-eagle --json report current-context ./reports/current-context.json
cli-anything-eagle --json bridge doctor --skip-ping
cli-anything-eagle --json item selected
cli-anything-eagle --json folder selected
```

bridge plugin 상태가 계속 `offline`이라면 Eagle을 재시작한 뒤 출력에 보이는 `log_path`를 확인하세요.
plugin은 `~/.config/cli-anything-eagle/bridge/` 아래에 지속적인 `plugin.log`를 기록합니다.

## 유용한 워크플로우

로컬 Eagle API와 버전 확인:

```bash
cli-anything-eagle doctor
cli-anything-eagle --json app info
cli-anything-eagle --json library summary
cli-anything-eagle --json smart-folder audit
```

이름이나 경로로 폴더 찾기 및 준비:

```bash
cli-anything-eagle folder find Inspiration
cli-anything-eagle --dry-run folder ensure-path "Design/UI/References"
cli-anything-eagle folder ensure-path "Design/UI/References"
```

폴더 ID가 아니라 폴더 경로로 아이템 다루기:

```bash
cli-anything-eagle item list --folder-path "Design/UI/References" --limit 20
cli-anything-eagle item add-path ./shot.png --folder-path "Design/UI/References"
```

Eagle 안에서 이미 쓰고 있는 스마트 폴더 규칙과 변수를 점검:

```bash
cli-anything-eagle smart-folder list
cli-anything-eagle smart-folder rules --name "Camera JPG"
cli-anything-eagle --json smart-folder audit
```

지원되는 스마트 폴더 규칙을 실제 item query로 실행:

```bash
cli-anything-eagle --json smart-folder run --name "Camera JPG"
cli-anything-eagle smart-folder run --name "Camera JPG" --limit 100 --save-preset camera-jpg
```

적용 전에 일괄 수정 미리보기:

```bash
cli-anything-eagle --dry-run item bulk-update \
  --folder-name References \
  --keyword icon \
  --add-tag reviewed

cli-anything-eagle item bulk-update \
  --folder-name References \
  --keyword icon \
  --add-tag reviewed
```

bulk-update 프리셋 저장 및 재실행:

```bash
cli-anything-eagle preset save-bulk-update review-ui \
  --keyword ui \
  --add-tag reviewed

cli-anything-eagle --dry-run preset run-bulk-update review-ui
cli-anything-eagle preset run-bulk-update review-ui
```

다른 Eagle 사용자와 프리셋 공유:

```bash
cli-anything-eagle preset export ./bundles/team-presets.json review-ui ui-ref
cli-anything-eagle preset import ./bundles/team-presets.json --prefix team-
```

자주 쓰는 검색 저장 및 재사용:

```bash
cli-anything-eagle preset save-item-list ui-ref \
  --keyword ui \
  --tag reference \
  --folder-path "Design/UI/References"

cli-anything-eagle preset list
cli-anything-eagle preset run-item-list ui-ref
```

로컬 디렉터리 전체를 필터와 manifest와 함께 추가:

```bash
cli-anything-eagle --dry-run item add-dir ./assets \
  --recursive \
  --ext png \
  --folder-path "Design/UI/References" \
  --save-manifest ./manifests/assets.json

cli-anything-eagle item add-dir ./assets --recursive --glob "*.png"
```

조건에 맞는 아이템을 모두 가져와서 export:

```bash
cli-anything-eagle item list --all --limit 100 --keyword ui
cli-anything-eagle item export ./exports/ui-items.jsonl --all --limit 100 --keyword ui
cli-anything-eagle item export ./exports/ui-items.csv --format csv --folder-path "Design/UI/References"
```

수정 전에 필터된 아이템 상태 점검:

```bash
cli-anything-eagle item stats --all --limit 50 --keyword ui
cli-anything-eagle item stats --folder-path "Design/UI/References" --top 20
```

bulk update 안전장치 사용:

```bash
cli-anything-eagle --dry-run item bulk-update \
  --keyword ui \
  --add-tag reviewed \
  --max-items 10 \
  --require-match 1 \
  --save-matches ./exports/ui-matches.json

cli-anything-eagle --dry-run item bulk-update \
  --item-id EXAMPLE \
  --add-tag reviewed \
  --skip-unchanged
```

직전 item-producing 명령 재사용 또는 파일에서 item ID 로드:

```bash
cli-anything-eagle --json item list --limit 20 --keyword CleanShot
cli-anything-eagle --dry-run item bulk-update --last --add-tag reviewed

cli-anything-eagle item export ./exports/cleanshot.json --limit 20 --keyword CleanShot
cli-anything-eagle --dry-run item bulk-update --item-file ./exports/cleanshot.json --add-tag reviewed
```

큰 변경 전에 롤백용 snapshot 생성:

```bash
cli-anything-eagle snapshot create ./snapshots/ui.json --folder-path "Design/UI/References"
cli-anything-eagle snapshot show ./snapshots/ui.json
cli-anything-eagle snapshot diff ./snapshots/ui.json --include-names --include-folders
cli-anything-eagle --dry-run snapshot restore ./snapshots/ui.json
```

companion bridge plugin을 이용해 많은 아이템 이름/이동 작업 처리:

```bash
cli-anything-eagle bridge install-plugin
cli-anything-eagle --json bridge status
cli-anything-eagle --json bridge doctor --skip-ping
cli-anything-eagle --json --dry-run bridge cleanup --max-age-hours 24
cli-anything-eagle --json item selected
cli-anything-eagle --json folder selected
cli-anything-eagle --json app show
cli-anything-eagle --dry-run item open --item-id EXAMPLE --window
cli-anything-eagle --json tag recent-live --top 10
cli-anything-eagle --json tag starred-live --top 10
cli-anything-eagle --dry-run tag rename-live "Old Tag" "New Tag"
cli-anything-eagle --dry-run tag merge-live "Legacy Tag" "Canonical Tag"
cli-anything-eagle --dry-run item rename-bulk --folder-name References --prefix archived-
cli-anything-eagle --dry-run item move-bulk --tag reviewed --target-folder-path "Archive/Reviewed"
```

현재 Eagle UI selection에 직접 작업:

```bash
cli-anything-eagle --json bridge selected-item-ids
cli-anything-eagle --dry-run item bulk-update --current-selection --add-tag reviewed
cli-anything-eagle --dry-run item rename-bulk --current-selection --prefix archived-
cli-anything-eagle --dry-run item move-bulk --current-selection --target-folder-path "Archive/Reviewed"
cli-anything-eagle --dry-run organize apply --current-selection --add-tag reviewed --name-prefix ui-
```

selection 기반 필터는 audit, tag 정리, report에도 사용 가능:

```bash
cli-anything-eagle --json audit cleanup --current-selection --sample-limit 10
cli-anything-eagle --json tag stats --selection live-selection --top 20
cli-anything-eagle --dry-run tag normalize --selection live-selection --trim --collapse-spaces
cli-anything-eagle report tags ./reports/live-selection-tags.json --selection live-selection --format json
```

현재 Eagle 폴더를 재사용 가능한 대상이나 selection으로 저장:

```bash
cli-anything-eagle --json report current-context ./reports/current-context.json
cli-anything-eagle select save-current-folder live-folder
cli-anything-eagle --dry-run item move-to-current-folder --selection review-set
```

구형 Eagle plugin 런타임에서 `eagle.item.select(itemIds)`를 제공하지 않으면,
`bridge select-items`는 단일 아이템 요청에 한해 `open()`으로 폴백하고,
실제로 selection이 바뀌었는지까지 같이 보고합니다.

중복 후보와 정리 핫스팟 audit:

```bash
cli-anything-eagle --json audit duplicates --all --mode name --mode url --top 20
cli-anything-eagle --json audit cleanup --all --sample-limit 10
cli-anything-eagle --json audit dedupe-plan ./plans/duplicate-trash.json --keyword ui --mode name-size --keep largest
cli-anything-eagle --json plan stats ./plans/duplicate-trash.json
```

한 번에 실행하는 고수준 organize workflow:

```bash
cli-anything-eagle --dry-run organize apply \
  --folder-path "Design/UI/References" \
  --add-tag reviewed \
  --name-prefix ui- \
  --ensure-target-path "Archive/UI Reviewed" \
  --max-items 100 \
  --save-snapshot ./snapshots/ui-reviewed.json
```

mutation plan 저장 후 나중에 적용:

```bash
cli-anything-eagle --dry-run item bulk-update \
  --folder-path "Design/UI/References" \
  --add-tag reviewed \
  --save-plan ./plans/reviewed.json

cli-anything-eagle plan show ./plans/reviewed.json
cli-anything-eagle plan stats ./plans/reviewed.json
cli-anything-eagle plan apply ./plans/reviewed.json
```

bridge 기반 plan도 동일하게 사용 가능:

```bash
cli-anything-eagle --dry-run item rename-bulk \
  --item-file ./exports/cleanshot.json \
  --prefix archived- \
  --save-plan ./plans/rename.json

cli-anything-eagle plan stats ./plans/rename.json
cli-anything-eagle plan apply ./plans/rename.json
```

저장된 plan 설명 확인 또는 workflow 템플릿 생성:

```bash
cli-anything-eagle workflow template --list
cli-anything-eagle workflow template review-batch ./workflow.yml
cli-anything-eagle --json workflow validate ./workflow.yml
cli-anything-eagle --json plan explain ./plans/rename.json --output ./plans/rename.md --format md
```

대규모 정리 전 태그 audit 및 정규화:

```bash
cli-anything-eagle --json tag stats --all --top 25
cli-anything-eagle --json tag audit --all --top 25
cli-anything-eagle --dry-run tag normalize \
  --all \
  --trim \
  --collapse-spaces \
  --save-plan ./plans/normalize-tags.json

cli-anything-eagle --dry-run tag alias-map-apply ./tag-aliases.yaml \
  --all \
  --save-plan ./plans/tag-aliases.json
```

재사용 가능한 item selection 저장 및 비교:

```bash
cli-anything-eagle select save review-set --keyword review --all
cli-anything-eagle select sample review-set --count 10 --resolve
cli-anything-eagle select diff review-set archived-set
cli-anything-eagle select save-current live-selection
```

재사용 가능한 리포트와 workflow plan 생성:

```bash
cli-anything-eagle report library ./reports/library.md --format md
cli-anything-eagle report tags ./reports/tags.csv --all --top 100 --format csv
cli-anything-eagle report folders ./reports/folders.md --all --format md
cli-anything-eagle report trend ./reports/trend.json --all --bucket month --field modification

cli-anything-eagle workflow validate ./workflow.yml
cli-anything-eagle --dry-run workflow run ./workflow.yml --save-plan ./plans/workflow.json
cli-anything-eagle plan validate ./plans/workflow.json
cli-anything-eagle plan split ./plans/workflow.json ./plans/chunks --max-operations 25
cli-anything-eagle plan merge ./plans/all.json ./plans/chunks/*.json
cli-anything-eagle report index ./reports/index.json ./reports ./plans ./snapshots
```

이제 workflow selection도 현재 Eagle UI를 직접 가리킬 수 있습니다:

```yaml
kind: eagle-cli-workflow
selection:
  current_folder: true
  fetch_all: true
steps:
  - action: snapshot
    output: ./snapshots/current-folder.json
```

manifest, 증분 watch, 셸 completion, 내장 schema 활용:

```bash
cli-anything-eagle ingest manifest ./manifests/assets.json --folder-path "Design/UI/References"
cli-anything-eagle --dry-run watch import-dir ./incoming --recursive --ext png --tag-from-name
cli-anything-eagle completion script --shell zsh --output ./completions/cli-anything-eagle.zsh
cli-anything-eagle schema show workflow --output ./schemas/workflow.json
```

공통 CLI 기본값을 한 번 저장하고 재사용:

```bash
cli-anything-eagle config set report_format md
cli-anything-eagle config set export_format jsonl
cli-anything-eagle config set completion_shell fish
cli-anything-eagle config show
cli-anything-eagle config unset completion_shell
```

AI 에이전트가 안전하게 Eagle을 다루도록 observe -> plan -> apply -> verify 루프 실행:

```bash
cli-anything-eagle --json agent observe --output ./reports/agent-observe.json
cli-anything-eagle --json agent plan ./plans/review-selection.json \
  --goal "Review current selection" \
  --current-selection \
  --add-tag reviewed \
  --save-snapshot ./snapshots/review-selection.json
cli-anything-eagle --json --dry-run agent apply ./plans/review-selection.json \
  --save-results ./plans/review-selection-preview.json
cli-anything-eagle --json agent apply ./plans/review-selection.json \
  --save-results ./plans/review-selection-results.json
cli-anything-eagle --json agent verify ./plans/review-selection.json
```

현재 Eagle 폴더를 기준으로 plan을 만들 수도 있습니다:

```bash
cli-anything-eagle --json agent plan ./plans/review-folder.json \
  --goal "Review current folder" \
  --current-folder \
  --add-tag reviewed
cli-anything-eagle --json agent plan ./plans/move-into-current-folder.json \
  --goal "Move current selection into the current folder" \
  --current-selection \
  --move-to-current-folder
```

현재 Eagle selection이 비어 있어도, 명시적 아이템 1개를 대상으로 전체 루프를 스모크 테스트한 뒤
즉시 복원할 수 있습니다:

```bash
cli-anything-eagle --json snapshot create ./snapshots/smoke.json --item-id EXAMPLE
cli-anything-eagle --json agent plan ./plans/smoke.json \
  --goal "Smoke test one item" \
  --item-id EXAMPLE \
  --add-tag smoke-test
cli-anything-eagle --json agent apply ./plans/smoke.json
cli-anything-eagle --json agent verify ./plans/smoke.json
cli-anything-eagle --json snapshot restore ./snapshots/smoke.json
```

## 지원 명령

- `doctor`
- `agent observe`, `plan`, `apply`, `verify`
- `config path`, `show`, `set`, `unset`
- `app info`
- `app show`
- `library info`, `history`, `switch`, `icon`, `summary`, `quick-access`
- `smart-folder list`, `tree`, `show`, `rules`, `audit`, `run`
- `tag stats`, `audit`, `rename`, `normalize`, `alias-map-apply`
- `tag recent-live`, `starred-live`
- `tag rename-live`, `merge-live`
- `tag-group list`, `show`
- `folder list`, `tree`, `find`, `selected`, `open`, `recent`, `create`, `ensure`, `ensure-path`, `rename`, `update`
- `item list`, `selected`, `select`, `open`, `export`, `stats`, `info`, `thumbnail`, `update`, `bulk-update`, `rename-bulk`, `move-bulk`, `move-to-current-folder`
- `item add-path`, `add-paths`, `add-dir`, `add-url`, `add-urls`, `add-bookmark`
- `item trash`, `refresh-palette`, `refresh-thumbnail`
- `select list`, `save`, `show`, `delete`, `sample`, `diff`, `save-current-folder`
- `report library`, `index`, `tags`, `folders`, `trend`, `current-context`
- `report dashboard`
- `preset list`, `show`, `delete`, `export`, `import`, `save-item-list`, `run-item-list`, `save-bulk-update`, `run-bulk-update`
- `snapshot create`, `show`, `diff`, `restore`
- `audit duplicates`, `cleanup`, `cleanup-plan`, `dedupe-plan`
- `organize apply`
- `bridge status`, `doctor`, `context`, `selected-item-ids`, `open-folder`, `select-items`, `cleanup`, `export-plugin`, `install-plugin`, `ping`
- `workflow template`, `validate`, `run`
- `ingest manifest`
- `watch import-dir`
- `completion script`
- `schema show`
- `plan show`, `stats`, `save-last`, `apply`, `merge`, `split`, `filter`, `explain`, `validate`, `rollback-from-results`
- `raw request`

## 참고 사항

- 이 harness는 로컬에서 실제 응답이 확인된 Eagle API 변형을 기준으로 작성되었습니다:
  `GET /api/application/info`, `GET /api/library/info`, `GET /api/folder/list`,
  `GET /api/item/list`
- 최신 Eagle Web API v2 문서도 존재하지만, 이 프로젝트는 테스트한 Eagle 빌드에서 실제로 응답한 API에 맞춰 최적화되어 있습니다.
- CLI는 세션 상태와 프리셋을 `~/.config/cli-anything-eagle`에 저장합니다.
  기존 `~/.config/eagle-agent-harness` 상태는 레거시 fallback으로 읽습니다.
- 세션 상태 쓰기는 원자적으로 처리되며, 손상된 세션 파일은 다음 로드 시 CLI를 죽이지 않고
  `session.corrupt-<timestamp>.json`으로 옆으로 치워둡니다.
- 프리셋, plan, report, manifest, bridge 요청, watch 상태 파일도 모두 원자적 쓰기를 사용하므로
  장시간 실행이나 동시 실행 중 부분 JSON이 남을 가능성이 줄었습니다.
- `--last`는 세션 상태에 기록된 바로 직전 item-producing 명령의 item ID를 재사용합니다.
  병렬 실행보다 순차 워크플로우에서 사용하는 것이 적합합니다.
- `smart-folder run`은 의도적으로 보수적으로 동작합니다.
  Eagle 규칙에 non-`AND` 그룹 같은 미지원 로직이 있으면, 명시적으로 `--allow-partial`을 주지 않는 한 중단됩니다.
- `item bulk-update`는 `--max-items`, `--require-match`, `--skip-unchanged`, `--save-matches`로 안전 경계를 둘 수 있습니다.
- `item bulk-update`, `rename-bulk`, `move-bulk`, `organize apply`, `snapshot restore`는 모두 재사용 가능한 plan 저장을 지원합니다.
  `plan apply`는 직접 HTTP 작업뿐 아니라 bridge 기반 rename/move 작업도 지원합니다.
- `snapshot` 파일은 일반 JSON 문서이므로, 별도 백업에 보관하거나 restore 전에 사람이 직접 검토할 수 있습니다.
- `audit dedupe-plan`은 재사용 가능한 휴지통 plan만 기록하며, 자체적으로 삭제나 휴지통 이동을 실행하지 않습니다.
- `item rename-bulk`, `item move-bulk`, `organize apply`는 이름이나 폴더 배치를 로컬 HTTP API 대신
  Eagle Plugin API로 바꿔야 할 때 companion bridge plugin에 의존합니다.
- `agent observe`는 Eagle의 library metadata 엔드포인트가 잠깐 실패해도 계속 동작하도록 만들었지만,
  `agent observe`, `agent plan --current-selection`, `agent plan --current-folder`,
  `agent plan --move-to-current-folder`는 모두 companion bridge 상태가 건강해야 합니다.
- `bridge install-plugin`은 번들된 service plugin을 Eagle plugin 디렉터리로 복사합니다.
  plugin 디렉터리를 명시하지 않으면 감지된 모든 Eagle plugin 루트를 갱신합니다.
  Eagle이 이미 열려 있다면 백그라운드 bridge가 시작되도록 한 번 재시작하세요.
- companion plugin 템플릿은 Python 패키지 내부 `cli_anything/eagle/assets/companion-plugin`에도 들어 있으므로,
  wheel 설치에서도 저장소 checkout 없이 plugin export/install이 가능합니다.
- `bridge status`, `bridge doctor`는 heartbeat freshness, queue backlog, 쓰기 가능한 bridge 디렉터리,
  설치된 plugin 빌드가 현재 CLI 버전과 맞는지까지 요약합니다.
- `bridge selected-item-ids`는 selection 기반 워크플로우에서 가장 좁은 bridge probe이며,
  `--current-selection`도 내부적으로 이것을 사용합니다.
- `item selected`, `folder selected`는 companion plugin을 통해 현재 Eagle UI selection을 읽습니다.
  `item open`, `tag rename-live`, `tag merge-live`도 bridge plugin이 활성화되어 있어야 합니다.
- `app show`는 `eagle.app.show()`에 의존하며, Eagle 문서 기준 build18+ Plugin API 기능입니다.
- `tag starred-live`는 `eagle.tag.getStarredTags()`에 의존하며, Eagle 문서 기준 build18+ Plugin API 기능입니다.
  `tag recent-live`는 `eagle.tag.getRecentTags()`만 필요합니다.
- `bridge cleanup`은 오래된 bridge request/response 산출물만 지웁니다.
  어떤 파일이 지워질지 먼저 보고 싶다면 `--dry-run`을 먼저 사용하세요.
- 변경 명령은 대부분 `--dry-run`을 지원하므로, 다른 Eagle 사용자와 공유할 때도 먼저 미리볼 수 있습니다.
