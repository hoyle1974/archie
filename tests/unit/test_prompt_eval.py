import importlib.util
from pathlib import Path


def _module():
    spec = importlib.util.spec_from_file_location("prompt_eval", Path("scripts/prompt_eval.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_review_questions_are_loaded_after_the_built_in_ones(tmp_path):
    mod = _module()
    (tmp_path / "reviews/evals").mkdir(parents=True)
    (tmp_path / "reviews/evals/questions.yaml").write_text(
        "- q: What is Workpersons title?\n  handlers: [who]\n  has: [Director of Engineering]\n  lacks: []\n")
    qs = mod.load_questions(tmp_path)
    assert qs[: len(mod.QUESTIONS)] == mod.QUESTIONS
    assert qs[-1]["q"] == "What is Workpersons title?"
    assert mod.load_questions(tmp_path / "missing") == mod.QUESTIONS
