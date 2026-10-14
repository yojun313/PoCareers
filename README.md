# SES Notify

POSTECH 현장실습 온라인 시스템(SES)에 **새 현장실습 기관 공고가 올라오면 이메일로 알림**을 보내는 도구입니다.
학생 통합 SSO 로그인(ECDH+SEED 암호화)을 실제 헤드리스 브라우저(Playwright)로 처리하고,
한 번 알림을 보낸 공고는 다시 보내지 않습니다.

## 동작 방식
1. 저장된 세션으로 `현장실습 기관조회` 페이지 접근 (만료 시 자동 재로그인)
2. 공고 표를 파싱해 각 공고의 고유 키 생성
3. `state/seen.json`(이미 보낸 공고)과 비교해 **신규 공고만** 추출
4. `recipients.json`의 모든 수신자에게 Gmail로 발송 후 `seen.json` 갱신

> 최초 실행 시에는 기존 공고를 "기준선"으로만 저장하고 메일을 보내지 않습니다.
> (그 이후 새로 올라오는 공고부터 알림)

## 설정
```bash
# 1) 의존성 설치 (uv)
uv sync
uv run playwright install --with-deps chromium   # Ubuntu 서버는 --with-deps 권장

# 2) 자격증명
cp .env.example .env            # SES 로그인 + Gmail 발신 계정 입력
cp recipients.example.json recipients.json   # 알림 받을 이메일 목록(JSON 배열)
```

`.env` 항목:
| 키 | 설명 |
|----|------|
| `SES_ID` / `SES_PW` | SES(통합 SSO) 학생 아이디/비밀번호 |
| `SES_GROUP` | 로그인 그룹 (학생=1) |
| `GMAIL_ADDRESS` | 알림 메일을 보내는 Gmail 주소 |
| `GMAIL_APP_PASSWORD` | Gmail 앱 비밀번호 (2단계 인증 > 앱 비밀번호) |

`recipients.json` — 알림 받을 주소 목록:
```json
["someone@gmail.com", "another@postech.ac.kr"]
```

## 실행
```bash
uv run run.py             # 1회 점검 + 신규 공고 메일 발송
uv run run.py --dry-run   # 발송 없이 신규 공고만 출력
uv run run.py --show      # 브라우저 창 띄워 동작 확인(디버그)
```

## 주기 실행 (예시)
- **cron** (리눅스, 10분마다):
  ```cron
  */10 * * * * cd /path/to/ses-notify && /path/to/uv run run.py >> state/cron.log 2>&1
  ```

## 비고
- `.env`, `state/`, `recipients.json` 은 `.gitignore` 로 제외됩니다(민감정보).
- 공고 표가 비어 있으면("데이터가 없습니다") 모집 시즌이 아니거나 이력서/자기소개서 미작성 상태일 수 있습니다.
