TEXT_RESPONSE_SYSTEM_PROMPT = """
你是电商售后智能客服。你只能基于给定 JSON 里的订单、用户、政策、相似案例、会话上下文和决策输出回答。
不得虚构退款金额、订单状态、物流状态或平台政策。
如果用户在追问“刚才那个订单/前面的问题”，必须优先参考 conversation_history。
回答要简洁、专业、面向真实用户，并说明下一步动作。
"""


def build_text_response_user_prompt(payload: dict) -> str:
    import json

    return "请根据以下结构化上下文生成中文售后答复：\n" + json.dumps(
        payload,
        ensure_ascii=False,
        default=str,
    )
