"""Проверка логики пайплайна без реальных LLM и сети."""

from pathlib import Path

from agents_news.feeds import Deduper, NewsItem, load_state, save_state
from agents_news.pipeline import Expert, process_item


class FakeLLM:
    """ask: гейт отвечает ДА только эксперту it; рецензия — по полю review_answer.
    embed: вектор задаётся словарём vectors, незнакомый текст роняет KeyError."""

    def __init__(self, review_answer: str = "ВЕРДИКТ: ПРИНЯТО\n- замечаний нет",
                 vectors: dict[str, list[float]] | None = None,
                 confirm_dup: str = "НЕТ") -> None:
        self.review_answer = review_answer
        self.vectors = vectors or {}
        self.confirm_dup = confirm_dup

    def ask(self, model: str, system: str, user: str, temperature: float = 0.3) -> str:
        if "фильтр тем" in system:
            return "ДА" if "информационным технологиям" in user else "НЕТ."
        if "фильтр дублей" in system:
            return self.confirm_dup
        if "фактчекер" in system:
            return self.review_answer
        return "Переработанный текст статьи."

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        return [self.vectors[t] for t in texts]


CONFIG = {
    "models": {"gate": "gate", "reviewer": "reviewer", "embed": "embed"},
    "experts": [
        Expert(name="agro", title="Эксперт по агрономии",
               domain="сельское хозяйство", model="expert"),
        Expert(name="it", title="Эксперт по информационным технологиям",
               domain="IT", model="expert"),
    ],
}

ITEM = NewsItem(
    id="https://example.com/1",
    title="Вышел новый релиз ядра Linux",
    summary="Разработчики выпустили новую версию ядра.",
    link="https://example.com/1",
    source="https://example.com/rss",
)


def test_only_relevant_expert_writes_article(tmp_path: Path) -> None:
    config = dict(CONFIG, output_dir=str(tmp_path))
    written = process_item(FakeLLM(), config, ITEM)

    assert len(written) == 1
    assert written[0].parent.name == "it"

    text = written[0].read_text(encoding="utf-8")
    assert "verdict: ПРИНЯТО" in text
    assert "Переработанный текст статьи." in text
    assert "source: https://example.com/1" in text
    assert not any(p.name == "agro" for p in tmp_path.rglob("*") if p.is_dir())


def test_rejected_article_goes_to_rejected_subdir(tmp_path: Path) -> None:
    config = dict(CONFIG, output_dir=str(tmp_path))
    llm = FakeLLM(review_answer="ВЕРДИКТ: ОТКЛОНЕНО\n- выдуманы факты")
    written = process_item(llm, config, ITEM)

    assert len(written) == 1
    assert written[0].parent.name == "rejected"
    assert written[0].parent.parent.name == "it"
    assert "verdict: ОТКЛОНЕНО" in written[0].read_text(encoding="utf-8")


def test_deduper_jaccard_and_embedding_cascade() -> None:
    vectors = {
        "В Волгограде загорелся склад": [1.0, 0.0],
        "Пожар уничтожил склад в Волгограде": [0.95, 0.31],   # cos ~0.95: дубль
        "Совсем другая новость про бабочек": [0.0, 1.0],      # cos 0: не дубль
        "Открытие школы в Волжском": [0.75, 0.66],            # cos ~0.75: серая зона
    }
    llm = FakeLLM(vectors=vectors, confirm_dup="ДА")
    deduper = Deduper(llm, "gate", "embed", ["В Волгограде загорелся склад"])

    # Жаккар: те же слова в другом порядке — дубль без эмбеддингов
    assert deduper.is_duplicate("Склад загорелся в Волгограде")
    # высокий косинус — дубль без подтверждения
    assert deduper.is_duplicate("Пожар уничтожил склад в Волгограде")
    # низкий косинус — не дубль
    assert not deduper.is_duplicate("Совсем другая новость про бабочек")
    # серая зона — решает LLM (здесь отвечает ДА)
    assert deduper.is_duplicate("Открытие школы в Волжском")
    llm.confirm_dup = "НЕТ"
    assert not deduper.is_duplicate("Открытие школы в Волжском")


def test_deduper_degrades_without_embeddings() -> None:
    llm = FakeLLM()  # пустой словарь векторов -> embed падает с KeyError
    deduper = Deduper(llm, "gate", "embed", ["В Волгограде загорелся склад"])
    assert deduper.is_duplicate("Склад загорелся в Волгограде")   # Жаккар работает
    assert not deduper.is_duplicate("Пожар уничтожил склад в Волгограде")


def test_state_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "seen.json"
    save_state(path, {"ids": {"a", "b"}, "titles": ["Первая новость"]})
    state = load_state(path)
    assert state["ids"] == {"a", "b"}
    assert state["titles"] == ["Первая новость"]
