# 텔레그램 알림 설정 가이드

`telegram_notifier.py`가 매일 자산군 추천 결과(요약 텍스트 + 매수/매도 종목 차트 이미지)를 보내기 위한 설정 절차입니다. `recommendation_engine.run_asset_class_recommendations`(즉 GitHub Actions의 `recommend.yml` 크론)에서만 발동하고, Streamlit UI에서 "조회" 버튼을 눌러 보는 것으로는 발송되지 않습니다.

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

## 트러블슈팅

**`getUpdates` 응답이 계속 `"result":[]`로 빈 채로 나옴**
→ 봇과의 대화(또는 그룹)에 메시지를 먼저 보내지 않은 것. 텔레그램 봇은 사용자가 먼저 말을 걸어야 그 대화의 정보를 조회할 수 있음.

**`send_message`/`send_photo` 호출 시 401 Unauthorized**
→ 봇 토큰이 잘못됨. @BotFather에서 `/mybots` → 해당 봇 선택 → "API Token"으로 재확인.

**`send_message`/`send_photo` 호출 시 400 Bad Request (chat not found)**
→ `chat_id`가 잘못됨. 그룹인데 봇을 그룹에서 추방했거나, 개인/그룹 id를 혼동했을 가능성. 2단계를 다시 수행해 정확한 id 확인.

**차트 이미지가 하나도 안 옴**
→ 정상일 수 있음 — 오늘 매수/매도 시그널이 발생한 종목이 없으면(전부 HOLD) 요약 텍스트만 오고 차트는 첨부되지 않음 (의도된 동작, [investment_assistant_spec.md](investment_assistant_spec.md) 참고).
