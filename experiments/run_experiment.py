"""
두 방식(naive / queue)에 동시 요청 N건을 보내고, 컨테이너 메모리·소요 시간·생존 여부를 잰다.

사용법 (프로젝트 루트에서):
    docker compose -p playstory-exp -f experiments/docker-compose.yml up --build -d
    python experiments/run_experiment.py
외부 라이브러리 없이 표준 라이브러리 + docker CLI만 사용한다.
"""
import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT = "playstory-exp"
CONCURRENCY = [1, 3, 5, 10]
TIMEOUT_SEC = 900

VARIANTS = {
    "naive": {"port": 8001, "create": "/jobs", "status": "/jobs/{id}", "container": f"{PROJECT}-naive-1"},
    "queue": {"port": 8002, "create": "/api/jobs", "status": "/api/jobs/{id}", "container": f"{PROJECT}-queue-1"},
}


def docker(*args: str) -> str:
    return subprocess.run(["docker", *args], capture_output=True, text=True).stdout.strip()


def http(method: str, url: str) -> dict:
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read())


def mem_mib(container: str) -> float | None:
    """docker stats의 현재 메모리 사용량 (MiB). 컨테이너가 죽었으면 None."""
    out = docker("stats", "--no-stream", "--format", "{{.MemUsage}}", container)
    if not out:
        return None
    value = out.split("/")[0].strip()
    for unit, factor in (("GiB", 1024), ("MiB", 1), ("KiB", 1 / 1024), ("B", 1 / 1024 / 1024)):
        if value.endswith(unit):
            return float(value[: -len(unit)]) * factor
    return None


def is_running(container: str) -> bool:
    return docker("inspect", "-f", "{{.State.Running}}", container) == "true"


def oom_killed(container: str) -> bool:
    return docker("inspect", "-f", "{{.State.OOMKilled}}", container) == "true"


def restart_and_wait(v: dict) -> None:
    """측정 전에 컨테이너를 재시작해서 메모리를 깨끗한 상태로 맞춘다."""
    docker("restart", v["container"])
    base = f"http://localhost:{v['port']}"
    for _ in range(60):
        try:
            http("GET", base + v["status"].format(id=0))
            return
        except urllib.error.HTTPError:
            return  # 404 등이어도 서버는 떠 있음
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"{v['container']} did not start")


def run_scenario(name: str, n: int) -> dict:
    v = VARIANTS[name]
    base = f"http://localhost:{v['port']}"
    restart_and_wait(v)
    time.sleep(2)
    idle = mem_mib(v["container"])

    # N건을 동시에 요청
    ids, lock = [], threading.Lock()

    def post():
        job = http("POST", base + v["create"])
        with lock:
            ids.append(job["job_id"])

    threads = [threading.Thread(target=post) for _ in range(n)]
    started = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    peak, result = idle or 0, "timeout"
    while time.monotonic() - started < TIMEOUT_SEC:
        m = mem_mib(v["container"])
        if m is not None:
            peak = max(peak, m)
        if not is_running(v["container"]):
            result = "OOM Killed 💥" if oom_killed(v["container"]) else "crashed"
            break
        try:
            statuses = [http("GET", base + v["status"].format(id=i))["status"] for i in ids]
        except Exception:
            continue  # 죽는 중일 수 있음 → 다음 루프에서 is_running으로 판정
        if all(s == "done" or s.startswith("failed") for s in statuses):
            failed = sum(s.startswith("failed") for s in statuses)
            result = "all done ✅" if failed == 0 else f"{failed} failed"
            break

    row = {
        "variant": name,
        "concurrency": n,
        "result": result,
        "idle_mib": round(idle or 0),
        "peak_mib": round(peak),
        "elapsed_sec": round(time.monotonic() - started, 1),
    }
    print(row, flush=True)
    return row


def main() -> None:
    rows = []
    for name in VARIANTS:
        for n in CONCURRENCY:
            row = run_scenario(name, n)
            rows.append(row)
            if not row["result"].startswith("all done"):
                break  # 이미 죽었으면 더 많은 동시 요청은 의미 없음

    lines = [
        "| 방식 | 동시 요청 | 결과 | 대기 메모리 | 최대 메모리 | 전체 소요 |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['variant']} | {r['concurrency']}건 | {r['result']} | {r['idle_mib']}MiB "
            f"| {r['peak_mib']}MiB | {r['elapsed_sec']}초 |"
        )
    out = Path(__file__).with_name("results.md")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines))
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    main()
