from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from backend.config.settings import get_settings
from backend.tools.fund_tools import TOOLS

SYSTEM_PROMPT = (
    "你是个人基金市场信息助手，不是投资顾问。"
    "你只能提供公开信息整理、历史数据分析和风险提示。"
    "你不能给出买入、卖出、持有、加仓、减仓、申购、赎回等建议，不预测或承诺收益。"
    "所有数字必须来自工具返回结果，不得自行编造或心算。"
    "回答时附上数据来源(source)与日期(as_of)。"
    "若工具返回 error，请如实说明数据缺失，不要编造数据。"
)


def build_agent() -> AgentExecutor:
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY 未配置。请在 backend/.env 中设置后重试。")
    llm = ChatOpenAI(
        model=settings.deepseek_model,
        base_url=settings.deepseek_base_url,
        api_key=settings.deepseek_api_key,
        temperature=0,
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])
    agent = create_tool_calling_agent(llm, TOOLS, prompt)
    return AgentExecutor(agent=agent, tools=TOOLS, verbose=True)


def ask(question: str) -> str:
    executor = build_agent()
    result = executor.invoke({"input": question})
    return result["output"]
