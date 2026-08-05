# 订单主表字段说明

> 表名：`dwd_order_d` ｜ 层级：DWD 明细层 ｜ 负责人：王芳 ｜ 更新：日级 T+1

## 一、表用途

存储订单主信息（一订单一行），是订单分析看板的核心事实表。粒度：`order_id`。

## 二、字段清单

| 字段名 | 类型 | 说明 |
|---|---|---|
| order_id | string | 订单号，主键 |
| order_status | string | 订单状态：PENDING/PAID/SHIPPED/DONE/RETURNED |
| region | string | 下单区域：EAST/SOUTH/WEST/NORTH/CENTER |
| channel | string | 下单渠道：APP/WEB/MINIAPP/STORE |
| order_total_amount | decimal(12,2) | 优惠前总额 |
| discount_amount | decimal(12,2) | 订单级优惠 |
| order_pay_amount | decimal(12,2) | 实付金额 = total - discount |
| pay_time | datetime | 支付时间 |
| ship_time | datetime | 发货时间 |
| done_time | datetime | 完成时间 |
| customer_id | string | 客户ID |

## 三、状态流转

PENDING → PAID → SHIPPED → DONE；任意状态可 → RETURNED。RETURNED 为终态。

## 四、分区策略

按 `dt` 日期分区，每日增量更新当日变更订单，保留 36 个月。
