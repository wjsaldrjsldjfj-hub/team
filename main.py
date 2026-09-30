import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import streamlit as st


# --------------------------------------------------
# 기본 설정
# --------------------------------------------------

st.set_page_config(
    page_title="학교별로 급식 칼로리는 얼마나 차이가 날까?",
    page_icon="🍚",
    layout="wide",
)

SCHOOL_INFO_URL = "https://open.neis.go.kr/hub/schoolInfo"
MEAL_URL = "https://open.neis.go.kr/hub/mealServiceDietInfo"

KST = ZoneInfo("Asia/Seoul")


# --------------------------------------------------
# NEIS API 공통 함수
# --------------------------------------------------

def request_neis(url, params):
    """NEIS API를 호출하고 JSON을 반환한다."""
    try:
        response = requests.get(
            url,
            params=params,
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

    except requests.RequestException:
        return None

    except ValueError:
        return None


def get_result_code(data, service_name):
    """NEIS 응답에서 RESULT CODE를 찾는다."""
    service = data.get(service_name, [])

    for box in service:
        if not isinstance(box, dict):
            continue

        if "head" not in box:
            continue

        for head in box["head"]:
            result = head.get("RESULT")

            if result:
                return result.get("CODE")

    return None


def get_rows(data, service_name):
    """NEIS 응답에서 row 목록을 가져온다."""
    service = data.get(service_name, [])

    for box in service:
        if isinstance(box, dict) and "row" in box:
            return box["row"]

    return []


# --------------------------------------------------
# 학교 검색
# --------------------------------------------------

def search_schools(keyword):
    """학교 이름 일부를 이용해 학교를 검색한다."""

    data = request_neis(
        SCHOOL_INFO_URL,
        {
            "Type": "json",
            "SCHUL_NM": keyword,
        },
    )

    if data is None:
        return None, "학교 정보를 불러오지 못했습니다."

    result_code = get_result_code(data, "schoolInfo")

    if result_code == "INFO-200":
        return [], None

    if result_code and result_code != "INFO-000":
        return None, (
            "학교 정보를 불러오는 중 오류가 발생했습니다. "
            f"({result_code})"
        )

    return get_rows(data, "schoolInfo"), None


def expand_school_name(keyword):
    """
    축약 학교명을 정식 학교급 표현으로 바꾼다.

    예:
    수도여고 -> 수도여자고등학교
    서울고 -> 서울고등학교
    """

    expanded = keyword

    # '여고'를 먼저 처리한다.
    expanded = expanded.replace(
        "여고",
        "여자고등학교",
    )

    # 이미 '고등학교'가 붙어 있지 않은 경우
    # 남아 있는 '고'를 '고등학교'로 바꾼다.
    if "고등학교" not in expanded:
        expanded = expanded.replace(
            "고",
            "고등학교",
        )

    return expanded


def search_schools_with_fallback(keyword):
    """
    일반 검색 → 결과가 없으면 축약 학교명 확장 후 재검색.
    """

    schools, error = search_schools(keyword)

    if error:
        return None, error, None

    # 첫 번째 검색에서 찾았다면 그대로 사용
    if schools:
        return schools, None, None

    expanded = expand_school_name(keyword)

    # 검색어가 실제로 변경된 경우에만 재검색
    if expanded != keyword:
        schools, error = search_schools(expanded)

        if error:
            return None, error, expanded

        return schools, None, expanded

    return [], None, None


# --------------------------------------------------
# 급식 조회
# --------------------------------------------------

def search_meal(school, selected_date):
    """선택한 학교의 선택 날짜 중식을 조회한다."""

    date_string = selected_date.strftime("%Y%m%d")

    params = {
        "Type": "json",
        "ATPT_OFCDC_SC_CODE": school["ATPT_OFCDC_SC_CODE"],
        "SD_SCHUL_CODE": school["SD_SCHUL_CODE"],
        "MMEAL_SC_CODE": "2",
        "MLSV_FROM_YMD": date_string,
        "MLSV_TO_YMD": date_string,
        "pSize": 1000,
        "pIndex": 1,
    }

    data = request_neis(
        MEAL_URL,
        params,
    )

    if data is None:
        return None, "급식 정보를 불러오지 못했습니다."

    result_code = get_result_code(
        data,
        "mealServiceDietInfo",
    )

    # 해당 날짜에 급식 데이터가 없는 경우
    if result_code == "INFO-200":
        return [], None

    # 인증 오류 등 다른 오류
    if result_code and result_code != "INFO-000":
        return None, (
            "급식 정보를 불러오는 중 오류가 발생했습니다. "
            f"({result_code})"
        )

    return get_rows(
        data,
        "mealServiceDietInfo",
    ), None


# --------------------------------------------------
# 메뉴 표시
# --------------------------------------------------

def format_menu(menu):
    """NEIS의 <br/> 메뉴를 줄바꿈으로 변환한다."""

    if not menu:
        return ""

    menu = menu.replace(
        "<br/>",
        "\n",
    ).replace(
        "<br>",
        "\n",
    )

    # 혹시 남아 있는 HTML 태그 제거
    menu = re.sub(
        r"<[^>]+>",
        "",
        menu,
    )

    return menu.strip()


# --------------------------------------------------
# 화면
# --------------------------------------------------

def main():

    st.title(
        "학교별로 급식 칼로리는 얼마나 차이가 날까?"
    )

    st.write(
        "학교를 선택하고 날짜를 고르면 "
        "그날의 중식 메뉴와 칼로리를 확인할 수 있습니다."
    )

    st.divider()

    # --------------------------------------------------
    # 학교 검색
    # --------------------------------------------------

    school_keyword = st.text_input(
        "학교 이름",
        placeholder="예: 수도여고",
    ).strip()

    if "schools" not in st.session_state:
        st.session_state.schools = []

    if "school_message" not in st.session_state:
        st.session_state.school_message = ""

    if st.button(
        "학교 찾기",
        type="primary",
    ):
        if not school_keyword:
            st.session_state.schools = []
            st.session_state.school_message = (
                "학교 이름을 입력해 주세요."
            )

        else:
            schools, error, expanded = (
                search_schools_with_fallback(
                    school_keyword
                )
            )

            if error:
                st.session_state.schools = []
                st.session_state.school_message = error

            elif not schools:
                st.session_state.schools = []

                if expanded:
                    st.session_state.school_message = (
                        f"'{school_keyword}'으로 찾지 못해 "
                        f"'{expanded}'으로도 검색했지만 "
                        "학교를 찾지 못했습니다."
                    )
                else:
                    st.session_state.school_message = (
                        f"'{school_keyword}'에 해당하는 "
                        "학교를 찾지 못했습니다."
                    )

            else:
                st.session_state.schools = schools

                if expanded:
                    st.session_state.school_message = (
                        f"'{school_keyword}'으로 찾지 못해 "
                        f"'{expanded}'으로 다시 검색했습니다."
                    )
                else:
                    st.session_state.school_message = ""

    if st.session_state.school_message:
        st.info(
            st.session_state.school_message
        )

    schools = st.session_state.schools

    # --------------------------------------------------
    # 학교 선택
    # --------------------------------------------------

    if schools:

        school_options = []

        for school in schools:
            school_name = school.get(
                "SCHUL_NM",
                "",
            )

            region = school.get(
                "LCTN_SC_NM",
                "지역 정보 없음",
            )

            school_options.append(
                f"{school_name} — {region}"
            )

        selected_label = st.selectbox(
            "학교 선택",
            school_options,
        )

        selected_index = school_options.index(
            selected_label
        )

        selected_school = schools[selected_index]

        st.caption(
            f"선택한 학교: "
            f"{selected_school['SCHUL_NM']} "
            f"({selected_school.get('LCTN_SC_NM', '지역 정보 없음')})"
        )

        # --------------------------------------------------
        # 날짜 선택
        # --------------------------------------------------

        # 서버의 시간대와 관계없이 한국 날짜 사용
        today_kst = datetime.now(KST).date()

        selected_date = st.date_input(
            "급식 날짜",
            value=today_kst,
        )

        # --------------------------------------------------
        # 급식 조회
        # --------------------------------------------------

        if st.button(
            "중식 조회",
            type="primary",
        ):

            rows, error = search_meal(
                selected_school,
                selected_date,
            )

            if error:
                st.error(error)

            elif not rows:
                st.info(
                    f"{selected_date.strftime('%Y년 %-m월 %-d일')}"
                    "에는 등록된 중식 급식 정보가 없습니다."
                )

            else:
                meal = rows[0]

                menu = format_menu(
                    meal.get(
                        "DDISH_NM",
                        "",
                    )
                )

                calories = meal.get(
                    "CAL_INFO",
                    "",
                )

                st.divider()

                st.subheader(
                    f"{selected_date.strftime('%Y년 %-m월 %-d일')} 중식"
                )

                # --------------------------------------------------
                # 칼로리
                # --------------------------------------------------

                if calories:
                    st.metric(
                        "총 칼로리",
                        calories,
                    )

                # --------------------------------------------------
                # 메뉴
                # --------------------------------------------------

                if menu:
                    st.markdown("### 메뉴")

                    st.text(
                        menu
                    )

                else:
                    st.info(
                        "등록된 메뉴 정보가 없습니다."
                    )


if __name__ == "__main__":
    main()
