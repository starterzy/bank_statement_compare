"""读取层：任意表格文件 → 原始网格（不猜表头、不抽账号）。"""
import pandas as pd

from app.parsing.excel_reader import read_grid, read_table

BOM = "﻿"

CSV_TEXT = (
    "查询账号[ Inquirer account number ],\"376674731895\t\",,,,,,,,,,,,,,,,,\r\n"
    "总笔数[ Total number ],52,,,,,,,,,,,,,,,,,\r\n"
    "交易类型[ Transaction Type ],付款人账号[ Debit Account No. ],"
    "收款人账号[ Payee's Account Number ],交易日期[ Transaction Date ],"
    "交易金额[ Trade Amount ],交易后余额[ After-transaction balance ]\r\n"
    "来账,\"4900004008\t\",\"376674731895\t\",\"20250102\t\",\"10,457.04\",\"2,855,707.29\"\r\n"
    "往账,\"376674731895\t\",\"07549\t\",\"20250113\t\",-11,\"2,874,351.90\"\r\n"
)


def test_read_grid_csv_utf8_bom_keeps_rows_and_strips_cells(tmp_path):
    p = tmp_path / "bank.csv"
    p.write_bytes((BOM + CSV_TEXT).encode("utf-8"))

    rows = read_grid(str(p))

    assert len(rows) == 5
    assert rows[0][0] == "查询账号[ Inquirer account number ]"
    assert rows[0][1] == "376674731895"      # 银行导出常见制表符后缀，读取时去掉
    assert rows[3][4] == "10,457.04"          # 带千分位的金额原样保留


def test_read_grid_csv_gb18030(tmp_path):
    p = tmp_path / "bank.csv"
    p.write_bytes(CSV_TEXT.encode("gb18030"))

    rows = read_grid(str(p))

    assert rows[0][0] == "查询账号[ Inquirer account number ]"
    assert rows[4][5] == "2,874,351.90"


def test_read_grid_csv_semicolon_and_tab_delimiters(tmp_path):
    semi = tmp_path / "semi.csv"
    semi.write_bytes("日期;金额\n20250102;100.00\n".encode("utf-8"))
    assert read_grid(str(semi))[1] == ["20250102", "100.00"]

    tab = tmp_path / "tab.csv"
    tab.write_bytes("日期\t金额\n20250102\t100.00\n".encode("utf-8"))
    assert read_grid(str(tab))[1] == ["20250102", "100.00"]


def test_read_grid_csv_cr_only_line_endings(tmp_path):
    """老式 Mac / 部分银行导出只用 \\r 换行，csv 读取必须开 newline='' 才能切行。"""
    p = tmp_path / "bank.csv"
    p.write_bytes("日期,金额\r20250102,100.00\r20250103,-50\r".encode("utf-8"))

    rows = read_grid(str(p))

    assert rows == [["日期", "金额"], ["20250102", "100.00"], ["20250103", "-50"]]


def test_read_grid_csv_quoted_multiline_cell(tmp_path):
    """引号内的换行应原样保留为一个单元格，不报 new-line character。"""
    p = tmp_path / "bank.csv"
    p.write_bytes('摘要,金额\r"第一行\r\n第二行",100\r'.encode("utf-8"))

    rows = read_grid(str(p))

    assert rows[0] == ["摘要", "金额"]
    assert rows[1][0] == "第一行\r\n第二行"
    assert rows[1][1] == "100"


def test_read_grid_csv_extension_but_xlsx_content(tmp_path):
    """扩展名是 .csv、内容其实是 xlsx（zip 魔数）时按内容读。"""
    p = tmp_path / "TQP_test.csv"
    pd.DataFrame([["账户明细", None], ["交易时间", "金额", None],
                  ["2026-01-08 15:51:12", 4161.47, None]]).to_excel(
        p, header=False, index=False, engine="openpyxl")
    assert p.read_bytes()[:2] == b"PK"

    rows = read_grid(str(p))

    assert rows[0][0] == "账户明细"
    assert rows[2][0] == "2026-01-08 15:51:12"
    assert rows[2][1] == "4161.47"


def test_read_grid_csv_extension_but_ole2_content_uses_xls_engine(tmp_path, monkeypatch):
    """银行导出常见的「.csv 扩展名 + Excel 97-2003 内容」（OLE2 魔数）应交给 xlrd。"""
    p = tmp_path / "TQP_test2.csv"
    p.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512)
    seen = {}

    def fake_read_excel(path, **kwargs):
        seen.update(kwargs)
        return pd.DataFrame([["账户明细"], ["交易时间", "金额"]])

    monkeypatch.setattr("app.parsing.excel_reader.pd.read_excel", fake_read_excel)

    rows = read_grid(str(p))

    assert seen.get("engine") == "xlrd"
    assert rows[1] == ["交易时间", "金额"]


def test_read_grid_xlsx(tmp_path):
    p = tmp_path / "bank.xlsx"
    pd.DataFrame([["账户明细", None], ["交易时间", "支出金额"],
                  ["2026-01-08 15:51:12", 4161.47]]).to_excel(p, header=False, index=False)

    rows = read_grid(str(p))

    assert rows[0][0] == "账户明细"
    assert rows[2][0] == "2026-01-08 15:51:12"
    assert rows[2][1] == "4161.47"


def test_read_table_csv_detects_header_and_extracts_account(tmp_path):
    p = tmp_path / "bank.csv"
    p.write_bytes((BOM + CSV_TEXT).encode("utf-8"))

    raw = read_table(str(p))

    assert raw.headers[0].startswith("交易类型")
    assert len(raw.rows) == 2
    assert raw.preamble[0][0].startswith("查询账号")
