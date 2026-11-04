"""The watchdog: alerts outside email, and a time limit that leaves a trace of where a run was stuck. Prompted by
two silent failures on Nov 4, 2026: the review email failed along with the email reporting it, and a run hung."""

from __future__ import annotations

import threading

import httpx

from domain_health_check import cli, mailer, pipeline, watchdog


def test_an_alert_is_always_written_to_a_file_and_needs_no_network(tmp_path):
    path = tmp_path / "ALERT.txt"
    watchdog.alert("the email to the reviewer could not be sent", path=path)
    assert "the email to the reviewer could not be sent. Details: logs\\intake.log" in path.read_text("utf-8")


def test_with_a_topic_the_phone_notification_carries_only_the_kind_of_failure(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setenv("NTFY_TOPIC", "mizan-test-topic")
    monkeypatch.setattr(watchdog, "TRANSPORT", httpx.MockTransport(
        lambda request: sent.append(request) or httpx.Response(200)))
    watchdog.alert("intake ran longer than 20 minutes and was stopped", path=tmp_path / "ALERT.txt")
    [request] = sent
    assert str(request.url) == "https://ntfy.sh/mizan-test-topic"
    assert request.content == b"domain-health-check: intake ran longer than 20 minutes and was stopped."


def test_a_notification_that_cannot_be_delivered_never_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "mizan-test-topic")
    monkeypatch.setattr(watchdog, "TRANSPORT", httpx.MockTransport(lambda r: (_ for _ in ()).throw(
        httpx.ConnectError("down"))))
    watchdog.alert("x", path=tmp_path / "ALERT.txt")
    assert (tmp_path / "ALERT.txt").exists()


def test_a_run_past_its_limit_is_reported_its_stacks_saved_and_the_process_stopped(tmp_path):
    done, calls = threading.Event(), []
    exits = []

    def stop(code):
        exits.append(code)
        done.set()

    watchdog.start(lambda minutes: calls.append(minutes), minutes=0.001, hang_file=tmp_path / "hang.log",
                   exit_=stop)
    assert done.wait(5)
    assert calls == [0.001] and exits == [watchdog.HANG_EXIT]
    assert "passed its 0.001 minute limit" in (tmp_path / "hang.log").read_text("utf-8")


def test_a_run_that_finishes_cancels_the_limit(tmp_path):
    exits = []
    timer = watchdog.start(lambda m: None, minutes=0.002, hang_file=tmp_path / "hang.log", exit_=exits.append)
    timer.cancel()
    timer.join(1)
    assert exits == [] and not (tmp_path / "hang.log").exists()


def test_the_limit_comes_from_env_and_falls_back_on_nonsense(monkeypatch):
    assert watchdog.limit_minutes() == watchdog.DEFAULT_LIMIT_MINUTES
    monkeypatch.setenv("INTAKE_TIME_LIMIT_MINUTES", "7.5")
    assert watchdog.limit_minutes() == 7.5
    for bad in ("soon", "-3", "0"):
        monkeypatch.setenv("INTAKE_TIME_LIMIT_MINUTES", bad)
        assert watchdog.limit_minutes() == watchdog.DEFAULT_LIMIT_MINUTES


def test_an_email_to_the_reviewer_that_fails_raises_an_alert(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, "ALERT_FILE", tmp_path / "ALERT.txt")
    monkeypatch.setattr(pipeline, "LOG", tmp_path / "intake.log")

    def refuse(message):
        raise mailer.SendFailed("Connection unexpectedly closed")

    pipeline._tell(refuse, object())
    assert "could not email" in (tmp_path / "intake.log").read_text("utf-8")
    assert "the email to the reviewer could not be sent" in (tmp_path / "ALERT.txt").read_text("utf-8")


def test_intake_with_no_email_settings_raises_an_alert(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(watchdog, "ALERT_FILE", tmp_path / "ALERT.txt")
    monkeypatch.setattr(pipeline, "LOG", tmp_path / "intake.log")
    assert cli.main(["intake"]) == 2
    assert "email is not configured" in (tmp_path / "ALERT.txt").read_text("utf-8")
