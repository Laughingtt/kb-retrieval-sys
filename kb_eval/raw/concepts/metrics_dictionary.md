# 指标口径字典

> 维护：指标治理组 ｜ 版本：v5.2 ｜ 更新：2024-09-10

## 一、GMV（商品交易总额）

- **口径**：`sum(order_pay_amount) where order_status in (PAID, SHIPPED, DONE)`
- **粒度**：可按日/周/月/区域/品类汇总
- **不含**：退款金额、未支付订单（PENDING）、赠品行金额
- **常见误区**：不要把 `order_total_amount`（含优惠前总额）当作 GMV，应取 `order_pay_amount`（实付金额）。

## 二、客单价

- **口径**：`GMV / 支付订单数`
- **支付订单数**：`count(distinct order_id) where order_status != PENDING`
- **注意**：退货订单在退货当月从分子分母同时剔除。

## 三、退货率

- **口径**：`退货订单数 / 已发货订单数`
- **退货订单数**：`count(distinct order_id) where order_status = RETURNED`
- **已发货订单数**：`count(distinct order_id) where order_status in (SHIPPED, DONE, RETURNED)`

## 四、动销率

- **口径**：`有销商品数 / 在售商品数`
- **有销商品数**：统计期内有 `dwd_order_detail_d` 记录的去重 `product_sku`
- **在售商品数**：商品中心 `dim_product` 中 `status = ON_SALE` 的去重 SKU

## 五、复购率

- **口径**：`统计期内购买≥2次的用户数 / 统计期有购买行为的用户数`
- **周期**：通常按月，月内多次购买算 1 次复购行为（按用户去重）
- **数据源**：`dws_user_repurchase_m`
