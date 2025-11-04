import aiohttp
import asyncio
from typing import List, Optional, Literal, Tuple, Dict

BASE_URL = "https://clinicaltrials.gov/api/v2/studies"


async def async_search_trials(
        keywords: List[str],
        logic: Literal["AND", "OR", "NOT"] = "AND",
        status: Optional[str] = None,
        size: int = 10,
        page_token: Optional[str] = None
) -> Tuple[List[Dict], Optional[str]]:
    """
    使用 aiohttp 异步搜索 ClinicalTrials.gov 临床试验

    :param keywords: 关键词列表，例如 ["cancer", "diabetes"]
    :param logic: 关键词逻辑 ("AND" | "OR" | "NOT")
    :param status: 研究状态筛选，如 "RECRUITING"
    :param size: 每页返回的条数
    :param page_token: 翻页标识
    :return: (结果列表, 下一页标识)
    """
    query = f" {logic} ".join(keywords)
    params = {"query.term": query, "pageSize": size}
    if status:
        params["filter.overallStatus"] = status
    if page_token:
        params["pageToken"] = page_token

    async with aiohttp.ClientSession() as session:
        async with session.get(BASE_URL, params=params, timeout=30) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"HTTP {resp.status}: {text[:300]}")
            data = await resp.json()

    results = []
    for study in data.get("studies", []):
        section = study.get("protocolSection", {})

        # 模块信息
        id_mod = section.get("identificationModule", {})
        status_mod = section.get("statusModule", {})
        design_mod = section.get("designModule", {})
        cond_mod = section.get("conditionsModule", {})
        sponsor_mod = section.get("sponsorCollaboratorsModule", {})
        location_mod = section.get("contactsLocationsModule", {})

        # designInfo 内的 allocation/intervention_model
        design_info = design_mod.get("designInfo", {})

        results.append({
            # === 基本信息 ===
            "nct_id": id_mod.get("nctId"),
            "title": id_mod.get("briefTitle"),
            "official_title": id_mod.get("officialTitle"),

            # === 状态信息 ===
            "status": status_mod.get("overallStatus"),
            "start_date": status_mod.get("startDateStruct", {}).get("date"),
            "completion_date": status_mod.get("completionDateStruct", {}).get("date"),

            # === 研究设计 ===
            "study_type": design_mod.get("studyType"),
            "phase": ", ".join(design_mod.get("phases", []) or []),
            "allocation": design_info.get("allocation"),             # 修正路径
            "intervention_model": design_info.get("interventionModel"),  # 修正路径

            # === 疾病/条件 ===
            "conditions": ", ".join(cond_mod.get("conditions", []) or []),

            # === 赞助方信息 ===
            "sponsor": sponsor_mod.get("leadSponsor", {}).get("name"),  # 修正路径

            # === 地点 ===
            "locations": ", ".join(
                [f"{loc.get('city', '')}, {loc.get('country', '')}"
                 for loc in location_mod.get("locations", [])]
            ),

            # === 来源链接 ===
            "source_url": f"https://clinicaltrials.gov/study/{id_mod.get('nctId')}",
        })

    return results, data.get("nextPageToken")


# -------------------------
# 调用示例
# -------------------------
if __name__ == "__main__":
    async def main():
        results, next_token = await async_search_trials(
            ["lung", "cancer"], size=5, status="RECRUITING"
        )
        for r in results:
            print(r)

    asyncio.run(main())
