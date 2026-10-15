# PoCareers

POSTECH 현장실습 온라인 시스템(SES)에 올라온 **현장실습 공고를 기업별로 모아 보는 웹사이트**와,
**새 공고가 올라오면 이메일로 알려 주는 스케줄러**입니다. `run.py` 하나로 둘 다 실행됩니다.
화면 구조·디자인(데스크톱/모바일, 다크 모드)은 Commeet 과 같은 디자인 시스템을 따릅니다.

## 화면
| 경로 | 내용 |
|------|------|
| `/` | 모집 기간(SES 탭)별 카드 + 필터(검색·기관 구분·지역·학과) + 기업별 공고 카드 |
| `/company/{id}` | 기업 상세 - 회사 소개, 공고별 실습기간·접수마감·모집·지원금, SES 상세 항목 전체 |
| `/calendar` | 마감 캘린더 - 접수마감(기본)·면접·최종선발·실습시작 일정, 기간별 필터 |
| `/admin` | 관리자 - 메일 수신자 추가/삭제/테스트 메일, 수신자별 관심 공고, 수집 상태, "지금 점검" |

SES 는 같은 시즌이라도 **실습 기간별로 탭이 나뉘어** 있습니다
(예: `2026 포스텍 동계 SES (8주~9주)`, `(4주이상~8주미만)`). 진행 중인 탭을 모두 수집하고,
각 공고에 어느 기간인지 색 배지로 표시합니다.

## 동작 방식
1. 저장된 세션으로 `현장실습 기관조회` 접근 (만료 시 SSO 자동 재로그인, Playwright)
2. 진행 중인 모든 기간 탭 × 모든 페이지의 공고 목록 수집
3. 공고별 상세(`/jobInternDetail.do`)를 받아 `state/postings.json` 에 저장 (웹 화면의 데이터)
   - 상세는 새 공고·목록 값이 바뀐 공고만 받고, 그 외에는 `DETAIL_REFRESH_HOURS` 마다 갱신
4. `state/seen.json`(이미 보낸 공고, SES 공고번호 기준)과 비교해 **신규 공고만** 메일 발송

> 최초 실행 시에는 기존 공고를 "기준선"으로만 저장하고 메일을 보내지 않습니다.
> SES 목록에서 내려간 공고는 지우지 않고 "마감"으로 남겨 둡니다 (홈의 "마감된 공고도 보기").

## 설정
```bash
uv sync
uv run playwright install --with-deps chromium   # Ubuntu 서버는 --with-deps 권장
cp .env.example .env
```

| 키 | 설명 |
|----|------|
| `SES_ID` / `SES_PW` | SES(통합 SSO) 학생 아이디/비밀번호 |
| `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` | 알림 메일 발신 Gmail 과 앱 비밀번호 |
| `STARTUP_MAIL` | 서버가 켜질 때 시작 알림 메일 발송 여부 (기본 `true`, `false` 로 끔) |
| `BOARD_ENABLED` | POSTECH 전자게시판 "인턴 및 채용 공고" 새 글 점검 (기본 `true`). 수신자별 on/off 는 관리자 화면 |
| `CHECK_INTERVAL_MINUTES` | 점검 주기 (기본 10분) |
| `DETAIL_REFRESH_HOURS` | 상세 페이지 재수집 주기 (기본 6시간) |
| `HOST` / `PORT` | 웹 서버 주소 (기본 `127.0.0.1:7007`, 외부 접속은 `HOST=0.0.0.0`) |
| `BASE_URL` | 외부 접속 주소. 알림 메일에 "공고 모아보기" 링크로 들어감 |
| `ADMIN_ID` / `ADMIN_PASSWORD` | `/admin` 관리자 로그인 계정 |

메일 수신자는 웹의 **관리자 화면**에서 관리합니다 (`recipients.json` 에 저장).

수신자마다 **관심 공고**를 고를 수 있습니다. 점검 때 그 공고의 지원자 수가 지난번 알린 값보다
늘었으면 그 사람에게 "[지원자 알림]" 메일을 보냅니다 (기준값은 `state/watch_counts.json`).

## 실행
```bash
uv run run.py                  # 메일 스케줄러 + 웹 서버 (기본)
uv run run.py --dry-run        # 메일 발송 없이 동작
uv run run.py --no-web         # 스케줄러만
uv run run.py --no-scheduler   # 웹 서버만 (저장된 공고만 보여 줌)
uv run run.py --once           # 1회 점검 후 종료 (cron 용)
uv run run.py --show           # 브라우저 창 띄워 로그인 확인(디버그)
```

- 상주 모드로 **처음 켜지면 "알림 시스템이 시작되었습니다" 메일을 1회** 보냅니다 (`.env` 의 `STARTUP_MAIL=false` 로 끌 수 있음).
- 점검 중 일시적 오류가 나도 프로세스는 죽지 않고 다음 주기에 재시도하며, 오류는 관리자 화면에 표시됩니다.

## 구조
```
run.py                 진입점 (스케줄러 스레드 + uvicorn)
app/
  config.py            .env 로드, 경로
  main.py              FastAPI 앱 (보안 헤더, 라우터)
  core/                세션 쿠키·로그인 제한, 템플릿
  routes/              페이지 / 로그인 / 공고 API / 관리자 API
  services/
    ses_client.py      SES 로그인·목록·상세 수집 (Playwright)
    parser.py          기간 탭·공고 표·상세 항목 파싱
    scheduler.py       점검 루프, 신규 판정, 발송
    store.py           state/*.json, recipients.json 읽기/쓰기
    views.py           기업별 묶음, 마감 D-day 등 화면용 가공
    notify.py          Gmail 발송
  templates/, static/  화면 (Commeet 디자인 시스템)
```
