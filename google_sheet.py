"""Write a WeekGrid to its own "Week N" tab: colours, merged team cells, frozen headers, cell notes.
Also the "Who's In" tab: live formulas over the form responses showing who has submitted this week.

Tabs are rebuilt from scratch each time (same tab ID, so links to them keep working).
Google's "Form Responses" tab is only ever read.
"""

from datetime import datetime
from itertools import groupby
from typing import Optional

import grid as g

STATE_COLORS = {  # background, text
    g.OPEN: ("#ffffff", "#000000"),
    g.LOCKED: ("#b7b7b7", "#666666"),
    g.USED: ("#d9d9d9", "#666666"),
    g.TAKEN: ("#eeeeee", "#999999"),
    g.NO_GAME: ("#d9d9d9", "#999999"),
    g.PENDING: ("#fff2cc", "#000000"),
    g.WIN: ("#b7e1cd", "#000000"),
    g.LOSS: ("#f4c7c3", "#000000"),
    g.VOID: ("#e0e0e0", "#000000"),
    g.DROPPED: ("#fce5cd", "#b45f06"),
}
HEADER_BG = "#434343"
TEAM_WIDTH, GAME_WIDTH, MEMBER_WIDTH, VIDEO_WIDTH = 150, 190, 72, 110


def rgb(hex_color: str) -> dict:
    h = hex_color.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}


def _cell(value: str, bg: str = "#ffffff", fg: str = "#000000", bold: bool = False, center: bool = False,
          note: str = "", top_border: bool = False, italic: bool = False, link: str = "") -> dict:
    fmt = {"backgroundColor": rgb(bg), "verticalAlignment": "MIDDLE",
           "textFormat": {"foregroundColor": rgb(fg), "bold": bold, "italic": italic}}
    if center:
        fmt["horizontalAlignment"] = "CENTER"
    if top_border:
        fmt["borders"] = {"top": {"style": "SOLID_MEDIUM", "color": rgb("#666666")}}
    if link:
        fmt["textFormat"]["link"] = {"uri": link}
    cell = {"userEnteredValue": {"stringValue": value}, "userEnteredFormat": fmt}
    if note:
        cell["note"] = note
    return cell


def grid_rows(week_grid: g.WeekGrid) -> list:
    """RowData for the whole tab: header, one row per team-in-game, then the summary rows."""
    header = [_cell(f"{week_grid.title}", HEADER_BG, "#ffffff", bold=True, note=week_grid.subtitle),
              _cell(week_grid.subtitle, HEADER_BG, "#ffffff", italic=True)]
    header += [_cell(m, HEADER_BG, "#ffffff", bold=True, center=True) for m in week_grid.members]
    header.append(_cell("Highlights", HEADER_BG, "#ffffff", bold=True, center=True))
    rows = [{"values": header}]
    previous = None
    for row in week_grid.rows:
        first = row.team != previous
        previous = row.team
        values = [_cell(g.team_name(row.team) if first else "", bold=True, top_border=first),
                  _cell(row.game_text, *(STATE_COLORS[g.LOCKED] if any(c.state == g.LOCKED for c in row.cells)
                                         else ("#ffffff", "#000000")), top_border=first)]
        values += [_cell(c.text, *STATE_COLORS[c.state], center=True, note=c.note, top_border=first)
                   for c in row.cells]
        video = row.game.highlights if row.game and row.game.status == g.FINAL else ""
        values.append(_cell("▶ Highlights" if video else "", fg="#1155cc", center=True, link=video,
                            top_border=first))
        rows.append({"values": values})
    if week_grid.summary:
        rows.append({"values": []})
        for i, (label, cells) in enumerate(week_grid.summary):
            rows.append({"values": [_cell("", top_border=i == 0), _cell(label, bold=True, top_border=i == 0)]
                         + [_cell(v, bold=True, center=True, top_border=i == 0) for v in cells]})
    return rows


def merge_ranges(week_grid: g.WeekGrid, sheet_id: int) -> list:
    """Team-name cells merged down across that team's game rows."""
    merges, row_index = [], 1  # row 0 is the header
    for _, block in groupby(week_grid.rows, key=lambda r: r.team):
        size = len(list(block))
        if size > 1:
            merges.append({"sheetId": sheet_id, "startRowIndex": row_index, "endRowIndex": row_index + size,
                           "startColumnIndex": 0, "endColumnIndex": 1})
        row_index += size
    return merges


def tab_requests(week_grid: g.WeekGrid, sheet_id: int) -> list:
    rows = grid_rows(week_grid)
    columns = 2 + len(week_grid.members) + 1
    widths = [TEAM_WIDTH, GAME_WIDTH] + [MEMBER_WIDTH] * len(week_grid.members) + [VIDEO_WIDTH]
    hidden = [False, False] + [m in week_grid.idle for m in week_grid.members] + [False]
    requests = [
        {"unmergeCells": {"range": {"sheetId": sheet_id}}},
        {"updateCells": {"range": {"sheetId": sheet_id}, "fields": "*"}},  # clear values, formats and notes
        {"updateSheetProperties": {"properties": {"sheetId": sheet_id, "index": 0, "gridProperties": {
            "rowCount": len(rows), "columnCount": columns, "frozenRowCount": 1, "frozenColumnCount": 2}},
            "fields": "index,gridProperties(rowCount,columnCount,frozenRowCount,frozenColumnCount)"}},
        {"updateCells": {"start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 0}, "rows": rows,
                         "fields": "userEnteredValue,userEnteredFormat,note"}},
    ]
    requests += [{"mergeCells": {"range": r, "mergeType": "MERGE_ALL"}} for r in merge_ranges(week_grid, sheet_id)]
    requests += [{"updateDimensionProperties": {
        "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
        "properties": {"pixelSize": w, "hiddenByUser": h}, "fields": "pixelSize,hiddenByUser"}}
        for i, (w, h) in enumerate(zip(widths, hidden))]  # members who've never picked stay hidden until they do
    return requests


def responses_tab(sheets, spreadsheet_id: str) -> str:
    """Title of the tab Google writes form responses to ("Form Responses 1")."""
    meta = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets.properties.title").execute()
    titles = [s["properties"]["title"] for s in meta["sheets"]]
    tab = next((t for t in titles if t.startswith("Form Responses")), None)
    if tab is None:
        raise ValueError(f"no 'Form Responses' tab in the Sheet (tabs: {titles}); is the form linked?")
    return tab


def read_form_responses(sheets, spreadsheet_id: str) -> tuple:
    """(headers, rows) from the form responses tab."""
    tab = responses_tab(sheets, spreadsheet_id)
    values = sheets.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=f"'{tab}'").execute()
    rows = values.get("values", [])
    return (rows[0], rows[1:]) if rows else ([], [])


def week_tabs(sheets, spreadsheet_id: str) -> list:
    """Week numbers that already have a "Week N" tab."""
    meta = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets.properties.title").execute()
    return sorted(int(t[5:]) for t in (s["properties"]["title"] for s in meta["sheets"])
                  if t.startswith("Week ") and t[5:].isdigit())


def arrange_tabs(sheets, spreadsheet_id: str, order: list, hidden: list) -> None:
    """Show the "Week N" tabs in `order` (first = front) and hide those in `hidden`; other tabs go after."""
    meta = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets.properties").execute()
    ids = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}
    requests = [{"updateSheetProperties": {"properties": {"sheetId": ids[f"Week {w}"], "index": i, "hidden": False},
                                           "fields": "index,hidden"}} for i, w in enumerate(order)]
    requests += [{"updateSheetProperties": {"properties": {"sheetId": ids[f"Week {w}"], "hidden": True},
                                            "fields": "hidden"}} for w in hidden if f"Week {w}" in ids]
    sheets.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()


def write_week_tab(sheets, spreadsheet_id: str, week_grid: g.WeekGrid) -> str:
    """Create or rebuild the grid's tab; returns a link straight to it."""
    meta = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets.properties").execute()
    tabs = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}
    sheet_id = tabs.get(week_grid.title)
    if sheet_id is None:
        reply = sheets.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": [
            {"addSheet": {"properties": {"title": week_grid.title, "index": 0}}}]}).execute()
        sheet_id = reply["replies"][0]["addSheet"]["properties"]["sheetId"]
    sheets.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id,
                                      body={"requests": tab_requests(week_grid, sheet_id)}).execute()
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid={sheet_id}"


STATUS_TAB = "Who's In"
IN, LATE, MISSING = "✅ In", "⚠️ Late", "—"


def _column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def status_rows(tab: str, headers: list, week: int, members: list, deadline: Optional[datetime],
                subtitle: str) -> list:
    """RowData for the "Who's In" tab. Each member's status is a formula over the responses tab, so it updates
    the moment a form comes in. Only who and when shows, never the picks. `deadline` (naive, in the Sheet's
    time zone) marks later responses as late; None for special weeks, which lock game by game."""
    def col(keyword: str) -> str:
        i = next((i for i, h in enumerate(headers) if keyword in h.lower()), None)
        if i is None:
            raise ValueError(f"no column containing {keyword!r} in {headers}")
        letter = _column_letter(i)
        return "'{}'!${}:${}".format(tab.replace("'", "''"), letter, letter)

    ts, name, wk = col("timestamp"), col("name"), col("week")
    rows = [{"values": [_cell(f"Week {week}: who's in", HEADER_BG, "#ffffff", bold=True),
                        _cell(subtitle, HEADER_BG, "#ffffff", italic=True), _cell("", HEADER_BG)]},
            {"values": [_cell(h, "#d9d9d9", bold=True) for h in ("Name", "Status", "Last submitted")]}]
    for r, member in enumerate(members, start=3):
        mine = f'{name},$A{r},{wk},"Week {week}"'
        if deadline is None:
            status = f'=IF(COUNTIFS({mine})>0,"{IN}","{MISSING}")'
        else:
            lock = f"DATE({deadline:%Y},{deadline.month},{deadline.day})+TIME({deadline.hour},{deadline.minute},0)"
            status = (f'=IF(COUNTIFS({mine},{ts},"<="&{lock})>0,"{IN}",'
                      f'IF(COUNTIFS({mine})>0,"{LATE}","{MISSING}"))')
        last = f'=IF(COUNTIFS({mine})=0,"",MAXIFS({ts},{mine}))'
        rows.append({"values": [
            _cell(member, bold=True),
            {"userEnteredValue": {"formulaValue": status},
             "userEnteredFormat": {"horizontalAlignment": "CENTER"}},
            {"userEnteredValue": {"formulaValue": last}, "userEnteredFormat": {
                "numberFormat": {"type": "DATE_TIME", "pattern": "ddd m/d h:mm am/pm"}}}]})
    end = 2 + len(members)
    rows.append({"values": []})
    rows.append({"values": [_cell(""), {"userEnteredValue": {
        "formulaValue": f'=COUNTIF(B3:B{end},"{IN}")&" of {len(members)} in"'},
        "userEnteredFormat": {"horizontalAlignment": "CENTER", "textFormat": {"bold": True}}}]})
    return rows


def write_status_tab(sheets, spreadsheet_id: str, week: int, members: list, deadline: Optional[datetime],
                     subtitle: str, index: int = 1) -> str:
    """Create or rebuild the "Who's In" tab for `week` at position `index`; returns a link straight to it."""
    tab = responses_tab(sheets, spreadsheet_id)
    header = sheets.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=f"'{tab}'!1:1").execute()
    rows = status_rows(tab, (header.get("values") or [[]])[0], week, members, deadline, subtitle)
    meta = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets.properties").execute()
    sheet_id = next((s["properties"]["sheetId"] for s in meta["sheets"]
                     if s["properties"]["title"] == STATUS_TAB), None)
    if sheet_id is None:
        reply = sheets.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": [
            {"addSheet": {"properties": {"title": STATUS_TAB}}}]}).execute()
        sheet_id = reply["replies"][0]["addSheet"]["properties"]["sheetId"]
    requests = [
        {"updateCells": {"range": {"sheetId": sheet_id}, "fields": "*"}},
        {"updateSheetProperties": {"properties": {"sheetId": sheet_id, "index": index, "hidden": False,
                                                  "gridProperties": {"rowCount": len(rows), "columnCount": 3,
                                                                     "frozenRowCount": 2}},
                                   "fields": "index,hidden,gridProperties(rowCount,columnCount,frozenRowCount)"}},
        {"updateCells": {"start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 0}, "rows": rows,
                         "fields": "userEnteredValue,userEnteredFormat"}},
    ]
    requests += [{"updateDimensionProperties": {
        "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
        "properties": {"pixelSize": w}, "fields": "pixelSize"}} for i, w in enumerate((TEAM_WIDTH, 110, 170))]
    sheets.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid={sheet_id}"
