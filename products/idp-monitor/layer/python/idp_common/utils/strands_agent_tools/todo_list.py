import os
from aws_lambda_powertools import Logger
from typing_extensions import Any
from strands import Agent, tool

logger = Logger(service="agentic_idp", level=os.getenv("LOG_LEVEL", "INFO"))


@tool
def update_todo(task_index: int, completed: bool, agent: Agent) -> str:
    """Mark a todo item as completed or not completed.

    Args:
        task_index: Index of the task to update (1-based, matching the list display)
        completed: True to mark as completed, False to mark as incomplete

    Example:
        update_todo(1, True, agent)  # Mark first task as completed
    """
    todo_list: list[dict[str, Any]] | None = agent.state.get("todo_list")

    if not todo_list:
        return "No todo list found. Create one first using create_todo_list."

    # Convert to 0-based index
    index = task_index - 1

    if index < 0 or index >= len(todo_list):
        return f"Invalid task index {task_index}. Valid range: 1-{len(todo_list)}"

    todo_list[index]["completed"] = completed
    agent.state.set("todo_list", todo_list)

    status = "completed" if completed else "incomplete"
    logger.info(
        f"Updated todo {task_index}",
        extra={"task": todo_list[index]["task"], "completed": completed},
    )
    return f"Task {task_index} marked as {status}: {todo_list[index]['task']}"


@tool
def view_todo_list(agent: Agent) -> str:
    """View your current todo list with completion status."""
    todo_list: list[dict[str, Any]] | None = agent.state.get("todo_list")

    if not todo_list:
        return "No todo list found. Create one using create_todo_list to track your extraction tasks."

    completed_count = sum(1 for item in todo_list if item["completed"])
    total_count = len(todo_list)

    result = f"Todo List ({completed_count}/{total_count} completed):\n"
    result += "\n".join(
        f"{i + 1}. [{'✓' if item['completed'] else ' '}] {item['task']}"
        for i, item in enumerate(todo_list)
    )

    return result


@tool
def create_todo_list(todos: list[str], agent: Agent) -> str:
    """Create a new todo list to track your extraction tasks. Use this to plan your work, especially for large documents.

    Args:
        todos: List of task descriptions to track (e.g., ["Extract rows 1-100", "Extract rows 101-200"])

    Example:
        create_todo_list(["Extract first 100 rows", "Extract rows 101-200", "Extract rows 201-300", "Validate and finalize"], agent)
    """
    todo_list = [{"task": task, "completed": False} for task in todos]
    agent.state.set("todo_list", todo_list)
    logger.info("Created todo list", extra={"todo_count": len(todo_list)})
    return f"Created todo list with {len(todo_list)} tasks:\n" + "\n".join(
        f"{i + 1}. [ ] {item['task']}" for i, item in enumerate(todo_list)
    )
