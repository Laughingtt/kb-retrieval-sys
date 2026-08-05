"""造一份合成 Excel：订单宽表（宽表，>20 列，触发字段分组）。

运行：python kb_eval/make_wide_xlsx.py
产出：kb_eval/raw/data_table/order_wide.xlsx
"""
from __future__ import annotations
from pathlib import Path
from openpyxl import Workbook

OUT = Path(__file__).parent / "raw" / "data_table" / "order_wide.xlsx"

# 4 组字段（共 30 列，> 20 触发宽表分组）
COLS = [
    # 订单信息组
    "order_id", "order_name", "order_status",
    # 金额信息组
    "amount_total", "amount_tax", "amount_discount",
    # 时间信息组
    "time_create", "time_pay", "time_ship",
    # 扩展字段组（15 个 extra）
] + [f"extra_{i}" for i in range(15)]

ROWS = [
    ["OD20240901001", "华东秋季大促单#1", "PAID",
     599.00, 71.88, 50.00,
     "2024-09-01 09:12:00", "2024-09-01 09:15:00", "",
     "备注A", "CUST_8001", "EAST", "APP", "v1", "tags:promo",
     "Y", "N", "N", "Y", "N", "N", "Y", "N", "N", "Y", "N", "N", "Y", "N", "N"],
    ["OD20240901002", "华南退货单", "RETURNED",
     128.00, 15.36, 0.00,
     "2024-09-01 10:30:00", "2024-09-01 10:35:00", "2024-09-02 08:00:00",
     "退货备注", "CUST_8002", "SOUTH", "WEB", "v1", "tags:return",
     "N", "N", "Y", "N", "N", "Y", "N", "N", "Y", "N", "N", "Y", "N", "N", "Y"],
]


def main() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "order_wide"
    ws.append(COLS)
    for r in ROWS:
        ws.append(r)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print(f"[OK] wrote {OUT}  cols={len(COLS)} rows={len(ROWS)}")


if __name__ == "__main__":
    main()
