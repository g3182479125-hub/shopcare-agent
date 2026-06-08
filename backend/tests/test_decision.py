from app.agent.tools import decide_aftersales


def test_paid_order_can_refund_before_shipping():
    order = {"order_id": "3000010", "order_status": "Paid", "category": "家居日用", "amount": 100, "fulfillment_time": 12}
    decision = decide_aftersales(message="我想退款", intent="refund", order=order, user=None, policy_hits=[])
    assert decision["status"] == "approved"
    assert decision["resolution"] == "refund_only"
