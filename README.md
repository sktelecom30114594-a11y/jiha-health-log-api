# 마이 헬스 로그 API

> 흩어진 개인 건강 기록을 날짜별로 저장하고, 장기 변화와 위험 상태를 자동으로 확인할 수 있도록 만든 REST API입니다.

FastAPI와 SQLite를 활용해 만든 개인 건강 기록 관리 REST API입니다.  
사용자는 계정을 생성한 뒤 체중, 키, 혈압, 공복혈당, 걸음 수, 수면 시간, 메모를 날짜별로 기록하고 조회·수정·삭제할 수 있습니다.

입력된 건강 수치를 바탕으로 BMI와 건강 상태를 자동 계산하며, 날짜 범위 검색과 전체 통계 기능도 제공합니다.

기본 CRUD 요구사항에 더해 다중 사용자 인증, 사용자별 데이터 분리, SQLite 영구 저장, 자동 테스트, 현실형 합성 데이터, Docker 볼륨 영속성, 주간 리포트, HTML 대시보드를 선택 확장 기능으로 구현했습니다.

---

## 1. 주요 기능

### 사용자

- 회원가입
- Argon2 비밀번호 해시 저장
- HTTP Basic Authentication 로그인
- 현재 사용자 정보 조회
- 사용자별 데이터 접근 분리

### 건강 기록

- 건강 기록 생성
- 전체 기록 조회 (개수·정렬 순서 지정 가능)
- 단건 기록 조회
- 기록 수정
- 기록 삭제
- 날짜 범위 검색
- 전체 기록 통계

### 자동 건강 분석

- BMI 계산
- BMI 상태 분류
- 혈압 상태 분류
- 공복혈당 상태 분류
- 위험 수준에 따른 경고 메시지 생성

### 리포트 · 대시보드

- 최근 7일과 직전 7일을 비교하는 주간 리포트 제공
- 로그인 후 최근 기록·주간 리포트를 확인할 수 있는 HTML 대시보드 화면 제공

### 데이터 저장

- SQLite 영구 저장
- 서버 재시작 후 데이터 유지
- 사용자별 동일 날짜 기록 중복 방지
- Docker named volume을 이용한 DB 영속성 지원

---

## 2. 기술 스택

| 구분 | 기술 |
|---|---|
| Language | Python |
| API Framework | FastAPI |
| Validation | Pydantic |
| Database | SQLite |
| Authentication | HTTP Basic Authentication |
| Password Hashing | pwdlib, Argon2 |
| ASGI Server | Uvicorn |
| Test | FastAPI TestClient |
| Container | Docker, Docker Compose |

---

## 3. 프로젝트 구조

```text
jiha-health-log-api/
├─ main.py
├─ seed_year_data.py
├─ test_sqlite_smoke.py
├─ dashboard.html
├─ requirements.txt
├─ Dockerfile
├─ compose.yaml
├─ .dockerignore
├─ .gitignore
├─ PRD_마이_헬스_로그_API_v2.md
└─ README.md
```

### 주요 파일

| 파일 | 역할 |
|---|---|
| `main.py` | FastAPI 애플리케이션 본체 |
| `seed_year_data.py` | 3명의 데모 사용자와 1년치 합성 데이터 생성 |
| `test_sqlite_smoke.py` | 회원가입·인증·CRUD·검색·통계·리포트·대시보드·영속성 자동 검증 |
| `dashboard.html` | 로그인·최근 기록·주간 리포트를 보여주는 읽기 전용 HTML 대시보드 |
| `Dockerfile` | API Docker 이미지 생성 |
| `compose.yaml` | API 실행과 SQLite 볼륨 연결 |
| `PRD_마이_헬스_로그_API_v2.md` | 프로젝트 요구사항 및 데이터 정책 |

---

## 4. 데이터베이스 구조

### users

| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | INTEGER | 사용자 고유 ID |
| username | TEXT | 고유 사용자명 |
| hashed_password | TEXT | Argon2 비밀번호 해시 |
| created_at | TEXT | 가입 시각 |

### health_records

| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | INTEGER | 기록 고유 ID |
| user_id | INTEGER | 기록 소유 사용자 |
| date | TEXT | 측정일 |
| weight | REAL | 몸무게 |
| height | REAL | 키 |
| systolic | INTEGER | 수축기 혈압 |
| diastolic | INTEGER | 이완기 혈압 |
| blood_sugar | INTEGER | 공복혈당 |
| steps | INTEGER | 하루 걸음 수 |
| sleep_hours | REAL | 수면 시간 |
| memo | TEXT | 메모 |
| created_at | TEXT | 생성 시각 |
| updated_at | TEXT | 수정 시각 |

관계:

```text
users 1 ───────── N health_records
```

한 사용자는 같은 날짜의 건강 기록을 한 건만 저장할 수 있습니다.

```sql
UNIQUE(user_id, date)
```

---

## 5. 계산 필드 정책

다음 값은 SQLite에 직접 저장하지 않습니다.

- `bmi`
- `bmi_category`
- `bp_category`
- `sugar_category`
- `warnings`

이 값들은 원본 건강 수치를 바탕으로 API 응답 시 다시 계산됩니다.

이 방식은 건강 분류 기준이 변경되더라도 기존 DB 값과 계산 기준이 불일치하는 문제를 줄일 수 있습니다.

주간 리포트의 평균값과 증감값도 같은 원칙으로, DB에 저장하지 않고 `GET /reports/weekly` 호출 시점에 원본 기록으로부터 매번 다시 계산됩니다.

---

## 6. 건강 상태 분류 기준

### BMI

```text
BMI = 몸무게(kg) / 키(m)²
```

| 범위 | 분류 |
|---|---|
| 18.5 미만 | 저체중 |
| 18.5 이상 23 미만 | 정상 |
| 23 이상 25 미만 | 과체중 |
| 25 이상 | 비만 |

### 혈압

| 조건 | 분류 |
|---|---|
| 수축기 140 이상 또는 이완기 90 이상 | 고혈압 |
| 수축기 120 이상 또는 이완기 80 이상 | 주의 |
| 그 외 | 정상 |

### 공복혈당

| 범위 | 분류 |
|---|---|
| 100 미만 | 정상 |
| 100 이상 126 미만 | 공복혈당장애 |
| 126 이상 | 당뇨 의심 |

> 본 분류는 프로젝트 시연용 규칙이며 의료 진단을 대체하지 않습니다.

---

## 7. API 목록

| Method | Endpoint | 설명 | 인증 |
|---|---|---|---|
| GET | `/` | 서버 상태 확인 | 불필요 |
| POST | `/users/register` | 회원가입 | 불필요 |
| POST | `/users/login` | 로그인 확인 | 필요 |
| GET | `/users/me` | 현재 사용자 조회 | 필요 |
| POST | `/records` | 건강 기록 생성 | 필요 |
| GET | `/records` | 전체 기록 조회 | 필요 |
| GET | `/records/{record_id}` | 단건 기록 조회 | 필요 |
| PUT | `/records/{record_id}` | 기록 전체 수정 | 필요 |
| DELETE | `/records/{record_id}` | 기록 삭제 | 필요 |
| GET | `/search` | 날짜 범위 검색 | 필요 |
| GET | `/stats` | 전체 기록 통계 | 필요 |
| GET | `/reports/weekly` | 최근 7일과 직전 7일을 비교하는 주간 리포트 | 필요 |
| GET | `/dashboard` | 로그인·최근 기록·주간 리포트를 보여주는 HTML 화면 | 불필요 |

`GET /records`는 `limit`(1~100, 기본값 전체)과 `order`(`asc`/`desc`, 기본값 `asc`) 쿼리 파라미터로 반환 개수와 정렬 순서를 지정할 수 있습니다.

최근 기록 10건을 최신순으로 조회하는 예시:

```text
GET /records?limit=10&order=desc
```

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

Docker 실행 시:

```text
http://localhost:8000/docs
```

---

## 8. 주요 오류 응답

| 상태 코드 | 발생 조건 |
|---|---|
| 400 | 검색 시작일이 종료일보다 늦음 |
| 401 | 인증 정보가 없거나 계정 정보가 틀림 |
| 404 | 현재 사용자의 기록이 없거나 통계·주간 리포트 대상이 없음 |
| 409 | 사용자명 중복 또는 동일 날짜 기록 충돌 |
| 422 | 입력값 형식 또는 범위가 잘못됨 |

POST에서 같은 날짜의 기록을 다시 등록하거나, PUT에서 날짜를 변경하면서 기존 기록과 충돌하면 `409 Conflict`가 반환됩니다.

---

## 9. 로컬 실행 방법

### 9.1 저장소 이동

```powershell
git clone <저장소 URL>
cd jiha-health-log-api
```

### 9.2 가상환경 생성

```powershell
python -m venv venv
```

Windows PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\venv\Scripts\Activate.ps1
```

### 9.3 패키지 설치

```powershell
python -m pip install -r requirements.txt
```

### 9.4 서버 실행

```powershell
uvicorn main:app --reload
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

대시보드:

```text
http://127.0.0.1:8000/dashboard
```

서버를 처음 실행하면 프로젝트 폴더에 `health_log.db`가 자동 생성됩니다.

### 9.5 데모 데이터 준비 (선택)

대시보드를 바로 확인하려면 데모 사용자와 합성 데이터를 생성합니다. `seed_year_data.py`는 SQLite 데이터베이스에 직접 저장하므로 Uvicorn 서버가 실행 중이지 않아도 사용할 수 있습니다.

```powershell
python seed_year_data.py
```

데모 로그인:

```text
사용자명: demo_stable
비밀번호: demo1234
```

이미 데모 데이터가 있는 상태에서 깨끗하게 다시 만들고 싶다면 `--reset` 옵션을 사용하세요. 세 데모 계정과 해당 기록만 초기화하며, 다른 사용자의 데이터는 삭제하지 않습니다.

```powershell
python seed_year_data.py --reset
```

---

## 10. 현실형 합성 데이터

`seed_year_data.py`는 3명의 가상 사용자에게 각각 365건의 건강 기록을 생성합니다.

```text
3명 × 365일 = 총 1,095건
```

데이터 기간:

```text
2025-07-01 ~ 2026-06-30
```

### 데모 사용자

| 사용자명 | 비밀번호 | 시나리오 |
|---|---|---|
| `demo_stable` | `demo1234` | 꾸준한 운동과 생활 습관으로 정상 상태 유지 |
| `demo_decline` | `demo1234` | 활동량·수면 감소와 체중 증가로 건강 수치 악화 |
| `demo_recovery` | `demo1234` | 운동·식단·수면 관리로 비정상 수치 개선 |

### 저장하지 않고 검증만 실행

```powershell
python seed_year_data.py --dry-run
```

### SQLite에 실제 저장

```powershell
python seed_year_data.py
```

같은 스크립트를 다시 실행하면 이미 존재하는 사용자·날짜 기록은 건너뛰므로 중복 생성되지 않습니다.

### 데모 데이터 초기화 후 재생성

```powershell
python seed_year_data.py --reset
```

`--reset`은 세 데모 계정과 해당 기록만 삭제한 뒤 다시 생성하며, 다른 사용자의 데이터는 삭제하지 않습니다.

### 데이터 생성 원칙

- 전날 수치를 일부 이어받는 시계열 연속성
- 평일·주말 활동 패턴
- 계절별 활동량과 수면 변화
- 수면·활동량과 혈압·혈당 사이의 느슨한 방향성
- 체중 변화가 느리게 반영되는 시차
- 피로, 과로, 휴식, 정체기, 일시적 반등
- 고정 랜덤 시드를 통한 재현 가능성
- 허용 범위와 체중 일일 변동폭 자동 검증

이 데이터는 실제 건강 예측이나 의학적 인과관계 입증용이 아닌 시연용 합성 데이터입니다.

---

## 11. 자동 테스트

자동 테스트는 임시 SQLite DB와 별도 애플리케이션 모듈을 사용하므로, 로컬 Uvicorn 서버 실행 여부와 관계없이 독립적으로 실행할 수 있습니다.

```powershell
python test_sqlite_smoke.py
```

정상 결과:

```text
SQLite 스모크 테스트: 모든 항목 통과
```

주요 테스트 항목:

- 회원가입과 중복 가입
- 로그인 성공·실패
- 기록 CRUD
- POST 동일 날짜 충돌
- PUT 날짜 변경 충돌
- 사용자별 기록 접근 제한
- 날짜 범위 검색
- 통계 계산
- 주간 리포트 계산 (이전 기록 없음 / 있음)
- `/dashboard` HTML 응답 및 필수 요소 포함 여부
- 삭제 후 404
- SQLite 재시작 후 데이터 유지
- 자동 증가 ID
- 파생 필드 미저장
- 외래키 정의

테스트는 임시 SQLite DB를 사용하므로 실제 `health_log.db`를 변경하지 않습니다.

---

## 12. 대시보드 화면

`GET /dashboard`에 접속하면 로그인부터 최근 기록·주간 리포트 확인까지 브라우저에서 바로 할 수 있는 읽기 전용 화면을 제공합니다.

접속 주소:

```text
로컬 실행: http://127.0.0.1:8000/dashboard
Docker 실행: http://localhost:8000/dashboard
```

### 구성

- 사용자명·비밀번호 로그인 폼
- 최근 7일 평균과 직전 7일 대비 변화 (체중·혈압·공복혈당·걸음 수·수면 시간)
- 수치 비교 기반의 주간 변화 요약 문장
- 최근 건강 기록 최대 10건 (날짜 최신순, BMI·혈압·혈당 분류와 경고 상태 포함)
- 새로고침 · 로그아웃 버튼

### 인증 방식

`/dashboard` 자체는 인증 없이 접근할 수 있는 화면입니다. 로그인 폼에 입력한 사용자명·비밀번호는 브라우저 저장소나 쿠키에 저장하지 않고, 페이지가 열려 있는 동안만 JavaScript 메모리에 유지되는 HTTP Basic 인증 헤더로 변환되어 API 호출에 사용됩니다. 새로고침하면 자동으로 로그아웃됩니다.

### 구현 방식

React·Vue·Jinja2·외부 CDN이나 차트 라이브러리 없이, 순수 HTML·CSS·JavaScript(`dashboard.html`)로 구현했습니다. 모든 데이터는 이미 구현된 API(`/users/me`, `/records`, `/reports/weekly`)를 `fetch()`로 호출해 가져오며, 별도의 데이터 처리 로직을 중복 구현하지 않습니다.

### 제한 사항

읽기 전용 화면으로, 새 기록 추가·수정·삭제는 지원하지 않습니다. 기록 추가·수정·삭제는 Swagger UI(`/docs`) 또는 API를 직접 호출해 사용할 수 있습니다.

---

## 13. Docker 실행

### 13.1 Docker 이미지 직접 빌드

```powershell
docker build -t jiha-health-log-api .
```

### 13.2 기본 컨테이너 실행

```powershell
docker run --rm -p 8000:8000 jiha-health-log-api
```

접속:

```text
Swagger: http://localhost:8000/docs
대시보드: http://localhost:8000/dashboard
```

이 방식은 별도의 볼륨을 연결하지 않으므로 컨테이너를 삭제하면 컨테이너 내부 DB도 삭제됩니다.

### 13.3 Docker Compose 실행

```powershell
docker compose up --build
```

백그라운드 실행:

```powershell
docker compose up -d --build
```

### 13.4 Docker 내부 데모 데이터 준비

로컬 SQLite DB와 Docker SQLite DB는 서로 분리되어 있습니다. Docker 대시보드에서 데모 계정으로 로그인하려면 Docker 내부 DB에도 데모 데이터를 생성해야 합니다.

Docker Compose가 실행 중인 상태에서 새 터미널을 열고 다음 명령을 실행합니다.

```powershell
docker compose exec api python seed_year_data.py --reset
```

그다음 접속합니다.

```text
대시보드: http://localhost:8000/dashboard
사용자명: demo_stable
비밀번호: demo1234
```

### 13.5 종료

```powershell
docker compose down
```

`compose.yaml`은 named volume을 사용합니다.

```text
health_log_data → /app/data
```

따라서 `docker compose down`으로 컨테이너를 제거하고 다시 생성해도 SQLite 데이터가 유지됩니다.

### Docker 볼륨까지 삭제

```powershell
docker compose down -v
```

이 명령은 SQLite 데이터가 저장된 Docker 볼륨까지 삭제하므로 주의해야 합니다.

볼륨을 삭제한 뒤 데모 계정으로 다시 로그인하려면 다음 명령으로 데이터를 재생성해야 합니다.

```powershell
docker compose up -d --build
docker compose exec api python seed_year_data.py --reset
```

---

## 14. Docker 영속성 검증 결과

다음 절차로 Docker 볼륨 영속성을 확인했습니다.

1. Docker Compose로 API 실행
2. `docker_test` 계정 생성
3. 건강 기록 생성
4. `docker compose down`으로 컨테이너 제거
5. `docker compose up`으로 컨테이너 재생성
6. 동일 계정으로 로그인
7. 기존 건강 기록 조회

컨테이너를 제거하고 다시 생성한 뒤에도 계정과 건강 기록이 유지되는 것을 확인했습니다.

Docker Desktop 환경에서 `http://localhost:8000/dashboard` 접속도 확인했으며, Docker 내부 DB에 데모 데이터를 생성한 뒤 `demo_stable / demo1234`로 로그인하여 최근 기록·주간 리포트가 정상 표시되는 것을 확인했습니다.

---

## 15. 보안 및 데이터 정책

- 비밀번호 평문 저장 금지
- Argon2 해시만 DB에 저장
- HTTP Basic Authentication 사용
- 사용자별 데이터 분리
- 다른 사용자의 기록 ID 요청 시 404 반환
- SQLite 외래키 제약 활성화
- 데이터 변경 작업 트랜잭션 처리
- DB 파일은 Git 저장소와 Docker 이미지에서 제외
- 대시보드 인증 정보는 브라우저 저장소·쿠키에 저장하지 않음

> HTTP Basic Authentication은 인증 정보를 매 요청에 전송하므로, 실제 운영 환경에서는 반드시 HTTPS와 함께 사용해야 합니다.

`.gitignore` 제외 대상:

```text
venv/
__pycache__/
*.pyc

data.json
data.tmp

health_log.db
health_log.db-journal
health_log.db-wal
health_log.db-shm
```

---

## 16. 프로젝트 검증 결과

- SQLite 전환 완료
- 수동 Swagger 테스트 통과
- 자동 스모크 테스트 통과
- 동일 날짜 POST·PUT 충돌 처리 확인
- 서버 재시작 후 데이터 유지 확인
- 3명 × 365일 합성 데이터 생성 확인
- 재실행 중복 방지 확인
- 주간 리포트 계산 결과 확인 (최근 7일 vs 직전 7일, 이전 기록 없는 경우 포함)
- HTML 대시보드 로그인·최근 기록·주간 리포트 표시 확인 (로컬 및 Docker)
- 혈압·공복혈당·걸음 수의 화면 표시값 정수 반올림 확인
- Docker 이미지 빌드 확인
- Docker 컨테이너 실행 확인
- Docker named volume 영속성 확인

---

## 17. 향후 개선 방향

- SQLAlchemy ORM 적용
- Alembic 마이그레이션
- PostgreSQL 전환
- JWT 인증
- 페이지네이션
- 기간별 통계 API
- 건강 기록 CSV·JSON 내보내기
- 사용자 목표 설정
- 웨어러블 데이터 연동
- 대시보드에서 새 기록 입력 기능 추가
- 건강 상태 기준 변경 이력 관리

---

## 18. 참고 문서

자세한 요구사항과 설계 결정은 다음 문서를 참고할 수 있습니다.

```text
PRD_마이_헬스_로그_API_v2.md
```
