import csv
import re
from io import BytesIO, StringIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter


def safe(value):
    text = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]", "", str(value))
    # Prevent formulas, including spreadsheet applications that trim leading space.
    return (
        "'" + text
        if text.lstrip().startswith(("=", "+", "-", "@"))
        or text.startswith(("\t", "\r", "\n"))
        else text
    )


def export(records, names, kind):
    columns = names + ["_source"]
    if kind == "csv":
        stream = StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow([safe(c) for c in columns])
        writer.writerows([safe(row.get(c, "")) for c in columns] for row in records)
        return b"\xef\xbb\xbf" + stream.getvalue().encode("utf-8")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Extracted data"
    sheet.append([safe(c) for c in columns])
    for row in records:
        sheet.append([safe(row.get(c, "")) for c in columns])
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="176B52")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for i, name in enumerate(columns, 1):
        sheet.column_dimensions[get_column_letter(i)].width = min(
            60, max(18, len(name) + 4)
        )
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
