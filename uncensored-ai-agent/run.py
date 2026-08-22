#!/usr/bin/env python3
"""
הרצה פשוטה של השרת
"""
import uvicorn
import os

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        reload_dirs=["app", "templates", "static"]
    )
