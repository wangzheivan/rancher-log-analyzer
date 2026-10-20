#!/usr/bin/env python3
"""WSL entry point; all service configuration is provided by environment variables."""
import uvicorn

if __name__ == '__main__':
    uvicorn.run('backend.app:app', host='127.0.0.1', port=8080, workers=1)
