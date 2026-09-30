import html
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import streamlit as st


# --------------------------------------------------
# 기본 설정
# --------------------------------------------------

st.set_page_config(
    page_title="우리 학교 달력별 급식",
    page_icon="🍚",
    layout="wide",
)

MEAL_API_URL = "https://open.neis.go.kr/hub/mealServiceDietInfo"

# 송탄고등학교 고정
SCHOOL_NAME = "송탄고등학교"
ATPT_OFCDC_SC_CODE = "J10"
SD_SCHUL_CODE = "7530480"

KST = ZoneInfo("Asia/Seoul")


# --------------------------------------------------
# API
# --------------------------------------------------

def get_meal(date):
    """선택한 날짜의 송탄고등학교 중식을 조회한다."""

    date_str = date.strftime("%Y%m%d")

    params = {
        "Type": "json",
        "ATPT_OFCDC_SC_CODE": ATPT_OFCDC_SC_CODE,
        "SD_SCHUL_CODE": SD_SCHUL_CODE,
        "MMEAL_SC_CODE": "2",
        "MLSV_FROM_YMD": date_str,
        "MLSV_TO_YMD": date_str,
        # 조회 기간을 하루로 제한하므로 무인증 API에서도 충분하다.
        "pSize": 5,
        "pIndex": 1,
    }

    try:
        response = requests.get(
            MEAL_API_URL,
            params=params,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

    except requests.RequestException:
        return None, "급식 정보를 불러오지 못했습니다."

    except ValueError:
        return None, "급식 정보 응답을 읽을 수 없습니다."

    service = data.get("mealServiceDietInfo", [])

    # RESULT 확인
    result_code = None

    for box in service:
        if not isinstance(box, dict):
            continue

        for head in box.get("head", []):
            result = head.get("RESULT")

            if result:
                result_code = result.get("CODE")
                break

        if result_code:
            break

    # 급식 데이터가 없는 날
    if result_code == "INFO-200":
        return [], None

    # 기타 API 오류
    if result_code and result_code != "INFO-000":
        return None, (
            "급식 정보를 불러오는 중 오류가 발생했습니다. "
            f"({result_code})"
        )

    # row 찾기
    for box in service:
        if isinstance(box, dict) and "row" in box:
            return box["row"], None

    return [], None


# --------------------------------------------------
# 메뉴 처리
# --------------------------------------------------

def split_menu(menu_text):
    """NEIS의 <br/> 구분 메뉴를 메뉴별로 나눈다."""

    if not menu_text:
        return []

    menu_text = (
        menu_text
        .replace("<br/>", "\n")
        .replace("<br>", "\n")
        .replace("<BR/>", "\n")
        .replace("<BR>", "\n")
    )

    items = []

    for item in menu_text.splitlines():
        item = item.strip()

        if item:
            items.append(item)

    return items


def remove_allergy_number(menu):
    """
    메뉴 마지막에 붙은 알레르기 번호를 제거한다.

    예:
    김치찌개(5.6.9) -> 김치찌개
    우유(2) -> 우유
    밥(1.2.3.5.6) -> 밥
    """

    return re.sub(
        r"\s*\(\s*\d+(?:\.\d+)*\s*\)\s*$",
        "",
        menu,
    ).strip()


# --------------------------------------------------
# 메뉴 카드
# --------------------------------------------------

def render_menu_card(menu):
    """메뉴 하나를 카드 형태로 출력한다."""

    safe_menu = html.escape(menu)

    st.markdown(
        f"""
        <div style="
            min-height: 105px;
            height: 100%;
            padding: 20px 16px;
            border: 1px solid #e5e7eb;
            border-radius: 16px;
            background: #ffffff;
            box-shadow: 0 3px 12px rgba(0, 0, 0, 0.06);
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
            box-sizing: border-box;
        ">
            <div style="
                font-size: 17px;
                font-weight: 600;
                line-height: 1.5;
                word-break: keep-all;
            ">
                {safe_menu}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# --------------------------------------------------
# 화면
# --------------------------------------------------

def main():

    st.title("우리 학교 달력별 급식")
    st.caption(f"{SCHOOL_NAME} · 중식")

    # 한국시간 기준 오늘
    today_kst = datetime.now(KST).date()

    # 날짜 / 알레르기 스위치를 나란히 배치
    date_col, allergy_col = st.columns([3, 2])

    with date_col:
        selected_date = st.date_input(
            "급식 날짜",
            value=today_kst,
        )

    with allergy_col:
        show_allergy = st.toggle(
            "알레르기 정보 보기",
            value=True,
        )

    # 날짜가 바뀌면 자동으로 해당 날짜를 조회할 수 있도록
    # 날짜를 포함한 키로 결과를 캐싱한다.
    rows, error = get_meal(selected_date)

    if error:
        st.error(error)
        return

    # 주말, 방학 등 급식이 없는 날
    if not rows:
        st.info("급식이 없는 날입니다")
        return

    meal = rows[0]

    raw_menu = meal.get("DDISH_NM", "")
    calories = meal.get("CAL_INFO", "").strip()

    menu_items = split_menu(raw_menu)

    if not menu_items:
        st.info("급식이 없는 날입니다")
        return

    # 알레르기 번호 표시 여부
    if not show_allergy:
        menu_items = [
            remove_allergy_number(menu)
            for menu in menu_items
        ]

    st.divider()

    # --------------------------------------------------
    # 큰 숫자 카드
    # --------------------------------------------------

    stat_col1, stat_col2 = st.columns(2)

    with stat_col1:
        st.metric(
            label="메뉴 가짓수",
            value=f"{len(menu_items)}개",
        )

    with stat_col2:
        st.metric(
            label="칼로리",
            value=calories if calories else "-",
        )

    st.markdown("### 오늘의 중식")

    # --------------------------------------------------
    # 메뉴 카드
    # --------------------------------------------------

    # 4열로 배치하고 메뉴 수에 따라 자동으로 다음 줄로 넘어간다.
    columns = st.columns(4)

    for index, menu in enumerate(menu_items):
        with columns[index % 4]:
            render_menu_card(menu)


if __name__ == "__main__":
    main()
