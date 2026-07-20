# 텔레그램 알림 설정 가이드

`telegram_notifier.py`가 매일 자산군 추천 결과(티커/구분/액션/종가 요약 표 + 일일 리포트 URL 링크 1건, v3.0부터 종목별 차트 이미지 첨부는 하지 않음 — 차트는 리포트 안에 있음)를 보내기 위한 설정 절차입니다. `recommendation_engine.run_asset_class_recommendations`(즉 GitHub Actions의 `recommend.yml` 크론)에서만 발동하고, Streamlit UI에서 "조회" 버튼을 눌러 보는 것으로는 발송되지 않습니다.

## 1. 봇 생성 (@BotFather)
1. 텔레그램에서 **[@BotFather](https://t.me/BotFather)** 검색 후 대화 시작
2. `/newbot` 전송
3. 봇 이름(표시용), 봇 사용자명(반드시 `bot`으로 끝나야 함, 예: `my_invest_alert_bot`) 순서대로 입력
4. 완료되면 **봇 토큰**이 발급됨 (`123456789:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` 형식) — 이게 `TELEGRAM_BOT_TOKEN`

## 2. chat_id 확인
1. 방금 만든 봇을 검색해서 대화 시작 → 아무 메시지나 하나 전송 (예: "hi")
   - 그룹방에서 알림받고 싶으면 그 봇을 그룹에 초대한 뒤 그룹에 아무 메시지나 전송
2. 브라우저에서 아래 주소 접속 (`<봇토큰>` 자리에 1단계에서 받은 토큰 입력):
   ```
   https://api.telegram.org/bot<봇토큰>/getUpdates
   ```
3. 응답 JSON에서 `"chat":{"id": 123456789, ...}` 부분의 **`id` 값**이 `TELEGRAM_CHAT_ID`
   - 개인 대화면 양수, 그룹이면 보통 음수(`-` 포함)로 나옴 — 그대로 사용하면 됨
   - 응답이 비어있다면(`"result":[]`) 1단계에서 메시지를 안 보낸 것이니 다시 보내고 새로고침

## 3. `.env` 작성 (로컬 테스트용)
`.env.example`을 참고해 아래 값 채우기:
```
TELEGRAM_BOT_TOKEN=<1단계에서 받은 토큰>
TELEGRAM_CHAT_ID=<2단계에서 확인한 chat_id>
```

## 4. 로컬 테스트
```
python -c "import telegram_notifier; telegram_notifier.send_message('테스트 메시지입니다')"
```
- 텔레그램 앱(또는 그룹)에 메시지가 도착하면 성공
- 실패 시 `TELEGRAM_BOT_TOKEN` 또는 `TELEGRAM_CHAT_ID`가 잘못 설정된 것 — 특히 `getUpdates` 응답을 다시 확인

전체 추천 알림 플로우(요약 + 차트)까지 확인하려면:
```
python -c "
from drive_db import DriveDB
import recommendation_engine
recommendation_engine.run_asset_class_recommendations(DriveDB())
"
```
`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`가 설정돼 있으면 자동으로 텔레그램 발송까지 이어집니다 (설정 안 돼 있으면 조용히 스킵하고 로그만 남김).

## 5. GitHub Actions에 등록
`recommend.yml` 크론에서 실제로 발송되려면 저장소 시크릿에도 등록해야 합니다:
```
gh secret set TELEGRAM_BOT_TOKEN --repo <owner>/<repo>
gh secret set TELEGRAM_CHAT_ID --repo <owner>/<repo>
```
(또는 GitHub 저장소 → Settings → Secrets and variables → Actions에서 직접 추가)

**중요**: 로컬 `.env`만 바꾸는 것으로는 GitHub Actions 크론에 반영되지 않는다 — 로컬 실행과 GitHub Actions는 값을 완전히 별도로 읽는다(로컬은 `.env`, 워크플로는 저장소 Secrets). 둘 다 갱신해야 한다. `gh secret list`로 각 Secret이 마지막으로 언제 갱신됐는지 확인할 수 있으니, `.env`를 바꾼 뒤에는 이 명령으로 `TELEGRAM_CHAT_ID`도 같은 날짜로 갱신됐는지 대조해 볼 것.

## 6. 1:1 채팅 → 그룹 채팅으로 전환하기
여러 명이 같이 알림을 받고(초대/추방도 가능하게) 싶다면:
1. 텔레그램 앱에서 새 그룹 생성 → 원하는 사람 초대.
2. 그 그룹에 봇도 멤버로 추가(사용자명으로 검색). 발송 전용이라 관리자 권한은 필요 없음.
3. 그룹에 아무 메시지나 하나 보낸 뒤 위 **2. chat_id 확인**을 다시 수행 — 그룹 chat_id는 음수(`-`로 시작)로 나온다.
4. `.env`와 GitHub Secret `TELEGRAM_CHAT_ID`를 새 그룹 id로 **둘 다** 교체(바로 위 "중요" 참고).
5. `recommend.yml`을 `workflow_dispatch`로 한 번 수동 실행해서(아래 7절의 `skip_llm_and_news=true`로 API 비용 없이) 새 그룹에 메시지가 오는지 확인.

## 7. 수동 테스트 시 LLM/뉴스 API 호출 없이 실행하기 (v3.5)
`recommend.yml`을 GitHub Actions 탭에서 "Run workflow"로 수동 실행할 때 `skip_llm_and_news` 입력을 체크(기본값 `true`)하면 Exa 뉴스 수집과 OpenRouter LLM 호출을 건너뛰고 규칙 기반 설명으로 대체한다 — 파이프라인/리포트/텔레그램 배관만 확인하고 싶을 때(예: 이 문서의 그룹 전환 테스트) API 사용량을 아낄 수 있다. `gh` CLI로는 `gh workflow run recommend.yml -f skip_llm_and_news=true`. 실제 뉴스/LLM 분석까지 포함해 검증하려면 `-f skip_llm_and_news=false`로 실행할 것 — 매일 자동으로 도는 스케줄 실행(`workflow_run` 트리거)에는 이 입력 자체가 없어 항상 실제 호출이 일어난다.

## 트러블슈팅

**`getUpdates` 응답이 계속 `"result":[]`로 빈 채로 나옴**
→ 봇과의 대화(또는 그룹)에 메시지를 먼저 보내지 않은 것. 텔레그램 봇은 사용자가 먼저 말을 걸어야 그 대화의 정보를 조회할 수 있음.

**`send_message` 호출 시 401 Unauthorized**
→ 봇 토큰이 잘못됨. @BotFather에서 `/mybots` → 해당 봇 선택 → "API Token"으로 재확인.

**`send_message` 호출 시 400 Bad Request (chat not found)**
→ `chat_id`가 잘못됨. 그룹인데 봇을 그룹에서 추방했거나, 개인/그룹 id를 혼동했을 가능성, 또는 `.env`만 바꾸고 GitHub Secret은 안 바꿨을 가능성(5절 참고). 2단계를 다시 수행해 정확한 id 확인.

**GitHub Actions에서는 안 오는데 로컬 테스트는 됨**
→ 거의 항상 Secret이 `.env`와 다른 값으로 남아있는 경우. `gh secret list`로 `TELEGRAM_CHAT_ID`가 마지막으로 언제 갱신됐는지 확인해 `.env`를 바꾼 시점과 대조할 것.
