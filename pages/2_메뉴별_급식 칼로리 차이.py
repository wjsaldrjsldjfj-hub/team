import html
import re
from collections import defaultdict
from datetime import date

import pandas as pd
import plotly.express as px
import requests
import streamlit as st


# --------------------------------------------------
# 기본 설정
# --------------------------------------------------

st.set_page_config(
    page_title="우리 학교 메뉴별 급식 칼로리 차이",
    page_icon="📊",
    layout="wide",
)

MEAL_API_URL = "https://open.neis.go.kr/hub/mealServiceDietInfo"

# 송탄고등학교
SCHOOL_NAME = "송탄고등학교"
ATPT_OFCDC_SC_CODE = "J10"
SD_SCHUL_CODE = "7530480"

# 분석 기간: 2025년 9월 ~ 2026년 9월
START_DATE = date(2025, 9, 1)
END_DATE = date(2026, 9, 30)

PAGE_SIZE = 1000


# --------------------------------------------------
# API 인증키
# --------------------------------------------------

def get_api_key():
    """Streamlit Secrets에서 NEIS API 인증키를 가져온다."""

    try:
        api_key = st.secrets["NEIS_API_KEY"]
    except Exception:
        return None

    if not api_key:
        return None

    return str(api_key).strip()


# --------------------------------------------------
# NEIS API
# --------------------------------------------------

def request_meals(api_key):
    """
    인증키를 사용해 전체 급식 데이터를 페이지 단위로 가져온다.

    NEIS 응답의 list_total_count를 확인하고
    전체 건수를 받을 때까지 pIndex를 증가시킨다.
    """

    all_rows = []
    page_index = 1
    total_count = None

    while True:
        params = {
            "KEY": api_key,
            "Type": "json",
            "pIndex": page_index,
            "pSize": PAGE_SIZE,
            "ATPT_OFCDC_SC_CODE": ATPT_OFCDC_SC_CODE,
            "SD_SCHUL_CODE": SD_SCHUL_CODE,
            "MMEAL_SC_CODE": "2",
            "MLSV_FROM_YMD": START_DATE.strftime("%Y%m%d"),
            "MLSV_TO_YMD": END_DATE.strftime("%Y%m%d"),
        }

        try:
            response = requests.get(
                MEAL_API_URL,
                params=params,
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()

        except requests.RequestException as exc:
            raise RuntimeError(
                "NEIS 급식 API에 연결하지 못했습니다."
            ) from exc

        except ValueError as exc:
            raise RuntimeError(
                "NEIS API의 응답을 JSON으로 읽을 수 없습니다."
            ) from exc

        service = data.get("mealServiceDietInfo", [])

        # ----------------------------------------------
        # RESULT 확인
        # ----------------------------------------------

        result_code = None
        result_message = None

        for box in service:
            if not isinstance(box, dict):
                continue

            for head in box.get("head", []):
                result = head.get("RESULT")

                if result:
                    result_code = result.get("CODE")
                    result_message = result.get("MESSAGE")
                    break

            if result_code:
                break

        # 데이터가 없는 경우
        if result_code == "INFO-200":
            return []

        # 정상 외 응답
        if result_code and result_code not in ("INFO-000", "INFO-100"):
            raise RuntimeError(
                "NEIS API 오류가 발생했습니다. "
                f"{result_code}: {result_message or ''}"
            )

        # ----------------------------------------------
        # 전체 건수 확인
        # ----------------------------------------------

        page_rows = []

        for box in service:
            if not isinstance(box, dict):
                continue

            if "head" in box:
                for head in box["head"]:
                    if "list_total_count" in head:
                        total_count = int(
                            head["list_total_count"]
                        )

            if "row" in box:
                page_rows.extend(box["row"])

        all_rows.extend(page_rows)

        # 전체 건수를 모두 받았으면 종료
        if total_count is not None:
            if len(all_rows) >= total_count:
                break

        # 더 이상 데이터가 없으면 안전하게 종료
        if not page_rows:
            break

        # 다음 페이지
        page_index += 1

        # 예상치 못한 무한 반복 방지
        if page_index > 100:
            raise RuntimeError(
                "너무 많은 페이지가 반환되어 조회를 중단했습니다."
            )

    return all_rows[:total_count] if total_count else all_rows


# --------------------------------------------------
# 메뉴 처리
# --------------------------------------------------

def split_menu(menu_text):
    """<br/> 기준으로 하나의 급식 문자열을 메뉴별로 나눈다."""

    if not menu_text:
        return []

    normalized = (
        menu_text
        .replace("<br/>", "\n")
        .replace("<br>", "\n")
        .replace("<BR/>", "\n")
        .replace("<BR>", "\n")
    )

    result = []

    for item in normalized.splitlines():
        item = re.sub(r"<[^>]+>", "", item)
        item = html.unescape(item)
        item = item.strip()

        if item:
            result.append(item)

    return result


def remove_allergy_numbers(menu):
    """
    메뉴 마지막의 알레르기 번호를 제거한다.

    예:
    김치찌개(5.6.9) -> 김치찌개
    우유(2) -> 우유
    닭고기볶음(5.6.15) -> 닭고기볶음
    """

    return re.sub(
        r"\s*\(\s*\d+(?:\.\d+)*\s*\)\s*$",
        "",
        menu,
    ).strip()


def parse_calories(cal_info):
    """
    CAL_INFO에서 숫자를 추출한다.

    예:
    '734.2 Kcal' -> 734.2
    '734 Kcal' -> 734
    """

    if not cal_info:
        return None

    match = re.search(
        r"(\d+(?:\.\d+)?)",
        str(cal_info),
    )

    if not match:
        return None

    try:
        return float(match.group(1))
    except ValueError:
        return None


# --------------------------------------------------
# 데이터 집계
# --------------------------------------------------

def build_menu_statistics(rows):
    """
    급식 데이터를 메뉴별로 집계한다.

    같은 날 같은 메뉴가 여러 번 나오더라도
    해당 메뉴의 출현일은 하루로 계산한다.

    칼로리는 해당 메뉴가 포함된 급식의 칼로리 중
    가장 높은 값을 사용한다.
    """

    # 메뉴 -> {날짜들}
    menu_dates = defaultdict(set)

    # 메뉴 -> 해당 메뉴가 나온 급식의 칼로리들
    menu_calories = defaultdict(list)

    valid_meal_dates = set()

    for row in rows:
        meal_date_text = row.get("MLSV_YMD", "").strip()

        if not meal_date_text:
            continue

        # 날짜 형식 검증
        try:
            meal_date = date(
                int(meal_date_text[:4]),
                int(meal_date_text[4:6]),
                int(meal_date_text[6:8]),
            )
        except (ValueError, IndexError):
            continue

        # 요청 범위 밖 데이터 방어
        if not (START_DATE <= meal_date <= END_DATE):
            continue

        raw_menu = row.get("DDISH_NM", "")
        menus = split_menu(raw_menu)

        if not menus:
            continue

        valid_meal_dates.add(meal_date)

        calories = parse_calories(
            row.get("CAL_INFO", "")
        )

        # 같은 날 같은 메뉴가 여러 번 나와도
        # set을 사용하므로 하루로 한 번만 계산된다.
        seen_on_this_day = set()

        for menu in menus:
            clean_menu = remove_allergy_numbers(menu)

            if not clean_menu:
                continue

            # 같은 날 동일 메뉴 중복 제거
            menu_key = clean_menu

            if menu_key in seen_on_this_day:
                continue

            seen_on_this_day.add(menu_key)

            menu_dates[menu_key].add(meal_date)

            if calories is not None:
                menu_calories[menu_key].append(calories)

    # 데이터프레임 생성
    records = []

    total_days = len(valid_meal_dates)

    for menu, dates in menu_dates.items():
        days = len(dates)

        # 해당 메뉴가 나온 급식의 최대 칼로리
        max_calories = (
            max(menu_calories[menu])
            if menu_calories[menu]
            else None
        )

        # 메뉴가 나온 비율
        ratio = (
            days / total_days * 100
            if total_days > 0
            else 0
        )

        records.append(
            {
                "메뉴": menu,
                "일수": days,
                "비율": ratio,
                "최고 칼로리": max_calories,
            }
        )

    df = pd.DataFrame(records)

    if df.empty:
        return df, total_days

    # 최고 칼로리가 있는 메뉴를 먼저 정렬
    df = df.sort_values(
        by=["최고 칼로리", "일수"],
        ascending=[False, False],
        na_position="last",
    ).reset_index(drop=True)

    return df, total_days


# --------------------------------------------------
# 그래프
# --------------------------------------------------

def make_calorie_chart(df, top_n):
    """최고 칼로리 기준 TOP N 가로 막대그래프."""

    chart_df = (
        df.dropna(subset=["최고 칼로리"])
        .head(top_n)
        .copy()
    )

    if chart_df.empty:
        return None

    # Plotly 가로 막대에서 첫 번째 항목이 위로 오도록
    # 순서를 역순으로 넣는다.
    chart_df = chart_df.iloc[::-1]

    fig = px.bar(
        chart_df,
        x="최고 칼로리",
        y="메뉴",
        orientation="h",
        text="최고 칼로리",
        color="최고 칼로리",
        color_continuous_scale=[
            "#dbeafe",
            "#60a5fa",
            "#2563eb",
            "#1e3a8a",
        ],
    )

    fig.update_traces(
        texttemplate="%{text:.0f} kcal",
        textposition="outside",
        hovertemplate=(
            "<b>%{y}</b><br>"
            "최고 칼로리: %{x:.1f} kcal"
            "<extra></extra>"
        ),
    )

    fig.update_layout(
        xaxis_title="최고 칼로리 (kcal)",
        yaxis_title=None,
        coloraxis_showscale=False,
        height=max(420, top_n * 55),
        margin=dict(
            l=10,
            r=60,
            t=20,
            b=20,
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
    )

    return fig


# --------------------------------------------------
# 메인 화면
# --------------------------------------------------

def main():

    st.title("우리 학교 메뉴별 급식 칼로리 차이")

    st.caption(
        f"{SCHOOL_NAME} · "
        f"{START_DATE.strftime('%Y.%m.%d')} ~ "
        f"{END_DATE.strftime('%Y.%m.%d')} · 중식"
    )

    api_key = get_api_key()

    if not api_key:
        st.error(
            "NEIS_API_KEY가 설정되어 있지 않습니다. "
            "Streamlit Secrets에 NEIS_API_KEY를 추가해 주세요."
        )
        st.stop()

    # ----------------------------------------------
    # 데이터 조회
    # ----------------------------------------------

    @st.cache_data(
        ttl=60 * 60 * 24,
        show_spinner=False,
    )
    def load_data(key):
        return request_meals(key)

    with st.spinner(
        "2025년 9월부터 2026년 9월까지 급식 데이터를 불러오는 중..."
    ):
        try:
            rows = load_data(api_key)

        except RuntimeError as exc:
            st.error(str(exc))
            st.stop()

    if not rows:
        st.info("해당 기간에 급식 데이터가 없습니다.")
        st.stop()

    # ----------------------------------------------
    # 집계
    # ----------------------------------------------

    df, total_days = build_menu_statistics(rows)

    if df.empty:
        st.info("집계할 메뉴 데이터가 없습니다.")
        st.stop()

    # ----------------------------------------------
    # 상단 큰 숫자 카드
    # ----------------------------------------------

    top_menu = df.iloc[0]["메뉴"]
    top_ratio = df.iloc[0]["비율"]

    stat1, stat2, stat3 = st.columns(3)

    with stat1:
        st.metric(
            "집계한 급식 일수",
            f"{total_days:,}일",
        )

    with stat2:
        st.metric(
            "1위 메뉴",
            top_menu,
        )

    with stat3:
        st.metric(
            "1위 메뉴 출현 비율",
            f"{top_ratio:.1f}%",
        )

    st.divider()

    # ----------------------------------------------
    # TOP N 슬라이더
    # ----------------------------------------------

    max_top_n = min(10, len(df))

    top_n = st.slider(
        "몇 위까지 볼까요?",
        min_value=1,
        max_value=max_top_n,
        value=max_top_n,
        step=1,
    )

    st.subheader(
        f"최고 칼로리 TOP {top_n}"
    )

    chart = make_calorie_chart(
        df,
        top_n,
    )

    if chart:
        st.plotly_chart(
            chart,
            use_container_width=True,
        )

    # ----------------------------------------------
    # 메뉴별 출현 일수 / 비율
    # ----------------------------------------------

    st.subheader("메뉴별 출현 일수와 비율")

    table_df = df.copy()

    table_df["비율"] = table_df["비율"].map(
        lambda value: f"{value:.1f}%"
    )

    table_df["최고 칼로리"] = table_df[
        "최고 칼로리"
    ].map(
        lambda value: (
            f"{value:.0f} kcal"
            if pd.notna(value)
            else "-"
        )
    )

    table_df = table_df[
        [
            "메뉴",
            "일수",
            "비율",
            "최고 칼로리",
        ]
    ]

    table_df.columns = [
        "메뉴",
        "출현 일수",
        "출현 비율",
        "최고 칼로리",
    ]

    st.dataframe(
        table_df,
        use_container_width=True,
        hide_index=True,
    )


if __name__ == "__main__":
    main()
