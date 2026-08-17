"""Пайплайн: фильтр релевантности -> переработка экспертом -> независимая проверка."""

import datetime
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from agents_news.feeds import NewsItem
from agents_news.llm import LLM

logger = logging.getLogger(__name__)

GATE_SYSTEM = (
    "Ты — фильтр тем для новостной ленты. Отвечай строго одним словом: ДА или НЕТ."
)
GATE_USER = (
    "Тема эксперта: {title}.\nОбласть: {domain}\n\n"
    "Новость:\nЗаголовок: {news_title}\nТекст: {summary}\n\n"
    "Относится ли новость к области эксперта? Ответь одним словом: ДА или НЕТ."
)

EXPERT_SYSTEM = (
    "Ты — {title}. Перепиши новость для своей профессиональной аудитории "
    "(область: {domain}). Используй только факты из исходной новости, ничего не "
    "выдумывай и не добавляй. Пиши по-русски, 3–5 абзацев: суть события, "
    "значение для отрасли, практический вывод. Без приветствий и преамбул."
)
EXPERT_USER = "Заголовок: {news_title}\nТекст: {summary}\nИсточник: {link}"

REVIEW_SYSTEM = (
    "Ты — независимый редактор-фактчекер. Сравни исходную новость и статью, "
    "написанную по ней. Проверь: 1) нет ли в статье фактов, которых не было в "
    "исходнике; 2) не искажён ли смысл; 3) раскрыта ли заявленная тема ({domain}). "
    "Первая строка ответа — строго «ВЕРДИКТ: ПРИНЯТО» или «ВЕРДИКТ: ОТКЛОНЕНО», "
    "дальше — замечания списком."
)
REVIEW_USER = (
    "ИСХОДНАЯ НОВОСТЬ:\nЗаголовок: {news_title}\nТекст: {summary}\n\n"
    "СТАТЬЯ ЭКСПЕРТА:\n{article}"
)


@dataclass(frozen=True)
class Expert:
    """Тематический эксперт: роль, область и алиас модели в шлюзе."""

    name: str
    title: str
    domain: str
    model: str


def is_relevant(llm: LLM, gate_model: str, expert: Expert, item: NewsItem) -> bool:
    """Относится ли новость к области эксперта (ответ gate-модели ДА/НЕТ)."""
    answer = llm.ask(
        gate_model,
        GATE_SYSTEM,
        GATE_USER.format(
            title=expert.title, domain=expert.domain,
            news_title=item.title, summary=item.summary,
        ),
        temperature=0.0,
    )
    return answer.upper().lstrip("«\"' ").startswith("ДА")


def rewrite(llm: LLM, expert: Expert, item: NewsItem) -> str:
    """Переписать новость от лица эксперта для его аудитории."""
    return llm.ask(
        expert.model,
        EXPERT_SYSTEM.format(title=expert.title, domain=expert.domain),
        EXPERT_USER.format(
            news_title=item.title, summary=item.summary, link=item.link,
        ),
        temperature=0.4,
    )


def review(llm: LLM, reviewer_model: str, expert: Expert, item: NewsItem,
           article: str) -> dict:
    """Проверить статью независимой моделью; вернуть {"verdict", "notes"}."""
    answer = llm.ask(
        reviewer_model,
        REVIEW_SYSTEM.format(domain=expert.domain),
        REVIEW_USER.format(
            news_title=item.title, summary=item.summary, article=article,
        ),
        temperature=0.0,
    )
    first_line, _, rest = answer.partition("\n")
    verdict = "ПРИНЯТО" if "ПРИНЯТО" in first_line.upper() else "ОТКЛОНЕНО"
    return {"verdict": verdict, "notes": rest.strip() or first_line.strip()}


def _slug(title: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^\w-]+", "-", title.lower(), flags=re.UNICODE).strip("-")
    return slug[:max_len].rstrip("-") or "no-title"


def write_result(output_dir: Path, expert: Expert, item: NewsItem, article: str,
                 review_result: dict, reviewer_model: str) -> Path:
    """Сохранить статью в Markdown; отклонённые — в подпапку rejected/."""
    today = datetime.date.today().isoformat()
    expert_dir = output_dir / today / expert.name
    if review_result["verdict"] != "ПРИНЯТО":
        expert_dir = expert_dir / "rejected"
    path = expert_dir / f"{_slug(item.title)}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            f"---\n"
            f"source: {item.link}\n"
            f"expert: {expert.name}\n"
            f"expert_model: {expert.model}\n"
            f"reviewer_model: {reviewer_model}\n"
            f"verdict: {review_result['verdict']}\n"
            f"date: {today}\n"
            f"---\n\n"
            f"# {item.title}\n\n"
            f"{article}\n\n"
            f"## Замечания рецензента\n\n{review_result['notes']}\n"
        ),
        encoding="utf-8",
    )
    return path


def process_item(llm: LLM, config: dict, item: NewsItem) -> list[Path]:
    """Прогнать одну новость через всех экспертов; вернуть пути созданных файлов."""
    written: list[Path] = []
    for expert in config["experts"]:
        if not is_relevant(llm, config["models"]["gate"], expert, item):
            logger.info("[%s] пропуск: %s", expert.name, item.title)
            continue
        logger.info("[%s] переработка: %s", expert.name, item.title)
        article = rewrite(llm, expert, item)
        review_result = review(llm, config["models"]["reviewer"], expert, item, article)
        path = write_result(
            Path(config["output_dir"]), expert, item, article, review_result,
            config["models"]["reviewer"],
        )
        if review_result["verdict"] == "ПРИНЯТО":
            logger.info("[%s] ПРИНЯТО -> %s", expert.name, path)
        else:
            logger.warning("[%s] рецензент ОТКЛОНИЛ статью — сохранена в %s",
                           expert.name, path)
        written.append(path)
    return written
