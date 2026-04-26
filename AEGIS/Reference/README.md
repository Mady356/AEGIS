# Reference/

The operator drops the source medical PDFs that back the AEGIS corpus into
this folder. Every chunk in `backend/corpus/chunks/*.md` carries a
`source_pdf:` field naming the exact filename below.

**On ingest, `backend/ingest.py` halts with an explicit error if any
referenced PDF is missing.** That is the load-bearing guarantee — no
chunk in the corpus can cite a file that is not actually present on disk.

## Required filenames

The V4 corpus references these PDFs. Place each one (the publicly
available current edition) into this folder with the exact filename:

| Filename                                | Source                                                     |
|-----------------------------------------|------------------------------------------------------------|
| `TCCC_Guidelines_2024.pdf`              | Tactical Combat Casualty Care Guidelines for Medical Personnel |
| `JTS_CPG_Tourniquet_Conversion.pdf`     | Joint Trauma System CPG — Tourniquet Conversion           |
| `AHA_CPR_ECC_Guidelines_2020.pdf`       | AHA Guidelines for CPR and ECC                            |
| `ILCOR_CoSTR_2023.pdf`                  | ILCOR International Consensus on CPR Science              |
| `WHO_Pocket_Book_Children_2013.pdf`     | WHO Pocket Book of Hospital Care for Children             |
| `WHO_IMAI_Guidelines_2014.pdf`          | WHO IMAI / IMCI Guidelines                                |

The download URLs are listed in each chunk's frontmatter `source_url:`
field. All sources are public.

## Citation resolution

When the operator clicks any citation pill in the cockpit:

1. The frontend calls `GET /api/retrieve/chunk/{citation_id}`
2. The chunk's `source_pdf` and `page` are read from frontmatter
3. The citation overlay's `VIEW SOURCE PDF` button opens
   `/api/source-pdf/{source_pdf}#page={page}` in a new tab
4. The browser's PDF viewer jumps to the cited page

The `/api/source-pdf/` endpoint validates the requested filename
against the whitelist of files referenced by the corpus before serving
— arbitrary file paths are rejected.
