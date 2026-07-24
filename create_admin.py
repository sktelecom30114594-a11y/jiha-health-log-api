"""SQLite DB에 최초 관리자 계정을 안전하게 생성한다."""

from __future__ import annotations

import getpass
import sqlite3
from contextlib import closing

from pydantic import ValidationError

from main import (
    UserRegister,
    get_db_connection,
    init_database,
    normalize_username,
    password_hash,
    utc_now_iso,
)


def create_admin_account(username: str, password: str) -> str:
    """입력값을 검증하고 role이 admin인 계정을 생성한다."""

    validated = UserRegister(
        username=username,
        password=password,
    )
    normalized_username = normalize_username(validated.username)
    hashed_password = password_hash.hash(validated.password)

    init_database()

    try:
        with closing(get_db_connection()) as connection:
            with connection:
                existing = connection.execute(
                    "SELECT 1 FROM users WHERE username = ?",
                    (normalized_username,),
                ).fetchone()
                if existing is not None:
                    raise ValueError("이미 사용 중인 사용자명입니다.")

                connection.execute(
                    """
                    INSERT INTO users (
                        username,
                        hashed_password,
                        created_at,
                        role
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        normalized_username,
                        hashed_password,
                        utc_now_iso(),
                        "admin",
                    ),
                )
    except sqlite3.IntegrityError as error:
        raise ValueError("이미 사용 중인 사용자명입니다.") from error

    return normalized_username


def main() -> None:
    """터미널에서 관리자 생성 정보를 대화형으로 입력받는다."""

    username = input("관리자 사용자명: ").strip()
    password = getpass.getpass("관리자 비밀번호: ")
    password_confirm = getpass.getpass("관리자 비밀번호 확인: ")

    if password != password_confirm:
        print("관리자 생성 중단: 비밀번호가 일치하지 않습니다.")
        raise SystemExit(1)

    try:
        created_username = create_admin_account(username, password)
    except ValidationError as error:
        print(
            "관리자 생성 중단: 사용자명 또는 비밀번호 형식이 "
            "요구사항에 맞지 않습니다."
        )
        raise SystemExit(1) from error
    except ValueError as error:
        print("관리자 생성 중단: 이미 사용 중인 사용자명입니다.")
        raise SystemExit(1) from error

    print(f"관리자 계정 '{created_username}'을 생성했습니다.")


if __name__ == "__main__":
    main()
