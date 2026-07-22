"""SQLite 전환본의 핵심 API를 자동 검증하는 스모크 테스트."""

import importlib.util
import os
import sys
import tempfile
import types
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi.testclient import TestClient


MAIN_PATH = Path(__file__).with_name("main.py")


class FakePasswordHash:
    """테스트 환경에서 pwdlib 인터페이스를 대신하는 Argon2 래퍼."""

    def __init__(self):
        self.hasher = PasswordHasher()

    @classmethod
    def recommended(cls):
        return cls()

    def hash(self, password: str) -> str:
        return self.hasher.hash(password)

    def verify(self, password: str, encoded_hash: str) -> bool:
        try:
            return self.hasher.verify(encoded_hash, password)
        except VerifyMismatchError:
            return False


def install_pwdlib_test_double() -> None:
    module = types.ModuleType("pwdlib")
    module.PasswordHash = FakePasswordHash
    sys.modules["pwdlib"] = module


def load_app(module_name: str):
    spec = importlib.util.spec_from_file_location(
        module_name,
        MAIN_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("main.py를 불러올 수 없습니다.")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def assert_status(response, expected: int, label: str) -> None:
    assert response.status_code == expected, (
        f"{label}: expected={expected}, "
        f"actual={response.status_code}, body={response.text}"
    )


def record_payload(date: str, **overrides):
    payload = {
        "date": date,
        "weight": 60.0,
        "height": 170.0,
        "systolic": 118,
        "diastolic": 76,
        "blood_sugar": 92,
        "steps": 8000,
        "sleep_hours": 7.0,
        "memo": "스모크 테스트",
    }
    payload.update(overrides)
    return payload


def run_test() -> None:
    install_pwdlib_test_double()

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "health_log_test.db"
        os.environ["HEALTH_LOG_DB_PATH"] = str(db_path)

        module = load_app("health_log_app_first")

        with TestClient(module.app) as client:
            alice_auth = ("Alice", "test1234")
            bob_auth = ("bob", "bobpass12")

            response = client.post(
                "/users/register",
                json={"username": "Alice", "password": "test1234"},
            )
            assert_status(response, 201, "회원가입")
            assert response.json() == {"username": "alice"}

            response = client.post(
                "/users/register",
                json={"username": "alice", "password": "test1234"},
            )
            assert_status(response, 409, "중복 회원가입")

            response = client.post(
                "/users/register",
                json={"username": "bob", "password": "bobpass12"},
            )
            assert_status(response, 201, "두 번째 사용자 가입")

            response = client.post(
                "/users/login",
                auth=("alice", "wrongpass"),
            )
            assert_status(response, 401, "잘못된 비밀번호")

            response = client.post(
                "/users/login",
                auth=alice_auth,
            )
            assert_status(response, 200, "정상 로그인")

            response = client.post(
                "/records",
                auth=alice_auth,
                json=record_payload("2026-07-01"),
            )
            assert_status(response, 201, "첫 기록 생성")
            first_id = response.json()["id"]
            assert "created_at" not in response.json()
            assert "updated_at" not in response.json()

            response = client.post(
                "/records",
                auth=alice_auth,
                json=record_payload(
                    "2026-07-02",
                    weight=61.0,
                    systolic=125,
                    diastolic=82,
                    blood_sugar=105,
                ),
            )
            assert_status(response, 201, "두 번째 기록 생성")
            second_id = response.json()["id"]

            response = client.post(
                "/records",
                auth=alice_auth,
                json=record_payload("2026-07-01"),
            )
            assert_status(response, 409, "POST 날짜 중복")

            response = client.get(
                "/records",
                auth=alice_auth,
            )
            assert_status(response, 200, "전체 조회")
            assert response.json()["count"] == 2
            assert [
                item["date"] for item in response.json()["records"]
            ] == ["2026-07-01", "2026-07-02"]

            response = client.get(
                f"/records/{first_id}",
                auth=bob_auth,
            )
            assert_status(response, 404, "다른 사용자 기록 접근")

            response = client.put(
                f"/records/{first_id}",
                auth=alice_auth,
                json=record_payload("2026-07-02"),
            )
            assert_status(response, 409, "PUT 날짜 변경 충돌")

            response = client.put(
                f"/records/{first_id}",
                auth=alice_auth,
                json=record_payload(
                    "2026-07-01",
                    weight=60.5,
                    memo="수정 결과 유지 확인",
                ),
            )
            assert_status(response, 200, "정상 수정")
            assert response.json()["weight"] == 60.5

            response = client.get(
                "/search",
                auth=alice_auth,
                params={"start": "2026-07-01", "end": "2026-07-01"},
            )
            assert_status(response, 200, "날짜 검색")
            assert response.json()["count"] == 1

            response = client.get(
                "/search",
                auth=alice_auth,
                params={"start": "2026-07-03", "end": "2026-07-01"},
            )
            assert_status(response, 400, "역전 날짜 범위")

            response = client.get(
                "/stats",
                auth=alice_auth,
            )
            assert_status(response, 200, "통계")
            assert response.json()["count"] == 2
            assert response.json()["average_weight"] == 60.75

            response = client.delete(
                f"/records/{second_id}",
                auth=alice_auth,
            )
            assert_status(response, 200, "삭제")

            response = client.delete(
                f"/records/{second_id}",
                auth=alice_auth,
            )
            assert_status(response, 404, "삭제된 기록 재삭제")

        assert db_path.exists(), "SQLite 파일이 생성되지 않았습니다."

        # 같은 DB 파일을 사용해 모듈과 앱을 다시 로드한다.
        module_restarted = load_app("health_log_app_restarted")

        with TestClient(module_restarted.app) as client:
            response = client.post(
                "/users/login",
                auth=("alice", "test1234"),
            )
            assert_status(response, 200, "재시작 후 로그인")

            response = client.get(
                "/records",
                auth=("alice", "test1234"),
            )
            assert_status(response, 200, "재시작 후 기록 조회")
            assert response.json()["count"] == 1
            assert response.json()["records"][0]["memo"] == (
                "수정 결과 유지 확인"
            )

            response = client.post(
                "/records",
                auth=("alice", "test1234"),
                json=record_payload("2026-07-03"),
            )
            assert_status(response, 201, "재시작 후 새 기록")
            assert response.json()["id"] > second_id

        # 파생값은 DB 컬럼에 저장하지 않는지 확인한다.
        import sqlite3

        connection = sqlite3.connect(db_path)
        try:
            record_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(health_records)"
                ).fetchall()
            }
            assert "bmi" not in record_columns
            assert "bmi_category" not in record_columns
            assert "bp_category" not in record_columns
            assert "sugar_category" not in record_columns
            assert "warnings" not in record_columns
            assert "created_at" in record_columns
            assert "updated_at" in record_columns

            foreign_keys = connection.execute(
                "PRAGMA foreign_key_list(health_records)"
            ).fetchall()
            assert foreign_keys, "외래키가 정의되지 않았습니다."
        finally:
            connection.close()

    print("SQLite 스모크 테스트: 모든 항목 통과")


if __name__ == "__main__":
    run_test()