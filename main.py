"""项目入口：uvicorn matcher.main:app --port 8000 亦可直接 `python main.py`。"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("matcher.main:app", host="127.0.0.1", port=8000, reload=False)
