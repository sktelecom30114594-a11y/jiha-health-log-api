import datetime as dt
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field, model_validator
from pwdlib import PasswordHash


app = FastAPI(
    title="마이 헬스 로그 API",
    description=(
        "회원가입과 HTTP Basic 인증을 사용해 "
        "사용자별 건강 기록을 관리하는 REST API입니다."
    ),
    version="1.0",
)


# =========================================================
# 1. 보안 설정
# =========================================================

# pwdlib에서 현재 권장하는 비밀번호 해시 설정을 사용한다.
password_hash = PasswordHash.recommended()

# HTTP Basic 인증 방식을 사용한다.
security = HTTPBasic()

# 존재하지 않는 사용자도 비밀번호 검증을 수행하기 위한 더미 해시
DUMMY_HASH = password_hash.hash(
    "dummy-password-for-timing-protection"
)


# =========================================================
# 2. 건강 상태 분류 타입
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
# 3. 사용자 데이터 모델
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
    """서버 내부에서 보관하는 사용자 정보"""

    username: str
    hashed_password: str


class LoginResponse(BaseModel):
    """로그인 성공 응답"""

    message: str
    user: UserPublic


# =========================================================
# 4. 건강 기록 데이터 모델
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


# =========================================================
# 5. 임시 저장소
# =========================================================

# 사용자명과 사용자 정보를 저장한다.
users: dict[str, UserInDB] = {}

# 서버가 실행되는 동안 건강 기록을 보관한다.
records: list[RecordResponse] = []

# 새 기록에 부여할 다음 ID
next_record_id = 1


# =========================================================
# 6. 사용자 인증 함수
# =========================================================

def normalize_username(username: str) -> str:
    """사용자명을 소문자로 통일한다."""

    return username.strip().lower()


def authenticate_user(
    username: str,
    password: str,
) -> UserInDB | None:
    """사용자명과 비밀번호를 검증한다."""

    normalized_username = normalize_username(username)
    user = users.get(normalized_username)

    if user is None:
        # 사용자가 없어도 해시 검증을 수행해
        # 사용자 존재 여부에 따른 시간 차이를 줄인다.
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
# 7. 건강 분석 함수
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
    """수축기와 이완기 혈압을 이용해 혈압 상태를 분류한다."""

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
    """입력된 건강 수치를 분석해 완성된 기록을 만든다."""

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


def find_user_record(
    record_id: int,
    username: str,
) -> tuple[int, RecordResponse]:
    """
    현재 사용자가 소유한 기록을 찾는다.

    반환값:
    - 리스트 안에서의 위치
    - 찾은 건강 기록
    """

    for index, record in enumerate(records):
        if (
            record.id == record_id
            and record.user == username
        ):
            return index, record

    # 기록이 없거나 다른 사용자의 기록이면
    # 모두 동일하게 404를 반환한다.
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="기록을 찾을 수 없습니다.",
    )


# =========================================================
# 8. 기본 API
# =========================================================

@app.get("/")
def read_root():
    return {
        "message": "마이 헬스 로그 API가 실행 중입니다.",
        "status": "running",
    }


# =========================================================
# 9. 사용자 API
# =========================================================

@app.post(
    "/users/register",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
)
def register_user(user_input: UserRegister):
    """새로운 사용자를 등록한다."""

    username = normalize_username(user_input.username)

    if username in users:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 사용 중인 사용자명입니다.",
        )

    hashed_password = password_hash.hash(
        user_input.password,
    )

    new_user = UserInDB(
        username=username,
        hashed_password=hashed_password,
    )

    users[username] = new_user

    return UserPublic(
        username=new_user.username,
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
# 10. 건강 기록 API
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

    global next_record_id

    new_record = build_record(
        record_input=record_input,
        record_id=next_record_id,
        username=current_user.username,
    )

    records.append(new_record)
    next_record_id += 1

    return new_record


@app.get(
    "/records",
    response_model=RecordListResponse,
)
def read_records(
    current_user: UserInDB = Depends(get_current_user),
):
    """현재 사용자가 소유한 모든 건강 기록을 조회한다."""

    user_records = [
        record
        for record in records
        if record.user == current_user.username
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

    _, record = find_user_record(
        record_id=record_id,
        username=current_user.username,
    )

    return record


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

    record_index, existing_record = find_user_record(
        record_id=record_id,
        username=current_user.username,
    )

    updated_record = build_record(
        record_input=record_input,
        record_id=existing_record.id,
        username=current_user.username,
    )

    records[record_index] = updated_record

    return updated_record


@app.delete(
    "/records/{record_id}",
    response_model=DeleteResponse,
)
def delete_record(
    record_id: int,
    current_user: UserInDB = Depends(get_current_user),
):
    """현재 사용자가 소유한 건강 기록을 삭제한다."""

    record_index, existing_record = find_user_record(
        record_id=record_id,
        username=current_user.username,
    )

    records.pop(record_index)

    return DeleteResponse(
        message="건강 기록이 삭제되었습니다.",
        id=existing_record.id,
    )