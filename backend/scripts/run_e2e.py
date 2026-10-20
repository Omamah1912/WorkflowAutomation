"""Phase 7 end-to-end run against a running API (local uvicorn or Cloud Run).

    python scripts/run_e2e.py --base-url http://localhost:8000

Runs the CSV batch (450 rows), the real-document manifest and the Samsung fixture, then prints
the acceptance checks (pass/fail) and the /metrics output. Uses only the standard library."""
import argparse
import json
import sys
import time
import urllib.request


def make_client(base_url: str):
    def call(method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base_url.rstrip("/") + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    return call


def run_and_wait(call, source: str, timeout_s: float = 900) -> dict:
    batch_id = call("POST", "/batch", {"source": source})["batch_id"]
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        batch = call("GET", f"/batch/{batch_id}")
        if batch["status"] != "running":
            return batch
        time.sleep(1)
    raise TimeoutError(f"{source} batch {batch_id} did not finish")


def acceptance(call) -> list[tuple[str, bool, str]]:
    """The five Phase 7 checks from CLAUDE.md, each computed from the API's live output."""
    results = []

    dup = call("GET", "/doc/JOB-00200")
    results.append(("FDOC-35032 held as duplicate",
                     dup["route"] == "duplicate" and dup["duplicate_of"] == "JOB-00012",
                     f"JOB-00200 route={dup['route']} duplicate_of={dup['duplicate_of']} ({dup['duplicate_reason']})"))

    shell = [call("GET", f"/doc/PSX-{i}") for i in ("185483", "207953", "230000")]
    results.append(("Shell template filings not flagged as duplicates",
                     all(d["duplicate_of"] is None for d in shell),
                     "; ".join(f"{d['doc_id']} period={d['period']['value'] if d['period'] else None} route={d['route']}"
                               for d in shell)))

    pso = call("GET", "/doc/PSX-283440")
    labels = [t["entity_label"] for t in pso["tracks"]]
    results.append(("PSO split into unconsolidated + consolidated tracks",
                     labels == ["unconsolidated", "consolidated"],
                     f"tracks={labels} pages={[t['pages'] for t in pso['tracks']]}"))

    ppp = call("GET", "/doc/PSX-215429")
    fields = {f["name"]: f for f in ppp["tracks"][0]["fields"]}
    div04 = next(r for r in ppp["tracks"][0]["rule_results"] if r["rule_id"] == "DIV-04")
    converted = "cash_dividend" in fields and fields["cash_dividend"]["derived_from"]
    flagged = div04["status"] == "fail" and ppp["route"] == "needs_review"
    results.append(("Percent-only dividend converted or flagged", bool(converted or flagged),
                     f"PPP 40%: {'converted to Rs ' + str(fields['cash_dividend']['value']) if converted else 'not converted'}; "
                     f"DIV-04 {div04['status']}: {div04['message']}; route={ppp['route']}"))

    sam = call("GET", "/doc/FIX-SAMSUNG-2018")
    failed = {r["rule_id"] for t in sam["tracks"] for r in t["rule_results"] if r["status"] == "fail"}
    results.append(("Samsung fixture escalated with DIV-01 + DIV-02",
                     sam["route"] == "needs_review" and {"DIV-01", "DIV-02"} <= failed
                     and sam["label"] == "Reconstruction from public reporting",
                     f"route={sam['route']} failed={sorted(failed)} consequence: {sam['review_packet']['computed_consequence']}"))
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    call = make_client(args.base_url)
    print("health:", call("GET", "/health"))
    for source in ("csv", "manifest", "fixture"):
        t0 = time.time()
        batch = run_and_wait(call, source)
        routes: dict[str, int] = {}
        for d in batch["documents"]:
            routes[d["route"]] = routes.get(d["route"], 0) + 1
        print(f"{source:9s} {len(batch['documents']):4d} docs in {time.time() - t0:6.1f}s  {routes}")

    print("\nAcceptance")
    results = acceptance(call)
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}\n         {detail}")
    print("\nMetrics")
    print(json.dumps(call("GET", "/metrics"), indent=2))
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
