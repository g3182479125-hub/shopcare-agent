from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(r"E:\agnet\2024全年电商订单+用户数据集含38万订单数据+9.8万用户数据")
ORDER_CSV = SOURCE / "order.csv"
USER_CSV = SOURCE / "user.csv"
OUTPUT = ROOT / "frontend" / "public" / "merchant_analytics.json"


def as_float(value: str) -> float:
    try:
        return float(value or 0)
    except ValueError:
        return 0.0


def as_int(value: str) -> int:
    try:
        return int(float(value or 0))
    except ValueError:
        return 0


def top_items(counter: Counter, limit: int = 8) -> list[dict]:
    return [{"name": name, "value": value} for name, value in counter.most_common(limit)]


def open_csv(path: Path):
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            handle = path.open("r", encoding=encoding, newline="")
            handle.readline()
            handle.seek(0)
            return handle
        except UnicodeDecodeError:
            handle.close()
    return path.open("r", encoding="utf-8", errors="replace", newline="")


def user_tier(total_amount: float, total_times: int) -> str:
    if total_amount >= 5000 or total_times >= 8:
        return "VIP"
    if total_amount >= 1500 or total_times >= 4:
        return "HighValue"
    if total_amount >= 500 or total_times >= 2:
        return "Regular"
    return "New"


def main() -> None:
    order_count = 0
    gmv = 0.0
    quantity = 0
    unique_users: set[str] = set()
    status_count: Counter = Counter()
    payment_count: Counter = Counter()
    category_count: Counter = Counter()
    category_gmv: defaultdict[str, float] = defaultdict(float)
    category_fulfillment: defaultdict[str, list[int]] = defaultdict(list)
    brand_gmv: defaultdict[str, float] = defaultdict(float)
    product_gmv: defaultdict[str, float] = defaultdict(float)
    month_gmv: defaultdict[str, float] = defaultdict(float)
    month_orders: Counter = Counter()
    city_gmv: defaultdict[str, float] = defaultdict(float)
    province_gmv: defaultdict[str, float] = defaultdict(float)
    hot_gmv = 0.0
    fulfillment_values: list[int] = []

    with open_csv(ORDER_CSV) as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            amount = as_float(row.get("amount", "0"))
            qty = as_int(row.get("quantity", "0"))
            month = (row.get("order_time", "") or "")[:7]
            category = row.get("category") or "Unknown"
            brand = row.get("brand") or "Unknown"
            product = row.get("product_name") or "Unknown"
            city = row.get("shipping_city") or "Unknown"
            province = row.get("user_province_name") or "Unknown"
            fulfillment = as_int(row.get("fulfillment_time", "0"))

            order_count += 1
            gmv += amount
            quantity += qty
            unique_users.add(row.get("user_id") or "")
            status_count[row.get("order_status") or "Unknown"] += 1
            payment_count[row.get("payment_method") or "Unknown"] += 1
            category_count[category] += 1
            category_gmv[category] += amount
            brand_gmv[brand] += amount
            product_gmv[product] += amount
            month_gmv[month] += amount
            month_orders[month] += 1
            city_gmv[city] += amount
            province_gmv[province] += amount
            if row.get("is_hot") == "1":
                hot_gmv += amount
            if fulfillment:
                fulfillment_values.append(fulfillment)
                category_fulfillment[category].append(fulfillment)

    user_count = 0
    tier_count: Counter = Counter()
    channel_count: Counter = Counter()
    total_clicks = 0
    total_carts = 0
    total_purchase_times = 0
    total_purchase_amount = 0.0

    with open_csv(USER_CSV) as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            times = as_int(row.get("total_purchase_times", "0"))
            amount = as_float(row.get("total_purchase_amount", "0"))
            user_count += 1
            tier_count[user_tier(amount, times)] += 1
            channel_count[row.get("register_channel") or "Unknown"] += 1
            total_clicks += as_int(row.get("click_count", "0"))
            total_carts += as_int(row.get("cart_count", "0"))
            total_purchase_times += times
            total_purchase_amount += amount

    month_rows = [
        {
            "month": month,
            "gmv": round(month_gmv[month], 2),
            "orders": month_orders[month],
        }
        for month in sorted(month_gmv)
        if month
    ]
    category_rows = [
        {
            "name": name,
            "orders": category_count[name],
            "gmv": round(value, 2),
            "aov": round(value / category_count[name], 2),
            "avg_fulfillment": round(mean(category_fulfillment[name]), 1) if category_fulfillment[name] else 0,
        }
        for name, value in sorted(category_gmv.items(), key=lambda item: item[1], reverse=True)[:8]
    ]
    brand_rows = [
        {"name": name, "gmv": round(value, 2)}
        for name, value in sorted(brand_gmv.items(), key=lambda item: item[1], reverse=True)[:8]
    ]
    product_rows = [
        {"name": name, "gmv": round(value, 2)}
        for name, value in sorted(product_gmv.items(), key=lambda item: item[1], reverse=True)[:8]
    ]
    city_rows = [
        {"name": name, "gmv": round(value, 2)}
        for name, value in sorted(city_gmv.items(), key=lambda item: item[1], reverse=True)[:8]
    ]
    province_rows = [
        {"name": name, "gmv": round(value, 2)}
        for name, value in sorted(province_gmv.items(), key=lambda item: item[1], reverse=True)[:8]
    ]

    best_category = category_rows[0]
    slow_category = max(category_rows, key=lambda row: row["avg_fulfillment"])
    top_month = max(month_rows, key=lambda row: row["gmv"])
    cart_rate = total_carts / total_clicks if total_clicks else 0
    purchase_frequency = total_purchase_times / user_count if user_count else 0

    data = {
        "generated_at": "2026-06-10",
        "overview": {
            "orders": order_count,
            "gmv": round(gmv, 2),
            "users": user_count,
            "buyers": len(unique_users),
            "aov": round(gmv / order_count, 2),
            "items": quantity,
            "hot_product_gmv_share": round(hot_gmv / gmv, 4) if gmv else 0,
            "avg_fulfillment_hours": round(mean(fulfillment_values), 1) if fulfillment_values else 0,
            "cart_rate": round(cart_rate, 4),
            "avg_purchase_frequency": round(purchase_frequency, 2),
            "user_ltv": round(total_purchase_amount / user_count, 2) if user_count else 0,
        },
        "monthly": month_rows,
        "categories": category_rows,
        "brands": brand_rows,
        "products": product_rows,
        "cities": city_rows,
        "provinces": province_rows,
        "payments": top_items(payment_count),
        "statuses": top_items(status_count),
        "tiers": top_items(tier_count),
        "channels": top_items(channel_count),
        "agent_insights": [
            {
                "title": f"{best_category['name']} 是当前主力盘",
                "body": f"贡献 GMV {best_category['gmv']:,.0f}，客单价 {best_category['aov']}。建议把首页资源位和直播讲解优先给这个类目。",
                "action": "加大投放",
            },
            {
                "title": f"{slow_category['name']} 履约偏慢",
                "body": f"平均履约 {slow_category['avg_fulfillment']} 小时，容易拖累评价和售后。建议拆分仓配或提高预警阈值。",
                "action": "优化履约",
            },
            {
                "title": f"{top_month['month']} 是全年销售峰值",
                "body": f"当月 GMV {top_month['gmv']:,.0f}，订单 {top_month['orders']:,}。建议复盘当月活动和爆品组合。",
                "action": "复盘活动",
            },
            {
                "title": "加购到成交还有提升空间",
                "body": f"整体加购率约 {cart_rate * 100:.1f}%，可用优惠券、包邮门槛和限时提醒提升转化。",
                "action": "提升转化",
            },
        ],
        "agent_replies": [
            "我先看经营大盘：订单量和 GMV 很稳，当前重点是把高 GMV 类目继续放大，同时处理履约慢的类目。",
            "如果你要下周经营动作，我建议先做三件事：主推高 GMV 类目、压缩慢履约链路、给高价值用户做复购券。",
            "从数据看，商家端最该盯的是 GMV、客单价、履约时效和加购率，这四个指标能直接影响利润和售后压力。",
        ],
    }

    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUTPUT}")
    print(json.dumps(data["overview"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
