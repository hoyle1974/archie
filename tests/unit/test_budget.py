import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from archie import doctor
from archie.llm.backend import GeminiBackend, LLMError, make_backend
from archie.llm.budget import Budget, cost_usd
from archie.store.home import init_home

OCT = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
LLM = {"backend": "gemini", "models": {"fast": "gemini-3.7-flash"}, "monthly_budget_usd": 15}


def usage(prompt, out, thinking):
    return SimpleNamespace(prompt_token_count=prompt, candidates_token_count=out, thoughts_token_count=thinking)


class Client:
    def __init__(self, text="a: ok", finish="STOP", meta=None):
        self.calls = []
        self.models = self
        self.resp = SimpleNamespace(text=text, prompt_feedback=None,
                                    candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name=finish))],
                                    usage_metadata=meta or usage(1_000_000, 100_000, 100_000))

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        return self.resp


def test_cost_uses_the_price_in_force_on_the_day_and_overcounts_unknown_models():
    assert cost_usd("gemini-3.7-flash", 1_000_000, 1_000_000, OCT) == pytest.approx(0.75 + 3.75)
    assert cost_usd("gemini-3.7-flash", 1_000_000, 1_000_000, datetime(2027, 1, 2, tzinfo=timezone.utc)) == \
        pytest.approx(1.50 + 7.50)
    assert cost_usd("gemini-9-ultra", 1_000_000, 1_000_000, OCT) > cost_usd("gemini-3.1-pro-preview", 1_000_000,
                                                                            1_000_000, OCT)


def test_spend_counts_only_this_month(tmp_path):
    home = init_home(tmp_path / "h")
    b = Budget(home, 15, clock=lambda: OCT)
    b.record("gemini-3.7-flash", "fast", 1_000_000, 0, 0)
    log = home.root / "logs/llm_usage.jsonl"
    with log.open("a") as fh:
        fh.write(json.dumps({"ts": "2026-09-30T23:00:00+00:00", "usd": 99.0}) + "\n")
    assert b.spent() == pytest.approx(0.75)
    assert json.loads(log.read_text().splitlines()[0])["model"] == "gemini-3.7-flash"


def test_summary_reads_plainly_at_every_size(tmp_path):
    home = init_home(tmp_path / "h")
    b = Budget(home, 15, clock=lambda: OCT)
    assert b.summary() == "Gemini: $0.00 of $15 this month"
    b.record("gemini-3.7-flash", "fast", 28_000, 0, 0)  # $0.021
    assert b.summary() == "Gemini: $0.02 of $15 this month"
    b.record("gemini-3.7-flash", "fast", 1_600_000, 0, 0)  # +$1.20
    assert b.summary() == "Gemini: $1.22 of $15 this month"
    b.record("gemini-3.7-flash", "fast", 20_000_000, 0, 0)
    assert b.summary() == "Gemini: $16.22 of $15 this month: paused until Nov 1"


def test_session_spend_counts_only_this_process_calls(tmp_path):
    home = init_home(tmp_path / "h")
    Budget(home, 15, clock=lambda: OCT).record("gemini-3.7-flash", "fast", 1_000_000, 0, 0)  # an earlier run: $0.75
    b = Budget(home, 15, clock=lambda: OCT)
    assert b.session_usd == 0
    b.record("gemini-3.7-flash", "fast", 40_000, 0, 0)  # $0.03
    assert b.session_usd == pytest.approx(0.03)
    assert b.session_line() == "Gemini: $0.03 this session"
    assert b.spent() == pytest.approx(0.78)


def test_gemini_records_each_call_and_refuses_once_the_month_is_used_up(tmp_path):
    home = init_home(tmp_path / "h")
    client = Client()  # each call: 1M in ($0.75) + 200k out incl. thinking ($0.75) = $1.50
    b = GeminiBackend(LLM, client=client, budget=Budget(home, 3, clock=lambda: OCT))
    b.generate("s", "u")
    b.generate("s", "u")
    with pytest.raises(LLMError, match=r"monthly Gemini budget \(\$3\) is used up.*Nov 1") as err:
        b.generate("s", "u")
    assert len(client.calls) == 2 and not err.value.about_input


def test_a_cut_off_reply_is_still_billed(tmp_path):
    home = init_home(tmp_path / "h")
    budget = Budget(home, 15, clock=lambda: OCT)
    with pytest.raises(LLMError, match="cut off"):
        GeminiBackend(LLM, client=Client(finish="MAX_TOKENS"), budget=budget).generate("s", "u")
    assert budget.spent() == pytest.approx(1.50)


def test_make_backend_reads_the_budget_from_config(tmp_path):
    home = init_home(tmp_path / "h")
    b = make_backend({"llm": LLM}, home)
    assert b.budget.limit == 15 and b.budget.home == home


def test_doctor_shows_spend_and_flags_a_used_up_budget(tmp_path):
    home = init_home(tmp_path / "h")
    cfg = {"llm": {**LLM, "monthly_budget_usd": 2}}
    assert doctor.check_budget(home, cfg, clock=lambda: OCT) == (True, "gemini spend this month: $0.00 of $2")
    Budget(home, 2, clock=lambda: OCT).record("gemini-3.7-flash", "fast", 2_000_000, 200_000, 0)
    ok, msg = doctor.check_budget(home, cfg, clock=lambda: OCT)
    assert not ok and "$2.25 of $2" in msg and "monthly_budget_usd" in msg


def test_each_call_records_its_prompt_name_and_cached_tokens_and_can_log_the_prompt(tmp_path):
    from archie.llm.shape import F, Shape

    home = init_home(tmp_path / "h")
    meta = SimpleNamespace(prompt_token_count=100, candidates_token_count=5, thoughts_token_count=0,
                           cached_content_token_count=60)
    b = GeminiBackend(LLM, client=Client(meta=meta), budget=Budget(home, 15, clock=lambda: OCT),
                      prompt_log=home.root / "logs/prompts")
    b.complete("system words", "user words", Shape("probe", fields=(F("a"),)))
    entry = json.loads((home.root / "logs/llm_usage.jsonl").read_text().splitlines()[-1])
    assert entry["call"] == "probe" and entry["cached"] == 60
    [logged] = (home.root / "logs/prompts").iterdir()
    assert logged.name.endswith("-probe.md") and "system words" in logged.read_text()
