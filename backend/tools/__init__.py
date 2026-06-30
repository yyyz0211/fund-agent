"""围绕 `backend.services` 的 LangChain tool 包装。

tool 本身很薄:它们调用 service 并把返回的字典透传出去。LLM 不直接
访问网络或数据库,只负责编排和表达。
"""