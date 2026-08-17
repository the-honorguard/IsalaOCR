from __future__ import annotations
import argparse
from .webui import create_web_app

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--workspace",default="/training/workspace")
    p.add_argument("--models",default="/models")
    p.add_argument("--output",default="/output")
    p.add_argument("--project",default="/project")
    p.add_argument("--config",default="/app/config/app.yaml")
    p.add_argument("--host",default="0.0.0.0")
    p.add_argument("--port",type=int,default=8088)
    a=p.parse_args()
    from waitress import serve
    serve(create_web_app(a.workspace,models_root=a.models,output_root=a.output,project_root=a.project,config_path=a.config),host=a.host,port=a.port,threads=8)
    return 0

if __name__=="__main__": raise SystemExit(main())
