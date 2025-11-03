import httpx
from typing import List, Dict

def pmid_to_pmcid(pmids: List[str]) -> Dict[str, str]:
    """
    批量获取 PMID 对应的 PMCID
    如果没有 PMCID，返回空字符串
    """
    result = {}
    # NCBI 一次最多允许查询 200 个 ID，如果超过需分批
    batch_size = 200
    for i in range(0, len(pmids), batch_size):
        batch_pmids = pmids[i:i+batch_size]
        ids_str = ",".join(batch_pmids)
        url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        params = {
            "db": "pubmed",
            "id": ids_str,
            "retmode": "json"
        }
        resp = httpx.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for pmid in batch_pmids:
            record = data.get("result", {}).get(pmid, {})
            # 有些文章可能没有 pmc
            pmcid = record.get("articleids", [])
            pmc = ""
            for item in pmcid:
                if item.get("idtype") == "pmc":
                    pmc = item.get("value")
                    break
            result[pmid] = pmc
    return result

# 示例
pmids = ["40903692", "36712345", "12345678"]
mapping = pmid_to_pmcid(pmids)
print(mapping)
