from pathlib import Path
import sys
import pytest
pytest.importorskip("flask")
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'application'/'src'))
from isala_ocr.training.webui import create_web_app

def test_webui_routes(tmp_path):
    workspace=tmp_path/'training'/'workspace'; models=tmp_path/'models'; output=tmp_path/'output'; project=tmp_path/'project'
    project.mkdir(parents=True); (project/'VERSION').write_text('3.5.6')
    app=create_web_app(workspace,models_root=models,output_root=output,project_root=project)
    client=app.test_client()
    for route in ('/','/documents','/review','/training','/activation','/health'):
        assert client.get(route).status_code==200

def test_job_submission(tmp_path):
    workspace=tmp_path/'training'/'workspace'; project=tmp_path/'project'; project.mkdir(parents=True); (project/'VERSION').write_text('3.5.6')
    app=create_web_app(workspace,models_root=tmp_path/'models',output_root=tmp_path/'output',project_root=project)
    response=app.test_client().post('/jobs',data={'action_id':'10'},follow_redirects=False)
    assert response.status_code==302
    assert list((workspace/'webui'/'jobs'/'pending').glob('*.json'))
