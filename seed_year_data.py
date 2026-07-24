"""3명의 데모 사용자에게 1년치 현실형 합성 건강 데이터를 생성한다.

이 데이터는 API 기능 시연과 테스트를 위한 합성 시계열이며,
실제 개인의 건강 변화나 의학적 인과관계를 예측하지 않는다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import random
import statistics
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from main import (
    DB_PATH,
    RecordInput,
    calculate_bmi,
    classify_blood_pressure,
    classify_blood_sugar,
    classify_bmi,
    get_db_connection,
    init_database,
    password_hash,
    utc_now_iso,
)


START_DATE = dt.date(2025, 7, 1)
END_DATE = dt.date(2026, 6, 30)
TOTAL_DAYS = (END_DATE - START_DATE).days + 1
DEMO_PASSWORD = "demo1234"


@dataclass(frozen=True)
class DemoProfile:
    username: str
    label: str
    height: float
    seed: int


@dataclass(frozen=True)
class DailyRecord:
    date: dt.date
    weight: float
    height: float
    systolic: int
    diastolic: int
    blood_sugar: int
    steps: int
    sleep_hours: float
    memo: str

    def to_input(self) -> RecordInput:
        return RecordInput(
            date=self.date,
            weight=self.weight,
            height=self.height,
            systolic=self.systolic,
            diastolic=self.diastolic,
            blood_sugar=self.blood_sugar,
            steps=self.steps,
            sleep_hours=self.sleep_hours,
            memo=self.memo,
        )


PROFILES = (
    DemoProfile(
        username="demo_stable",
        label="정상 유지형",
        height=170.0,
        seed=2026072201,
    ),
    DemoProfile(
        username="demo_decline",
        label="생활 습관 악화형",
        height=173.0,
        seed=2026072202,
    ),
    DemoProfile(
        username="demo_recovery",
        label="생활 습관 개선형",
        height=170.0,
        seed=2026072203,
    ),
)


ACTIVITY_SEASON_FACTOR = {
    1: 0.84,
    2: 0.88,
    3: 1.02,
    4: 1.07,
    5: 1.08,
    6: 0.98,
    7: 0.93,
    8: 0.90,
    9: 1.03,
    10: 1.05,
    11: 0.98,
    12: 0.87,
}

SLEEP_SEASON_ADJUSTMENT = {
    1: 0.15,
    2: 0.10,
    3: 0.00,
    4: 0.05,
    5: 0.00,
    6: -0.05,
    7: -0.10,
    8: -0.15,
    9: 0.00,
    10: 0.05,
    11: 0.10,
    12: -0.05,
}


SPECIAL_MEMOS = {
    "demo_stable": {
        dt.date(2025, 9, 13): "주말 장거리 걷기",
        dt.date(2025, 12, 26): "연말 모임 후 수면 부족",
        dt.date(2026, 3, 16): "업무 마감으로 피로 누적",
    },
    "demo_decline": {
        dt.date(2025, 10, 15): "업무 증가로 운동량 감소 시작",
        dt.date(2026, 1, 12): "짧은 기간 운동 재개",
        dt.date(2026, 2, 20): "운동 중단 후 활동량 감소",
        dt.date(2026, 4, 1): "야근과 수면 부족 지속",
    },
    "demo_recovery": {
        dt.date(2025, 7, 1): "건강 관리 시작",
        dt.date(2025, 8, 15): "걷기 운동 적응",
        dt.date(2025, 11, 10): "감기로 활동량 일시 감소",
        dt.date(2026, 1, 5): "체중 감소 정체기",
        dt.date(2026, 3, 15): "운동 강도 재조정",
        dt.date(2026, 6, 30): "1년 건강 관리 완료",
    },
}


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def lerp(start: float, end: float, progress: float) -> float:
    return start + ((end - start) * progress)


def piecewise_progress(
    day_index: int,
    points: tuple[tuple[int, float], ...],
) -> float:
    if day_index <= points[0][0]:
        return points[0][1]

    for (left_day, left_value), (right_day, right_value) in zip(
        points,
        points[1:],
    ):
        if day_index <= right_day:
            width = right_day - left_day
            ratio = (day_index - left_day) / width
            return lerp(left_value, right_value, ratio)

    return points[-1][1]


def lifestyle_progress(username: str, day_index: int) -> float:
    if username == "demo_decline":
        return piecewise_progress(
            day_index,
            (
                (0, 0.00),
                (60, 0.13),
                (150, 0.53),
                (205, 0.38),
                (260, 0.68),
                (364, 1.00),
            ),
        )

    if username == "demo_recovery":
        return piecewise_progress(
            day_index,
            (
                (0, 0.00),
                (45, 0.11),
                (130, 0.49),
                (200, 0.57),
                (245, 0.48),
                (300, 0.79),
                (364, 1.00),
            ),
        )

    return 0.0


def in_period(
    current: dt.date,
    start: dt.date,
    end: dt.date,
) -> bool:
    return start <= current <= end


def event_modifiers(
    username: str,
    current: dt.date,
) -> dict[str, float]:
    modifiers = {
        "steps_multiplier": 1.0,
        "steps_add": 0.0,
        "sleep_add": 0.0,
        "weight_target_add": 0.0,
        "systolic_add": 0.0,
        "diastolic_add": 0.0,
        "sugar_add": 0.0,
    }

    if in_period(
        current,
        dt.date(2025, 12, 20),
        dt.date(2026, 1, 5),
    ):
        modifiers["steps_multiplier"] *= 0.76
        modifiers["sleep_add"] -= 0.45
        modifiers["weight_target_add"] += 0.65
        modifiers["systolic_add"] += 2.5
        modifiers["diastolic_add"] += 1.5
        modifiers["sugar_add"] += 3.5

    if username == "demo_stable":
        if in_period(
            current,
            dt.date(2025, 9, 10),
            dt.date(2025, 9, 14),
        ):
            modifiers["steps_add"] += 3500

        if in_period(
            current,
            dt.date(2026, 3, 10),
            dt.date(2026, 3, 18),
        ):
            modifiers["steps_multiplier"] *= 0.72
            modifiers["sleep_add"] -= 0.75
            modifiers["systolic_add"] += 4.0
            modifiers["diastolic_add"] += 2.5
            modifiers["sugar_add"] += 2.0

    if username == "demo_decline":
        if in_period(
            current,
            dt.date(2025, 10, 15),
            dt.date(2025, 11, 30),
        ) or in_period(
            current,
            dt.date(2026, 3, 1),
            dt.date(2026, 4, 15),
        ):
            modifiers["steps_multiplier"] *= 0.80
            modifiers["sleep_add"] -= 0.35
            modifiers["systolic_add"] += 2.0
            modifiers["diastolic_add"] += 1.5
            modifiers["sugar_add"] += 2.0

        if in_period(
            current,
            dt.date(2026, 1, 10),
            dt.date(2026, 2, 10),
        ):
            modifiers["steps_add"] += 1800
            modifiers["sleep_add"] += 0.35
            modifiers["weight_target_add"] -= 0.45
            modifiers["systolic_add"] -= 3.0
            modifiers["diastolic_add"] -= 2.0
            modifiers["sugar_add"] -= 3.0

    if username == "demo_recovery":
        if in_period(
            current,
            dt.date(2025, 11, 10),
            dt.date(2025, 11, 17),
        ):
            modifiers["steps_multiplier"] *= 0.42
            modifiers["sleep_add"] += 0.20
            modifiers["systolic_add"] += 4.0
            modifiers["diastolic_add"] += 2.0
            modifiers["sugar_add"] += 2.0

        if in_period(
            current,
            dt.date(2026, 1, 1),
            dt.date(2026, 2, 15),
        ):
            modifiers["weight_target_add"] += 0.55

        if in_period(
            current,
            dt.date(2026, 3, 15),
            dt.date(2026, 4, 30),
        ):
            modifiers["steps_add"] += 750
            modifiers["sleep_add"] += 0.15

    return modifiers


def weekend_steps_adjustment(username: str, weekday: int) -> int:
    if weekday == 5:  # Saturday
        return {
            "demo_stable": 1500,
            "demo_decline": -300,
            "demo_recovery": 2200,
        }[username]

    if weekday == 6:  # Sunday
        return {
            "demo_stable": -500,
            "demo_decline": -1000,
            "demo_recovery": 800,
        }[username]

    return 0


def base_targets(
    profile: DemoProfile,
    day_index: int,
) -> tuple[float, float, float, float, float, float]:
    progress = lifestyle_progress(profile.username, day_index)

    if profile.username == "demo_stable":
        annual_wave = math.sin((2 * math.pi * day_index) / 365)
        return (
            60.5 + (0.35 * annual_wave),
            9200.0,
            7.25,
            116.0,
            74.0,
            91.0,
        )

    if profile.username == "demo_decline":
        weight_progress = lifestyle_progress(
            profile.username,
            max(0, day_index - 21),
        )
        return (
            lerp(73.5, 82.5, weight_progress),
            lerp(8200.0, 3500.0, progress),
            lerp(7.0, 5.3, progress),
            lerp(126.0, 144.0, progress),
            lerp(81.0, 94.0, progress),
            lerp(107.0, 129.0, progress),
        )

    weight_progress = lifestyle_progress(
        profile.username,
        max(0, day_index - 21),
    )
    return (
        lerp(80.0, 66.0, weight_progress),
        lerp(3200.0, 9500.0, progress),
        lerp(5.4, 7.35, progress),
        lerp(149.0, 119.0, progress),
        lerp(96.0, 78.0, progress),
        lerp(134.0, 96.0, progress),
    )


def generate_profile_records(
    profile: DemoProfile,
) -> list[DailyRecord]:
    rng = random.Random(profile.seed)

    if profile.username == "demo_stable":
        current_weight = 60.5
    elif profile.username == "demo_decline":
        current_weight = 73.5
    else:
        current_weight = 80.0

    step_noise = 0.0
    sleep_noise = 0.0
    weight_noise = 0.0
    systolic_noise = 0.0
    diastolic_noise = 0.0
    sugar_noise = 0.0

    steps_history: list[int] = []
    sleep_history: list[float] = []
    records: list[DailyRecord] = []

    for day_index in range(TOTAL_DAYS):
        current_date = START_DATE + dt.timedelta(days=day_index)
        (
            weight_target,
            steps_target,
            sleep_target,
            systolic_target,
            diastolic_target,
            sugar_target,
        ) = base_targets(profile, day_index)

        modifiers = event_modifiers(profile.username, current_date)

        step_noise = (0.62 * step_noise) + rng.gauss(0, 720)
        sleep_noise = (0.52 * sleep_noise) + rng.gauss(0, 0.24)

        steps = (
            steps_target
            * ACTIVITY_SEASON_FACTOR[current_date.month]
            * modifiers["steps_multiplier"]
            + modifiers["steps_add"]
            + weekend_steps_adjustment(
                profile.username,
                current_date.weekday(),
            )
            + step_noise
        )

        sleep_hours = (
            sleep_target
            + SLEEP_SEASON_ADJUSTMENT[current_date.month]
            + modifiers["sleep_add"]
            + sleep_noise
        )

        rare_fatigue = rng.random() < 0.018
        if rare_fatigue:
            steps -= rng.uniform(1800, 3200)
            sleep_hours -= rng.uniform(0.35, 0.85)

        steps = int(round(clamp(steps, 700, 18000) / 10) * 10)
        sleep_hours = round(clamp(sleep_hours, 3.6, 9.3), 1)

        steps_history.append(steps)
        sleep_history.append(sleep_hours)

        recent_steps = statistics.fmean(steps_history[-7:])
        recent_sleep = statistics.fmean(sleep_history[-7:])

        low_activity = max(0.0, (7000.0 - recent_steps) / 3000.0)
        sleep_debt = max(0.0, 7.0 - recent_sleep)

        weight_noise = (0.80 * weight_noise) + rng.gauss(0, 0.075)
        desired_weight = (
            weight_target
            + modifiers["weight_target_add"]
            + (0.10 * sleep_debt)
            + (0.08 * low_activity)
        )
        daily_weight_change = (
            0.10 * (desired_weight - current_weight)
            + weight_noise
        )
        daily_weight_change = clamp(daily_weight_change, -0.45, 0.45)
        current_weight += daily_weight_change
        current_weight = clamp(current_weight, 45.0, 130.0)
        weight = round(current_weight, 1)

        systolic_noise = (
            0.58 * systolic_noise
            + rng.gauss(0, 2.3)
        )
        diastolic_noise = (
            0.58 * diastolic_noise
            + rng.gauss(0, 1.7)
        )
        sugar_noise = (
            0.56 * sugar_noise
            + rng.gauss(0, 2.5)
        )

        systolic = (
            systolic_target
            + (2.0 * sleep_debt)
            + (1.5 * low_activity)
            + modifiers["systolic_add"]
            + systolic_noise
        )
        diastolic = (
            diastolic_target
            + (1.1 * sleep_debt)
            + (0.9 * low_activity)
            + modifiers["diastolic_add"]
            + diastolic_noise
        )
        blood_sugar = (
            sugar_target
            + (1.7 * sleep_debt)
            + (1.2 * low_activity)
            + modifiers["sugar_add"]
            + sugar_noise
        )

        if rare_fatigue:
            systolic += rng.uniform(2.0, 5.0)
            diastolic += rng.uniform(1.0, 3.0)
            blood_sugar += rng.uniform(1.0, 4.0)

        systolic_int = int(round(clamp(systolic, 95, 175)))
        diastolic_int = int(round(clamp(diastolic, 55, 110)))

        if systolic_int <= diastolic_int:
            systolic_int = diastolic_int + 15

        blood_sugar_int = int(round(clamp(blood_sugar, 70, 170)))

        memo = SPECIAL_MEMOS.get(profile.username, {}).get(
            current_date,
            "",
        )
        if rare_fatigue and not memo:
            memo = "피로 누적으로 활동량 감소"

        record = DailyRecord(
            date=current_date,
            weight=weight,
            height=profile.height,
            systolic=systolic_int,
            diastolic=diastolic_int,
            blood_sugar=blood_sugar_int,
            steps=steps,
            sleep_hours=sleep_hours,
            memo=memo,
        )

        record.to_input()
        records.append(record)

    return records


def average_window(
    records: list[DailyRecord],
    field_name: str,
    first: bool,
) -> float:
    window = records[:30] if first else records[-30:]
    return round(
        statistics.fmean(
            float(getattr(record, field_name))
            for record in window
        ),
        2,
    )


def validate_profile_records(
    profile: DemoProfile,
    records: list[DailyRecord],
) -> None:
    assert len(records) == TOTAL_DAYS == 365
    assert len({record.date for record in records}) == 365
    assert records[0].date == START_DATE
    assert records[-1].date == END_DATE

    for record in records:
        assert 45.0 <= record.weight <= 130.0
        assert 700 <= record.steps <= 18000
        assert 3.6 <= record.sleep_hours <= 9.3
        assert 95 <= record.systolic <= 175
        assert 55 <= record.diastolic <= 110
        assert 70 <= record.blood_sugar <= 170
        assert record.systolic > record.diastolic
        record.to_input()

    max_weight_change = max(
        abs(current.weight - previous.weight)
        for previous, current in zip(records, records[1:])
    )
    assert max_weight_change <= 0.6

    first = {
        field: average_window(records, field, first=True)
        for field in (
            "weight",
            "systolic",
            "diastolic",
            "blood_sugar",
            "steps",
            "sleep_hours",
        )
    }
    last = {
        field: average_window(records, field, first=False)
        for field in first
    }

    if profile.username == "demo_stable":
        assert abs(last["weight"] - first["weight"]) < 1.5
        assert abs(last["systolic"] - first["systolic"]) < 8
        assert abs(last["blood_sugar"] - first["blood_sugar"]) < 8
        assert abs(last["sleep_hours"] - first["sleep_hours"]) < 0.9

    elif profile.username == "demo_decline":
        assert last["weight"] > first["weight"] + 5.0
        assert last["systolic"] > first["systolic"] + 8.0
        assert last["blood_sugar"] > first["blood_sugar"] + 10.0
        assert last["steps"] < first["steps"] - 2500
        assert last["sleep_hours"] < first["sleep_hours"] - 0.8

    else:
        assert last["weight"] < first["weight"] - 8.0
        assert last["systolic"] < first["systolic"] - 15.0
        assert last["blood_sugar"] < first["blood_sugar"] - 20.0
        assert last["steps"] > first["steps"] + 3500
        assert last["sleep_hours"] > first["sleep_hours"] + 1.0


def category_counts(
    records: Iterable[DailyRecord],
) -> tuple[Counter[str], Counter[str], Counter[str]]:
    bmi_counts: Counter[str] = Counter()
    bp_counts: Counter[str] = Counter()
    sugar_counts: Counter[str] = Counter()

    for record in records:
        bmi = calculate_bmi(record.weight, record.height)
        bmi_counts[classify_bmi(bmi)] += 1
        bp_counts[
            classify_blood_pressure(
                record.systolic,
                record.diastolic,
            )
        ] += 1
        sugar_counts[
            classify_blood_sugar(record.blood_sugar)
        ] += 1

    return bmi_counts, bp_counts, sugar_counts


def print_profile_summary(
    profile: DemoProfile,
    records: list[DailyRecord],
) -> None:
    fields = (
        "weight",
        "systolic",
        "diastolic",
        "blood_sugar",
        "steps",
        "sleep_hours",
    )
    first = {
        field: average_window(records, field, first=True)
        for field in fields
    }
    last = {
        field: average_window(records, field, first=False)
        for field in fields
    }
    bmi_counts, bp_counts, sugar_counts = category_counts(records)

    print(f"\n[{profile.username}] {profile.label}")
    print(f"  기간/건수: {START_DATE} ~ {END_DATE} / {len(records)}건")
    print(
        "  첫 30일 → 마지막 30일 평균: "
        f"체중 {first['weight']} → {last['weight']}kg, "
        f"혈압 {first['systolic']}/{first['diastolic']} → "
        f"{last['systolic']}/{last['diastolic']}mmHg"
    )
    print(
        "  공복혈당/걸음/수면: "
        f"{first['blood_sugar']} → {last['blood_sugar']}mg/dL, "
        f"{first['steps']} → {last['steps']}보, "
        f"{first['sleep_hours']} → {last['sleep_hours']}시간"
    )
    print(f"  BMI 분류: {dict(bmi_counts)}")
    print(f"  혈압 분류: {dict(bp_counts)}")
    print(f"  혈당 분류: {dict(sugar_counts)}")


def create_all_datasets() -> dict[str, list[DailyRecord]]:
    datasets: dict[str, list[DailyRecord]] = {}

    for profile in PROFILES:
        records = generate_profile_records(profile)
        validate_profile_records(profile, records)
        datasets[profile.username] = records

    return datasets


def reset_demo_users() -> None:
    with get_db_connection() as connection:
        with connection:
            connection.executemany(
                "DELETE FROM users WHERE username = ?",
                [(profile.username,) for profile in PROFILES],
            )


def ensure_demo_user(
    connection,
    profile: DemoProfile,
) -> tuple[int, bool]:
    existing = connection.execute(
        "SELECT id FROM users WHERE username = ?",
        (profile.username,),
    ).fetchone()

    hashed_password = password_hash.hash(DEMO_PASSWORD)
    now = utc_now_iso()

    if existing is not None:
        connection.execute(
            """
            UPDATE users
            SET hashed_password = ?
            WHERE id = ?
            """,
            (hashed_password, existing["id"]),
        )
        return int(existing["id"]), False

    cursor = connection.execute(
        """
        INSERT INTO users (
            username,
            hashed_password,
            created_at,
            role
        )
        VALUES (?, ?, ?, ?)
        """,
        (profile.username, hashed_password, now, "user"),
    )
    return int(cursor.lastrowid), True


def seed_database(
    datasets: dict[str, list[DailyRecord]],
) -> None:
    init_database()
    total_inserted = 0
    total_skipped = 0

    with get_db_connection() as connection:
        with connection:
            for profile in PROFILES:
                user_id, created = ensure_demo_user(connection, profile)
                now = utc_now_iso()
                inserted = 0
                skipped = 0

                for record in datasets[profile.username]:
                    cursor = connection.execute(
                        """
                        INSERT OR IGNORE INTO health_records (
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
                            user_id,
                            record.date.isoformat(),
                            record.weight,
                            record.height,
                            record.systolic,
                            record.diastolic,
                            record.blood_sugar,
                            record.steps,
                            record.sleep_hours,
                            record.memo,
                            now,
                            now,
                        ),
                    )

                    if cursor.rowcount == 1:
                        inserted += 1
                    else:
                        skipped += 1

                total_inserted += inserted
                total_skipped += skipped
                user_status = "신규 생성" if created else "기존 계정 사용"
                print(
                    f"{profile.username}: {user_status}, "
                    f"삽입 {inserted}건, 기존 {skipped}건 건너뜀"
                )

    print(f"\nDB 경로: {DB_PATH}")
    print(f"총 삽입: {total_inserted}건")
    print(f"총 건너뜀: {total_skipped}건")
    print(f"데모 계정 공통 비밀번호: {DEMO_PASSWORD}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "3명의 데모 사용자에게 2025-07-01부터 "
            "2026-06-30까지 현실형 합성 건강 데이터를 생성합니다."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DB에 저장하지 않고 생성·검증 결과만 출력합니다.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help=(
            "기존 demo_stable, demo_decline, demo_recovery 계정과 "
            "기록을 삭제한 뒤 다시 생성합니다."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    datasets = create_all_datasets()

    print("현실형 합성 건강 데이터 검증 완료")
    for profile in PROFILES:
        print_profile_summary(profile, datasets[profile.username])

    if args.dry_run:
        print("\n--dry-run 옵션: SQLite에는 저장하지 않았습니다.")
        return

    if args.reset:
        init_database()
        reset_demo_users()
        print("\n기존 데모 계정과 기록을 삭제했습니다.")

    print("\nSQLite 저장 시작")
    seed_database(datasets)


if __name__ == "__main__":
    main()
