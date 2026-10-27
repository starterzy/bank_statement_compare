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
