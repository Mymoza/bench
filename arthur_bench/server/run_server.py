import json
import argparse
from pathlib import Path
import uuid
from typing import Optional

try:
    import uvicorn
    from fastapi import FastAPI, Request
    from fastapi.staticfiles import StaticFiles
    from fastapi.middleware.cors import CORSMiddleware


except ImportError as e:
    raise ImportError("Can't run Bench Server without server dependencies, to install run: "
                      "pip install arthur-bench[server]") from e

from arthur_bench.client.local.client import _bench_root_dir, LocalBenchClient
from arthur_bench.telemetry.telemetry import send_event, set_track_usage_data
from arthur_bench.telemetry.config import get_or_persist_id, persist_usage_data

app = FastAPI()

origins = [
    "http://localhost:8000",
    "http://127.0.0.1:8000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONT_END_DIRECTORY = Path(__file__).parent / "js" / "dist"

SERVER_ROOT_DIR: Path
USER_ID: uuid.UUID


@app.get("/api/v3/bench/test_suites")
def test_suites(request: Request, page: int = 1, page_size: int = 5, sort: Optional[str] = None, scoring_method: Optional[str] = None, name: Optional[str] = None):
    client = LocalBenchClient(root_dir=SERVER_ROOT_DIR)
    suite_resp = client.get_test_suites(page=page, page_size=page_size, sort=sort, scoring_method=scoring_method, name=name).json()
    suites = json.loads(suite_resp)
    
    send_event({"event_type": "test_suites_load", "event_properties": {"num_test_suites_load": len(suites["test_suites"]), "test_suites_all": [suite['scoring_method'] for suite in suites["test_suites"]]}}, USER_ID)
    return suites

@app.get("/api/v3/bench/test_suites/{test_suite_id}")
def test_suite(request: Request, test_suite_id: uuid.UUID, page: int = 1, page_size: int = 5):
    client = LocalBenchClient(root_dir=SERVER_ROOT_DIR)
    suite_resp = client.get_test_suite(test_suite_id=str(test_suite_id), page=page, page_size=page_size).json()
    suite = json.loads(suite_resp)
    suite["scoring_method"] = suite["scoring_method"]["name"]
    return suite


@app.get("/api/v3/bench/test_suites/{test_suite_id}/runs")
def test_runs(request: Request, test_suite_id: uuid.UUID, page: int = 1, page_size: int = 5, sort: Optional[str] = None):
    client = LocalBenchClient(root_dir=SERVER_ROOT_DIR)
    run_resp = client.get_runs_for_test_suite(test_suite_id=str(test_suite_id), page=page, page_size=page_size, sort=sort).json()
    suite_resp = client.get_test_suite(test_suite_id=str(test_suite_id))
    runs = json.loads(run_resp)
    send_event({"event_type": "test_runs_load", "event_properties": {"test_runs_all": [str(run["created_at"]) for run in runs["test_runs"]], "scoring_method_real": suite_resp.scoring_method.name}}, USER_ID)
    return runs


@app.get("/api/v3/bench/test_suites/{test_suite_id}/runs/summary")
def test_suite_summary(request: Request, test_suite_id: uuid.UUID, page: int = 1, page_size: int = 5, run_id: Optional[uuid.UUID] = None):
    client = LocalBenchClient(root_dir=SERVER_ROOT_DIR)
    summary_resp = client.get_summary_statistics(test_suite_id=str(test_suite_id), page=page, page_size=page_size, run_id=str(run_id) if run_id is not None else None).json()
    summary = json.loads(summary_resp)
    return summary


@app.get("/api/v3/bench/test_suites/{test_suite_id}/runs/{run_id}")
def test_run_results(request: Request, test_suite_id: uuid.UUID, run_id: uuid.UUID, page: int = 1, page_size: int = 5):
    client = LocalBenchClient(root_dir=SERVER_ROOT_DIR)
    run_resp = client.get_test_run(test_suite_id=str(test_suite_id), test_run_id=str(run_id), page=page, page_size=page_size).json(by_alias=True)
    run = json.loads(run_resp)
    run["metadata"] = None
    return run


app.mount("/", StaticFiles(directory=FRONT_END_DIRECTORY, html=True), name="frontend")


def run():
    # parser needs to go in this function for compatibility with packaging
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', required=False, help="optional directory override to run as root for bench server ")

    group = parser.add_mutually_exclusive_group()
    group.add_argument('--enable_push_usage_data', help="Enable sending anonymous usage data", required=False, action='store_true')
    group.add_argument('--disable_push_usage_data', help="Disable sending anonymous usage data", required=False, action='store_true')
    args = parser.parse_args()
    if args.enable_push_usage_data:
        persist_usage_data(True)
        return
    if args.disable_push_usage_data:
        persist_usage_data(False)
        return

    global SERVER_ROOT_DIR
    # TODO: how to maintain state on fast api server
    default_root_dir = _bench_root_dir()
    if args.directory:
        default_root_dir = args.directory
    SERVER_ROOT_DIR = Path(default_root_dir).resolve()

    global USER_ID
    config = get_or_persist_id()
    set_track_usage_data(config)
    USER_ID = config.user_id

    uvicorn.run("arthur_bench.server.run_server:app", host="127.0.0.1", port=8000, log_level="info")


if __name__  == '__main__':
   run()