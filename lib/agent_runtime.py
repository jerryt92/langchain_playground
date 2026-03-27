from __future__ import annotations

from abc import ABC, abstractmethod


class InteractiveAgentRuntime(ABC):
    """交互式 Agent 运行时基类。

        提供了一个用于与 Agent 进行交互的框架，支持两种运行模式:

        1. **单次运行模式** (`run_one_shot`): 处理单个问题并返回答案
        2. **交互式模式** (`run_interactive`): 持续对话，支持多轮交互

        该类定义了 Agent 运行时的基本接口和通用功能:
        - 消息发送与响应接收
        - 会话状态管理 (重置、清空上下文)
        - 用户输入处理
        - 结果输出格式化
        - 退出和重置命令处理

        子类需要实现 `send_message` 方法来定义具体的 Agent 执行逻辑。

        Attributes:
            intro_message (str): 进入交互模式时显示的欢迎信息
            input_prompt (str): 用户输入提示符
            exit_commands (set[str]): 触发退出的命令集合
            clear_commands (set[str]): 触发重置的命令集合
    """
    intro_message = "进入交互模式，输入 exit 退出，输入 clear 清空上下文。"
    input_prompt = "\n请输入问题 > "
    exit_commands = {"exit", "quit", "q"}
    clear_commands = {"clear", "reset"}

    @abstractmethod
    def send_message(self, message: str) -> str:
        """Run one user turn and return the final answer text."""

    def reset(self) -> None:
        """Clear the current conversation state."""

    def wait_input(self, prompt: str | None = None) -> str:
        return input(prompt or self.input_prompt).strip()

    def print_answer(self, answer: str) -> None:
        print("\n=== 最终回答 ===")
        print(answer)

    def run_one_shot(self, question: str) -> int:
        self.print_answer(self.send_message(question))
        return 0

    def run_interactive(self) -> int:
        print(self.intro_message)
        while True:
            question = self.wait_input()
            if not question:
                continue

            normalized = question.lower()
            if normalized in self.exit_commands:
                print("已退出。")
                return 0
            if normalized in self.clear_commands:
                self.reset()
                print("上下文已清空。")
                continue

            self.print_answer(self.send_message(question))
