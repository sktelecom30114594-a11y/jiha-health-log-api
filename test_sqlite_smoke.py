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
CHART_JS_PATH = Path(__file__).with_name("chart.umd.min.js")
DOCKERFILE_PATH = Path(__file__).with_name("Dockerfile")


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

        assert module.describe_weekly_change(
            label="수축기 혈압",
            value=-2.28,
            unit="mmHg",
            digits=0,
        ) == "평균 수축기 혈압이 직전 기간보다 2mmHg 감소했습니다."
        assert module.describe_weekly_change(
            label="이완기 혈압",
            value=0.43,
            unit="mmHg",
            digits=0,
        ) == "평균 이완기 혈압은 직전 기간과 같습니다."
        assert module.describe_weekly_change(
            label="공복혈당",
            value=-4.4,
            unit="mg/dL",
            digits=0,
        ) == "평균 공복혈당이 직전 기간보다 4mg/dL 감소했습니다."
        assert module.describe_weekly_change(
            label="걸음 수",
            value=772.85,
            unit="보",
            subject_particle="가",
            topic_particle="는",
            digits=0,
        ) == "평균 걸음 수가 직전 기간보다 773보 증가했습니다."

        assert CHART_JS_PATH.is_file(), "Chart.js 파일이 없습니다."
        chart_js_header = CHART_JS_PATH.read_text(
            encoding="utf-8",
        )[:300]
        assert "Chart.js v4.5.1" in chart_js_header

        assert DOCKERFILE_PATH.is_file(), "Dockerfile이 없습니다."
        dockerfile_text = DOCKERFILE_PATH.read_text(encoding="utf-8")
        assert (
            "COPY main.py seed_year_data.py dashboard.html "
            "chart.umd.min.js ./"
            in dockerfile_text
        )

        with TestClient(module.app) as client:
            response = client.get("/static/chart.umd.min.js")
            assert_status(response, 200, "로컬 Chart.js 응답")
            assert response.headers["content-type"].startswith(
                "application/javascript"
            )
            assert "Chart.js v4.5.1" in response.text[:300]

            response = client.get("/dashboard")
            assert_status(response, 200, "대시보드 HTML 응답")
            assert response.headers["content-type"].startswith(
                "text/html"
            )
            assert "마이 헬스 로그 대시보드" in response.text
            assert 'id="loginForm"' in response.text
            assert 'id="recordsBody"' in response.text
            assert 'id="recordsSearchForm"' in response.text
            assert 'id="startDate"' in response.text
            assert 'id="endDate"' in response.text
            assert 'id="sortBy"' in response.text
            assert 'id="sortOrder"' in response.text
            assert 'id="bmiCategory"' in response.text
            assert 'id="bpCategory"' in response.text
            assert 'id="sugarCategory"' in response.text
            assert 'id="pageSize"' in response.text
            assert 'id="searchRecordsButton"' in response.text
            assert 'id="resetSearchButton"' in response.text
            assert 'id="previousPageButton"' in response.text
            assert 'id="nextPageButton"' in response.text
            assert 'id="paginationInfo"' in response.text
            assert "/records/explore" in response.text
            assert 'src="/static/chart.umd.min.js"' in response.text
            assert 'id="trendSection"' in response.text
            assert 'id="trendForm"' in response.text
            assert 'id="trendMetric"' in response.text
            assert 'id="trendPeriod"' in response.text
            assert 'id="trendCustomDates"' in response.text
            assert 'id="trendStartDate"' in response.text
            assert 'id="trendEndDate"' in response.text
            assert 'id="loadTrendButton"' in response.text
            assert 'id="trendMinimumValue"' in response.text
            assert 'id="trendMaximumValue"' in response.text
            assert 'id="trendAverageValue"' in response.text
            assert 'id="trendStatusPanel"' in response.text
            assert 'id="trendStatusBadge"' in response.text
            assert 'id="trendStatusText"' in response.text
            assert 'id="trendDangerAlert"' in response.text
            assert 'id="trendChart"' in response.text
            assert 'id="trendEmpty"' in response.text
            assert "/reports/trends" in response.text
            assert "new Chart(canvas" in response.text
            assert 'chartType: "bar"' in response.text
            assert 'type: definition.chartType' in response.text
            assert 'type: "line"' in response.text
            assert 'const isBarChart = definition.chartType === "bar"' in response.text
            assert 'statusKey: "blood_pressure"' in response.text
            assert 'statusKey: "blood_sugar"' in response.text
            assert "function renderTrendStatus(payload, definition)" in response.text
            assert 'statusSummary.level === "위험"' in response.text
            assert "위험 수치가 감지되었습니다." in response.text
            assert "trendRiskBackgroundPlugin" not in response.text
            assert "drawTrendRiskBand" not in response.text
            assert "drawTrendThresholdLine" not in response.text
            assert "TREND_CAUTION_BACKGROUND" not in response.text
            assert "TREND_DANGER_BACKGROUND" not in response.text
            assert "TREND_THRESHOLD_DASH" not in response.text
            assert 'id="trendGuide"' not in response.text
            assert 'id="trendGuideItems"' not in response.text
            assert "그래프 읽는 법" not in response.text
            assert 'id="trendPointLegend"' in response.text
            assert (
                "파란 점: 정상 · 주황 점: 주의 · 빨간 점: 위험"
                in response.text
            )
            assert 'const TREND_NORMAL_COLOR = "#2764e7";' in response.text
            assert (
                'return usesRiskColors ? TREND_NORMAL_COLOR : normalColor;'
                in response.text
            )
            assert "function renderTrendPointLegend(definition)" in response.text
            assert (
                "Chart.defaults.plugins.legend.labels.generateLabels(chart)"
                in response.text
            )
            assert "function buildTrendPointBackgroundColors(" in response.text
            assert "trendGuideDefinitions" not in response.text
            assert ".trend-guide" not in response.text
            assert ".trend-point-legend" in response.text
            assert "pointBackgroundColor: pointBackgroundColors" in response.text
            assert "value >= 140" in response.text
            assert "value >= 120" in response.text
            assert "value >= 90" in response.text
            assert "value >= 80" in response.text
            assert "value >= 126" in response.text
            assert "value >= 100" in response.text
            assert "chartjs-plugin-annotation" not in response.text
            assert "cdn.jsdelivr.net" not in response.text
            assert (
                'formatNumber(current.average_blood_sugar, 0)'
                in response.text
            )
            assert (
                'setMetricChange("bloodSugarChange", '
                'changes && changes.blood_sugar, "mg/dL", 0)'
                in response.text
            )
            assert (
                'setMetricChange("stepsChange", '
                'changes && changes.steps, "보", 0)'
                in response.text
            )

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

            weekly_auth = ("weekly", "weekly123")
            explorer_auth = ("explorer", "explore123")

            response = client.post(
                "/users/register",
                json={
                    "username": "weekly",
                    "password": "weekly123",
                },
            )
            assert_status(response, 201, "주간 리포트 사용자 가입")

            response = client.post(
                "/users/register",
                json={
                    "username": "explorer",
                    "password": "explore123",
                },
            )
            assert_status(response, 201, "기록 탐색 사용자 가입")

            response = client.get(
                "/reports/weekly",
                auth=weekly_auth,
            )
            assert_status(response, 404, "기록 없는 주간 리포트")

            response = client.get(
                "/reports/trends",
                auth=weekly_auth,
            )
            assert_status(response, 404, "기록 없는 변화 그래프")

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
                "/records",
                auth=alice_auth,
                params={"limit": 1, "order": "desc"},
            )
            assert_status(response, 200, "최신 기록 제한 조회")
            assert response.json()["count"] == 1
            assert response.json()["records"][0]["date"] == (
                "2026-07-02"
            )

            response = client.get(
                "/records",
                auth=alice_auth,
                params={"limit": 0},
            )
            assert_status(response, 422, "잘못된 기록 제한값")

            response = client.get(
                "/records",
                auth=alice_auth,
                params={"order": "newest"},
            )
            assert_status(response, 422, "잘못된 정렬값")

            explorer_records = [
                record_payload(
                    "2026-08-01",
                    weight=60.0,
                    systolic=125,
                    diastolic=82,
                    blood_sugar=105,
                    steps=1000,
                    sleep_hours=6.0,
                ),
                record_payload(
                    "2026-08-02",
                    weight=60.0,
                    systolic=125,
                    diastolic=82,
                    blood_sugar=105,
                    steps=2000,
                    sleep_hours=6.5,
                ),
                record_payload(
                    "2026-08-03",
                    weight=50.0,
                    systolic=118,
                    diastolic=76,
                    blood_sugar=92,
                    steps=3000,
                    sleep_hours=7.0,
                ),
                record_payload(
                    "2026-08-04",
                    weight=50.0,
                    systolic=120,
                    diastolic=80,
                    blood_sugar=99,
                    steps=4000,
                    sleep_hours=7.5,
                ),
                record_payload(
                    "2026-08-05",
                    weight=68.0,
                    systolic=145,
                    diastolic=92,
                    blood_sugar=130,
                    steps=5000,
                    sleep_hours=8.0,
                ),
                record_payload(
                    "2026-08-06",
                    weight=75.0,
                    systolic=130,
                    diastolic=85,
                    blood_sugar=110,
                    steps=6000,
                    sleep_hours=8.5,
                ),
                record_payload(
                    "2026-08-07",
                    weight=50.0,
                    systolic=118,
                    diastolic=76,
                    blood_sugar=92,
                    steps=7000,
                    sleep_hours=9.0,
                ),
                record_payload(
                    "2026-08-08",
                    weight=68.0,
                    systolic=140,
                    diastolic=90,
                    blood_sugar=126,
                    steps=8000,
                    sleep_hours=5.5,
                ),
                record_payload(
                    "2026-08-09",
                    weight=68.0,
                    systolic=135,
                    diastolic=88,
                    blood_sugar=120,
                    steps=9000,
                    sleep_hours=6.0,
                ),
                record_payload(
                    "2026-08-10",
                    weight=75.0,
                    systolic=150,
                    diastolic=95,
                    blood_sugar=140,
                    steps=10000,
                    sleep_hours=6.5,
                ),
                record_payload(
                    "2026-08-11",
                    weight=50.0,
                    systolic=120,
                    diastolic=80,
                    blood_sugar=99,
                    steps=11000,
                    sleep_hours=7.0,
                ),
                record_payload(
                    "2026-08-12",
                    weight=68.0,
                    systolic=119,
                    diastolic=79,
                    blood_sugar=100,
                    steps=12000,
                    sleep_hours=7.5,
                ),
            ]

            for index, payload in enumerate(explorer_records, start=1):
                response = client.post(
                    "/records",
                    auth=explorer_auth,
                    json=payload,
                )
                assert_status(
                    response,
                    201,
                    f"기록 탐색 테스트 데이터 {index}",
                )

            response = client.post(
                "/records",
                auth=bob_auth,
                json=record_payload(
                    "2026-08-12",
                    weight=99.0,
                    systolic=180,
                    diastolic=100,
                    blood_sugar=180,
                    steps=100,
                    sleep_hours=2.0,
                ),
            )
            assert_status(response, 201, "탐색 사용자 격리용 기록")

            response = client.get("/reports/trends")
            assert_status(response, 401, "변화 그래프 인증 필요")

            response = client.get(
                "/reports/trends",
                auth=explorer_auth,
            )
            assert_status(response, 200, "변화 그래프 기본 30일")
            trend_result = response.json()
            assert trend_result["period"] == {
                "mode": "30d",
                "start_date": "2026-07-14",
                "end_date": "2026-08-12",
                "total_days": 30,
                "record_count": 12,
            }
            assert len(trend_result["points"]) == 30
            assert trend_result["points"][0] == {
                "date": "2026-07-14",
                "weight": None,
                "systolic": None,
                "diastolic": None,
                "blood_sugar": None,
                "steps": None,
                "sleep_hours": None,
            }
            assert trend_result["points"][-1]["date"] == "2026-08-12"
            assert trend_result["points"][-1]["weight"] == 68.0
            assert trend_result["summary"]["weight"] == {
                "minimum": 50.0,
                "maximum": 75.0,
                "average": 61.83,
            }
            assert trend_result["summary"]["steps"] == {
                "minimum": 1000.0,
                "maximum": 12000.0,
                "average": 6500.0,
            }
            assert trend_result["status"] == {
                "blood_pressure": {
                    "level": "위험",
                    "total_count": 12,
                    "normal_count": 3,
                    "caution_count": 6,
                    "danger_count": 3,
                },
                "blood_sugar": {
                    "level": "위험",
                    "total_count": 12,
                    "normal_count": 4,
                    "caution_count": 5,
                    "danger_count": 3,
                },
            }

            for period, expected_start, expected_days in [
                ("7d", "2026-08-06", 7),
                ("90d", "2026-05-15", 90),
                ("1y", "2025-08-13", 365),
            ]:
                response = client.get(
                    "/reports/trends",
                    auth=explorer_auth,
                    params={"period": period},
                )
                assert_status(
                    response,
                    200,
                    f"변화 그래프 {period} 기간",
                )
                trend_result = response.json()
                assert trend_result["period"]["start_date"] == (
                    expected_start
                )
                assert trend_result["period"]["end_date"] == (
                    "2026-08-12"
                )
                assert trend_result["period"]["total_days"] == (
                    expected_days
                )
                assert len(trend_result["points"]) == expected_days

            response = client.get(
                "/reports/trends",
                auth=explorer_auth,
                params={
                    "period": "custom",
                    "start_date": "2026-08-03",
                    "end_date": "2026-08-05",
                },
            )
            assert_status(response, 200, "변화 그래프 직접 설정")
            trend_result = response.json()
            assert trend_result["period"] == {
                "mode": "custom",
                "start_date": "2026-08-03",
                "end_date": "2026-08-05",
                "total_days": 3,
                "record_count": 3,
            }
            assert [
                point["date"] for point in trend_result["points"]
            ] == [
                "2026-08-03",
                "2026-08-04",
                "2026-08-05",
            ]
            assert trend_result["summary"]["blood_sugar"] == {
                "minimum": 92.0,
                "maximum": 130.0,
                "average": 107.0,
            }
            assert trend_result["status"]["blood_pressure"] == {
                "level": "위험",
                "total_count": 3,
                "normal_count": 1,
                "caution_count": 1,
                "danger_count": 1,
            }
            assert trend_result["status"]["blood_sugar"] == {
                "level": "위험",
                "total_count": 3,
                "normal_count": 2,
                "caution_count": 0,
                "danger_count": 1,
            }

            response = client.get(
                "/reports/trends",
                auth=explorer_auth,
                params={
                    "period": "custom",
                    "start_date": "2026-07-31",
                    "end_date": "2026-08-02",
                },
            )
            assert_status(response, 200, "변화 그래프 기록 없는 날짜")
            trend_result = response.json()
            assert trend_result["period"]["record_count"] == 2
            assert trend_result["points"][0] == {
                "date": "2026-07-31",
                "weight": None,
                "systolic": None,
                "diastolic": None,
                "blood_sugar": None,
                "steps": None,
                "sleep_hours": None,
            }

            response = client.get(
                "/reports/trends",
                auth=explorer_auth,
                params={
                    "period": "custom",
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-03",
                },
            )
            assert_status(response, 200, "변화 그래프 빈 기간")
            trend_result = response.json()
            assert trend_result["period"]["record_count"] == 0
            assert len(trend_result["points"]) == 3
            assert all(
                point["weight"] is None
                for point in trend_result["points"]
            )
            assert trend_result["summary"]["weight"] == {
                "minimum": None,
                "maximum": None,
                "average": None,
            }
            assert trend_result["status"]["blood_pressure"] == {
                "level": "기록 없음",
                "total_count": 0,
                "normal_count": 0,
                "caution_count": 0,
                "danger_count": 0,
            }
            assert trend_result["status"]["blood_sugar"] == {
                "level": "기록 없음",
                "total_count": 0,
                "normal_count": 0,
                "caution_count": 0,
                "danger_count": 0,
            }

            for invalid_params, expected_status, label in [
                (
                    {"period": "custom", "start_date": "2026-08-01"},
                    400,
                    "변화 그래프 직접 설정 종료일 누락",
                ),
                (
                    {
                        "period": "custom",
                        "start_date": "2026-08-10",
                        "end_date": "2026-08-01",
                    },
                    400,
                    "변화 그래프 역전 날짜 범위",
                ),
                (
                    {"period": "7d", "start_date": "2026-08-01"},
                    400,
                    "변화 그래프 사전 기간과 직접 날짜 혼용",
                ),
                (
                    {"period": "14d"},
                    422,
                    "변화 그래프 잘못된 기간",
                ),
            ]:
                response = client.get(
                    "/reports/trends",
                    auth=explorer_auth,
                    params=invalid_params,
                )
                assert_status(response, expected_status, label)

            response = client.get("/records/explore")
            assert_status(response, 401, "기록 탐색 인증 필요")

            response = client.get(
                "/records/explore",
                auth=explorer_auth,
            )
            assert_status(response, 200, "기록 탐색 기본 조회")
            explore_result = response.json()
            assert len(explore_result["items"]) == 10
            assert explore_result["items"][0]["date"] == "2026-08-12"
            assert explore_result["pagination"] == {
                "page": 1,
                "page_size": 10,
                "total_items": 12,
                "total_pages": 2,
                "has_previous": False,
                "has_next": True,
            }

            response = client.get(
                "/records/explore",
                auth=explorer_auth,
                params={"page": 2},
            )
            assert_status(response, 200, "기록 탐색 다음 페이지")
            explore_result = response.json()
            assert [
                item["date"] for item in explore_result["items"]
            ] == ["2026-08-02", "2026-08-01"]
            assert explore_result["pagination"]["has_previous"] is True
            assert explore_result["pagination"]["has_next"] is False

            response = client.get(
                "/records/explore",
                auth=explorer_auth,
                params={"page_size": 20},
            )
            assert_status(response, 200, "기록 탐색 20건 페이지")
            assert len(response.json()["items"]) == 12
            assert response.json()["pagination"]["total_pages"] == 1

            response = client.get(
                "/records/explore",
                auth=explorer_auth,
                params={"start_date": "2026-08-10", "page_size": 20},
            )
            assert_status(response, 200, "기록 탐색 시작일만 적용")
            assert response.json()["pagination"]["total_items"] == 3

            response = client.get(
                "/records/explore",
                auth=explorer_auth,
                params={"end_date": "2026-08-02", "page_size": 20},
            )
            assert_status(response, 200, "기록 탐색 종료일만 적용")
            assert response.json()["pagination"]["total_items"] == 2

            response = client.get(
                "/records/explore",
                auth=explorer_auth,
                params={
                    "start_date": "2026-08-04",
                    "end_date": "2026-08-06",
                    "page_size": 20,
                },
            )
            assert_status(response, 200, "기록 탐색 날짜 범위")
            assert [
                item["date"] for item in response.json()["items"]
            ] == ["2026-08-06", "2026-08-05", "2026-08-04"]

            response = client.get(
                "/records/explore",
                auth=explorer_auth,
                params={
                    "start_date": "2026-08-10",
                    "end_date": "2026-08-01",
                },
            )
            assert_status(response, 400, "기록 탐색 역전 날짜 범위")

            sort_fields = [
                "date",
                "weight",
                "systolic",
                "diastolic",
                "blood_sugar",
                "steps",
                "sleep_hours",
            ]
            for sort_by in sort_fields:
                for order in ["asc", "desc"]:
                    response = client.get(
                        "/records/explore",
                        auth=explorer_auth,
                        params={
                            "sort_by": sort_by,
                            "order": order,
                            "page_size": 20,
                        },
                    )
                    assert_status(
                        response,
                        200,
                        f"기록 탐색 {sort_by} {order} 정렬",
                    )

                    def expected_sort_key(item):
                        if sort_by == "date":
                            return (item["date"],)
                        return (item[sort_by], item["date"])

                    expected_dates = [
                        item["date"]
                        for item in sorted(
                            explorer_records,
                            key=expected_sort_key,
                            reverse=(order == "desc"),
                        )
                    ]
                    actual_dates = [
                        item["date"]
                        for item in response.json()["items"]
                    ]
                    assert actual_dates == expected_dates

            response = client.get(
                "/records/explore",
                auth=explorer_auth,
                params={"bmi_category": "정상"},
            )
            assert_status(response, 200, "기록 탐색 BMI 상태 필터")
            assert response.json()["pagination"]["total_items"] == 2
            assert [
                item["date"] for item in response.json()["items"]
            ] == ["2026-08-02", "2026-08-01"]

            response = client.get(
                "/records/explore",
                auth=explorer_auth,
                params={"bp_category": "주의", "page_size": 20},
            )
            assert_status(response, 200, "기록 탐색 혈압 상태 필터")
            assert response.json()["pagination"]["total_items"] == 6

            response = client.get(
                "/records/explore",
                auth=explorer_auth,
                params={
                    "sugar_category": "공복혈당장애",
                    "page_size": 20,
                },
            )
            assert_status(response, 200, "기록 탐색 혈당 상태 필터")
            assert response.json()["pagination"]["total_items"] == 5

            response = client.get(
                "/records/explore",
                auth=explorer_auth,
                params={
                    "bmi_category": "정상",
                    "bp_category": "주의",
                    "sugar_category": "공복혈당장애",
                },
            )
            assert_status(response, 200, "기록 탐색 상태 AND 필터")
            assert response.json()["pagination"] == {
                "page": 1,
                "page_size": 10,
                "total_items": 2,
                "total_pages": 1,
                "has_previous": False,
                "has_next": False,
            }

            response = client.get(
                "/records/explore",
                auth=explorer_auth,
                params={
                    "start_date": "2027-01-01",
                    "end_date": "2027-01-31",
                },
            )
            assert_status(response, 200, "기록 탐색 빈 결과")
            assert response.json() == {
                "items": [],
                "pagination": {
                    "page": 1,
                    "page_size": 10,
                    "total_items": 0,
                    "total_pages": 0,
                    "has_previous": False,
                    "has_next": False,
                },
            }

            for invalid_params, label in [
                ({"sort_by": "memo"}, "잘못된 탐색 정렬 기준"),
                ({"order": "newest"}, "잘못된 탐색 정렬 순서"),
                ({"page": 0}, "잘못된 탐색 페이지"),
                ({"page_size": 7}, "잘못된 탐색 페이지 크기"),
                ({"bmi_category": "매우 정상"}, "잘못된 BMI 필터"),
                ({"bp_category": "위험"}, "잘못된 혈압 필터"),
                ({"sugar_category": "주의"}, "잘못된 혈당 필터"),
            ]:
                response = client.get(
                    "/records/explore",
                    auth=explorer_auth,
                    params=invalid_params,
                )
                assert_status(response, 422, label)

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

            response = client.post(
                "/records",
                auth=weekly_auth,
                json=record_payload(
                    "2026-07-14",
                    weight=66.0,
                    systolic=120,
                    diastolic=78,
                    blood_sugar=100,
                    steps=8000,
                    sleep_hours=7.0,
                ),
            )
            assert_status(response, 201, "주간 현재 기간 첫 기록")

            response = client.get(
                "/reports/weekly",
                auth=weekly_auth,
            )
            assert_status(response, 200, "이전 기록 없는 주간 리포트")
            report = response.json()
            assert report["current_period"]["record_count"] == 1
            assert report["previous_period"]["record_count"] == 0
            assert report["changes"] is None
            assert report["summary"] == [
                (
                    "비교할 이전 기록이 없어 "
                    "증감을 계산할 수 없습니다."
                )
            ]

            response = client.post(
                "/records",
                auth=weekly_auth,
                json=record_payload(
                    "2026-07-10",
                    weight=67.0,
                    systolic=122,
                    diastolic=79,
                    blood_sugar=102,
                    steps=7000,
                    sleep_hours=6.8,
                ),
            )
            assert_status(response, 201, "주간 현재 기간 두 번째 기록")

            response = client.post(
                "/records",
                auth=weekly_auth,
                json=record_payload(
                    "2026-07-01",
                    weight=70.0,
                    systolic=130,
                    diastolic=85,
                    blood_sugar=110,
                    steps=5000,
                    sleep_hours=6.0,
                ),
            )
            assert_status(response, 201, "주간 이전 기간 첫 기록")

            response = client.post(
                "/records",
                auth=weekly_auth,
                json=record_payload(
                    "2026-07-07",
                    weight=68.0,
                    systolic=126,
                    diastolic=82,
                    blood_sugar=106,
                    steps=6000,
                    sleep_hours=6.5,
                ),
            )
            assert_status(response, 201, "주간 이전 기간 두 번째 기록")

            response = client.post(
                "/records",
                auth=bob_auth,
                json=record_payload(
                    "2026-07-14",
                    weight=99.0,
                    systolic=180,
                    diastolic=100,
                    blood_sugar=180,
                    steps=100,
                    sleep_hours=2.0,
                ),
            )
            assert_status(response, 201, "다른 사용자 비교용 기록")

            response = client.get(
                "/reports/weekly",
                auth=weekly_auth,
            )
            assert_status(response, 200, "정상 주간 리포트")
            report = response.json()

            assert report["current_period"] == {
                "start_date": "2026-07-08",
                "end_date": "2026-07-14",
                "record_count": 2,
                "average_weight": 66.5,
                "average_systolic": 121.0,
                "average_diastolic": 78.5,
                "average_blood_sugar": 101.0,
                "average_steps": 7500.0,
                "average_sleep_hours": 6.9,
            }
            assert report["previous_period"] == {
                "start_date": "2026-07-01",
                "end_date": "2026-07-07",
                "record_count": 2,
                "average_weight": 69.0,
                "average_systolic": 128.0,
                "average_diastolic": 83.5,
                "average_blood_sugar": 108.0,
                "average_steps": 5500.0,
                "average_sleep_hours": 6.25,
            }
            assert report["changes"] == {
                "weight": -2.5,
                "systolic": -7.0,
                "diastolic": -5.0,
                "blood_sugar": -7.0,
                "steps": 2000.0,
                "sleep_hours": 0.65,
            }
            assert len(report["summary"]) == 6
            assert report["summary"][4] == (
                "평균 걸음 수가 직전 기간보다 "
                "2,000보 증가했습니다."
            )

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
