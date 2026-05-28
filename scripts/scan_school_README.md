# scan_school.py — Quick Reference

Converts every useful file in your school folder into readable markdown notes inside `education/`.

---

## Supported file types

| Type | Extensions |
|---|---|
| Documents | `.pdf` `.docx` `.doc` `.txt` `.md` |
| Slides | `.pptx` `.pptm` `.ppsx` `.ppt` |
| Spreadsheets | `.xlsx` `.xls` `.csv` |
| Images | `.png` `.jpg` `.jpeg` `.gif` `.webp` `.bmp` |
| Diagrams | `.drawio` (nodes, edges, labels extracted from XML) |
| Code / Data | `.py` `.js` `.html` `.json` `.xml` `.yaml` `.csv` |

### How images work
Images are sent to Claude Vision which describes what it sees — text, diagrams, charts, tables.
Requires `ANTHROPIC_API_KEY` set as an environment variable.

### How draw.io works
draw.io files are XML under the hood. The script extracts every shape label and connection arrow
so Claude can read your diagrams as structured text.

---

## First time setup (run once)

```
pip install pdfplumber python-docx python-pptx openpyxl anthropic Pillow
```

Set your API key (for image vision):
```
# Windows CMD
setx ANTHROPIC_API_KEY "your-key-here"

# Windows PowerShell
$env:ANTHROPIC_API_KEY = "your-key-here"

# macOS / Linux
export ANTHROPIC_API_KEY="your-key-here"
```

---

## How to run

**Scan everything (recommended first run):**
```
cd <your-vault-root>
python scripts/scan_school.py
```

**One subject only:**
```
python scripts/scan_school.py --subject "Database Management"
python scripts/scan_school.py --subject "Enterprise Systems"
```

**Skip image analysis (faster, no API calls):**
```
python scripts/scan_school.py --no-vision
```

---

## After running

Notes are saved to your vault's `education/` folder. If you use an AI assistant with
file access to your vault, say something like *"load my Database Management context"*
and it can read everything.

---

## Re-run anytime

The script skips files that haven't changed since last scan. Re-run whenever you add
new school files — it's fast on subsequent runs.
