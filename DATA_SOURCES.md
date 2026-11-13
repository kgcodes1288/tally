# Data sources and licenses

Tally uses only public data. Raw files are not stored in this repository; the loaders in `data/` download or read them locally.

| Workspace | Source | What | License / terms |
|---|---|---|---|
| Federal Spending | [USAspending.gov](https://www.usaspending.gov/) account data download API | DATA Act Files A, B and C, fiscal year 2025, for NASA, Education, Energy, EPA, NSF and SBA | US Government work, public domain |
| Federal Spending | [USAspending glossary API](https://api.usaspending.gov/api/v2/references/glossary/) | 151 glossary terms for the knowledge base | US Government work, public domain |
| Online Retail | [Olist Brazilian E-Commerce](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) on Kaggle | About 100K anonymized orders, 2016 to 2018, nine tables | CC BY-NC-SA 4.0 (non-commercial, attribution to Olist) |
| City Operations | [NYC Open Data: 311 Service Requests](https://data.cityofnewyork.us/d/erm2-nwe9) | Requests created January to March 2025 | [NYC Open Data terms of use](https://opendata.cityofnewyork.us/overview/#termsofuse) |

Tally is a personal, non-commercial project. Knowledge-base playbooks in `kb/docs/` are original writing.

Local embedding model: [BAAI/bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5) (MIT), run with [fastembed](https://github.com/qdrant/fastembed).
