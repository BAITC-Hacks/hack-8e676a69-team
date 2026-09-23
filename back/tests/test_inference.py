"""Real CatBoost integration, offline weather fixtures, unchanged frontend HTTP API."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
import shutil
import sys
import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from back.config import Settings
from back.dataset import DatasetSeries, WeatherValue
from back.inputs import InputBuilder, publish_csv
from back.main import create_app
from back.schemas import TicketRequest, UTC
from inference.features import features
from inference.forecast import ForecastPipeline, prepare_frame
from inference.supervisor import Supervisor, claim


class Datasets:
    def __init__(self, values=None):
        self.series = DatasetSeries(values or {})

    def get(self, turbine):
        return self.series


class Weather:
    async def weather_for(self, turbine, timestamps, **kwargs):
        # Deliberately fake weather; only the ML models and API are real.
        return {t: WeatherValue(6+3*np.sin(t.hour/4), 10+np.cos(t.hour/8), 'fixture_forecast') for t in timestamps}


def config(tmp_path, **kwargs):
    return Settings(tickets_dir=tmp_path/'tickets', datasets_dir=tmp_path/'datasets',
        cache_dir=tmp_path/'cache', web_dist=tmp_path/'no-web', **kwargs)


def rows(settings, turbine='A', days=7, datasets=None):
    request = TicketRequest(turbine_id=turbine, horizon_start='2026-02-05', history_days=days)
    return asyncio.run(InputBuilder(settings, datasets or Datasets(), Weather()).build(
        request, now=datetime(2026,9,23,tzinfo=UTC)))


def assert_response(payload):
    assert set(payload) == {'series'}
    assert len(payload['series']) == 1
    series = payload['series'][0]
    assert set(series) == {'id','name','color','points'}
    assert (series['id'], series['name'], series['color']) == ('agent-ctboost', 'Main forecast', '#157a65')
    assert len(series['points']) == 48
    assert [p['hour'] for p in series['points']] == list(range(48))
    assert all(set(p) == {'hour','value'} and 0 <= p['value'] <= 1 for p in series['points'])
    json.dumps(payload, allow_nan=False)


@pytest.mark.parametrize('turbine', ['A','B'])
@pytest.mark.parametrize('step', [1,3,6,12])
def test_backend_csv_matches_model_and_response(turbine, step, tmp_path):
    settings = config(tmp_path, sampling_step=step)
    frame = pd.DataFrame(rows(settings, turbine, days=1))
    x, names, info = prepare_frame(frame, settings.turbine_timezone)
    assert x.shape == (48,80)
    assert not any('power' in n or 'efficiency' in n for n in names)
    assert len(frame) == (168+48)*step  # minimum history padded without frontend changes
    assert info['history'].index.min() == pd.Timestamp('2026-01-29')
    assert info['history'].index.max() == pd.Timestamp('2026-02-04 23:00')
    assert info['future'].index.min() == pd.Timestamp('2026-02-05')
    assert info['future'].index.max() == pd.Timestamp('2026-02-06 23:00')
    # Calendar must use site-local midnight, not the previous day's 19:00 UTC.
    assert x[0,names.index('day_sin')] == 0
    assert x[0,names.index('day_cos')] == 1
    path = tmp_path/'data.csv'
    frame.to_csv(path,index=False)
    pipeline = ForecastPipeline(timezone=settings.turbine_timezone)
    first = pipeline.infer(path)
    assert_response(first)
    frame['power'] = 99999
    frame['efficiency'] = 'DO_NOT_USE'
    frame.to_csv(path,index=False)
    assert pipeline.infer(path) == first


def test_dataset_hourly_mean_matches_training_and_history_stops_before_origin(tmp_path):
    settings = config(tmp_path, turbine_timezone='UTC')
    origin = datetime(2026,2,5,tzinfo=UTC)
    values = {}
    for i in range((168+48)*6):
        t = origin-timedelta(hours=168)+timedelta(minutes=10*i)
        values[t] = WeatherValue(float(i%6), float(2*(i%6)), 'dataset')
    frame = pd.DataFrame(rows(settings,datasets=Datasets(values)))
    _, _, info = prepare_frame(frame,'UTC')
    np.testing.assert_allclose(info['history'].to_numpy(), np.tile([2.5,5],(168,1)))
    np.testing.assert_allclose(info['future'].to_numpy(), np.tile([2.5,5],(48,1)))
    changed = frame.copy()
    changed.loc[changed.phase=='forecast','wind_speed_ms'] = 30
    _, _, after = prepare_frame(changed,'UTC')
    pd.testing.assert_frame_equal(info['history'],after['history'])
    assert (after['future'].wind_speed_ms == 30).all()


def test_excess_history_ignored_and_missing_hours_not_filled(tmp_path):
    settings = config(tmp_path,turbine_timezone='UTC')
    frame = pd.DataFrame(rows(settings,days=30))
    x, _, info = prepare_frame(frame,'UTC')
    first_needed = '2026-01-29T00:00:00+00:00'
    frame.loc[frame.timestamp < first_needed,'wind_speed_ms'] = 999
    np.testing.assert_array_equal(x, prepare_frame(frame,'UTC')[0])
    frame = frame[~frame.timestamp.str.startswith('2026-02-04T12:')]
    after = prepare_frame(frame,'UTC')[2]
    assert after['history'].loc['2026-02-04 12:00'].isna().all()


@pytest.mark.parametrize('problem', ['duplicate','missing_future','phase','naive','negative','mixed_turbines','before_training'])
def test_bad_csv_is_rejected(problem,tmp_path):
    frame = pd.DataFrame(rows(config(tmp_path)))
    if problem == 'duplicate': frame = pd.concat([frame,frame.iloc[-1:]])
    if problem == 'missing_future': frame = frame.iloc[:-1]
    if problem == 'phase': frame.loc[0,'phase'] = 'forecast'
    if problem == 'naive': frame['timestamp'] = frame.timestamp.str.replace('+05:00','',regex=False)
    if problem == 'negative': frame.loc[0,'wind_speed_ms'] = -1
    if problem == 'mixed_turbines': frame.loc[0,'turbine_id'] = 'B'
    if problem == 'before_training': frame['timestamp'] = (pd.to_datetime(frame.timestamp)-pd.Timedelta(days=40)).map(lambda v:v.isoformat())
    with pytest.raises(ValueError): prepare_frame(frame,'Asia/Almaty')


def test_partial_files_claims_restart_and_atomic_response(tmp_path):
    root = tmp_path/'tickets'
    root.mkdir()
    folder = root/'ticket'
    folder.mkdir()
    (folder/'data.csv.tmp').write_text('unfinished')
    settings = config(tmp_path)
    worker = Supervisor(ForecastPipeline(),root)
    assert worker.run_once() == []
    publish_csv(folder,rows(settings))
    with claim(folder) as acquired:
        assert acquired
        assert worker.run_once() == [('ticket','skipped')]
    # Leftover lock inode is safe after release/restart.
    assert worker.run_once() == [('ticket','done')]
    assert_response(json.loads((folder/'response.json').read_text()))
    assert not (folder/'response.json.tmp').exists()
    assert worker.run_once() == []
    assert Supervisor(ForecastPipeline(),root).run_once() == []


def test_two_workers_infer_ticket_only_once(tmp_path):
    root = tmp_path/'tickets'
    folder = root/'shared'
    folder.mkdir(parents=True)
    (folder/'data.csv').write_text('fixture')
    class Slow:
        calls = 0
        def infer(self,path):
            self.calls += 1
            time.sleep(.05)
            return {'series':[]}
    pipeline=Slow()
    first,second=Supervisor(pipeline,root),Supervisor(pipeline,root)
    with ThreadPoolExecutor(2) as pool:
        futures=[pool.submit(w.run_once) for w in [first,second]]
        [f.result() for f in futures]
    assert pipeline.calls == 1


def test_bad_ticket_returns_frontend_error_not_timeout(tmp_path):
    folder=tmp_path/'tickets'/'bad'
    folder.mkdir(parents=True)
    (folder/'data.csv').write_text('wrong,header\n1,2\n')
    worker=Supervisor(ForecastPipeline(),folder.parent)
    assert worker.run_once() == [('bad','error')]
    response=json.loads((folder/'response.json').read_text())
    assert response['error']['code']=='inference_failed'
    assert isinstance(response['error']['message'],str)


@pytest.mark.parametrize('turbine',['A','B'])
def test_real_model_embedded_http_ticket_roundtrip(tmp_path,turbine):
    settings=config(tmp_path,inference_enabled=True)
    with TestClient(create_app(settings,datasets=Datasets(),weather=Weather())) as client:
        created=client.post('/api/tickets',json={'turbine_id':turbine,'horizon_start':'2026-02-05','history_days':1})
        assert created.status_code==202
        ticket=created.json()['ticket_id']
        assert created.json()['input']['history_days']==7
        for _ in range(300):
            result=client.get(f'/api/tickets/{ticket}')
            if result.status_code!=202: break
            time.sleep(.01)
        assert result.status_code==200,result.text
        assert_response(result.json())
        assert result.content==(settings.tickets_dir/ticket/'response.json').read_bytes()
        assert not (settings.tickets_dir/ticket/'request.json').exists()


def test_standalone_worker_cli_then_backend_poll(tmp_path):
    settings=config(tmp_path,inference_enabled=False)
    with TestClient(create_app(settings,datasets=Datasets(),weather=Weather())) as client:
        ticket=client.post('/api/tickets',json={'turbine_id':'A','horizon_start':'2026-02-05'}).json()['ticket_id']
        folder=settings.tickets_dir/ticket
        for _ in range(200):
            if (folder/'data.csv').exists(): break
            time.sleep(.01)
        assert client.get(f'/api/tickets/{ticket}').status_code==202
        result=subprocess.run([sys.executable,'-m','inference.main','--tickets-dir',str(settings.tickets_dir),
            '--timezone',settings.turbine_timezone],cwd=Path(__file__).resolve().parents[2],capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stderr
        response=client.get(f'/api/tickets/{ticket}')
        assert response.status_code==200
        assert_response(response.json())


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js unavailable')
def test_actual_response_is_accepted_by_unchanged_frontend_parser(tmp_path):
    path=tmp_path/'data.csv'
    pd.DataFrame(rows(config(tmp_path))).to_csv(path,index=False)
    payload=ForecastPipeline().infer(path)
    module=(Path(__file__).resolve().parents[2]/'frontend/src/utils/backendForecast.js').as_uri()
    script=f"""
import {{ normalizeForecastResponse }} from {json.dumps(module)};
import {{ readFileSync }} from 'node:fs';
const result = normalizeForecastResponse(JSON.parse(readFileSync(0, 'utf8')), {{}});
if (result.length !== 1 || result[0].id !== 'agent-ctboost' || result[0].color !== '#157a65'
    || result[0].points.length !== 48 || result[0].points[0].hour !== 0
    || result[0].points[47].hour !== 47) throw new Error('Frontend contract mismatch');
console.log('Frontend accepted all 48 real-model points');
"""
    result=subprocess.run(['node','--input-type=module','-e',script],input=json.dumps(payload),
                          capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr


def test_no_source_data_returns_explicit_backend_error(tmp_path):
    # Capture the actual current-workspace startup prerequisite in a regression test.
    with TestClient(create_app(config(tmp_path),weather=Weather())) as client:
        result=client.get('/api/bootstrap')
        assert result.status_code==503
        assert result.json()['error']['code']=='dataset_configuration'
