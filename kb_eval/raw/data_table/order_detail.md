# 订单明细表字段说明

> 表名：`dwd_order_detail_d` ｜ 层级：DWD 明细层 ｜ 负责人：李明 ｜ 更新：日级 T+1

## 一、表用途

存储每笔订单的商品明细行（一订单多商品一行一记录），用于订单分析看板的明细下钻、退货分析、商品关联分析。粒度：`order_id + item_id`。

## 二、字段清单

| 字段名 | 类型 | 说明 |
|---|---|---|
| order_id | string | 订单号，关联 `dwd_order_d.order_id` |
| item_id | string | 明细行号，同一订单内自增 |
| product_sku | string | 商品 SKU |
| product_name | string | 商品名称 |
| qty | int | 购买数量 |
| unit_price | decimal(12,2) | 单价（含税） |
| line_total | decimal(12,2) | 行小计 = qty × unit_price |
| discount_amount | decimal(12,2) | 行级优惠金额 |
| create_time | datetime | 明细创建时间 |
| is_gift | boolean | 是否赠品行（赠品行 unit_price=0） |

## 三、数据质量规则

- `line_total` 必须等于 `qty × unit_price - discount_amount`，否则记 DQ 告警。
- `qty` 必须 > 0（赠品行除外，赠品 qty 由业务配置）。
- `product_sku` 不得为空，空值进清洗异常表 `dwd_order_detail_d_dirty`。

## 四、分区策略

按 `dt`（日期分区）增量写入，每日全量覆盖当日分区。保留 36 个月。
