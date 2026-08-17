from pathlib import Path
import sys
import pytest
pytest.importorskip("flask")
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'application'/'src'))
from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.webui import create_web_app

def test_smart_review_accepts_only_safe_dynamic_samples(tmp_path):
    workspace=tmp_path/'workspace'; db=TrainingDatabase(workspace/'samples.sqlite3')
    base={'profile':'p','field_key':'f','field_label':'F','crop_path':'c.png','raw_variant':'v','image_width':100,'image_height':100,'roi_x1':1,'roi_y1':1,'roi_x2':10,'roi_y2':10,'locator_label_text':'F','locator_version':'v','crop_sha256':'x'}
    db.upsert_sample({**base,'sample_id':'s1','source_id':'a','raw_ocr':'12.3','raw_confidence':.995,'extraction_method':'dynamic_token_box','locator_confidence':.95})
    db.upsert_sample({**base,'sample_id':'s2','source_id':'b','raw_ocr':'12.4','raw_confidence':.5,'extraction_method':'dynamic_token_box','locator_confidence':.95,'crop_sha256':'y'})
    db.upsert_sample({**base,'sample_id':'s3','source_id':'c','raw_ocr':'12.5','raw_confidence':.999,'extraction_method':'dynamic_token_box','locator_confidence':.99,'crop_sha256':'z'})
    db.review_roi('s1','correct')
    db.review_roi('s2','correct')
    project=tmp_path/'project'; project.mkdir(); (project/'VERSION').write_text('3.5.6')
    profile=tmp_path/'profile.yaml'; profile.write_text('fields:\n- key: f\n  range: [0, 100]\n')
    config=tmp_path/'app.yaml'; config.write_text(f'profile: {profile.as_posix()}\n')
    app=create_web_app(workspace,models_root=tmp_path/'models',output_root=tmp_path/'output',project_root=project,config_path=config)
    app.test_client().post('/review/smart-apply',data={'threshold':'0.98','qa_percent':'0'})
    assert db.get('s1')['status']=='accepted'
    assert db.get('s2')['status']=='pending'
    assert db.get('s3')['status']=='pending'
