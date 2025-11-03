from metapub import FindIt


pmid = "40925376"

find_result = FindIt(pmid)

print(find_result.to_dict())

if find_result.url:
    print(FindIt(pmid).url)
