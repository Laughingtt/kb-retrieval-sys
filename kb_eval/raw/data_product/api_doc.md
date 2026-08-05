# 数据产品 API 文档

> 流程编号：PRC-2024-003 ｜ 维护：数据中台 API 网关组 ｜ 版本：v1.4

## 一、概述

本文档定义订单分析看板对外暴露的查询接口。所有接口遵循公司内部 OpenAPI 规范，走 API 网关鉴权（OAuth2 client_credentials），返回 JSON。基类路径：`https://api.internal/dataproduct/order/v1`。

## 二、接口清单

| 接口名称 | 方法 | 路径 | 用途 |
|---|---|---|---|
| 订单查询 | GET | `/api/v1/orders` | 分页查询订单列表，支持按时间/状态/区域筛选 |
| 订单明细 | GET | `/api/v1/orders/{id}/items` | 查询某订单的商品明细行 |

## 三、订单查询接口

`GET /api/v1/orders`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| start_time | string(ISO8601) | 是 | 订单创建起始时间 |
| end_time | string(ISO8601) | 是 | 订单创建结束时间 |
| order_status | string | 否 | PENDING/PAID/SHIPPED/DONE/RETURNED，多值逗号分隔 |
| region | string | 否 | 区域编码，如 `EAST`/`SOUTH` |
| page | int | 否 | 页码，默认 1 |
| page_size | int | 否 | 每页条数，默认 20，最大 100 |

返回示例：

```json
{
  "total": 1280,
  "page": 1,
  "items": [
    {"order_id": "OD20240901001", "order_status": "PAID", "region": "EAST", "pay_amount": 299.00}
  ]
}
```

错误码：`400` 参数缺失；`401` 未鉴权；`429` 限流（QPS 上限 50）。

## 四、订单明细接口

`GET /api/v1/orders/{id}/items`

路径参数：`id` = 订单号。

返回某订单的商品明细行列表，每行含 `item_id`/`product_sku`/`qty`/`unit_price`/`line_total`。

## 五、限流与配额

- 单应用 QPS 上限 50，超出返回 `429`。
- 单次查询时间跨度不超过 90 天，否则 `400`。
- 日调用量配额由数据资产平台分配，超额需提工单扩容。
