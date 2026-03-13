# E2B Doc Template

Build a custom E2B template that includes the dependencies needed for
docx/pptx/pdf/xlsx generation and editing.

## Build

```bash
python build_template.py --alias cloudcanvasai-docs
```

Then set `E2B_TEMPLATE=cloudcanvasai-docs` in your backend `.env`.

## Notes

- This template includes LibreOffice, Pandoc, Poppler, and Node.js.
- For HTML-to-PPTX rendering, add Playwright + Chromium and Sharp to the template.
