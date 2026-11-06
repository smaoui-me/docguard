import json

import pytest

from docguard.ai.files import ProposalError
from docguard.ai.human_review import review_template, score_review


@pytest.fixture
def form(tmp_path):
    report = tmp_path / "report.json"
    reviews = tmp_path / "reviews.json"
    report.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "case": "a",
                        "status": "completed",
                        "action": "revise",
                        "expected_action": "revise",
                    },
                    {
                        "case": "b",
                        "status": "completed",
                        "action": "unchanged",
                        "expected_action": "unchanged",
                    },
                    {"case": "c", "status": "api_error"},
                ]
            }
        )
    )
    review_template(report, reviews)
    return report, reviews, tmp_path / "scores.json"


def test_pending_reviews_have_no_invented_scores(form):
    report, reviews, output = form
    data = json.loads(reviews.read_text())
    assert [r["case"] for r in data["reviews"]] == ["a", "b"]
    result = score_review(report, reviews, output)
    assert result["reviewed_cases"] == 0
    assert result["metrics"]["acceptance"]["value"] is None


def filled(row, independent=True):
    return {
        **row,
        "reviewer": "human@example.invalid",
        "independent": independent,
        "expected_action": "unchanged",
        "supported": False,
        "complete": True,
        "preserves_unrelated": True,
        "accepted": False,
        "notes": "Claim not established by cited source.",
    }


def test_explicit_ratings_and_disagreements_keep_denominators(form):
    report, reviews, output = form
    data = json.loads(reviews.read_text())
    data["reviews"][0] = filled(data["reviews"][0])
    reviews.write_text(json.dumps(data))
    result = score_review(report, reviews, output)
    assert result["selected_cases"] == 3
    assert result["metrics"]["coverage_of_completed"]["value"] == 0.5
    assert result["independent_metrics"]["acceptance"]["value"] == 0
    assert result["metrics"]["label_agreement"]["value"] == 0
    assert json.loads(report.read_text())["results"][0]["expected_action"] == "revise"


@pytest.mark.parametrize(
    "change",
    ["duplicate", "unknown", "partial", "integer_bool", "stale", "no_reviewer"],
)
def test_invalid_reviews_rejected(form, change):
    report, reviews, output = form
    data = json.loads(reviews.read_text())
    data["reviews"][0] = filled(data["reviews"][0])
    if change == "duplicate":
        data["reviews"].append(data["reviews"][0])
    elif change == "unknown":
        data["reviews"][0]["case"] = "c"
    elif change == "partial":
        data["reviews"][0]["complete"] = None
    elif change == "integer_bool":
        data["reviews"][0]["accepted"] = 1
    elif change == "no_reviewer":
        data["reviews"][0]["reviewer"] = " "
    else:
        report.write_text(report.read_text() + " ")
    reviews.write_text(json.dumps(data))
    with pytest.raises(ProposalError):
        score_review(report, reviews, output)
    assert not output.exists()


def test_nonindependent_reviews_reported_separately_and_cli(form, capsys):
    from docguard.cli import main

    report, reviews, output = form
    data = json.loads(reviews.read_text())
    data["reviews"][0] = filled(data["reviews"][0], independent=False)
    reviews.write_text(json.dumps(data))
    assert (
        main(
            [
                "score-review",
                str(report),
                "--reviews",
                str(reviews),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    result = json.loads(output.read_text())
    assert result["reviewed_cases"] == 1
    assert result["independent_metrics"]["acceptance"]["value"] is None
    assert "1/2" in capsys.readouterr().out
