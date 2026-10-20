#!/usr/bin/env python3
"""Package an extracted bundle without changing its original files."""
import argparse
from pathlib import Path
import tarfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.parsers.bundle import discover

parser = argparse.ArgumentParser()
parser.add_argument('--source', default='node22-2026-10-20_14_18_53')
parser.add_argument('--output', default='/tmp/rancher-sample.tar.gz')
args = parser.parse_args()
roots = discover(args.source)
if len(roots) != 1:
    parser.error('source must contain exactly one bundle')
output = Path(args.output).resolve()
if output.is_relative_to(roots[0]):
    parser.error('output must be outside the original bundle')
with tarfile.open(output, 'w:gz') as archive:
    archive.add(roots[0], arcname=roots[0].name)
print(output)
