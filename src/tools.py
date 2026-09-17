"""해외여행플래너 도메인 도구: 국가 추천, 계절 정보, 장소 검증, 동선 최적화, 예산 시뮬레이션."""

import math
import os

import requests

from country_data import find_country, load_countries, load_places, maps_url, resolve_slug, MONTH_NAMES

from langchain_core.tools import tool

GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")


def _purpose_list(purpose: str) -> list[str]:
    """쉼표나 공백으로 구분된 목적 문자열을 목적 단어 리스트로 나눈다."""
    return [p.strip() for p in purpose.replace(",", " ").split() if p.strip()]


def _format_country_line(country: dict, score: float, total_cost: int) -> str:
    """국가 스코어링 결과 한 줄(국가명·매칭 점수·예상 비용·추천 사유)을 만든다."""
    reason = country["notes"].split(".")[0] + "."
    return (
        f"- {country['country']} · {country['city']} (slug: {country['slug']}) "
        f"매칭 {round(score * 100)}% · 예상 총비용 약 {total_cost:,}원\n"
        f"  이유: {reason}"
    )


@tool
def score_countries(
    budget_krw: int,
    purpose: str,
    companions: str,
    days: int = 4,
    month: int = 0,
    preferred_country: str = "",
) -> str:
    """예산·동반인·여행 목적 조건으로 국가를 1차 필터링하고 스코어링해 상위 후보를 추천한다.
    budget_krw는 1인 총 여행 예산(원), purpose는 "휴양,미식"처럼 쉼표나 공백으로 구분한 목적,
    companions는 "성인 2 아동 1(6세)"처럼 동반인 구성을 적은 자유 텍스트다.
    month은 1~12 여행 예정 월(모르면 0), preferred_country는 사용자가 직접 지정한 국가명(없으면 빈 문자열)이다.
    예산 조건에 맞는 국가가 하나도 없으면 그 사실만 안내하고 지어내지 않는다.
    """
    requested_purposes = _purpose_list(purpose)
    has_child = any(k in companions for k in ["아동", "미취학", "영유아", "아기", "유아"])

    candidates = []
    for country in load_countries():
        if preferred_country and preferred_country not in (country["country"], country["city"]):
            continue
        total_cost = country["avg_daily_cost_krw"] * days
        if total_cost > budget_krw:
            continue

        if requested_purposes:
            matched = sum(1 for p in requested_purposes if p in country["purposes"])
            purpose_score = matched / len(requested_purposes)
        else:
            purpose_score = 0.5

        companion_score = country["safety_level"] / 5 if has_child else 0.6
        score = purpose_score * 0.6 + companion_score * 0.4
        candidates.append((score, country, total_cost))

    if not candidates:
        return (
            f"예산 {budget_krw:,}원({days}일 기준)으로 조건에 맞는 국가를 찾지 못했습니다. "
            "예산을 늘리거나 여행 기간을 줄여서 다시 요청해 주세요."
        )

    candidates.sort(key=lambda c: c[0], reverse=True)
    top = candidates[:5]

    lines = [_format_country_line(country, score, total_cost) for score, country, total_cost in top]
    result = "\n".join(lines)

    if month:
        climate_notes = []
        for _, country, _ in top:
            verdict = country["climate"][month - 1]
            verdict_kr = "건기" if verdict == "dry" else "우기"
            climate_notes.append(f"  {country['country']}: {MONTH_NAMES[month - 1]} 기준 {verdict_kr}")
        result += "\n\n[계절 참고]\n" + "\n".join(climate_notes)

    return result


@tool
def get_climate_info(slug: str, month: int) -> str:
    """국가/도시 이름이나 slug와 여행 예정 월(1~12)로 그 시기가 건기인지 우기인지 판정 근거와 함께 안내한다.
    "베트남", "다낭"처럼 자연어 이름을 넘겨도 되고, 등록되지 않은 국가면 정보가 없다고 안내한다.
    """
    slug = resolve_slug(slug) or slug
    country = find_country(slug)
    if country is None:
        return f"'{slug}'는 등록된 국가 데이터가 없어 계절 정보를 확인할 수 없습니다."
    if not 1 <= month <= 12:
        return "month는 1에서 12 사이여야 합니다."

    verdict = country["climate"][month - 1]
    if verdict == "dry":
        return f"{country['country']} {country['city']}의 {MONTH_NAMES[month - 1]}은 건기로, 맑은 날이 많아 여행하기 좋은 시기입니다."
    return (
        f"{country['country']} {country['city']}의 {MONTH_NAMES[month - 1]}은 우기로, 비 소식이 잦을 수 있습니다. "
        f"참고: {country['notes']}"
    )


@tool
def list_candidate_places(slug: str, category: str = "") -> str:
    """국가/도시 이름이나 slug에 해당하는, 실제 검증된(장소 확인됨) 후보 장소 목록을 조회한다.
    "태국 방콕"처럼 자연어 이름을 넘겨도 되고, category를 주면 '해변', '식당', '관광지', '액티비티', '쇼핑' 중 하나로 필터링한다.
    코스를 짤 때는 이 도구가 돌려주는 장소만 사용하고, 목록에 없는 장소를 지어내지 않는다.
    데이터가 없으면 없다고 안내한다.
    """
    slug = resolve_slug(slug) or slug
    country = find_country(slug)
    places = load_places(slug)
    if not places:
        return f"'{slug}'는 등록된 장소 데이터가 없습니다."
    if category:
        places = [p for p in places if p["category"] == category]
        if not places:
            return f"'{slug}'에는 '{category}' 카테고리로 등록된 장소가 없습니다."

    default_city = country["city"] if country else slug
    lines = []
    for p in places:
        badges = []
        if p.get("kid_friendly"):
            badges.append("유모차 가능" if p.get("stroller_ok") else "키즈존 있음")
        if p.get("kids_menu"):
            badges.append("키즈메뉴 있음")
        badge_text = f" [{', '.join(badges)}]" if badges else ""
        place_city = p.get("city", default_city)
        lines.append(
            f"- {p['name']} ({place_city} · {p['category']}) · 평점 {p['rating']} ({p['review_count']:,}건){badge_text}\n"
            f"  구글맵: {maps_url(p['name'], place_city)}"
        )
    return "\n".join(lines)


@tool
def verify_place(slug: str, name: str) -> str:
    """장소 이름을 실제 데이터로 검증한다. slug 자리에는 국가/도시 이름을 그대로 넘겨도 된다.
    GOOGLE_MAPS_API_KEY가 설정돼 있으면 구글 플레이스 텍스트 검색을 사용하고,
    없으면 로컬로 큐레이션된 검증 데이터에서 조회한다. 두 경우 모두에서 찾지 못하면 확인되지 않았다고 안내하며,
    좌표나 평점을 지어내지 않는다.
    """
    slug = resolve_slug(slug) or slug
    country = find_country(slug)
    city = country["city"] if country else slug

    if GOOGLE_MAPS_API_KEY:
        try:
            resp = requests.get(
                "https://maps.googleapis.com/maps/api/place/textsearch/json",
                params={"query": f"{name} {city}", "key": GOOGLE_MAPS_API_KEY},
                timeout=5,
            )
            data = resp.json()
            if data.get("results"):
                place = data["results"][0]
                rating = place.get("rating", "정보 없음")
                review_count = place.get("user_ratings_total", 0)
                return (
                    f"{place.get('name', name)} · 평점 {rating} ({review_count:,}건)\n"
                    f"구글맵: {maps_url(place.get('name', name), city)}"
                )
        except requests.RequestException:
            pass  # 실패하면 아래 로컬 데이터로 폴백

    for p in load_places(slug):
        if name in p["name"] or p["name"] in name:
            return (
                f"{p['name']} ({p.get('city', city)} · {p['category']}) · 평점 {p['rating']} ({p['review_count']:,}건)\n"
                f"구글맵: {maps_url(p['name'], p.get('city', city))}"
            )

    return f"'{name}'은(는) 확인되지 않은 장소입니다. 후보 목록(list_candidate_places)에서 확인된 장소를 사용해 주세요."


def _haversine_km(a: dict, b: dict) -> float:
    """위도·경도로 두 지점 사이의 실제 거리(km)를 하버사인 공식으로 계산한다."""
    r = 6371.0
    lat1, lng1, lat2, lng2 = map(math.radians, [a["lat"], a["lng"], b["lat"], b["lng"]])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


@tool
def optimize_route(slug: str, place_names: list[str]) -> str:
    """하루에 방문할 장소 이름 목록을 받아, 이동 거리가 최소가 되도록 방문 순서를 재배열한다.
    slug 자리에는 국가/도시 이름을 그대로 넘겨도 된다.
    첫 번째로 준 장소를 출발점으로 삼아 가장 가까운 미방문 장소를 그리디하게 이어붙이는 방식이다.
    목록에 없는 장소 이름은 건너뛴다.
    """
    slug = resolve_slug(slug) or slug
    all_places = {p["name"]: p for p in load_places(slug)}
    route = [all_places[n] for n in place_names if n in all_places]
    missing = [n for n in place_names if n not in all_places]
    if len(route) < 2:
        return "동선을 계산하려면 등록된 장소가 2곳 이상 필요합니다." + (
            f" (확인 안 된 장소: {', '.join(missing)})" if missing else ""
        )

    ordered = [route[0]]
    remaining = route[1:]
    while remaining:
        last = ordered[-1]
        nearest = min(remaining, key=lambda p: _haversine_km(last, p))
        ordered.append(nearest)
        remaining.remove(nearest)

    segments = []
    total_km = 0.0
    for i in range(len(ordered) - 1):
        d = _haversine_km(ordered[i], ordered[i + 1])
        total_km += d
        segments.append(f"{ordered[i]['name']} → {ordered[i + 1]['name']} ({d:.1f}km)")

    result = f"최적 방문 순서: {' → '.join(p['name'] for p in ordered)}\n"
    result += "\n".join(segments)
    result += f"\n총 이동 거리: {total_km:.1f}km"
    if missing:
        result += f"\n(확인 안 된 장소라 제외됨: {', '.join(missing)})"
    return result


@tool
def estimate_budget(slug: str, days: int, companions_count: int = 1) -> str:
    """국가/도시 이름이나 slug·일정·인원수로 숙소/교통/식비/액티비티 항목별 예상 예산을 추정한다.
    실시간 가격이 아니라 평균값 기반 추정치임을 함께 안내한다.
    """
    slug = resolve_slug(slug) or slug
    country = find_country(slug)
    if country is None:
        return f"'{slug}'는 등록된 국가 데이터가 없어 예산을 추정할 수 없습니다."

    total = country["avg_daily_cost_krw"] * days * max(companions_count, 1)
    breakdown = {
        "숙소": round(total * 0.40),
        "교통": round(total * 0.15),
        "식비": round(total * 0.25),
        "액티비티": round(total * 0.20),
    }
    lines = [f"- {k}: 약 {v:,}원" for k, v in breakdown.items()]
    return (
        f"{country['country']} {country['city']} {days}일 · {companions_count}인 예상 총비용: 약 {total:,}원\n"
        + "\n".join(lines)
        + "\n(평균값 기반 추정치이며 실시간 가격이 아닙니다)"
    )
