"""LangChain agent 组件。

目前只有一个轻量的 tool-calling agent(`thin_agent`),把真正的活都
委托给 `backend.tools`。LLM 的唯一职责是编排和自然语言表达。
"""