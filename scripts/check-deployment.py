#!/usr/bin/env python3
"""Refuse to overwrite a pre-existing installation owned by somebody else."""
import json
import os
import subprocess
import sys
name='rancher-log-analyzer'
context=os.environ.get('KUBE_CONTEXT')
if not context:
    sys.exit('Set KUBE_CONTEXT explicitly before checking deployment ownership.')
command=['kubectl','--context',context,'--request-timeout=15s','--namespace',name,'get','deployment,service',name,'--ignore-not-found','-o','json']
result=subprocess.run(command,capture_output=True,text=True)
if result.returncode:
    print('Unable to verify deployment ownership; no changes were made.',file=sys.stderr)
    sys.exit(result.returncode)
for item in json.loads(result.stdout).get('items',[]):
    meta=item['metadata'];annotations=meta.get('annotations',{})
    if annotations.get('meta.helm.sh/release-name')!=name or annotations.get('meta.helm.sh/release-namespace')!=name or meta.get('labels',{}).get('app.kubernetes.io/name')!=name:
        sys.exit('An unrelated resource already uses the target name. Refusing to deploy.')
print('Deployment ownership check passed.')
