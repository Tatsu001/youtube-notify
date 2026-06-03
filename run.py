#!/usr/bin/env python3
"""ローカル/CI共通のエントリポイント。

使い方:
    python run.py
環境変数:
    GEMINI_API_KEY                Google AI Studio のAPIキー（生成に必須）
    LINE_CHANNEL_ACCESS_TOKEN     LINE Messaging API のチャネルアクセストークン（通知に使用）
"""
from src.main import main

if __name__ == "__main__":
    main()
