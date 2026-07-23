import datetime as dt
import os
import sqlite3
from contextlib import asynccontextmanager, closing
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field, model_validator
from pwdlib import PasswordHash


# =========================================================
# 1. SQLite 데이터베이스 설정
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "health_log.db"
DASHBOARD_PATH = BASE_DIR / "dashboard.html"
DB_PATH = Path(
    os.getenv("HEALTH_LOG_DB_PATH", str(DEFAULT_DB_PATH))
).expanduser().resolve()


def get_db_connection() -> sqlite3.Connection:
    """SQLite 연결을 만들고 공통 설정을 적용한다."""

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        DB_PATH,
        timeout=10,
    )
    connection.row_factory = sqlite3.Row

    # SQLite는 연결마다 외래키 제약을 활성화해야 한다.
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")

    return connection


def init_database() -> None:
    """필요한 SQLite 테이블을 생성한다."""

    with closing(get_db_connection()) as connection:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    hashed_password TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS health_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    weight REAL NOT NULL,
                    height REAL NOT NULL,
                    systolic INTEGER NOT NULL,
                    diastolic INTEGER NOT NULL,
                    blood_sugar INTEGER NOT NULL,
                    steps INTEGER NOT NULL DEFAULT 0,
                    sleep_hours REAL NOT NULL DEFAULT 0,
                    memo TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (user_id)
                        REFERENCES users(id)
                        ON DELETE CASCADE,
                    UNIQUE (user_id, date)
                )
                """
            )


def utc_now_iso() -> str:
    """현재 UTC 시각을 ISO 8601 문자열로 반환한다."""

    return dt.datetime.now(
        dt.timezone.utc
    ).isoformat(timespec="seconds")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """FastAPI 시작 시 데이터베이스를 준비한다."""

    init_database()
    yield


app = FastAPI(
    title="마이 헬스 로그 API",
    description=(
        "회원가입과 HTTP Basic 인증을 사용해 "
        "사용자별 건강 기록을 SQLite에 저장하는 REST API입니다."
    ),
    version="2.0",
    lifespan=lifespan,
)


# =========================================================
# 2. 보안 설정
# =========================================================

password_hash = PasswordHash.recommended()
security = HTTPBasic()

DUMMY_HASH = password_hash.hash(
    "dummy-password-for-timing-protection"
)


# =========================================================
# 3. 건강 상태 분류 타입
# =========================================================

BmiCategory = Literal[
    "저체중",
    "정상",
    "과체중",
    "비만",
]

BloodPressureCategory = Literal[
    "정상",
    "주의",
    "고혈압",
]

BloodSugarCategory = Literal[
    "정상",
    "공복혈당장애",
    "당뇨 의심",
]


# =========================================================
# 4. 사용자 데이터 모델
# =========================================================

class UserRegister(BaseModel):
    """회원가입 시 입력받는 사용자 정보"""

    username: str = Field(
        ...,
        min_length=3,
        max_length=30,
        pattern=r"^[A-Za-z0-9_-]+$",
        description=(
            "사용자명: 영문자, 숫자, 밑줄, "
            "하이픈만 사용할 수 있습니다."
        ),
        examples=["jiha"],
    )

    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="비밀번호: 8자 이상 입력해야 합니다.",
        examples=["test1234"],
    )


class UserPublic(BaseModel):
    """외부 응답으로 보여주는 사용자 정보"""

    username: str


class UserInDB(BaseModel):
    """서버 내부에서 사용하는 사용자 정보"""

    id: int = Field(..., ge=1)
    username: str
    hashed_password: str


class LoginResponse(BaseModel):
    """로그인 성공 응답"""

    message: str
    user: UserPublic


# =========================================================
# 5. 건강 기록 데이터 모델
# =========================================================

class RecordBase(BaseModel):
    """건강 기록에서 공통으로 사용하는 필드"""

    date: dt.date = Field(
        ...,
        description="측정일",
        examples=["2026-07-21"],
    )

    weight: float = Field(
        ...,
        gt=0,
        description="몸무게(kg)",
        examples=[60.5],
    )

    height: float = Field(
        ...,
        gt=0,
        description="키(cm)",
        examples=[170],
    )

    systolic: int = Field(
        ...,
        gt=0,
        description="수축기 혈압",
        examples=[118],
    )

    diastolic: int = Field(
        ...,
        gt=0,
        description="이완기 혈압",
        examples=[76],
    )

    blood_sugar: int = Field(
        ...,
        gt=0,
        description="공복 혈당(mg/dL)",
        examples=[92],
    )

    steps: int = Field(
        default=0,
        ge=0,
        description="하루 걸음 수",
        examples=[8500],
    )

    sleep_hours: float = Field(
        default=0.0,
        ge=0,
        le=24,
        description="수면 시간",
        examples=[7.2],
    )

    memo: str = Field(
        default="",
        max_length=500,
        description="건강 기록 메모",
        examples=["아침 기상 후 측정"],
    )

    @model_validator(mode="after")
    def validate_blood_pressure(self):
        """수축기 혈압과 이완기 혈압의 관계를 검사한다."""

        if self.systolic <= self.diastolic:
            raise ValueError(
                "수축기 혈압은 이완기 혈압보다 높아야 합니다."
            )

        return self


class RecordInput(RecordBase):
    """POST와 PUT 요청에서 사용하는 입력 모델"""

    pass


class RecordResponse(RecordBase):
    """서버가 사용자에게 반환하는 건강 기록 모델"""

    id: int = Field(
        ...,
        ge=1,
        description="기록 고유 번호",
    )

    user: str = Field(
        ...,
        description="기록 소유자",
    )

    bmi: float = Field(
        ...,
        gt=0,
        description="계산된 BMI",
    )

    bmi_category: BmiCategory = Field(
        ...,
        description="BMI 분류",
    )

    bp_category: BloodPressureCategory = Field(
        ...,
        description="혈압 분류",
    )

    sugar_category: BloodSugarCategory = Field(
        ...,
        description="공복혈당 분류",
    )

    warnings: list[str] = Field(
        ...,
        description="건강 수치 경고 목록",
    )


class RecordListResponse(BaseModel):
    """건강 기록 목록 응답"""

    count: int = Field(
        ...,
        ge=0,
        description="조회된 기록 개수",
    )

    records: list[RecordResponse]


class DeleteResponse(BaseModel):
    """건강 기록 삭제 응답"""

    message: str
    id: int


class StatsResponse(BaseModel):
    """현재 사용자의 건강 기록 통계 응답"""

    count: int = Field(
        ...,
        ge=1,
        description="통계 계산에 사용된 기록 수",
    )

    average_weight: float = Field(
        ...,
        description="평균 몸무게",
    )

    average_bmi: float = Field(
        ...,
        description="평균 BMI",
    )

    average_systolic: float = Field(
        ...,
        description="평균 수축기 혈압",
    )

    average_diastolic: float = Field(
        ...,
        description="평균 이완기 혈압",
    )

    average_blood_sugar: float = Field(
        ...,
        description="평균 공복혈당",
    )

    min_weight: float = Field(
        ...,
        description="최저 몸무게",
    )

    max_weight: float = Field(
        ...,
        description="최고 몸무게",
    )

    min_bmi: float = Field(
        ...,
        description="최저 BMI",
    )

    max_bmi: float = Field(
        ...,
        description="최고 BMI",
    )

    min_systolic: int = Field(
        ...,
        description="최저 수축기 혈압",
    )

    max_systolic: int = Field(
        ...,
        description="최고 수축기 혈압",
    )

    min_diastolic: int = Field(
        ...,
        description="최저 이완기 혈압",
    )

    max_diastolic: int = Field(
        ...,
        description="최고 이완기 혈압",
    )

    min_blood_sugar: int = Field(
        ...,
        description="최저 공복혈당",
    )

    max_blood_sugar: int = Field(
        ...,
        description="최고 공복혈당",
    )


class WeeklyPeriodStats(BaseModel):
    """주간 리포트의 한 기간에 대한 평균 통계"""

    start_date: dt.date
    end_date: dt.date

    record_count: int = Field(
        ...,
        ge=0,
        description="해당 기간의 기록 수",
    )

    average_weight: float | None = Field(
        default=None,
        description="해당 기간의 평균 몸무게",
    )

    average_systolic: float | None = Field(
        default=None,
        description="해당 기간의 평균 수축기 혈압",
    )

    average_diastolic: float | None = Field(
        default=None,
        description="해당 기간의 평균 이완기 혈압",
    )

    average_blood_sugar: float | None = Field(
        default=None,
        description="해당 기간의 평균 공복혈당",
    )

    average_steps: float | None = Field(
        default=None,
        description="해당 기간의 평균 걸음 수",
    )

    average_sleep_hours: float | None = Field(
        default=None,
        description="해당 기간의 평균 수면 시간",
    )


class WeeklyChanges(BaseModel):
    """현재 7일 평균에서 직전 7일 평균을 뺀 변화량"""

    weight: float
    systolic: float
    diastolic: float
    blood_sugar: float
    steps: float
    sleep_hours: float


class WeeklyReportResponse(BaseModel):
    """최근 7일과 직전 7일을 비교한 주간 리포트"""

    current_period: WeeklyPeriodStats
    previous_period: WeeklyPeriodStats
    changes: WeeklyChanges | None
    summary: list[str]


# =========================================================
# 6. 사용자 조회 및 인증 함수
# =========================================================

def normalize_username(username: str) -> str:
    """사용자명을 소문자로 통일한다."""

    return username.strip().lower()


def get_user_by_username(username: str) -> UserInDB | None:
    """사용자명으로 SQLite 사용자 정보를 조회한다."""

    normalized_username = normalize_username(username)

    with closing(get_db_connection()) as connection:
        row = connection.execute(
            """
            SELECT id, username, hashed_password
            FROM users
            WHERE username = ?
            """,
            (normalized_username,),
        ).fetchone()

    if row is None:
        return None

    return UserInDB(
        id=row["id"],
        username=row["username"],
        hashed_password=row["hashed_password"],
    )


def authenticate_user(
    username: str,
    password: str,
) -> UserInDB | None:
    """사용자명과 비밀번호를 검증한다."""

    user = get_user_by_username(username)

    if user is None:
        password_hash.verify(
            password,
            DUMMY_HASH,
        )
        return None

    password_matches = password_hash.verify(
        password,
        user.hashed_password,
    )

    if not password_matches:
        return None

    return user


def get_current_user(
    credentials: HTTPBasicCredentials = Depends(security),
) -> UserInDB:
    """HTTP Basic 인증 정보로 현재 사용자를 확인한다."""

    user = authenticate_user(
        username=credentials.username,
        password=credentials.password,
    )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="사용자명 또는 비밀번호가 올바르지 않습니다.",
            headers={
                "WWW-Authenticate": "Basic",
            },
        )

    return user


# =========================================================
# 7. 건강 분석 및 응답 변환 함수
# =========================================================

def calculate_bmi(weight: float, height: float) -> float:
    """몸무게와 키를 이용해 BMI를 계산한다."""

    height_m = height / 100
    bmi = weight / (height_m ** 2)

    return round(bmi, 2)


def classify_bmi(bmi: float) -> BmiCategory:
    """BMI 수치에 따라 건강 상태를 분류한다."""

    if bmi < 18.5:
        return "저체중"

    if bmi < 23:
        return "정상"

    if bmi < 25:
        return "과체중"

    return "비만"


def classify_blood_pressure(
    systolic: int,
    diastolic: int,
) -> BloodPressureCategory:
    """수축기와 이완기 혈압으로 혈압 상태를 분류한다."""

    if systolic >= 140 or diastolic >= 90:
        return "고혈압"

    if systolic >= 120 or diastolic >= 80:
        return "주의"

    return "정상"


def classify_blood_sugar(
    blood_sugar: int,
) -> BloodSugarCategory:
    """공복혈당 수치에 따라 혈당 상태를 분류한다."""

    if blood_sugar < 100:
        return "정상"

    if blood_sugar < 126:
        return "공복혈당장애"

    return "당뇨 의심"


def create_warnings(
    bmi_category: BmiCategory,
    bp_category: BloodPressureCategory,
    sugar_category: BloodSugarCategory,
) -> list[str]:
    """건강 상태에 따라 경고 메시지 목록을 생성한다."""

    warnings: list[str] = []

    if bmi_category == "비만":
        warnings.append("BMI가 비만 범위입니다.")

    if bp_category == "고혈압":
        warnings.append("혈압이 고혈압 범위입니다.")

    if sugar_category == "당뇨 의심":
        warnings.append(
            "공복혈당이 당뇨 의심 범위입니다."
        )

    return warnings


def build_record(
    record_input: RecordInput,
    record_id: int,
    username: str,
) -> RecordResponse:
    """원본 건강 수치로 파생값을 계산해 응답을 만든다."""

    bmi = calculate_bmi(
        weight=record_input.weight,
        height=record_input.height,
    )

    bmi_category = classify_bmi(bmi)

    bp_category = classify_blood_pressure(
        systolic=record_input.systolic,
        diastolic=record_input.diastolic,
    )

    sugar_category = classify_blood_sugar(
        blood_sugar=record_input.blood_sugar,
    )

    warnings = create_warnings(
        bmi_category=bmi_category,
        bp_category=bp_category,
        sugar_category=sugar_category,
    )

    return RecordResponse(
        id=record_id,
        user=username,
        **record_input.model_dump(),
        bmi=bmi,
        bmi_category=bmi_category,
        bp_category=bp_category,
        sugar_category=sugar_category,
        warnings=warnings,
    )


def row_to_record_response(
    row: sqlite3.Row,
    username: str,
) -> RecordResponse:
    """SQLite 행을 검증된 RecordResponse로 변환한다."""

    record_input = RecordInput(
        date=dt.date.fromisoformat(row["date"]),
        weight=row["weight"],
        height=row["height"],
        systolic=row["systolic"],
        diastolic=row["diastolic"],
        blood_sugar=row["blood_sugar"],
        steps=row["steps"],
        sleep_hours=row["sleep_hours"],
        memo=row["memo"],
    )

    return build_record(
        record_input=record_input,
        record_id=row["id"],
        username=username,
    )


def get_user_record_row(
    record_id: int,
    user_id: int,
) -> sqlite3.Row:
    """현재 사용자가 소유한 기록 한 건을 조회한다."""

    with closing(get_db_connection()) as connection:
        row = connection.execute(
            """
            SELECT
                id,
                user_id,
                date,
                weight,
                height,
                systolic,
                diastolic,
                blood_sugar,
                steps,
                sleep_hours,
                memo
            FROM health_records
            WHERE id = ? AND user_id = ?
            """,
            (record_id, user_id),
        ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="기록을 찾을 수 없습니다.",
        )

    return row


def duplicate_date_exception() -> HTTPException:
    """동일 날짜 기록 충돌 응답을 만든다."""

    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "해당 날짜의 건강 기록이 이미 존재합니다. "
            "기존 기록을 수정하려면 PUT 요청을 사용해주세요."
        ),
    )


def calculate_weekly_period_stats(
    rows: list[sqlite3.Row],
    start_date: dt.date,
    end_date: dt.date,
) -> WeeklyPeriodStats:
    """조회된 기록으로 한 기간의 평균값을 계산한다."""

    record_count = len(rows)

    if record_count == 0:
        return WeeklyPeriodStats(
            start_date=start_date,
            end_date=end_date,
            record_count=0,
        )

    return WeeklyPeriodStats(
        start_date=start_date,
        end_date=end_date,
        record_count=record_count,
        average_weight=round(
            sum(row["weight"] for row in rows) / record_count,
            2,
        ),
        average_systolic=round(
            sum(row["systolic"] for row in rows) / record_count,
            2,
        ),
        average_diastolic=round(
            sum(row["diastolic"] for row in rows) / record_count,
            2,
        ),
        average_blood_sugar=round(
            sum(row["blood_sugar"] for row in rows) / record_count,
            2,
        ),
        average_steps=round(
            sum(row["steps"] for row in rows) / record_count,
            2,
        ),
        average_sleep_hours=round(
            sum(row["sleep_hours"] for row in rows) / record_count,
            2,
        ),
    )


def format_change_value(
    value: float,
    unit: str,
    digits: int = 2,
) -> str:
    """변화량을 지정한 소수 자릿수로 표시한다."""

    rounded_value = round(abs(value), digits)

    if digits == 0 or float(rounded_value).is_integer():
        number = f"{int(rounded_value):,}"
    else:
        number = (
            f"{rounded_value:,.{digits}f}"
            .rstrip("0")
            .rstrip(".")
        )

    return f"{number}{unit}"


def describe_weekly_change(
    label: str,
    value: float,
    unit: str,
    subject_particle: str = "이",
    topic_particle: str = "은",
    digits: int = 2,
) -> str:
    """증감값 하나를 의학적 판단 없이 사실 문장으로 만든다."""

    display_value = round(value, digits)

    if display_value > 0:
        direction = "증가"
    elif display_value < 0:
        direction = "감소"
    else:
        return (
            f"평균 {label}{topic_particle} "
            "직전 기간과 같습니다."
        )

    formatted_value = format_change_value(
        value=display_value,
        unit=unit,
        digits=digits,
    )

    return (
        f"평균 {label}{subject_particle} 직전 기간보다 "
        f"{formatted_value} {direction}했습니다."
    )


def build_weekly_summary(
    changes: WeeklyChanges,
) -> list[str]:
    """주간 변화량을 수치 중심의 요약 문장으로 변환한다."""

    return [
        describe_weekly_change(
            label="체중",
            value=changes.weight,
            unit="kg",
        ),
        describe_weekly_change(
            label="수축기 혈압",
            value=changes.systolic,
            unit="mmHg",
            digits=0,
        ),
        describe_weekly_change(
            label="이완기 혈압",
            value=changes.diastolic,
            unit="mmHg",
            digits=0,
        ),
        describe_weekly_change(
            label="공복혈당",
            value=changes.blood_sugar,
            unit="mg/dL",
            digits=0,
        ),
        describe_weekly_change(
            label="걸음 수",
            value=changes.steps,
            unit="보",
            subject_particle="가",
            topic_particle="는",
            digits=0,
        ),
        describe_weekly_change(
            label="수면 시간",
            value=changes.sleep_hours,
            unit="시간",
        ),
    ]


# =========================================================
# 8. 기본 API
# =========================================================

@app.get("/")
def read_root():
    return {
        "message": "마이 헬스 로그 API가 실행 중입니다.",
        "status": "running",
    }


@app.get(
    "/dashboard",
    response_class=HTMLResponse,
)
def read_dashboard():
    """인증 폼과 건강 기록 요약이 포함된 HTML 화면을 반환한다."""

    try:
        html_content = DASHBOARD_PATH.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="대시보드 HTML 파일을 찾을 수 없습니다.",
        ) from error

    return HTMLResponse(content=html_content)


# =========================================================
# 9. 사용자 API
# =========================================================

@app.post(
    "/users/register",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
)
def register_user(user_input: UserRegister):
    """새로운 사용자를 SQLite에 등록한다."""

    username = normalize_username(user_input.username)
    hashed_password = password_hash.hash(
        user_input.password,
    )
    created_at = utc_now_iso()

    try:
        with closing(get_db_connection()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO users (
                        username,
                        hashed_password,
                        created_at
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        username,
                        hashed_password,
                        created_at,
                    ),
                )
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 사용 중인 사용자명입니다.",
        ) from error

    return UserPublic(
        username=username,
    )


@app.post(
    "/users/login",
    response_model=LoginResponse,
)
def login_user(
    current_user: UserInDB = Depends(get_current_user),
):
    """사용자명과 비밀번호를 확인한다."""

    return LoginResponse(
        message="로그인에 성공했습니다.",
        user=UserPublic(
            username=current_user.username,
        ),
    )


@app.get(
    "/users/me",
    response_model=UserPublic,
)
def read_current_user(
    current_user: UserInDB = Depends(get_current_user),
):
    """현재 인증된 사용자의 정보를 반환한다."""

    return UserPublic(
        username=current_user.username,
    )


# =========================================================
# 10. 건강 기록 CRUD API
# =========================================================

@app.post(
    "/records",
    response_model=RecordResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_record(
    record_input: RecordInput,
    current_user: UserInDB = Depends(get_current_user),
):
    """현재 사용자의 새로운 건강 기록을 추가한다."""

    timestamp = utc_now_iso()

    try:
        with closing(get_db_connection()) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    INSERT INTO health_records (
                        user_id,
                        date,
                        weight,
                        height,
                        systolic,
                        diastolic,
                        blood_sugar,
                        steps,
                        sleep_hours,
                        memo,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        current_user.id,
                        record_input.date.isoformat(),
                        record_input.weight,
                        record_input.height,
                        record_input.systolic,
                        record_input.diastolic,
                        record_input.blood_sugar,
                        record_input.steps,
                        record_input.sleep_hours,
                        record_input.memo,
                        timestamp,
                        timestamp,
                    ),
                )
                record_id = cursor.lastrowid
    except sqlite3.IntegrityError as error:
        raise duplicate_date_exception() from error

    if record_id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="기록 ID를 생성하지 못했습니다.",
        )

    return build_record(
        record_input=record_input,
        record_id=record_id,
        username=current_user.username,
    )


@app.get(
    "/records",
    response_model=RecordListResponse,
)
def read_records(
    limit: int | None = Query(
        default=None,
        ge=1,
        le=100,
        description=(
            "반환할 최대 기록 수입니다. "
            "입력하지 않으면 전체 기록을 반환합니다."
        ),
    ),
    order: Literal["asc", "desc"] = Query(
        default="asc",
        description="날짜 정렬 순서",
    ),
    current_user: UserInDB = Depends(get_current_user),
):
    """현재 사용자의 건강 기록을 선택한 순서와 개수로 조회한다."""

    order_keyword = "ASC" if order == "asc" else "DESC"

    query = f"""
        SELECT
            id,
            user_id,
            date,
            weight,
            height,
            systolic,
            diastolic,
            blood_sugar,
            steps,
            sleep_hours,
            memo
        FROM health_records
        WHERE user_id = ?
        ORDER BY date {order_keyword}, id {order_keyword}
    """

    parameters: list[int] = [current_user.id]

    if limit is not None:
        query += "\nLIMIT ?"
        parameters.append(limit)

    with closing(get_db_connection()) as connection:
        rows = connection.execute(
            query,
            parameters,
        ).fetchall()

    user_records = [
        row_to_record_response(
            row=row,
            username=current_user.username,
        )
        for row in rows
    ]

    return RecordListResponse(
        count=len(user_records),
        records=user_records,
    )


@app.get(
    "/records/{record_id}",
    response_model=RecordResponse,
)
def read_record(
    record_id: int,
    current_user: UserInDB = Depends(get_current_user),
):
    """현재 사용자가 소유한 건강 기록 한 건을 조회한다."""

    row = get_user_record_row(
        record_id=record_id,
        user_id=current_user.id,
    )

    return row_to_record_response(
        row=row,
        username=current_user.username,
    )


@app.put(
    "/records/{record_id}",
    response_model=RecordResponse,
)
def update_record(
    record_id: int,
    record_input: RecordInput,
    current_user: UserInDB = Depends(get_current_user),
):
    """현재 사용자가 소유한 건강 기록을 수정한다."""

    timestamp = utc_now_iso()

    try:
        with closing(get_db_connection()) as connection:
            existing_row = connection.execute(
                """
                SELECT id
                FROM health_records
                WHERE id = ? AND user_id = ?
                """,
                (record_id, current_user.id),
            ).fetchone()

            if existing_row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="기록을 찾을 수 없습니다.",
                )

            with connection:
                connection.execute(
                    """
                    UPDATE health_records
                    SET
                        date = ?,
                        weight = ?,
                        height = ?,
                        systolic = ?,
                        diastolic = ?,
                        blood_sugar = ?,
                        steps = ?,
                        sleep_hours = ?,
                        memo = ?,
                        updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (
                        record_input.date.isoformat(),
                        record_input.weight,
                        record_input.height,
                        record_input.systolic,
                        record_input.diastolic,
                        record_input.blood_sugar,
                        record_input.steps,
                        record_input.sleep_hours,
                        record_input.memo,
                        timestamp,
                        record_id,
                        current_user.id,
                    ),
                )
    except sqlite3.IntegrityError as error:
        raise duplicate_date_exception() from error

    return build_record(
        record_input=record_input,
        record_id=record_id,
        username=current_user.username,
    )


@app.delete(
    "/records/{record_id}",
    response_model=DeleteResponse,
)
def delete_record(
    record_id: int,
    current_user: UserInDB = Depends(get_current_user),
):
    """현재 사용자가 소유한 건강 기록을 삭제한다."""

    with closing(get_db_connection()) as connection:
        with connection:
            cursor = connection.execute(
                """
                DELETE FROM health_records
                WHERE id = ? AND user_id = ?
                """,
                (record_id, current_user.id),
            )

        deleted_count = cursor.rowcount

    if deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="기록을 찾을 수 없습니다.",
        )

    return DeleteResponse(
        message="건강 기록이 삭제되었습니다.",
        id=record_id,
    )


# =========================================================
# 11. 검색·통계·리포트 API
# =========================================================

@app.get(
    "/search",
    response_model=RecordListResponse,
)
def search_records(
    start: dt.date = Query(
        ...,
        description="검색 시작일",
        examples=["2026-07-01"],
    ),
    end: dt.date = Query(
        ...,
        description="검색 종료일",
        examples=["2026-07-31"],
    ),
    current_user: UserInDB = Depends(get_current_user),
):
    """현재 사용자의 기록을 날짜 범위로 검색한다."""

    if start > end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="시작일은 종료일보다 늦을 수 없습니다.",
        )

    with closing(get_db_connection()) as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                user_id,
                date,
                weight,
                height,
                systolic,
                diastolic,
                blood_sugar,
                steps,
                sleep_hours,
                memo
            FROM health_records
            WHERE
                user_id = ?
                AND date BETWEEN ? AND ?
            ORDER BY date ASC, id ASC
            """,
            (
                current_user.id,
                start.isoformat(),
                end.isoformat(),
            ),
        ).fetchall()

    search_results = [
        row_to_record_response(
            row=row,
            username=current_user.username,
        )
        for row in rows
    ]

    return RecordListResponse(
        count=len(search_results),
        records=search_results,
    )


@app.get(
    "/stats",
    response_model=StatsResponse,
)
def read_stats(
    current_user: UserInDB = Depends(get_current_user),
):
    """현재 사용자의 전체 건강 기록 통계를 계산한다."""

    with closing(get_db_connection()) as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                user_id,
                date,
                weight,
                height,
                systolic,
                diastolic,
                blood_sugar,
                steps,
                sleep_hours,
                memo
            FROM health_records
            WHERE user_id = ?
            ORDER BY date ASC, id ASC
            """,
            (current_user.id,),
        ).fetchall()

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="통계를 계산할 건강 기록이 없습니다.",
        )

    user_records = [
        row_to_record_response(
            row=row,
            username=current_user.username,
        )
        for row in rows
    ]

    count = len(user_records)

    return StatsResponse(
        count=count,
        average_weight=round(
            sum(record.weight for record in user_records) / count,
            2,
        ),
        average_bmi=round(
            sum(record.bmi for record in user_records) / count,
            2,
        ),
        average_systolic=round(
            sum(record.systolic for record in user_records) / count,
            2,
        ),
        average_diastolic=round(
            sum(record.diastolic for record in user_records) / count,
            2,
        ),
        average_blood_sugar=round(
            sum(record.blood_sugar for record in user_records) / count,
            2,
        ),
        min_weight=min(
            record.weight for record in user_records
        ),
        max_weight=max(
            record.weight for record in user_records
        ),
        min_bmi=min(
            record.bmi for record in user_records
        ),
        max_bmi=max(
            record.bmi for record in user_records
        ),
        min_systolic=min(
            record.systolic for record in user_records
        ),
        max_systolic=max(
            record.systolic for record in user_records
        ),
        min_diastolic=min(
            record.diastolic for record in user_records
        ),
        max_diastolic=max(
            record.diastolic for record in user_records
        ),
        min_blood_sugar=min(
            record.blood_sugar for record in user_records
        ),
        max_blood_sugar=max(
            record.blood_sugar for record in user_records
        ),
    )


@app.get(
    "/reports/weekly",
    response_model=WeeklyReportResponse,
)
def read_weekly_report(
    current_user: UserInDB = Depends(get_current_user),
):
    """가장 최근 기록일을 기준으로 최근 7일과 직전 7일을 비교한다."""

    with closing(get_db_connection()) as connection:
        latest_date_value = connection.execute(
            """
            SELECT MAX(date)
            FROM health_records
            WHERE user_id = ?
            """,
            (current_user.id,),
        ).fetchone()[0]

        if latest_date_value is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="주간 리포트를 생성할 건강 기록이 없습니다.",
            )

        current_end = dt.date.fromisoformat(
            latest_date_value
        )
        current_start = current_end - dt.timedelta(days=6)
        previous_end = current_start - dt.timedelta(days=1)
        previous_start = previous_end - dt.timedelta(days=6)

        rows = connection.execute(
            """
            SELECT
                date,
                weight,
                systolic,
                diastolic,
                blood_sugar,
                steps,
                sleep_hours
            FROM health_records
            WHERE
                user_id = ?
                AND date BETWEEN ? AND ?
            ORDER BY date ASC, id ASC
            """,
            (
                current_user.id,
                previous_start.isoformat(),
                current_end.isoformat(),
            ),
        ).fetchall()

    current_rows: list[sqlite3.Row] = []
    previous_rows: list[sqlite3.Row] = []

    for row in rows:
        record_date = dt.date.fromisoformat(row["date"])

        if current_start <= record_date <= current_end:
            current_rows.append(row)
        elif previous_start <= record_date <= previous_end:
            previous_rows.append(row)

    current_period = calculate_weekly_period_stats(
        rows=current_rows,
        start_date=current_start,
        end_date=current_end,
    )
    previous_period = calculate_weekly_period_stats(
        rows=previous_rows,
        start_date=previous_start,
        end_date=previous_end,
    )

    if previous_period.record_count == 0:
        return WeeklyReportResponse(
            current_period=current_period,
            previous_period=previous_period,
            changes=None,
            summary=[
                (
                    "비교할 이전 기록이 없어 "
                    "증감을 계산할 수 없습니다."
                )
            ],
        )

    if (
        current_period.average_weight is None
        or current_period.average_systolic is None
        or current_period.average_diastolic is None
        or current_period.average_blood_sugar is None
        or current_period.average_steps is None
        or current_period.average_sleep_hours is None
        or previous_period.average_weight is None
        or previous_period.average_systolic is None
        or previous_period.average_diastolic is None
        or previous_period.average_blood_sugar is None
        or previous_period.average_steps is None
        or previous_period.average_sleep_hours is None
    ):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="주간 리포트 평균값을 계산하지 못했습니다.",
        )

    changes = WeeklyChanges(
        weight=round(
            current_period.average_weight
            - previous_period.average_weight,
            2,
        ),
        systolic=round(
            current_period.average_systolic
            - previous_period.average_systolic,
            2,
        ),
        diastolic=round(
            current_period.average_diastolic
            - previous_period.average_diastolic,
            2,
        ),
        blood_sugar=round(
            current_period.average_blood_sugar
            - previous_period.average_blood_sugar,
            2,
        ),
        steps=round(
            current_period.average_steps
            - previous_period.average_steps,
            2,
        ),
        sleep_hours=round(
            current_period.average_sleep_hours
            - previous_period.average_sleep_hours,
            2,
        ),
    )

    return WeeklyReportResponse(
        current_period=current_period,
        previous_period=previous_period,
        changes=changes,
        summary=build_weekly_summary(changes),
    )

