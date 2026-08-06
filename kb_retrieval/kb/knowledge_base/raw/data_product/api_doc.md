# 数据产品 API 文档

> 流程编号 PRC-2024-003

## 概述

本接口提供订单数据查询能力，支持分页与按时间范围筛选。

## 接口列表

### 订单查询

- 路径: `/api/v1/orders`
- 方法: `GET`
- 参数: `start_date`, `end_date`, `page`

### 订单明细

- 路径: `/api/v1/orders/{id}/items`
- 方法: `GET`

## 错误码

| code | message |
|---|---|
| 400 | 参数错误 |
| 404 | 订单不存在 |
