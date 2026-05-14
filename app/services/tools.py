from __future__ import annotations


TOOLS = [
    {
        "id": "mentor",
        "title": "Агент-наставник",
        "status": "active",
        "description": "Объясняет принципы, действия и причинно-следственные связи при работе со звуком.",
    },
    {
        "id": "critic",
        "title": "Агент-критик",
        "status": "mock",
        "description": "Будущий модуль для разбора результата студента и мягкой обратной связи.",
    },
    {
        "id": "methodologist",
        "title": "Агент-методист",
        "status": "mock",
        "description": "Будущий модуль для построения учебной траектории и последовательности заданий.",
    },
    {
        "id": "task-generator",
        "title": "Генератор заданий",
        "status": "mock",
        "description": "Будущий модуль для учебных упражнений без выдачи готового творческого результата.",
    },
    {
        "id": "audio-project-analyzer",
        "title": "Анализ аудио/проекта",
        "status": "mock",
        "description": "Будущий модуль для анализа загруженных аудиофайлов и структуры проекта.",
    },
]


def list_tools() -> list[dict]:
    return TOOLS


def run_mock_tool(tool_id: str) -> dict:
    tool = next((item for item in TOOLS if item["id"] == tool_id), None)
    if not tool:
        return {"ok": False, "message": "Инструмент не найден."}
    if tool["status"] == "active":
        return {"ok": True, "message": "Этот инструмент уже используется как основной чат-наставник."}
    return {
        "ok": True,
        "message": f"{tool['title']} заложен архитектурно и будет подключен в следующих версиях.",
    }
