import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import streamlit as st


NEIS_BASE_URL = "https://open.neis.go.kr/hub"
SCHOOL_INFO_URL = f"{NEIS_BASE_URL}/schoolInfo"
MEAL_URL = f"{NEIS_BASE_URL}/mealServiceDietInfo"
KST = ZoneInfo("Asia/Seoul")


def get_json(url, params):
    """NEIS API를 호출하고 JSON을 반환한다."""
    try:
        response = requests.get(url, params=params, timeout=10)
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
        if isinstance(box, dict) and "head" in box:
            for head in box["head"]:
                if "RESULT" in head:
                    return head["RESULT"].get("CODE")
    return None


def get_rows(data, service_name):
    """NEIS 응답의 row 목록을 가져온다."""
    service = data.get(service_name, [])

    for box in service:
        if isinstance(box, dict) and "row" in box:
            return box["row"]

    return []


def search_schools(name):
    """학교 이름 일부로 학교를 검색한다."""
    data = get_json(
        SCHOOL_INFO_URL,
        {
            "Type": "json",
            "SCHUL_NM": name,
        },
    )

    if data is None:
        return None, "API 호출에 실패했습니다."

    code = get_result_code(data, "schoolInfo")

    if code == "INFO-200":
        return [], None

    if code and code != "INFO-000":
        return None, f"학교 정보 조회 중 오류가 발생했습니다. ({code})"

    return get_rows(data, "schoolInfo"), None


def expand_short_name(name):
    """
    축약형 학교명을 검색하기 위한 두 번째 검색어를 만든다.

    예:
    수도여고 -> 수도여자고등학교
    서울고 -> 서울고등학교
    """
    expanded = name

    # '여고'를 먼저 바꿔야 '고'가 다시 적용되지 않는다.
    expanded = expanded.replace("여고", "여자고등학교")

    # 이미 '고등학교'가 붙은 경우에는 다시 바꾸지 않는다.
    if not expanded.endswith("고등학교"):
        expanded = expanded.replace("고", "고등학교")

    return expanded


def search_schools_with_fallback(name):
    """원래 검색 후, 결과가 없으면 학교급 축약어를 풀어 재검색한다."""
    schools, error = search_schools(name)

    if error is not None:
        return None, error, None

    if schools:
        return schools, None, None

    expanded_name = expand_short_name(name)

    # 축약어가 실제로 변환된 경우에만 두 번째 검색
    if expanded_name != name:
        schools, error = search_schools(expanded_name)

        if error is not None:
            return None, error, expanded_name

        return schools, None, expanded_name

    return [], None, None


def search_meal(school, date):
    """선택한 학교의 해당 날짜 중식 정보를 조회한다."""
    date_str = date.strftime("%Y%m%d")

    data = get_json(
        MEAL_URL,
        {
            "Type": "json",
            "ATPT_OFCDC_SC_CODE": school["ATPT_OFCDC_SC_CODE"],
            "SD_SCHUL_CODE": school["SD_SCHUL_CODE"],
            "MMEAL_SC_CODE": "2",
            "MLSV_FROM_YMD": date_str,
            "MLSV_TO_YMD": date_str,
            "pSize": 1000,
            "pIndex": 1,
        },
    )

    if data is None:
        return None, "급식 정보를 불러오지 못했습니다."

    code = get_result_code(data, "mealServiceDietInfo")

    if code == "INFO-200":
        return [], None

    if code and code != "INFO-000":
        return None, f"급식 정보 조회 중 오류가 발생했습니다. ({code})"

    return get_rows(data, "mealServiceDietInfo"), None


def format_menu(menu):
    """<br/>로 구분된 메뉴를 보기 좋게 줄바꿈한다."""
    if not menu:
        return ""

    menu = menu.replace("<br/>", "\n").replace("<br>", "\n")

    # 혹시 HTML 태그가 남아 있다면 제거
    menu = re.sub(r"<[^>]+>", "", menu)

    return menu.strip()


def main():
    st.set_page_config(
        page_title="학교 급식 찾아보기",
        page_icon="🍚",
    )

    st.title("학교 급식 찾아보기")

    st.write("학교 이름을 입력하고 학교와 날짜를 선택하면 해당 날짜의 중식 메뉴를 확인할 수 있습니다.")

    school_name = st.text_input(
        "학교 이름",
        placeholder="예: 수도여고",
    ).strip()

    if "schools" not in st.session_state:
        st.session_state.schools = []

    if "search_message" not in st.session_state:
        st.session_state.search_message = ""

    if st.button("학교 찾기", type="primary"):
        if not school_name:
            st.session_state.schools = []
            st.session_state.search_message = "학교 이름을 입력해 주세요."
        else:
            schools, error, expanded_name = search_schools_with_fallback(school_name)

            if error:
                st.session_state.schools = []
                st.session_state.search_message = error
            elif not schools:
                st.session_state.schools = []

                if expanded_name:
                    st.session_state.search_message = (
                        f"'{school_name}'으로 찾지 못해 "
                        f"'{expanded_name}'으로도 검색했지만 학교를 찾지 못했습니다."
                    )
                else:
                    st.session_state.search_message = (
                        f"'{school_name}'에 해당하는 학교를 찾지 못했습니다."
                    )
            else:
                st.session_state.schools = schools

                if expanded_name:
                    st.session_state.search_message = (
                        f"'{school_name}'으로 찾지 못해 "
                        f"'{expanded_name}'으로 다시 검색했습니다."
                    )
                else:
                    st.session_state.search_message = ""

    if st.session_state.search_message:
        st.info(st.session_state.search_message)

    schools = st.session_state.schools

    if schools:
        # 무인증 API는 한 번에 최대 5건을 반환하므로
        # 반환된 학교를 모두 선택할 수 있도록 한다.
        school_options = [
            f"{school['SCHUL_NM']} — {school.get('LCTN_SC_NM', '지역 정보 없음')}"
            for school in schools
        ]

        selected_label = st.selectbox(
            "학교 선택",
            school_options,
        )

        selected_index = school_options.index(selected_label)
        selected_school = schools[selected_index]

        st.caption(
            f"선택한 학교: {selected_school['SCHUL_NM']} "
            f"({selected_school.get('LCTN_SC_NM', '지역 정보 없음')})"
        )

        # 배포 서버가 한국 시간이 아니더라도 한국의 오늘 날짜를 사용한다.
        today_kst = datetime.now(KST).date()

        selected_date = st.date_input(
            "급식 날짜",
            value=today_kst,
        )

        if st.button("중식 조회", type="primary"):
            rows, error = search_meal(selected_school, selected_date)

            if error:
                st.error(error)
            elif not rows:
                st.info(
                    f"{selected_date.strftime('%Y년 %-m월 %-d일')}에는 "
                    "등록된 중식 급식 정보가 없습니다."
                )
            else:
                # 날짜를 하루로 제한했으므로 일반적으로 한 행이다.
                meal = rows[0]

                st.subheader(
                    f"{selected_date.strftime('%Y년 %-m월 %-d일')} 중식"
                )

                menu = format_menu(meal.get("DDISH_NM", ""))
                calories = meal.get("CAL_INFO", "")

                if menu:
                    st.markdown("### 메뉴")
                    st.text(menu)
                else:
                    st.info("등록된 메뉴 정보가 없습니다.")

                if calories:
                    st.markdown("### 칼로리")
                    st.write(calories)


if __name__ == "__main__":
    main()
